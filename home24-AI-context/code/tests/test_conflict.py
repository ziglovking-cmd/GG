"""Регрессии: ИИ не конфликтует со скриптом, нет повторов."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.catalog import parse_offer_pick
from bot.config import get_settings
from bot.engine import Engine, keyword_intent, match_button, parse_dates, parse_guests


def test_parsers() -> None:
    assert parse_offer_pick("Давайте 1") == 1
    assert parse_offer_pick("Давайте 1 впервые") == 1
    assert parse_offer_pick("1 впервые") == 1
    # голое 1–3 — не дата (гости/вариант)
    assert parse_dates("2") is None
    assert parse_dates("3") is None
    assert parse_dates("30") == "на 30"
    assert parse_dates("2", allow_day_1_3=True) == "на 2"
    assert parse_guests("2") == "2"
    assert keyword_intent("Ну квартиру хочу наверное в аренду взять") == "looking"
    assert keyword_intent("Просто смотрим") == "browsing"
    assert match_button("Давайте 1 впервые") == "ret_no"


async def _run_conflict_flow() -> None:
    from bot.ai import reply

    s = get_settings()
    e = Engine(s)
    sess = {
        "step": "await_returning",
        "dates": "на 30",
        "guests": "2",
        "district": "центр",
        "handed_off": 0,
        "context": {"offers": ["Чаплин", "А", "Б"]},
        "returning": "",
        "favorite": "",
    }
    msgs, _, upd, esc = await reply(s, e, sess, "Давайте 1 впервые", [])
    assert upd.get("favorite") == "Чаплин", upd
    assert upd.get("returning") == "нет"
    assert esc is True
    blob = " ".join(msgs).lower()
    # handoff, не повторный опрос
    assert "были у нас раньше" not in blob

    # гости «2» не портят даты
    sess2 = {
        "step": "await_guests",
        "dates": "на 30",
        "guests": "",
        "district": "",
        "handed_off": 0,
        "context": {},
    }
    _, _, upd2, _ = await reply(s, e, sess2, "2", [])
    assert upd2.get("dates") != "на 2"
    assert upd2.get("guests") in ("2", "1-2") or upd2.get("step") == "await_district"
    # даты сессии сохранились через _ctx_upd
    assert (upd2.get("dates") or "на 30") == "на 30"

    # «Тихий» на returning — без LLM «напишите даты»
    sess3 = {
        "step": "await_returning",
        "dates": "1–10",
        "guests": "3",
        "district": "центр",
        "handed_off": 0,
        "context": {"offers": ["X", "Y", "Z"]},
    }
    msgs3, _, _, esc3 = await reply(s, e, sess3, "Тихий", [])
    assert esc3 is False
    blob3 = " ".join(msgs3).lower()
    assert "напишите даты" not in blob3
    assert "сколько человек" not in blob3
    print("OK conflict regressions")


if __name__ == "__main__":
    test_parsers()
    asyncio.run(_run_conflict_flow())
    print("ALL OK")
