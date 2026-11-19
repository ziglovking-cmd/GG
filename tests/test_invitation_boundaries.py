import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from telethon import errors as telegram_errors

from app.application.invitations.targets import CampaignTargetBuilder
from app.domain import invitations as domain
from app.infrastructure.invitations.telegram import TelethonInvitationGateway
from app import db


class TelegramBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_rejections_are_translated_to_domain_failures(self):
        gateway = TelethonInvitationGateway(Mock())
        cases = (
            (telegram_errors.PeerFloodError(request=None), domain.PeerFloodError),
            (telegram_errors.ChatAdminRequiredError(request=None), domain.ChatAdminRequiredError),
            (telegram_errors.FloodWaitError(request=None, capture=37), domain.FloodWaitError),
        )
        for remote_error, expected_type in cases:
            with self.subTest(error=expected_type.__name__):
                client = AsyncMock(side_effect=remote_error)
                with self.assertRaises(expected_type) as raised:
                    await gateway.invite_one(client, object(), object())
                self.assertIs(raised.exception.__cause__, remote_error)
                if isinstance(remote_error, telegram_errors.FloodWaitError):
                    self.assertEqual(raised.exception.seconds, 37)
                self.assertFalse(gateway.is_transient_connection_error(raised.exception))

    async def test_transport_errors_remain_retryable(self):
        gateway = TelethonInvitationGateway(Mock())
        error = ConnectionError("connection reset")
        with self.assertRaises(ConnectionError) as raised:
            await gateway.invite_one(AsyncMock(side_effect=error), object(), object())
        self.assertIs(raised.exception, error)
        self.assertTrue(gateway.is_transient_connection_error(error))

    def test_sqlite_lock_is_transient_not_telegram_limit(self):
        gateway = TelethonInvitationGateway(Mock())
        locked = sqlite3.OperationalError("database is locked")
        self.assertTrue(gateway.is_transient_connection_error(locked))
        self.assertFalse(
            gateway.is_transient_connection_error(domain.PeerFloodError())
        )


class SqliteHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db.connect()

    def tearDown(self):
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        self.tmp.cleanup()

    def test_main_connection_enables_busy_timeout(self):
        connection = db.connect()
        timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertGreaterEqual(int(timeout), 30000)

    def test_parallel_claim_only_one_worker_wins(self):
        account_id = db.ex(
            "INSERT INTO accounts (label,phone,session_name,status,can_invite,created_at) "
            "VALUES ('a','1','s1','authorized',1,0)"
        )
        campaign_id = db.ex(
            "INSERT INTO campaigns (name,target_chat_id,status,created_at) "
            "VALUES ('c',1,'running',0)"
        )
        db.ex(
            "INSERT INTO targets (campaign_id,user_id,username,status) "
            "VALUES (?,?,?,'pending')",
            (campaign_id, 100, "user100"),
        )
        first = db.claim_invite_target(campaign_id, account_id)
        second = db.claim_invite_target(campaign_id, account_id)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        row = db.q1("SELECT status,account_id FROM targets WHERE campaign_id=?", (campaign_id,))
        self.assertEqual(row["status"], "in_progress")
        self.assertEqual(row["account_id"], account_id)


class TargetSelectionTests(unittest.TestCase):
    def test_use_case_can_build_targets_without_sqlite_or_telegram(self):
        class MemoryRepository:
            def populate_targets(self, campaign_id, source_chat_ids, selection):
                self.selection = selection
                return 3

        repository = MemoryRepository()
        result = CampaignTargetBuilder(repository).build_targets(
            7, [10], {"only_active": True, "min_messages": "5", "skip_bots": False}
        )
        self.assertEqual(result, 3)
        self.assertFalse(repository.selection.skip_bots)
        self.assertTrue(repository.selection.skip_deleted)
        self.assertEqual(repository.selection.min_messages, 5)
        self.assertEqual(repository.selection.limit, 100000)

    def test_malformed_persisted_settings_keep_legacy_empty_defaults(self):
        self.assertEqual(domain.settings_of({"settings": "broken json"}), {})
