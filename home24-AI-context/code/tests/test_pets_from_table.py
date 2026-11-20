# -*- coding: utf-8 -*-
"""Питомцы из таблицы /pets: пометки и доплата в карточках."""

from __future__ import annotations

from bot.apartments_map import allows_pets, load_pets, pets_fee_rub, pets_note
from bot.travelline import Stay, free_offer_cards, set_search_hook


def setup_function() -> None:
    load_pets.cache_clear()


def test_pets_flags_and_fees() -> None:
    assert allows_pets("Эльбрус") is True
    assert allows_pets("Сойка") is True
    assert allows_pets("Дзен") is True
    assert allows_pets("Эверест") is True
    assert allows_pets("Олимп") is True
    assert allows_pets("Чехов") is False
    assert allows_pets("Малевич") is False
    assert pets_fee_rub("Эльбрус") == 500
    assert pets_fee_rub("Олимп") == 1500
    assert pets_fee_rub("Эверест") == 1500
    assert pets_fee_rub("Чехов") is None
    note = pets_note("Сойка")
    assert "можно с животными" in note
    assert "500" in note
    assert "1500" in pets_note("Олимп") or "1\u00a0500" in pets_note("Олимп")


def test_calendar_cards_mark_pets() -> None:
    from datetime import date

    mk = lambda i, n, p: Stay(
        room_id=str(i), title=n, address="x", price_night=p, price_total=p * 3, available=1
    )
    set_search_hook(
        lambda a, d, n: [
            mk(1, "Эльбрус", 4800),
            mk(2, "Чехов", 4100),
            mk(3, "Олимп", 9000),
        ]
    )
    try:
        text, names = free_offer_cards(
            "с 5 по 8 декабря",
            2,
            district="не принципиально",
            today=date(2026, 11, 11),
            limit=5,
        )
    finally:
        set_search_hook(None)
    assert "Эльбрус" in text
    assert "можно с животными" in text
    assert "500" in text
    # Чехов без пометки про животных
    assert re_search_chekhov_no_pets(text)
    assert "Олимп" in text
    assert "1\u00a0500" in text or "1500" in text


def re_search_chekhov_no_pets(text: str) -> bool:
    import re

    m = re.search(r"«Чехов»([^\n]*)", text)
    if not m:
        return True
    return "можно с животными" not in m.group(1)


def test_site_links_not_replaced_by_guides() -> None:
    from bot.apartments_map import link_for, load_guides, load_links

    load_links.cache_clear()
    load_guides.cache_clear()
    site = link_for("Дягилев")
    assert "home24.msk.ru" in site
    assert "sslip.io" not in site
    assert "sslip.io" in load_guides()["дягилев"]


def test_center_card_marks_dyagilev_pets() -> None:
    from datetime import date

    mk = lambda i, n, p: Stay(
        room_id=str(i), title=n, address="x", price_night=p, price_total=p * 4, available=1
    )
    set_search_hook(lambda a, d, n: [mk(1, "Шаляпин", 4000), mk(2, "Дягилев", 4200)])
    try:
        text, _ = free_offer_cards(
            "с 20 по 24 декабря",
            3,
            district="центр",
            today=date(2026, 11, 11),
            limit=5,
        )
    finally:
        set_search_hook(None)
    assert "Дягилев" in text
    assert "можно с животными" in text
    assert "500" in text
    assert re_search_chekhov_no_pets(text.replace("Шаляпин", "Чехов").replace("«Шаляпин»", "«Чехов»"))
    # у Шаляпина в первой строке карточки нет пометки про животных
    import re

    m = re.search(r"«Шаляпин»([^\n]*)", text)
    assert m and "можно с животными" not in m.group(1)


def test_pets_early_answer_wording() -> None:
    from bot.smart import PETS_EARLY_LINE, _pets_answer

    out = _pets_answer("можно ли с собакой?", {})
    assert out == PETS_EARLY_LINE
    assert "не во всех" in out.lower()
    assert "доплата" in out.lower() or "карточк" in out.lower()
    assert "уточню про стоимость" not in out.lower()
    with_offers = _pets_answer(
        "можно ли с собакой?",
        {},
        offers=["Эльбрус", "Чехов"],
    )
    assert "Эльбрус" in with_offers
    assert "можно с животными" in with_offers
    assert "Чехов" in with_offers
    assert "Без животных" in with_offers
