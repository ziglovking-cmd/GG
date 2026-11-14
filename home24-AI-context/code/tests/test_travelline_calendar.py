# -*- coding: utf-8 -*-
"""Календарь TravelLine: даты, улица не путается с проспектом, ответ без сети."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.travelline import Stay, describe_availability, hint_place, matches_place, stay_span


TODAY = date(2026, 10, 15)


def test_span_rolls_past_month_and_keeps_future() -> None:
    assert stay_span("с 12 по 14 марта", TODAY) == (date(2027, 3, 12), date(2027, 3, 14))
    assert stay_span("с 1 по 4 ноября", TODAY) == (date(2026, 11, 1), date(2026, 11, 4))
    assert stay_span("на 26", TODAY) is None
    assert stay_span("ближайшие выходные", TODAY) == (date(2026, 10, 17), date(2026, 10, 19))


def test_drive_is_not_prospect() -> None:
    briz = Stay(room_id="1", title="Бриз", address="Москва, ул. Лобановский Лес, д. 11")
    karma = Stay(room_id="2", title="Карма", address="Москва, Прокшинский проспект, д. 9")
    place = "Прокшинский проезд, Прокшино"
    assert matches_place(briz, place) is False
    assert matches_place(karma, place) is False
    assert matches_place(karma, "Прокшино") is True
    # 11.11: Лобановский Лес — это тоже Прокшино (раздел «Районы» в script.md, листы таблицы)
    assert matches_place(briz, "Прокшино") is True
    text = describe_availability(
        date(2026, 11, 1),
        date(2026, 11, 4),
        [briz, karma],
        place,
    )
    low = text.lower()
    assert "проезд" in low
    assert "нет" in low
    assert "бриз" not in low
    assert "карма" not in low


def test_named_free_room_gets_calendar_price() -> None:
    stay = Stay(
        room_id="9",
        title="Жасмин",
        address="Москва, ул. Малый Краснопрудный тупик, д. 1",
        price_night=3200,
        price_total=6400,
        available=1,
    )
    text = describe_availability(date(2026, 11, 1), date(2026, 11, 3), [stay], "Жасмин")
    assert "Жасмин" in text
    assert "3\u00a0200" in text
    assert "календар" in text.lower()
    assert "не подтвержда" not in text.lower()


def test_hint_keeps_named_district() -> None:
    stays = [
        Stay(room_id="1", title="Малевич", address="Москва, ул. Пример, д. 1", price_night=3255),
        Stay(room_id="2", title="Карма", address="Москва, Прокшинский проспект, д. 9", price_night=4371),
    ]
    assert hint_place("Ищу квартиру на 12-14 марта, 2 гостя, Прокшино", stays) == "прокшино"
    text = describe_availability(
        date(2027, 3, 12),
        date(2027, 3, 14),
        stays,
        "прокшино",
    )
    assert "Карма" in text
    assert "Малевич" not in text


def test_uneven_nights_do_not_contradict_total() -> None:
    stay = Stay(
        room_id="2",
        title="Карма",
        address="Москва, Прокшинский проспект, д. 9",
        price_night=4371,
        price_total=13671,
        night_prices=(4371, 4550, 4750),
    )
    text = describe_availability(date(2026, 11, 1), date(2026, 11, 4), [stay], "Прокшино")
    assert "13\u00a0671" in text
    assert "4\u00a0371" not in text  # по ночам не сходится с итогом — только итог
    assert "4371–4750" not in text  # вилку Telegram делает ссылкой (скрин 10.11)
    flat = Stay(
        room_id="2",
        title="Карма",
        address="Москва, Прокшинский проспект, д. 9",
        price_night=4371,
        price_total=13671,
    )
    text2 = describe_availability(date(2026, 11, 1), date(2026, 11, 4), [flat], "Прокшино")
    assert "13\u00a0671" in text2
    assert "4\u00a0371" not in text2


def test_all() -> None:
    test_span_rolls_past_month_and_keeps_future()
    test_drive_is_not_prospect()
    test_named_free_room_gets_calendar_price()
    test_hint_keeps_named_district()
    test_uneven_nights_do_not_contradict_total()
    print("calendar ok")


if __name__ == "__main__":
    test_all()


def test_prokshino_area_includes_lobanovsky_les() -> None:
    """11.11: на 12–15 декабря в Прокшино свободно несколько, а бот прислал одну «Карму» — адрес совпал только у неё."""
    from bot.travelline import describe_availability_offer, display_title

    mk = lambda i, n, p, a="": Stay(room_id=str(i), title=n, address=a, price_night=p, price_total=p * 3, available=1)
    stays = [
        mk(1, "Карма", 4433, "Москва, Прокшинский проспект, 9"),
        mk(2, "Вояж", 5200, "Москва, улица Лобановский Лес, 13"),
        mk(3, "Бриз", 4100),  # без адреса с сайта — по разделу «Районы»
        mk(4, display_title("Апартаменты «Нуар» от Home24"), 4300),
        mk(5, "Феррари", 3900, "Москва, Фитарёвская, 6"),
        mk(6, "Малевич", 3424, "Одинцово, Каштановая, 6"),
    ]
    text, names = describe_availability_offer(date(2026, 12, 12), date(2026, 12, 15), stays, "Прокшино")
    assert set(names) == {"Карма", "Вояж", "Бриз", "Нуар"}
    assert "Феррари" not in text and "Малевич" not in text
    assert text.index("«Бриз»") < text.index("«Карма»")  # дешевле — выше


def test_display_title_cleans_travelline_names() -> None:
    from bot.travelline import display_title

    assert display_title("Апартаменты «Артмен» от Home24") == "Артмен"
    assert display_title("Квартира Карма от Home24") == "Карма"
    assert display_title("Вояж") == "Вояж"
