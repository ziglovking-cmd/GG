# -*- coding: utf-8 -*-
"""Строгий TravelLine: район → только свои; «без разницы» → все свободные."""

from __future__ import annotations

from datetime import date

from bot.reply_guard import is_open_district
from bot.travelline import Stay, free_offer_cards, set_search_hook


def _mk(i: int, name: str, price: int, address: str = "") -> Stay:
    return Stay(
        room_id=str(i),
        title=name,
        address=address,
        price_night=price,
        price_total=price * 3,
        available=1,
    )


def test_open_district_labels() -> None:
    assert is_open_district("не принципиально")
    assert is_open_district("без разницы")
    assert is_open_district("любой район")
    assert is_open_district("на ваш выбор")
    assert not is_open_district("Прокшино")
    assert not is_open_district("центр")


def test_named_district_never_leaks_others() -> None:
    stays = [
        _mk(1, "Карма", 4400),
        _mk(2, "Вояж", 4500),
        _mk(99, "Малевич", 3400, "Одинцово, Каштановая, 6"),
        _mk(98, "Юниверсал", 3600, "Котельники"),
    ]
    set_search_hook(lambda a, d, n: list(stays))
    try:
        text, names = free_offer_cards(
            "с 12 по 15 декабря",
            2,
            district="Прокшино",
            today=date(2026, 11, 12),
        )
    finally:
        set_search_hook(None)
    assert "Малевич" not in names
    assert "Юниверсал" not in names
    assert "Малевич" not in text
    assert set(names) <= {"Карма", "Вояж"}


def test_named_district_empty_returns_nothing() -> None:
    stays = [
        _mk(99, "Малевич", 3400, "Одинцово, Каштановая, 6"),
        _mk(98, "Юниверсал", 3600, "Котельники"),
    ]
    set_search_hook(lambda a, d, n: list(stays))
    try:
        text, names = free_offer_cards(
            "с 12 по 15 декабря",
            2,
            district="Прокшино",
            today=date(2026, 11, 12),
        )
    finally:
        set_search_hook(None)
    assert text == ""
    assert names == []


def test_open_preference_returns_all_free() -> None:
    titles = ["Карма", "Вояж", "Малевич", "Чехов", "Юниверсал"]
    stays = [_mk(i + 1, n, 4000 + i * 50) for i, n in enumerate(titles)]
    set_search_hook(lambda a, d, n: list(stays))
    try:
        for label in ("не принципиально", "без разницы", "любой район", ""):
            text, names = free_offer_cards(
                "с 12 по 15 декабря",
                2,
                district=label,
                today=date(2026, 11, 12),
            )
            assert set(names) == set(titles), label
            assert "Свободны по календарю" in text or "календарю" in text.lower()
    finally:
        set_search_hook(None)


def test_engine_named_district_no_catalog_leak() -> None:
    from bot.config import get_settings
    from bot.engine import Engine

    stays = [_mk(99, "Малевич", 3400, "Одинцово")]
    set_search_hook(lambda a, d, n: list(stays))
    try:
        eng = Engine(get_settings())
        sess = {
            "dates": "с 12 по 15 декабря",
            "guests": "",
            "district": "",
            "returning": "нет",
            "context": {},
        }
        msgs, _btns, upd, esc = eng._offers_after_slots(
            sess, district="Прокшино", guests="2"
        )
    finally:
        set_search_hook(None)
    blob = "\n".join(msgs).lower()
    assert "малевич" not in blob
    assert "близкие варианты" not in blob
    assert esc or "менеджер" in blob or "календар" in blob
