import tempfile
import time
import unittest
from pathlib import Path

from app import accounts, db
from app.config import SILENT_LOSS_RESTRICT_THRESHOLD


class PoolHygieneTests(unittest.TestCase):
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

    def _account(self, phone: str, proxy: str, can_invite: int = 1) -> int:
        return db.ex(
            """
            INSERT INTO accounts
                (label, phone, session_name, proxy, status, can_invite, created_at)
            VALUES (?, ?, ?, ?, 'authorized', ?, 0)
            """,
            (phone, phone, "s_" + phone[-4:], proxy, can_invite),
        )

    def test_proxy_endpoint_ignores_credentials(self):
        self.assertEqual(
            accounts.proxy_endpoint("socks5://u:p@Host.Example:1080"),
            "host.example:1080",
        )

    def test_duplicate_invite_proxy_is_rejected(self):
        self._account("+1001", "socks5://a:b@1.2.3.4:1080")
        with self.assertRaises(accounts.AuthError):
            accounts.assert_unique_invite_proxy("socks5://other:x@1.2.3.4:1080")

    def test_same_proxy_allowed_for_parse_only_account(self):
        self._account("+1001", "socks5://a:b@1.2.3.4:1080", can_invite=1)
        accounts.assert_unique_invite_proxy(
            "socks5://a:b@1.2.3.4:1080", can_invite=False
        )

    def test_silent_losses_without_confirmed_restrict_account(self):
        account_id = self._account("+2002", "socks5://u:p@5.6.7.8:1080")
        campaign_id = db.ex(
            "INSERT INTO campaigns (name,target_chat_id,status,created_at) "
            "VALUES ('c',1,'paused',0)"
        )
        now = int(time.time())
        for idx in range(SILENT_LOSS_RESTRICT_THRESHOLD):
            target_id = db.ex(
                """
                INSERT INTO targets
                    (campaign_id,user_id,username,status,account_id,attempted_at)
                VALUES (?,?,?,'failed',?,?)
                """,
                (campaign_id, 1000 + idx, "u%d" % idx, account_id, now),
            )
            db.ex(
                """
                INSERT INTO invite_confirmations
                    (target_id,checked_at,result,member_count)
                VALUES (?,?, 'not_present', 0)
                """,
                (target_id, now),
            )
            reason = accounts.register_delivery_outcome(account_id, "unconfirmed")
            if idx + 1 < SILENT_LOSS_RESTRICT_THRESHOLD:
                self.assertIsNone(reason)
        account = db.row_to_dict(
            db.q1("SELECT * FROM accounts WHERE id=?", (account_id,))
        )
        self.assertTrue(account["invite_restricted"])
        self.assertIn("Тихие потери", account["invite_restriction_reason"])

    def test_confirmed_delivery_prevents_silent_loss_restrict(self):
        account_id = self._account("+3003", "socks5://u:p@9.9.9.9:1080")
        campaign_id = db.ex(
            "INSERT INTO campaigns (name,target_chat_id,status,created_at) "
            "VALUES ('c',1,'paused',0)"
        )
        now = int(time.time())
        ok = db.ex(
            """
            INSERT INTO targets
                (campaign_id,user_id,username,status,account_id,attempted_at)
            VALUES (?,?,?,'invited',?,?)
            """,
            (campaign_id, 1, "ok", account_id, now),
        )
        db.ex(
            "INSERT INTO invite_confirmations (target_id,checked_at,result,member_count) "
            "VALUES (?,?,'confirmed',1)",
            (ok, now),
        )
        for idx in range(SILENT_LOSS_RESTRICT_THRESHOLD):
            target_id = db.ex(
                """
                INSERT INTO targets
                    (campaign_id,user_id,username,status,account_id,attempted_at)
                VALUES (?,?,?,'failed',?,?)
                """,
                (campaign_id, 2000 + idx, "x%d" % idx, account_id, now),
            )
            db.ex(
                "INSERT INTO invite_confirmations (target_id,checked_at,result,member_count) "
                "VALUES (?,?,'not_present',0)",
                (target_id, now),
            )
            self.assertIsNone(
                accounts.register_delivery_outcome(account_id, "unconfirmed")
            )
        account = db.row_to_dict(
            db.q1("SELECT * FROM accounts WHERE id=?", (account_id,))
        )
        self.assertFalse(bool(account["invite_restricted"]))


if __name__ == "__main__":
    unittest.main()
