# -*- coding: utf-8 -*-
"""v9.4 — догадливый тон: human-ack, LLM insight, inference из намёков."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine, parse_district, parse_guests
from bot import smart as smart_mod
from bot.smart import (
    _human_ack,
    _llm_insight_ok,
    _next_question,
    _pick_llm_insight,
    _sanitize_messages,
)


def _j(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def _mock(payload: dict):
    async def _hook(system, messages, **_k):
        return _j(**payload), "mock/v9.4"

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
            elif v not in (None, ""):
                sess[k] = v
        if esc:
            sess["handed_off"] = 1
        history.append({"role": "guest", "text": text})
        for m in msgs:
            history.append({"role": "bot", "text": m})
        return msgs, upd, esc
    finally:
        smart_mod.set_understand_hook(None)


def test_infer_couple_center_weekend() -> None:
    assert parse_guests("нужны на выходные вдвоём поближе к центру") == "2"
    assert parse_district("нужны на выходные вдвоём поближе к центру") == "Близко к центру"
    assert parse_guests("с парнем на двоих") == "2"
    assert parse_district("потише, подальше от шума") == "спокойный район"


def test_human_ack_and_insight_filters() -> None:
    ack = _human_ack(
        "на выходные вдвоём центр",
        {"dates": "ближайшие выходные", "guests": "2", "district": "центр"},
        {},
    )
    assert ack
    assert "записала всё" not in ack.lower()
    assert "2" in ack or "дво" in ack.lower()

    assert _llm_insight_ok(
        "Поняла, выходные на двоих в центре — сейчас подберу.",
        intent="looking",
    )
    assert not _llm_insight_ok("Записала: 1–2 человека", intent="looking")
    assert not _llm_insight_ok(
        "Подберу с парковкой и метро рядом.", intent="looking"
    )
    cleaned = _sanitize_messages(
        ["На выходные, двое, ближе к центру. Покажу варианты."],
        allowed_prices=set(),
        greeted=True,
    )
    assert cleaned == ["На выходные, двое, ближе к центру."]

    picked = _pick_llm_insight(
        ["Поняла, на двоих в центре. Были у нас раньше?"],
        intent="looking",
        with_cards=True,
    )
    assert picked and "?" not in picked


def test_next_question_uses_known_slots() -> None:
    q = _next_question("guests", {"dates": "с пятницы по воскресенье"})
    assert q and "сколько" in q.lower()
    q2 = _next_question(
        "district", {"dates": "ближайшие выходные", "guests": "2"}
    )
    assert q2 and "центр" in q2.lower()
    assert "подмосков" in q2.lower() or "зелён" in q2.lower() or "зелен" in q2.lower()


async def _sc_insight_over_robot_summary() -> None:
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "на выходные вдвоём поближе к центру",
        [{"role": "bot", "text": "Добрый день! Это Home24."}],
        {
            "intent": "looking",
            "slots": {
                "dates": "ближайшие выходные",
                "guests": "2",
                "district": "Близко к центру",
            },
            "messages": [
                "Поняла, выходные на двоих ближе к центру — сейчас подберу варианты."
            ],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов", "Дюма"],
            "escalate": False,
        },
    )
    assert len(msgs) <= 2, msgs
    blob = "\n".join(msgs).lower()
    assert "записала:" not in blob and "отметила:" not in blob
    assert "выходн" in blob or "дво" in blob or "центр" in blob
    assert upd.get("guests") == "2"
    assert "центр" in str(upd.get("district") or "").lower()
    offers = (upd.get("context") or {}).get("offers") or []
    # без mailing.sqlite карточки могут не подтянуться — район всё равно записан
    assert offers or "центр" in str(upd.get("district") or "").lower()


def test_insight_preferred_when_safe() -> None:
    asyncio.run(_sc_insight_over_robot_summary())


async def _sc_human_ack_fallback() -> None:
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "с 5 по 8 мая, нас двое, спокойный район",
        [{"role": "bot", "text": "Здравствуйте!"}],
        {
            "intent": "looking",
            "slots": {
                "dates": "с 5 по 8 мая",
                "guests": "2",
                "district": "спокойный",
            },
            # робо-сводка / пустышка — система должна дать human-ack
            "messages": ["Записала: с 5 по 8 мая, 2 человека, спокойный район."],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Симфония", "Россо"],
            "escalate": False,
        },
    )
    blob = "\n".join(msgs)
    low = blob.lower()
    assert "записала:" not in low
    assert "сейчас подберу" in low or "поняла" in low or "вижу" in low or "приняла" in low
    assert upd.get("guests") == "2"


def test_human_ack_when_llm_robotic() -> None:
    asyncio.run(_sc_human_ack_fallback())


async def _sc_no_reask_known() -> None:
    sess = _sess(
        dates="с 1 по 7 января",
        guests="2",
        district="",
        step="await_district",
    )
    msgs, upd, _ = await _turn(
        sess,
        "поближе к центру",
        [{"role": "bot", "text": "Какой район удобнее?"}],
        {
            "intent": "looking",
            "slots": {
                "dates": "с 1 по 7 января",
                "guests": "2",
                "district": "Близко к центру",
            },
            "messages": ["Ок"],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов"],
            "escalate": False,
        },
    )
    blob = "\n".join(msgs).lower()
    assert "сколько будет гост" not in blob
    assert "на какие даты" not in blob
    assert upd.get("district")
    assert "центр" in str(upd.get("district")).lower()


def test_does_not_reask_known_slots() -> None:
    asyncio.run(_sc_no_reask_known())


def test_all_v9_4() -> None:
    test_infer_couple_center_weekend()
    test_human_ack_and_insight_filters()
    test_next_question_uses_known_slots()
    test_insight_preferred_when_safe()
    test_human_ack_when_llm_robotic()
    test_does_not_reask_known_slots()
    print("ok v9.4 human-smart")


if __name__ == "__main__":
    test_all_v9_4()
