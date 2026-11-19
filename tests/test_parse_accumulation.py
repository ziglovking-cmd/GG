"""Повторные проходы дополняют одну базу, а в прирост входят только новые ID."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from telethon.tl.types import User

from app import db, parsing
from app.api import chats

CHAT = 1934743169


def person(uid, username=None):
    return User(id=uid, access_hash=uid * 100, first_name="user",
                username=username or "person%d" % uid, bot=False)


class Client:
    def __init__(self, ids, reactors=()):
        self.ids = ids
        self.reactors = reactors

    async def is_user_authorized(self):
        return True

    async def iter_messages(self, entity, limit=None, offset_id=0, wait_time=1):
        entries = list(enumerate(self.ids, 1))[::-1]
        if offset_id:
            entries = [(i, uid) for i, uid in entries if i < offset_id]
        if limit is not None:
            entries = entries[:limit]
        for i, uid in entries:
            yield SimpleNamespace(id=i, sender=person(uid), reactions=bool(self.reactors))

    async def iter_participants(self, entity, limit=None, search=None):
        for uid in self.ids[:limit]:
            yield person(uid)

    async def __call__(self, request):
        return SimpleNamespace(users=[person(uid) for uid in self.reactors])


class AccumulatingParseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        db.DB_PATH = Path(self.directory.name) / "test.db"
        db.connect()
        self.waiter = patch.object(parsing, "_wait", AsyncMock())
        self.waiter.start()

    def tearDown(self):
        self.waiter.stop()
        parsing.JOBS.clear()
        parsing.ACTIVE.clear()
        db._conn.close()
        db._conn = None
        db.DB_PATH = self.old_path
        self.directory.cleanup()

    def ids(self):
        return {r["user_id"] for r in db.q("SELECT user_id FROM members WHERE chat_id=?", (CHAT,))}

    async def parse(self, client, account=1, sources=None):
        entity = SimpleNamespace(id=CHAT, title="Авитологи", username=None)
        job_id = parsing.new_job("parse", "Авитологи")
        with patch.object(parsing.accounts, "get_client", AsyncMock(return_value=client)), \
                patch.object(parsing, "resolve_chat", AsyncMock(return_value=entity)):
            await parsing.run_parse(job_id, account, str(CHAT), sources or ["history"], False, None, None, None)
        return dict(parsing.JOBS[job_id])

    async def test_second_pass_counts_only_new_and_retains_absent_old_users(self):
        first = await self.parse(Client([1, 2, 2, 3]))
        second = await self.parse(Client([2, 3, 4, 4]))
        self.assertEqual((first["found"], first["added"], first["total"]), (3, 3, 3))
        self.assertEqual((second["found"], second["added"], second["total"]), (1, 1, 4))
        self.assertEqual(self.ids(), {1, 2, 3, 4})

    async def test_repeated_pass_reports_zero_new_even_after_database_reconnect(self):
        await self.parse(Client([1, 2, 3]))
        db._conn.close()
        db._conn = None
        repeated = await self.parse(Client([3, 2, 1]))
        self.assertEqual((repeated["found"], repeated["added"], repeated["total"]), (0, 0, 3))

    async def test_sources_share_one_unique_new_counter(self):
        result = await self.parse(Client([1, 2], reactors=[2, 3]), sources=["participants", "history", "reactions"])
        self.assertEqual((result["found"], result["added"], result["total"]), (3, 3, 3))
        repeated = await self.parse(Client([1, 2], reactors=[2, 3]), sources=["participants", "history", "reactions"])
        self.assertEqual((repeated["found"], repeated["added"], repeated["total"]), (0, 0, 3))

    async def test_other_account_updates_hash_but_does_not_recount_user(self):
        await self.parse(Client([1, 2]), account=1)
        result = await self.parse(Client([1, 2]), account=2)
        self.assertEqual(result["added"], 0)
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM hashes WHERE account_id=2")["n"], 2)

    async def test_existing_user_can_change_username_without_becoming_new(self):
        self.assertEqual(parsing.save_users(CHAT, 1, [person(1, "oldname")], "history"), 1)
        self.assertEqual(parsing.save_users(CHAT, 1, [person(1, "newname")], "history"), 0)
        self.assertEqual(self.ids(), {1})
        self.assertEqual(db.q1("SELECT username FROM members WHERE user_id=1")["username"], "newname")

    async def test_interleaved_batch_saves_count_each_id_once(self):
        a = {"added": 0}
        b = {"added": 0}
        parsing._save_for_job(a, CHAT, 1, [person(1), person(2)], "history")
        parsing._save_for_job(b, CHAT, 2, [person(2), person(3)], "participants")
        parsing._save_for_job(a, CHAT, 1, [person(3), person(4)], "history")
        self.assertEqual((a["added"], b["added"]), (3, 1))
        self.assertEqual(self.ids(), {1, 2, 3, 4})

    async def test_concurrent_writers_cannot_both_count_the_same_user(self):
        def save(account):
            return parsing.save_users(CHAT, account, [person(99)], "history")
        with ThreadPoolExecutor(max_workers=2) as pool:
            additions = list(pool.map(save, [1, 2]))
        self.assertEqual(sum(additions), 1)
        self.assertEqual(self.ids(), {99})

    async def test_member_and_hash_updates_rollback_together(self):
        row = (CHAT, 7, "person7", "user", None, None, 0, 0, 0, "", 1, "history", 1)
        with self.assertRaises(sqlite3.IntegrityError):
            db.save_parsed_members(CHAT, [row], [(None, 7, 700, 1)])
        self.assertEqual(self.ids(), set())

    async def test_all_accounts_sum_new_users_instead_of_taking_largest_run(self):
        parent_id = parsing.new_job("parse-all", "Авитологи")
        entity = SimpleNamespace(id=CHAT, title="Авитологи", username=None)
        clients = {1: Client([1, 2]), 2: Client([2, 3])}
        with patch.object(parsing.accounts, "get_client", AsyncMock(side_effect=lambda account: clients[account])), \
                patch.object(parsing, "resolve_chat", AsyncMock(return_value=entity)):
            await parsing.run_parse_all(parent_id, [1, 2], str(CHAT), ["history"], False, None, None, None, gap=0)
        job = parsing.JOBS[parent_id]
        self.assertEqual((job["found"], job["added"], job["total"]), (3, 3, 3))

    async def test_jobs_endpoint_includes_live_child_progress_without_mutating_parent(self):
        parent = parsing.new_job("parse-all", "Авитологи")
        child = parsing.new_job("parse", "Авитологи")
        parsing.JOBS[parent].update(added=3, found=3, current_sub=child)
        parsing.JOBS[child].update(added=2, found=2, total=105)
        result = next(r for r in chats.jobs() if r["id"] == parent)
        self.assertEqual((result["found"], result["added"], result["total"]), (5, 5, 105))
        self.assertEqual(parsing.JOBS[parent]["added"], 3)


if __name__ == "__main__":
    unittest.main()
