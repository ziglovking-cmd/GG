import asyncio
from datetime import date
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from app import accounts, db, inviting
from app.application.invitations import timing
from app.bootstrap import invitations as services
from app.domain import invitations as policy


class CampaignGapTests(unittest.IsolatedAsyncioTestCase):
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
                VALUES (?, ?, ?, 'authorized', 10, 600, 600, ?, ?)
                """,
                (f"test-{index}", f"+1000000000{index}", f"session-{index}",
                 0, date.today().isoformat()),
            ))
        self.campaign_id = self._campaign()

    def tearDown(self):
        inviting.set_attempt_notifier(None)
        services.runtime.campaign_locks.clear()
        for account_id in self.account_ids:
            services.runtime.account_locks.pop(account_id, None)
        inviting.STATE.pop(self.campaign_id, None)
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        self.tmp.cleanup()

    def _campaign(self, settings=None) -> int:
        return db.ex(
            """
            INSERT INTO campaigns (name, target_chat_id, settings, status, created_at)
            VALUES ('gap', 123, ?, 'running', 0)
            """,
            (json.dumps(settings or {}),),
        )

    def _next_invite_at(self, campaign_id=None) -> int:
        row = db.q1(
            "SELECT next_invite_at FROM campaigns WHERE id=?",
            (campaign_id or self.campaign_id,),
        )
        return int(row["next_invite_at"])

    async def test_first_reservation_is_immediate_and_books_15_to_25_minutes(self):
        before = int(time.time())
        reserved = await asyncio.wait_for(
            services.scheduler.reserve_campaign_slot(self.campaign_id, asyncio.Event(), {}),
            timeout=1,
        )
        self.assertGreaterEqual(reserved, before + 15 * 60)
        self.assertLessEqual(reserved, int(time.time()) + 25 * 60)
        self.assertEqual(self._next_invite_at(), reserved)

    async def test_other_account_waits_for_campaign_gap(self):
        first = await services.scheduler.reserve_campaign_slot(
            self.campaign_id, asyncio.Event(), {}
        )
        stop = asyncio.Event()
        info = {}
        second_task = asyncio.create_task(
            services.scheduler.reserve_campaign_slot(self.campaign_id, stop, info)
        )
        await asyncio.sleep(0.05)
        self.assertIn("очередь кампании", info["state"])
        self.assertIn("запрос ещё не отправлен", info["state"])
        stop.set()
        self.assertIsNone(await asyncio.wait_for(second_task, timeout=1))
        self.assertEqual(self._next_invite_at(), first)

    async def test_campaigns_have_independent_queues(self):
        other_id = self._campaign()
        await services.scheduler.reserve_campaign_slot(self.campaign_id, asyncio.Event(), {})
        reserved = await asyncio.wait_for(
            services.scheduler.reserve_campaign_slot(other_id, asyncio.Event(), {}),
            timeout=1,
        )
        self.assertIsNotNone(reserved)

    async def test_gap_can_be_overridden_in_campaign_settings(self):
        campaign_id = self._campaign({"invite_gap_min": 60, "invite_gap_max": 60})
        before = int(time.time())
        reserved = await services.scheduler.reserve_campaign_slot(campaign_id, asyncio.Event(), {})
        self.assertIn(reserved - before, (60, 61))

    async def test_release_does_not_clear_newer_reservation(self):
        reserved = await services.scheduler.reserve_campaign_slot(
            self.campaign_id, asyncio.Event(), {}
        )
        services.scheduler.release_campaign_slot(self.campaign_id, reserved - 1)
        self.assertEqual(self._next_invite_at(), reserved)
        services.scheduler.release_campaign_slot(self.campaign_id, reserved)
        self.assertEqual(self._next_invite_at(), 0)

    def _add_target(self, user_id: int) -> int:
        return db.ex(
            "INSERT INTO targets (campaign_id, user_id, username, display) "
            "VALUES (?, ?, ?, ?)",
            (self.campaign_id, user_id, "user%d" % user_id, "User"),
        )

    async def _run_worker_once(self, membership_states, verify_result):
        stop = asyncio.Event()
        inviting.STATE[self.campaign_id] = {
            "target_entity_by_account": {self.account_ids[0]: object()},
            "workers": {},
        }

        async def notifier(_payload):
            stop.set()

        inviting.set_attempt_notifier(notifier)
        with (
            patch.object(accounts, "get_client", AsyncMock(return_value=object())),
            patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
            patch.object(services.gateway, "membership_state_once",
                AsyncMock(side_effect=membership_states),
            ),
            patch.object(services.verification, "verify",
                AsyncMock(return_value=verify_result),
            ),
            patch.object(services.gateway, "invite_one", AsyncMock(return_value=None)) as invite,
        ):
            await asyncio.wait_for(
                services.worker.run(self.campaign_id, self.account_ids[0], stop),
                timeout=2,
            )
        return invite

    async def test_sent_invite_keeps_campaign_gap(self):
        self._add_target(77)
        before = int(time.time())
        invite = await self._run_worker_once(
            [("not_member", ""), ("not_member", "")],
            ("present", "", "confirmed"),
        )
        invite.assert_awaited_once()
        self.assertGreaterEqual(self._next_invite_at(), before + 15 * 60)

    async def test_worker_reconnects_after_waiting_in_campaign_queue(self):
        self._add_target(79)
        stale_client, fresh_client = object(), object()
        entity, peer = object(), object()
        resolve = AsyncMock(side_effect=[
            (stale_client, entity, peer),
            (fresh_client, entity, peer),
        ])
        checked_with = []

        async def membership(client, *_args):
            checked_with.append(client)
            return ("not_member", "")

        stop = asyncio.Event()
        inviting.STATE[self.campaign_id] = {"workers": {}}

        async def notifier(_payload):
            stop.set()

        inviting.set_attempt_notifier(notifier)
        with (
            patch.object(services.context, "resolve", resolve),
            patch.object(services.gateway, "membership_state_once", side_effect=membership),
            patch.object(services.verification, "verify",
                AsyncMock(return_value=("present", "", "confirmed")),
            ),
            patch.object(services.gateway, "invite_one", AsyncMock(return_value=None)) as invite,
        ):
            await asyncio.wait_for(
                services.worker.run(self.campaign_id, self.account_ids[0], stop),
                timeout=2,
            )
        self.assertEqual(resolve.await_count, 2)
        # Первая проверка — до очереди, вторая и сама отправка — уже через
        # новое соединение.
        self.assertEqual(checked_with, [stale_client, fresh_client])
        self.assertIs(invite.await_args.args[0], fresh_client)

    async def test_rejected_invite_releases_campaign_gap_before_next_target(self):
        self._add_target(81)
        self._add_target(82)
        stop = asyncio.Event()
        received = []
        inviting.STATE[self.campaign_id] = {"workers": {}}

        async def notifier(payload):
            received.append(payload)
            self.assertEqual(self._next_invite_at(), 0)
            self.assertEqual(payload["next_attempt_at"], 0)
            if len(received) == 2:
                stop.set()

        inviting.set_attempt_notifier(notifier)
        invite = AsyncMock(side_effect=policy.InviteNotAcceptedError("missing_invitees"))
        with (
            patch.object(services.context, "resolve", AsyncMock(
                return_value=(object(), object(), object()),
            )),
            patch.object(services.gateway, "membership_state_once", AsyncMock(
                return_value=("not_member", ""),
            )),
            patch.object(services.gateway, "invite_one", invite),
        ):
            await asyncio.wait_for(
                services.worker.run(self.campaign_id, self.account_ids[0], stop),
                timeout=1,
            )

        self.assertEqual(invite.await_count, 2)
        self.assertEqual([p["outcome"] for p in received], ["rejected", "rejected"])
        self.assertEqual(self._next_invite_at(), 0)

    async def test_same_worker_sends_two_successful_invites_after_both_intervals(self):
        target_ids = [self._add_target(83), self._add_target(84)]
        db.ex(
            "UPDATE campaigns SET settings=? WHERE id=?",
            (json.dumps({"invite_gap_min": 900, "invite_gap_max": 900}), self.campaign_id),
        )
        current_time = [int(time.time())]
        started_at = current_time[0]
        sent_at = []
        received = []
        stop = asyncio.Event()
        inviting.STATE[self.campaign_id] = {"workers": {}}

        async def advance_time(seconds, _stop):
            current_time[0] += seconds
            await asyncio.sleep(0)

        async def send(*_args):
            sent_at.append(current_time[0])

        async def notifier(payload):
            received.append(payload)
            if len(received) == 2:
                stop.set()

        inviting.set_attempt_notifier(notifier)
        with (
            patch.object(time, "time", side_effect=lambda: current_time[0]),
            patch.object(timing, "sleep", side_effect=advance_time),
            patch.object(services.context, "resolve", AsyncMock(
                return_value=(object(), object(), object()),
            )),
            patch.object(services.gateway, "membership_state_once", AsyncMock(
                return_value=("not_member", ""),
            )),
            patch.object(services.verification, "verify", AsyncMock(
                return_value=("present", "", "confirmed"),
            )),
            patch.object(services.gateway, "invite_one", side_effect=send),
        ):
            await asyncio.wait_for(
                services.worker.run(self.campaign_id, self.account_ids[0], stop),
                timeout=1,
            )

        self.assertEqual(sent_at, [started_at, started_at + 900])
        self.assertEqual([p["outcome"] for p in received], ["invited", "invited"])
        for target_id in target_ids:
            self.assertEqual(db.q1(
                "SELECT status FROM targets WHERE id=?", (target_id,),
            )["status"], "invited")
        account = db.q1(
            "SELECT invites_today,successful_today FROM accounts WHERE id=?",
            (self.account_ids[0],),
        )
        self.assertEqual(account["invites_today"], 2)
        self.assertEqual(account["successful_today"], 2)
        messages = [r["message"] for r in db.q(
            "SELECT message FROM events WHERE campaign_id=? ORDER BY id", (self.campaign_id,),
        )]
        self.assertEqual(sum("Ожидание общего интервала" in m for m in messages), 1)
        self.assertEqual(sum("Общий интервал кампании завершён" in m for m in messages), 1)

    async def test_cancel_while_waiting_in_queue_releases_account_reservation(self):
        self._add_target(80)
        # Очередь кампании занята на 10 минут вперёд — воркер будет ждать.
        busy_until = int(time.time()) + 600
        db.ex(
            "UPDATE campaigns SET next_invite_at=? WHERE id=?",
            (busy_until, self.campaign_id),
        )
        inviting.STATE[self.campaign_id] = {"workers": {}}
        resolve = AsyncMock(return_value=(object(), object(), object()))
        with (
            patch.object(services.context, "resolve", resolve),
            patch.object(services.gateway, "membership_state_once",
                AsyncMock(return_value=("not_member", "")),
            ),
            patch.object(services.gateway, "invite_one", AsyncMock(return_value=None)) as invite,
        ):
            task = asyncio.create_task(
                services.worker.run(
                    self.campaign_id, self.account_ids[0], asyncio.Event()
                )
            )
            await asyncio.sleep(0.1)
            reserved = db.q1(
                "SELECT next_attempt_at FROM accounts WHERE id=?",
                (self.account_ids[0],),
            )["next_attempt_at"]
            self.assertGreater(reserved, 0)
            worker = inviting.STATE[self.campaign_id]["workers"][self.account_ids[0]]
            self.assertIn("запрос ещё не отправлен", worker["state"])
            invite.assert_not_awaited()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        invite.assert_not_awaited()
        released = db.q1(
            "SELECT next_attempt_at FROM accounts WHERE id=?",
            (self.account_ids[0],),
        )["next_attempt_at"]
        self.assertEqual(released, 0)
        self.assertEqual(self._next_invite_at(), busy_until)

    async def test_user_already_in_chat_releases_campaign_gap(self):
        target_id = self._add_target(78)
        # Вторая проверка, сразу перед отправкой, находит человека в чате:
        # приглашение не отправлено, поэтому пауза кампании не нужна.
        states = [("not_member", ""), ("present", "")]

        async def stop_when_done(*_args, **_kwargs):
            return states.pop(0) if states else ("present", "")

        stop = asyncio.Event()
        inviting.STATE[self.campaign_id] = {
            "target_entity_by_account": {self.account_ids[0]: object()},
            "workers": {},
        }
        with (
            patch.object(accounts, "get_client", AsyncMock(return_value=object())),
            patch.object(services.gateway, "resolve_peer", AsyncMock(return_value=object())),
            patch.object(services.gateway, "membership_state_once", side_effect=stop_when_done),
            patch.object(services.gateway, "invite_one", AsyncMock(return_value=None)) as invite,
        ):
            await asyncio.wait_for(
                services.worker.run(self.campaign_id, self.account_ids[0], stop),
                timeout=2,
            )
        invite.assert_not_awaited()
        status = db.q1("SELECT status FROM targets WHERE id=?", (target_id,))["status"]
        self.assertEqual(status, "already")
        self.assertEqual(self._next_invite_at(), 0)


if __name__ == "__main__":
    unittest.main()
