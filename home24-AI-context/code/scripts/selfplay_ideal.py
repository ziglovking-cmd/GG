#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Самопрогон: бот играет сам с собой по эталонному сценарию + авто-гость.

Без Telegram. Печатает ход и score vs идеальный менеджер.
Usage:
  PYTHONPATH=. python scripts/selfplay_ideal.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

os.environ.pop("HOME24_FORCE_SCRIPT", None)
os.environ["SMART_BOT"] = "1"
os.environ.setdefault("FACT_GUARD", "1")

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine
from bot.phrases import greeting_msgs
from bot.smart import set_understand_hook
from bot.travelline import Stay, set_search_hook

set_understand_hook(None)


def _hook_stays(adults, dates, nights):
    return [
        Stay("1", "Чехов", "Балакиревский пер, 23", 5500, 22000, 1),
        Stay("2", "Шаляпин", "Балакиревский пер, 23", 5200, 20800, 1),
        Stay("3", "Дягилев", "Балакиревский пер, 23", 5000, 20000, 1),
    ]


# Эталон: фиксированные реплики гостя
IDEAL_GUEST = [
    "Здравствуйте! Да, интересует октябрь с 1 по 5 число",
    "3 человека, центр, бесплатная парковка",
    "Спасибо!",
]

# После рассылки «рассказать?» — живой сценарий
OUTREACH_GUEST = [
    "Здравствуйте! Да",
    "с 20 по 24 ноября",
    "трое, центр",
    "1",
    "Спасибо!",
]


def _score_turn(guest: str, bot: str, sess: dict, *, expect: str) -> list[str]:
    bad: list[str] = []
    low = (bot or "").lower()
    if "будем ждать" in low:
        bad.append("закрыл «Будем ждать!»")
    if "записал" in low or "данный" in low:
        bad.append("канцелярит")
    if "«вариант»" in bot or "«покажите»" in low:
        bad.append("fact_guard сломал имя")
    if expect == "conditions":
        if not re.search(r"(?i)услови|сколько\s+(человек|вас)|что\s+важно", low):
            bad.append("нет вопроса про условия/гостей после дат")
        if re.search(r"(?i)на какие даты|удобные даты", low) and "октябр" not in low:
            bad.append("переспросил даты")
    if expect == "cards_or_confirm":
        if not (re.search(r"(?m)^1\)", bot) or "уточню" in low or "парковк" in low):
            bad.append("нет подтверждения/карточек")
        if "бесплатн" in low and "парков" in low and "уточню" not in low:
            bad.append("обещал бесплатную парковку")
    if expect == "thanks":
        if not re.search(r"(?i)пожалуйста", low):
            bad.append("на «спасибо» не «пожалуйста»")
        if "?" in bot:
            bad.append("после спасибо снова вопрос")
    if expect == "pick_ok":
        if not re.search(r"(?i)отличн|выбор|дягилев|чехов|шаляпин|«", low):
            bad.append("нет подтверждения выбора квартиры")
    if expect == "dates_ask":
        if not re.search(r"(?i)дат", low):
            bad.append("после «да» на оффер нет вопроса про даты")
    return bad


async def _play(title: str, guest_lines: list[str], *, outreach: bool) -> list[str]:
    s = get_settings()
    e = Engine(s)
    sess: dict = {
        "name": "Ия",
        "step": "greeting",
        "dates": "",
        "guests": "",
        "district": "",
        "returning": "да",
        "favorite": "",
        "handed_off": 0,
        "context": {},
    }
    history: list[dict] = []
    fails: list[str] = []
    print("\n" + "=" * 64)
    print(f"SELFPLAY: {title}")
    print("=" * 64)

    set_search_hook(_hook_stays)
    try:
        if outreach:
            msgs, upd = greeting_msgs(dict(sess), outreach=True)
            sess.update(upd)
            for m in msgs:
                print(f"BOT: {m}")
                history.append({"role": "bot", "text": m})
        else:
            greet = (
                "Добрый вечер, Ия! Пишем из Home24. Спасибо, что ранее жили у нас! "
                "Если планируете снова приехать, подскажите удобные даты — подберу квартиру."
            )
            print(f"BOT: {greet}")
            history.append({"role": "bot", "text": greet})
            sess.update({"step": "await_dates", "context": {"outreach": True, "greeted": True}})

        expects = []
        if outreach:
            # да → даты; даты → условия; гости+район → карточки; номер → подтверждение; спасибо → пожалуйста
            expects = ["dates_ask", "conditions", "cards_or_confirm", "pick_ok", "thanks"]
        else:
            expects = ["conditions", "cards_or_confirm", "thanks"]

        for i, line in enumerate(guest_lines):
            print(f"GUEST: {line}")
            msgs, _btns, upd, esc = await reply(s, e, sess, line, history)
            for k, v in upd.items():
                if k == "context":
                    sess["context"] = v
                elif v is not None and v != "":
                    sess[k] = v
            if esc:
                sess["handed_off"] = 1
            history.append({"role": "guest", "text": line})
            blob = "\n".join(msgs)
            for m in msgs:
                shown = m if len(m) < 320 else m[:300] + "…"
                print(f"BOT: {shown}")
                history.append({"role": "bot", "text": m})
            path = str((sess.get("context") or {}).get("reply_path") or "?")
            print(
                f"  · path={path} step={sess.get('step')} "
                f"d={sess.get('dates')!r} g={sess.get('guests')!r} r={sess.get('district')!r}"
            )
            exp = expects[i] if i < len(expects) else ""
            if exp:
                for b in _score_turn(line, blob, sess, expect=exp):
                    fails.append(f"[{title} turn{i+1}] {b}: {blob[:120]!r}")
                    print(f"  ✗ {b}")
            if not msgs:
                fails.append(f"[{title} turn{i+1}] пустой ответ")
                print("  ✗ пустой ответ")
    finally:
        set_search_hook(None)

    if not fails:
        print(f"✓ {title}: OK")
    else:
        print(f"✗ {title}: {len(fails)} issues")
    return fails


async def main() -> int:
    all_fails: list[str] = []
    all_fails += await _play("ideal_dialog", IDEAL_GUEST, outreach=False)
    all_fails += await _play("outreach_then_book", OUTREACH_GUEST, outreach=True)
    print("\n" + "=" * 64)
    if all_fails:
        print(f"FAILED {len(all_fails)}")
        for f in all_fails:
            print(" -", f)
        return 1
    print("ALL SELFPLAY PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
