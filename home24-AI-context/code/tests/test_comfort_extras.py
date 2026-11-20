# -*- coding: utf-8 -*-
"""После выбора квартиры бот спрашивает про лёд / чай / удлинитель / питомца."""

from __future__ import annotations

from bot.config import get_settings
from bot.engine import Engine
from bot.phrases import COMFORT_EXTRAS_ASK
from bot.smart import _comfort_extras_reply, _tl_pick_reply


def test_comfort_ask_text() -> None:
    low = COMFORT_EXTRAS_ASK.lower().replace("ё", "е")
    assert "лед" in low or "лёд" in COMFORT_EXTRAS_ASK.lower()
    assert "чай" in low and "кофе" in low
    assert "удлинител" in low or "зарядк" in low
    assert "питомц" in low


def test_tl_pick_asks_comfort_before_handoff() -> None:
    sess = {
        "step": "await_returning",
        "dates": "с 12 по 17 декабря",
        "guests": "2",
        "district": "Коммунарка",
        "context": {"tl_offers": ["Скандинавия", "Феррари"], "tl_dates": "с 12 по 17 декабря"},
    }
    history = [{"role": "bot", "text": "Свободны по календарю на 12–17 декабря:\n1) «Скандинавия»"}]
    msgs, _btns, upd, esc = _tl_pick_reply(sess, "Скандинавия", history)  # type: ignore[misc]
    assert esc is False
    assert upd.get("step") == "await_comfort"
    assert upd.get("favorite") == "Скандинавия"
    blob = "\n".join(msgs)
    assert "Скандинавия" in blob
    assert "чай" in blob.lower()
    assert "менеджера" not in blob.lower()


def test_comfort_answer_asks_docs() -> None:
    sess = {
        "step": "await_comfort",
        "favorite": "Скандинавия",
        "dates": "с 12 по 17 декабря",
        "district": "Коммунарка",
        "context": {"comfort_asked": True},
    }
    msgs, _, upd, esc = _comfort_extras_reply(sess, "нужен лёд и удлинитель")  # type: ignore[misc]
    assert esc is False
    assert upd.get("step") == "await_docs"
    prefs = str((upd.get("context") or {}).get("prefs") or "").lower()
    assert "лёд" in prefs or "лед" in prefs
    blob = "\n".join(msgs).lower().replace("ё", "е")
    assert "отчетн" in blob or "отчётн" in "\n".join(msgs).lower()


def test_comfort_no_asks_docs() -> None:
    sess = {
        "step": "await_comfort",
        "favorite": "Олимп",
        "dates": "с 1 по 3 января",
        "district": "центр",
        "context": {"comfort_asked": True},
    }
    msgs, _, upd, esc = _comfort_extras_reply(sess, "нет")  # type: ignore[misc]
    assert esc is False
    assert upd.get("step") == "await_docs"
    assert "не нужны" in str((upd.get("context") or {}).get("prefs") or "")
    assert "документ" in "\n".join(msgs).lower()


def test_engine_ask_comfort_before_handoff() -> None:
    eng = Engine(get_settings())
    msgs, _, upd, esc = eng.ask_comfort_or_handoff(
        {"favorite": "Феррари", "returning": "нет", "context": {}},
        note="Интересует «Феррари».",
    )
    assert esc is False
    assert upd.get("step") == "await_comfort"
    assert COMFORT_EXTRAS_ASK in msgs
