"""MVP policy: jitter, phone geo, ranking, start gates."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app import accounts, db, mvp
from app.domain.invitations import humanized_delay_seconds, phone_country, speed_profile_bounds


class MvpHelpersTests(unittest.TestCase):
    def test_humanized_delay_stays_near_bounds(self):
        samples = [humanized_delay_seconds(100, 200) for _ in range(80)]
        self.assertTrue(all(70 <= value <= 240 for value in samples))
        self.assertGreater(max(samples), min(samples))

    def test_humanized_delay_exact_when_bounds_equal(self):
        self.assertEqual(humanized_delay_seconds(900, 900), 900)

    def test_phone_country_prefixes(self):
        self.assertEqual(phone_country("+79001234567"), "RU")
        self.assertEqual(phone_country("380501112233"), "UA")
        self.assertEqual(phone_country("+99999"), None)

    def test_speed_profile_bounds(self):
        low, high = speed_profile_bounds("cautious")
        self.assertLess(low, high)
        self.assertEqual(speed_profile_bounds("unknown")[0], speed_profile_bounds("cautious")[0])


class MvpGateTests(unittest.TestCase):
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

    def _account(self, **kwargs) -> int:
        defaults = dict(
            label="a",
            phone="+79001112233",
            session_name="s_" + kwargs.get("phone", "+79001112233")[-4:],
            proxy="socks5://u:p@10.0.0.1:1080",
            status="authorized",
            can_invite=1,
            warmup_done=1,
            proxy_country="RU",
            created_at=0,
        )
        defaults.update(kwargs)
        cols = ",".join(defaults.keys())
        marks = ",".join("?" for _ in defaults)
        return db.ex(
            "INSERT INTO accounts (%s) VALUES (%s)" % (cols, marks),
            tuple(defaults.values()),
        )

    def _campaign(self, account_ids, *, mode="hybrid", preflight="ready") -> dict:
        settings = {
            "account_ids": account_ids,
            "invite_mode": mode,
            "speed_profile": "cautious",
        }
        campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name,target_chat_id,settings,status,created_at,preflight_status)
            VALUES ('c',1,?,?,0,?)
            """,
            (json.dumps(settings), "draft", preflight),
        )
        return db.row_to_dict(db.q1("SELECT * FROM campaigns WHERE id=?", (campaign_id,)))

    def test_start_blocked_without_preflight(self):
        account_id = self._account()
        campaign = self._campaign([account_id], preflight="not_run")
        with self.assertRaises(mvp.MvpGateError):
            mvp.assert_campaign_start_allowed(campaign)

    def test_start_blocked_without_warmup(self):
        account_id = self._account(warmup_done=0)
        campaign = self._campaign([account_id])
        with self.assertRaises(mvp.MvpGateError) as ctx:
            mvp.assert_campaign_start_allowed(campaign)
        self.assertIn("прогрева", str(ctx.exception))

    def test_start_allowed_when_ready(self):
        account_id = self._account()
        campaign = self._campaign([account_id])
        gate = mvp.assert_campaign_start_allowed(campaign)
        self.assertEqual(gate["invite_mode"], "hybrid")
        self.assertEqual(gate["account_ids"], [account_id])

    def test_geo_mismatch_is_warning_not_block(self):
        account_id = self._account(proxy_country="DE")
        campaign = self._campaign([account_id])
        gate = mvp.assert_campaign_start_allowed(campaign)
        self.assertTrue(any("гео" in item.lower() or "≠" in item for item in gate["warnings"]))

    def test_rank_prefers_premium_and_hashes(self):
        weak = self._account(
            phone="+79000000001",
            session_name="s_0001",
            proxy="socks5://u:p@10.0.0.2:1080",
            is_premium=0,
        )
        strong = self._account(
            phone="+79000000002",
            session_name="s_0002",
            proxy="socks5://u:p@10.0.0.3:1080",
            is_premium=1,
        )
        db.ex(
            "INSERT INTO hashes (account_id,user_id,access_hash,updated_at) VALUES (?,?,?,0)",
            (strong, 42, 99),
        )
        ranked = mvp.rank_inviter_accounts([weak, strong])
        self.assertEqual(ranked[0], strong)

    def test_spambot_classifier(self):
        status, _ = accounts.classify_spambot_reply(
            "Good news, no limits are currently applied to your account"
        )
        self.assertEqual(status, "clean")
        status, _ = accounts.classify_spambot_reply("You are limited for spam")
        self.assertEqual(status, "limited")

    def test_mark_warmup(self):
        account_id = self._account(warmup_done=0)
        payload = accounts.mark_warmup(account_id, done=True, notes="ok")
        self.assertTrue(payload["warmup_done"])
        row = db.q1("SELECT warmup_done,warmup_notes FROM accounts WHERE id=?", (account_id,))
        self.assertEqual(int(row["warmup_done"]), 1)


class ConfigSilentLossTests(unittest.TestCase):
    def test_threshold_is_one(self):
        from app.config import SILENT_LOSS_RESTRICT_THRESHOLD

        self.assertEqual(SILENT_LOSS_RESTRICT_THRESHOLD, 1)


if __name__ == "__main__":
    unittest.main()
