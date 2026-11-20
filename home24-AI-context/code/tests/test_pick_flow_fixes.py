# -*- coding: utf-8 -*-
"""Фиксы диалога: выбор «Скандинавия», ранний/поздний, без «Подойдёт?»."""

from __future__ import annotations

from bot.apartments_map import resolve_apartment_title
from bot.faq import match_faq
from bot.smart import (
    _EARLY_LATE_LINE,
    _apartment_pick_reply,
    _comfort_after_pick,
)


def test_resolve_scandinavia_without_catalog() -> None:
    assert resolve_apartment_title("Скандинавия").lower().startswith("скандинав")
    assert resolve_apartment_title("мы выбрали квартиру Скандинавия").lower().startswith("скандинав")


def test_bare_name_starts_comfort_or_asks_dates() -> None:
    sess = {"step": "await_intent", "context": {}}
    history = [{"role": "bot", "text": "Здравствуйте! Чем могу вам помочь?"}]
    out = _apartment_pick_reply(sess, "Скандинавия", history)
    assert out is not None
    msgs, _btns, upd, esc = out
    assert esc is False
    assert upd.get("favorite", "").lower().startswith("скандинав")
    # нет дат → спросит даты; с датами → комфорт
    assert upd.get("step") in ("await_dates", "await_comfort", "await_guests", "await_district")
    blob = "\n".join(msgs).lower()
    assert "подойд" not in blob
    assert "вариант ближе" not in blob


def test_chose_phrase_accepts_without_reasking() -> None:
    sess = {
        "step": "await_returning",
        "dates": "с 12 по 17 декабря",
        "guests": "2",
        "district": "Коммунарка",
        "context": {"offers": ["Скандинавия", "Феррари"]},
    }
    history = [
        {
            "role": "bot",
            "text": "Хороший выбор, Скандинавия). Какой вариант ближе, напишите номер или название 🙂",
        }
    ]
    out = _apartment_pick_reply(sess, "Я написала мы выбрали квартиру Скандинавия", history)
    assert out is not None
    msgs, _, upd, esc = out
    assert esc is False
    assert upd.get("step") == "await_comfort"
    assert "подойд" not in "\n".join(msgs).lower()
    assert "комфорт" in "\n".join(msgs).lower() or "лёд" in "\n".join(msgs).lower() or "лед" in "\n".join(msgs).lower()


def test_yes_after_podoydet_goes_comfort() -> None:
    sess = {
        "step": "await_returning",
        "favorite": "Скандинавия",
        "dates": "с 12 по 17 декабря",
        "guests": "2",
        "district": "Коммунарка",
        "context": {"offers": ["Скандинавия"]},
    }
    history = [{"role": "bot", "text": "Скандинавия, тихо, рядом метро. Подойдёт?"}]
    out = _apartment_pick_reply(sess, "Да", history)
    assert out is not None
    msgs, _, upd, esc = out
    assert esc is False
    assert upd.get("step") == "await_comfort"
    assert "менеджер сейчас уточнит" not in "\n".join(msgs).lower()


def test_early_and_late_one_answer() -> None:
    text = "Скажите пожалуйста возможен ли ранний заезд и поздний выезд?"
    faq = match_faq(text)
    assert faq is not None
    blob = " ".join(faq[0]).lower()
    assert "ранний заезд и поздний выезд" in blob
    assert blob.count("иногда можно") == 1


def test_comfort_after_pick_with_full_slots() -> None:
    msgs, _, upd, esc = _comfort_after_pick(
        {
            "dates": "с 1 по 3 января",
            "guests": "2",
            "district": "Коммунарка",
            "context": {},
        },
        "Скандинавия",
    )
    assert esc is False
    assert upd.get("step") == "await_comfort"
    assert "Скандинавия" in "\n".join(msgs)
