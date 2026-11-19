import asyncio
import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import db, preflight, reporter


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "app.db"
        self.old_connection = db._conn
        db._conn = None
        self.db_path_patch = patch.object(db, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        db.connect()

    def tearDown(self):
        if db._conn is not None:
            db._conn.close()
        db._conn = self.old_connection
        self.db_path_patch.stop()
        self.directory.cleanup()

    def test_schema_contains_persistent_preflight_fields(self):
        campaign_columns = {
            row[1] for row in db.q("PRAGMA table_info(campaigns)")
        }
        target_columns = {
            row[1] for row in db.q("PRAGMA table_info(targets)")
        }
        self.assertIn("preflight_status", campaign_columns)
        self.assertIn("resolved_user_id", target_columns)
        self.assertIn("preflight_checked_at", target_columns)

    def test_preflight_start_endpoint_runs_inside_event_loop(self):
        from app.api import campaigns

        self.assertTrue(inspect.iscoroutinefunction(campaigns.start_campaign_preflight))

    def test_validated_real_id_is_saved_and_used_for_confirmation(self):
        campaign_id = db.ex(
            "INSERT INTO campaigns (name,target_chat_id,status,created_at) VALUES (?,?,?,?)",
            ("Проверка", 100, "draft", 1),
        )
        target_id = db.ex(
            "INSERT INTO targets (campaign_id,user_id,username,status) VALUES (?,?,?,?)",
            (campaign_id, -123, "example", "pending"),
        )
        preflight._target_mark(target_id, "valid", None, 777)
        row = db.row_to_dict(db.q1("SELECT * FROM targets WHERE id=?", (target_id,)))
        self.assertEqual(row["resolved_user_id"], 777)
        self.assertEqual(row["preflight_status"], "valid")
        self.assertTrue(reporter._present(row, ({"777"}, set())))

    def test_target_without_username_requires_hash_from_selected_account(self):
        campaign_id = db.ex(
            "INSERT INTO campaigns (name,target_chat_id,status,created_at) VALUES (?,?,?,?)",
            ("Проверка", 100, "draft", 1),
        )
        target = {
            "id": 1,
            "campaign_id": campaign_id,
            "user_id": 777,
            "username": None,
        }
        result = preflight._known_target(target, [3])
        self.assertEqual(result[0], "no_hash")
        db.ex(
            "INSERT INTO hashes (account_id,user_id,access_hash,updated_at) VALUES (?,?,?,?)",
            (3, 777, 999, 1),
        )
        result = preflight._known_target(target, [3])
        self.assertEqual(result[0], "valid")
        self.assertEqual(result[2], 777)

    def test_account_progress_is_persisted_after_each_completed_check(self):
        job = preflight._blank_job(9, 3, 0)
        snapshots = []

        async def fake_check(_campaign, account_id, _semaphore):
            await asyncio.sleep({10: 0.03, 20: 0.01, 30: 0.02}[account_id])
            return preflight._account_result(
                account_id,
                "Аккаунт %d" % account_id,
                "ready" if account_id != 30 else "technical",
                "ok",
                account_id != 30,
            )

        def remember(current):
            snapshots.append((
                current["accounts"]["checked"],
                current["accounts"]["ready"],
            ))

        with patch.object(preflight, "_check_account", side_effect=fake_check), \
                patch.object(preflight, "_persist", side_effect=remember):
            results = asyncio.run(preflight._run_account_checks({}, [10, 20, 30], job))

        self.assertEqual(len(results), 3)
        self.assertEqual([item["account_id"] for item in results], [10, 20, 30])
        self.assertEqual([item[0] for item in snapshots], [1, 2, 3])
        self.assertEqual(snapshots[-1], (3, 2))

    def test_account_check_retries_with_a_clean_client_after_timeout(self):
        account = {
            "id": 7,
            "label": "Седьмой",
            "can_invite": 1,
            "status": "authorized",
            "cooldown_until": 0,
        }
        ready = preflight._account_result(7, "Седьмой", "ready", "ok", True)
        probe = AsyncMock(side_effect=[asyncio.TimeoutError(), ready])
        reset = AsyncMock()

        async def run_check():
            return await preflight._check_account({}, 7, asyncio.Semaphore(1))

        with patch.object(preflight.db, "q1", return_value=account), \
                patch.object(preflight, "_probe_account", probe), \
                patch.object(preflight, "_reset_account_client", reset), \
                patch.object(preflight, "ACCOUNT_CHECK_RETRY_PAUSE", 0):
            result = asyncio.run(run_check())

        self.assertTrue(result["ready"])
        self.assertEqual(probe.await_count, 2)
        self.assertEqual(reset.await_count, 2)

    def test_preflight_rejects_persistent_peer_flood_after_cooldown(self):
        account = {
            "id": 7,
            "label": "Седьмой",
            "can_invite": 1,
            "status": "authorized",
            "cooldown_until": 0,
            "invite_restricted": 1,
            "invite_restriction_reason": "PEER_FLOOD",
        }
        probe = AsyncMock()

        async def run_check():
            return await preflight._check_account({}, 7, asyncio.Semaphore(1))

        with patch.object(preflight.db, "q1", return_value=account), \
                patch.object(preflight, "_probe_account", probe):
            result = asyncio.run(run_check())

        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "restricted")
        self.assertIn("ручное восстановление", result["detail"])
        probe.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
