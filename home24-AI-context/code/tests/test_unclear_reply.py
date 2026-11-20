# -*- coding: utf-8 -*-
"""Обрывок и замечание про скорость — ответ по делу, без отповеди."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot.reply_guard import question_key  # noqa: E402
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine, parse_dates
from bot.smart import _craft_early


def _sess():
    return {
        "name": "Гость",
        "step": "await_dates",
        "dates": "",
        "guests": "",
        "district": "",
        "returning": "",
        "favorite": "",
        "handed_off": 0,
        "context": {"greeted": True},
    }


def test_noisy_day_fragment_is_a_date() -> None:
    assert parse_dates("ну газ в 10") == "на 10"
    assert parse_dates("на 26") == "на 26"
    assert parse_dates("заезд в 10") != "на 10"
    assert parse_dates("в 10 утра") != "на 10"


def test_noisy_day_asks_the_month() -> None:
    out = _craft_early(_sess(), "ну газ в 10", [])
    assert out is not None
    blob = out[0][0].lower()
    assert "заковырист" not in blob
    assert "по делу" not in blob
    assert "10" in blob
    assert "месяц" in blob
    assert out[2]["dates"] == "на 10"
    assert out[2]["step"] == "await_dates"


def test_pace_remark_does_not_lecture() -> None:
    history = [
        {
            "role": "bot",
            "text": "Здравствуйте! Подскажите, пожалуйста, на какие даты планируете поездку?",
        }
    ]
    out = _craft_early(_sess(), "бистро ответил", history)
    assert out is not None
    blob = out[0][0].lower()
    assert "по делу" not in blob
    assert "не значит" not in blob
    assert "заковырист" not in blob
    assert "жду числа" not in blob
    # формулировка вопроса чередуется (reply_guard.humanize) — важен сам вопрос про даты
    assert question_key(blob) == "dates" or "даты" in blob
    assert (out[2].get("context") or {}).get("reply_path") == "smart:rule/pace"


def test_live_path_keeps_both_replies() -> None:
    async def run():
        s = get_settings()
        engine = Engine(s)
        history = [
            {
                "role": "bot",
                "text": "Здравствуйте! Подскажите, пожалуйста, на какие даты планируете поездку?",
            }
        ]
        msgs, _b, upd, esc = await reply(s, engine, _sess(), "ну газ в 10", history)
        blob = "\n".join(msgs).lower()
        assert not esc
        assert "10" in blob
        assert "заковырист" not in blob
        msgs2, _b2, _u2, esc2 = await reply(s, engine, _sess(), "бистро ответил", history)
        blob2 = "\n".join(msgs2).lower()
        assert not esc2
        assert blob2.strip()
        assert "по делу" not in blob2
        assert "не значит" not in blob2
        assert "заковырист" not in blob2
        assert question_key(blob2) == "dates" or "даты" in blob2

    asyncio.run(run())
