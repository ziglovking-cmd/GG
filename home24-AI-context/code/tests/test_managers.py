"""Мульти-менеджеры: назначение, глобальный стоп/14 дней, лимиты на менеджера."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.managers import ManagerRegistry, reset_registry_cache
from bot.rate_limit import OutreachLimiter
from bot.store import OUTREACH_RESEND_COOLDOWN_SEC, Store


def test_registry_bootstrap_and_upsert() -> None:
    d = Path(tempfile.mkdtemp())
    path = d / "managers.json"
    reset_registry_cache()
    reg = ManagerRegistry(path)
    assert reg.default_manager_id
    assert reg.default().name
    reg.upsert(manager_id="ivan", name="Иван", phone="+7900", daily_send_limit=50)
    reg2 = ManagerRegistry(path)
    assert "ivan" in reg2.managers
    assert reg2.managers["ivan"].daily_send_limit == 50
    pub = reg2.list_public()
    assert all("session" not in p for p in pub)
    assert any(p["id"] == "ivan" for p in pub)


def test_assignment_one_manager() -> None:
    d = Path(tempfile.mkdtemp())
    store = Store(str(d / "t.db"))
    store.add_contact("[REDACTED]", name="A", manager_id="anna")
    store.add_contact("[REDACTED]", name="B", manager_id="ivan")
    store.add_contact("[REDACTED]", name="C")  # unassigned

    anna = store.list_outreach_batch(
        limit=50, manager_id="anna", default_manager_id="anna"
    )
    phones_a = {c["phone"] for c in anna}
    assert "[REDACTED]" in phones_a
    assert "[REDACTED]" in phones_a  # default забирает незакреплённых
    assert "[REDACTED]" not in phones_a

    ivan = store.list_outreach_batch(
        limit=50, manager_id="ivan", default_manager_id="anna"
    )
    phones_i = {c["phone"] for c in ivan}
    assert "[REDACTED]" in phones_i
    assert "[REDACTED]" not in phones_i
    assert "[REDACTED]" not in phones_i


def test_no_reassign_after_sent() -> None:
    d = Path(tempfile.mkdtemp())
    store = Store(str(d / "t.db"))
    store.add_contact("[REDACTED]", manager_id="anna")
    store.update_contact("[REDACTED]", status="sent", chat_id="111")
    ok, why = store.assign_manager("[REDACTED]", "ivan")
    assert ok is False
    assert "нельзя" in why or "писали" in why or "sent" in why


def test_global_stop_list() -> None:
    d = Path(tempfile.mkdtemp())
    store = Store(str(d / "t.db"))
    store.add_contact("[REDACTED]", manager_id="anna")
    store.update_contact("[REDACTED]", chat_id="555")
    store.mark_stopped(phone="[REDACTED]", chat_id="555")
    assert store.is_stopped_chat("555")
    assert store.is_globally_stopped(phone="[REDACTED]")
    assert store.is_globally_stopped(chat_id="555")
    # второй менеджер тоже не должен брать
    store.add_contact("[REDACTED]", manager_id="ivan")
    row = store.contact_by_phone("[REDACTED]")
    assert row and row["status"] == "stopped"
    batch = store.list_outreach_batch(
        limit=20, manager_id="ivan", default_manager_id="anna"
    )
    assert all(c["phone"] != "[REDACTED]" for c in batch)


def test_global_14_day_resend() -> None:
    d = Path(tempfile.mkdtemp())
    store = Store(str(d / "t.db"))
    store.add_contact("[REDACTED]", manager_id="anna")
    store.update_contact(
        "[REDACTED]",
        status="sent",
        chat_id="666",
        updated_at=time.time(),
    )
    assert store.recently_sent_global(phone="[REDACTED]")
    # попытка снова добавить в pending — статус не сбрасывается в pending
    store.add_contact("[REDACTED]", manager_id="ivan")
    row = store.contact_by_phone("[REDACTED]")
    assert row["status"] == "sent"
    # после cooldown можно
    store.update_contact(
        "[REDACTED]",
        status="sent",
        updated_at=time.time() - OUTREACH_RESEND_COOLDOWN_SEC - 10,
    )
    assert not store.recently_sent_global(phone="[REDACTED]")


def test_per_manager_daily_limits() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    d = Path(tempfile.mkdtemp())
    store = Store(str(d / "t.db"))

    class Noon(OutreachLimiter):
        def now(self):
            return datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    a = Noon(store, manager_id="anna", daily_limit=2, work_start=10, work_end=20)
    b = Noon(store, manager_id="ivan", daily_limit=5, work_start=10, work_end=20)
    a.record_send()
    a.record_send()
    assert a.remaining_today() == 0
    assert b.remaining_today() == 5  # счётчики раздельные
    b.record_send()
    assert b.sent_today() == 1
    assert a.sent_today() == 2


def test_import_csv_assign() -> None:
    d = Path(tempfile.mkdtemp())
    store = Store(str(d / "t.db"))
    csv = "phone,name,manager_id\n[REDACTED],Гость,ivan\n@someone,Имя,\n"
    stats = store.import_contacts_csv(csv, default_manager_id="anna")
    assert stats["ok"] == 2
    assert store.contact_by_phone("[REDACTED]")["manager_id"] == "ivan"
    assert store.contact_by_phone("@someone")["manager_id"] == "anna"


def test_web_login_has_manager_select() -> None:
    from bot.web_login import HTML, create_app

    assert "mgrSelect" in HTML
    assert "accSelect" in HTML
    assert "аккаунт компании" in HTML.lower() or "Telegram бота" in HTML
    assert "личный Telegram" not in HTML  # менеджеры без личных TG
    assert "Менеджер" in HTML
    app = create_app()
    paths = " ".join(r.canonical for r in app.router.resources())
    assert "/api/manager/select" in paths


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print("run", name)
            fn()
    print("ok")
