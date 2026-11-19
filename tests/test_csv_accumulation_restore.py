import json
from pathlib import Path
import tempfile
import unittest

from app import db
from deploy.merge_existing_csv import merge


class CsvAccumulationRestoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.old_path = db.DB_PATH
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        db.DB_PATH = self.root / "app.db"
        db.connect()
        db.ex("INSERT INTO chats(id,title,kind) VALUES (?,?,?)", (123, "test", "supergroup"))
        db.ex("INSERT INTO members(chat_id,user_id,username) VALUES (?,?,?)", (123, 1, "current_name"))
        db.ex("INSERT INTO members(chat_id,user_id,username) VALUES (?,?,?)", (123, 4, "live_only"))

    def tearDown(self):
        db._conn.close()
        db._conn = None
        db.DB_PATH = self.old_path
        self.directory.cleanup()

    def payload(self):
        return {"chat_id": 123, "files": [{"name": "old.csv"}, {"name": "new.csv"}],
                "rows": [{"user_id": 1, "username": "stale_name"},
                         {"user_id": 2, "username": "restored2"},
                         {"user_id": 3, "username": "restored3"}]}

    def test_restore_keeps_live_rows_and_does_not_overwrite_current_profile(self):
        result = merge(self.payload(), db.DB_PATH, self.root / "backup")
        self.assertEqual((result["before"], result["added"], result["after"]), (2, 2, 4))
        self.assertEqual(result["removed_live_ids"], 0)
        self.assertEqual(result["missing_csv_ids"], 0)
        self.assertEqual(db.q1("SELECT username FROM members WHERE user_id=1")["username"], "current_name")
        self.assertTrue(Path(result["backup"]).exists())
        self.assertEqual(json.loads((self.root / "backup/csv-merge-summary.json").read_text())["after"], 4)

    def test_repeat_restore_does_not_add_duplicates(self):
        merge(self.payload(), db.DB_PATH, self.root / "backup")
        repeated = merge(self.payload(), db.DB_PATH, self.root / "backup")
        self.assertEqual((repeated["added"], repeated["after"]), (0, 4))

    def test_unknown_chat_cannot_be_created_accidentally(self):
        payload = dict(self.payload(), chat_id=999)
        with self.assertRaises(ValueError):
            merge(payload, db.DB_PATH, self.root / "backup")
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM members")["n"], 2)


if __name__ == "__main__":
    unittest.main()
