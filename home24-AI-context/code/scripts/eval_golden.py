#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прогон бота по эталонным диалогам training/dialogs_home24.jsonl.

    python scripts/eval_golden.py --offline            # правила и скрипт, без ИИ (быстро, все 1200)
    python scripts/eval_golden.py --limit 100          # с Groq (пауза между ходами, ~15 мин на 100)

Гость говорит реплики из эталона, бот отвечает сам. Проверяется не дословное совпадение,
а поведение: не переспрашивает известное, передаёт менеджеру когда надо (и только тогда),
отвечает на вопрос по теме, уважает стоп, не пишет роботских фраз.
Отчёт: data/golden_report.md
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import re
import sys
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

import logging  # noqa: E402

logging.disable(logging.CRITICAL)

from bot import phrases as P  # noqa: E402
from bot import smart as smart_mod  # noqa: E402
from bot.ai import reply  # noqa: E402
from bot.config import get_settings  # noqa: E402
from bot.engine import Engine  # noqa: E402
from bot.reply_guard import smooth_speech  # noqa: E402
from tests.dialogs_home24 import ASK_DATES, ASK_DISTRICT, ASK_GUESTS, ROBOT_PHRASES  # noqa: E402

TOPIC_RX = {
    "питомцы": r"(?i)питом|собак|кот|животн",
    "парковка": r"(?i)парков",
    "заезд": r"(?i)15:00|заезд",
    "выезд": r"(?i)12:00|выезд",
    "вайфай": r"(?i)вайфай|интернет|wi-?fi",
    "курение": r"(?i)кур",
    "ранний заезд": r"(?i)ранн|раньше|пораньше|время",
    "поздний выезд": r"(?i)поздн|позже",
    "кухня": r"(?i)кухн|посуд|готов",
    "залог": r"(?i)залог|депозит",
    "оплата": r"(?i)оплат|карт|перевод",
    "ключи": r"(?i)ключ|код|без встречи",
    "уборка": r"(?i)уборк|бель|чист",
    "дети": r"(?i)дет|ребён|кроват",
    "кофе": r"(?i)кофе",
    "завтрак": r"(?i)завтрак",
    "трансфер": r"(?i)трансфер|такси|аэроэкспресс",
    "паспорт": r"(?i)паспорт",
    "ночь": r"(?i)ночь|ночью|код",
    "баллы": r"(?i)балл|бонус",
    "скидка": r"(?i)промокод|скидк|комисси|балл",
    "по часам": r"(?i)посуточно|по часам",
    "бассейн": r"(?i)бассейн|спа",
    "вечеринка": r"(?i)вечеринк|шум|тихо",
    "адрес Скандинавии": r"Фитарёвская|Коммунарка",
    "адрес Дюма": r"Ленинский",
    "адрес Чехова": r"Балакиревский|Бауманская",
}
STOP_RX = r"(?i)не пишу|не беспокою|убрала|больше не побеспокою|извините"


def new_session() -> dict[str, Any]:
    return {"name": "Гость", "step": "greeting", "dates": "", "guests": "", "district": "",
            "returning": "", "favorite": "", "handed_off": 0, "context": {}}


def _greeting_idx(letter: str) -> int:
    for i, tmpl in enumerate(P.GREETINGS):
        tail = tmpl[0].split("{stay}")[-1].strip()[:40]
        if tail and tail in letter:
            return i
    return 0


