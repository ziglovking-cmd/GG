# -*- coding: utf-8 -*-
"""Воронка: район → даты → гости → календарь TravelLine."""

from __future__ import annotations

from datetime import date

from bot.config import get_settings
from bot.engine import Engine, BUTTONS
from bot.phrases import district_choice_message
from bot.travelline import Stay, set_search_hook


def _eng() -> Engine:
    return Engine(get_settings())


def test_district_choice_message_is_short() -> None:
    text = district_choice_message()
    low = text.lower().replace("ё", "е")
    assert "центре" in low or "центр" in low
    assert "спокойн" in low
    assert "коммунарка" in low and "прокшино" in low and "очаково" in low
    assert "одинцово" in low and "котельники" in low
    assert "район или метро" in low
    assert "•" not in text
    assert "чехов" not in low and "дягилев" not in low
    assert "уточню более точно" not in low


def test_looking_starts_with_district_list_no_buttons() -> None:
    eng = _eng()
    msgs, btns, upd, esc = eng.handle({"step": "await_intent"}, "Да, ищу квартиру")
    assert esc is False
    blob = "\n".join(msgs).lower().replace("ё", "е")
    assert "коммунарка" in blob and "прокшино" in blob
    assert "чехов" not in blob
    assert "уточню более точно" not in blob
    assert upd.get("step") == "await_district"
    assert btns is None


def test_later_think_does_not_send_districts() -> None:
    from bot.phrases import LATER_LINE, is_later_think

    assert is_later_think("прдумаем")
    assert is_later_think("подумаем")
    eng = _eng()
    msgs, btns, upd, esc = eng.handle(
        {"step": "await_dates", "context": {"offer_told": "bonus", "perk": "orient"}},
        "прдумаем",
    )
    assert esc is False
    assert btns is None
    assert msgs == [LATER_LINE]
    assert "район" not in msgs[0].lower()
    assert upd.get("step") == "done"


def test_district_then_dates_then_guests_then_calendar() -> None:
    eng = _eng()
    sess: dict = {"step": "await_intent"}
    msgs, btns, upd, _ = eng.handle(sess, "looking")
    sess = {**sess, **upd}
    assert sess["step"] == "await_district"

    msgs, btns, upd, _ = eng.handle(sess, "Зелёный / тихий")
    sess = {**sess, **upd}
    assert sess["district"] == "Тихий зелёный район"
    assert sess["step"] == "await_dates"
    assert btns == BUTTONS["dates"]
    assert any("дат" in m.lower() or "заезд" in m.lower() or "ноч" in m.lower() for m in msgs)

    msgs, btns, upd, _ = eng.handle(sess, "с 20 по 22 декабря")
    sess = {**sess, **upd}
    assert "декабр" in str(sess.get("dates") or "").lower() or "20" in str(sess.get("dates") or "")
    assert sess["step"] == "await_guests"
    assert btns == BUTTONS["guests"]
    assert any("сколько" in m.lower() or "гост" in m.lower() or "человек" in m.lower() for m in msgs)

    mk = lambda i, n, p: Stay(
        room_id=str(i),
        title=n,
        address="x",
        price_night=p,
        price_total=p * 2,
        available=1,
    )
    set_search_hook(lambda a, d, n: [mk(1, "Хомлин", 4500), mk(2, "Малевич", 3400)])
    try:
        msgs, btns, upd, esc = eng.handle(sess, "двое")
    finally:
        set_search_hook(None)
    sess = {**sess, **upd}
    assert esc is False
    blob = "\n".join(msgs)
    assert "Хомлин" in blob
    assert "Малевич" not in blob  # другой район — Подмосковье
    assert sess.get("step") == "await_returning"
    assert "Хомлин" in (sess.get("context") or {}).get("offers", [])
