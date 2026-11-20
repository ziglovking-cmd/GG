"""Карточки гостю и сегодняшние кривые ответы: без центра у окраин, без кв., без инструкции."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.catalog import classify_zone, client_address, format_card, reason_for_offer
from bot.engine import parse_guests
from bot.smart import _craft_early
from bot.tg_accounts import TgAccountRegistry


def _flat(**kwargs):
    base = {
        "name": "Сандал",
        "area": "Москва",
        "metro": "Хорошёво · 10 минут",
        "address": "Хорошёво, ул. Пример, кв. 264",
        "how": (
            "Адрес для внутреннего листа.\n"
            "Кнопка «Маршрут» в этой инструкции открывает карту для менеджера, гостю её не слать."
        ),
        "capacity": 4,
        "price_night": None,
    }
    base.update(kwargs)
    return base


def test_khoroshevo_and_lefortovo_are_not_center() -> None:
    for metro, address in (
        ("Хорошёво · 10 минут", "Хорошёво, кв. 264"),
        ("м. Лефортово", "Лефортово, квартира 12"),
        ("Хорошево", "Хорошево"),
    ):
        obj = _flat(metro=metro, address=address)
        zone = classify_zone(obj)
        assert zone["zone"] != "center", metro
        assert zone["is_central"] is False
        why = reason_for_offer(obj, district="центр")
        assert "в центре" not in why.lower(), why


def test_card_hides_flat_number_and_internal_copy() -> None:
    card = format_card(_flat())
    assert "264" not in card
    assert "кв" not in card.lower()
    assert "инструкц" not in card.lower()
    assert "маршрут" not in card.lower()
    assert "Сандал" in card
    assert client_address("кв. 264, дом 1") == "дом 1"
    lefort = format_card(
        _flat(
            name="Лофт",
            metro="м. Лефортово",
            address="Лефортово, квартира №7",
            how="Нажмите кнопку «Маршрут» в этой инструкции — это служебный текст длиннее сорока знаков.",
        )
    )
    assert "№7" not in lefort
    assert "квартира" not in lefort.lower()
    assert "маршрут" not in lefort.lower()


def test_hello_does_not_repeat_bare_day() -> None:
    out = _craft_early(
        {"dates": "на 10", "step": "await_guests", "guests": "", "district": ""},
        "Привет",
        [],
    )
    assert out
    blob = " ".join(out[0])
    assert "на 10" not in blob.lower()
    assert "дат" in blob.lower()


def test_parents_count_as_two() -> None:
    assert parse_guests("Ну я мама и папа") == "2"
    out = _craft_early(
        {"dates": "с 1 по 7 января", "step": "await_guests"},
        "Ну я мама и папа",
        [],
    )
    assert out
    assert out[2].get("guests") == "2"
    blob = " ".join(out[0]).lower()
    assert "сколько вас" not in blob
    assert "район" in blob or "центр" in blob


def test_vague_cool_area_asks_district() -> None:
    for text in ("Крутой", "Ну район крутой"):
        out = _craft_early(
            {"dates": "с 1 по 7 января", "guests": "2", "step": "await_district"},
            text,
            [],
        )
        assert out, text
        blob = " ".join(out[0]).lower()
        assert "по квартире" not in blob
        assert "центр" in blob or "поспокойнее" in blob
        assert out[2]["context"]["reply_path"] == "smart:rule/area"
        assert out[2].get("guests") == "2"
        assert "сколько вас" not in blob


def test_ku_is_a_ping() -> None:
    out = _craft_early({}, "Ку", [])
    assert out
    blob = " ".join(out[0]).lower()
    assert blob != "поняла."
    assert "дат" in blob


def test_main_account_backup_then_cap() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "tg_accounts.json"
    path.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "main",
                        "is_main": True,
                        "daily_send_limit": 210,
                        "weekly_send_limit": 1200,
                        "session": "keep",
                    },
                    {
                        "id": "srv-1",
                        "daily_send_limit": 40,
                        "weekly_send_limit": 280,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    reg = TgAccountRegistry(path)
    assert reg.accounts["main"].daily_send_limit == 30
    assert reg.accounts["main"].weekly_send_limit == 210
    assert reg.accounts["srv-1"].daily_send_limit == 40
    assert reg.accounts["srv-1"].weekly_send_limit == 280
    bak = path.with_name(path.name + ".bak-limits")
    assert bak.exists()
    old = json.loads(bak.read_text(encoding="utf-8"))
    assert old["accounts"][0]["daily_send_limit"] == 210
    assert old["accounts"][0]["weekly_send_limit"] == 1200


if __name__ == "__main__":
    test_khoroshevo_and_lefortovo_are_not_center()
    test_card_hides_flat_number_and_internal_copy()
    test_hello_does_not_repeat_bare_day()
    test_parents_count_as_two()
    test_vague_cool_area_asks_district()
    test_ku_is_a_ping()
    test_main_account_backup_then_cap()
    print("ok")
