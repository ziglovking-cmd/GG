# -*- coding: utf-8 -*-
"""Служебный обзор не виден в смене и отвечает 404 всем, кроме своего входа."""

from __future__ import annotations

import asyncio
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
from bot.dashboard.ingress import reset_for_tests
from bot.managers import reset_registry_cache

PATH = "/sight-test-path-9f3a"
HIDDEN = "hiddenone"
HIDDEN_PW = "hidden-pass-123"


def test_own_refresh_is_folded_away_and_actions_group_by_ip() -> None:
    os.environ["HOME24_SIGHT_PATH"] = PATH
    from bot.dashboard.ingress import _by_ip, _fold_rows, _is_own_path, _scrub

    assert _is_own_path(PATH)
    assert _is_own_path(PATH + "?part=feed")
    gone = _scrub({"path": PATH, "method": "GET", "kind": "hit", "ip": "1.1.1.1"})
    assert gone is None
    kept = _scrub(
        {
            "path": "/api/dialogs",
            "method": "POST",
            "kind": "action",
            "ip": "5.5.5.5",
            "detail": "POST",
        }
    )
    assert kept and kept["path"] == "/api/dialogs"
    folded = _fold_rows(
        [
            {"ip": "9.9.9.9", "method": "GET", "path": "/app", "status": 200, "username": "", "kind": "", "detail": ""},
            {"ip": "9.9.9.9", "method": "GET", "path": "/app", "status": 200, "username": "", "kind": "", "detail": ""},
            {"ip": "1.2.3.4", "method": "POST", "path": "/api/reply", "status": 200, "username": "a", "kind": "action", "detail": "POST", "ts": 50},
            {"ip": "8.8.8.8", "method": "POST", "path": "/api/users", "status": 200, "username": "b", "kind": "action", "detail": "POST", "ts": 10},
        ]
    )
    assert folded[0]["n"] == 2
    groups = _by_ip(folded[1:])
    assert [g["ip"] for g in groups] == ["1.2.3.4", "8.8.8.8"]


def test_roster_skips_unlisted_and_panel_cannot_drop_it() -> None:
    tmp = Path(tempfile.mkdtemp())
    users = tmp / "users.json"
    users.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username": "boss",
                        "role": "admin",
                        "manager_id": "",
                        "display_name": "Админ",
                        "password_hash": dash_auth.hash_password("admin-pass-123"),
                        "enabled": True,
                        "unlisted": False,
                    },
                    {
                        "username": HIDDEN,
                        "role": "admin",
                        "manager_id": "",
                        "display_name": "Глеб",
                        "password_hash": dash_auth.hash_password(HIDDEN_PW),
                        "enabled": True,
                        "unlisted": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    names = [u["username"] for u in dash_auth.list_users_public(users)]
    assert names == ["boss"]
    assert dash_auth.delete_user(HIDDEN, path=users) is False
    try:
        dash_auth.reset_password(HIDDEN, path=users)
        raise AssertionError("reset must miss")
    except KeyError:
        pass
    assert dash_auth.find_user(HIDDEN, users)["unlisted"] is True


def test_quiet_page_is_404_for_everyone_else() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        users = tmp / "users.json"
        users.write_text(
            json.dumps(
                {
                    "users": [
                        {
                            "username": "boss",
                            "role": "admin",
                            "manager_id": "",
                            "display_name": "Админ",
                            "password_hash": dash_auth.hash_password("admin-pass-123"),
                            "enabled": True,
                            "must_change_password": False,
                            "session_jti": "",
                            "unlisted": False,
                        },
                        {
                            "username": HIDDEN,
                            "role": "admin",
                            "manager_id": "",
                            "display_name": "Глеб",
                            "password_hash": dash_auth.hash_password(HIDDEN_PW),
                            "enabled": True,
                            "must_change_password": False,
                            "session_jti": "",
                            "unlisted": True,
                        },
                    ],
                    "setup_done": True,
                }
            ),
            encoding="utf-8",
        )
        os.environ["DASHBOARD_USERS_PATH"] = str(users)
        os.environ["DATABASE_PATH"] = str(tmp / "t.db")
        os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
        os.environ["HOME24_DASHBOARD_DEMO"] = "0"
        os.environ["HOME24_SIGHT_PATH"] = PATH
        os.environ["HOME24_SIGHT_USER"] = HIDDEN
        os.environ["HOME24_SIGHT_PASSWORD"] = HIDDEN_PW
        os.environ["HOME24_INGRESS_DB"] = str(tmp / "ingress.sqlite")
        os.environ.pop("HOME24_ACCESS_LOG", None)
        get_settings.cache_clear()
        reset_registry_cache()
        reset_for_tests()
        dash_auth._fail_log.clear()
        app = create_dashboard_app()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            anon = await client.get(PATH)
            assert anon.status == 404
            assert await anon.text() == "404: Not Found"
            bad = await client.post("/api/login", json={"username": "ghost", "password": "nope-nope"})
            assert bad.status == 401
            own = await client.post(
                "/api/login", json={"username": HIDDEN, "password": HIDDEN_PW}
            )
            assert own.status == 200
            body = await own.json()
            assert body["user"]["role"] == "admin"
            assert "unlisted" not in body["user"]
            assert body["next"] == PATH
            page = await client.get(PATH)
            assert page.status == 200
            html = await page.text()
            assert "Входы" in html and "Обзор" in html
            assert "создател" not in html.lower()
            assert PATH not in INDEX_HTML
            feed = await client.get(PATH + "?part=feed")
            data = await feed.json()
            kinds = {row["kind"] for row in data["logins"]}
            names = {row["username"] for row in data["logins"]}
            assert "login_ok" in kinds and "login_fail" in kinds
            assert HIDDEN in names and "ghost" in names
            assert all("password" not in json.dumps(row).lower() for row in data["logins"])
            listed = {u["username"] for u in data["users"]}
            assert HIDDEN in listed and "boss" in listed
            await client.post("/api/logout")
            boss = await client.post(
                "/api/login", json={"username": "boss", "password": "admin-pass-123"}
            )
            assert boss.status == 200
            boss_body = await boss.json()
            assert "next" not in boss_body
            hidden = await client.get("/api/users")
            # csrf not required for GET
            payload = await hidden.json()
            assert all(u["username"] != HIDDEN for u in payload["users"])
            denied = await client.get(PATH)
            assert denied.status == 404
            assert await denied.text() == "404: Not Found"
            js = Path("bot/dashboard/static/dashboard.js").read_text(encoding="utf-8")
            assert "HOME24_SIGHT" not in js and PATH not in js
        finally:
            await client.close()

    asyncio.run(run())


if __name__ == "__main__":
    test_own_refresh_is_folded_away_and_actions_group_by_ip()
    test_roster_skips_unlisted_and_panel_cannot_drop_it()
    test_quiet_page_is_404_for_everyone_else()
    print("ok")
