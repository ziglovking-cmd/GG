"""DAILY=30 / WEEKLY=210, pause_for_day, настройки панели. main не выше 30/210."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import rate_limit as rl
from bot.rate_limit import OutreachLimiter
from bot.store import Store
from bot.tg_accounts import TgAccountRegistry, reset_tg_accounts_cache


def test_defaults() -> None:
    assert rl.DEFAULT_DAILY == 30
    assert rl.DEFAULT_WEEKLY == 210
    assert rl.DEFAULT_PER_HOUR == 4
    assert rl.MIN_GAP_SEC == 240


def test_rolling_week_and_pause() -> None:
    tmp = Path(tempfile.mkdtemp())
    store = Store(str(tmp / "db.sqlite"))
    lim = OutreachLimiter(
        store,
        account_id="main",
        daily_limit=172,
        weekly_limit=1200,
        work_start=0,
        work_end=24,
    )
    for _ in range(10):
        lim.record_send()
    c = lim.counts()
    assert c["sent_today"] == 10
    assert c["sent_week"] == 10
    assert c["remaining_week"] == 1190
    assert not c["paused_today"]
    lim.pause_for_day("FloodWait 120s — стоп на сегодня")
    ok, why = lim.can_send()
    assert not ok
    assert "стоп" in why.lower() or "FloodWait" in why
    c2 = lim.counts()
    assert c2["paused_today"] is True
    assert "FloodWait" in c2["pause_reason"]


def test_settings_api_edit_limits() -> None:
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from bot.config import get_settings
    from bot.dashboard import auth as dash_auth
    from bot.dashboard.app import create_dashboard_app
    from bot.managers import ManagerRegistry, reset_registry_cache

    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        users = tmp / "users.json"
        dash_auth.save_store(
            {
                "users": [
                    {
                        "username": "admin",
                        "role": "admin",
                        "manager_id": "",
                        "display_name": "Админ",
                        "password_hash": dash_auth.hash_password("admin123"),
                        "enabled": True,
                        "must_change_password": False,
                        "session_jti": "",
                    }
                ],
                "setup_done": True,
            },
            users,
        )
        os.environ["DASHBOARD_USERS_PATH"] = str(users)
        os.environ["DATABASE_PATH"] = str(tmp / "home24.db")
        os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
        os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg.json")
        os.environ["HOME24_DASHBOARD_DEMO"] = "0"
        get_settings.cache_clear()
        reset_registry_cache()
        reset_tg_accounts_cache()
        ManagerRegistry(tmp / "managers.json").upsert(
            manager_id="anna", name="Анна", make_default=True
        )
        Store(str(tmp / "home24.db"))  # init
        tg = TgAccountRegistry(tmp / "tg.json")
        tg.upsert(account_id="main", label="Основной", is_main=True)
        tg.set_session("main", "SESS")

        app = create_dashboard_app()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.post(
                "/api/login", json={"username": "admin", "password": "admin123"}
            )
            csrf = (await r.json())["csrf"]
            r = await client.get("/api/settings")
            assert r.status == 200
            body = await r.json()
            assert body["defaults"]["daily"] == 30
            assert body["defaults"]["weekly"] == 210
            assert body["accounts"]
            acc = body["accounts"][0]
            assert acc["daily_send_limit"] == 30
            assert acc["weekly_send_limit"] == 210
            r = await client.post(
                "/api/settings",
                json={
                    "accounts": [
                        {
                            "id": "main",
                            "daily_send_limit": 100,
                            "weekly_send_limit": 800,
                            "manager_id": "",
                        }
                    ],
                    "managers": [{"id": "anna", "share_weight": 2}],
                },
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200
            reset_tg_accounts_cache()
            r = await client.get("/api/settings")
            acc2 = (await r.json())["accounts"][0]
            assert acc2["daily_send_limit"] == 30
            assert acc2["weekly_send_limit"] == 210
        finally:
            await client.close()

    asyncio.run(run())


if __name__ == "__main__":
    test_defaults()
    test_rolling_week_and_pause()
    test_settings_api_edit_limits()
    print("ok")
