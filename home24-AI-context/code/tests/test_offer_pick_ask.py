# -*- coding: utf-8 -*-
"""После фактов — как менеджер: даты, потом условия."""
from __future__ import annotations

from bot import phrases as P
from bot.smart import _forward_question, _waiting_reply


def test_yes_on_bonus_offer_asks_dates_like_manager() -> None:
    sess = {
        "name": "Ия",
        "step": "await_intent",
        "context": {"offer_open": True, "offer": "bonus", "outreach": True},
    }
    msgs, ctx, step = P.offer_reply(dict(sess), "Да", last_bot="…Рассказать подробнее?")
    assert step == "await_dates"
    low = msgs[0].lower()
    assert "даты" in low and "подберу" in low
    assert "если что-то планируете" not in low
    assert ctx.get("offer_pick_ask") is True


def test_yes_on_pick_ask_repeats_dates_not_facts() -> None:
    last = (
        "Если бронировать напрямую, начисляем баллы: 500 за регистрацию. "
        "Подскажите удобные даты — подберу квартиру?"
    )
    sess = {
        "name": "Ия",
        "step": "await_dates",
        "context": {"offer_open": False, "offer_told": "bonus", "offer_pick_ask": True},
    }
    msgs, ctx, step = P.offer_reply(dict(sess), "Да", last_bot=last)
    assert step == "await_dates"
    assert "даты" in msgs[0].lower()


def test_ok_on_pick_ask_soft_later_not_wait() -> None:
    last = (
        "Если бронировать напрямую, начисляем баллы: 500 за регистрацию. "
        "Подскажите удобные даты — подберу квартиру?"
    )
    sess = {"name": "Ия", "step": "await_dates", "context": {"offer_pick_ask": True}}
    history = [{"role": "bot", "text": last}]
    out = _waiting_reply(sess, "Хорошо", history)
    assert out is not None
    msgs, _btns, state, _esc = out
    assert msgs and "будем ждать" not in msgs[0].lower()
    assert (state.get("context") or {}).get("thinking") is True


def test_after_dates_asks_conditions_like_manager() -> None:
    sess = {
        "name": "Ия",
        "step": "await_dates",
        "dates": "с 1 по 5 октября",
        "guests": "",
        "district": "",
        "context": {},
    }
    q, ask = _forward_question(sess, [{"role": "bot", "text": "Приняла даты)"}])
    assert ask == "conditions"
    assert "условиях" in q.lower()
    assert "сколько человек" in q.lower()
