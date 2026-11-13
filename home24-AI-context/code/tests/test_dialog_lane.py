"""Категории смены: позже, сделка, отказ, проблема."""

from bot.store import dialog_lane


def test_later_from_path():
    row = {
        "step": "await_dates",
        "context": {"reply_path": "smart:rule/life/later"},
        "dates": "выходные",
        "guests": "2",
        "district": "центр",
    }
    assert dialog_lane(row) == "later"


def test_later_from_guest_words():
    row = {"step": "await_dates", "context": {}, "last_guest": "подумаю и напишу"}
    assert dialog_lane(row) == "later"


def test_deal_needs_handoff_and_facts():
    row = {
        "step": "handed_off",
        "handed_off": 1,
        "dates": "12–14 мая",
        "guests": "2",
        "district": "Прокшино",
        "favorite": "Лофт",
        "context": {},
    }
    assert dialog_lane(row) == "deal"


def test_agreed_but_not_handed_is_hot():
    row = {
        "step": "await_returning",
        "handed_off": 0,
        "dates": "12–14 мая",
        "guests": "2",
        "favorite": "Лофт",
        "context": {},
    }
    assert dialog_lane(row) == "hot"


def test_payment_is_issue_not_deal():
    row = {
        "step": "handed_off",
        "handed_off": 1,
        "dates": "12–14 мая",
        "guests": "2",
        "district": "центр",
        "context": {"reply_path": "smart:rule/life/pay"},
    }
    assert dialog_lane(row) == "issue"


def test_stop_is_lost():
    row = {"step": "done", "context": {"stopped": True}, "last_guest": "не пишите"}
    assert dialog_lane(row) == "lost"


def test_open_chat_stays_in_work():
    row = {"step": "await_guests", "dates": "на выходные", "context": {}}
    assert dialog_lane(row) == "work"
