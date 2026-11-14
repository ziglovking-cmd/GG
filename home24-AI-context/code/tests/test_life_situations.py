# -*- coding: utf-8 -*-
"""Ситуации проживания: факт, менеджер или тишина. Бронь не перехватываем."""

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
from bot.engine import Engine
from bot import smart as smart_mod


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


async def _turn(text: str, **sess):
    s = get_settings()
    msgs, _b, upd, esc = await reply(s, Engine(s), _sess(**sess), text, [])
    return "\n".join(msgs).lower(), upd, esc


def test_paid_and_trouble_go_to_manager() -> None:
    async def run() -> None:
        blob, upd, esc = await _turn("я уже оплатил, пришлите подтверждение")
        assert esc
        assert "не подтвержда" in blob
        assert upd.get("handed_off") == 1
        blob2, _, esc2 = await _turn("нет горячей воды, не могу зайти")
        assert esc2
        assert "менеджер" in blob2
        assert "5000" not in blob2

    asyncio.run(run())


def test_later_and_wrong_number_do_not_sell() -> None:
    async def run() -> None:
        blob, upd, esc = await _turn("подумаю")
        assert not esc
        assert "готовы" in blob
        assert "?" not in blob
        assert (upd.get("context") or {}).get("reply_path") == "smart:rule/life/later"
        blob2, upd2, esc2 = await _turn("ошибся номером")
        assert not esc2
        assert "не пишу" in blob2
        assert (upd2.get("context") or {}).get("stopped") is True

    asyncio.run(run())


def test_hotel_extras_are_short_facts() -> None:
    async def run() -> None:
        blob, upd, esc = await _turn("а завтрак входит?")
        assert not esc
        assert "завтрак" in blob
        assert (upd.get("context") or {}).get("reply_path") == "smart:rule/life/breakfast"
        blob2, _, _ = await _turn("можно почасово на пару часов?")
        assert "посуточ" in blob2
        blob3, _, _ = await _turn("встретите в аэропорту?")
        assert "трансфер" in blob3
        assert "₽" not in blob3

    asyncio.run(run())


def test_booking_is_not_stolen_by_life() -> None:
    async def _hook(system, messages, **_k):
        return (
            json.dumps(
                {
                    "intent": "looking",
                    "slots": {"dates": "ближайшие выходные", "guests": "2", "district": "центр"},
                    "messages": ["На выходные, двое, центр — вот что подходит."],
                    "ask_next": "none",
                    "attach_offers": False,
                    "escalate": False,
                },
                ensure_ascii=False,
            ),
            "mock/life",
        )

    async def run() -> None:
        smart_mod.set_understand_hook(_hook)
        try:
            blob, upd, esc = await _turn("нужны на выходные вдвоём поближе к центру")
        finally:
            smart_mod.set_understand_hook(None)
        assert not esc
        path = str((upd.get("context") or {}).get("reply_path") or "")
        assert "life/" not in path
        assert "выходн" in blob or upd.get("dates")

    asyncio.run(run())


if __name__ == "__main__":
    test_paid_and_trouble_go_to_manager()
    test_later_and_wrong_number_do_not_sell()
    test_hotel_extras_are_short_facts()
    test_booking_is_not_stolen_by_life()
    print("life ok")