async def run_one(dlg: dict[str, Any], *, pace: float = 0.0) -> dict[str, Any]:
    s = get_settings()
    e = Engine(s)
    sess = new_session()
    history: list[dict[str, str]] = []
    turns = dlg["turns"]
    i = 0
    if dlg["start"] == "outreach" and turns and turns[0]["role"] == "bot":
        idx = _greeting_idx(turns[0]["text"])
        P._GREET_RR, P._GREET_RECENT = idx - 1, []
        msgs, upd = P.greeting_msgs(sess, outreach=True)
        sess.update(upd)
        history += [{"role": "bot", "text": m} for m in msgs]
        i = 1
    out_turns = []
    prev_bot = [history[-1]["text"]] if history else []
    for t in turns[i:]:
        if t["role"] != "guest":
            continue
        exp = t.get("expect") or {}
        golden = []
        j = turns.index(t) + 1
        while j < len(turns) and turns[j]["role"] == "bot":
            golden.append(turns[j]["text"])
            j += 1
        before = dict(sess)
        if sess.get("handed_off"):
            out_turns.append({"guest": t["text"], "bot": [], "golden": golden, "problems": [], "skipped": True})
            continue
        if pace:
            await asyncio.sleep(pace)
        msgs, _b, upd, esc = await reply(s, e, sess, t["text"], history)
        msgs = [m for m in (smooth_speech(x) for x in msgs) if m]  # как main._guest_safe перед отправкой
        for k, v in upd.items():
            if k == "context":
                sess["context"] = v
            elif v not in (None, ""):
                sess[k] = v
        if esc:
            sess["handed_off"] = 1
        text = "\n".join(msgs)
        probs: list[str] = []
        if exp.get("esc") is True and not esc:
            probs.append("не передал менеджеру")
        golden_esc = any(P.HANDOFF_LINE in g or "подключу менеджера" in g or "передаю менеджеру" in g
                         or "передам менеджеру" in g or "передам администратору" in g for g in golden)
        if esc and exp.get("esc") is not True and not golden_esc:
            probs.append("лишняя передача менеджеру")
        if exp.get("stop") and not re.search(STOP_RX, text):
            probs.append("не принял стоп")
        known = set(exp.get("known_before") or [])
        if "dates" in known and re.search(ASK_DATES, text):
            probs.append("переспросил даты")
        if "guests" in known and re.search(ASK_GUESTS, text):
            probs.append("переспросил гостей")
        if "district" in known and re.search(ASK_DISTRICT, text) and "?" in text:
            probs.append("переспросил район")
        if exp.get("no_dates_question") and re.search(ASK_DATES, text):
            probs.append("спросил даты, хотя не надо")
        if exp.get("no_question") and "?" in text:
            probs.append("лишний вопрос после «спасибо»")
        topic = exp.get("topic")
        if topic in TOPIC_RX and not re.search(TOPIC_RX[topic], text):
            probs.append(f"не ответил про «{topic}»")
        if not text.strip() and not esc:
            probs.append("пустой ответ")
        for rx in ROBOT_PHRASES:
            if re.search(rx, text, flags=re.M):
                probs.append("роботская фраза")
                break
        if prev_bot and text and text.strip() == "\n".join(prev_bot).strip():
            probs.append("повтор прошлого ответа")
        out_turns.append({"guest": t["text"], "bot": msgs, "golden": golden, "esc": esc, "problems": probs,
                          "intent": exp.get("intent", ""), "before": {k: before.get(k) for k in ("dates", "guests", "district")}})
        history.append({"role": "guest", "text": t["text"]})
        history += [{"role": "bot", "text": m} for m in msgs]
        prev_bot = msgs or prev_bot
    return {"id": dlg["id"], "outcome": dlg["outcome"], "turns": out_turns}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pace", type=float, default=0.0)
    ap.add_argument("--file", default="training/dialogs_home24.jsonl")
    ap.add_argument("--out", default="data/golden_report.md")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    dialogs = [json.loads(x) for x in Path(args.file).read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.limit:
        dialogs = dialogs[: args.limit]
    if args.offline:
        async def _no(system, messages):
            return None

        smart_mod.set_understand_hook(_no)
        import bot.ai as ai_mod

        async def _no_llm(*a, **k):
            return None

        ai_mod.chat_completion = _no_llm  # крайний ответ ИИ тоже выключен — без сети и ожиданий
        smart_mod.chat_completion = _no_llm
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
            print("Нет ключей ИИ — запустите с --offline")
            sys.exit(2)
        mode = "ИИ: " + ", ".join(p.name for p in prov)
        if not args.pace and any("groq" in p.name.lower() for p in prov):
            args.pace = 8.0

    async def run_all():
        return [await run_one(d, pace=args.pace) for d in dialogs]

    results = asyncio.run(run_all())
    cnt = collections.Counter()
    turns_total = 0
    bad_turns = 0
    examples: dict[str, list[tuple[str, dict[str, Any]]]] = collections.defaultdict(list)
    for r in results:
        for t in r["turns"]:
            if t.get("skipped"):
                continue
            turns_total += 1
            if t["problems"]:
                bad_turns += 1
            for p in t["problems"]:
                cnt[p] += 1
                if len(examples[p]) < 6:
                    examples[p].append((r["id"], t))
    ok_dialogs = sum(1 for r in results if not any(t["problems"] for t in r["turns"]))
    lines = [f"# Бот против эталона ({mode})", "",
             f"Диалогов: {len(results)}, без замечаний: {ok_dialogs} ({100 * ok_dialogs // max(1, len(results))}%)",
             f"Ходов: {turns_total}, с замечаниями: {bad_turns} ({100 * bad_turns // max(1, turns_total)}%)", "",
             "| Замечание | Сколько |", "| --- | --- |"]
    lines += [f"| {p} | {n} |" for p, n in cnt.most_common()]
    for p, exs in examples.items():
        lines += ["", f"## {p}"]
        for did, t in exs:
            lines.append(f"- `{did}` Гость: {t['guest']}")
            lines.append(f"  - Бот: {' / '.join(t['bot']) or '(молчит)'}")
            lines.append(f"  - Эталон: {' / '.join(t['golden'])}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    print("\n".join(lines[:6 + len(cnt) + 1]))
    print(f"\nОтчёт: {out}")


if __name__ == "__main__":
    main()
