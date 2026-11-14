# -*- coding: utf-8 -*-
"""Архив не прячет ждущий чат и возвращает его, когда гость пишет."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.store import Store


def test_archive_pin_note_and_guest_return() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(str(Path(tmp) / "t.db"))
        store.save_session("c1", name="Мария", manager_id="anna", step="handed_off", handed_off=1)
        store.add_message("c1", "bot", "Добрый день")
        store.save_session("c1", archived=1, pinned=0, note="предоплата")
        live = store.list_dialogs(admin=True)
        assert all(d["chat_id"] != "c1" for d in live)
        arch = store.list_dialogs(admin=True, only_archived=True)
        assert arch[0]["chat_id"] == "c1"
        assert arch[0]["note"] == "предоплата"
        store.add_message("c1", "guest", "Я на месте")
        back = store.list_dialogs(admin=True)
        assert back[0]["chat_id"] == "c1"
        assert int(back[0]["archived"] or 0) == 0
        assert store.get_session("c1")["note"] == "предоплата"


def test_archive_quiet_keeps_waiting_and_pinned() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(str(Path(tmp) / "t.db"))
        import time

        old = time.time() - 4 * 86400
        store.save_session("wait", name="Ждёт", manager_id="anna")
        store.add_message("wait", "guest", "Завтра можно?")
        store._conn.execute("UPDATE sessions SET updated_at=? WHERE chat_id='wait'", (old,))
        store.save_session("quiet", name="Тихий", manager_id="anna")
        store.add_message("quiet", "bot", "Напишу, если появятся даты")
        store._conn.execute("UPDATE sessions SET updated_at=? WHERE chat_id='quiet'", (old,))
        store.save_session("pin", name="Важный", manager_id="anna", pinned=1)
        store.add_message("pin", "bot", "Держу")
        store._conn.execute("UPDATE sessions SET updated_at=? WHERE chat_id='pin'", (old,))
        store._conn.commit()
        n = store.archive_quiet(now=old + 4 * 86400)
        assert n == 1
        ids = {d["chat_id"] for d in store.list_dialogs(admin=True)}
        assert ids == {"wait", "pin"}
        snap = store.desk_snapshot(now=old + 4 * 86400)
        assert snap["waiting"] == 1
        assert snap["archived"] == 1
        assert snap["pinned"] == 1
        hits = store.search_messages("завтра", admin=True)
        assert hits and hits[0]["chat_id"] == "wait"


def test_tone_hide_after_two_days_purge_after_week() -> None:
    import time

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(str(Path(tmp) / "t.db"))
        now = time.time()
        store.save_session(
            "ready",
            name="Ольга",
            manager_id="anna",
            step="browsing",
            dates="12–14 мая",
            guests="2",
            district="Прокшино",
            favorite="Лофт",
        )
        store.save_session(
            "work",
            name="Илья",
            manager_id="anna",
            step="await_guests",
            dates="май",
        )
        store.save_session("fresh", name="Свежий", manager_id="anna", step="done")
        store.add_message("fresh", "bot", "До встречи")
        fresh_at = now - 3600
        store._conn.execute(
            "UPDATE sessions SET updated_at=? WHERE chat_id='fresh'", (fresh_at,)
        )
        store._conn.execute(
            "UPDATE messages SET created_at=? WHERE chat_id='fresh'", (fresh_at,)
        )
        store.save_session("stale", name="Старый", manager_id="anna", step="done")
        store.add_message("stale", "bot", "Закрыли")
        stale_at = now - 3 * 86400
        store._conn.execute(
            "UPDATE sessions SET updated_at=? WHERE chat_id='stale'", (stale_at,)
        )
        store._conn.execute(
            "UPDATE messages SET created_at=? WHERE chat_id='stale'", (stale_at,)
        )
        store.save_session(
            "held", name="Важный", manager_id="anna", step="done", pinned=1
        )
        store.add_message("held", "bot", "Держу")
        store._conn.execute(
            "UPDATE sessions SET updated_at=? WHERE chat_id='held'", (stale_at,)
        )
        store._conn.execute(
            "UPDATE messages SET created_at=? WHERE chat_id='held'", (stale_at,)
        )
        store.add_contact("[REDACTED]", name="Ушедший")
        store.save_session("gone", name="Ушедший", manager_id="anna", step="done")
        store.add_message("gone", "guest", "Спасибо, больше не нужно")
        gone_at = now - 8 * 86400
        store._conn.execute(
            "UPDATE sessions SET updated_at=? WHERE chat_id='gone'", (gone_at,)
        )
        store._conn.execute(
            "UPDATE messages SET created_at=? WHERE chat_id='gone'", (gone_at,)
        )
        store._conn.commit()

        live = store.list_dialogs(admin=True, now=now)
        ids = [d["chat_id"] for d in live]
        assert "gone" not in ids
        assert "stale" not in ids
        assert "fresh" in ids
        assert "held" in ids
        assert ids.index("ready") < ids.index("work")
        by_id = {d["chat_id"]: d for d in live}
        assert by_id["ready"]["tone"] == "ready"
        assert by_id["ready"]["brief"] == "12–14 мая · 2 гост. · Прокшино · Лофт"
        assert by_id["work"]["tone"] == "work"
        assert by_id["fresh"]["tone"] == "done"
        assert by_id["held"]["tone"] == "done"
        arch = {d["chat_id"] for d in store.list_dialogs(admin=True, only_archived=True, now=now)}
        assert "stale" in arch
        assert "fresh" not in arch
        assert store.peek_session("gone") is None
        assert store._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE chat_id='gone'"
        ).fetchone()[0] == 0
        assert store._conn.execute(
            "SELECT COUNT(*) FROM contacts WHERE phone='[REDACTED]'"
        ).fetchone()[0] == 1


def test_peek_does_not_create_and_stranger_cannot_open() -> None:
    from bot.dashboard.app import _chat_access
    from bot.dashboard.auth import DashUser

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(str(Path(tmp) / "t.db"))
        assert store.peek_session("missing") is None
        anna = DashUser("anna", "manager", "anna", "Анна")
        ivan = DashUser("ivan", "manager", "ivan", "Иван")
        admin = DashUser("admin", "admin", "", "Админ")
        missing = _chat_access(admin, store, "missing")
        assert getattr(missing, "status", None) == 404
        assert store.peek_session("missing") is None
        store.save_session("c1", name="Мария", manager_id="anna")
        assert getattr(_chat_access(ivan, store, "c1"), "status", None) == 403
        ok_anna, mid = _chat_access(anna, store, "c1")
        assert ok_anna["name"] == "Мария" and mid == "anna"
        ok_admin, _mid = _chat_access(admin, store, "c1")
        assert ok_admin["chat_id"] == "c1"


if __name__ == "__main__":
    test_archive_pin_note_and_guest_return()
    test_archive_quiet_keeps_waiting_and_pinned()
    test_tone_hide_after_two_days_purge_after_week()
    print("ok")
