# -*- coding: utf-8 -*-
"""v9.1 — точечные фиксы умного бота (8 пунктов)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine, parse_guests
from bot import smart as smart_mod
from bot.smart import (
    _pets_answer,
    _slot_summary_line,
    log_smart_startup,
    smart_enabled,
)


def _j(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def _mock(payload: dict):
    async def _hook(system, messages, **_k):
        return _j(**payload), "mock/v9.1"

    return _hook


def _sess(**kw):
    base = {
        "name": "Мария",
        "step": "await_intent",
        "dates": "",
        "guests": "",
        "district": "",
        "returning": "",
        "favorite": "",
        "handed_off": 0,
        "context": {"greeted": True, "outreach": True},
    }
    base.update(kw)
    return base


async def _turn(sess, text, history, payload):
    smart_mod.set_understand_hook(_mock(payload))
    try:
        s = get_settings()
        e = Engine(s)
        msgs, _b, upd, esc = await reply(s, e, sess, text, history)
        for k, v in upd.items():
            if k == "context":
                sess["context"] = v
            elif v is not None and v != "":
                sess[k] = v
        if esc:
            sess["handed_off"] = 1
        history.append({"role": "guest", "text": text})
        for m in msgs:
            history.append({"role": "bot", "text": m})
        return msgs, upd, esc
    finally:
        smart_mod.set_understand_hook(None)


def test_1_kids_count_as_guests() -> None:
    assert parse_guests("нас двое и ребёнок, тихий район") == "3"
    assert parse_guests("на выходные нас двое и ребёнок") == "3"
    assert parse_guests("двое взрослых и ребёнок") == "3"
    assert parse_guests("нас двое") == "2"  # exact, not 1-2
    assert parse_guests("1-2 человека") == "1-2"
    # даты «на 12-14» не должны становиться числом гостей
    assert parse_guests("Ищу квартиру на 12-14 марта, 2 гостя, центр") == "2"
    assert parse_guests("на 12 марта") is None
    assert parse_guests("не 3 а 4 человека") == "4"


async def _sc_kids_via_smart() -> None:
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "на выходные нас двое и ребёнок, тихий район",
        [],
        {
            "intent": "multi",
            # модель ошибочно даёт диапазон — safety должен взять 3 из текста
            "slots": {
                "dates": "ближайшие выходные",
                "guests": "1-2",
                "district": "спокойный",
                "kids": "ребёнок",
            },
            "messages": ["Записала всё: 1–2 человека"],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Симфония", "Россо"],
            "escalate": False,
        },
    )
    assert upd.get("guests") == "3", upd
    blob = "\n".join(msgs).lower()
    assert "1–2" not in blob and "1-2" not in blob
    assert "3" in blob or "трое" in blob or "3 человек" in blob or "3 гост" in blob


def test_1_kids_smart_slots() -> None:
    asyncio.run(_sc_kids_via_smart())


async def _sc_correction() -> None:
    sess = _sess(
        dates="с 1 по 7 января",
        guests="3",
        district="центр",
        step="await_returning",
        context={
            "greeted": True,
            "offers": ["Чехов", "Дюма", "Жизель"],
        },
    )
    hist = [
        {"role": "bot", "text": "Приняла: с 1 по 7 января, 3 человека, центр."},
        {"role": "bot", "text": "1) Чехов\n2) Дюма\n3) Жизель"},
    ]
    msgs, upd, _ = await _turn(
        sess,
        "не 3 а 4 человека",
        hist,
        {
            "intent": "correction",
            "slots": {"dates": "с 1 по 7 января", "guests": "4", "district": "центр"},
            "messages": ["ок"],
            "ask_next": "pick",
            "attach_offers": False,
            "escalate": False,
        },
    )
    blob = "\n".join(msgs)
    assert "Поняла, 4 человека" in blob or "поняла, 4" in blob.lower()
    assert upd.get("guests") == "4"
    # переподбор: карточки или хотя бы не только «какой вариант»
    assert "подобрал" in blob.lower() or "1)" in blob or "почему подходит" in blob.lower()
    # все показанные вмещают 4
    offers = (upd.get("context") or {}).get("offers") or []
    assert offers
    from bot.catalog import find_by_name

    for name in offers:
        hit = find_by_name(name)
        assert hit, name
        cap = hit.get("capacity")
        if isinstance(cap, int):
            assert cap >= 4, (name, cap)


def test_2_correction_confirm_and_repick() -> None:
    asyncio.run(_sc_correction())


def test_3_pets_answer_not_generic_note() -> None:
    ans = _pets_answer("можно с собакой?", {"pets": "собака"})
    assert "животн" in ans.lower()
    assert "зависит от конкретной квартиры" in ans.lower()
    assert "отметила ваш запрос" not in ans.lower()

    async def _run() -> None:
        sess = _sess()
        msgs, _, _ = await _turn(
            sess,
            "январь 1–7, 3 человека, центр, можно с собакой?",
            [{"role": "bot", "text": "Добрый день! Это Home24."}],
            {
                "intent": "multi",
                "slots": {
                    "dates": "с 1 по 7 января",
                    "guests": "3",
                    "district": "центр",
                    "pets": "собака",
                },
                "messages": ["С питомцами — на части объектов; отметила ваш запрос."],
                "ask_next": "returning",
                "attach_offers": True,
                "offer_names": ["Чехов", "Дюма"],
                "escalate": False,
            },
        )
        blob = "\n".join(msgs).lower()
        assert "отметила ваш запрос" not in blob
        assert "собак" in blob or "питом" in blob or "животн" in blob
        assert (
            "зависит от квартиры" in blob
            or "менеджер" in blob
            or "согласован" in blob
            or "можно с животными" in blob
        )

    asyncio.run(_run())


def test_4_summary_varies_and_delta() -> None:
    full = _slot_summary_line(
        {"dates": "с 1 по 7 января", "guests": "3", "district": "центр"},
        {},
        only_changed=False,
    )
    assert full and "записала всё" not in full.lower()
    delta = _slot_summary_line(
        {"dates": "с 1 по 7 января", "guests": "4", "district": "центр"},
        {"dates": "с 1 по 7 января", "guests": "3", "district": "центр"},
        only_changed=True,
    )
    # одна правка гостей → None (caller скажет «Поняла, 4»)
    assert delta is None


async def _sc_weather() -> None:
    sess = _sess(step="await_dates")
    # weather short-circuit — hook не должен понадобиться, но поставим
    smart_mod.set_understand_hook(_mock({"intent": "chitchat", "messages": ["+5°C"]}))
    try:
        msgs, _, _, _ = await reply(
            get_settings(), Engine(get_settings()), sess, "какая погода", []
        )
    finally:
        smart_mod.set_understand_hook(None)
    blob = "\n".join(msgs).lower()
    assert "не проверяю" in blob or "не смотрю" in blob or "приложении" in blob
    assert "°" not in "\n".join(msgs)
    assert "дат" in blob or "продолж" in blob


def test_5_weather_no_made_up_facts() -> None:
    asyncio.run(_sc_weather())


async def _sc_rude() -> None:
    sess = _sess(step="await_dates")
    smart_mod.set_understand_hook(
        _mock({"intent": "chitchat", "messages": ["Хорошо"], "escalate": True})
    )
    try:
        msgs, _, upd, esc = await reply(
            get_settings(),
            Engine(get_settings()),
            sess,
            "вы чё тупите",
            [{"role": "bot", "text": "На какие даты?"}],
        )
    finally:
        smart_mod.set_understand_hook(None)
    blob = "\n".join(msgs).lower()
    # script.md v3: на грубость спокойно, без зеркаления
    assert "извините, если не так поняла" in blob
    assert "тупо" not in blob
    assert not esc
    assert (upd.get("context") or {}).get("reply_path") == "smart:rule/troll"


def test_6_pure_troll_is_mirrored() -> None:
    asyncio.run(_sc_rude())


async def _sc_pick() -> None:
    sess = _sess(
        dates="с 1 по 7 января",
        guests="4",
        district="центр",
        step="await_returning",
        context={"greeted": True, "offers": ["Чехов", "Дюма", "Жизель"]},
    )
    hist = [{"role": "bot", "text": "1) Чехов\n2) Дюма\n3) Жизель"}]
    # early pick — до LLM
    smart_mod.set_understand_hook(
        _mock({"intent": "book", "messages": ["не должно слать карточки снова"]})
    )
    try:
        msgs, _, upd, esc = await reply(
            get_settings(),
            Engine(get_settings()),
            sess,
            "давайте 1",
            hist,
        )
    finally:
        smart_mod.set_understand_hook(None)
    blob = "\n".join(msgs)
    assert "Чехов" in blob
    assert "подобрала несколько" not in blob.lower()
    assert "впервые" in blob.lower() or "были" in blob.lower() or esc
    assert upd.get("favorite") == "Чехов" or "Чехов" in blob


def test_7_pick_confirms_name_no_resend_cards() -> None:
    asyncio.run(_sc_pick())


async def _sc_crib() -> None:
    sess = _sess(
        dates="ближайшие выходные",
        guests="3",
        district="спокойный",
        step="await_returning",
        context={"greeted": True, "offers": ["Матисс", "Мёд"]},
    )
    smart_mod.set_understand_hook(
        _mock({"intent": "faq", "messages": ["не должно эхо гостя"]})
    )
    try:
        msgs, _, _, esc = await reply(
            get_settings(),
            Engine(get_settings()),
            sess,
            "а кроватка детская есть?",
            [{"role": "bot", "text": "1) Матисс"}],
        )
    finally:
        smart_mod.set_understand_hook(None)
    blob = "\n".join(msgs).lower()
    assert "кроват" in blob
    assert "менеджер" in blob or "уточню" in blob  # script.md: «Кроватку или стульчик уточню по квартире»
    assert "нас двое" not in blob
    assert not esc


def test_crib_faq_no_echo() -> None:
    asyncio.run(_sc_crib())


def test_8_smart_bot_default_on_and_logs() -> None:
    os.environ.pop("HOME24_FORCE_SCRIPT", None)
    smart_mod.set_understand_hook(None)
    assert smart_mod.SMART_BOT is True
    assert smart_enabled() is True
    log_smart_startup()
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"(?m)^SMART_BOT=1\s*$", example)
    # дефолт getenv без .env тоже «1»
    assert os.getenv("SMART_BOT", "1") == "1" or os.getenv("SMART_BOT") == "1"


def test_all_v9_1() -> None:
    test_1_kids_count_as_guests()
    test_1_kids_smart_slots()
    test_2_correction_confirm_and_repick()
    test_3_pets_answer_not_generic_note()
    test_4_summary_varies_and_delta()
    test_5_weather_no_made_up_facts()
    test_6_rude_apology_plus_next_step()
    test_7_pick_confirms_name_no_resend_cards()
    test_crib_faq_no_echo()
    test_8_smart_bot_default_on_and_logs()
    print("ok v9.1 fixes")


if __name__ == "__main__":
    test_all_v9_1()
