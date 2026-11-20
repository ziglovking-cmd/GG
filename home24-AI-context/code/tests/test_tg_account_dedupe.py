# -*- coding: utf-8 -*-
"""Дедуп Telegram-аккаунтов и выживание дашборда при SessionRevokedError."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.runtime_flags import (
    dashboard_keepalive,
    is_session_dead_error,
    set_dashboard_keepalive,
)
from bot.tg_accounts import TgAccountRegistry, reset_tg_accounts_cache


def _reg(tmp: Path) -> TgAccountRegistry:
    reset_tg_accounts_cache()
    path = tmp / "tg_accounts.json"
    reg = TgAccountRegistry(path)
    reg.accounts.clear()
    reg.save()
    return reg


def test_apply_session_first_becomes_main_and_bound() -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = _reg(tmp)
    acc = reg.apply_authorized_session(
        session="SESS_A",
        phone="[REDACTED]",
        [REDACTED],
        manager_id="anna",
        preferred_account_id="anna",
        label="Анна",
    )
    assert acc.id == "main"
    assert acc.is_main
    assert acc.manager_id == "anna"
    assert acc.phone.endswith("9056564540") or "[REDACTED]" in acc.phone
    assert acc.telegram_user_id == "6517138023"
    assert len(reg.accounts) == 1


def test_apply_session_dedupes_same_user_id() -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = _reg(tmp)
    reg.upsert(account_id="main", label="Main", is_main=True)
    reg.set_session("main", "OLD", phone="[REDACTED]")
    # тот же Telegram user — обновить main, не создать anna
    acc = reg.apply_authorized_session(
        session="SESS_NEW",
        phone="[REDACTED]",
        [REDACTED],
        manager_id="anna",
        preferred_account_id="anna",
    )
    # phone differs from main's old phone — new user_id, so new slot OR update if phone match
    # user_id not on main yet, phone different → creates preferred/new
    # Force: put user_id on main first
    reg.accounts["main"].telegram_user_id = "6517138023"
    reg.accounts["main"].phone = "[REDACTED]"
    reg.save()
    acc = reg.apply_authorized_session(
        session="SESS_NEW2",
        phone="[REDACTED]",
        [REDACTED],
        manager_id="anna",
        preferred_account_id="anna",
    )
    assert acc.id == "main"
    assert acc.session == "SESS_NEW2"
    assert acc.manager_id == "anna"
    assert "anna" not in reg.accounts or not reg.accounts.get("anna") or not reg.accounts["anna"].enabled


def test_repair_duplicates_main_and_anna_same_phone() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "tg_accounts.json"
    path.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "main",
                        "label": "Основной",
                        "phone": "[REDACTED]",
                        "session": "SAME_SESS",
                        "manager_id": "",
                        "is_main": True,
                        "daily_send_limit": 172,
                        "weekly_send_limit": 1200,
                        "status": "revoked",
                        "status_note": "dead",
                        "enabled": True,
                        "telegram_user_id": "6517138023",
                    },
                    {
                        "id": "anna",
                        "label": "Анна",
                        "phone": "[REDACTED]",
                        "session": "SAME_SESS",
                        "manager_id": "anna",
                        "is_main": False,
                        "daily_send_limit": 30,
                        "weekly_send_limit": 1200,
                        "status": "revoked",
                        "status_note": "dead",
                        "enabled": True,
                        "telegram_user_id": "6517138023",
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    reset_tg_accounts_cache()
    reg = TgAccountRegistry(path)
    assert "main" in reg.accounts
    assert "anna" in reg.accounts
    # дубликат отключён
    keep = reg.accounts["main"]
    dup = reg.accounts["anna"]
    assert keep.enabled
    assert not dup.enabled
    assert dup.session == ""
    assert "дубликат" in (dup.status_note or "")
    assert keep.manager_id == "anna"  # переняли с дубликата
    # unique ready — пусто (revoked)
    assert reg.unique_ready_ok() == []


def test_unique_ready_ok_one_client_per_session() -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = _reg(tmp)
    reg.upsert(account_id="main", is_main=True)
    reg.set_session("main", "S1")
    reg.upsert(account_id="sim2", manager_id="ivan")
    reg.accounts["sim2"].session = "S1"  # тот же ключ — ошибка данных
    reg.accounts["sim2"].status = "ok"
    reg.save()
    ready = reg.unique_ready_ok()
    assert len(ready) == 1
    assert ready[0].id == "main"


def test_session_already_used_blocks_legacy_copy() -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = _reg(tmp)
    reg.upsert(account_id="main", is_main=True)
    reg.upsert(account_id="anna", manager_id="anna")
    reg.set_session("anna", "LEGACY", phone="[REDACTED]")
    assert reg.session_already_used("LEGACY", except_id="main") is not None
    assert reg.session_already_used("LEGACY", except_id="anna") is None


def test_is_session_dead_error() -> None:
    assert is_session_dead_error("SessionRevokedError")
    assert is_session_dead_error("AuthKeyUnregisteredError")
    assert is_session_dead_error("AuthKeyDuplicatedError")
    assert is_session_dead_error("UserDeactivatedBanError")

    class SessionRevokedError(Exception):
        pass

    assert is_session_dead_error(SessionRevokedError("x"))


def test_account_session_dead_no_systemexit_with_keepalive() -> None:
    set_dashboard_keepalive(True)
    assert dashboard_keepalive()
    tmp = Path(tempfile.mkdtemp())
    os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg.json")
    reset_tg_accounts_cache()
    from bot.tg_accounts import get_tg_accounts
    from bot.main import _account_session_dead

    tg = get_tg_accounts()
    tg.accounts.clear()
    tg.upsert(account_id="main", is_main=True, manager_id="anna")
    tg.set_session("main", "DEAD")
    _account_session_dead("main", "anna", "SessionRevokedError: test")
    a = tg.get("main")
    assert a is not None
    assert a.status == "revoked"
    assert a.session == ""
    set_dashboard_keepalive(False)


def test_run_manager_returns_on_session_revoked_with_keepalive() -> None:
    set_dashboard_keepalive(True)
    tmp = Path(tempfile.mkdtemp())
    os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg.json")
    os.environ["DATABASE_PATH"] = str(tmp / "db.sqlite")
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    reset_tg_accounts_cache()
    from bot.managers import ManagerConfig, reset_registry_cache
    from bot.store import Store
    from bot.tg_accounts import get_tg_accounts
    from bot import main as main_mod

    reset_registry_cache()
    tg = get_tg_accounts()
    tg.accounts.clear()
    tg.upsert(account_id="main", is_main=True, manager_id="anna")
    tg.set_session("main", "DEADSESS")
    store = Store(tmp / "db.sqlite")
    mgr = ManagerConfig(id="anna", name="Анна", session="DEADSESS")

    async def boom(*_a, **_k):
        raise SystemExit(42)

    async def run():
        with patch.object(main_mod, "ensure_login", side_effect=boom):
            await main_mod.run_manager(
                mgr, store, account_id="main", session_override="DEADSESS"
            )

    asyncio.run(run())
    a = get_tg_accounts().get("main")
    assert a is not None
    assert a.status == "revoked"
    set_dashboard_keepalive(False)


if __name__ == "__main__":
    test_apply_session_first_becomes_main_and_bound()
    test_apply_session_dedupes_same_user_id()
    test_repair_duplicates_main_and_anna_same_phone()
    test_unique_ready_ok_one_client_per_session()
    test_session_already_used_blocks_legacy_copy()
    test_is_session_dead_error()
    test_account_session_dead_no_systemexit_with_keepalive()
    test_run_manager_returns_on_session_revoked_with_keepalive()
    print("test_tg_account_dedupe OK")
