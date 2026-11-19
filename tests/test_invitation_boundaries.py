import unittest
from unittest.mock import AsyncMock, Mock

from telethon import errors as telegram_errors

from app.application.invitations.targets import CampaignTargetBuilder
from app.domain import invitations as domain
from app.infrastructure.invitations.telegram import TelethonInvitationGateway


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
