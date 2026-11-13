# -*- coding: utf-8 -*-
"""По району бот шлёт все свободные варианты из календаря TravelLine, без обрезки до 3/5."""

from __future__ import annotations

from datetime import date

from bot.travelline import Stay, describe_availability_offer, free_offer_cards, set_search_hook


def _mk(i: int, name: str, price: int, address: str = "") -> Stay:
    return Stay(
        room_id=str(i),
        title=name,
        address=address,
        price_night=price,
        price_total=price * 3,
        available=1,
    )


def test_free_offer_cards_returns_all_in_district() -> None:
    # раньше limit=5 обрезал список — теперь по району приходят все
    titles = [
        "Карма",
        "Вояж",
        "Бриз",
        "Нуар",
        "Хомлин",
        "Сноу Пикс",
        "Артмен",
        "Жизель",
    ]
    stays = [_mk(i + 1, n, 4000 + i * 100) for i, n in enumerate(titles)]
    stays.append(_mk(99, "Малевич", 3400, "Одинцово, Каштановая, 6"))

    set_search_hook(lambda a, d, n: list(stays))
    try:
        text, names = free_offer_cards(
            "с 12 по 15 декабря",
            2,
            district="Прокшино",
            today=date(2026, 11, 11),
        )
    finally:
        set_search_hook(None)

    assert len(names) == 8
    assert set(names) == set(titles)
    assert "Малевич" not in text
    for title in titles:
        assert f"«{title}»" in text


def test_describe_availability_offer_all_by_place() -> None:
    stays = [
        _mk(1, "Карма", 4433, "Москва, Прокшинский проспект, 9"),
        _mk(2, "Вояж", 5200, "Москва, улица Лобановский Лес, 13"),
        _mk(3, "Бриз", 4100),
        _mk(4, "Нуар", 4300),
        _mk(5, "Хомлин", 4500),
        _mk(6, "Сноу Пикс", 4600),
        _mk(7, "Артмен", 4700),
        _mk(8, "Феррари", 3900, "Москва, Фитарёвская, 6"),
    ]
    text, names = describe_availability_offer(
        date(2026, 12, 12), date(2026, 12, 15), stays, "Прокшино"
    )
    assert set(names) == {"Карма", "Вояж", "Бриз", "Нуар", "Хомлин", "Сноу Пикс", "Артмен"}
    assert "Феррари" not in text
    assert "напишите «ещё»" not in text.lower()
