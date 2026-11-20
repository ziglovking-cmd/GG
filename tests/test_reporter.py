import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app import reporter


class ReporterFormattingTests(unittest.TestCase):
    def _create_confirmation_database(
        self, db_path: Path, *, campaign_status: str = "running"
    ) -> None:
        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            CREATE TABLE campaigns (
                id INTEGER PRIMARY KEY, target_chat_id INTEGER, status TEXT
            );
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY, invites_today INTEGER,
                successful_today INTEGER, counter_day TEXT,
                next_attempt_at INTEGER
            );
            CREATE TABLE targets (
                id INTEGER PRIMARY KEY, campaign_id INTEGER, user_id INTEGER,
                resolved_user_id INTEGER, username TEXT, display TEXT,
                status TEXT, error TEXT, account_id INTEGER, attempted_at INTEGER
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, level TEXT,
                scope TEXT, campaign_id INTEGER, account_id INTEGER, message TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO campaigns VALUES (1,100,?)", (campaign_status,)
        )
        connection.execute(
            "INSERT INTO accounts VALUES (7,0,0,?,9999999999)",
            (datetime.now().date().isoformat(),),
        )
        connection.execute(
            """
            INSERT INTO targets VALUES
                (1,1,10,10,'target','Target','verifying',?,7,1)
            """,
            ("запрос отправлен, проверяю фактическое присутствие",),
        )
        connection.commit()
        connection.close()

    def test_invited_target_waits_for_membership_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE campaigns (
                    id INTEGER PRIMARY KEY, target_chat_id INTEGER, status TEXT
                );
                CREATE TABLE targets (
                    id INTEGER PRIMARY KEY, campaign_id INTEGER, user_id INTEGER,
                    username TEXT, status TEXT, error TEXT
                );
                INSERT INTO campaigns VALUES (1,100,'running');
                """
            )
            connection.execute(
                """
                INSERT INTO targets
                    (id,campaign_id,user_id,username,status)
                VALUES (1,1,10,'target','pending')
                """
            )
            connection.commit()
            connection.close()

            with patch.object(reporter, "DB_PATH", db_path):
                reporter._ensure_invite_confirmation_schema()
                connection = sqlite3.connect(db_path)
                connection.execute("UPDATE targets SET status='invited' WHERE id=1")
                row = connection.execute(
                    "SELECT status,error FROM targets WHERE id=1"
                ).fetchone()
                self.assertEqual(row[0], "verifying")
                self.assertEqual(row[1], reporter.INVITE_VERIFY_MARKER)

                connection.execute(
                    """
                    INSERT INTO invite_confirmations
                        (target_id,checked_at,result,member_count)
                    VALUES (1,1,'confirmed',10)
                    """
                )
                connection.execute("UPDATE targets SET status='invited' WHERE id=1")
                self.assertEqual(
                    connection.execute(
                        "SELECT status FROM targets WHERE id=1"
                    ).fetchone()[0],
                    "invited",
                )
                connection.close()

    def test_resolved_identity_never_falls_back_to_recycled_username(self):
        person = {
            "user_id": -1,
            "resolved_user_id": 111,
            "username": "recycled_name",
        }
        self.assertFalse(
            reporter._present(person, ({"222"}, {"recycled_name"}))
        )
        self.assertTrue(
            reporter._present(person, ({"111"}, set()))
        )
        unresolved = {
            "user_id": 0,
            "resolved_user_id": None,
            "username": "recycled_name",
        }
        self.assertTrue(
            reporter._present(unresolved, (set(), {"recycled_name"}))
        )

    def test_parallel_claim_trigger_blocks_second_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE campaigns (
                    id INTEGER PRIMARY KEY, target_chat_id INTEGER, status TEXT
                );
                CREATE TABLE targets (
                    id INTEGER PRIMARY KEY, campaign_id INTEGER, user_id INTEGER,
                    username TEXT, status TEXT, error TEXT
                );
                INSERT INTO campaigns VALUES (13,100,'running');
                INSERT INTO campaigns VALUES (14,100,'running');
                INSERT INTO targets VALUES (1,13,10,'same','pending',NULL);
                INSERT INTO targets VALUES (2,14,10,'same','pending',NULL);
                """
            )
            connection.commit()
            connection.close()

            with patch.object(reporter, "DB_PATH", db_path):
                reporter._ensure_invite_confirmation_schema()

            connection = sqlite3.connect(db_path)
            connection.execute("UPDATE targets SET status='in_progress' WHERE id=1")
            connection.execute("UPDATE targets SET status='in_progress' WHERE id=2")
            statuses = dict(connection.execute(
                "SELECT id,status FROM targets ORDER BY id"
            ).fetchall())
            connection.close()
            self.assertEqual(statuses[1], "in_progress")
            self.assertEqual(statuses[2], "pending")

    def test_confirmation_counts_only_verified_member(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.db"
            self._create_confirmation_database(db_path, campaign_status="paused")
            with (
                patch.object(reporter, "DB_PATH", db_path),
                patch.object(reporter, "TARGET_CHAT_ID", 100),
                patch.object(reporter, "INVITE_CONFIRM_DELAY_SECONDS", 30),
                patch.object(
                    reporter,
                    "_fresh_membership",
                    return_value=([{"user_id": "10", "username": "target"}], 100, 7),
                ),
            ):
                reporter._ensure_invite_confirmation_schema()
                changed = reporter._confirm_pending_invites(
                    reporter._default_state(), 100
                )

            connection = sqlite3.connect(db_path)
            target = connection.execute(
                "SELECT status,error FROM targets WHERE id=1"
            ).fetchone()
            account = connection.execute(
                "SELECT invites_today,successful_today FROM accounts WHERE id=7"
            ).fetchone()
            confirmation = connection.execute(
                "SELECT result FROM invite_confirmations WHERE target_id=1"
            ).fetchone()
            event = connection.execute(
                "SELECT message FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            connection.close()

            self.assertTrue(changed)
            self.assertEqual(target, ("invited", None))
            self.assertEqual(account, (1, 1))
            self.assertEqual(confirmation[0], "confirmed")
            self.assertEqual(event[0], "Приглашён @target")

    def test_stale_candidate_cannot_double_count_core_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.db"
            self._create_confirmation_database(db_path)
            with patch.object(reporter, "DB_PATH", db_path):
                reporter._ensure_invite_confirmation_schema()
                with reporter._write_connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """
                        INSERT INTO invite_confirmations
                            (target_id,checked_at,result,member_count)
                        VALUES (1,90,'confirmed',10)
                        """
                    )
                    connection.execute(
                        "UPDATE targets SET status='invited',error=NULL WHERE id=1"
                    )
                    connection.execute(
                        """
                        UPDATE accounts
                        SET invites_today=1,successful_today=1
                        WHERE id=7
                        """
                    )

                stale_target = {
                    "id": 1,
                    "campaign_id": 1,
                    "user_id": 10,
                    "resolved_user_id": 10,
                    "username": "target",
                    "status": "verifying",
                    "account_id": 7,
                }
                with reporter._write_connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    changed = reporter._confirm_present_target(
                        connection, stale_target, 11, 100
                    )

            connection = sqlite3.connect(db_path)
            target = connection.execute(
                "SELECT status FROM targets WHERE id=1"
            ).fetchone()
            account = connection.execute(
                "SELECT invites_today,successful_today FROM accounts WHERE id=7"
            ).fetchone()
            confirmations = connection.execute(
                "SELECT COUNT(*),MAX(checked_at) FROM invite_confirmations WHERE target_id=1"
            ).fetchone()
            events = connection.execute("SELECT COUNT(*) FROM events").fetchone()
            connection.close()

            self.assertFalse(changed)
            self.assertEqual(target[0], "invited")
            self.assertEqual(account, (1, 1))
            self.assertEqual(confirmations, (1, 90))
            self.assertEqual(events[0], 0)

    def test_stale_duplicate_rejection_cannot_demote_core_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.db"
            self._create_confirmation_database(db_path)
            with patch.object(reporter, "DB_PATH", db_path):
                reporter._ensure_invite_confirmation_schema()
                with reporter._write_connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """
                        INSERT INTO invite_confirmations
                            (target_id,checked_at,result,member_count)
                        VALUES (1,90,'confirmed',10)
                        """
                    )
                    connection.execute(
                        "UPDATE targets SET status='invited',error=NULL WHERE id=1"
                    )
                    connection.execute(
                        """
                        UPDATE accounts
                        SET invites_today=1,successful_today=1
                        WHERE id=7
                        """
                    )

                stale_target = {
                    "id": 1,
                    "campaign_id": 1,
                    "user_id": 10,
                    "resolved_user_id": 10,
                    "username": "target",
                    "status": "verifying",
                    "account_id": 7,
                }
                with reporter._write_connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    changed = reporter._reject_unconfirmed_target(
                        connection,
                        stale_target,
                        "skipped",
                        "дубль подтверждённого приглашения",
                        "duplicate",
                        11,
                        100,
                    )

            connection = sqlite3.connect(db_path)
            target = connection.execute(
                "SELECT status,error FROM targets WHERE id=1"
            ).fetchone()
            account = connection.execute(
                "SELECT invites_today,successful_today FROM accounts WHERE id=7"
            ).fetchone()
            confirmation = connection.execute(
                "SELECT result,checked_at FROM invite_confirmations WHERE target_id=1"
            ).fetchone()
            events = connection.execute("SELECT COUNT(*) FROM events").fetchone()
            connection.close()

            self.assertFalse(changed)
            self.assertEqual(target, ("invited", None))
            self.assertEqual(account, (1, 1))
            self.assertEqual(confirmation, ("confirmed", 90))
            self.assertEqual(events[0], 0)

    def test_snapshot_absence_does_not_create_false_negative(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.db"
            self._create_confirmation_database(db_path)
            with (
                patch.object(reporter, "DB_PATH", db_path),
                patch.object(reporter, "TARGET_CHAT_ID", 100),
                patch.object(reporter, "INVITE_CONFIRM_DELAY_SECONDS", 30),
                patch.object(
                    reporter,
                    "_fresh_membership",
                    return_value=([{"user_id": "99", "username": "other"}], 100, 7),
                ),
            ):
                reporter._ensure_invite_confirmation_schema()
                changed = reporter._confirm_pending_invites(
                    reporter._default_state(), 100
                )

            connection = sqlite3.connect(db_path)
            target = connection.execute(
                "SELECT status,error FROM targets WHERE id=1"
            ).fetchone()
            account = connection.execute(
                """
                SELECT invites_today,successful_today,next_attempt_at
                FROM accounts WHERE id=7
                """
            ).fetchone()
            confirmation = connection.execute(
                "SELECT result FROM invite_confirmations WHERE target_id=1"
            ).fetchone()
            connection.close()

            self.assertTrue(changed)
            self.assertEqual(target[0], "verifying")
            self.assertIn("проверяю фактическое присутствие", target[1])
            self.assertEqual(account, (0, 0, 9999999999))
            self.assertIsNone(confirmation)

    def test_reporter_does_not_promote_legacy_verifying_without_precheck(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.db"
            self._create_confirmation_database(db_path)
            connection = sqlite3.connect(db_path)
            connection.execute(
                "UPDATE targets SET error='старый успех ожидает подтверждения' WHERE id=1"
            )
            connection.commit()
            connection.close()

            with (
                patch.object(reporter, "DB_PATH", db_path),
                patch.object(reporter, "TARGET_CHAT_ID", 100),
                patch.object(reporter, "INVITE_CONFIRM_DELAY_SECONDS", 30),
                patch.object(
                    reporter,
                    "_fresh_membership",
                    return_value=([{"user_id": "10", "username": "target"}], 100, 7),
                ) as membership,
            ):
                reporter._ensure_invite_confirmation_schema()
                changed = reporter._confirm_pending_invites(
                    reporter._default_state(), 100
                )

            connection = sqlite3.connect(db_path)
            target = connection.execute(
                "SELECT status FROM targets WHERE id=1"
            ).fetchone()
            connection.close()
            self.assertFalse(changed)
            self.assertEqual(target[0], "verifying")
            membership.assert_not_called()

    def test_parallel_pending_targets_are_split_between_campaigns(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE campaigns (
                    id INTEGER PRIMARY KEY, target_chat_id INTEGER, status TEXT
                );
                CREATE TABLE targets (
                    id INTEGER PRIMARY KEY, campaign_id INTEGER, user_id INTEGER,
                    username TEXT, status TEXT, account_id INTEGER,
                    error TEXT, attempted_at INTEGER
                );
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY, ts INTEGER, level TEXT, scope TEXT,
                    message TEXT
                );
                INSERT INTO campaigns VALUES (13,4396252688,'running');
                INSERT INTO campaigns VALUES (14,4396252688,'running');
                INSERT INTO targets VALUES (1,13,100,'same_user','pending',NULL,NULL,NULL);
                INSERT INTO targets VALUES (2,14,100,'same_user','pending',NULL,NULL,NULL);
                """
            )
            connection.commit()
            connection.close()

            with (
                patch.object(reporter, "DB_PATH", db_path),
                patch.object(reporter, "TARGET_CHAT_ID", 4396252688),
            ):
                skipped = reporter._dedupe_running_targets()

            connection = sqlite3.connect(db_path)
            statuses = [
                row[0] for row in connection.execute(
                    "SELECT status FROM targets ORDER BY id"
                ).fetchall()
            ]
            connection.close()
            self.assertEqual(skipped, 1)
            self.assertEqual(statuses.count("pending"), 1)
            self.assertEqual(statuses.count("skipped"), 1)

    def test_current_campaigns_excludes_paused_campaigns(self):
        campaigns = [
            {
                "id": 13, "name": "Пауза", "target_chat_id": 100,
                "status": "paused", "running": False,
            },
            {
                "id": 14, "name": "Работает", "target_chat_id": 100,
                "status": "running", "running": True,
            },
        ]
        with (
            patch.object(reporter, "TARGET_CHAT_ID", 100),
            patch.object(reporter, "_api_request", return_value=campaigns),
        ):
            current = reporter._current_campaigns()

        self.assertEqual([item["id"] for item in current], [14])

    def test_paused_campaign_state_is_removed_without_bot_report(self):
        state = reporter._default_state()
        state["pending_waves"] = {"13": {"last_activity_at": 1}}
        state["campaign_health"] = {"13": {"running": False}}

        self.assertTrue(reporter._prune_inactive_campaign_state(state, []))
        self.assertEqual(state["pending_waves"], {})
        self.assertEqual(state["campaign_health"], {})
        self.assertFalse(reporter._cycle_ready(state, int(time.time())))
        with (
            patch.object(reporter, "_current_campaigns", return_value=[]),
            patch.object(reporter, "_send_bot_message") as send,
        ):
            reporter._send_current_report(state, int(time.time()))
        send.assert_not_called()

    def test_cycle_report_contains_counts_users_statuses_and_next_windows(self):
        now = int(time.time())
        campaigns = [
            {"id": 8, "name": "6 часов"},
            {"id": 12, "name": "6 часов вторая смена"},
        ]
        details = {
            8: {
                "running": True,
                "settings": {"account_ids": [5, 6]},
                "workers": [
                    {"account_id": 5, "state": "до следующей попытки 360 мин"},
                    {"account_id": 6, "state": "сбой подключения — проверьте прокси"},
                ],
            },
            12: {
                "running": True,
                "settings": {"account_ids": [8]},
                "workers": [
                    {"account_id": 8, "state": "до следующей попытки 355 мин"},
                ],
            },
        }
        accounts = [
            {
                "id": 5, "label": "Первый", "status": "authorized", "can_invite": 1,
                "cooldown_until": 0, "next_attempt_at": now + 21600,
            },
            {
                "id": 6, "label": "Второй", "status": "authorized", "can_invite": 1,
                "cooldown_until": 0, "next_attempt_at": 0,
            },
            {
                "id": 8, "label": "Третий", "status": "authorized", "can_invite": 1,
                "cooldown_until": 0, "next_attempt_at": now + 21000,
            },
        ]
        waves = {
            "8": {
                "invited": [
                    {"id": 1, "user_id": 77, "username": "alice", "display": "Alice"},
                    {"id": 2, "user_id": 78, "username": "bob", "display": "Bob"},
                ]
            },
            "12": {"invited": []},
        }

        text = reporter._build_cycle_report(campaigns, details, accounts, waves, now)

        self.assertIn("Компания 6 часов", text)
        self.assertIn("Результат: ✅ цикл отработал", text)
        self.assertIn("Пригласили конкретно — 2 человек", text)
        self.assertIn("@alice", text)
        self.assertIn("@bob", text)
        self.assertIn("✅ Первый", text)
        self.assertIn("❌ Второй — сбой подключения", text)
        self.assertIn("Компания 6 часов вторая смена", text)
        self.assertIn("Следующий интервал приглашения", text)
        self.assertIn("МСК", text)

    def test_departures_match_by_username_when_ids_differ(self):
        previous = [
            {"user_id": "100", "username": "kept"},
            {"user_id": "200", "username": "left_user"},
        ]
        current = [
            {"user_id": "999", "username": "kept"},
        ]
        invited_today = []
        all_invited = [
            {"user_id": "-1", "username": "kept"},
            {"user_id": "-2", "username": "left_user"},
        ]

        left = reporter._daily_departures(previous, current, invited_today, all_invited)

        self.assertEqual(len(left), 1)
        self.assertEqual(left[0]["username"], "left_user")

    def test_daily_report_is_due_only_at_2359_moscow(self):
        state = {"last_daily_date": None}
        due = datetime(2026, 9, 25, 23, 59, tzinfo=reporter.MOSCOW_TZ)
        early = datetime(2026, 9, 25, 23, 58, tzinfo=reporter.MOSCOW_TZ)

        self.assertTrue(reporter._daily_due(state, due))
        self.assertFalse(reporter._daily_due(state, early))
        state["last_daily_date"] = "2026-09-25"
        self.assertFalse(reporter._daily_due(state, due))

    def test_failure_transition_creates_one_grouped_wave(self):
        now = int(time.time())
        state = reporter._default_state()
        campaigns = [{"id": 8, "name": "6 часов", "status": "running"}]
        accounts = [{
            "id": 5,
            "label": "Первый",
            "status": "authorized",
            "can_invite": 1,
            "cooldown_until": 0,
        }]
        healthy = {
            8: {
                "running": True,
                "status": "running",
                "settings": {"account_ids": [5]},
                "workers": [{
                    "account_id": 5,
                    "state": "до следующей попытки 360 мин",
                }],
            }
        }
        failed = {
            8: {
                "running": True,
                "status": "running",
                "settings": {"account_ids": [5]},
                "workers": [{
                    "account_id": 5,
                    "state": "сбой подключения — проверьте прокси",
                }],
            }
        }

        self.assertTrue(reporter._update_failure_waves(
            state, campaigns, healthy, accounts, now
        ))
        self.assertEqual(state["pending_waves"], {})
        self.assertTrue(reporter._update_failure_waves(
            state, campaigns, failed, accounts, now + 30
        ))
        self.assertTrue(state["pending_waves"]["8"]["failure_event"])
        self.assertEqual(state["pending_waves"]["8"]["attempts"], 0)
        self.assertFalse(reporter._update_failure_waves(
            state, campaigns, failed, accounts, now + 60
        ))

    def test_reporter_prefers_private_bot_config(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "reporter_bot.json"
            config_path.write_text(json.dumps({
                "bot_token": "123456:private-token",
                "bot_chat_id": 987654,
            }), "utf-8")
            with (
                patch.object(reporter, "BOT_CONFIG_PATH", config_path),
                patch.object(reporter, "get_bot_settings", side_effect=AssertionError),
                patch.object(reporter, "get_bot_recipient", side_effect=AssertionError),
                patch.object(
                    reporter.urllib.request, "urlopen", return_value=Response()
                ) as urlopen,
            ):
                reporter._send_bot_message("Итоговый отчёт")

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertIn("123456:private-token", request.full_url)
        self.assertEqual(payload["chat_id"], 987654)
        self.assertEqual(payload["text"], "Итоговый отчёт")

    def test_reporter_sends_the_same_report_to_all_private_recipients(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "reporter_bot.json"
            config_path.write_text(json.dumps({
                "bot_token": "123456:private-token",
                "bot_chat_id": 987654,
                "bot_chat_ids": [987654, 867860646],
            }), "utf-8")
            with (
                patch.object(reporter, "BOT_CONFIG_PATH", config_path),
                patch.object(reporter, "get_bot_settings", side_effect=AssertionError),
                patch.object(reporter, "get_bot_recipient", side_effect=AssertionError),
                patch.object(
                    reporter.urllib.request, "urlopen", return_value=Response()
                ) as urlopen,
            ):
                reporter._send_bot_message("Общий отчёт")

        self.assertEqual(urlopen.call_count, 2)
        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in urlopen.call_args_list
        ]
        self.assertEqual(
            [payload["chat_id"] for payload in payloads],
            [987654, 867860646],
        )
        self.assertTrue(all(payload["text"] == "Общий отчёт" for payload in payloads))

    def test_long_report_is_split_for_each_recipient(self):
        long_report = "Заголовок\n" + "\n".join(
            "Аккаунт %03d — работает" % number for number in range(300)
        )
        with (
            patch.object(reporter, "_bot_recipient_ids", return_value=[101, 202]),
            patch.object(reporter, "_bot_request", return_value={}) as request,
            patch.object(reporter, "BOT_COMMANDS_ENABLED", True),
        ):
            reporter._send_bot_message(long_report)

        chunks = reporter._split_bot_message(long_report)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 3500 for chunk in chunks))
        self.assertEqual(request.call_count, len(chunks) * 2)
        first_recipient = [
            call.args[1] for call in request.call_args_list[:len(chunks)]
        ]
        self.assertEqual("\n".join(payload["text"] for payload in first_recipient), long_report)
        self.assertNotIn("reply_markup", first_recipient[0])
        self.assertIn("reply_markup", first_recipient[-1])


if __name__ == "__main__":
    unittest.main()
