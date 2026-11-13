# -*- coding: utf-8 -*-
"""Персональные настройки менеджера (data/user_prefs.json)."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.user_prefs import (
    UserPrefsStore,
    manager_label,
    reset_user_prefs_cache,
)


def test_prefs_roundtrip_and_defaults() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "user_prefs.json"
    store = UserPrefsStore(path)
    assert store.get("anna")["theme"] == "dark"
    updated = store.update(
        "anna",
        {
            "theme": "system",
            "signature": "Анна",
            "composer_enter": "newline",
            "dialog_filter": "needs_reply",
            "font_size": "lg",
            "compact_chat": True,
            "notify_browser": True,
        },
    )
    assert updated["signature"] == "Анна"
    assert updated["theme"] == "system"
    assert path.exists()
    store2 = UserPrefsStore(path)
    again = store2.get("anna")
    assert again["signature"] == "Анна"
    assert again["compact_chat"] is True
    # preserve: другой пользователь не тронут
    assert store2.get("ivan")["signature"] == ""


def test_manager_label_prefers_signature() -> None:
    tmp = Path(tempfile.mkdtemp())
    os.environ["USER_PREFS_PATH"] = str(tmp / "prefs.json")
    reset_user_prefs_cache()
    from bot.user_prefs import get_user_prefs_store

    get_user_prefs_store().update("anna", {"signature": "Аня"})
    assert manager_label("anna", "Анна") == "Аня"
    get_user_prefs_store().update("ivan", {"signature": ""})
    assert manager_label("ivan", "Иван") == "Иван"


def test_prefs_api_manager() -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from bot.config import get_settings
    from bot.dashboard import auth as dash_auth
    from bot.dashboard.app import create_dashboard_app
    from bot.managers import reset_registry_cache
    from bot.reply_templates import reset_template_store_cache
    from bot.tg_accounts import reset_tg_accounts_cache

    tmp = Path(tempfile.mkdtemp())
    users = tmp / "users.json"
    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    os.environ["USER_PREFS_PATH"] = str(tmp / "user_prefs.json")
    os.environ["TEMPLATES_PATH"] = str(tmp / "templates.json")
    os.environ["DATABASE_PATH"] = str(tmp / "db.sqlite")
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg.json")
    os.environ["HOME24_DASHBOARD_DEMO"] = "0"
    os.environ["DASHBOARD_SECRET"] = "prefs-test-secret"
    os.environ["DASHBOARD_ADMIN_MUST_CHANGE"] = "0"
    get_settings.cache_clear()
    reset_registry_cache()
    reset_tg_accounts_cache()
    reset_template_store_cache()
    reset_user_prefs_cache()
    dash_auth.save_store(
        {
            "users": [
                {
                    "username": "admin",
                    "role": "admin",
                    "manager_id": "",
                    "display_name": "Админ",
                    "password_hash": dash_auth.hash_password("admin12345"),
                    "enabled": True,
                    "must_change_password": False,
                    "session_jti": "",
                },
                {
                    "username": "anna",
                    "role": "manager",
                    "manager_id": "anna",
                    "display_name": "Анна",
                    "password_hash": dash_auth.hash_password("anna12345"),
                    "enabled": True,
                    "must_change_password": False,
                    "session_jti": "",
                },
            ],
            "setup_done": True,
            "distribution": {"mode": "even"},
        },
        users,
    )

    async def run():
        app = create_dashboard_app()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.post(
                "/api/login", json={"username": "anna", "password": "anna12345"}
            )
            assert r.status == 200, await r.text()
            csrf = (await r.json())["csrf"]
            r = await client.get("/api/prefs")
            assert r.status == 200
            body = await r.json()
            assert body["store_path"] == "data/user_prefs.json"
            assert body["display_name"] == "Анна"
            r = await client.post(
                "/api/prefs",
                json={
                    "display_name": "Анна М.",
                    "signature": "Анна",
                    "theme": "light",
                    "dialog_filter": "needs_reply",
                },
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200, await r.text()
            data = await r.json()
            assert data["prefs"]["signature"] == "Анна"
            assert data["user"]["display_name"] == "Анна М."
            # личный шаблон + reorder
            r = await client.post(
                "/api/templates",
                json={
                    "title": "Мой вход",
                    "body": "Привет {имя}, это {менеджер}",
                    "category": "greeting",
                    "scope": "personal",
                },
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200, await r.text()
            tid = (await r.json())["template"]["id"]
            r = await client.post(
                "/api/templates",
                json={
                    "title": "Пока",
                    "body": "До связи!",
                    "category": "closing",
                    "scope": "personal",
                },
                headers={"X-CSRF-Token": csrf},
            )
            tid2 = (await r.json())["template"]["id"]
            r = await client.post(
                "/api/templates/reorder",
                json={"ids": [tid2, tid]},
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200
            personal = (await r.json())["templates"]
            assert personal[0]["id"] == tid2
            r = await client.get("/api/templates")
            filled = next(
                t for t in (await r.json())["templates"] if t["id"] == tid
            )
            assert "Анна" in filled["filled"]  # signature in {менеджер}
        finally:
            await client.close()

    asyncio.run(run())


if __name__ == "__main__":
    test_prefs_roundtrip_and_defaults()
    test_manager_label_prefers_signature()
    test_prefs_api_manager()
    print("test_user_prefs OK")
