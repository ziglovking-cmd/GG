#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline eval: sample-диалоги через smart brain с реальными ключами + pacing.

Usage:
  python scripts/eval_smart_dialogs.py
  SMART_BOT=1 python scripts/eval_smart_dialogs.py --limit 5 --pace 12

Печатает guest→bot и reply_path (smart:model | script) на каждый ход.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
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
os.environ.setdefault("SMART_BOT", "1")

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine
from bot.llm import load_providers
from bot.phrases import greeting_msgs
from bot.smart import set_understand_hook

set_understand_hook(None)

DIALOGS: list[tuple[str, list[str]]] = [
    (
        "Multi-intent + pets",
        [
            "__OUTREACH__",
            "Здравствуйте! Да,планы есть на январь с 1 по 7 число,3 человека,центр, можно с собакой?",
            "не 3 а 4 человека",
            "давайте 1, мы впервые",
        ],
    ),
    (
        "Outreach looking",
        [
            "__OUTREACH__",
            "Здравствуйте! Да, хотели бы снять квартиру",
            "ближайшие выходные, двое, поспокойнее",
        ],
    ),
    (
        "Price + handoff",
        [
            "Ищу квартиру на 12-14 марта, 2 гостя, центр",
            "сколько будет стоить?",
        ],
    ),
    (
        "Kids + calm area",
        [
            "на выходные нас двое и ребёнок, тихий район",
            "а кроватка детская есть?",
        ],
    ),
    (
        "Rude / off-topic",
        [
            "привет",
            "какая погода",
            "вы чё тупите",
            "ладно, на пятницу-воскресенье двое центр",
        ],
    ),
]


def _summarize_cards(text: str) -> str:
    """Карточки → коротко имена + area/metro."""
    if "1)" not in text and "Почему подходит" not in text:
        return text
    names = re.findall(r"(?m)^\d+\)\s*«([^»]+)»\s*·\s*([^\n]+)", text)
    if not names:
        names = re.findall(r"(?m)^\d+\)\s*«([^»]+)»", text)
        return "CARDS: " + ", ".join(f"«{n}»" for n in names) if names else text[:200]
    bits = [
        f"«{n}» ({a.strip()})"
        for n, a in names
    ]
    lead = text.split("1)")[0].strip()
    foot = ""
    if "впервые" in text.lower() or "были у нас" in text.lower():
        foot = " [+ returning?]"
    elif "номер" in text.lower():
        foot = " [+ pick?]"
    return (lead + "\n" if lead else "") + "CARDS: " + "; ".join(bits) + foot


async def _run_dialog(
    title: str,
    lines: list[str],
    *,
    pace: float,
    stats: dict[str, int],
) -> None:
    s = get_settings()
    e = Engine(s)
    sess: dict = {
        "name": "Мария",
        "step": "greeting",
        "dates": "",
        "guests": "",
        "district": "",
        "returning": "",
        "favorite": "",
        "handed_off": 0,
        "context": {},
    }
    history: list[dict] = []
    print("\n" + "=" * 60)
    print(f"DIALOG: {title}")
    print("=" * 60)
    for line in lines:
        if line == "__OUTREACH__":
            msgs, upd = greeting_msgs(sess, outreach=True)
            sess.update(upd)
            for m in msgs:
                print(f"BOT (outreach): {m}")
                history.append({"role": "bot", "text": m})
            continue
        print(f"GUEST: {line}")
        if sess.get("handed_off"):
            print("BOT: (silent — handed_off)")
            continue
        if pace > 0:
            await asyncio.sleep(pace)
        t0 = time.time()
        msgs, buttons, upd, esc = await reply(s, e, sess, line, history)
        for k, v in upd.items():
            if k == "context":
                sess["context"] = v
            elif v is not None and v != "":
                sess[k] = v
        if esc:
            sess["handed_off"] = 1
        path = str((sess.get("context") or {}).get("reply_path") or "?")
        if path.startswith("smart"):
            stats["smart"] += 1
        elif path == "script":
            stats["script"] += 1
        else:
            stats["other"] += 1
        history.append({"role": "guest", "text": line})
        for m in msgs:
            shown = _summarize_cards(m)
            print(f"BOT: {shown}")
            history.append({"role": "bot", "text": m})
        print(
            f"  · path={path}  {time.time()-t0:.1f}s  "
            f"step={sess.get('step')} esc={esc} "
            f"slots={{d:{sess.get('dates')!r} g:{sess.get('guests')!r} r:{sess.get('district')!r}}}"
        )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="только первые N диалогов")
    ap.add_argument(
        "--pace",
        type=float,
        default=float(os.getenv("EVAL_PACE_SEC") or "12"),
        help="пауза между LLM-ходами (сек), 0=без паузы",
    )
    args = ap.parse_args()
    prov = load_providers(role="understand")
    if not prov:
        print("No AI providers configured. Set GROQ_API_KEY (или AI1_API_KEY / AI2_API_KEY) in .env")
        sys.exit(2)
    print("Providers:", ", ".join(f"{p.name}:{p.model}" for p in prov))
    print(f"Pace: {args.pace}s between guest turns")
    dialogs = DIALOGS[: args.limit] if args.limit else DIALOGS
    stats = {"smart": 0, "script": 0, "other": 0}
    for title, lines in dialogs:
        try:
            await _run_dialog(title, lines, pace=args.pace, stats=stats)
        except Exception as e:
            print(f"ERROR in {title}: {e}")
    total = stats["smart"] + stats["script"] + stats["other"]
    print("\n" + "=" * 60)
    print(
        f"PATH STATS: smart={stats['smart']} script={stats['script']} "
        f"other={stats['other']} total={total}"
    )
    if total:
        print(
            f"LLM turns: {100*stats['smart']/total:.0f}%  "
            f"script turns: {100*stats['script']/total:.0f}%"
        )
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
