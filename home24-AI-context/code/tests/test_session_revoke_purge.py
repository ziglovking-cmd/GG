# -*- coding: utf-8 -*-
"""Отозванная сессия: purge legacy + blacklist; repair_duplicates идемпотентен."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.session_blacklist import (
    blacklist_session,
    is_blacklisted,
    reset_blacklist_cache,
    session_hash,
)
from bot.session_io import purge_dead_session
from bot.tg_accounts import TgAccountRegistry, reset_tg_accounts_cache
from bot.managers import reset_registry_cache


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def test_blacklist_sha256_persists() -> None:
    tmp = _tmp()
    bl = tmp / "session_blacklist.json"
    os.environ["SESSION_BLACKLIST_PATH"] = str(bl)
    reset_blacklist_cache()
    sess = "DEAD_SESSION_STRING_ABC"
    assert not is_blacklisted(sess)
    assert blacklist_session(sess) is True
    assert is_blacklisted(sess)
    assert blacklist_session(sess) is False  # already there
    h = session_hash(sess)
    data = json.loads(bl.read_text(encoding="utf-8"))
    assert h in data["sha256"]
    reset_blacklist_cache()
    assert is_blacklisted(sess)


def test_purge_dead_session_wipes_all_legacy_sources() -> None:
    tmp = _tmp()
    dead = "REVOKED_STRING_SESSION_XYZ"
    other = "OTHER_LIVE_SESSION"

    env_path = tmp / ".env"
    env_path.write_text(
        f"TELEGRAM_SESSION={dead}\nAPI_ID=1\n",
        encoding="utf-8",
    )
    os.environ["TELEGRAM_SESSION"] = dead

    managers_path = tmp / "managers.json"
    managers_path.write_text(
        json.dumps(
            {
                "default_manager_id": "default",
                "managers": [
                    {
                        "id": "default",
                        "name": "Default",
                        "session": dead,
                        "enabled": True,
                    },
                    {
                        "id": "ivan",
                        "name": "Ivan",
                        "session": other,
                        "enabled": True,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.environ["MANAGERS_PATH"] = str(managers_path)
    reset_registry_cache()

    tg_path = tmp / "tg_accounts.json"
    os.environ["TG_ACCOUNTS_PATH"] = str(tg_path)
    reset_tg_accounts_cache()
    from bot.tg_accounts import get_tg_accounts

    tg = get_tg_accounts()
    tg.accounts.clear()
    tg.upsert(account_id="main", is_main=True)
    tg.set_session("main", dead)
    tg.upsert(account_id="sim2", manager_id="ivan")
    tg.set_session("sim2", other)

    db_path = tmp / "home24.db"
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute(
        "INSERT INTO meta(key,value) VALUES('telethon_session',?)", (dead,)
    )
    con.execute(
        "INSERT INTO meta(key,value) VALUES('telethon_session:default',?)",
        (dead,),
    )
    con.execute(
        "INSERT INTO meta(key,value) VALUES('telethon_session:ivan',?)",
        (other,),
    )
    con.commit()
    con.close()
    os.environ["DATABASE_PATH"] = str(db_path)

    bl = tmp / "session_blacklist.json"
    os.environ["SESSION_BLACKLIST_PATH"] = str(bl)
    reset_blacklist_cache()

    purge_dead_session(dead, env_path=env_path, db_path=db_path)

    assert is_blacklisted(dead)
    assert not is_blacklisted(other)

    env_text = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_SESSION=\n" in env_text or "TELEGRAM_SESSION=\r\n" in env_text
    assert dead not in env_text
    assert (os.getenv("TELEGRAM_SESSION") or "").strip() == ""

    from bot.managers import get_registry

    reg = get_registry()
    assert (reg.get("default").session or "").strip() == ""
    assert (reg.get("ivan").session or "").strip() == other

    main = get_tg_accounts().get("main")
    assert main is not None
    assert (main.session or "").strip() == ""
    assert main.status == "revoked"
    sim2 = get_tg_accounts().get("sim2")
    assert sim2 is not None
    assert sim2.session == other

    con = sqlite3.connect(str(db_path))
    rows = {k: v for k, v in con.execute("SELECT key, value FROM meta")}
    con.close()
    assert (rows.get("telethon_session") or "").strip() == ""
    assert (rows.get("telethon_session:default") or "").strip() == ""
    assert (rows.get("telethon_session:ivan") or "").strip() == other


def test_unique_ready_ok_skips_blacklisted_and_clears_once() -> None:
    tmp = _tmp()
    bl = tmp / "bl.json"
    os.environ["SESSION_BLACKLIST_PATH"] = str(bl)
    os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg.json")
    reset_blacklist_cache()
    reset_tg_accounts_cache()
    dead = "BLACKLISTED_SESS"
    blacklist_session(dead)

    from bot.tg_accounts import get_tg_accounts

    tg = get_tg_accounts()
    tg.accounts.clear()
    tg.upsert(account_id="main", is_main=True)
    tg.set_session("main", dead)
    assert tg.accounts["main"].status == "ok"

    ready = tg.unique_ready_ok()
    assert ready == []
    assert tg.accounts["main"].status == "revoked"
    assert (tg.accounts["main"].session or "") == ""

    # повтор — без изменений (идемпотентно)
    ready2 = tg.unique_ready_ok()
    assert ready2 == []


def test_repair_duplicates_idempotent_no_repeat_notes() -> None:
    tmp = _tmp()
    path = tmp / "tg_accounts.json"
    path.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "main",
                        "label": "Основной",
                        "phone": "[REDACTED]",
                        "session": "SAME",
                        "manager_id": "",
                        "is_main": True,
                        "daily_send_limit": 172,
                        "weekly_send_limit": 1200,
                        "status": "ok",
                        "status_note": "",
                        "enabled": True,
                        "telegram_user_id": "6517138023",
                    },
                    {
                        "id": "anna",
                        "label": "Анна",
                        "phone": "[REDACTED]",
                        "session": "SAME",
                        "manager_id": "anna",
                        "is_main": False,
                        "daily_send_limit": 30,
                        "weekly_send_limit": 1200,
                        "status": "ok",
                        "status_note": "",
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
    # первый load уже починил
    assert not reg.accounts["anna"].enabled
    assert reg.accounts["anna"].session == ""

    notes1 = reg.repair_duplicates()
    assert notes1 == []

    notes2 = reg.repair_duplicates()
    assert notes2 == []

    # имитация цикла keepalive: load + repair каждую секунду
    for _ in range(5):
        reg.load()
        assert reg.repair_duplicates() == []


def test_account_session_dead_purges_and_blacklists() -> None:
    tmp = _tmp()
    dead = "DEAD_FOR_PURGE_TEST"
    os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg.json")
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    os.environ["DATABASE_PATH"] = str(tmp / "db.sqlite")
    os.environ["SESSION_BLACKLIST_PATH"] = str(tmp / "bl.json")
    env_path = tmp / ".env"
    env_path.write_text(f"TELEGRAM_SESSION={dead}\n", encoding="utf-8")
    os.environ["TELEGRAM_SESSION"] = dead

    reset_blacklist_cache()
    reset_tg_accounts_cache()
    reset_registry_cache()

    from bot.managers import get_registry
    from bot.store import Store
    from bot.tg_accounts import get_tg_accounts
    from bot.main import _account_session_dead
    from bot.runtime_flags import set_dashboard_keepalive

    set_dashboard_keepalive(True)
    store = Store(tmp / "db.sqlite")
    store.set_meta("telethon_session", dead)

    reg = get_registry()
    reg.set_session(reg.default_manager_id, dead)

    tg = get_tg_accounts()
    tg.accounts.clear()
    tg.upsert(account_id="main", is_main=True, manager_id="default")
    tg.set_session("main", dead)

    with patch("bot.session_io.project_root", return_value=tmp):
        _account_session_dead("main", "default", "SessionRevokedError")

    assert is_blacklisted(dead)
    a = get_tg_accounts().get("main")
    assert a is not None
    assert a.status == "revoked"
    assert a.session == ""
    assert (get_registry().default().session or "").strip() == ""
    assert (store.get_meta("telethon_session") or "").strip() == ""
    # unique_ready пуст — respawn не поднимет
    assert get_tg_accounts().unique_ready_ok() == []
    set_dashboard_keepalive(False)


def test_spawn_tasks_allow_legacy_false_skips_managers_only() -> None:
    """После revoke keepalive не должен стартовать legacy managers.json."""
    tmp = _tmp()
    os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg.json")
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    os.environ["SESSION_BLACKLIST_PATH"] = str(tmp / "bl.json")
    reset_blacklist_cache()
    reset_tg_accounts_cache()
    reset_registry_cache()

    from bot.managers import get_registry
    from bot.tg_accounts import get_tg_accounts
    from bot.session_blacklist import is_blacklisted

    dead = "LEGACY_ONLY_DEAD"
    blacklist_session(dead)

    tg = get_tg_accounts()
    tg.accounts.clear()
    tg.upsert(account_id="main", is_main=True)
    tg.accounts["main"].status = "revoked"
    tg.accounts["main"].session = ""
    tg.save()

    reg = get_registry()
    reg.set_session(reg.default_manager_id, dead)

    # как _spawn_tasks(allow_legacy=False)
    ready = tg.unique_ready_ok()
    assert ready == []
    # legacy был бы доступен в managers, но blacklist + allow_legacy=False
    legacy_ready = [
        m
        for m in reg.enabled_list()
        if (m.session or "").strip()
        and not is_blacklisted(m.session or "")
    ]
    assert legacy_ready == []  # blacklisted
    assert is_blacklisted(dead)


if __name__ == "__main__":
    test_blacklist_sha256_persists()
    test_purge_dead_session_wipes_all_legacy_sources()
    test_unique_ready_ok_skips_blacklisted_and_clears_once()
    test_repair_duplicates_idempotent_no_repeat_notes()
    test_account_session_dead_purges_and_blacklists()
    test_spawn_tasks_allow_legacy_false_skips_managers_only()
    print("test_session_revoke_purge OK")
