# -*- coding: utf-8 -*-
"""v8.6: post-outreach offers kept, grammar, inbound queue persistence."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.ai import reply
from bot.config import get_settings
from bot.engine import (
    BUTTONS,
    Engine,
    format_booking_summary,
    format_guests_phrase,
    parse_dates,
)
from bot.main import finalize_post_outreach_msgs
from bot.phrases import GREETINGS, greeting_msgs, already_greeted
from bot.store import Store

TRANSCRIPT = (
    "Здравствуйте! Да,планы есть на январь с 1 по 7 число,3 человека,центр"
)


def test_user_text_edits_openers_and_buttons() -> None:
    joined = "\n".join(" ".join(v) for v in GREETINGS).lower()
    assert "home24" in joined
    assert "услуг" in joined
    assert "визит" in joined or "москв" in joined
    assert "просто смотрите" not in joined
    assert "пока без планов" not in joined
    assert "на связи" not in joined
    assert "по-человечески" not in joined
    labels = [b[0] for b in BUTTONS["greeting"]]
    assert "Пока просто смотрю" not in labels
    assert "Да, ищу квартиру" in labels


def test_guests_pluralization() -> None:
    assert format_guests_phrase("1") == "1 гость"
    assert format_guests_phrase("2") == "2 человека"
    assert format_guests_phrase("3") == "3 человека"
    assert format_guests_phrase("4") == "4 человека"
    assert format_guests_phrase("5") == "5 человек"
    assert format_guests_phrase("11") == "11 человек"
    assert format_guests_phrase("21") == "21 гость"
    assert format_guests_phrase("1-2") == "1–2 человека"
    assert "3 человек," not in format_booking_summary(
        {"dates": "1–7", "guests": "3", "district": "центр"}
    )
    assert "3 человека" in format_booking_summary(
        {"dates": "с 1 по 7 января", "guests": "3", "district": "центр"}
    )


def test_month_aware_dates() -> None:
    assert parse_dates(TRANSCRIPT) == "с 1 по 7 января"
    assert parse_dates("с 12 по 15 октября") == "с 12 по 15 октября"
    assert parse_dates("5-7 марта") == "с 5 по 7 марта"
    assert parse_dates("с 1 по 7") == "1–7"


async def _transcript_full_reply() -> list[str]:
    s = get_settings()
    e = Engine(s)
    sess: dict = {
        "name": "Клиент",
        "step": "greeting",
        "context": {},
        "dates": "",
        "guests": "",
        "district": "",
    }
    g_msgs, g_upd = greeting_msgs(sess, outreach=True)
    sess.update(g_upd)
    assert already_greeted(sess)
    history = [{"role": "bot", "text": m} for m in g_msgs]
    msgs, _btns, updates, esc = await reply(s, e, sess, TRANSCRIPT, history)
    assert not esc
    assert updates.get("step") == "await_returning"
    offers = (updates.get("context") or {}).get("offers") or []
    assert offers, updates
    # pipeline + send finalize
    final, max_msgs = finalize_post_outreach_msgs(
        msgs, post_opener=True, step=str(updates.get("step") or "")
    )
    assert max_msgs >= 1
    blob = "\n".join(final)
    low = blob.lower()
    # v9.4: живой ack вместо «Записала всё»; слоты и карточки остаются
    assert (
        "записала" in low
        or "поняла" in low
        or "приняла" in low
        or "вижу" in low
        or "3 человека" in blob
    ), blob
    assert "3 человека" in blob or "3 гост" in low
    assert "с 1 по 7 января" in blob
    assert "3 человек," not in blob
    assert "Подобрала несколько" in blob or re_has_card(blob) or "1)" in blob
    assert "впервые" in low or "были у нас" in low
    assert "?" in blob or "подскажите" in low
    assert len(final) >= 1
    return final


def re_has_card(blob: str) -> bool:
    return bool(__import__("re").search(r"(?m)^\d\)\s", blob))


def test_transcript_keeps_offers_and_next_question() -> None:
    final = asyncio.run(_transcript_full_reply())
    print("--- exact reply ---")
    for i, m in enumerate(final):
        print(f"[{i}]\n{m}\n")


def test_finalize_does_not_drop_summary_only() -> None:
    # как в баге: осталась одна сводка без вопроса — дописываем шаг
    out, mx = finalize_post_outreach_msgs(
        ["Записала всё: с 1 по 7 января, 3 человека, центр."],
        post_opener=True,
        step="await_returning",
    )
    assert len(out) >= 2
    assert "впервые" in out[-1].lower()
    assert mx >= 1


def test_finalize_simple_post_opener_still_one_bubble() -> None:
    out, mx = finalize_post_outreach_msgs(
        [
            "Отлично! Подскажите даты поездки и число гостей — помогу с подбором.",
        ],
        post_opener=True,
        step="await_dates",
    )
    assert len(out) == 1
    assert mx == 1


def test_inbound_queue_persists_across_store_reopen() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "q.db")
        st = Store(db)
        st.enqueue_inbound("111", "привет", message_id="10", manager_id="anna")
        st.enqueue_inbound("222", "ищу квартиру", message_id="11", manager_id="anna")
        rows = st.list_inbound_queue(manager_id="anna")
        assert len(rows) == 2
        # reopen
        st2 = Store(db)
        rows2 = st2.list_inbound_queue(manager_id="anna")
        assert len(rows2) == 2
        assert {r["chat_id"] for r in rows2} == {"111", "222"}
        st2.dequeue_inbound("111", message_id="10", manager_id="anna")
        assert len(st2.list_inbound_queue(manager_id="anna")) == 1
        st2.clear_inbound_queue(manager_id="anna")
        assert st2.list_inbound_queue(manager_id="anna") == []


def test_v8_3_looking_still_one_bubble() -> None:
    """Регрессия v8.3: простой looking после outreach — один пузырь."""

    async def _run() -> None:
        s = get_settings()
        e = Engine(s)
        sess: dict = {"name": "Клиент", "step": "greeting", "context": {}}
        g_msgs, g_upd = greeting_msgs(sess, outreach=True)
        sess.update(g_upd)
        history = [{"role": "bot", "text": m} for m in g_msgs]
        msgs, _b, updates, _e = await reply(
            s, e, sess, "Здравствуйте! Да, хотели бы снять квартиру", history
        )
        final, mx = finalize_post_outreach_msgs(
            msgs, post_opener=True, step=str(updates.get("step") or "")
        )
        assert len(final) == 1
        assert mx == 1
        assert "даты" in final[0].lower()

    asyncio.run(_run())


if __name__ == "__main__":
    test_user_text_edits_openers_and_buttons()
    test_guests_pluralization()
    test_month_aware_dates()
    test_transcript_keeps_offers_and_next_question()
    test_finalize_does_not_drop_summary_only()
    test_finalize_simple_post_opener_still_one_bubble()
    test_inbound_queue_persists_across_store_reopen()
    test_v8_3_looking_still_one_bubble()
    print("ok v8.6")
