# -*- coding: utf-8 -*-
"""Доп. услуги: сразу список, не «за день до заезда»; «почему» ≠ календарь."""

from __future__ import annotations

from bot.phrases import ADDON_SERVICES_LIST
from bot.smart import _AVAIL_RE, _craft_early


def _one(sess, text, history=None):
    got = _craft_early(dict(sess), text, history or [])
    assert got, text
    return got[0][0], got[2], got[3]


def test_avail_re_does_not_match_pochemu():
    assert not _AVAIL_RE.search("Почему за день?")
    assert not _AVAIL_RE.search("почему так?")
    assert _AVAIL_RE.search("почём за сутки?")
    assert _AVAIL_RE.search("Сколько стоит?")


def test_services_question_sends_list_not_day_before():
    sess = {
        "step": "handed_off",
        "dates": "12–15 декабря",
        "guests": "2",
        "district": "Прокшино",
        "favorite": "Нуар",
        "handed_off": 1,
        "context": {"perk": "wait", "tl_offers": [], "tl_dates": "12–15 декабря"},
    }
    history = [
        {
            "role": "bot",
            "text": "Отлично, «Нуар» на 12–15 декабря, передаю менеджеру на бронь 🙂",
        }
    ]
    line, state, esc = _one(sess, "Какие дополнительные услуги у вас есть?", history)
    assert "организац" in line.lower()
    assert "романтическ" in line.lower()
    assert "только для двоих" in line.lower()
    assert "фотосесс" in line.lower()
    assert "за день до заезда" not in line.lower()
    assert "бесплатн" not in line.lower()
    assert ADDON_SERVICES_LIST.split("\n")[0] in line
    assert esc is False
    assert state["context"]["perk"] == "told"


def test_why_day_before_does_not_relist_apartments():
    sess = {
        "step": "await_returning",
        "dates": "12–15 декабря",
        "guests": "2",
        "district": "Прокшино",
        "favorite": "Нуар",
        "handed_off": 0,
        "context": {
            "perk": "told",
            "tl_offers": [],
            "offers": ["Хомлин", "Карма", "Нуар"],
            "tl_dates": "12–15 декабря",
        },
    }
    history = [
        {
            "role": "bot",
            "text": "Хорошо) Список услуг откроется за день до заезда, тогда и выберете.",
        }
    ]
    line, state, esc = _one(sess, "Почему за день?", history)
    assert "по календарю" not in line.lower()
    assert "хомлин" not in line.lower()
    assert "какая нравится" not in line.lower()
    assert "организац" in line.lower() or "сразу" in line.lower()
    assert "за день до заезда" not in line.lower()
    assert esc is False
    assert (state.get("context") or {}).get("reply_path") == "smart:rule/perks-why"
