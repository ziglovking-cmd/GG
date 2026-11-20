# -*- coding: utf-8 -*-
"""Шаблоны ответов менеджера: store, fill, API preserve-on-update."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.reply_templates import (
    TemplateStore,
    fill_template,
    placeholder_vars,
    reset_template_store_cache,
)


def test_seed_and_preserve_on_update() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "templates.json"
    store = TemplateStore(path)
    assert path.exists()
    cats = {t["category"] for t in store.templates if t["scope"] == "shared"}
    assert cats == {"greeting", "closing"}
    assert len(store.templates) >= 6
    assert all(t["category"] in ("greeting", "closing") for t in store.templates)
    # пользовательский шаблон + правка дефолта
    store.upsert(
        tid=None,
        title="Мой",
        body="Привет {имя}",
        category="greeting",
        scope="personal",
        owner="anna",
        actor="anna",
        is_admin=False,
    )
    greet = store.get("greet_takeover")
    assert greet
    store.upsert(
        tid="greet_takeover",
        title="Кастомный перехват",
        body="Свой текст {имя}",
        category="greeting",
        scope="shared",
        owner="",
        actor="admin",
        is_admin=True,
    )
    # «обновление» приложения: новый store на том же файле не затирает правки
    store2 = TemplateStore(path)
    assert store2.get("greet_takeover")["body"] == "Свой текст {имя}"
    assert store2.get("greet_takeover")["title"] == "Кастомный перехват"
    personal = [t for t in store2.templates if t["scope"] == "personal"]
    assert len(personal) == 1
    assert personal[0]["owner"] == "anna"
    # недостающий дефолт добавляется
    data = json.loads(path.read_text(encoding="utf-8"))
    data["templates"] = [t for t in data["templates"] if t["id"] != "closing_thanks"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    store3 = TemplateStore(path)
    assert store3.get("closing_thanks") is not None
    assert store3.get("greet_takeover")["body"] == "Свой текст {имя}"


def test_obsolete_stock_templates_pruned_on_load() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "templates.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "templates": [
                    {
                        "id": "ask_dates",
                        "category": "dates_guests",
                        "title": "Уточнить даты",
                        "body": "даты?",
                        "scope": "shared",
                        "owner": "",
                        "enabled": True,
                        "sort": 10,
                    },
                    {
                        "id": "greet_takeover",
                        "category": "greeting",
                        "title": "Мой перехват",
                        "body": "Привет {имя}, это {менеджер}",
                        "scope": "shared",
                        "owner": "",
                        "enabled": True,
                        "sort": 10,
                    },
                    {
                        "id": "custom_shared",
                        "category": "greeting",
                        "title": "Свой общий",
                        "body": "Кастом",
                        "scope": "shared",
                        "owner": "",
                        "enabled": True,
                        "sort": 99,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = TemplateStore(path)
    assert store.get("ask_dates") is None
    assert store.get("greet_takeover")["body"] == "Привет {имя}, это {менеджер}"
    assert store.get("custom_shared") is not None
    assert store.get("closing_thanks") is not None  # недостающий дефолт добавлен


def test_fill_placeholders_and_conditionals() -> None:
    vars_map = {"имя": "Мария", "менеджер": "Иван"}
    body = "Здравствуйте{, имя}! Это Home24, команда {менеджер}."
    out = fill_template(body, vars_map)
    assert out == "Здравствуйте, Мария! Это Home24, команда Иван."

    empty = fill_template("Здравствуйте{, имя}!", {"имя": "", "менеджер": "Анна"})
    assert empty == "Здравствуйте!"


def test_placeholder_vars_from_dialog_and_catalog() -> None:
    dialog = {
        "name": "DEMO · Мария К.",
        "dates": "12–15 октября",
        "guests": "2 человека",
        "district": "Коммунарка",
        "favorite": "Феррари",
        "context": {},
    }
    v = placeholder_vars(dialog, manager_name="Иван")
    assert v["имя"] == "Мария"
    assert v["даты"] == "12–15 октября"
    assert "Феррари" in v["квартира"] or v["квартира"] == "Феррари"
    # цена из mailing.sqlite если есть
    assert v["цена"]
    assert v["менеджер"] == "Иван"


def test_list_for_scopes() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "t.json"
    store = TemplateStore(path)
    store.upsert(
        tid=None,
        title="Личное Анны",
        body="x",
        category="closing",
        scope="personal",
        owner="anna",
        actor="anna",
        is_admin=False,
    )
    store.upsert(
        tid=None,
        title="Личное Ивана",
        body="y",
        category="closing",
        scope="personal",
        owner="ivan",
        actor="ivan",
        is_admin=False,
    )
    anna = store.list_for(username="anna")
    assert any(t["title"] == "Личное Анны" for t in anna)
    assert not any(t["title"] == "Личное Ивана" for t in anna)
    assert any(t["scope"] == "shared" for t in anna)


def test_api_templates_list_and_fill() -> None:
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from bot.config import get_settings
    from bot.dashboard import auth as dash_auth
    from bot.dashboard.app import create_dashboard_app
    from bot.managers import reset_registry_cache
    from bot.store import Store
    from bot.tg_accounts import reset_tg_accounts_cache

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
    os.environ["TEMPLATES_PATH"] = str(tmp / "templates.json")
    os.environ["DASHBOARD_USERS_PATH"] = str(users)
    os.environ["DATABASE_PATH"] = str(tmp / "db.sqlite")
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg.json")
    os.environ["HOME24_DASHBOARD_DEMO"] = "0"
    os.environ["DASHBOARD_SECRET"] = "test-secret-templates"
    get_settings.cache_clear()
    reset_registry_cache()
    reset_tg_accounts_cache()
    reset_template_store_cache()

    store = Store(str(tmp / "db.sqlite"))
    store.get_session("c1")
    store.save_session(
        "c1",
        name="Ольга",
        dates="5–7 ноября",
        guests="2",
        district="центр",
        favorite="Феррари",
        manager_id="",
    )

    async def run():
        app = create_dashboard_app()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.post(
                "/api/login", json={"username": "admin", "password": "admin123"}
            )
            assert r.status == 200, await r.text()
            csrf = (await r.json())["csrf"]
            r = await client.get("/api/templates?chat_id=c1")
            assert r.status == 200, await r.text()
            data = await r.json()
            assert len(data["templates"]) >= 6
            assert {t["category"] for t in data["templates"] if t["scope"] == "shared"} <= {
                "greeting",
                "closing",
            }
            assert data["vars"]["имя"] == "Ольга"
            r = await client.post(
                "/api/templates",
                json={
                    "title": "Тест",
                    "body": "Привет {имя}, даты {даты}",
                    "category": "greeting",
                    "scope": "shared",
                },
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200, await r.text()
            created = (await r.json())["template"]
            r = await client.get("/api/templates?chat_id=c1")
            data = await r.json()
            hit = next(t for t in data["templates"] if t["id"] == created["id"])
            assert "Ольга" in hit["filled"]
            assert "5–7 ноября" in hit["filled"]
            r = await client.delete(
                f"/api/templates/{created['id']}",
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status == 200
        finally:
            await client.close()

    asyncio.run(run())


if __name__ == "__main__":
    test_seed_and_preserve_on_update()
    test_fill_placeholders_and_conditionals()
    test_placeholder_vars_from_dialog_and_catalog()
    test_list_for_scopes()
    test_api_templates_list_and_fill()
    print("test_reply_templates OK")
