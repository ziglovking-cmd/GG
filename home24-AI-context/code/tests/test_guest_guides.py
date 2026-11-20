# -*- coding: utf-8 -*-
"""Путеводители по проживанию: адрес → ссылка из таблицы."""

from __future__ import annotations

from bot.apartments_map import (
    GUIDE_ASK_LINE,
    format_guide_message,
    guide_for_name,
    guides_for_address,
    load_guides,
)
from bot.smart import _craft_early, _guide_intent


def test_guides_loaded_from_script() -> None:
    guides = load_guides()
    assert len(guides) >= 50
    assert "чехов" in guides
    assert guides["чехов"].startswith("https://")
    assert "/g/chekhov" in guides["чехов"]


def test_guide_for_name_and_alias() -> None:
    title, url = guide_for_name("Чехов")
    assert url.endswith("/g/chekhov")
    title2, url2 = guide_for_name("Dark Blue")
    assert url2.endswith("/g/dark-blyu")
    assert title2


def test_guides_for_address_unique() -> None:
    hits = guides_for_address("Руставели 14")
    assert len(hits) == 1
    assert hits[0][0].lower().startswith("рим")
    assert "/g/rim" in hits[0][1]


def test_guides_for_address_multi_asks_name() -> None:
    hits = guides_for_address("Балакиревский пер 23")
    assert len(hits) >= 3
    urls = {u for _n, u in hits}
    assert any("/g/chekhov" in u for u in urls)


def test_guide_intent_patterns() -> None:
    assert _guide_intent("как включить стиральную машину?")
    assert _guide_intent("не работает микроволновка")
    assert _guide_intent("какой пароль от вайфая?")
    assert _guide_intent("где парковка?")
    assert _guide_intent("как добраться до квартиры")
    assert not _guide_intent("нас двое на выходные")


def test_craft_asks_address_then_sends_link() -> None:
    got = _craft_early({}, "как пользоваться бойлером?", [])
    assert got is not None
    assert got[0][0] == GUIDE_ASK_LINE
    assert (got[2].get("context") or {}).get("guide_await") is True

    got2 = _craft_early(got[2], "Руставели 14", [])
    assert got2 is not None
    blob = got2[0][0]
    assert "путеводитель" in blob.lower()
    assert "https://89-111-184-212.sslip.io/g/rim" in blob
    assert "Рим" in blob or "рим" in blob.lower()


def test_craft_multi_address_then_name() -> None:
    sess = {"context": {"guide_await": True}}
    got = _craft_early(sess, "Балакиревский 23", [])
    assert got is not None
    assert "несколько квартир" in got[0][0].lower()
    assert (got[2].get("context") or {}).get("guide_pick") is True

    got2 = _craft_early(got[2], "Чехов", [])
    assert got2 is not None
    assert "/g/chekhov" in got2[0][0]


def test_format_guide_message_copy() -> None:
    text = format_guide_message("Олимп", "https://example/g/olimp")
    assert "Олимп" in text
    assert "техник" in text.lower()
    assert "парков" in text.lower()
    assert "https://example/g/olimp" in text
