# -*- coding: utf-8 -*-
"""v9.3 — приветствие, диапазоны дней недели, area_label, 429 cooldown."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.ai import reply
from bot.catalog import (
    DEFAULT_PATH,
    _connect,
    _row_public,
    area_label,
    format_card,
)
from bot.config import get_settings
from bot.engine import Engine, parse_dates
from bot import llm as llm_mod
from bot import smart as smart_mod


def _j(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def _mock(payload: dict):
    async def _hook(system, messages, **_k):
        return _j(**payload), "mock/v9.3"

    return _hook


def test_weekday_ranges() -> None:
    assert parse_dates("на пятницу-воскресенье") == "с пятницы по воскресенье"
    assert parse_dates("пятницу-воскресенье") == "с пятницы по воскресенье"
    assert parse_dates("пятница-воскресенье двое центр") == "с пятницы по воскресенье"
    assert parse_dates("с пятницы по воскресенье") == "с пятницы по воскресенье"
    assert parse_dates("на выходные") == "ближайшие выходные"
    assert parse_dates("с 1 по 7 января") == "с 1 по 7 января"
    assert parse_dates("на пятницу") == "пятница"  # одиночный день ок


def test_area_label_not_bare_moscow() -> None:
    con = _connect(DEFAULT_PATH)
    assert con
    for name in ("Олимп", "Рим", "Монблан", "Россо", "Дзен", "Артледи"):
        r = con.execute("SELECT * FROM objects WHERE name=?", (name,)).fetchone()
        assert r, name
        o = _row_public(r)
        label = o.get("area_label") or area_label(o)
        assert label and label.lower() != "москва", (name, label)
        card = format_card(o)
        assert "«" + name + "» · Москва\n" not in card.replace("\r", "")
        # первая строка карточки — с конкретным лейблом
        first = card.split("\n")[0]
        assert "Москва" not in first or label.lower() != "москва", (name, first)
        assert label.split()[0].lower() in first.lower() or label.lower() in first.lower()
    con.close()


async def _sc_hello() -> None:
    smart_mod.set_understand_hook(
        _mock(
            {
                "intent": "chitchat",
                "messages": [
                    "Привет! Расскажите, когда и на сколько человек планируете заезд?"
                ],
                "ask_next": "dates",
            }
        )
    )
    try:
        sess = {
            "name": "Мария",
            "step": "await_intent",
            "dates": "",
            "guests": "",
            "district": "",
            "returning": "",
            "favorite": "",
            "handed_off": 0,
            "context": {},
        }
        msgs, _, upd, _ = await reply(
            get_settings(), Engine(get_settings()), sess, "привет", []
        )
    finally:
        smart_mod.set_understand_hook(None)
    assert len(msgs) == 1, msgs
    blob = msgs[0].lower()
    assert "здравствуйте" in blob
    assert "привет" not in blob
    assert blob.count("дат") + blob.count("когда") <= 2
    # один вопрос — не два про даты
    assert msgs[0].count("?") <= 1
    path = (upd.get("context") or {}).get("reply_path") or ""
    assert "hello" in path or path.startswith("smart")


def test_hello_one_bubble() -> None:
    asyncio.run(_sc_hello())


def test_rate_limit_long_cooldown() -> None:
    assert llm_mod._DEAD_TTL_RATE >= 600
    p = llm_mod.Provider(
        name="mini-smart",
        api_[REDACTED]
        base_url="https://example.com",
        model="mistral-small-latest",
    )
    llm_mod._DEAD.pop(p.key, None)
    llm_mod._mark_dead(p, "429 rate-limit", rate_limit=True)
    until = llm_mod._DEAD[p.key]
    assert until - time.time() > 500  # ~10 min
    llm_mod._DEAD.pop(p.key, None)


def test_all_v9_3() -> None:
    test_weekday_ranges()
    test_area_label_not_bare_moscow()
    test_hello_one_bubble()
    test_rate_limit_long_cooldown()
    print("ok v9.3 small fixes")


if __name__ == "__main__":
    test_all_v9_3()
