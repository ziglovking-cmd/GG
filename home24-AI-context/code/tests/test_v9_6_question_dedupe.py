# -*- coding: utf-8 -*-
"""v9.6: один вопрос на слот — без «Назовите … количество гостей — 2, 3 или 4?» + «сколько будет гостей?»."""
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

from bot.question_dedupe import GUESTS_Q, asked_slots, dedupe_slot_questions  # noqa: E402

IYA_BAD = (
    "Отлично! Назовите, пожалуйста, количество гостей — 2, 3 или 4 человека? "
    "Подскажите, пожалуйста, сколько будет гостей?"
)


def _run(sess, text, hook_json, history=None):
    from bot import smart
    from bot.config import get_settings
    from bot.engine import Engine

    async def hook(system, messages, **kw):
        return json.dumps(hook_json, ensure_ascii=False), "mock"

    smart.set_understand_hook(hook)
    try:
        s = get_settings()
        return asyncio.run(smart.smart_reply(
            s, Engine(s), sess, text, history or [{"role": "bot", "text": "Добрый вечер! Это Home24"}]
        ))
    finally:
        smart.set_understand_hook(None)


def _sess(**kw):
    base = {"name": "Iya", "step": "await_dates", "dates": "", "guests": "", "district": "",
            "returning": "да", "favorite": "", "handed_off": 0,
            "context": {"outreach": True, "greeted": True, "smart": True}}
    base.update(kw)
    return base


def test_iya_exact_bubble_deduped():
    assert dedupe_slot_questions([IYA_BAD]) == ["Отлично! Подскажите, пожалуйста, сколько будет гостей?"]


def test_nazovite_template_replaced():
    out = dedupe_slot_questions(["Назовите, пожалуйста, количество гостей — 2, 3 или 4 человека?"])
    assert out == [GUESTS_Q]
    assert "Назовите" not in out[0] and "2, 3 или 4" not in out[0]


def test_cross_bubble_and_other_slots():
    assert dedupe_slot_questions(["Супер! Сколько вас будет?", GUESTS_Q]) == ["Супер! Сколько вас будет?"]
    out = dedupe_slot_questions(["На какие даты смотрите? Подскажите, пожалуйста, на какие даты планируете поездку?"])
    assert out == ["На какие даты смотрите?"]
    out = dedupe_slot_questions(["Какой район ближе? Какой район удобнее — центр или поспокойнее?"])
    assert out == ["Какой район ближе?"]
    out = dedupe_slot_questions(["Какой бюджет на сутки? Подскажите бюджет, пожалуйста?"])
    assert out == ["Какой бюджет на сутки?"]
    # разные слоты не трогаем
    msg = "Подскажите, пожалуйста, на какие даты планируете поездку и сколько будет гостей?"
    assert dedupe_slot_questions([msg]) == [msg]
    assert asked_slots(msg) == {"dates", "guests"}
    # не-вопросы с «гостей» не режем
    assert dedupe_slot_questions(["Квартира до 4 гостей.", GUESTS_Q]) == ["Квартира до 4 гостей.", GUESTS_Q]


def test_smart_reply_llm_ask_plus_funnel_no_double():
    hook = {
        "intent": "looking",
        "slots": {"dates": "с 3 по 5 ноября"},
        "messages": ["Отлично! Назовите, пожалуйста, количество гостей — 2, 3 или 4 человека?"],
        "ask_next": "guests",
    }
    m, _b, upd, esc = _run(_sess(), "Да,супер! Необходима квартира на 3,4,5 ноября", hook)
    blob = " ".join(m)
    assert not esc
    assert "Назовите" not in blob and "2, 3 или 4" not in blob, blob
    assert blob.count("гостей") == 1, blob
    assert "Подскажите, пожалуйста, сколько будет гостей?" in blob, blob


def test_smart_reply_llm_without_question_gets_funnel_once():
    hook = {
        "intent": "looking",
        "slots": {"dates": "с 3 по 5 ноября"},
        "messages": ["Отлично!"],
        "ask_next": "guests",
    }
    m, _b, _u, _e = _run(_sess(), "Нужна квартира на 3,4,5 ноября", hook)
    blob = " ".join(m)
    assert blob.count("сколько будет гостей") == 1, blob


def test_guarantee_dedupes_script_path():
    from bot.ai import _guarantee

    msgs, _b, _u, _e = _guarantee(
        ["Сколько вас будет?", GUESTS_Q], None, {}, False, "await_guests", history=[]
    )
    assert " ".join(msgs).count("?") == 1, msgs
