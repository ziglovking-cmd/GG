# -*- coding: utf-8 -*-
"""v9.4 — «подумаем / посоветуюсь / позже напишу»: тёплая пауза, без вопросов воронки."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine, is_deferral, is_refusal
from bot import smart as smart_mod

OFFERS = ["Артледи", "Россо", "Юниверсал"]
FUNNEL_Q = ("район", "центр или", "сколько", "на какие даты", "впервые", "были у нас")

_CALLS: list[int] = []


def _bad_llm(payload: dict[str, Any] | None = None):
    """Имитация ministral-8b: «подумаем» → intent=looking, ask_next=district."""
    data = payload or {
        "intent": "looking",
        "slots": {"dates": "с 1 по 7 ноября", "guests": "2"},
        "messages": ["Какой район удобнее — центр или поспокойнее?"],
        "ask_next": "district",
    }

    async def _hook(system, messages, **_kw):
        _CALLS.append(1)
        return json.dumps(data, ensure_ascii=False), "mock/ministral"

    return _hook


def _sess_after_offers() -> dict[str, Any]:
    return {
        "name": "Iya",
        "step": "await_returning",
        "dates": "с 1 по 7 ноября",
        "guests": "2",
        "district": "",
        "returning": "",
        "favorite": "",
        "handed_off": 0,
        "context": {"greeted": True, "outreach": True, "offers": list(OFFERS), "smart": True},
    }


def _hist_after_offers() -> list[dict[str, Any]]:
    return [
        {"role": "bot", "text": "Добрый день, Iya! Это Home24. Вы у нас уже жили — возможно, планируете снова приехать в Москву?"},
        {"role": "guest", "text": "Здравствуйте! Да"},
        {"role": "bot", "text": "Подскажите, пожалуйста, на какие даты планируете поездку?"},
        {"role": "guest", "text": "С 1 по 7 ноября"},
        {"role": "bot", "text": "Сколько человек будет проживать?"},
        {"role": "guest", "text": "2"},
        {"role": "bot", "text": "Подобрала несколько вариантов под вас 🙂\n\n1) «Артледи»\n2) «Россо»\n3) «Юниверсал»\n\nЕсли зайдёт — напишите номер (1–3) или название."},
        {"role": "guest", "text": "Супер! Спасибо"},
        {"role": "bot", "text": "Хорошо, жду вашего выбора! Напишите номер варианта."},
    ]


async def _say(sess, text, history, payload=None):
    smart_mod.set_understand_hook(_bad_llm(payload))
    try:
        s = get_settings()
        return await reply(s, Engine(s), sess, text, history)
    finally:
        smart_mod.set_understand_hook(None)


def _assert_pause(msgs: list[str], upd: dict[str, Any], esc: bool, step_before: str) -> None:
    assert len(msgs) == 1, msgs
    blob = msgs[0].lower()
    assert "?" not in msgs[0], msgs
    for q in FUNNEL_Q:
        assert q not in blob, (q, msgs)
    assert "анна" not in blob, msgs
    assert not esc
    assert not upd.get("handed_off"), upd
    assert (upd.get("step") or step_before) == step_before, upd
    assert (upd.get("context") or {}).get("funnel_paused") is True, upd


def test_is_deferral_patterns() -> None:
    yes = [
        "Подумаем", "подумаю", "Надо подумать", "посоветуюсь с мужем", "пока думаем",
        "позже напишу", "Спасибо, подумаем", "я подумаю и напишу", "обсудим с женой",
        "дам знать", "напишу потом", "как решим — напишем", "думаем", "Хорошо, подумаю)",
    ]
    no = [
        "2", "центр", "давайте 2", "подумаю, а с парковкой есть?", "с 1 по 7 ноября",
        "думаю, в центре", "спасибо", "Супер! Спасибо", "не пишите мне",
    ]
    for t in yes:
        assert is_deferral(t), t
    for t in no:
        assert not is_deferral(t), t
    for t in ("пока не актуально", "спасибо, не надо", "уже не актуально"):
        assert is_refusal(t) and not is_deferral(t), t


def test_deferral_after_offers() -> None:
    for text, word in (
        ("Подумаем", "подумайте"),
        ("подумаю", "подумайте"),
        ("надо подумать", "подумайте"),
        ("посоветуюсь с мужем", "посоветуйтесь"),
        ("позже напишу", "буду ждать"),
    ):
        _CALLS.clear()
        sess = _sess_after_offers()
        msgs, btns, upd, esc = asyncio.run(_say(sess, text, _hist_after_offers()))
        _assert_pause(msgs, upd, esc, "await_returning")
        assert word in msgs[0].lower(), (text, msgs)
        assert "забронировать" in msgs[0].lower() and "на связи" in msgs[0].lower(), msgs
        assert not btns, btns
        assert not _CALLS, f"LLM must not decide pauses: {text}"
        # варианты не потеряли — можно выбрать позже
        assert (upd.get("context") or {}).get("offers") == OFFERS, upd
    sess = _sess_after_offers()
    msgs, *_ = asyncio.run(_say(sess, "Подумаем", _hist_after_offers()))
    assert msgs == [
        "Хорошо, подумайте! Если появятся вопросы или захотите забронировать — пишите, я на связи 🙂"
    ], msgs


def test_deferral_mid_qualification() -> None:
    sess = {
        "name": "Iya",
        "step": "await_guests",
        "dates": "с 1 по 7 ноября",
        "guests": "",
        "district": "",
        "returning": "",
        "favorite": "",
        "handed_off": 0,
        "context": {"greeted": True, "smart": True},
    }
    hist = [
        {"role": "bot", "text": "Подскажите, пожалуйста, на какие даты планируете поездку?"},
        {"role": "guest", "text": "С 1 по 7 ноября"},
        {"role": "bot", "text": "Сколько человек будет проживать?"},
    ]
    for text in ("подумаем", "посоветуюсь с мужем"):
        _CALLS.clear()
        msgs, _b, upd, esc = asyncio.run(_say(dict(sess, context=dict(sess["context"])), text, hist))
        _assert_pause(msgs, upd, esc, "await_guests")
        assert "подберу варианты" in msgs[0], msgs
        assert not _CALLS


def test_llm_defer_intent_respected() -> None:
    # фраза без ключевых слов, но LLM поняла паузу → тоже без вопроса воронки
    sess = _sess_after_offers()
    msgs, _b, upd, esc = asyncio.run(
        _say(sess, "хм, не знаю пока", _hist_after_offers(),
             {"intent": "defer", "slots": {}, "messages": ["Хорошо!"], "ask_next": "none"})
    )
    _assert_pause(msgs, upd, esc, "await_returning")


def test_polite_decline_no_funnel() -> None:
    for text in ("спасибо, не надо", "пока не актуально"):
        sess = _sess_after_offers()
        _CALLS.clear()
        msgs, _b, upd, esc = asyncio.run(_say(sess, text, _hist_after_offers()))
        blob = "\n".join(msgs).lower()
        assert msgs, text
        assert "?" not in blob, msgs
        for q in ("район", "центр или", "сколько", "на какие даты"):
            assert q not in blob, (q, msgs)
        assert not esc
        assert not _CALLS


def test_resume_after_pause() -> None:
    sess = _sess_after_offers()
    hist = _hist_after_offers()
    msgs, _b, upd, _e = asyncio.run(_say(sess, "Подумаем", hist))
    sess["context"] = upd.get("context") or sess["context"]
    sess["step"] = upd.get("step") or sess["step"]
    hist += [{"role": "guest", "text": "Подумаем"}, {"role": "bot", "text": msgs[0]}]
    msgs2, _b2, upd2, _e2 = asyncio.run(_say(sess, "давайте 2", hist))
    assert any("Россо" in m for m in msgs2), msgs2


def test_all_v9_4() -> None:
    test_is_deferral_patterns()
    test_deferral_after_offers()
    test_deferral_mid_qualification()
    test_llm_defer_intent_respected()
    test_polite_decline_no_funnel()
    test_resume_after_pause()
    print("ok v9.4 deferral")


if __name__ == "__main__":
    test_all_v9_4()
