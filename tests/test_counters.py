import asyncio
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from telethon.errors import UserNotParticipantError
from telethon.tl.types import (
    ChannelParticipant,
    ChannelParticipantBanned,
    Chat,
    ChatBannedRights,
    PeerUser,
)

from app import accounts, db, inviting
from app.bootstrap import invitations as services
from app.domain import invitations as policy
from app.domain.invitations import (
    ChatAdminRequiredError,
    PeerFloodError,
    UserChannelsTooMuchError,
    UserPrivacyRestrictedError,
)


class InviteCounterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db.connect()
        self.account_id = db.ex(
            """
            INSERT INTO accounts
                (label, phone, session_name, created_at, counter_day)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("test", "+10000000000", "test_session", 0, date.today().isoformat()),
        )

    def tearDown(self):
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        self.tmp.cleanup()

    def test_peer_flood_restriction_survives_expired_cooldown(self):
        db.ex(
            "UPDATE accounts SET status='authorized', cooldown_until=1 WHERE id=?",
            (self.account_id,),
        )
        accounts.restrict_invites(self.account_id, "PEER_FLOOD")
        account = db.row_to_dict(
            db.q1("SELECT * FROM accounts WHERE id=?", (self.account_id,))
        )
        self.assertFalse(accounts.is_available(account))
        self.assertEqual(
            accounts.invite_eligibility(account, now=int(time.time()) + 86400)[1],
            "restricted",
        )

    def test_telethon_client_disables_internal_request_resend(self):
        account = {"session_name": "safe_session", "proxy": None}
        with (
            patch.object(accounts, "get_api_credentials", return_value=(12345, "hash")),
            patch.object(accounts, "TelegramClient") as client_factory,
        ):
            accounts.build_client(account)

        kwargs = client_factory.call_args.kwargs
        self.assertEqual(kwargs["request_retries"], 0)
        self.assertFalse(kwargs["auto_reconnect"])
        self.assertEqual(kwargs["flood_sleep_threshold"], 0)
        self.assertTrue(kwargs["raise_last_call_error"])

    def test_manual_restore_requires_finished_cooldown(self):
        now = 1000
        db.ex(
            """
            UPDATE accounts
            SET status='authorized', cooldown_until=?, invite_restricted=1,
                invite_restriction_reason='PEER_FLOOD', last_error='PEER_FLOOD'
            WHERE id=?
            """,
            (now + 60, self.account_id),
        )
        with self.assertRaises(accounts.AuthError):
            accounts.restore_invites(self.account_id, now=now)

        accounts.restore_invites(self.account_id, now=now + 61)
        account = db.row_to_dict(
            db.q1("SELECT * FROM accounts WHERE id=?", (self.account_id,))
        )
        self.assertEqual(account["invite_restricted"], 0)
        self.assertIsNone(account["invite_restriction_reason"])
        self.assertIsNone(account["last_error"])

    def test_unconfirmed_legacy_invited_is_failed_on_connect(self):
        campaign_id = db.ex(
            """
            INSERT INTO campaigns (name,target_chat_id,settings,status,created_at)
            VALUES ('legacy',123,'{}','done',0)
            """
        )
        target_id = db.ex(
            """
            INSERT INTO targets (campaign_id,user_id,status)
            VALUES (?,77,'invited')
            """,
            (campaign_id,),
        )
        db._conn.close()
        db._conn = None
        target = db.q1("SELECT status,error FROM targets WHERE id=?", (target_id,))
        self.assertEqual(target["status"], "failed")
        self.assertIn("нет подтверждения", target["error"])

    def test_durable_verification_cannot_return_to_invite_queue(self):
        campaign_id = db.ex(
            """
            INSERT INTO campaigns (name,target_chat_id,settings,status,created_at)
            VALUES ('at-most-once',123,'{}','running',0)
            """
        )
        target_id = db.ex(
            """
            INSERT INTO targets (campaign_id,user_id,status,account_id)
            VALUES (?,77,'in_progress',?)
            """,
            (campaign_id, self.account_id),
        )
        self.assertTrue(
            db.mark_invite_rpc_started(
                target_id,
                self.account_id,
                policy.invite_verification_note("invite_rpc=armed"),
                attempted_at=1,
            )
        )

        connection = db.connect()
        for forbidden_status in ("pending", "in_progress"):
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE targets SET status=? WHERE id=?",
                    (forbidden_status, target_id),
                )
            connection.rollback()

        target = db.q1("SELECT status,error FROM targets WHERE id=?", (target_id,))
        self.assertEqual(target["status"], "verifying")
        self.assertTrue(target["error"].startswith(policy.INVITE_RPC_DURABLE_MARKER))

    def test_cleanup_requeues_only_claims_proven_pre_rpc(self):
        campaign_id = db.ex(
            """
            INSERT INTO campaigns (name,target_chat_id,settings,status,created_at)
            VALUES ('cleanup',123,'{}','paused',0)
            """
        )
        safe_target_id = db.ex(
            """
            INSERT INTO targets
                (campaign_id,user_id,status,account_id,error)
            VALUES (?,77,'in_progress',?,?)
            """,
            (campaign_id, self.account_id, db.INVITE_CLAIM_MARKER),
        )
        legacy_target_id = db.ex(
            """
            INSERT INTO targets
                (campaign_id,user_id,status,account_id,error)
            VALUES (?,78,'in_progress',?,'legacy ambiguous state')
            """,
            (campaign_id, self.account_id),
        )

        services.repository.requeue_safe_pre_rpc_claims(campaign_id)

        safe = db.q1(
            "SELECT status,account_id,error FROM targets WHERE id=?", (safe_target_id,)
        )
        legacy = db.q1(
            "SELECT status,account_id,error FROM targets WHERE id=?", (legacy_target_id,)
        )
        self.assertEqual(tuple(safe), ("pending", None, None))
        self.assertEqual(legacy["status"], "in_progress")
        self.assertEqual(legacy["account_id"], self.account_id)
        self.assertEqual(legacy["error"], "legacy ambiguous state")

    def test_daily_quota_depends_on_successes_not_failed_attempts(self):
        db.ex(
            "UPDATE accounts SET daily_limit=5, invites_today=4, successful_today=1 "
            "WHERE id=?",
            (self.account_id,),
        )
        account = db.row_to_dict(
            db.q1("SELECT * FROM accounts WHERE id=?", (self.account_id,))
        )
        self.assertEqual(accounts.quota_left(account), 4)

    def test_next_attempt_survives_reconnect(self):
        expected = accounts.schedule_next_attempt(self.account_id, 14400, now=1000)
        self.assertEqual(expected, 15400)
        db._conn.close()
        db._conn = None
        row = db.q1("SELECT next_attempt_at FROM accounts WHERE id=?", (self.account_id,))
        self.assertEqual(row["next_attempt_at"], 15400)

    def test_batch_pause_cannot_shorten_base_interval(self):
        accounts.schedule_next_attempt(self.account_id, 14400, now=1000)
        result = accounts.defer_next_attempt(self.account_id, 2700, now=1000)
        self.assertEqual(result, 15400)

    def test_privacy_release_cancels_matching_interval(self):
        reserved = accounts.schedule_next_attempt(self.account_id, 14400, now=1000)
        result = accounts.release_next_attempt(self.account_id, reserved)
        self.assertEqual(result, 0)

    def test_privacy_release_cannot_erase_newer_interval(self):
        old_reservation = accounts.schedule_next_attempt(self.account_id, 90, now=1000)
        newer_reservation = accounts.schedule_next_attempt(self.account_id, 240, now=1000)
        result = accounts.release_next_attempt(self.account_id, old_reservation)
        self.assertEqual(result, newer_reservation)

    def test_accounts_have_independent_parallel_timers(self):
        second_id = db.ex(
            """
            INSERT INTO accounts
                (label, phone, session_name, created_at, counter_day)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("second", "+10000000001", "second_session", 0, date.today().isoformat()),
        )
        first_next = accounts.schedule_next_attempt(self.account_id, 14400, now=1000)
        second_next = accounts.schedule_next_attempt(second_id, 14400, now=1000)
        self.assertEqual(first_next, 15400)
        self.assertEqual(second_next, 15400)

    def test_restart_pauses_campaign_without_resetting_account_schedule(self):
        campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name, target_chat_id, settings, status, created_at)
            VALUES (?, ?, '{}', 'running', ?)
            """,
            ("test", 123, 0),
        )
        accounts.schedule_next_attempt(self.account_id, 14400, now=1000)
        safe_target_id = db.ex(
            """
            INSERT INTO targets
                (campaign_id,user_id,status,account_id,error)
            VALUES (?,77,'in_progress',?,?)
            """,
            (campaign_id, self.account_id, db.INVITE_CLAIM_MARKER),
        )
        legacy_target_id = db.ex(
            """
            INSERT INTO targets
                (campaign_id,user_id,status,account_id,error)
            VALUES (?,78,'in_progress',?,'legacy in_progress')
            """,
            (campaign_id, self.account_id),
        )
        db._conn.close()
        db._conn = None
        campaign = db.q1("SELECT status FROM campaigns WHERE id=?", (campaign_id,))
        self.assertEqual(campaign["status"], "running")
        db.pause_stale_running_campaigns()
        campaign = db.q1("SELECT status FROM campaigns WHERE id=?", (campaign_id,))
        account = db.q1("SELECT next_attempt_at FROM accounts WHERE id=?", (self.account_id,))
        self.assertEqual(campaign["status"], "paused")
        self.assertEqual(account["next_attempt_at"], 15400)
        safe_target = db.q1(
            "SELECT status,account_id,error FROM targets WHERE id=?", (safe_target_id,)
        )
        legacy_target = db.q1(
            "SELECT status,account_id,error FROM targets WHERE id=?", (legacy_target_id,)
        )
        self.assertEqual(tuple(safe_target), ("pending", None, None))
        self.assertEqual(legacy_target["status"], "in_progress")

    def test_new_campaign_excludes_previously_unconfirmed_target(self):
        source_chat_id = 555
        target_chat_id = 777
        db.ex(
            """
            INSERT INTO members
                (chat_id,user_id,username,first_name,is_bot,is_deleted,msg_count)
            VALUES (?,?,?,?,0,0,5)
            """,
            (source_chat_id, 700, "rejected_target", "Rejected"),
        )
        old_campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name,target_chat_id,settings,status,created_at)
            VALUES (?,?,'{}','done',?)
            """,
            ("old", target_chat_id, 0),
        )
        old_target_id = db.ex(
            """
            INSERT INTO targets
                (campaign_id,user_id,resolved_user_id,username,status)
            VALUES (?,?,?,?, 'failed')
            """,
            (old_campaign_id, 700, 700, "rejected_target"),
        )
        db.ex(
            """
            INSERT INTO invite_confirmations
                (target_id,checked_at,result,member_count)
            VALUES (?,1,'not_present',10)
            """,
            (old_target_id,),
        )
        new_campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name,target_chat_id,settings,status,created_at)
            VALUES (?,?,'{}','draft',?)
            """,
            ("new", target_chat_id, 0),
        )

        count = inviting.build_targets(new_campaign_id, [source_chat_id], {})

        self.assertEqual(count, 0)
        self.assertEqual(
            db.q1(
                "SELECT COUNT(*) c FROM targets WHERE campaign_id=?",
                (new_campaign_id,),
            )["c"],
            0,
        )


class AccountSlotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db.connect()
        self.account_ids = []
        for index in range(2):
            self.account_ids.append(db.ex(
                """
                INSERT INTO accounts
                    (label, phone, session_name, status, daily_limit,
                     min_delay, max_delay, created_at, counter_day)
                VALUES (?, ?, ?, 'authorized', 10, 14400, 14400, ?, ?)
                """,
                (f"test-{index}", f"+1000000000{index}", f"session-{index}",
                 0, date.today().isoformat()),
            ))

    def tearDown(self):
        inviting.set_attempt_notifier(None)
        for account_id in self.account_ids:
            services.runtime.account_locks.pop(account_id, None)
        services.runtime.recovery_locks.clear()
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        self.tmp.cleanup()

    async def test_different_accounts_can_reserve_in_parallel(self):
        before = int(time.time())
        results = await asyncio.gather(*[
            services.scheduler.reserve_account_slot(account_id, asyncio.Event(), {})
            for account_id in self.account_ids
        ])
        self.assertTrue(all(result is not None for result in results))
        self.assertLessEqual(abs(results[0] - results[1]), 1)
        self.assertGreaterEqual(min(results), before + 14400)

    async def test_same_account_cannot_reserve_second_slot_early(self):
        account_id = self.account_ids[0]
        first = await services.scheduler.reserve_account_slot(account_id, asyncio.Event(), {})
        stop = asyncio.Event()
        second_task = asyncio.create_task(
            services.scheduler.reserve_account_slot(account_id, stop, {})
        )
        await asyncio.sleep(0.01)
        stop.set()
        second = await asyncio.wait_for(second_task, timeout=1)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    async def test_campaign_account_checks_run_in_parallel_and_skip_timeout(self):
        campaign = {"id": 44, "target_chat_id": 123}
        healthy_entity = object()

        class HealthyClient:
            async def is_user_authorized(self):
                return True

            async def get_entity(self, _target_chat_id):
                return healthy_entity

        async def get_client(account_id):
            if account_id == self.account_ids[0]:
                await asyncio.sleep(1)
            return HealthyClient()

        started = time.monotonic()
        with (
            patch.object(accounts, "get_client", AsyncMock(side_effect=get_client)),
            patch.object(accounts, "drop_client", AsyncMock(return_value=None)),
            patch.object(services.gateway, "can_invite", return_value=True),
            patch.object(policy, "CONNECTION_RETRY_ATTEMPTS", 1),
        ):
            results = await asyncio.gather(*[
                services.preparation.prepare(
                    campaign,
                    account_id,
                    connect_timeout=0.02,
                    request_timeout=0.02,
                )
                for account_id in self.account_ids
            ])

        self.assertLess(time.monotonic() - started, 0.2)
        self.assertIsNone(results[0])
        self.assertIs(results[1], healthy_entity)

    async def test_campaign_account_retries_transient_connection_and_recovers(self):
        campaign = {"id": 46, "target_chat_id": 123}
        account_id = self.account_ids[0]
        healthy_entity = object()

        class HealthyClient:
            async def is_user_authorized(self):
                return True

            async def get_entity(self, _target_chat_id):
                return healthy_entity

        get_client = AsyncMock(side_effect=[
            asyncio.TimeoutError(),
            ConnectionError("proxy connection reset"),
            HealthyClient(),
        ])
        with (
            patch.object(accounts, "get_client", get_client),
            patch.object(accounts, "drop_client", AsyncMock(return_value=None)),
            patch.object(services.gateway, "can_invite", return_value=True),
        ):
            result = await asyncio.wait_for(
                services.preparation.prepare(campaign, account_id), timeout=1
            )

        self.assertIs(result, healthy_entity)
        self.assertEqual(get_client.await_count, 3)

    def test_telegram_rpc_error_is_never_treated_as_connection_retry(self):
        self.assertFalse(
            services.gateway.is_transient_connection_error(PeerFloodError())
        )
        self.assertTrue(
            services.gateway.is_transient_connection_error(ConnectionError("proxy reset"))
        )

    async def test_disabled_account_is_not_connected_during_campaign_start(self):
        campaign = {"id": 45, "target_chat_id": 123}
        account_id = self.account_ids[0]
        db.ex("UPDATE accounts SET can_invite=0 WHERE id=?", (account_id,))

        get_client = AsyncMock()
        with patch.object(accounts, "get_client", get_client):
            result = await services.preparation.prepare(campaign, account_id)

        self.assertIsNone(result)
        get_client.assert_not_awaited()
        self.assertEqual(
            inviting.STATE[campaign["id"]]["workers"][account_id]["state"],
            "отключён пользователем",
        )
        inviting.STATE.pop(campaign["id"], None)

    async def test_technical_worker_can_recover_without_resetting_interval(self):
        account_id = self.account_ids[0]
        next_attempt_at = int(time.time()) + 14400
        db.ex(
            "UPDATE accounts SET can_invite=0, cooldown_until=?, next_attempt_at=? WHERE id=?",
            (int(time.time()) + 900, next_attempt_at, account_id),
        )
        campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name, target_chat_id, settings, status, created_at)
            VALUES (?, ?, ?, 'running', ?)
            """,
            (
                "recovery",
                123,
                '{"account_ids":[%d]}' % account_id,
                int(time.time()),
            ),
        )
        stop = asyncio.Event()
        inviting.STATE[campaign_id] = {
            "stop": stop,
            "workers": {account_id: {"state": "сбой подключения — проверьте прокси"}},
            "worker_tasks": {},
            "target_entity_by_account": {},
        }
        runner = asyncio.create_task(asyncio.Event().wait())
        inviting.RUNNERS[campaign_id] = runner

        async def recovered_worker(_campaign_id, _account_id, worker_stop):
            await worker_stop.wait()

        try:
            with (
                patch.object(
                    accounts,
                    "test_proxy",
                    AsyncMock(return_value={
                        "ok": True,
                        "authorized": True,
                        "latency_ms": 120,
                        "verdict": "хорошо",
                    }),
                ),
                patch.object(services.preparation, "prepare", AsyncMock(return_value=object())
                ),
                patch.object(services.worker, "run", side_effect=recovered_worker),
            ):
                result = await inviting.recover_campaign_account(campaign_id, account_id)

            account = db.q1(
                "SELECT can_invite, status, cooldown_until, next_attempt_at "
                "FROM accounts WHERE id=?",
                (account_id,),
            )
            self.assertTrue(result["ok"])
            self.assertFalse(result["already_active"])
            self.assertEqual(result["latency_ms"], 120)
            self.assertEqual(account["can_invite"], 1)
            self.assertEqual(account["status"], "authorized")
            self.assertEqual(account["cooldown_until"], 0)
            self.assertEqual(account["next_attempt_at"], next_attempt_at)
            self.assertFalse(
                inviting.STATE[campaign_id]["worker_tasks"][account_id].done()
            )
        finally:
            stop.set()
            worker_task = inviting.STATE[campaign_id]["worker_tasks"].get(account_id)
            if worker_task:
                await worker_task
            runner.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await runner
            inviting.RUNNERS.pop(campaign_id, None)
            inviting.STATE.pop(campaign_id, None)

    async def test_recovery_does_not_bypass_active_peer_flood(self):
        account_id = self.account_ids[0]
        db.ex(
            "UPDATE accounts SET cooldown_until=?, last_error='PEER_FLOOD' WHERE id=?",
            (int(time.time()) + 3600, account_id),
        )
        campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name, target_chat_id, settings, status, created_at)
            VALUES (?, ?, ?, 'running', ?)
            """,
            (
                "protected-recovery",
                123,
                '{"account_ids":[%d]}' % account_id,
                int(time.time()),
            ),
        )
        stop = asyncio.Event()
        inviting.STATE[campaign_id] = {
            "stop": stop,
            "workers": {account_id: {"state": "PEER_FLOOD, сутки паузы"}},
            "worker_tasks": {},
            "target_entity_by_account": {},
        }
        runner = asyncio.create_task(asyncio.Event().wait())
        inviting.RUNNERS[campaign_id] = runner
        proxy_test = AsyncMock()
        try:
            with patch.object(accounts, "test_proxy", proxy_test):
                with self.assertRaises(inviting.WorkerRecoveryError) as raised:
                    await inviting.recover_campaign_account(campaign_id, account_id)
            self.assertIn("Защитное ограничение Telegram", str(raised.exception))
            proxy_test.assert_not_awaited()
        finally:
            runner.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await runner
            inviting.RUNNERS.pop(campaign_id, None)
            inviting.STATE.pop(campaign_id, None)

    async def test_attempt_notification_is_dispatched_with_event_data(self):
        received = []

        async def notifier(payload):
            received.append(payload)

        inviting.set_attempt_notifier(notifier)
        services.notifier.queue(
            campaign_id=12,
            account_id=self.account_ids[0],
            target={"id": 55, "user_id": 77, "username": "target", "display": "Target"},
            outcome="invited",
            next_attempt_at=12345,
        )
        await asyncio.sleep(0)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["campaign_id"], 12)
        self.assertEqual(received[0]["account_id"], self.account_ids[0])
        self.assertEqual(received[0]["outcome"], "invited")
        self.assertEqual(received[0]["next_attempt_at"], 12345)

    async def test_missing_invitees_is_rejected_for_channel_and_basic_chat(self):
        result = SimpleNamespace(missing_invitees=[SimpleNamespace(user_id=77)])
        channel_client = AsyncMock(return_value=result)
        with self.assertRaises(policy.InviteNotAcceptedError):
            await services.gateway.invite_one(channel_client, object(), object())

        basic_chat = Chat(123, "Test", None, 1, None, 1)
        chat_client = AsyncMock(return_value=result)
        with self.assertRaises(policy.InviteNotAcceptedError):
            await services.gateway.invite_one(chat_client, basic_chat, object())

    async def test_missing_invitees_persists_not_present_without_retry(self):
        campaign_id, target_id = self._campaign_with_target()
        invite = AsyncMock(
            side_effect=policy.InviteNotAcceptedError("missing_invitees")
        )
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.gateway, "invite_one", invite),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, self.account_ids[0], asyncio.Event()
                    ),
                    timeout=0.5,
                )

            target = db.q1("SELECT status,error FROM targets WHERE id=?", (target_id,))
            confirmation = db.q1(
                "SELECT result FROM invite_confirmations WHERE target_id=?",
                (target_id,),
            )
            account = db.q1(
                "SELECT invites_today,successful_today,next_attempt_at "
                "FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "failed")
            self.assertIn("missing_invitees", target["error"])
            self.assertEqual(confirmation["result"], "not_present")
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertEqual(account["next_attempt_at"], 0)
            self.assertEqual(invite.await_count, 1)
        finally:
            inviting.STATE.pop(campaign_id, None)

    def test_campaign_keeps_last_rejected_attempt_while_waiting_and_after_restart(self):
        from app.api import campaigns as campaign_api

        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        db.ex(
            "UPDATE targets SET status='failed',account_id=?,attempted_at=10,error=? WHERE id=?",
            (account_id, "Telegram вернул missing_invitees", target_id),
        )
        # Подготовка следующей цели не скрывает результат завершённой попытки.
        db.ex(
            "INSERT INTO targets (campaign_id,user_id,status,account_id,error) "
            "VALUES (?,88,'in_progress',?,?)",
            (campaign_id, account_id, db.INVITE_CLAIM_MARKER),
        )
        inviting.STATE[campaign_id]["workers"][account_id] = {
            "state": "очередь кампании: следующее приглашение через 15 мин"
        }
        try:
            for restarted in (False, True):
                with self.subTest(restarted=restarted):
                    if restarted:
                        inviting.STATE.pop(campaign_id, None)
                    result = campaign_api.get_campaign(campaign_id)
                    self.assertEqual(result["stats"].get("invited", 0), 0)
                    worker = result["workers"][0]
                    self.assertEqual(worker["last_attempt"]["id"], target_id)
                    self.assertEqual(worker["last_attempt"]["status"], "failed")
                    self.assertIn("missing_invitees", worker["last_attempt"]["error"])
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_verifying_campaign_cannot_be_deleted(self):
        from app.api import campaigns as campaign_api

        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        db.ex(
            "UPDATE targets SET status='in_progress',account_id=? WHERE id=?",
            (account_id, target_id),
        )
        self.assertTrue(
            db.mark_invite_rpc_started(
                target_id,
                account_id,
                policy.invite_verification_note("invite_rpc=ambiguous"),
                attempted_at=1,
            )
        )

        with self.assertRaises(Exception) as raised:
            await campaign_api.delete_campaign(campaign_id)
        self.assertEqual(getattr(raised.exception, "status_code", None), 409)
        self.assertIsNotNone(db.q1("SELECT id FROM campaigns WHERE id=?", (campaign_id,)))
        self.assertEqual(
            db.q1("SELECT status FROM targets WHERE id=?", (target_id,))["status"],
            "verifying",
        )
        inviting.STATE.pop(campaign_id, None)

    async def test_targeted_membership_check_is_tri_state(self):
        present_client = SimpleNamespace(
            get_permissions=AsyncMock(
                return_value=SimpleNamespace(
                    participant=ChannelParticipant(user_id=77, date=None)
                )
            )
        )
        self.assertEqual(
            (await services.gateway.membership_state_once(
                present_client, object(), object()
            ))[0],
            "present",
        )

        absent_client = SimpleNamespace(
            get_permissions=AsyncMock(
                side_effect=UserNotParticipantError(request=None)
            )
        )
        self.assertEqual(
            (await services.gateway.membership_state_once(
                absent_client, object(), object()
            ))[0],
            "not_member",
        )

        unknown_client = SimpleNamespace(
            get_permissions=AsyncMock(side_effect=asyncio.TimeoutError())
        )
        state, detail = await services.gateway.membership_state_once(
            unknown_client, object(), object()
        )
        self.assertEqual(state, "unknown")
        self.assertTrue(detail)

    async def test_restricted_channel_participant_still_counts_as_present(self):
        participant = ChannelParticipantBanned(
            peer=PeerUser(77),
            kicked_by=1,
            date=None,
            banned_rights=ChatBannedRights(
                until_date=None,
                view_messages=False,
                send_messages=True,
            ),
            left=False,
        )
        client = SimpleNamespace(
            get_permissions=AsyncMock(
                return_value=SimpleNamespace(participant=participant)
            )
        )
        state, _ = await services.gateway.membership_state_once(
            client, object(), object()
        )
        self.assertEqual(state, "present")

    async def test_left_or_view_banned_channel_participant_is_not_member(self):
        participants = (
            ChannelParticipantBanned(
                peer=PeerUser(77),
                kicked_by=1,
                date=None,
                banned_rights=ChatBannedRights(
                    until_date=None,
                    view_messages=False,
                ),
                left=True,
            ),
            ChannelParticipantBanned(
                peer=PeerUser(78),
                kicked_by=1,
                date=None,
                banned_rights=ChatBannedRights(
                    until_date=None,
                    view_messages=True,
                ),
                left=False,
            ),
        )
        for participant in participants:
            with self.subTest(participant=participant):
                client = SimpleNamespace(
                    get_permissions=AsyncMock(
                        return_value=SimpleNamespace(participant=participant)
                    )
                )
                state, _ = await services.gateway.membership_state_once(
                    client, object(), object()
                )
                self.assertEqual(state, "not_member")

    def _campaign_with_target(self) -> tuple[int, int]:
        campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name, target_chat_id, settings, status, created_at)
            VALUES (?, ?, '{}', 'running', ?)
            """,
            ("notifications", 123, 0),
        )
        target_id = db.ex(
            """
            INSERT INTO targets (campaign_id, user_id, username, display)
            VALUES (?, ?, ?, ?)
            """,
            (campaign_id, 77, "target", "Target"),
        )
        inviting.STATE[campaign_id] = {
            "target_entity_by_account": {self.account_ids[0]: object()},
            "workers": {},
        }
        return campaign_id, target_id

    async def test_successful_worker_attempt_sends_one_notification(self):
        campaign_id, target_id = self._campaign_with_target()
        stop = asyncio.Event()
        received = []

        async def notifier(payload):
            received.append(payload)
            stop.set()

        inviting.set_attempt_notifier(notifier)
        next_at = int(time.time()) + 14400
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=("present", "", "confirmed")),
                ),
                patch.object(services.scheduler, "reserve_account_slot", AsyncMock(return_value=next_at)),
                patch.object(services.gateway, "invite_one", AsyncMock(return_value=None)),
            ):
                await asyncio.wait_for(
                    services.worker.run(campaign_id, self.account_ids[0], stop),
                    timeout=1,
                )

            target = db.q1(
                "SELECT status, error FROM targets WHERE id=?", (target_id,)
            )
            account = db.q1(
                "SELECT invites_today, successful_today FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "invited")
            self.assertIsNone(target["error"])
            self.assertEqual(account["invites_today"], 1)
            self.assertEqual(account["successful_today"], 1)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["outcome"], "invited")
            self.assertEqual(received[0]["campaign_id"], campaign_id)
            confirmation = db.q1(
                "SELECT result FROM invite_confirmations WHERE target_id=?",
                (target_id,),
            )
            self.assertEqual(confirmation["result"], "confirmed")
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_nominal_rpc_without_membership_is_never_counted_as_invited(self):
        campaign_id, target_id = self._campaign_with_target()
        stop = asyncio.Event()
        received = []

        async def notifier(payload):
            received.append(payload)
            stop.set()

        inviting.set_attempt_notifier(notifier)
        next_at = int(time.time()) + 14400
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=(
                        "not_member",
                        "Telegram не подтвердил присутствие пользователя",
                        "not_present",
                    )),
                ),
                patch.object(services.scheduler, "reserve_account_slot",
                    AsyncMock(return_value=next_at),
                ),
                patch.object(services.gateway, "invite_one", AsyncMock(return_value=None)),
            ):
                await asyncio.wait_for(
                    services.worker.run(campaign_id, self.account_ids[0], stop),
                    timeout=1,
                )

            target = db.q1("SELECT status,error FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT invites_today,successful_today FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            confirmation = db.q1(
                "SELECT result FROM invite_confirmations WHERE target_id=?",
                (target_id,),
            )
            self.assertEqual(target["status"], "failed")
            self.assertIn("не подтвердил", target["error"])
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertEqual(confirmation["result"], "not_present")
            self.assertEqual(received[0]["outcome"], "unconfirmed")
            # Protective spacing after a real Invite RPC stays; daily quota does not.
            kept = db.q1(
                "SELECT next_attempt_at,cooldown_until FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(kept["next_attempt_at"], next_at)
            self.assertEqual(kept["cooldown_until"], 0)
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_unknown_post_check_stays_verifying_without_success(self):
        campaign_id, target_id = self._campaign_with_target()
        stop = asyncio.Event()

        async def notifier(_payload):
            stop.set()

        inviting.set_attempt_notifier(notifier)
        next_at = int(time.time()) + 14400
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=(
                        "unknown",
                        "Точечная проверка временно недоступна",
                        "verification_error",
                    )),
                ),
                patch.object(services.scheduler, "reserve_account_slot",
                    AsyncMock(return_value=next_at),
                ),
                patch.object(services.gateway, "invite_one", AsyncMock(return_value=None)),
            ):
                await asyncio.wait_for(
                    services.worker.run(campaign_id, self.account_ids[0], stop),
                    timeout=1,
                )

            target = db.q1("SELECT status,error FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT invites_today,successful_today FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "verifying")
            self.assertIn("временно недоступна", target["error"])
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertIsNone(db.q1(
                "SELECT result FROM invite_confirmations WHERE target_id=?",
                (target_id,),
            ))
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_unknown_confirmation_is_retried_without_second_invite(self):
        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        db.ex(
            """
            UPDATE targets
            SET status='verifying', account_id=?, attempted_at=1,
                error='Не удалось достоверно подтвердить присутствие пользователя'
            WHERE id=?
            """,
            (account_id, target_id),
        )
        info = {}
        invite = AsyncMock()
        try:
            with (
                patch.object(services.context, "resolve",
                    AsyncMock(return_value=(object(), object(), object())),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=("present", "", "confirmed")),
                ),
                patch.object(services.gateway, "invite_one", invite),
            ):
                handled = await services.verification.retry_pending(
                    campaign_id, account_id, info
                )

            target = db.q1("SELECT status FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT invites_today,successful_today FROM accounts WHERE id=?",
                (account_id,),
            )
            self.assertTrue(handled)
            self.assertEqual(target["status"], "invited")
            self.assertEqual(account["invites_today"], 1)
            self.assertEqual(account["successful_today"], 1)
            invite.assert_not_awaited()
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_present_before_rpc_is_already_and_invite_is_not_sent(self):
        campaign_id, target_id = self._campaign_with_target()
        invite = AsyncMock()
        reserve = AsyncMock()
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("present", "")),
                ),
                patch.object(services.scheduler, "reserve_account_slot", reserve),
                patch.object(services.gateway, "invite_one", invite),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, self.account_ids[0], asyncio.Event()
                    ),
                    timeout=1,
                )

            target = db.q1("SELECT status FROM targets WHERE id=?", (target_id,))
            self.assertEqual(target["status"], "already")
            reserve.assert_not_awaited()
            invite.assert_not_awaited()
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_membership_is_rechecked_after_waiting_for_account_slot(self):
        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        invite = AsyncMock()
        membership = AsyncMock(
            side_effect=[("not_member", ""), ("present", "")]
        )

        async def reserve_slot(_account_id, _stop, _info):
            return accounts.schedule_next_attempt(
                account_id, 14400, now=int(time.time())
            )

        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once", membership),
                patch.object(services.scheduler, "reserve_account_slot",
                    AsyncMock(side_effect=reserve_slot),
                ),
                patch.object(services.gateway, "invite_one", invite),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, account_id, asyncio.Event()
                    ),
                    timeout=0.5,
                )

            target = db.q1("SELECT status FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT next_attempt_at,invites_today,successful_today "
                "FROM accounts WHERE id=?",
                (account_id,),
            )
            self.assertEqual(target["status"], "already")
            self.assertEqual(membership.await_count, 2)
            invite.assert_not_awaited()
            self.assertEqual(account["next_attempt_at"], 0)
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_stop_after_slot_reservation_never_starts_invite_rpc(self):
        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        stop = asyncio.Event()
        invite = AsyncMock()

        async def membership_check(*_args):
            if membership_check.calls:
                stop.set()
            membership_check.calls += 1
            return "not_member", ""

        membership_check.calls = 0

        async def reserve_slot(_account_id, _stop, _info):
            return accounts.schedule_next_attempt(
                account_id, 14400, now=int(time.time())
            )

        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(side_effect=membership_check),
                ),
                patch.object(services.scheduler, "reserve_account_slot",
                    AsyncMock(side_effect=reserve_slot),
                ),
                patch.object(services.gateway, "invite_one", invite),
            ):
                await asyncio.wait_for(
                    services.worker.run(campaign_id, account_id, stop),
                    timeout=0.5,
                )

            target = db.q1("SELECT status,account_id FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT next_attempt_at FROM accounts WHERE id=?", (account_id,)
            )
            self.assertEqual(target["status"], "pending")
            self.assertIsNone(target["account_id"])
            self.assertEqual(account["next_attempt_at"], 0)
            invite.assert_not_awaited()
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_cancel_during_final_precheck_releases_unspent_slot(self):
        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        final_check_started = asyncio.Event()
        never_finishes = asyncio.Event()
        invite = AsyncMock()
        calls = 0

        async def membership_check(*_args):
            nonlocal calls
            calls += 1
            if calls == 1:
                return "not_member", ""
            final_check_started.set()
            await never_finishes.wait()
            return "not_member", ""

        async def reserve_slot(_account_id, _stop, _info):
            return accounts.schedule_next_attempt(
                account_id, 14400, now=int(time.time())
            )

        task = None
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(side_effect=membership_check),
                ),
                patch.object(services.scheduler, "reserve_account_slot",
                    AsyncMock(side_effect=reserve_slot),
                ),
                patch.object(services.gateway, "invite_one", invite),
            ):
                task = asyncio.create_task(
                    services.worker.run(campaign_id, account_id, asyncio.Event())
                )
                await asyncio.wait_for(final_check_started.wait(), timeout=0.5)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            target = db.q1("SELECT status,account_id FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT next_attempt_at FROM accounts WHERE id=?", (account_id,)
            )
            self.assertEqual(target["status"], "pending")
            self.assertIsNone(target["account_id"])
            self.assertEqual(account["next_attempt_at"], 0)
            invite.assert_not_awaited()
        finally:
            if task is not None and not task.done():
                task.cancel()
            inviting.STATE.pop(campaign_id, None)

    async def test_unknown_precheck_never_sends_invite(self):
        campaign_id, target_id = self._campaign_with_target()
        stop = asyncio.Event()
        invite = AsyncMock()
        reserve = AsyncMock()

        async def notifier(_payload):
            stop.set()

        inviting.set_attempt_notifier(notifier)
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("unknown", "проверка недоступна")),
                ),
                patch.object(services.scheduler, "reserve_account_slot", reserve),
                patch.object(services.gateway, "invite_one", invite),
            ):
                await asyncio.wait_for(
                    services.worker.run(campaign_id, self.account_ids[0], stop),
                    timeout=1,
                )

            target = db.q1("SELECT status,account_id FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT invites_today,successful_today FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "pending")
            self.assertIsNone(target["account_id"])
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            reserve.assert_not_awaited()
            invite.assert_not_awaited()
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_peer_flood_does_not_increment_success_counters(self):
        campaign_id, target_id = self._campaign_with_target()
        stop = asyncio.Event()
        reserved_at = int(time.time()) + 14400
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.scheduler, "reserve_account_slot",
                    AsyncMock(return_value=reserved_at),
                ),
                patch.object(services.gateway, "invite_one",
                    AsyncMock(side_effect=PeerFloodError()),
                ),
            ):
                await asyncio.wait_for(
                    services.worker.run(campaign_id, self.account_ids[0], stop),
                    timeout=1,
                )

            target = db.q1(
                "SELECT status,account_id FROM targets WHERE id=?", (target_id,)
            )
            account = db.q1(
                """
                SELECT invites_today,successful_today,cooldown_until,
                       invite_restricted,invite_restriction_reason
                FROM accounts WHERE id=?
                """,
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "failed")
            self.assertEqual(target["account_id"], self.account_ids[0])
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertGreater(account["cooldown_until"], int(time.time()))
            self.assertEqual(account["invite_restricted"], 1)
            self.assertIn("PEER_FLOOD", account["invite_restriction_reason"])
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_privacy_skip_releases_interval_without_notification(self):
        campaign_id, target_id = self._campaign_with_target()
        received = []

        async def notifier(payload):
            received.append(payload)

        inviting.set_attempt_notifier(notifier)
        reserved_at = int(time.time()) + 14400

        async def reserve_slot(account_id, stop, info):
            return accounts.schedule_next_attempt(
                account_id, 14400, now=reserved_at - 14400
            )

        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.scheduler, "reserve_account_slot", AsyncMock(side_effect=reserve_slot)
                ),
                patch.object(services.gateway, "invite_one",
                    AsyncMock(side_effect=UserPrivacyRestrictedError()),
                ),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, self.account_ids[0], asyncio.Event()
                    ),
                    timeout=1,
                )

            target = db.q1("SELECT status FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                """
                SELECT invites_today, successful_today, next_attempt_at
                FROM accounts WHERE id=?
                """,
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "privacy")
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertEqual(account["next_attempt_at"], 0)
            self.assertEqual(received, [])
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_target_with_too_many_chats_does_not_consume_slot(self):
        campaign_id, target_id = self._campaign_with_target()
        reserved_at = int(time.time()) + 14400

        async def reserve_slot(account_id, stop, info):
            return accounts.schedule_next_attempt(
                account_id, 14400, now=reserved_at - 14400
            )

        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.scheduler, "reserve_account_slot", AsyncMock(side_effect=reserve_slot)
                ),
                patch.object(services.gateway, "invite_one",
                    AsyncMock(side_effect=UserChannelsTooMuchError()),
                ),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, self.account_ids[0], asyncio.Event()
                    ),
                    timeout=1,
                )

            target = db.q1("SELECT status FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT invites_today, successful_today, next_attempt_at "
                "FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "failed")
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertEqual(account["next_attempt_at"], 0)
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_missing_chat_rights_does_not_consume_slot(self):
        campaign_id, target_id = self._campaign_with_target()
        reserved_at = int(time.time()) + 14400
        stop = asyncio.Event()

        async def reserve_slot(account_id, stop, info):
            return accounts.schedule_next_attempt(
                account_id, 14400, now=reserved_at - 14400
            )

        try:
            async def recheck_access(_campaign, _account_id):
                stop.set()
                return object()

            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.scheduler, "reserve_account_slot", AsyncMock(side_effect=reserve_slot)
                ),
                patch.object(services.gateway, "invite_one",
                    AsyncMock(side_effect=ChatAdminRequiredError()),
                ),
                patch.object(services.preparation, "prepare",
                    AsyncMock(side_effect=recheck_access),
                ) as prepare,
                patch.object(policy, "ACCESS_RECHECK_PAUSE", 0),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, self.account_ids[0], stop
                    ),
                    timeout=1,
                )

            target = db.q1(
                "SELECT status, account_id FROM targets WHERE id=?", (target_id,)
            )
            account = db.q1(
                "SELECT invites_today, successful_today, next_attempt_at "
                "FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "failed")
            self.assertEqual(target["account_id"], self.account_ids[0])
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertEqual(account["next_attempt_at"], 0)
            prepare.assert_not_awaited()
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_startup_missing_rights_stays_scheduled_for_recheck(self):
        campaign = {"id": 46, "target_chat_id": 123}
        account_id = self.account_ids[0]

        class Client:
            async def is_user_authorized(self):
                return True

            async def get_entity(self, _target_chat_id):
                return object()

        with (
            patch.object(accounts, "get_client", AsyncMock(return_value=Client())),
            patch.object(services.gateway, "can_invite", return_value=False),
            patch.object(policy, "ACCESS_RECHECK_PAUSE", 900),
        ):
            result = await services.preparation.prepare(campaign, account_id)

        worker = inviting.STATE[campaign["id"]]["workers"][account_id]
        self.assertIsNone(result)
        self.assertGreater(worker["access_retry_at"], int(time.time()))
        self.assertIn("перепроверка доступа", worker["state"])
        inviting.STATE.pop(campaign["id"], None)

    async def test_connection_failure_requeues_target_and_notifies(self):
        campaign_id, target_id = self._campaign_with_target()
        received = []
        stop = asyncio.Event()

        async def notifier(payload):
            received.append(payload)
            stop.set()

        inviting.set_attempt_notifier(notifier)
        try:
            with (
                patch.object(
                    accounts,
                    "get_client",
                    AsyncMock(side_effect=TypeError("ConnectionError() takes no keyword arguments")),
                ),
                patch.object(accounts, "drop_client", AsyncMock(return_value=None)),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, self.account_ids[0], stop
                    ),
                    timeout=1,
                )
            await asyncio.sleep(0)

            target = db.q1(
                "SELECT status, account_id, error FROM targets WHERE id=?", (target_id,)
            )
            account = db.q1(
                """
                SELECT invites_today, successful_today, cooldown_until, next_attempt_at
                FROM accounts WHERE id=?
                """,
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "pending")
            self.assertIsNone(target["account_id"])
            self.assertIsNone(target["error"])
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertEqual(account["cooldown_until"], 0)
            self.assertEqual(account["next_attempt_at"], 0)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["outcome"], "connection_error")
            self.assertEqual(
                received[0]["error"],
                "Прокси не смог установить соединение с Telegram",
            )
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_pre_invite_technical_failures_retry_without_delay(self):
        for error in (ConnectionError("connection reset"), RuntimeError("technical failure")):
            with self.subTest(error=type(error).__name__):
                campaign_id, target_id = self._campaign_with_target()
                stop = asyncio.Event()
                received = []

                async def notifier(payload):
                    received.append(payload)
                    if len(received) == 2:
                        stop.set()

                inviting.set_attempt_notifier(notifier)
                try:
                    with (
                        patch.object(accounts, "get_client", AsyncMock(side_effect=error)),
                        patch.object(accounts, "drop_client", AsyncMock(return_value=None)),
                    ):
                        await asyncio.wait_for(
                            services.worker.run(campaign_id, self.account_ids[0], stop),
                            timeout=1,
                        )

                    self.assertEqual(len(received), 2)
                    self.assertTrue(all(p["outcome"] == "connection_error" for p in received))
                    target = db.q1("SELECT status FROM targets WHERE id=?", (target_id,))
                    self.assertEqual(target["status"], "pending")
                    account = db.q1(
                        "SELECT invites_today, next_attempt_at FROM accounts WHERE id=?",
                        (self.account_ids[0],),
                    )
                    self.assertEqual(account["invites_today"], 0)
                    self.assertEqual(account["next_attempt_at"], 0)
                finally:
                    inviting.set_attempt_notifier(None)
                    inviting.STATE.pop(campaign_id, None)

    async def test_pre_invite_failure_after_reservation_releases_both_timers(self):
        for error in (ConnectionError("connection reset"), RuntimeError("technical failure")):
            with self.subTest(error=type(error).__name__):
                campaign_id, target_id = self._campaign_with_target()
                stop = asyncio.Event()
                received = []

                async def notifier(payload):
                    received.append(payload)
                    if len(received) == 2:
                        stop.set()

                inviting.set_attempt_notifier(notifier)
                invite = AsyncMock()
                try:
                    with (
                        patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                        patch.object(accounts, "drop_client", AsyncMock()),
                        patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                        patch.object(services.gateway, "membership_state_once", AsyncMock(side_effect=[
                            ("not_member", ""), error, ("not_member", ""), error,
                        ])),
                        patch.object(services.gateway, "invite_one", invite),
                    ):
                        await asyncio.wait_for(
                            services.worker.run(campaign_id, self.account_ids[0], stop),
                            timeout=1,
                        )

                    invite.assert_not_awaited()
                    self.assertEqual(len(received), 2)
                    self.assertTrue(all(p["outcome"] == "connection_error" for p in received))
                    self.assertTrue(all(p["next_attempt_at"] == 0 for p in received))
                    self.assertEqual(db.q1(
                        "SELECT next_invite_at FROM campaigns WHERE id=?", (campaign_id,),
                    )["next_invite_at"], 0)
                    self.assertEqual(db.q1(
                        "SELECT status FROM targets WHERE id=?", (target_id,),
                    )["status"], "pending")
                    account = db.q1(
                        "SELECT next_attempt_at, invites_today FROM accounts WHERE id=?",
                        (self.account_ids[0],),
                    )
                    self.assertEqual(account["next_attempt_at"], 0)
                    self.assertEqual(account["invites_today"], 0)
                finally:
                    inviting.set_attempt_notifier(None)
                    inviting.STATE.pop(campaign_id, None)

    async def test_startup_technical_failure_does_not_schedule_retry_delay(self):
        campaign = {"id": 46, "target_chat_id": 123}
        account_id = self.account_ids[0]
        for error in (ConnectionError("connection reset"), RuntimeError("technical failure")):
            with self.subTest(error=type(error).__name__):
                try:
                    with (
                        patch.object(accounts, "get_client", AsyncMock(side_effect=error)),
                        patch.object(accounts, "drop_client", AsyncMock()),
                    ):
                        result = await asyncio.wait_for(
                            services.preparation.prepare(campaign, account_id),
                            timeout=1,
                        )
                    self.assertIsNone(result)
                    info = inviting.STATE[campaign["id"]]["workers"][account_id]
                    self.assertNotIn("technical_retry_at", info)
                    self.assertIn("повтор без задержки", info["state"])
                finally:
                    inviting.STATE.pop(campaign["id"], None)

    async def test_connection_failure_during_invite_is_ambiguous_and_at_most_once(self):
        campaign_id, target_id = self._campaign_with_target()
        stop = asyncio.Event()

        async def fail_after_rpc_started(*_args):
            stop.set()
            raise ConnectionError("connection reset")

        invite = AsyncMock(side_effect=fail_after_rpc_started)
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(accounts, "drop_client", AsyncMock(return_value=None)),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.gateway, "invite_one", invite),
            ):
                await asyncio.wait_for(
                    services.worker.run(campaign_id, self.account_ids[0], stop),
                    timeout=1,
                )

            target = db.q1(
                "SELECT status, account_id, error FROM targets WHERE id=?", (target_id,)
            )
            account = db.q1(
                "SELECT invites_today, successful_today, next_attempt_at "
                "FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "verifying")
            self.assertEqual(target["account_id"], self.account_ids[0])
            self.assertTrue(
                target["error"].startswith(policy.INVITE_RPC_DURABLE_MARKER)
            )
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            self.assertGreater(account["next_attempt_at"], int(time.time()))
            self.assertIsNone(db.q1(
                "SELECT result FROM invite_confirmations WHERE target_id=?",
                (target_id,),
            ))
            self.assertEqual(invite.await_count, 1)

            resend = AsyncMock()
            with (
                patch.object(services.context, "resolve",
                    AsyncMock(return_value=(object(), object(), object())),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=("present", "", "confirmed")),
                ),
                patch.object(services.gateway, "invite_one", resend),
            ):
                handled = await services.verification.retry_pending(
                    campaign_id, self.account_ids[0], {}
                )

            self.assertTrue(handled)
            target = db.q1("SELECT status FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT invites_today,successful_today FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )
            self.assertEqual(target["status"], "invited")
            self.assertEqual(account["invites_today"], 1)
            self.assertEqual(account["successful_today"], 1)
            resend.assert_not_awaited()
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_ambiguous_invite_can_resolve_not_present_without_resend(self):
        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        db.ex(
            "UPDATE targets SET status='in_progress',account_id=? WHERE id=?",
            (account_id, target_id),
        )
        self.assertTrue(
            db.mark_invite_rpc_started(
                target_id,
                account_id,
                policy.invite_verification_note("invite_rpc=ambiguous"),
                attempted_at=1,
            )
        )
        resend = AsyncMock()
        try:
            with (
                patch.object(services.context, "resolve",
                    AsyncMock(return_value=(object(), object(), object())),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=(
                        "not_member",
                        "Telegram не подтвердил присутствие пользователя",
                        "not_present",
                    )),
                ),
                patch.object(services.gateway, "invite_one", resend),
            ):
                handled = await services.verification.retry_pending(
                    campaign_id, account_id, {}
                )

            target = db.q1("SELECT status,error FROM targets WHERE id=?", (target_id,))
            account = db.q1(
                "SELECT invites_today,successful_today FROM accounts WHERE id=?",
                (account_id,),
            )
            confirmation = db.q1(
                "SELECT result FROM invite_confirmations WHERE target_id=?",
                (target_id,),
            )
            self.assertTrue(handled)
            self.assertEqual(target["status"], "failed")
            self.assertIn("не подтвердил", target["error"])
            self.assertEqual(confirmation["result"], "not_present")
            self.assertEqual(account["invites_today"], 0)
            self.assertEqual(account["successful_today"], 0)
            resend.assert_not_awaited()
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_cancel_after_durable_marker_recovers_by_membership_only(self):
        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        rpc_started = asyncio.Event()
        never_finishes = asyncio.Event()

        async def hanging_invite(*_args):
            rpc_started.set()
            await never_finishes.wait()

        invite = AsyncMock(side_effect=hanging_invite)
        task = None
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.scheduler, "reserve_account_slot",
                    AsyncMock(return_value=int(time.time()) + 14400),
                ),
                patch.object(services.gateway, "invite_one", invite),
            ):
                task = asyncio.create_task(
                    services.worker.run(campaign_id, account_id, asyncio.Event())
                )
                await asyncio.wait_for(rpc_started.wait(), timeout=0.5)
                armed = db.q1(
                    "SELECT status,error FROM targets WHERE id=?", (target_id,)
                )
                self.assertEqual(armed["status"], "verifying")
                self.assertTrue(
                    armed["error"].startswith(policy.INVITE_RPC_DURABLE_MARKER)
                )
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            # Имитируем новый процесс: он видит durable marker и имеет право
            # только проверить членство, но не повторить Invite RPC.
            inviting.STATE[campaign_id] = {
                "target_entity_by_account": {account_id: object()},
                "workers": {},
            }
            resend = AsyncMock()
            with (
                patch.object(services.context, "resolve",
                    AsyncMock(return_value=(object(), object(), object())),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=("present", "", "confirmed")),
                ),
                patch.object(services.gateway, "invite_one", resend),
            ):
                handled = await services.verification.retry_pending(
                    campaign_id, account_id, {}
                )

            self.assertTrue(handled)
            self.assertEqual(
                db.q1("SELECT status FROM targets WHERE id=?", (target_id,))["status"],
                "invited",
            )
            self.assertEqual(invite.await_count, 1)
            resend.assert_not_awaited()
        finally:
            if task is not None and not task.done():
                task.cancel()
            inviting.STATE.pop(campaign_id, None)

    async def test_terminal_single_target_does_not_wait_for_future_slot(self):
        campaign_id, target_id = self._campaign_with_target()
        invite = AsyncMock(return_value=None)
        future_slot = int(time.time()) + 14400
        try:
            with (
                patch.object(accounts, "get_client", AsyncMock(return_value=object())),
                patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
                patch.object(services.gateway, "membership_state_once",
                    AsyncMock(return_value=("not_member", "")),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=("present", "", "confirmed")),
                ),
                patch.object(services.scheduler, "reserve_account_slot",
                    AsyncMock(return_value=future_slot),
                ),
                patch.object(services.gateway, "invite_one", invite),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, self.account_ids[0], asyncio.Event()
                    ),
                    timeout=0.5,
                )

            self.assertEqual(
                db.q1("SELECT status FROM targets WHERE id=?", (target_id,))["status"],
                "invited",
            )
            self.assertEqual(invite.await_count, 1)
        finally:
            inviting.STATE.pop(campaign_id, None)

    async def test_reconciled_single_target_does_not_wait_for_future_slot(self):
        campaign_id, target_id = self._campaign_with_target()
        account_id = self.account_ids[0]
        db.ex(
            "UPDATE targets SET status='in_progress',account_id=? WHERE id=?",
            (account_id, target_id),
        )
        self.assertTrue(
            db.mark_invite_rpc_started(
                target_id,
                account_id,
                policy.invite_verification_note("invite_rpc=ambiguous"),
                attempted_at=1,
            )
        )
        db.ex(
            "UPDATE accounts SET next_attempt_at=? WHERE id=?",
            (int(time.time()) + 14400, account_id),
        )
        resend = AsyncMock()
        try:
            with (
                patch.object(services.context, "resolve",
                    AsyncMock(return_value=(object(), object(), object())),
                ),
                patch.object(services.verification, "verify",
                    AsyncMock(return_value=("present", "", "confirmed")),
                ),
                patch.object(services.gateway, "invite_one", resend),
            ):
                await asyncio.wait_for(
                    services.worker.run(
                        campaign_id, account_id, asyncio.Event()
                    ),
                    timeout=0.5,
                )

            self.assertEqual(
                db.q1("SELECT status FROM targets WHERE id=?", (target_id,))["status"],
                "invited",
            )
            resend.assert_not_awaited()
        finally:
            inviting.STATE.pop(campaign_id, None)


if __name__ == "__main__":
    unittest.main()
