# -*- coding: utf-8 -*-
"""Файл номеров: отсев своих, проверка Telegram, раскладка по дням."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HOME24_DB", ":memory:")

from bot.number_screen import pairs_from_text, screen_pairs, take_day
from bot.store import Store


def test_parse_drops_own_and_keeps_name() -> None:
    text = "\n".join(
        [
            "[REDACTED]",
            "@bdoxa",
            "[REDACTED], Ира",
            "[REDACTED]",
            "[REDACTED]",
        ]
    )
    rows, dropped = pairs_from_text(text)
    phones = [r["phone"] for r in rows]
    assert "[REDACTED]" not in phones
    assert "@bdoxa" not in phones
    assert dropped == 2
    assert phones == ["[REDACTED]", "[REDACTED]"]
    named = {r["phone"]: r["name"] for r in rows}
    assert named["[REDACTED]"] == "Ира"


def test_days_respect_limit() -> None:
    load = {"2026-10-14": 1}
    days = [take_day(load, daily=2, start=__import__("datetime").date(2026, 10, 14)) for _ in range(4)]
    assert days == ["2026-10-14", "2026-10-15", "2026-10-15", "2026-10-16"]


def test_screen_splits_and_hides_future_from_today() -> None:
    async def run() -> None:
        store = Store(":memory:")
        phones = [f"+7999000{i:04d}" for i in range(5)]

        async def checker(phone: str, name: str):
            if phone.endswith("0003"):
                return None, "нет в Telegram"
            return "100" + phone[-4:], "ok"

        stats = await screen_pairs(
            [{"phone": p, "name": ""} for p in phones],
            store=store,
            checker=checker,
            daily=2,
            manager_id="anna",
            sent_today=0,
        )
        assert stats["in_tg"] == 4
        assert stats["missing"] == 1
        assert sum(stats["days"].values()) == 4
        assert max(stats["days"].values()) <= 2
        due = store.list_outreach_batch(limit=10, manager_id="anna")
        assert len(due) == 2
        from bot.store import _moscow_today
        today = _moscow_today()
        assert all((r.get("send_on") or "") <= today for r in due)
        missing = store.contact_by_phone("[REDACTED]")
        assert missing and missing["status"] == "skipped"

    asyncio.run(run())


if __name__ == "__main__":
    test_parse_drops_own_and_keeps_name()
    test_days_respect_limit()
    test_screen_splits_and_hides_future_from_today()
    print("screen ok")
