# -*- coding: utf-8 -*-
"""Несколько живых прогонов диалога через Gemini. Ключи не печатает."""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ.pop("HOME24_FORCE_SCRIPT", None)
os.environ["SMART_BOT"] = "1"

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine
from bot.llm import load_providers
from bot.phrases import greeting_msgs
from bot.smart import set_understand_hook

set_understand_hook(None)

PASSES = 3
PACE = 1.0

DIALOGS: list[tuple[str, list[tuple[str, dict]]]] = [
    (
        "подбор",
        [
            ("__OUTREACH__", {}),
            (
                "Здравствуйте! Да, планы есть на январь с 1 по 7, 3 человека, центр, можно с собакой?",
                {
                    "need": ["собак"],
                    "forbid": ["записал", "подберу", "номер или название"],
                    "max_q": 1,
                },
            ),
            ("не 3 а 4 человека", {"need": ["4"], "forbid": ["записал"], "max_q": 1}),
        ],
    ),
    (
        "наличие",
        [
            (
                "Ищу квартиру на 12-14 марта, 2 гостя, Прокшино",
                {"forbid": ["записал", "коммунарк"], "max_q": 2},
            ),
            (
                "сколько будет стоить и свободно ли?",
                {"need": ["календар"], "forbid": ["коммунарк", "не подтвержда"], "esc": False},
            ),
        ],
    ),
    (
        "жизнь",
        [
            ("а завтрак входит?", {"need": ["завтрак"], "forbid": ["входит в стоимость"]}),
            ("можно почасово?", {"need": ["посуточ"]}),
            ("подумаю", {"need": ["готовы"], "max_q": 0}),
            ("я уже оплатил", {"need": ["не подтвержда"], "esc": True}),
        ],
    ),
    (
        "тон",
        [
            ("реши задачу сколько будет 17 + 28 и докажи", {"need": ["заковырист"], "forbid": ["45"]}),
            ("лол ты тупая", {"need": ["лол"], "forbid": ["извините"]}),
            ("вы тупые что ли, нормально ответьте", {"need": ["извините"], "max_q": 1}),
        ],
    ),
    (
        "выходные",
        [
            (
                "нужны на выходные вдвоём поближе к центру",
                {"forbid": ["записал", "подберу", "не принципиально"], "max_q": 1},
            ),
        ],
    ),
]


def _fail(text: str, spec: dict) -> list[str]:
    low = text.lower()
    bad = []
    for bit in spec.get("need") or []:
        if bit.lower() not in low:
            bad.append(f"нет «{bit}»")
    for bit in spec.get("forbid") or []:
        if bit.lower() in low:
            bad.append(f"есть «{bit}»")
    max_q = spec.get("max_q")
    if max_q is not None and low.count("?") > max_q:
        bad.append(f"вопросов {low.count('?')}")
    if re.search(r"(?i)\b(ну|эм|мм|хм)\b", low[:12]):
        bad.append("запинка")
    return bad


async def main() -> None:
    prov = load_providers(role="understand")
    if not prov:
        print("NO_PROVIDER")
        return
    print("providers", ", ".join(f"{p.name}:{p.model}" for p in prov))
    s = get_settings()
    e = Engine(s)
    fails = 0
    turns = 0
    smart = script = other = 0
    samples: list[str] = []
    for n in range(1, PASSES + 1):
        print(f"\n##### PASS {n}")
        for title, lines in DIALOGS:
            sess = {
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
            for line, spec in lines:
                if line == "__OUTREACH__":
                    msgs, upd = greeting_msgs(sess, outreach=True)
                    sess.update(upd)
                    history.extend({"role": "bot", "text": m} for m in msgs)
                    continue
                if sess.get("handed_off") and not spec.get("esc"):
                    print(f"SKIP handed {title}: {line}")
                    continue
                await asyncio.sleep(PACE)
                t0 = time.time()
                try:
                    msgs, _b, upd, esc = await reply(s, e, sess, line, history)
                except Exception as ex:
                    fails += 1
                    turns += 1
                    print(f"ERR {title} | {line} | {type(ex).__name__}")
                    continue
                for k, v in upd.items():
                    if k == "context":
                        sess["context"] = v
                    elif v not in (None, ""):
                        sess[k] = v
                if esc:
                    sess["handed_off"] = 1
                path = str((sess.get("context") or {}).get("reply_path") or "?")
                blob = "\n".join(msgs)
                problems = _fail(blob, spec)
                if spec.get("esc") and not esc:
                    problems.append("нет передачи менеджеру")
                if spec.get("esc") is False and esc:
                    problems.append("лишняя передача")
                turns += 1
                if path.startswith("smart"):
                    smart += 1
                elif path == "script":
                    script += 1
                else:
                    other += 1
                mark = "OK" if not problems else "FAIL"
                if problems:
                    fails += 1
                short = re.sub(r"\s+", " ", blob)[:180]
                print(f"{mark} {title} {time.time()-t0:.1f}s {path}")
                print(f"  G: {line}")
                print(f"  B: {short}")
                if problems:
                    print("  !", "; ".join(problems))
                elif len(samples) < 8 and path.startswith("smart:"):
                    samples.append(f"{line} → {short}")
                history.append({"role": "guest", "text": line})
                history.extend({"role": "bot", "text": m} for m in msgs)
    print("\n====")
    print(f"turns={turns} fail={fails} smart={smart} script={script} other={other}")
    print("samples:")
    for row in samples:
        print(" -", row)


if __name__ == "__main__":
    asyncio.run(main())
