# -*- coding: utf-8 -*-
"""v9.5 — один следующий шаг: без петли, с местом гостя, наивные вопросы."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.ai import _dedupe_msgs, reply
from bot.config import get_settings
from bot.engine import Engine
from bot import smart as smart_mod
from bot.smart import _guest_place_phrase


def _sess(**kw):
    base = {
        "name": "Мария",
        "step": "await_guests",
        "dates": "с 1 по 4 ноября",
        "guests": "",
        "district": "Прокшино",
        "returning": "",
        "favorite": "",
        "handed_off": 0,
        "context": {"greeted": True, "outreach": True},
    }
    base.update(kw)
    return base


async def _turn(sess, text, history):
    s = get_settings()
    e = Engine(s)
    msgs, _b, upd, esc = await reply(s, e, sess, text, history)
    return msgs, upd, esc


def test_dedupe_does_not_replay_same_question() -> None:
    prev = "Подскажите, пожалуйста, сколько будет гостей?"
    out = _dedupe_msgs([prev], history=[{"role": "bot", "text": prev}])
    assert out
    assert "сколько будет гост" not in out[0].lower()
    assert "подбер" in out[0].lower() or "напишите" in out[0].lower()


def test_place_phrase_keeps_street_and_district() -> None:
    phrase = _guest_place_phrase(
        "Квартиры в Прокшино по адресу Прокшинский проезд. Там не свободно?",
        _sess(),
    )
    low = phrase.lower()
    assert "прокшин" in low
    assert "проезд" in low
    assert "прокшино" in low


async def _sc_laugh_does_not_repeat() -> None:
    hist = [
        {"role": "bot", "text": "На 1–4 ноября — вас будет двое или больше?"},
    ]
    # ключ гостей у этой фразы другой; берём явный повторный вопрос
    hist = [{"role": "bot", "text": "Подскажите, пожалуйста, сколько будет гостей?"}]
    msgs, upd, esc = await _turn(_sess(), "ахахаха", hist)
    blob = "\n".join(msgs).lower()
    assert not esc
    assert "сколько будет гост" not in blob
    assert upd.get("context", {}).get("reply_path") == "smart:rule/listen"
    assert "?" in blob or "напишите" in blob


def test_laugh_moves_forward() -> None:
    asyncio.run(_sc_laugh_does_not_repeat())


async def _sc_availability_names_place() -> None:
    from datetime import date

    from bot.travelline import Stay, set_search_hook

    def _hook(_arrival: date, _departure: date, _adults: int):
        return [
            Stay(
                room_id="1",
                title="Бриз",
                address="Москва, ул. Лобановский Лес, д. 11",
                price_night=5100,
                price_total=15300,
                available=1,
            ),
            Stay(
                room_id="2",
                title="Карма",
                address="Москва, Прокшинский проспект, д. 9",
                price_night=4800,
                price_total=14400,
                available=1,
            ),
        ]

    text = (
        "Я помню у Вас есть квартиры в Прокшино по адресу Прокшинский проезд. "
        "Там не свободно на эти даты?"
    )
    set_search_hook(_hook)
    try:
        msgs, upd, esc = await _turn(
            _sess(),
            text,
            [{"role": "bot", "text": "На сколько человек смотреть?"}],
        )
    finally:
        set_search_hook(None)
    blob = "\n".join(msgs)
    low = blob.lower()
    assert not esc
    assert "проезд" in low
    assert "календар" in low
    assert "нет" in low
    assert "бриз" not in low
    assert "карма" not in low
    assert "коммунарк" not in low
    assert "не подтвержда" not in low
    assert (upd.get("context") or {}).get("reply_path") == "smart:rule/calendar"


def test_availability_names_guest_place() -> None:
    asyncio.run(_sc_availability_names_place())


async def _sc_naive_wifi_and_bot() -> None:
    msgs, upd, _ = await _turn(
        _sess(step="await_dates", dates="", district=""),
        "а пароль от вайфая какой?",
        [{"role": "bot", "text": "Здравствуйте!"}],
    )
    blob = "\n".join(msgs).lower()
    assert "вайф" in blob or "wifi" in blob
    assert "парол" in blob
    assert "в чат" in blob or "не отправ" in blob
    assert blob.count("?") <= 1
    assert upd.get("context", {}).get("reply_path") == "smart:rule/naive"

    msgs2, _, _ = await _turn(_sess(dates="", district="", step="await_dates"), "вы бот?", [])
    low2 = "\n".join(msgs2).lower()
    assert "home24" in low2
    assert low2.count("?") <= 1


def test_naive_questions_get_one_fact() -> None:
    asyncio.run(_sc_naive_wifi_and_bot())


async def _sc_booking_not_stolen_by_faq() -> None:
    async def _hook(system, messages, **_k):
        return (
            json.dumps(
                {
                    "intent": "looking",
                    "slots": {
                        "dates": "ближайшие выходные",
                        "guests": "2",
                        "district": "центр",
                    },
                    "messages": ["Поняла, выходные на двоих в центре — сейчас подберу."],
                    "ask_next": "returning",
                    "attach_offers": False,
                    "escalate": False,
                },
                ensure_ascii=False,
            ),
            "mock/v9.5",
        )

    smart_mod.set_understand_hook(_hook)
    try:
        msgs, upd, esc = await _turn(
            _sess(dates="", guests="", district="", step="await_intent"),
            "нужны на выходные вдвоём поближе к центру",
            [{"role": "bot", "text": "Здравствуйте!"}],
        )
    finally:
        smart_mod.set_understand_hook(None)
    assert not esc
    blob = "\n".join(msgs).lower()
    assert "я здесь" not in blob
    assert upd.get("guests") == "2"
    path = str((upd.get("context") or {}).get("reply_path") or "")
    assert path.startswith("smart:")
    assert "naive" not in path


def test_booking_still_understood() -> None:
    asyncio.run(_sc_booking_not_stolen_by_faq())


def test_dedupe_keeps_pet_fact_after_outreach() -> None:
    hello = "Доброе утро, Мария! Это Home24, посуточно. Давно не бронировали — соскучились."
    fact = (
        "С собакой — только на части объектов и по согласованию. "
        "Когда выберете квартиру, менеджер подтвердит, можно ли именно туда."
    )
    ask = "Подскажите, пожалуйста — вы у нас уже были или впервые?"
    out = _dedupe_msgs(
        [fact, ask],
        history=[{"role": "bot", "text": hello}],
    )
    blob = "\n".join(out).lower()
    assert "собак" in blob
    assert "были" in blob or "впервые" in blob
    assert "номер или название" not in blob


async def _sc_no_cards_no_pick_question() -> None:
    async def _hook(system, messages, **_k):
        return (
            json.dumps(
                {
                    "intent": "looking",
                    "slots": {
                        "dates": "1–7 января",
                        "guests": "3",
                        "district": "центр",
                        "returning": "впервые",
                    },
                    "messages": ["Какой вариант ближе — напишите номер или название 🙂"],
                    "ask_next": "none",
                    "attach_offers": True,
                    "escalate": False,
                },
                ensure_ascii=False,
            ),
            "mock/pets",
        )

    smart_mod.set_understand_hook(_hook)
    try:
        msgs, upd, esc = await _turn(
            _sess(
                dates="",
                guests="",
                district="",
                returning="",
                step="greeting",
                context={"greeted": True, "outreach": True},
            ),
            "Здравствуйте! Да, планы есть на январь с 1 по 7, 3 человека, центр, можно с собакой?",
            [
                {
                    "role": "bot",
                    "text": "Доброе утро, Мария! Это Home24. Давно не бронировали.",
                }
            ],
        )
    finally:
        smart_mod.set_understand_hook(None)
    blob = "\n".join(msgs).lower()
    assert not esc
    assert "собак" in blob
    assert "номер или название" not in blob
    assert "какой вариант" not in blob
    assert str((upd.get("context") or {}).get("pets") or "")


def test_no_cards_keeps_pet_and_skips_pick() -> None:
    test_dedupe_keeps_pet_fact_after_outreach()
    asyncio.run(_sc_no_cards_no_pick_question())


def test_two_nights_is_a_human_date() -> None:
    from bot.engine import parse_dates

    assert parse_dates("На 24 октября на 2 суток") == "24–26 октября"

    async def run():
        msgs, upd, esc = await _turn(
            _sess(dates="", guests="", district="", step="await_dates"),
            "На 24 октября на 2 суток",
            [{"role": "bot", "text": "На какие даты планируете поездку?"}],
        )
        blob = "\n".join(msgs)
        low = blob.lower()
        assert not esc
        assert "24–26 октября" in blob
        assert "две ночи" in low
        assert "сколько вас будет" in low
        assert "планирует" not in low
        assert upd.get("dates") == "24–26 октября"
        assert (upd.get("context") or {}).get("reply_path") == "smart:rule/dates"

    asyncio.run(run())


def test_short_answers_stay_human() -> None:
    async def guests():
        msgs, upd, esc = await _turn(
            _sess(dates="24–26 октября", guests="", district="", step="await_guests"),
            "3",
            [{"role": "bot", "text": "Сколько вас будет?"}],
        )
        blob = "\n".join(msgs).lower()
        assert not esc
        assert "трое" in blob
        assert "центр" in blob
        assert "планирует" not in blob
        assert upd.get("guests") == "3"

    async def place():
        from datetime import date

        from bot.travelline import Stay, set_search_hook

        def hook(_a: date, _d: date, _adults: int):
            return [
                Stay(
                    room_id="2",
                    title="Карма",
                    address="Москва, Прокшинский проспект, д. 9",
                    price_night=4500,
                    price_total=9000,
                    available=1,
                )
            ]

        set_search_hook(hook)
        try:
            msgs, upd, esc = await _turn(
                _sess(dates="на 24", guests="3", district="", step="await_district"),
                "Прокшино",
                [
                    {"role": "guest", "text": "На 24 октября на 2 суток"},
                    {"role": "bot", "text": "Сколько вас будет?"},
                    {"role": "guest", "text": "3"},
                ],
            )
        finally:
            set_search_hook(None)
        blob = "\n".join(msgs)
        low = blob.lower()
        assert not esc
        assert "карма" in low
        assert "календар" in low
        assert "вот что есть" not in low
        assert upd.get("dates") == "24–26 октября"
        assert (upd.get("district") or "").lower() == "прокшино"

    asyncio.run(guests())
    asyncio.run(place())


def test_all_v9_5() -> None:
    test_dedupe_does_not_replay_same_question()
    test_place_phrase_keeps_street_and_district()
    test_laugh_moves_forward()
    test_availability_names_guest_place()
    test_naive_questions_get_one_fact()
    test_booking_still_understood()
    test_no_cards_keeps_pet_and_skips_pick()
    test_two_nights_is_a_human_date()
    test_short_answers_stay_human()
    print("ok v9.5 manager")


if __name__ == "__main__":
    test_all_v9_5()
