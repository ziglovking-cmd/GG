"""Дашборд: ADMIN/MANAGER, lockdown, rate-limit, одна сессия, CRUD, раздача."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp.test_utils import TestClient, TestServer

from bot.dashboard import auth as dash_auth
from bot.dashboard.app import create_dashboard_app
from bot.dashboard.demo import seed_demo
from bot.dashboard.distribute import on_manager_telegram_linked, redistribute_unassigned
from bot.managers import ManagerRegistry, reset_registry_cache
from bot.store import Store


def test_password_hash_roundtrip() -> None:
    h = dash_auth.hash_password("secret123")
    assert h.startswith("pbkdf2_sha256$")
    assert dash_auth.verify_password("secret123", h)
    assert not dash_auth.verify_password("wrong", h)


def test_bootstrap_first_admin(tmp_path: Path | None = None) -> None:
    tmp = Path(tempfile.mkdtemp()) if tmp_path is None else tmp_path
    users = tmp / "users.json"
    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    os.environ["DASHBOARD_ADMIN_USERNAME"] = "boss"
    os.environ["DASHBOARD_ADMIN_PASSWORD"] = "FirstAdmin!9"
    os.environ["DASHBOARD_ADMIN_MUST_CHANGE"] = "0"
    assert dash_auth.needs_first_setup(users)
    created = dash_auth.bootstrap_first_admin(users)
    assert created == ("boss", "FirstAdmin!9")
    assert not dash_auth.needs_first_setup(users)
    assert dash_auth.bootstrap_first_admin(users) is None  # once
    u = dash_auth.authenticate("boss", "FirstAdmin!9", path=users)
    assert u and u.is_admin


def test_session_single_login() -> None:
    tmp = Path(tempfile.mkdtemp())
    users = tmp / "users.json"
    users.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username": "anna",
                        "role": "manager",
                        "manager_id": "anna",
                        "display_name": "Анна",
                        "password_hash": dash_auth.hash_password("anna123"),
                        "enabled": True,
                        "session_jti": "",
                    }
                ],
                "distribution": {"mode": "even"},
            }
        ),
        encoding="utf-8",
    )
    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    u = dash_auth.DashUser("anna", "manager", "anna", "Анна")
    tok1 = dash_auth.make_session_token(u, path=users)
    assert dash_auth.parse_session_token(tok1, path=users)
    tok2 = dash_auth.make_session_token(u, path=users)
    assert dash_auth.parse_session_token(tok2, path=users)
    assert dash_auth.parse_session_token(tok1, path=users) is None  # вытеснена


def test_no_user_enumeration() -> None:
    tmp = Path(tempfile.mkdtemp())
    users = tmp / "users.json"
    users.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username": "anna",
                        "role": "manager",
                        "manager_id": "anna",
                        "display_name": "Анна",
                        "password_hash": dash_auth.hash_password("anna123"),
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    dash_auth._fail_log.clear()
    assert dash_auth.authenticate("nosuch", "x", path=users, client_ip="1.1.1.1") is None
    assert dash_auth.authenticate("anna", "bad", path=users, client_ip="1.1.1.1") is None
    # same public error constant used by API
    assert dash_auth.AUTH_ERROR == "Неверный логин или пароль"


def test_login_rate_limit() -> None:
    tmp = Path(tempfile.mkdtemp())
    users = tmp / "users.json"
    users.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "username": "anna",
                        "role": "manager",
                        "manager_id": "anna",
                        "password_hash": dash_auth.hash_password("anna123"),
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    os.environ["DASHBOARD_LOGIN_FAIL_LIMIT"] = "3"
    # reload module constants — patch directly
    old = dash_auth.LOGIN_FAIL_LIMIT
    dash_auth.LOGIN_FAIL_LIMIT = 3
    dash_auth._fail_log.clear()
    try:
        ip = "9.9.9.9"
        for _ in range(3):
            assert dash_auth.authenticate("anna", "wrong", path=users, client_ip=ip) is None
        assert dash_auth.login_rate_limited(ip)
        # even correct password blocked while limited
        assert dash_auth.authenticate("anna", "anna123", path=users, client_ip=ip) is None
    finally:
        dash_auth.LOGIN_FAIL_LIMIT = old
        dash_auth._fail_log.clear()


def test_manager_crud_and_invite() -> None:
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
            "distribution": {"mode": "even"},
            "setup_done": True,
        },
        users,
    )
    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    created = dash_auth.create_manager_user(
        username="ivan", display_name="Иван", manager_id="ivan", path=users
    )
    assert created["temp_password"]
    assert created["invite_token"]
    assert created["must_change_password"]
    u = dash_auth.authenticate("ivan", created["temp_password"], path=users)
    assert u and u.must_change_password
    accepted = dash_auth.accept_invite(created["invite_token"], "NewPass99!", path=users)
    assert accepted and not accepted.must_change_password
    assert dash_auth.authenticate("ivan", "NewPass99!", path=users)
    # reset
    tmp_pw = dash_auth.reset_password("ivan", path=users)
    assert dash_auth.authenticate("ivan", tmp_pw, path=users).must_change_password
    dash_auth.set_user_enabled("ivan", False, path=users)
    assert dash_auth.authenticate("ivan", tmp_pw, path=users) is None
    dash_auth.set_user_enabled("ivan", True, path=users)
    dash_auth.delete_user("ivan", path=users)
    assert dash_auth.find_user("ivan", path=users) is None


async def _client(tmp: Path):
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
                    },
                    {
                        "username": "anna",
                        "role": "manager",
                        "manager_id": "anna",
                        "display_name": "Анна",
                        "password_hash": dash_auth.hash_password("anna123"),
                        "enabled": True,
                        "must_change_password": False,
                        "session_jti": "",
                    },
                ],
                "distribution": {"mode": "even"},
                "setup_done": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    from bot.config import get_settings

    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    os.environ["DATABASE_PATH"] = str(tmp / "home24.db")
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    os.environ["HOME24_DASHBOARD_DEMO"] = "0"
    get_settings.cache_clear()
    reset_registry_cache()
    dash_auth._fail_log.clear()
    reg = ManagerRegistry(tmp / "managers.json")
    reg.upsert(manager_id="anna", name="Анна", make_default=True)
    reg.upsert(manager_id="ivan", name="Иван")
    store = Store(str(tmp / "home24.db"))
    seed_demo(store)
    assert get_settings().db_path == str(tmp / "home24.db")
    app = create_dashboard_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client, store, users


def test_guest_lockdown_and_login() -> None:
    import asyncio

    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        client, _store, _users = await _client(tmp)
        try:
            r = await client.get("/")
            assert r.status == 200
            text = await r.text()
            assert "Home24" not in text or "Вход" in text
            assert "Панель" not in text
            assert await r.text() and "Логин" in text
            # API / static / brand / accounts → 401
            for path in (
                "/api/dialogs",
                "/api/me",
                "/api/queue",
                "/static/dashboard.js",
                "/accounts/",
                "/app",
            ):
                r = await client.get(path, allow_redirects=False)
                if path == "/app":
                    assert r.status in (302, 401)
                else:
                    assert r.status == 401, path
            # wrong user / wrong password — same error
            r1 = await client.post(
                "/api/login", json={"username": "ghost", "password": "x"}
            )
            r2 = await client.post(
                "/api/login", json={"username": "anna", "password": "wrong"}
            )
            assert r1.status == 401 and r2.status == 401
            e1 = (await r1.json())["error"]
            e2 = (await r2.json())["error"]
            assert e1 == e2 == dash_auth.AUTH_ERROR
            # ok login
            r = await client.post(
                "/api/login", json={"username": "anna", "password": "anna123"}
            )
            assert r.status == 200
            body = await r.json()
            assert body["user"]["role"] == "manager"
            csrf = body["csrf"]
            r = await client.get("/api/me")
            assert r.status == 200
            r = await client.get("/static/dashboard.js")
            assert r.status == 200
            # csrf
            r = await client.post(
                "/api/dialogs/demo-1001/takeover",
                json={"active": True},
            )
            assert r.status == 403
            r = await client.post(
                "/api/dialogs/demo-1001/takeover",
                json={"active": True},
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200
        finally:
            await client.close()

    asyncio.run(run())


def test_manager_scope_and_admin_all() -> None:
    import asyncio

    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        client, store, _users = await _client(tmp)
        try:
            r = await client.post(
                "/api/login", json={"username": "anna", "password": "anna123"}
            )
            csrf = (await r.json())["csrf"]
            r = await client.get("/api/dialogs")
            dialogs = (await r.json())["dialogs"]
            assert dialogs
            assert all(
                (d.get("manager_id") in ("anna", "", None) or d["manager_id"] == "anna")
                for d in dialogs
            )
            r = await client.post(
                "/api/dialogs/demo-2001/reply",
                json={"text": "привет"},
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status in (403, 409)
            import bot.dashboard.app as dash_app

            dash_app.DEMO = True
            r = await client.post(
                "/api/dialogs/demo-1001/reply",
                json={"text": "Ответ с панели DEMO"},
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200
            msgs = store.list_messages("demo-1001", limit=50)
            assert any(m["role"] == "manager" and "панели" in m["text"] for m in msgs)
            # manager cannot list users
            r = await client.get("/api/users")
            assert r.status == 403
            await client.post("/api/logout", headers={"X-CSRF-Token": csrf}, json={})
            # admin
            r = await client.post(
                "/api/login", json={"username": "admin", "password": "admin123"}
            )
            csrf = (await r.json())["csrf"]
            r = await client.get("/api/dialogs")
            mids = {d.get("manager_id") for d in (await r.json())["dialogs"]}
            assert "anna" in mids or len(mids) >= 1
            r = await client.get("/api/users")
            assert r.status == 200
            assert any(u["username"] == "anna" for u in (await r.json())["users"])
            # create manager
            r = await client.post(
                "/api/users",
                json={"username": "oleg", "display_name": "Олег", "manager_id": "oleg"},
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200
            created = await r.json()
            assert created["temp_password"] and created["invite_url"]
        finally:
            await client.close()

    asyncio.run(run())


def test_single_session_via_api() -> None:
    import asyncio

    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        client, _store, _users = await _client(tmp)
        try:
            r1 = await client.post(
                "/api/login", json={"username": "anna", "password": "anna123"}
            )
            assert r1.status == 200
            # second login on "another browser"
            client2 = TestClient(TestServer(create_dashboard_app()))
            await client2.start_server()
            try:
                r2 = await client2.post(
                    "/api/login", json={"username": "anna", "password": "anna123"}
                )
                assert r2.status == 200
                # old session dead
                r = await client.get("/api/me")
                assert r.status == 401
                r = await client2.get("/api/me")
                assert r.status == 200
            finally:
                await client2.close()
        finally:
            await client.close()

    asyncio.run(run())


def test_distribute_even() -> None:
    tmp = Path(tempfile.mkdtemp())
    users = tmp / "users.json"
    dash_auth.save_store(
        {
            "users": [
                {
                    "username": "admin",
                    "role": "admin",
                    "manager_id": "",
                    "password_hash": dash_auth.hash_password("x"),
                    "enabled": True,
                },
                {
                    "username": "anna",
                    "role": "manager",
                    "manager_id": "anna",
                    "password_hash": dash_auth.hash_password("x"),
                    "enabled": True,
                },
                {
                    "username": "ivan",
                    "role": "manager",
                    "manager_id": "ivan",
                    "password_hash": dash_auth.hash_password("x"),
                    "enabled": True,
                },
            ],
            "distribution": {"mode": "even"},
        },
        users,
    )
    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    reset_registry_cache()
    reg = ManagerRegistry(tmp / "managers.json")
    reg.upsert(manager_id="anna", name="Анна", make_default=True)
    reg.upsert(manager_id="ivan", name="Иван")
    reg.set_session("anna", "SESS")
    reg.set_session("ivan", "SESS2")
    store = Store(str(tmp / "db.sqlite"))
    for i in range(4):
        store.add_contact(phone=f"+7900000000{i}", name=f"C{i}")
    result = on_manager_telegram_linked(store, "ivan")
    assert result["assigned"] == 4
    mids = [
        store.contact_by_phone(f"+7900000000{i}")["manager_id"] for i in range(4)
    ]
    assert set(mids) == {"anna", "ivan"}
    assert mids.count("anna") == 2 and mids.count("ivan") == 2
    # manual — no more
    dash_auth.set_distribution_mode("manual", path=users)
    store.add_contact(phone="[REDACTED]", name="X")
    r2 = redistribute_unassigned(store)
    assert r2["assigned"] == 0 and r2["skipped"] == "manual"


if __name__ == "__main__":
    test_password_hash_roundtrip()
    test_bootstrap_first_admin()
    test_session_single_login()
    test_no_user_enumeration()
    test_login_rate_limit()
    test_manager_crud_and_invite()
    test_guest_lockdown_and_login()
    test_manager_scope_and_admin_all()
    test_single_session_via_api()
    test_distribute_even()
    print("ok")
