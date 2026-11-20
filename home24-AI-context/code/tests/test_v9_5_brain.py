# -*- coding: utf-8 -*-
"""v9.5: сильнее «мозг» — парсеры, small talk, цена до дат, выбор без переспроса, без «Записала:»."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["SMART_BOT"] = "1"

from bot.engine import parse_dates, parse_district, parse_guests  # noqa: E402


def _settings():
    from bot.config import get_settings

    return get_settings()


def _run(sess, text, hook_json=None, history=None):
    from bot import smart
    from bot.engine import Engine

    async def hook(system, messages, **kw):
        return json.dumps(hook_json or {"intent": "chitchat", "slots": {}, "messages": ["Хорошо"], "ask_next": "none"}, ensure_ascii=False), "mock"

    smart.set_understand_hook(hook)
    try:
        s = _settings()
        return asyncio.run(smart.smart_reply(s, Engine(s), sess, text, history or [{"role": "bot", "text": "Добрый день! Это Home24"}]))
    finally:
        smart.set_understand_hook(None)


def _sess(**kw):
    base = {"name": "Мария", "step": "await_intent", "dates": "", "guests": "", "district": "",
            "returning": "", "favorite": "", "handed_off": 0, "context": {"outreach": True, "greeted": True}}
    base.update(kw)
    return base


def test_parse_guests_midmessage_correction():
    assert parse_guests("можно с собакой на 1-7 января нас 3, хотя нет 4, центр") == "4"
    assert parse_guests("на 9-11 ноября, нас 5, ой нет 3") == "3"
    assert parse_guests("нас будет 2+2") == "4"
    assert parse_guests("Мы с мужем и двумя детьми (5 и 8 лет)") == "4"
    assert parse_guests("у метро Павелецкая, с ребенком 2 года и мужем") == "3"
    assert parse_guests("не 3 а 4") == "4"


def test_parse_dates_formats():
    assert parse_dates("с 05.12 по 08.12") == "с 5 по 8 декабря"
    assert parse_dates("15.11-18.11") == "с 15 по 18 ноября"
    assert parse_dates("нас 6 человек, хотим с 31 декабря по 2 января") == "с 31 декабря по 2 января"
    assert parse_dates("на 4 ночи с 24 ноября") == "с 24 по 28 ноября"
    assert parse_dates("на 10-12 декабря вдвоём, хотя нет, с 11 по 13") == "с 11 по 13 декабря"
    assert parse_dates("нас 6") is None
    assert parse_dates("1-7 января") == "с 1 по 7 января"


def test_parse_district_central_and_negation():
    assert parse_district("не центр") == "спокойный район"
    assert parse_district("желательно не в самом центре") == "спокойный район"
    # «Павелецкая» оканчивается на -ая — как оценка («район крутой»), не как название
    assert parse_district("у метро Павелецкая") is None
    assert parse_district("Арбат") == "Арбат"
    assert parse_district("центр") == "центр"
    assert parse_district("ближе к центру") == "Близко к центру"
    assert parse_district("Подмосковье") == "Подмосковье"


def test_price_before_dates_no_handoff():
    msgs, _b, upd, esc = _run(_sess(), "сколько стоит?")
    assert not esc and not upd.get("handed_off")
    assert "₽" in msgs[0] and "дат" in msgs[0]
    assert "менеджер" not in msgs[0].lower()


def test_price_after_dates_still_handoff():
    _m, _b, _u, esc = _run(_sess(dates="с 17 по 19 ноября", guests="2", district="центр"), "сколько стоит?")
    assert esc


def test_smalltalk_rules():
    m, _b, u, esc = _run(_sess(), "кто это?")
    assert "Home24" in m[0] and not esc
    m, *_ = _run(_sess(), "а вы бот?")
    assert "живой" not in m[0].lower() and "Home24" in m[0]
    m, *_ = _run(_sess(), "как дела?")
    assert m[0].startswith("Спасибо")
    m, _b, u, esc = _run(_sess(), "спасибо")
    assert "Пожалуйста" in m[0] and u["step"] != "done" and "Сайт:" not in " ".join(m)
    m, *_ = _run(_sess(context={"outreach": True, "funnel_paused": True}), "ок")
    assert "?" not in m[0]


def test_pick_after_outreach_no_returning_reask():
    sess = _sess(step="await_returning", dates="с 1 по 3 декабря", guests="2", district="центр",
                 context={"outreach": True, "greeted": True, "offers": ["Чехов", "Монблан", "Олимп"]})
    m, _b, upd, esc = _run(sess, "давайте 2")
    assert "впервые" not in m[0] and esc
    assert "Монблан" in m[0]


def test_booking_intent_hands_off():
    sess = _sess(step="await_returning", dates="с 1 по 3 декабря", guests="2", district="центр",
                 context={"greeted": True, "offers": ["Чехов", "Монблан", "Олимп"]})
    _m, _b, _u, esc = _run(sess, "хочу забронировать первый")
    assert esc


def test_multi_message_not_eaten_by_crib_rule():
    text = ("Добрый день! Мы с мужем и двумя детьми хотим приехать с 3 по 6 ноября, "
            "не в самом центре, бюджет до 6000 в сутки. И можно ли детскую кроватку?")
    m, _b, upd, _esc = _run(_sess(), text, hook_json={"intent": "multi", "slots": {}, "messages": [], "ask_next": "none"})
    assert upd.get("dates") == "с 3 по 6 ноября"
    assert upd.get("guests") == "4"
    assert "кроватк" in " ".join(m).lower()


def test_no_robotic_summary_and_no_invented_district():
    m, _b, upd, _e = _run(_sess(), "с 12 по 15 ноября, двое",
                          hook_json={"intent": "looking", "slots": {"dates": "с 12 по 15 ноября", "guests": "2", "district": "центр"},
                                     "messages": [], "ask_next": "none", "attach_offers": False})
    blob = " ".join(m)
    assert "Записала:" not in blob and "Приняла:" not in blob
    assert not upd.get("district")


def test_correction_keeps_pets_and_parking_answer():
    sess = _sess()
    m, _b, upd, _e = _run(sess, "можно с собакой на 1-7 января нас 3, хотя нет 4, центр, и есть ли парковка?",
                          hook_json={"intent": "correction", "slots": {"guests": "3"}, "messages": [], "ask_next": "none"})
    blob = " ".join(m).lower()
    assert upd.get("guests") == "4"
    assert "собак" in blob and "парковк" in blob


def test_photo_of_second_offer_shows_card():
    sess = _sess(step="await_returning", dates="с 1 по 3 декабря", guests="2", district="центр",
                 context={"greeted": True, "offers": ["Чехов", "Монблан", "Олимп"]})
    m, _b, _u, esc = _run(sess, "а покажите фото второго")
    assert not esc and "Монблан" in m[0]


def test_no_verbatim_repeat_who_and_returning_no_redump():
    sess = _sess()
    m1, _b, u1, _e = _run(sess, "кто это?")
    sess["context"] = u1["context"]
    m2, *_ = _run(sess, "откуда номер?")
    assert m1[0] != m2[0]
    sess = _sess(step="await_returning", dates="с 1 по 3 декабря", guests="2", district="центр",
                 context={"greeted": True, "offers": ["Чехов", "Монблан", "Олимп"]})
    m, _b, u, esc = _run(sess, "впервые")
    assert not esc and "1)" not in m[0] and u.get("returning") == "нет"


def test_washing_machine_is_not_parking():
    sess = _sess(step="await_returning", dates="с 3 по 6 ноября", guests="4", district="спокойный район",
                 context={"greeted": True, "outreach": True, "offers": ["Дзен", "Юниверсал", "Дега"]})
    m, *_ = _run(sess, "а стиральная машина есть?", hook_json={"intent": "apartment_q", "slots": {}, "messages": ["Уточню по квартире"], "ask_next": "pick"})
    assert "парковк" not in " ".join(m).lower()


def test_all_v9_5():
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and k != "test_all_v9_5" and callable(v):
            v()
    print("ok v9.5 brain")


if __name__ == "__main__":
    test_all_v9_5()
