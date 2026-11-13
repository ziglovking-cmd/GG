# -*- coding: utf-8 -*-
"""Пачка сообщений не должна порождать второй пересказ и чужой район."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.catalog import reason_for_offer
from bot.engine import parse_district
from bot.main import coalesce_guest_batch
from bot.reply_guard import (
    GuestInbox,
    collapse_repeat_asks,
    finished_next_line,
    guest_defers_district,
    question_key,
    resolve_guest_district,
    smooth_speech,
    strip_repeated_outbound,
)


def test_coalesce_three_bubbles_one_text() -> None:
    items = [
        {"chat_id": "1", "text": "Ну можно наверное на завтра", "event": object(), "message_id": "1"},
        {"chat_id": "1", "text": "Нас будет 3 человека", "event": object(), "message_id": "2"},
        {"chat_id": "1", "text": "Сами район выберите", "event": object(), "message_id": "3"},
    ]
    out = coalesce_guest_batch(items)
    assert len(out) == 1
    assert "завтра" in out[0]["text"]
    assert "3 человека" in out[0]["text"]
    assert out[0]["text"].count("завтра") == 1


def test_strip_does_not_restate_slots() -> None:
    prev = "Завтра на троих — подберу варианты в спокойном районе."
    out = strip_repeated_outbound(
        ["Поняла, завтра на троих. Какой район удобнее — центр или поспокойнее?"],
        prev,
    )
    blob = " ".join(out).lower()
    assert "завтра на троих" not in blob
    assert "район" in blob


def test_strip_drops_same_cards() -> None:
    prev = "1) «Феррари»\n2) «Россо»\n3) «Артледи»"
    again = "Подобрала несколько вариантов.\n\n1) «Феррари»\n\n2) «Россо»\n\n3) «Артледи»"
    out = strip_repeated_outbound(["Поняла: парковка уточню.", again], prev)
    blob = "\n".join(out)
    assert "Феррари" not in blob
    assert "парков" in blob.lower()


def test_inbox_ignores_same_message_id() -> None:
    box = GuestInbox()
    item = {"chat_id": "9", "text": "ок", "message_id": "55"}
    assert box.push(item) is True
    assert box.push(dict(item)) is False
    gen = box.bump("9")
    assert box.pop_if_gen("9", gen - 1) is None
    got = box.pop_if_gen("9", gen)
    assert got is not None and len(got) == 1
    assert box.steal("9") == []


def test_defer_district_not_kommunarka() -> None:
    assert guest_defers_district("Сами район выберите")
    assert parse_district("Сами район выберите") == "не принципиально"
    dist = resolve_guest_district("Сами район выберите", "Коммунарка", "")
    assert dist == "не принципиально"
    kept = resolve_guest_district("ок", "Коммунарка", "Прокшино")
    assert kept == "Прокшино"
    named = resolve_guest_district("хочу в Прокшино", "спокойный район", "")
    assert named == "Прокшино"


def test_reason_does_not_repeat_metro_line() -> None:
    obj = {
        "name": "Бриз",
        "metro": "Прокшино · 5 минут пешком",
        "area_label": "Прокшино",
        "zone": "calm",
        "is_calm": True,
        "capacity": 4,
    }
    why = reason_for_offer(obj, district="Прокшино", guests="3")
    assert "прокшино · 5" not in why.lower()
    assert why
    assert "вместит 3" in why.lower() or "спокойн" in why.lower()


def test_one_question_and_no_reask() -> None:
    burst = collapse_repeat_asks(
        [
            "Поняла, завтра на троих.",
            "Подскажите, пожалуйста, на какие даты планируете поездку?",
            "Подскажите, пожалуйста, сколько будет гостей?",
        ],
        "",
    )
    blob = " ".join(burst)
    assert blob.count("?") == 1
    assert "сколько" in blob.lower()
    assert "поняла" in blob.lower()
    again = collapse_repeat_asks(
        ["Хорошо. Подскажите, пожалуйста, сколько будет гостей?"],
        "Подскажите, пожалуйста, сколько будет гостей?",
    )
    assert "сколько" not in " ".join(again).lower()
    assert question_key("Поняла: спокойный район.") == ""


def test_open_district_is_spoken_plainly() -> None:
    from bot.reply_guard import guest_district_phrase
    from bot.smart import _fresh_reason

    assert guest_district_phrase("не принципиально") == "район на ваш выбор"
    obj = {
        "name": "Бриз",
        "metro": "Прокшино · 5 минут пешком",
        "area_label": "Прокшино",
        "address": "Москва, ул. Лобановский Лес, д. 11",
        "zone": "calm",
        "is_calm": True,
        "capacity": 4,
        "price_night": 4280,
    }
    why = _fresh_reason(
        "Прокшино · 5 минут пешком, до 4 гостей",
        obj,
        district="Прокшино",
        guests="3",
    )
    assert "прокшино · 5" not in why.lower()
    assert "до 4" not in why.lower()


def test_smooth_speech_drops_stutter() -> None:
    assert smooth_speech("Ну, эм, завтра на троих — сейчас подберу") == "Завтра на троих."
    assert smooth_speech("Нужны даты на выходные.").startswith("Нужны")
    assert "минуту" not in finished_next_line({"dates": "завтра"}).lower()
    assert "сколько" in finished_next_line({"dates": "завтра"}).lower()


if __name__ == "__main__":
    test_coalesce_three_bubbles_one_text()
    test_strip_does_not_restate_slots()
    test_strip_drops_same_cards()
    test_inbox_ignores_same_message_id()
    test_defer_district_not_kommunarka()
    test_reason_does_not_repeat_metro_line()
    test_one_question_and_no_reask()
    test_open_district_is_spoken_plainly()
    test_smooth_speech_drops_stutter()
    print("ok reply guard")
