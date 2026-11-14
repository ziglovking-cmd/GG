# -*- coding: utf-8 -*-
"""После фактов про баллы — сразу вопрос про выбор квартир/района."""
from __future__ import annotations

from bot import phrases as P
from bot.smart import _waiting_reply


def test_yes_on_bonus_offer_asks_district_choice() -> None:
    sess = {
        "name": "Ия",
        "step": "await_intent",
        "context": {"offer_open": True, "offer": "bonus", "outreach": True},
    }
    msgs, ctx, step = P.offer_reply(dict(sess), "Да", last_bot="…Рассказать подробнее?")
    assert step == "await_district"
    low = msgs[0].lower()
    assert "хотите, подберу квартиру?" in low
    assert "центр" in low and "район" in low
    assert "если что-то планируете" not in low
    assert ctx.get("offer_pick_ask") is True


def test_yes_on_pick_ask_goes_district() -> None:
    last = (
        "Если бронировать напрямую, начисляем баллы: 500 за регистрацию. "
        "Хотите, подберу квартиру? Вам ближе центр, спокойный район или за город?"
    )
    sess = {
        "name": "Ия",
        "step": "await_district",
        "context": {"offer_open": False, "offer_told": "bonus", "offer_pick_ask": True},
    }
    msgs, ctx, step = P.offer_reply(dict(sess), "Да", last_bot=last)
    assert step == "await_district"
    assert "район" in msgs[0].lower() or "метро" in msgs[0].lower()


def test_ok_on_pick_ask_soft_later_not_wait() -> None:
    last = (
        "Если бронировать напрямую, начисляем баллы: 500 за регистрацию. "
        "Хотите, подберу квартиру? Вам ближе центр, спокойный район или за город?"
    )
    sess = {"name": "Ия", "step": "await_district", "context": {"offer_pick_ask": True}}
    history = [{"role": "bot", "text": last}]
    out = _waiting_reply(sess, "Хорошо", history)
    assert out is not None
    msgs, _btns, state, _esc = out
    assert msgs and "будем ждать" not in msgs[0].lower()
    assert "подберу" in msgs[0].lower()
    assert (state.get("context") or {}).get("thinking") is True
