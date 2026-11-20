# -*- coding: utf-8 -*-
"""Панель: слоты гостя в списке и карточка в шапке чата."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp.test_utils import TestClient, TestServer

from bot.config import get_settings
from bot.dashboard import auth as dash_auth
from bot.dashboard.app import INDEX_HTML, create_dashboard_app
from bot.managers import ManagerRegistry, reset_registry_cache
from bot.store import Store


def test_shell_has_desk_controls() -> None:
    assert 'id="chatBrief"' in INDEX_HTML
    assert 'id="btnCopyCard"' in INDEX_HTML
    assert 'data-dfilter="bot"' in INDEX_HTML
    assert 'data-dfilter="manager"' in INDEX_HTML


def test_dialog_list_includes_guest_slots() -> None:
    import asyncio

    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        users = tmp / "users.json"
        users.write_text(
            json.dumps(
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
                    "distribution": {"mode": "even"},
                    "setup_done": True,
                }
            ),
            encoding="utf-8",
        )
        os.environ["DASHBOARD_USERS_PATH"] = str(users)
        os.environ["DATABASE_PATH"] = str(tmp / "home24.db")
        os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
        os.environ["HOME24_DASHBOARD_DEMO"] = "0"
        get_settings.cache_clear()
        reset_registry_cache()
        ManagerRegistry(tmp / "managers.json").upsert(
            manager_id="anna", name="Анна", make_default=True
        )
        store = Store(str(tmp / "home24.db"))
        store.save_session(
            "555001",
            name="[REDACTED]",
            dates="с 1 по 4 ноября",
            guests="2",
            district="Прокшино",
            favorite="Бриз",
            manager_id="anna",
            step="handed_off",
            handed_off=1,
        )
        app = create_dashboard_app()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.post(
                "/api/login", json={"username": "admin", "password": "admin123"}
            )
            assert r.status == 200
            r = await client.get("/api/dialogs")
            assert r.status == 200
            rows = (await r.json())["dialogs"]
            hit = next(d for d in rows if str(d["chat_id"]) == "555001")
            assert hit["dates"] == "с 1 по 4 ноября"
            assert hit["guests"] == "2"
            assert hit["district"] == "Прокшино"
            assert hit["favorite"] == "Бриз"
            page = await client.get("/app")
            html = await page.text()
            assert page.status == 200
            assert 'id="chatBrief"' in html
        finally:
            await client.close()

    asyncio.run(run())


if __name__ == "__main__":
    test_shell_has_desk_controls()
    test_dialog_list_includes_guest_slots()
    print("ok panel desk")
