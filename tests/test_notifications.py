from datetime import date
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from app import db, inviting
from app.infrastructure.bot import client, reports, updates


class NotificationReportTests(unittest.IsolatedAsyncioTestCase):
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
                (label, phone, session_name, status, daily_limit, min_delay,
                 max_delay, created_at, counter_day, next_attempt_at)
            VALUES (?, ?, ?, 'authorized', 5, 21600, 21600, ?, ?, ?)
            """,
            (
                "Первый аккаунт",
                "+10000000000",
                "notifications_session",
                int(time.time()),
                date.today().isoformat(),
                int(time.time()) + 21600,
            ),
        )
        self.campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name, target_chat_id, settings, status, created_at)
            VALUES (?, ?, ?, 'draft', ?)
            """,
            (
                "6 часов вторая смена",
                123,
                '{"account_ids":[%d]}' % self.account_id,
                int(time.time()),
            ),
        )
        self.target_id = db.ex(
            """
            INSERT INTO targets
                (campaign_id, user_id, username, display, status, account_id, attempted_at)
            VALUES (?, ?, ?, ?, 'invited', ?, ?)
            """,
            (
                self.campaign_id,
                77,
                "target",
                "Target",
                self.account_id,
                int(time.time()),
            ),
        )

    def tearDown(self):
        inviting.STATE.clear()
        inviting.RUNNERS.clear()
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        self.tmp.cleanup()

    def test_attempt_message_contains_event_and_current_status(self):
        text = reports.attempt_text({
            "campaign_id": self.campaign_id,
            "account_id": self.account_id,
            "target_id": self.target_id,
            "user_id": 77,
            "username": "target",
            "display": "Target",
            "outcome": "invited",
            "next_attempt_at": int(time.time()) + 21600,
            "attempted_at": int(time.time()),
        })

        self.assertIn("Отработал аккаунт", text)
        self.assertIn("Кампания: 6 часов вторая смена", text)
        self.assertIn("Аккаунт: Первый аккаунт", text)
        self.assertIn("Результат: пользователь приглашён", text)
        self.assertIn("Следующая попытка:", text)
        self.assertIn("МСК", text)

    def test_draft_report_is_not_shown_as_failed_campaign(self):
        text = reports.report_text()
        self.assertIn("6 часов вторая смена — 📝 черновик", text)
        self.assertNotIn("🔴 нет работающих аккаунтов", text)

    def test_connection_failure_message_does_not_require_target(self):
        text = reports.attempt_text({
            "campaign_id": self.campaign_id,
            "account_id": self.account_id,
            "target_id": 0,
            "user_id": 0,
            "username": None,
            "display": None,
            "outcome": "connection_error",
            "error": "Тайм-аут подключения; проверьте прокси",
            "next_attempt_at": 0,
            "attempted_at": int(time.time()),
        })

        self.assertIn("Сбой аккаунта", text)
        self.assertIn("проверьте прокси", text)
        self.assertIn("Причина: Тайм-аут подключения", text)
        self.assertNotIn("Цель:", text)

    def test_failed_or_cooled_down_worker_is_not_counted_as_active(self):
        campaign = db.row_to_dict(db.q1(
            "SELECT * FROM campaigns WHERE id=?", (self.campaign_id,)
        ))
        inviting.STATE[self.campaign_id] = {
            "workers": {self.account_id: {"state": "сбой подключения — проверьте прокси"}}
        }
        self.assertEqual(
            reports.campaign_worker_counts(campaign, running=True),
            (0, 1),
        )

        inviting.STATE[self.campaign_id]["workers"][self.account_id]["state"] = (
            "пауза 60 мин"
        )
        db.ex(
            "UPDATE accounts SET cooldown_until=? WHERE id=?",
            (int(time.time()) + 3600, self.account_id),
        )
        self.assertEqual(
            reports.campaign_worker_counts(campaign, running=True),
            (0, 1),
        )

    async def test_status_command_requests_fresh_report(self):
        send_report = AsyncMock()
        with patch.object(reports, "send_report", send_report):
            await updates.process_update(
                "token",
                12345,
                {"message": {"chat": {"id": 12345}, "text": "/status"}},
            )
        send_report.assert_awaited_once_with()

    async def test_refresh_button_acknowledges_and_requests_report(self):
        send_report = AsyncMock()
        with (
            patch.object(reports, "send_report", send_report),
            patch.object(client, "request") as bot_request,
            patch.object(updates.asyncio, "to_thread", AsyncMock(
                side_effect=lambda operation, *args: operation(*args)
            )),
        ):
            await updates.process_update(
                "token",
                12345,
                {
                    "callback_query": {
                        "id": "callback-1",
                        "data": updates.BOT_REFRESH_CALLBACK,
                        "message": {"chat": {"id": 12345}},
                    }
                },
            )
        bot_request.assert_called_once_with(
            "token",
            "answerCallbackQuery",
            {"callback_query_id": "callback-1", "text": "Обновляю данные"},
        )
        send_report.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
