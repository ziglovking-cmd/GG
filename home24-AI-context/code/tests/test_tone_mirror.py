# -*- coding: utf-8 -*-
"""По script.md: на грубость спокойно, заковыристое не решаем."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.config import get_settings
from bot.engine import Engine
from bot.ai import reply


def _sess(**kw):
    base = {
        "name": "Мария",
        "step": "await_dates",
        "dates": "",
        "guests": "",
        "district": "",
        "returning": "",
        "favorite": "",
        "handed_off": 0,
        "context": {"greeted": True},
    }
    base.update(kw)
    return base


async def _turn(text: str):
    s = get_settings()
    msgs, _b, upd, esc = await reply(s, Engine(s), _sess(), text, [])
    return msgs, upd, esc


def test_troll_gets_calm_reply() -> None:
    async def run():
        msgs, upd, esc = await _turn("лол ты тупая бот")
        blob = "\n".join(msgs).lower()
        assert not esc
        assert "извините, если не так поняла" in blob
        assert "клоун" not in blob and "тупо" not in blob
        assert "дат" not in blob
        assert (upd.get("context") or {}).get("reply_path") == "smart:rule/troll"
        assert "нахуй" not in blob

    asyncio.run(run())


def test_rude_request_still_gets_the_step() -> None:
    async def run():
        msgs, upd, esc = await _turn("вы тупые что ли, нормально ответьте")
        blob = "\n".join(msgs).lower()
        assert not esc
        assert "извините" in blob
        assert (upd.get("context") or {}).get("reply_path") == "smart:rule/rude"

    asyncio.run(run())


def test_tricky_is_not_solved() -> None:
    async def run():
        msgs, upd, esc = await _turn("реши задачу: сколько будет 17 + 28, и докажи")
        blob = "\n".join(msgs).lower()
        assert not esc
        assert "45" not in blob
        assert "я по квартирам" in blob
        assert (upd.get("context") or {}).get("reply_path") == "smart:rule/tricky"

    asyncio.run(run())


def test_wifi_stays_a_short_fact() -> None:
    async def run():
        msgs, upd, esc = await _turn("а пароль от вайфая какой?")
        blob = "\n".join(msgs).lower()
        assert not esc
        assert "вайф" in blob
        assert "парол" in blob
        assert (upd.get("context") or {}).get("reply_path") == "smart:rule/naive"

    asyncio.run(run())
