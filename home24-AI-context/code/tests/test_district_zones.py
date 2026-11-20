# -*- coding: utf-8 -*-
"""Зоны районов из таблицы Home24: центр / близко / спальный / зелёный / Подмосковье."""

from __future__ import annotations

from bot.apartments_map import areas_for_place, in_area, load_areas
from bot.engine import BUTTONS, CALLBACK_MAP, match_button, parse_district
from bot.travelline import Stay, matches_place


def setup_function() -> None:
    load_areas.cache_clear()


def test_zone_buttons_offered() -> None:
    labels = [label for label, _code in BUTTONS["district"]]
    assert "Центр" in labels
    assert "Близко к центру" in labels
    assert "Зелёный / тихий" in labels
    assert "Спальный район" in labels
    assert "Подмосковье" in labels
    assert "Не принципиально" in labels
    for _label, code in BUTTONS["district"]:
        assert CALLBACK_MAP[code] == "district"


def test_parse_district_zones() -> None:
    assert parse_district("центр") == "центр"
    assert parse_district("ближе к центру") == "Близко к центру"
    assert parse_district("зелёный район") == "Тихий зелёный район"
    assert parse_district("спальный") == "Спальный район"
    assert parse_district("Подмосковье") == "Подмосковье"
    assert parse_district("не центр") == "спокойный район"
    assert parse_district("потише") == "спокойный район"
    assert match_button("Близко к центру") == "d_near"
    assert match_button("Подмосковье") == "d_suburb"


def test_areas_longest_match_near_vs_center() -> None:
    assert areas_for_place("центр") == ["Центр"]
    assert areas_for_place("близко к центру") == ["Близко к центру"]
    assert areas_for_place("Спальный район") == ["Спальный район"]
    assert areas_for_place("Подмосковье") == ["Подмосковье"]


def test_in_area_by_excel_zones() -> None:
    assert in_area("Чехов", "центр") is True
    assert in_area("Индиго", "центр") is False
    assert in_area("Индиго", "Близко к центру") is True
    assert in_area("Казбек", "Спальный район") is True
    assert in_area("Казбек", "Очаково") is True
    assert in_area("Казбек", "Коммунарка") is False
    assert in_area("Хомлин", "Тихий зелёный район") is True
    assert in_area("Хомлин", "Прокшино") is True
    assert in_area("Малевич", "Подмосковье") is True
    assert in_area("Малевич", "Одинцово") is True
    assert in_area("Шир", "Коммунарка") is True
    assert in_area("Шир", "Саларьево") is True


def test_matches_place_uses_zones() -> None:
    stay = Stay(room_id="1", title="Индиго", address="1-я Магистральная")
    assert matches_place(stay, "Близко к центру") is True
    assert matches_place(stay, "центр") is False
    calm = Stay(room_id="2", title="Казбек", address="Стройкомбината")
    assert matches_place(calm, "Спальный район") is True
    assert matches_place(calm, "Подмосковье") is False
