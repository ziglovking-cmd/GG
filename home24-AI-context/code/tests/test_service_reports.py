# -*- coding: utf-8 -*-
"""Дедуп online-отчётов и админ-переключатель Избранного."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.dashboard import auth as dash_auth
from bot.hub import get_hub
from bot.service_reports import (
    can_send_online_report,
    emit_service_report,
    get_service_report_settings,
    report_account_online,
    reset_service_reports_state_for_tests,
    saved_messages_reports_enabled,
    set_saved_messages_reports,
)
from bot.tg_accounts import TgAccountRegistry, reset_tg_accounts_cache


def _tmp_users(tmp: Path) -> None:
    path = tmp / "users.json"
    os.environ["DASHBOARD_USERS_PATH"] = str(path)
    path.write_text(
        json.dumps(
            {
                "setup_done": True,
                "users": [
                    {
                        "username": "admin",
                        "role": "admin",
                        "manager_id": "",
                        "display_name": "Админ",
                        "password_hash": dash_auth.hash_password("admin123"),
                        "enabled": True,
                    }
                ],
                "distribution": {"mode": "even"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_saved_messages_default_off() -> None:
    tmp = Path(tempfile.mkdtemp())
    _tmp_users(tmp)
    reset_service_reports_state_for_tests()
    assert saved_messages_reports_enabled() is False
    s = get_service_report_settings()
    assert s["saved_messages_reports"] is False
    set_saved_messages_reports(True)
    assert saved_messages_reports_enabled() is True
    set_saved_messages_reports(False)
    assert saved_messages_reports_enabled() is False


def test_online_report_dedupe_and_toggle() -> None:
    tmp = Path(tempfile.mkdtemp())
    _tmp_users(tmp)
    reset_service_reports_state_for_tests()
    client = MagicMock()
    client.send_message = AsyncMock(return_value=None)

    async def run() -> None:
        # default OFF → только hub, без Telegram
        sent = await report_account_online(
            client,
            account_id="main",
            manager_id="anna",
            telegram_user_id="42",
            text="Home24 online ✅",
            username="bot",
        )
        assert sent is False
        client.send_message.assert_not_called()
        hub = get_hub()
        assert any("сети" in (n.get("title") or "") for n in hub.notifications)

        set_saved_messages_reports(True)
        sent2 = await report_account_online(
            client,
            account_id="main",
            manager_id="anna",
            telegram_user_id="42",
            text="Home24 online ✅",
            username="bot",
        )
        assert sent2 is True
        assert client.send_message.await_count == 1

        # второй раз в том же процессе — блок
        ok, why = can_send_online_report("main", "42")
        assert not ok
        assert "процессе" in why
        sent3 = await report_account_online(
            client,
            account_id="main",
            manager_id="anna",
            telegram_user_id="42",
            text="Home24 online ✅ again",
            username="bot",
        )
        assert sent3 is False
        assert client.send_message.await_count == 1

    asyncio.run(run())


def test_online_skipped_when_other_client_same_user() -> None:
    from bot.tg_accounts import get_tg_accounts

    tmp = Path(tempfile.mkdtemp())
    _tmp_users(tmp)
    tg_path = tmp / "tg.json"
    os.environ["TG_ACCOUNTS_PATH"] = str(tg_path)
    reset_tg_accounts_cache()
    reset_service_reports_state_for_tests()
    set_saved_messages_reports(True)

    reg = get_tg_accounts()
    reg.accounts.clear()
    a1 = reg.upsert(account_id="main", is_main=True)
    a1.telegram_user_id = "777"
    a1.session = "S1"
    a2 = reg.upsert(account_id="sim2", manager_id="ivan")
    a2.telegram_user_id = "777"
    a2.session = "S2"
    reg.save()

    other = MagicMock()
    other.is_connected = MagicMock(return_value=True)
    hub = get_hub()
    hub.clients.clear()
    hub.register_client("ivan", other, account_id="sim2")

    client = MagicMock()
    client.send_message = AsyncMock(return_value=None)
    client.is_connected = MagicMock(return_value=True)

    async def run() -> None:
        ok, why = can_send_online_report("main", "777")
        assert not ok, why
        assert "другой клиент" in why
        sent = await report_account_online(
            client,
            account_id="main",
            manager_id="anna",
            telegram_user_id="777",
            text="online",
        )
        assert sent is False
        client.send_message.assert_not_called()

    asyncio.run(run())
    hub.clients.clear()


def test_emit_service_respects_toggle() -> None:
    tmp = Path(tempfile.mkdtemp())
    _tmp_users(tmp)
    reset_service_reports_state_for_tests()
    set_saved_messages_reports(False)
    client = MagicMock()
    client.send_message = AsyncMock(return_value=None)

    async def run() -> None:
        ok = await emit_service_report(
            client, "тест сервис", account_id="main", manager_id="anna"
        )
        assert ok is False
        client.send_message.assert_not_called()
        set_saved_messages_reports(True)
        ok2 = await emit_service_report(
            client, "тест сервис 2", account_id="main", manager_id="anna"
        )
        assert ok2 is True
        assert client.send_message.await_count == 1

    asyncio.run(run())


if __name__ == "__main__":
    test_saved_messages_default_off()
    test_online_report_dedupe_and_toggle()
    test_online_skipped_when_other_client_same_user()
    test_emit_service_respects_toggle()
    print("ok")
