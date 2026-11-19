import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config


class BotConfigTests(unittest.TestCase):
    def test_bot_token_is_saved_with_private_permissions_and_never_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with patch.object(config, "CONFIG_PATH", path), patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TG_BOT_TOKEN", None)
                config.save_api_credentials(12345, "api-secret")
                config.save_bot_settings("123456:abcdefghijklmnopqrstuvwxyz", "monitor_bot")

                token, username = config.get_bot_settings()
                self.assertEqual(token, "123456:abcdefghijklmnopqrstuvwxyz")
                self.assertEqual(username, "monitor_bot")
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertIn("api-secret", path.read_text("utf-8"))

    def test_bot_recipient_is_saved_and_cleared_when_bot_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with patch.object(config, "CONFIG_PATH", path), patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TG_BOT_TOKEN", None)
                config.save_bot_settings("123456:abcdefghijklmnopqrstuvwxyz", "first_bot")
                config.save_bot_recipient(123456789, "Александр (@example)")
                config.save_bot_update_offset(777)

                self.assertEqual(
                    config.get_bot_recipient(),
                    (123456789, "Александр (@example)"),
                )
                self.assertEqual(config.get_bot_update_offset(), 777)

                config.save_bot_settings("654321:zyxwvutsrqponmlkjihgfedcba", "second_bot")
                self.assertEqual(config.get_bot_recipient(), (None, None))
                self.assertIsNone(config.get_bot_update_offset())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
