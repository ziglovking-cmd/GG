"""Демо-данные для скриншота дашборда (явно помечены как DEMO). 5 менеджеров."""

from __future__ import annotations

import time
from typing import Any

from bot.store import Store

DEMO_MANAGERS = (
    ("anna", "Анна"),
    ("ivan", "Иван"),
    ("maria", "Мария"),
    ("oleg", "Олег"),
    ("elena", "Елена"),
)

DEMO_MANAGER_[REDACTED]


def ensure_demo_managers() -> None:
    from bot.managers import get_registry

    reg = get_registry()
    for i, (mid, name) in enumerate(DEMO_MANAGERS):
        reg.upsert(
            manager_id=mid,
            name=name,
            make_default=(i == 0),
            share_weight=1,
            daily_send_limit=30,
            weekly_send_limit=210,
        )


def ensure_demo_users() -> None:
    """Веб-пользователи 5 менеджеров — чтобы доли в Настройках считались по активным."""
    from bot.dashboard import auth as dash_auth

    dash_auth.ensure_users_file()
    for mid, name in DEMO_MANAGERS:
        if dash_auth.find_user(mid):
            try:
                data = dash_auth.load_store()
                dirty = False
                for u in data.get("users") or []:
                    if str(u.get("username") or "").lower() != mid:
                        continue
                    if u.get("must_change_password"):
                        u["must_change_password"] = False
                        u["password_hash"] = dash_auth.hash_password(
                            DEMO_MANAGER_PASSWORD
                        )
                        dirty = True
                    if (u.get("display_name") or "") != name:
                        u["display_name"] = name
                        dirty = True
                if dirty:
                    dash_auth.save_store(data)
            except Exception:
                pass
            continue
        try:
            dash_auth.create_manager_user(
                username=mid,
                display_name=name,
                manager_id=mid,
                temp_[REDACTED]
            )
            data = dash_auth.load_store()
            for u in data.get("users") or []:
                if str(u.get("username") or "").lower() == mid:
                    u["must_change_password"] = False
            dash_auth.save_store(data)
        except ValueError:
            pass


def seed_demo(store: Store) -> dict[str, Any]:
    """Наполнить БД фейковыми диалогами. Не трогает реальные контакты."""
    ensure_demo_managers()
    ensure_demo_users()
    now = time.time()
    demos = [
        {
            "chat_id": "demo-1001",
            "name": "DEMO · Ольга",
            "manager_id": "anna",
            "step": "await_dates",
            "phone": "+7900DEMO01",
            "tg_status": "ok",
            "msgs": [
                ("bot", "Здравствуйте! Это Home24 — рады помочь снова 🙂", "бот"),
                ("guest", "Привет, ищем квартиру на выходные", ""),
                ("bot", "Подскажите, на какие даты смотрите?", "бот"),
            ],
        },
        {
            "chat_id": "demo-1002",
            "name": "DEMO · Александр",
            "manager_id": "anna",
            "step": "await_district",
            "phone": "+7900DEMO02",
            "tg_status": "ok",
            "msgs": [
                ("bot", "Добрый день! Чем могу помочь?", "бот"),
                ("guest", "Нас будет двое, центр предпочтительнее", ""),
                ("manager", "Уточню варианты в центре на эти даты", "Анна"),
            ],
        },
        {
            "chat_id": "demo-2001",
            "name": "DEMO · Мария К.",
            "manager_id": "ivan",
            "step": "handed_off",
            "phone": "+7900DEMO03",
            "tg_status": "ok",
            "dates": "12–15 октября",
            "guests": "2 человека",
            "district": "Коммунарка",
            "favorite": "Феррари",
            "msgs": [
                ("guest", "Спасибо, жду менеджера", ""),
                ("bot", "Передала коллеге — обычно 10–15 минут 🙂", "бот"),
                ("manager", "Добрый день! Я Иван, сейчас подберу варианты.", "Иван"),
            ],
        },
        {
            "chat_id": "demo-3001",
            "name": "DEMO · Сергей",
            "manager_id": "maria",
            "step": "await_intent",
            "phone": "+7900DEMO04",
            "tg_status": "ok",
            "msgs": [
                ("bot", "Здравствуйте! Это Home24 — апартаменты в Москве.", "бот"),
                ("guest", "Сколько стоит у метро?", ""),
            ],
        },
        {
            "chat_id": "demo-4001",
            "name": "DEMO · нет в Telegram",
            "manager_id": "oleg",
            "step": "greeting",
            "phone": "+7900DEMO05",
            "tg_status": "нет в Telegram",
            "msgs": [],
        },
        {
            "chat_id": "demo-5001",
            "name": "DEMO · Наталья",
            "manager_id": "elena",
            "step": "await_dates",
            "phone": "+7900DEMO06",
            "tg_status": "ok",
            "msgs": [
                ("bot", "Добрый вечер! Подскажите даты заезда?", "бот"),
                ("guest", "С 12 по 15 число", ""),
            ],
        },
    ]
    for d in demos:
        store.add_contact(d["phone"], name=d["name"], manager_id=d["manager_id"])
        store.update_contact(
            d["phone"], chat_id=d["chat_id"], status="sent", manager_id=d["manager_id"]
        )
        store.set_contact_telegram(
            d["phone"],
            telegram_user_id=d["chat_id"] if d["tg_status"] == "ok" else "",
            tg_status=d["tg_status"],
            tg_account_id="main",
        )
        store.get_session(d["chat_id"])
        store.save_session(
            d["chat_id"],
            name=d["name"],
            step=d["step"],
            manager_id=d["manager_id"],
            handed_off=1 if d["step"] == "handed_off" else 0,
            dates=d.get("dates") or "",
            guests=d.get("guests") or "",
            district=d.get("district") or "",
            favorite=d.get("favorite") or "",
            context={
                "demo": True,
                "next": "уточнить даты" if "dates" in d["step"] else "",
                "tg_status": d["tg_status"],
                "dates": d.get("dates") or "",
                "guests": d.get("guests") or "",
                "district": d.get("district") or "",
                "favorite": d.get("favorite") or "",
            },
        )
        store._conn.execute("DELETE FROM messages WHERE chat_id=?", (d["chat_id"],))
        store._conn.commit()
        t0 = now - 600
        for i, (role, text, label) in enumerate(d["msgs"]):
            store._conn.execute(
                "INSERT INTO messages(chat_id,role,text,sender_label,created_at) "
                "VALUES(?,?,?,?,?)",
                (d["chat_id"], role, text, label, t0 + i * 90),
            )
        store._conn.commit()
    return {"ok": True, "dialogs": len(demos), "managers": 5, "mark": "DEMO"}
