"""Frankenstein: templates + confirmed wave pauses."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app import db
from app.frankenstein import (
    apply_template_to_settings,
    get_template,
    list_templates,
    template_warnings,
)


class TemplateTests(unittest.TestCase):
    def test_templates_are_conservative(self):
        rows = list_templates()
        self.assertGreaterEqual(len(rows), 4)
        for row in rows:
            self.assertLessEqual(int(row["daily_limit_per_account"]), 5)
            self.assertGreaterEqual(int(row["invite_gap_min"]), 8 * 60)
            self.assertNotIn("aggressive", row["id"])

    def test_apply_template_sets_wave_fields(self):
        settings = apply_template_to_settings(
            {"account_ids": [1, 2, 3]}, "conservative"
        )
        self.assertEqual(settings["template_id"], "conservative")
        self.assertEqual(settings["per_wave"], 4)
        self.assertEqual(settings["hours_between_waves"], 5)
        self.assertEqual(settings["daily_limit_per_account"], 3)
        self.assertIn("invite_gap_min", settings)

    def test_template_account_count_warning(self):
        warnings = template_warnings(1, "standard")
        self.assertTrue(any("аккаунтов" in item for item in warnings))


class WaveProgressTests(unittest.TestCase):
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

    def _ready_target(self, campaign_id: int, account_id: int, user_id: int) -> int:
        target_id = db.ex(
            """
            INSERT INTO targets (campaign_id,user_id,username,status,account_id,error)
            VALUES (?,?,?,'verifying',?,?)
            """,
            (campaign_id, user_id, "u%d" % user_id, account_id, "armed"),
        )
        return target_id

    def test_wave_closes_after_per_wave_confirmed(self):
        account_id = db.ex(
            """
            INSERT INTO accounts (label,phone,session_name,status,created_at)
            VALUES ('a','+700','s1','authorized',0)
            """
        )
        template = get_template("ultra_safe")
        settings = apply_template_to_settings({}, "ultra_safe")
        campaign_id = db.ex(
            """
            INSERT INTO campaigns
                (name,target_chat_id,settings,status,created_at,wave_progress)
            VALUES ('c',42,?,?,0,0)
            """,
            (json.dumps(settings), "running"),
        )
        per_wave = int(template["per_wave"])
        for idx in range(per_wave):
            target_id = self._ready_target(campaign_id, account_id, 100 + idx)
            status = db.finalize_invite_confirmation(target_id, True, member_count=1)
            self.assertEqual(status, "invited")
        row = db.q1(
            "SELECT wave_progress, wave_pause_until, next_invite_at FROM campaigns WHERE id=?",
            (campaign_id,),
        )
        self.assertEqual(int(row["wave_progress"]), 0)
        self.assertGreater(int(row["wave_pause_until"]), 0)
        self.assertGreaterEqual(
            int(row["next_invite_at"]), int(row["wave_pause_until"])
        )
        hours = int(template["hours_between_waves"])
        self.assertGreaterEqual(
            int(row["wave_pause_until"]) - int(__import__("time").time()),
            hours * 3600 - 5,
        )


if __name__ == "__main__":
    unittest.main()
