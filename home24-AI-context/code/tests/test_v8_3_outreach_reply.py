# -*- coding: utf-8 -*-
"""v8.3: после outreach — без повторного приветствия, без «Клиент», один ответ."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine, keyword_intent
from bot.phrases import (
    LOOKING_START,
    already_greeted,
    fill,
    greeting_msgs,
    inbound_hello_msgs,
    is_placeholder_name,
    real_first_name,
)


TRANSCRIPT_CLIENT = "Здравствуйте! Да, хотели бы снять квартиру"


def test_placeholder_names():
    for bad in (
        "Клиент",
        "клиент",
        "Client",
        "Гость",
        "Guest",
        "User",
        "",
        "[REDACTED]",
        "[REDACTED]",
        "Anna",
        "Анна",
    ):
        assert is_placeholder_name(bad), bad
        assert real_first_name(bad) == ""
    assert real_first_name("Мария") == "Мария"
    assert real_first_name("Иван Петров") == "Иван"


def test_fill_never_inserts_klient():
    sess = {"name": "Клиент"}
    out = fill("Здравствуйте{name_part}! Это Home24.", sess)
    assert "Клиент" not in out
    assert "Здравствуйте!" in out
    out2 = fill("{имя}, добрый день! Home24.", sess)
    assert "Клиент" not in out2
    assert not out2.lower().startswith("клиент")


def test_looking_beats_hello_intent():
    assert keyword_intent(TRANSCRIPT_CLIENT) == "looking"
    assert keyword_intent("Здравствуйте! Да, хотели бы снять квартиру") == "looking"
    assert keyword_intent("просто смотрю, здравствуйте") == "browsing"
    assert keyword_intent("Здравствуйте!") == "hello"


def test_outreach_marks_already_greeted():
    sess: dict = {"name": "Клиент"}
    msgs, upd = greeting_msgs(sess, outreach=True)
    assert upd["step"] == "await_intent"
    assert already_greeted({**sess, **upd})
    blob = "\n".join(msgs)
    assert "Клиент" not in blob


async def _outreach_then_rent() -> None:
    s = get_settings()
    e = Engine(s)
    sess: dict = {"name": "Клиент", "step": "greeting", "context": {}}
    # как в production: outreach opener
    g_msgs, g_btns, g_upd = e.greeting(sess, outreach=True)
    sess.update(g_upd)
    assert sess["step"] == "await_intent"
    assert already_greeted(sess)
    history = [{"role": "bot", "text": m} for m in g_msgs]

    msgs, buttons, updates, esc = await reply(
        s, e, sess, TRANSCRIPT_CLIENT, history
    )
    assert not esc
    assert len(msgs) == 1, msgs
    text = msgs[0]
    low = text.lower()
    assert "здравствуйте" not in low, text
    assert "клиент" not in low, text
    assert "home24" not in low or "подбер" in low  # не представляемся снова
    assert "дат" in low or "заезд" in low
    assert "гост" not in low and "человек" not in low
    assert updates.get("step") == "await_dates"
    # вопрос по датам, без канцелярского захода
    assert not text.startswith(
        ("Отлично", "Супер", "Хорошо", "С радостью", "Договорились", "Конечно")
    ), text


def test_outreach_transcript_one_reply_no_rehello():
    asyncio.run(_outreach_then_rent())


async def _fresh_inbound_no_name() -> None:
    s = get_settings()
    e = Engine(s)
    sess: dict = {"name": "", "step": "greeting", "context": {}}
    msgs, buttons, updates, esc = await reply(
        s, e, sess, "Здравствуйте", []
    )
    blob = "\n".join(msgs)
    assert "Клиент" not in blob
    assert "Client" not in blob
    assert "Гость," not in blob
    # либо приветствие без имени, либо вопрос
    assert "Здравствуйте" in blob or "Добрый" in blob or "даты" in blob.lower()


def test_fresh_inbound_empty_name_no_klient():
    asyncio.run(_fresh_inbound_no_name())


async def _fresh_inbound_placeholder_name() -> None:
    s = get_settings()
    e = Engine(s)
    sess: dict = {"name": "Клиент", "step": "greeting", "context": {}}
    msgs, _btns, _upd, _esc = await reply(s, e, sess, "Привет", [])
    blob = "\n".join(msgs)
    assert "Клиент" not in blob
    assert ", Клиент" not in blob


def test_fresh_inbound_placeholder_name_stripped():
    asyncio.run(_fresh_inbound_placeholder_name())


def test_looking_start_asks_dates_only():
    for line in LOOKING_START:
        low = line.lower()
        assert "дат" in low or "заезд" in low
        assert "гост" not in low
        assert low.count("?") <= 1


def test_engine_hello_after_outreach_skips_inbound_hello():
    s = get_settings()
    e = Engine(s)
    sess = {
        "name": "Клиент",
        "step": "await_intent",
        "context": {"greeted": True, "outreach": True, "phr_greet": 2},
    }
    msgs, _btns, upd, _esc = e.handle(sess, "Здравствуйте!")
    assert len(msgs) == 1
    assert "Здравствуйте" not in msgs[0]
    assert "Клиент" not in msgs[0]
    assert upd.get("step") == "await_dates"


if __name__ == "__main__":
    test_placeholder_names()
    test_fill_never_inserts_klient()
    test_looking_beats_hello_intent()
    test_outreach_marks_already_greeted()
    test_outreach_transcript_one_reply_no_rehello()
    test_fresh_inbound_empty_name_no_klient()
    test_fresh_inbound_placeholder_name_stripped()
    test_looking_start_asks_dates_only()
    test_engine_hello_after_outreach_skips_inbound_hello()
    print("ok v8.3")
