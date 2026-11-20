"""Анти-артефакты: без «не поймала», шум и квартиры mid-воронки."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.ai import _is_noise, reply
from bot.config import get_settings
from bot.engine import Engine


def test_noise() -> None:
    assert _is_noise("https://disk.yandex.ru/d/abc")
    assert _is_noise("18543546950")
    assert _is_noise("a" * 40 + "f" * 40)
    assert not _is_noise("на 30")
    assert not _is_noise("ищу квартиру")


async def _run() -> None:
    s = get_settings()
    e = Engine(s)
    sess = {"step": "await_dates", "dates": "", "guests": "", "handed_off": 0, "context": {}}

    msgs, _, _, _ = await reply(s, e, sess, "https://disk.yandex.ru/d/abc", [])
    blob = " ".join(msgs).lower()
    assert "не совсем поймала" not in blob
    assert "приняла" in blob or "поняла" in blob
    assert "дат" in blob

    msgs2, _, upd2, _ = await reply(s, e, dict(sess), "Вояж", [])
    assert upd2.get("favorite")
    assert "не совсем поймала" not in " ".join(msgs2).lower()
    assert "вояж" in " ".join(msgs2).lower()

    msgs3, _, _, _ = await reply(
        s, e, {**sess, "context": {"last_soft": "await_dates"}}, "хм", []
    )
    assert "не совсем поймала" not in " ".join(msgs3).lower()
    print("OK anti-artifact")


if __name__ == "__main__":
    test_noise()
    asyncio.run(_run())
    print("ALL OK")
