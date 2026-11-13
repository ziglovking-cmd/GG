#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прогон проверочных диалогов Home24 (tests/dialogs_home24.py).

На ПК с живым ИИ (Groq из .env):
    python scripts/eval_home24_dialogs.py
    python scripts/eval_home24_dialogs.py --limit 10 --pace 8
Без ИИ, только правила и скрипт:
    python scripts/eval_home24_dialogs.py --offline

Результат: в консоли «гость → бот» + замечания, и файл data/dialog_report.md
(его можно прислать на разбор). Telegram при этом не трогается, гостям ничего не уходит.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

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

from bot import phrases as P  # noqa: E402
from bot import smart as smart_mod  # noqa: E402
from bot.ai import reply  # noqa: E402
from bot.config import get_settings  # noqa: E402
from bot.engine import Engine  # noqa: E402
from tests.dialogs_home24 import DIALOGS, check_turn  # noqa: E402


def new_session() -> dict[str, Any]:
    return {
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


async def run_dialog(dialog: dict[str, Any], *, pace: float = 0.0) -> dict[str, Any]:
    s = get_settings()
    e = Engine(s)
    sess = new_session()
    history: list[dict[str, str]] = []
    kind, idx = dialog["start"]
    out_turns: list[dict[str, Any]] = []
    opener: list[str] = []
    if kind == "outreach":
        P._GREET_RR, P._GREET_RECENT = int(idx) - 1, []
        opener, upd = P.greeting_msgs(sess, outreach=True)
        sess.update(upd)
        sess["step"] = "await_intent"
        history += [{"role": "bot", "text": m} for m in opener]
    prev_bot = list(opener)
    first_bot_turn = kind != "outreach"
    for guest, checks in dialog["turns"]:
        before = dict(sess)
        if pace > 0:
            await asyncio.sleep(pace)
        t0 = time.time()
        if sess.get("handed_off"):
            msgs, esc, path = [], True, "handed_off"
        else:
            msgs, _buttons, upd, esc = await reply(s, e, sess, guest, history)
            from bot.reply_guard import smooth_speech

            msgs = [m for m in (smooth_speech(x) for x in msgs) if m]  # как перед отправкой в Telegram
            for k, v in upd.items():
                if k == "context":
                    sess["context"] = v
                elif v is not None and v != "":
                    sess[k] = v
            if esc:
                sess["handed_off"] = 1
            path = str((upd.get("context") or {}).get("reply_path") or "script")
        problems = check_turn(
            guest,
            msgs,
            esc,
            checks,
            prev_bot=prev_bot,
            sess_before=before,
            first_bot_turn=first_bot_turn,
        )
        out_turns.append(
            {
                "guest": guest,
                "bot": msgs,
                "esc": esc,
                "path": path,
                "problems": problems,
                "sec": time.time() - t0,
                "slots": {**{k: sess.get(k) for k in ("dates", "guests", "district", "returning", "step")}, "offers": (sess.get("context") or {}).get("offers")},
            }
        )
        history.append({"role": "guest", "text": guest})
        history += [{"role": "bot", "text": m} for m in msgs]
        prev_bot = list(msgs) or prev_bot
        first_bot_turn = False
    return {"title": dialog["title"], "opener": opener, "turns": out_turns}


async def run_all(*, limit: int = 0, pace: float = 0.0) -> list[dict[str, Any]]:
    dialogs = DIALOGS[:limit] if limit else DIALOGS
    return [await run_dialog(d, pace=pace) for d in dialogs]


def report_md(results: list[dict[str, Any]], *, mode: str) -> str:
    bad = sum(1 for r in results for t in r["turns"] if t["problems"])
    total = sum(len(r["turns"]) for r in results)
    lines = [f"# Проверочные диалоги Home24 ({mode})", "", f"Ходов: {total}, с замечаниями: {bad}", ""]
    for n, r in enumerate(results, 1):
        lines.append(f"## {n}. {r['title']}")
        for m in r["opener"]:
            lines.append(f"- **Бот (рассылка):** {m}")
        for t in r["turns"]:
            lines.append(f"- **Гость:** {t['guest']}")
            bot = " / ".join(x.replace("\n", " ") for x in t["bot"]) or "(молчит)"
            tag = " → менеджеру" if t["esc"] else ""
            lines.append(f"- **Бот:** {bot}{tag}  `{t['path']}`")
            for p in t["problems"]:
                lines.append(f"  - ⚠ {p}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="без ИИ: только правила и скрипт")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pace", type=float, default=float(os.getenv("EVAL_PACE_SEC") or "0"))
    ap.add_argument("--out", default="data/dialog_report.md")
    args = ap.parse_args()
    if args.offline:
        async def _no_llm(system: str, messages: list[dict[str, str]]):
            return None

        smart_mod.set_understand_hook(_no_llm)
        import bot.ai as ai_mod

        async def _none(*a, **k):
            return None

        ai_mod.chat_completion = _none
        smart_mod.chat_completion = _none
        try:
            import bot.travelline as tl_mod

            def _no_tl(*a, **k):
                return None

            tl_mod.availability_reply = _no_tl  # без сети: наличие TravelLine не спрашиваем
        except Exception:
            pass
        from scripts.test_catalog import use_test_catalog_if_missing

        mode = "без ИИ, " + use_test_catalog_if_missing()
    else:
        from bot.llm import load_providers

        prov = load_providers(role="understand")
        if not prov:
            print("Нет ключей ИИ в .env (GROQ_API_KEY / AI1_API_KEY). Запустите с --offline.")
            sys.exit(2)
        mode = "ИИ: " + ", ".join(f"{p.name}:{p.model}" for p in prov)
        # бесплатный Groq ~8000 токенов/мин — по умолчанию пауза между ходами
        if args.pace == 0 and any("groq" in p.name.lower() for p in prov):
            args.pace = 8.0
    results = asyncio.run(run_all(limit=args.limit, pace=args.pace))
    md = report_md(results, mode=mode)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    for r in results:
        for t in r["turns"]:
            mark = "✗" if t["problems"] else "✓"
            print(f"{mark} {r['title']} | {t['guest']}\n    → {' / '.join(t['bot']) or '(молчит)'}  [{t['path']}]")
            for p in t["problems"]:
                print(f"      ⚠ {p}")
    bad = sum(1 for r in results for t in r["turns"] if t["problems"])
    print(f"\nОтчёт: {out}  (замечаний: {bad})")


if __name__ == "__main__":
    main()
