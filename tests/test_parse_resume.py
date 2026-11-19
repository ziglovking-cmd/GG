import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from telethon.errors import FloodWaitError
from telethon.tl.types import User

from app import db, parsing

CHAT_ID = 777
ACCOUNT_ID = 1


def user(uid: int) -> User:
    return User(id=uid, access_hash=uid * 10, username="u%d" % uid, first_name="x", bot=False)


class Msg:
    def __init__(self, msg_id: int, sender: User, reactions=None):
        self.id = msg_id
        self.sender = sender
        self.reactions = reactions


class FakeIter:
    def __init__(self, client, limit, offset_id):
        self.client = client
        self.limit = limit
        self.offset_id = offset_id
        self.total = None

    def __aiter__(self):
        return self._run()

    async def _run(self):
        self.client.calls.append(self.offset_id)
        if self.client.always_fail:
            self.client.connected = False
            raise ConnectionError("Cannot send requests while disconnected")
        msgs = [m for m in self.client.messages if not self.offset_id or m.id < self.offset_id]
        if self.limit is not None:
            msgs = msgs[:self.limit]
        self.total = len(self.client.messages)
        for m in msgs:
            error = self.client.fail_at.pop(m.id, None)
            if error is not None:
                if isinstance(error, ConnectionError):
                    self.client.connected = False
                raise error
            if self.client.stop_at and self.client.stop_at[1] == m.id:
                # «Остановить» нажали, пока обрабатывается это сообщение.
                self.client.stop_at[0]["stop_requested"] = True
            yield m


class FakeClient:
    def __init__(self, count=250, fail_at=None, reactions=(), reaction_fail=None):
        self.messages = [
            Msg(i, user(i % 5 + 1), reactions=True if i in reactions else None)
            for i in range(count, 0, -1)
        ]
        self.fail_at = dict(fail_at or {})
        self.reaction_fail = dict(reaction_fail or {})
        self.calls = []
        self.reaction_calls = []
        self.connected = True
        self.connects = 0
        self.always_fail = False
        self.stop_at = None

    def iter_messages(self, entity, limit=None, offset_id=0, wait_time=None):
        return FakeIter(self, limit, offset_id)

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connects += 1
        self.connected = True

    async def is_user_authorized(self):
        return True

    async def __call__(self, request):
        self.reaction_calls.append(request.id)
        error = self.reaction_fail.pop(request.id, None)
        if error is not None:
            raise error
        return SimpleNamespace(users=[user(100 + request.id)])


def flood(seconds: int) -> FloodWaitError:
    return FloodWaitError(request=None, capture=seconds)


class ParseResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db.connect()
        self.wait = AsyncMock()
        self.patcher = patch.object(parsing, "_wait", self.wait)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        parsing.JOBS.clear()
        parsing.ACTIVE.clear()
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        self.tmp.cleanup()

    def job(self):
        return {"title": "Чат", "processed": 0, "found": 0}

    async def history(self, client, job=None, limit=None):
        await parsing._collect_history(client, None, job or self.job(), CHAT_ID, ACCOUNT_ID, limit)

    def cursor(self, source="history"):
        return db.row_to_dict(db.q1(
            "SELECT offset_id, scanned FROM parse_cursors WHERE chat_id=? AND account_id=? AND source=?",
            (CHAT_ID, ACCOUNT_ID, source)))

    def msg_total(self):
        return db.q1("SELECT SUM(msg_count) s FROM members WHERE chat_id=?", (CHAT_ID,))["s"]

    def events(self, pattern):
        return db.q("SELECT message FROM events WHERE message LIKE ?", (pattern,))

    async def test_short_flood_wait_continues_from_same_message(self):
        client = FakeClient(fail_at={150: flood(30)})
        job = self.job()
        await self.history(client, job)

        self.assertEqual(client.calls, [0, 151])
        self.assertEqual(job["processed"], 250)
        self.assertEqual(self.msg_total(), 250)
        self.wait.assert_any_await(job, 32)
        self.assertIsNone(self.cursor())
        self.assertTrue(self.events("%FloodWait 30 с%"))

    async def test_long_flood_wait_pauses_and_next_run_resumes(self):
        client = FakeClient(fail_at={150: flood(3600)})
        with self.assertRaises(parsing.ParsePaused):
            await self.history(client)

        self.assertEqual(self.cursor(), {"offset_id": 151, "scanned": 100})
        self.assertEqual(db.q1("SELECT COUNT(*) c FROM members")["c"], 5)
        self.wait.assert_not_awaited()

        job = self.job()
        await self.history(client, job)
        self.assertEqual(client.calls, [0, 151])
        self.assertEqual(job["processed"], 150)
        self.assertIsNone(self.cursor())
        self.assertTrue(self.events("Продолжаю история сообщений%#151%"))

    async def test_connection_drop_reconnects_and_continues(self):
        client = FakeClient(fail_at={100: ConnectionError("Cannot send requests while disconnected")})
        job = self.job()
        await self.history(client, job)

        self.assertEqual(client.calls, [0, 101])
        self.assertEqual(client.connects, 1)
        self.assertEqual(job["processed"], 250)
        self.wait.assert_any_await(job, parsing.RECONNECT_DELAYS[0])

    async def test_connection_never_returns_pauses_after_all_retries(self):
        client = FakeClient()
        client.always_fail = True
        with self.assertRaises(parsing.ParsePaused) as caught:
            await self.history(client)

        self.assertIn("Нет связи с Telegram", str(caught.exception))
        self.assertEqual(len(client.calls), len(parsing.RECONNECT_DELAYS) + 1)
        self.assertEqual([c.args[1] for c in self.wait.await_args_list], list(parsing.RECONNECT_DELAYS))

    async def test_limit_is_respected_and_cursor_cleared(self):
        client = FakeClient()
        job = self.job()
        await self.history(client, job, limit=120)

        self.assertEqual(job["processed"], 120)
        self.assertEqual(client.calls, [0])
        self.assertIsNone(self.cursor())

    async def test_restart_keeps_saved_progress(self):
        client = FakeClient(fail_at={100: asyncio.CancelledError()})
        with patch.object(parsing, "SAVE_EVERY", 50):
            with self.assertRaises(asyncio.CancelledError):
                await self.history(client)

        self.assertEqual(self.cursor(), {"offset_id": 101, "scanned": 150})
        self.assertEqual(self.msg_total(), 150)

    async def test_stop_button_saves_place(self):
        client = FakeClient()
        job = self.job()
        client.stop_at = (job, 200)
        with self.assertRaises(parsing.ParsePaused) as caught:
            await self.history(client, job)

        self.assertIn("Остановлено вручную", str(caught.exception))
        self.assertEqual(self.cursor(), {"offset_id": 200, "scanned": 51})

    async def test_reactions_flood_wait_retries_same_message(self):
        client = FakeClient(count=20, reactions={5, 10, 15}, reaction_fail={10: flood(5)})
        job = self.job()
        await parsing._collect_reactions(client, None, job, CHAT_ID, ACCOUNT_ID, None)

        self.assertEqual(client.reaction_calls, [15, 10, 10, 5])
        reactors = {r["user_id"] for r in db.q(
            "SELECT user_id FROM members WHERE chat_id=? AND sources LIKE '%reactions%'", (CHAT_ID,))}
        self.assertEqual(reactors, {105, 110, 115})
        self.assertIsNone(self.cursor("reactions"))

    async def test_run_parse_reports_paused_and_counts_new_members(self):
        client = FakeClient(fail_at={150: flood(3600)})
        entity = SimpleNamespace(id=CHAT_ID, title="Чат", username=None)
        job_id = parsing.new_job("parse", "Чат")
        with patch.object(parsing.accounts, "get_client", AsyncMock(return_value=client)), \
                patch.object(parsing, "resolve_chat", AsyncMock(return_value=entity)):
            await parsing.run_parse(job_id, ACCOUNT_ID, str(CHAT_ID), ["history"], False, None, None, 100)

        job = parsing.JOBS[job_id]
        self.assertEqual(job["status"], "paused")
        self.assertEqual(job["added"], 5)
        self.assertIn("продолжу с этого места", job["stage"])
        self.assertEqual(parsing.ACTIVE, set())


if __name__ == "__main__":
    unittest.main()
