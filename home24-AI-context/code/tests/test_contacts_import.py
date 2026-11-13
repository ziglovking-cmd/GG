"""ImportContacts перед первым сообщением: кэш, skip, «нет в Telegram»."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.contacts_import import (
    TG_ALREADY_CONTACT,
    TG_HAS_DIALOG,
    TG_MISSING,
    TG_OK,
    _split_name,
    ensure_telegram_user,
)
from bot.store import Store


class FakeUser:
    def __init__(self, uid: int, phone: str = "") -> None:
        self.id = uid
        self.phone = phone


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.contacts_users: list[FakeUser] = []
        self.import_users: list[FakeUser] = []
        self.imported_rows: list[Any] = []
        self.retry_ids: list[int] = []
        self.resolve_user: FakeUser | None = None
        self.entity_by_phone: dict[str, FakeUser] = {}
        self.flood: Exception | None = None

    async def __call__(self, req: Any) -> Any:
        name = type(req).__name__
        self.calls.append(name)
        if self.flood and "Import" in name:
            raise self.flood
        if name == "GetContactsRequest":
            return SimpleNamespace(users=list(self.contacts_users))
        if name == "ImportContactsRequest":
            # ровно один контакт в запросе
            assert len(req.contacts) == 1
            return SimpleNamespace(
                users=list(self.import_users),
                imported=list(self.imported_rows),
                retry_contacts=list(self.retry_ids),
            )
        if name == "ResolvePhoneRequest":
            users = [self.resolve_user] if self.resolve_user else []
            return SimpleNamespace(users=users)
        raise AssertionError(f"unexpected request {name}")

    async def get_entity(self, [REDACTED] -> FakeUser:
        if isinstance(key, str) and key in self.entity_by_phone:
            return self.entity_by_phone[key]
        raise ValueError("not found")


def test_split_name() -> None:
    assert _split_name("Иван Петров") == ("Иван", "Петров")
    assert _split_name("Мария") == ("Мария", "")
    assert _split_name("")[0] == "Клиент"


def test_uses_db_name_and_imports_once() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="Ольга Смирнова")
        client = FakeClient()
        client.import_users = [FakeUser(555001, "[REDACTED]")]

        uid, st = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid == "555001" and st == TG_OK
        assert "ImportContactsRequest" in client.calls
        row = store.contact_by_phone("[REDACTED]")
        assert row["telegram_user_id"] == "555001"
        assert row["tg_status"] == TG_OK
        assert row["tg_account_id"] == "main"
        # имя ушло в ImportContacts
        # повтор — из кэша, без нового Import
        client.calls.clear()
        uid2, st2 = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid2 == "555001" and st2 == TG_OK
        assert "ImportContactsRequest" not in client.calls

    asyncio.run(run())


def test_skip_if_already_contact() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="Пётр")
        client = FakeClient()
        client.contacts_users = [FakeUser(777, "[REDACTED]")]
        client.import_users = [FakeUser(999, "[REDACTED]")]  # не должны дойти

        uid, st = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid == "777" and st == TG_ALREADY_CONTACT
        assert "ImportContactsRequest" not in client.calls
        assert store.contact_by_phone("[REDACTED]")["telegram_user_id"] == "777"

    asyncio.run(run())


def test_skip_if_db_dialog_exists() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="Анна")
        store.update_contact("[REDACTED]", chat_id="888001", status="pending")
        client = FakeClient()
        client.import_users = [FakeUser(1)]

        uid, st = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid == "888001" and st == TG_HAS_DIALOG
        assert "ImportContactsRequest" not in client.calls

    asyncio.run(run())


def test_skip_if_telethon_dialog() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="Игорь")
        client = FakeClient()
        client.entity_by_phone["[REDACTED]"] = FakeUser(4242)
        client.import_users = [FakeUser(1)]

        uid, st = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid == "4242" and st == TG_HAS_DIALOG
        assert "ImportContactsRequest" not in client.calls

    asyncio.run(run())


def test_missing_on_telegram() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="НетТакого")
        client = FakeClient()
        client.import_users = []  # пустой ответ = нет в Telegram

        uid, st = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid is None and st == TG_MISSING
        row = store.contact_by_phone("[REDACTED]")
        assert row["tg_status"] == "нет в Telegram"
        # повтор сразу skip без Import
        client.calls.clear()
        uid2, st2 = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid2 is None and st2 == TG_MISSING
        assert "ImportContactsRequest" not in client.calls

    asyncio.run(run())


def test_imported_id_without_users() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="Карма")
        client = FakeClient()
        client.imported_rows = [SimpleNamespace([REDACTED])]

        uid, st = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid == "9090" and st == TG_OK
        assert "ResolvePhoneRequest" not in client.calls

    asyncio.run(run())


def test_resolve_phone_when_import_empty() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="Лена")
        client = FakeClient()
        client.resolve_user = FakeUser(3131)

        uid, st = await ensure_telegram_user(
            client, store, phone="[REDACTED]", account_id="main"
        )
        assert uid == "3131" and st == TG_OK
        assert "ResolvePhoneRequest" in client.calls

    asyncio.run(run())


def test_requeue_clears_missing_cache() -> None:
    tmp = Path(tempfile.mkdtemp())
    store = Store(str(tmp / "db.sqlite"))
    store.add_contact("[REDACTED]", name="", manager_id="anna")
    store.set_contact_telegram(
        "[REDACTED]",
        telegram_user_id="",
        tg_status=TG_MISSING,
        tg_account_id="main",
    )
    store.update_contact("[REDACTED]", status="failed", last_error=TG_MISSING)
    store.add_contact("[REDACTED]", manager_id="anna")
    row = store.contact_by_phone("[REDACTED]")
    assert row["status"] == "pending"
    assert row["tg_status"] == ""
    assert row["last_error"] == ""


def test_floodwait_propagates() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="Flood")
        client = FakeClient()

        class FloodWaitError(Exception):
            seconds = 30

        FloodWaitError.__name__ = "FloodWaitError"
        client.flood = FloodWaitError("wait")

        try:
            await ensure_telegram_user(
                client, store, phone="[REDACTED]", account_id="main"
            )
            assert False, "should raise"
        except Exception as e:
            assert "FloodWait" in type(e).__name__

    asyncio.run(run())


def test_one_contact_per_import_request() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        store = Store(str(tmp / "db.sqlite"))
        store.add_contact("[REDACTED]", name="Алексей Иванов")
        client = FakeClient()
        client.import_users = [FakeUser(12)]
        await ensure_telegram_user(
            client, store, phone="[REDACTED]", name="Алексей Иванов", account_id="main"
        )
        assert client.calls.count("ImportContactsRequest") == 1

    asyncio.run(run())


def test_dashboard_dialog_exposes_tg_status() -> None:
    """Карточка клиента в API отдаёт tg_status."""
    import json
    import os

    from aiohttp.test_utils import TestClient, TestServer

    from bot.dashboard import auth as dash_auth
    from bot.dashboard.app import create_dashboard_app
    from bot.managers import ManagerRegistry, reset_registry_cache

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
                    "setup_done": True,
                }
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
        ManagerRegistry(tmp / "managers.json").upsert(
            manager_id="anna", name="Анна", make_default=True
        )
        store = Store(str(tmp / "home24.db"))
        store.add_contact("+7900STATUS", name="Статус", manager_id="anna")
        store.update_contact("+7900STATUS", chat_id="demo-status-1", status="sent")
        store.set_contact_telegram(
            "+7900STATUS",
            telegram_user_id="",
            tg_status=TG_MISSING,
            tg_account_id="main",
        )
        store.get_session("demo-status-1")
        store.save_session(
            "demo-status-1", name="Статус", manager_id="anna", step="greeting"
        )
        app = create_dashboard_app()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.post(
                "/api/login", json={"username": "admin", "password": "admin123"}
            )
            assert r.status == 200
            r = await client.get("/api/dialogs/demo-status-1")
            assert r.status == 200
            body = await r.json()
            assert body["dialog"]["tg_status"] == "нет в Telegram"
        finally:
            await client.close()

    asyncio.run(run())


if __name__ == "__main__":
    test_split_name()
    test_uses_db_name_and_imports_once()
    test_skip_if_already_contact()
    test_skip_if_db_dialog_exists()
    test_skip_if_telethon_dialog()
    test_missing_on_telegram()
    test_imported_id_without_users()
    test_resolve_phone_when_import_empty()
    test_requeue_clears_missing_cache()
    test_floodwait_propagates()
    test_one_contact_per_import_request()
    test_dashboard_dialog_exposes_tg_status()
    print("ok")
