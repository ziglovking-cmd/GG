# -*- coding: utf-8 -*-
"""Районы из таблицы адресов: Казбек/Белуха ≠ Коммунарка, Хомлин = Прокшино."""

from __future__ import annotations

from bot.apartments_map import in_area, load_areas, load_places
from bot.phrases import ADDON_SERVICES_LIST, MANAGER_CONNECT_LINE
from bot.smart import _craft_early


def setup_function() -> None:
    load_areas.cache_clear()
    load_places.cache_clear()


def test_kommunarka_excludes_kazbek_belukha_homlin() -> None:
    assert in_area("Казбек", "Коммунарка") is False
    assert in_area("Белуха", "Коммунарка") is False
    assert in_area("Хомлин", "Коммунарка") is False
    assert in_area("Шир", "Коммунарка") is True
    assert in_area("Феррари", "Коммунарка") is True


def test_ochakovo_and_prokshino() -> None:
    assert in_area("Казбек", "Очаково") is True
    assert in_area("Белуха", "Очаково") is True
    assert in_area("Эльбрус", "Очаково") is True
    assert in_area("Аннапурна", "Очаково") is True
    assert in_area("Казбек", "Потапово") is True  # алиас района
    assert in_area("Хомлин", "Прокшино") is True
    assert in_area("Вояж", "Прокшино") is True
    assert in_area("Карма", "Прокшино") is True
    street, district, metro = load_places()["казбек"]
    assert "стройкомбинат" in street.lower()
    assert district.lower() == "очаково"
    assert "очаково" in metro.lower()
    _s, d2, _m = load_places()["хомлин"]
    assert d2.lower() == "прокшино"


def test_addon_services_offer_colleague_and_handoff() -> None:
    assert "фотосесс" in ADDON_SERVICES_LIST.lower()
    assert "другие дополнительные услуги по запросу" in ADDON_SERVICES_LIST.lower()
    assert "позову коллегу" in ADDON_SERVICES_LIST.lower()

    out = _craft_early({}, "Какие дополнительные услуги у вас есть?", [])
    assert out is not None
    blob = out[0][0].lower()
    assert "фотосесс" in blob
    assert "позову коллегу" in blob
    assert out[2]["context"].get("services_colleague_open") is True

    sess = {"context": dict(out[2]["context"])}
    history = [
        {"role": "guest", "text": "Какие дополнительные услуги у вас есть?"},
        {"role": "bot", "text": out[0][0]},
    ]
    yes = _craft_early(sess, "Да, позовите", history)
    assert yes is not None
    assert yes[0][0] == MANAGER_CONNECT_LINE
    assert yes[3] is True
    assert yes[2]["step"] == "handed_off"
