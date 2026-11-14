"""Симуляции диалогов Home24: скрипт, стоп-лист, отчёт, без галлюцинаций."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.ai import extract_slots, reply
from bot.config import get_settings
from bot.engine import Engine, is_stop_request, parse_budget, parse_objection
from bot.phrases import GREETINGS, client_report
from bot.store import Store, OUTREACH_RESEND_COOLDOWN_SEC


def test_stop_detection() -> None:
    assert is_stop_request("Не пишите мне больше")
    assert is_stop_request("стоп")
    assert is_stop_request("Отпишитесь пожалуйста")
    assert is_stop_request("unsubscribe")
    assert not is_stop_request("пока просто смотрю")
    assert not is_stop_request("ищу квартиру")


def test_greetings_mention_past_client() -> None:
    markers = (
        "останавливал",
        "были нашим",
        "наш гост",
        "постоянн",
        "бывших гост",
        "уже был",
        "уже были",
        "жили у нас",
        "уже жили",
        "жил у нас",
        "заезда",
        "прошлого заезда",
        "не бронировали",
        "гостем",
        "госте",
        "гостям",
        "гост",
        "уже были с нами",
        "были нашим гостем",
        "уже останавливались",
        "прошлого заезда",
        "бывшим гост",
        "у нас жили",
        "жили раньше",
        "останавливались у нас",
        "уже бывали",
    )
    banned = (
        "по-человечески",
        "на связи",
        "решила написать",
        "соскучились",
        "напомнила о себе",
        "напоминаю:",
        "напоминаю,",
        "пересекались",
        "удобно ли коротко",
        "рады бывшим",
        "рада снова",
        "приятно познакомиться",
        "меня зовут",
        "по площади",
        "отфильтрую",
        "1–2, 3–4",
        "останавливались у нас — вы",
    )
    for variant in GREETINGS:
        blob = " ".join(variant).lower()
        assert any(m in blob for m in markers), variant
        assert "home24" in blob
        for b in banned:
            assert b not in blob, (b, variant)
        assert "{tod}" in " ".join(variant)
    # script.md v3: каждое письмо заканчивается предложением рассказать / вопросом
    assert all(" ".join(v).rstrip().endswith("?") for v in GREETINGS)


def test_budget_objection() -> None:
    assert parse_budget("бюджет до 5000") == "до 5000 ₽"
    assert parse_budget("максимум 4 тыс") is not None
    assert parse_objection("слишком дорого") == "цена"


def test_store_stoplist_and_cooldown() -> None:
    with tempfile.TemporaryDirectory() as td:
        st = Store(str(Path(td) / "t.db"))
        st.add_contact("[REDACTED]", "Анна")
        assert st.list_outreach_batch()[0]["phone"] == "[REDACTED]"
        st.update_contact("[REDACTED]", status="sent", chat_id="111")
        # повторный add не должен вернуть в pending сразу
        st.add_contact("[REDACTED]", "Анна")
        assert st.list_contacts(status="pending") == []
        assert st.list_contacts(status="sent")[0]["phone"] == "[REDACTED]"

        st.mark_stopped(phone="[REDACTED]", chat_id="111")
        assert st.is_stopped_chat("111")
        st.add_contact("[REDACTED]", "Анна")  # не сбрасываем stopped
        assert st.list_contacts(status="stopped")[0]["phone"] == "[REDACTED]"
        assert st.list_outreach_batch() == []


async def _sim() -> None:
    s = get_settings()
    e = Engine(s)

    async def turn(sess: dict, text: str):
        msgs, _, upd, esc = await reply(s, e, sess, text, [])
        for k, v in upd.items():
            if k == "context":
                sess["context"] = v
            elif v is not None and v != "":
                sess[k] = v
        if esc:
            sess["handed_off"] = 1
        if upd.get("stop_requested") or (sess.get("context") or {}).get("stopped"):
            sess["stopped"] = True
        return msgs, upd, esc

    # 1) привет + looking + слоты + pick + handoff
    sess = {
        "name": "Игорь",
        "step": "await_intent",
        "dates": "",
        "guests": "",
        "district": "",
        "handed_off": 0,
        "context": {},
    }
    msgs, _, _ = await turn(sess, "Здравствуйте")
    blob = " ".join(msgs).lower()
    # v9.4 hello-rule: «Здравствуйте» + вопрос про даты (без обязательного Home24)
    assert (
        "home24" in blob
        or "рада" in blob
        or "рады" in blob
        or "здравствуйте" in blob
        or "дат" in blob
    ), blob
    assert "не совсем поймала" not in blob

    msgs, _, _ = await turn(
        sess, "Ищу квартиру на 26-27 нас двое в центре бюджет до 5000"
    )
    assert sess.get("dates")
    assert sess.get("guests")
    assert sess.get("district") == "центр" or "центр" in str(sess.get("district"))
    assert (sess.get("context") or {}).get("budget")

    # 2) стоп-лист
    sess2 = {**sess, "step": "await_intent", "handed_off": 0, "context": {}}
    msgs, upd, esc = await turn(sess2, "Не пишите мне больше")
    assert sess2.get("stopped") or upd.get("stop_requested") or (sess2.get("context") or {}).get(
        "stopped"
    )
    assert esc is False  # не заявка менеджеру
    blob_stop = " ".join(msgs).lower()
    assert (
        "больше не" in blob_stop
        or "не буду" in blob_stop
        or "отписа" in blob_stop
        or "не беспок" in blob_stop
        or "убираю" in blob_stop
    )

    # 3) короткий hello mid / как дела без цикла
    sess3 = {"step": "await_dates", "dates": "", "guests": "", "handed_off": 0, "context": {}}
    msgs, _, _ = await turn(sess3, "привет")
    assert "дат" in " ".join(msgs).lower()
    assert "отлично, работаю" not in " ".join(msgs).lower()  # howareyou ≠ hello

    # 4) выбор варианта
    sess4 = {
        "step": "await_returning",
        "dates": "на 30",
        "guests": "2",
        "district": "центр",
        "handed_off": 0,
        "context": {"offers": ["Чехов", "Бриз", "Вояж"], "budget": "до 5000 ₽"},
        "returning": "",
        "favorite": "",
    }
    msgs, upd, esc = await turn(sess4, "Давайте 2 впервые")
    assert upd.get("favorite") == "Бриз" or sess4.get("favorite") == "Бриз"
    assert esc is True or sess4.get("handed_off")
    report = client_report({**sess4, **upd}, guest_text="Давайте 2 впервые")
    assert "Бюджет" in report or "5000" in report
    assert "Чехов" in report or "Бриз" in report or "Показывали" in report

    # 5) ссылка не крутит «не поймала»
    sess5 = {"step": "await_dates", "dates": "", "guests": "", "handed_off": 0, "context": {}}
    msgs, _, _ = await turn(sess5, "https://disk.yandex.ru/d/xxx")
    assert "не совсем поймала" not in " ".join(msgs).lower()

    # 6) отказ мягкий ≠ стоп-лист
    sess6 = {"step": "await_intent", "handed_off": 0, "context": {}}
    msgs, upd, _ = await turn(sess6, "не сейчас")
    assert not (upd.get("context") or {}).get("stopped")
    assert upd.get("step") in ("done", "browsing", None) or sess6.get("step") in (
        "done",
        "browsing",
        "await_intent",
    )

    # 7) слоты из каши
    slots = extract_slots(
        "Нужна тихая квартира с ребёнком на выходные человек 3 бюджет 6 тысяч"
    )
    assert slots.get("guests")
    assert slots.get("district") == "спокойный район" or slots.get("_notes")
    assert slots.get("_budget")

    print("OK simulations")


if __name__ == "__main__":
    test_stop_detection()
    test_greetings_mention_past_client()
    test_budget_objection()
    test_store_stoplist_and_cooldown()
    asyncio.run(_sim())
    print("ALL OK")
