# -*- coding: utf-8 -*-
"""Regression: эталонный диалог Iya (chat 481263991, 30.09.2026, data/ideal_dialog_1.txt).

Реплеим реплики гостя через smart.smart_reply с фейковым LLM (хук возвращает JSON,
который реально дала модель) + детерминированный путь («Спасибо!» → rule/thanks).
Проверяем поведение, а не конкретные квартиры: порядок вопросов, отсутствие дублей,
вежливый тон, отсутствие преждевременного хэндоффа и корректный хэндофф при выборе.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["SMART_BOT"] = "1"

GREETING = ("Добрый вечер, Iya! Пишем из Home24. Спасибо, что ранее жили у нас! Если планируете снова "
            "приехать, подскажите, пожалуйста, удобные даты — подберём для Вас комфортную квартиру.")

# (реплика гостя, JSON фейкового LLM — как у реальной модели в эталоне; None = LLM не должен понадобиться)
TURNS = [
    ("Здравствуйте! Да,интересует октябрь с 1 по 5 число",
     {"intent": "looking", "slots": {"dates": "с 1 по 5 октября", "returning": "да"},
      "messages": ["Отлично! На каких условиях планируете остановиться? Например, сколько человек "
                   "и что важно: район, парковка, детская кроватка?"],
      "ask_next": "guests"}),
    ("3 человека,центр,бесплатная парковка",
     {"intent": "looking", "slots": {"guests": "3", "district": "центр", "parking": "бесплатная"},
      "messages": ["Хорошо, с 1 по 5 октября, 3 человека, центр. Парковка зависит от дома: где-то двор, "
                   "где-то городская рядом — уточню по выбранной квартире."],
      "ask_next": "pick", "attach_offers": True}),
    ("Спасибо!", None),
]

_Q_PATTERNS = {
    "dates": r"как\w* дат|удобные даты|когда планируете",
    "guests": r"сколько (будет )?(человек|гост)|сколько вас",
    "district": r"какой район|район удобнее",
    "returning": r"были у нас|впервые",
}


def _fresh_sess():
    return {"name": "Iya", "step": "await_dates", "dates": "", "guests": "", "district": "",
            "returning": "да", "favorite": "", "handed_off": 0,
            "context": {"outreach": True, "greeted": True, "smart": True}}


def _turn(sess, history, text, hook_json, calls):
    from bot import smart
    from bot.config import get_settings
    from bot.engine import Engine

    async def hook(system, messages, **kw):
        calls.append(system)
        hj = hook_json or {"intent": "chitchat", "slots": {}, "messages": ["Пожалуйста!"], "ask_next": "none"}
        return json.dumps(hj, ensure_ascii=False), "mock"

    smart.set_understand_hook(hook)
    try:
        s = get_settings()
        res = asyncio.run(smart.smart_reply(s, Engine(s), sess, text, history))
    finally:
        smart.set_understand_hook(None)
    assert res is not None, f"smart_reply fell back to script for {text!r}"
    msgs, buttons, upd, esc = res
    history.append({"role": "guest", "text": text})
    history.extend({"role": "bot", "text": m} for m in msgs)
    upd = dict(upd)
    ctx = upd.pop("context", None)
    sess.update(upd)
    if ctx is not None:
        sess["context"] = ctx
    return msgs, buttons, upd, esc


def _replay():
    sess, history, calls, out = _fresh_sess(), [{"role": "bot", "text": GREETING}], [], []
    for text, hj in TURNS:
        out.append((text, dict(sess)) + _turn(sess, history, text, hj, calls) + (len(calls),))
    return sess, history, calls, out


def _asked(msg: str) -> set[str]:
    low = msg.lower()
    return {k for k, p in _Q_PATTERNS.items() if re.search(p, low)}


def test_prompt_has_marked_example_and_reaches_llm():
    p = (ROOT / "bot" / "smart_prompt.txt").read_text(encoding="utf-8")
    assert "ЭТАЛОННЫЙ ДИАЛОГ №1 — ПРИМЕР СТИЛЯ" in p and "=== конец примера ===" in p
    assert "адаптируйся к каждому клиенту, не копируй фразы и факты" in p
    # пример стоит после JSON-схемы и не ломает её
    assert p.index('"ask_next": "dates"') < p.index("ЭТАЛОННЫЙ ДИАЛОГ")
    _s, _h, calls, _o = _replay()
    assert calls and all("ЭТАЛОННЫЙ ДИАЛОГ №1" in c for c in calls)


def test_turn1_dates_then_ask_guests_once():
    _s, _h, _c, out = _replay()
    _text, _before, msgs, buttons, upd, esc, _n = out[0]
    blob = " ".join(msgs)
    assert not esc and not upd.get("handed_off")
    assert upd.get("dates") == "с 1 по 5 октября"
    assert upd.get("step") == "await_guests"
    # одна реплика, один вопрос по сути (в эталоне — «На каких условиях…? Например, сколько человек…?»)
    assert len(msgs) == 1 and blob.rstrip().endswith("?") and blob.count("?") <= 2, msgs
    assert "человек" in blob.lower()  # следующий вопрос — состав гостей
    assert "dates" not in _asked(blob) and "returning" not in _asked(blob), blob
    assert buttons and any("человек" in b[0] for b in buttons)


def test_turn2_everything_known_gives_offers_no_reask():
    _s, _h, _c, out = _replay()
    _text, _before, msgs, _b, upd, esc, _n = out[1]
    blob = " ".join(msgs)
    assert not esc and not upd.get("handed_off")
    assert upd.get("guests") == "3" and upd.get("district") == "центр"
    assert upd.get("step") == "await_returning"
    assert msgs[0].startswith("Хорошо") and "с 1 по 5 октября" in msgs[0]
    assert len(msgs) <= 2, msgs
    offers = (_s.get("context") or {}).get("offers") or []
    assert len(offers) == 3
    assert all(f"{i})" in msgs[-1] for i in (1, 2, 3))
    assert re.search(r"номер", msgs[-1])  # следующий шаг — выбрать вариант
    assert not _asked(blob), blob  # ни дат, ни гостей, ни района, ни «впервые»
    assert "бесплатн" not in blob.lower() and "уточню" in blob.lower()  # парковку не обещаем


def test_turn3_thanks_deterministic_no_push():
    _s, _h, _c, out = _replay()
    _text, before, msgs, _b, upd, esc, ncalls = out[2]
    blob = " ".join(msgs)
    assert ncalls == out[1][-1], "«Спасибо!» должно идти детерминированным путём без LLM"
    assert (_s.get("context") or {}).get("reply_path") == "smart:rule/thanks"
    assert msgs and msgs[0].startswith("Пожалуйста")
    assert "?" not in blob and "1)" not in blob
    assert not esc and not upd.get("handed_off")
    assert _s["step"] == before["step"] == "await_returning"
    assert len((_s.get("context") or {}).get("offers") or []) == 3


def test_no_duplicate_questions_and_respectful_tone():
    _s, history, _c, _o = _replay()
    bot_msgs = [h["text"] for h in history if h["role"] == "bot"][1:]
    seen: set[str] = set()
    for m in bot_msgs:
        a = _asked(m)
        assert not (a & seen), f"повторный вопрос {a & seen}: {m}"
        seen |= a
        low = f" {m.lower()} "
        assert not re.search(r"\b(ты|тебя|тебе|твой|твоя|твои)\b", low), m
        assert "Клиент" not in m and not re.match(r"(Записала|Зафиксировала|Приняла):", m)
        assert m.count("🙂") <= 1
        assert not re.search(r"(?i)^(здравствуйте|добрый)", m), "повторное приветствие mid-dialog"
    assert len(bot_msgs) == 4


def test_handoff_only_when_guest_picks():
    # в эталоне хэндоффа нет: гость не выбирал вариант → менеджера не зовём
    s, history, _c, out = _replay()
    assert all(not o[5] for o in out) and not s.get("handed_off")
    # продолжение по текущему флоу: выбор варианта → хэндофф с названием, без переспроса
    offers = list(s["context"]["offers"])
    msgs, _b, upd, esc = _turn(s, history, "давайте 2",
                               {"intent": "looking", "slots": {"favorite": offers[1]}, "messages": [], "ask_next": "book"}, [])
    blob = " ".join(msgs)
    assert esc and s["step"] == "handed_off"
    assert offers[1] in blob
    assert "впервые" not in blob and "1)" not in blob


if __name__ == "__main__":
    for k, v in sorted(dict(globals()).items()):
        if k.startswith("test_") and callable(v):
            v()
            print("ok", k)
