# -*- coding: utf-8 -*-
"""Итог перед менеджером: даты, район, квартира, залог, животные, доп. услуги."""

from __future__ import annotations

from bot.phrases import booking_summary_message
from bot.smart import _booking_confirm_reply, _comfort_extras_reply, _docs_reply


def _sess(**kw):
    base = {
        "dates": "с 12 по 17 декабря",
        "guests": "2",
        "district": "Коммунарка",
        "favorite": "Скандинавия",
        "context": {},
    }
    base.update(kw)
    if "context" in kw:
        base["context"] = kw["context"]
    return base


def test_summary_without_extras_and_without_pets() -> None:
    text = booking_summary_message(
        _sess(
            context={
                "prefs": "доп. удобства не нужны",
                "comfort_asked": True,
                "report_docs": "нет",
            }
        )
    )
    low = text.lower().replace("ё", "е")
    assert "12" in text and "коммунарка" in low
    assert "скандинавия" in low
    assert "2 000" in text or "2000" in text.replace(" ", "")
    assert "без животных" in low
    assert "без доп. услуг" in low
    assert "отчетные документы: нет" in low or "отчётные документы: нет" in text.lower()
    assert "все верно" in low or "всё верно" in text.lower()


def test_summary_with_extras_and_pets() -> None:
    text = booking_summary_message(
        _sess(
            favorite="Эльбрус",
            district="Очаково",
            context={
                "pets": "собака",
                "prefs": "доп. для комфорта: лёд и удлинитель",
                "report_docs": "да",
            },
        )
    )
    low = text.lower().replace("ё", "е")
    assert "с животными" in low
    assert "500" in text
    assert "лед" in low or "лёд" in text.lower()
    assert "удлинител" in low
    assert "без доп" not in low
    assert "отчетные документы: да" in low or "отчётные документы: да" in text.lower()


def test_comfort_asks_docs_then_summary() -> None:
    sess = _sess(step="await_comfort", context={"comfort_asked": True})
    msgs, _, upd, esc = _comfort_extras_reply(sess, "нужен лёд")  # type: ignore[misc]
    assert esc is False
    assert upd.get("step") == "await_docs"
    assert "документ" in "\n".join(msgs).lower()

    msgs2, _, upd2, esc2 = _docs_reply({**sess, **upd}, "да")  # type: ignore[misc]
    assert esc2 is False
    assert upd2.get("step") == "await_booking_confirm"
    assert (upd2.get("context") or {}).get("report_docs") == "да"
    blob = "\n".join(msgs2).lower().replace("ё", "е")
    assert "сверим" in blob or "даты" in blob
    assert "отчетные документы: да" in blob or "отчётные документы: да" in "\n".join(msgs2).lower()


def test_docs_no_in_summary() -> None:
    sess = _sess(
        step="await_docs",
        context={"comfort_asked": True, "prefs": "доп. удобства не нужны"},
    )
    msgs, _, upd, esc = _docs_reply(sess, "нет")  # type: ignore[misc]
    assert esc is False
    assert upd.get("step") == "await_booking_confirm"
    assert (upd.get("context") or {}).get("report_docs") == "нет"
    assert "без доп. услуг" in "\n".join(msgs).lower()
    assert "нет" in "\n".join(msgs).lower()


def test_booking_confirm_yes_hands_off() -> None:
    sess = _sess(
        step="await_booking_confirm",
        context={
            "comfort_asked": True,
            "prefs": "доп. удобства не нужны",
            "report_docs": "нет",
        },
    )
    msgs, _, upd, esc = _booking_confirm_reply(sess, "да")  # type: ignore[misc]
    assert esc is True
    assert upd.get("handed_off") == 1 or upd.get("step") == "handed_off"
    assert "менеджера" in "\n".join(msgs).lower()
