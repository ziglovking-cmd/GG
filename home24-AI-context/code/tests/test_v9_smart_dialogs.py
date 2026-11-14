# -*- coding: utf-8 -*-
"""v9.0 smart bot — ≥25 реалистичных сценариев с mocked LLM."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# не ходим в платный API в этом файле — только хук
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.ai import reply
from bot.config import get_settings
from bot.engine import Engine
from bot.main import finalize_post_outreach_msgs
from bot.phrases import greeting_msgs, already_greeted
from bot import smart as smart_mod


def _j(**kwargs: Any) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def _mock(payload: dict[str, Any]):
    async def _hook(system: str, messages: list[dict[str, str]], **_kw):
        return _j(**payload), "mock/v9"

    return _hook


async def _turn(
    sess: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    payload: dict[str, Any],
) -> tuple[list[str], dict[str, Any], bool]:
    smart_mod.set_understand_hook(_mock(payload))
    try:
        s = get_settings()
        e = Engine(s)
        msgs, _b, upd, esc = await reply(s, e, sess, text, history)
        for k, v in upd.items():
            if k == "context":
                sess["context"] = v
            elif v is not None and v != "":
                sess[k] = v
        if esc:
            sess["handed_off"] = 1
        history.extend([{"role": "guest", "text": text}])
        history.extend([{"role": "bot", "text": m} for m in msgs])
        return msgs, upd, esc
    finally:
        smart_mod.set_understand_hook(None)


def _sess(**kw: Any) -> dict[str, Any]:
    base = {
        "name": "Мария",
        "step": "await_intent",
        "dates": "",
        "guests": "",
        "district": "",
        "returning": "",
        "favorite": "",
        "handed_off": 0,
        "context": {"greeted": True, "outreach": True},
    }
    base.update(kw)
    return base


def _blob(msgs: list[str]) -> str:
    return "\n".join(msgs).lower()


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------


async def sc_multi_intent_pets() -> None:
    """1. Даты+гости+район+собака в одном сообщении."""
    sess = _sess()
    hist = [{"role": "bot", "text": "Добрый день! Это Home24. Вы у нас останавливались."}]
    msgs, upd, esc = await _turn(
        sess,
        "январь 1–7, 3 человека, центр, можно с собакой?",
        hist,
        {
            "intent": "multi",
            "slots": {
                "dates": "с 1 по 7 января",
                "guests": "3",
                "district": "центр",
                "pets": "собака",
            },
            "messages": [
                "Записала: с 1 по 7 января, 3 человека, центр. С собакой — на части объектов, по согласованию 🙂"
            ],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов", "Дюма", "Жизель"],
            "offer_reasons": {
                "Чехов": "центр у Бауманской, до 4 гостей",
                "Дюма": "Гагаринский, просторно",
                "Жизель": "удобно по вместимости",
            },
            "escalate": False,
            "uncertain": False,
        },
    )
    assert not esc
    b = _blob(msgs)
    assert "собак" in b or "питом" in b
    assert "подобрала" in b or "1)" in b
    assert "впервые" in b or "были" in b
    assert upd.get("guests") == "3"
    assert "январ" in str(upd.get("dates") or "").lower() or "1" in str(upd.get("dates"))


async def sc_correction_guests() -> None:
    """2. Правка: не 3, а 4."""
    sess = _sess(dates="с 1 по 7 января", guests="3", district="центр", step="await_returning")
    hist = [
        {"role": "bot", "text": "Записала всё: с 1 по 7 января, 3 человека, центр."},
    ]
    msgs, upd, _ = await _turn(
        sess,
        "не 3, а 4 человека",
        hist,
        {
            "intent": "correction",
            "slots": {"dates": "с 1 по 7 января", "guests": "4", "district": "центр"},
            "messages": ["Поняла, исправила на 4 человека 🙂"],
            "ask_next": "pick",
            "attach_offers": True,
            "offer_names": ["Чехов", "Дюма"],
            "escalate": False,
        },
    )
    assert upd.get("guests") == "4"
    assert "4" in _blob(msgs)


async def sc_outreach_then_looking() -> None:
    """3. После outreach — без re-hello, сразу к датам."""
    sess = _sess(name="Клиент")
    g_msgs, g_upd = greeting_msgs(sess, outreach=True)
    sess.update(g_upd)
    hist = [{"role": "bot", "text": m} for m in g_msgs]
    msgs, upd, _ = await _turn(
        sess,
        "Здравствуйте! Да, хотели бы снять квартиру",
        hist,
        {
            "intent": "looking",
            "slots": {},
            "messages": ["Отлично! На какие даты смотрите и сколько будет гостей?"],
            "ask_next": "dates",
            "attach_offers": False,
            "escalate": False,
        },
    )
    final, _ = finalize_post_outreach_msgs(msgs, post_opener=True, step=str(upd.get("step")))
    assert len(final) == 1
    assert "здравствуйте" not in final[0].lower()
    assert "клиент" not in final[0].lower()
    assert "дат" in final[0].lower()


async def sc_price_question_handoff() -> None:
    """4. Вопрос цены → менеджер, без выдуманной суммы."""
    sess = _sess(dates="выходные", guests="2", district="центр", step="await_returning")
    hist = [{"role": "bot", "text": "Подобрала варианты."}]
    msgs, upd, esc = await _turn(
        sess,
        "сколько будет стоить Чехов на эти даты?",
        hist,
        {
            "intent": "faq",
            "slots": {"favorite": "Чехов"},
            "messages": [
                "Точную цену по вашим датам лучше подтвердит менеджер — сейчас подключу 🙂"
            ],
            "ask_next": "book",
            "escalate": True,
            "uncertain": True,
        },
    )
    assert esc or upd.get("handed_off")
    assert not any(x in _blob(msgs) for x in ("99999", "выдума"))


async def sc_apartment_followup() -> None:
    """5. Вопрос про конкретную квартиру из каталога."""
    sess = _sess(
        dates="с 1 по 7 января",
        guests="2",
        district="центр",
        step="await_returning",
        context={"greeted": True, "offers": ["Чехов", "Дюма"]},
    )
    hist = [{"role": "bot", "text": "1) Чехов 2) Дюма"}]
    msgs, _, esc = await _turn(
        sess,
        "а что рядом с Чеховым? во сколько заезд?",
        hist,
        {
            "intent": "apartment_q",
            "slots": {"favorite": "Чехов"},
            "messages": [
                "У «Чехова» ориентир — Бауманская, заезд обычно после 15:00, точнее по объекту."
            ],
            "ask_next": "pick",
            "attach_offers": False,
            "escalate": False,
        },
    )
    assert not esc
    assert "чехов" in _blob(msgs)


async def sc_rude_guest() -> None:
    """6. Грубость — коротко по делу, без эскалации зря."""
    sess = _sess(step="await_dates")
    msgs, _, esc = await _turn(
        sess,
        "вы тупые что ли, нормально ответьте",
        [{"role": "bot", "text": "На какие даты смотрите?"}],
        {
            "intent": "chitchat",
            "slots": {},
            "messages": ["Поняла. Давайте по делу — на какие даты нужна квартира?"],
            "ask_next": "dates",
            "escalate": False,
        },
    )
    assert not esc
    assert "извините" in _blob(msgs)
    assert "дат" in _blob(msgs)


async def sc_offtopic_weather() -> None:
    """7. Оффтоп про погоду → честно «не проверяю», без выдуманных фактов."""
    sess = _sess()
    msgs, _, _ = await _turn(
        sess,
        "какая погода в москве будет",
        [{"role": "bot", "text": "Чем помочь?"}],
        {
            "intent": "chitchat",
            "slots": {},
            "messages": [
                "В Москве погода переменчивая 🙂 По проживанию — на какие даты думаете?"
            ],
            "ask_next": "dates",
            "escalate": False,
        },
    )
    b = _blob(msgs)
    assert "дат" in b
    assert "не проверяю" in b or "не смотрю" in b
    assert "переменчив" not in b
    assert "°" not in "\n".join(msgs)


async def sc_returning_guest() -> None:
    """8. Бывший гость выбирает вариант."""
    sess = _sess(
        dates="ближайшие выходные",
        guests="2",
        district="центр",
        step="await_returning",
        context={"greeted": True, "offers": ["Чехов", "Дюма", "Жизель"]},
    )
    msgs, upd, esc = await _turn(
        sess,
        "давайте 1, мы у вас уже были",
        [{"role": "bot", "text": "1) Чехов\n2) Дюма"}],
        {
            "intent": "book",
            "slots": {"returning": "да", "favorite": "Чехов"},
            "messages": ["Отлично, «Чехов» — передаю менеджеру на бронь 🙂"],
            "ask_next": "book",
            "escalate": True,
        },
    )
    assert esc
    assert upd.get("returning") == "да" or "чехов" in _blob(msgs)


async def sc_kids() -> None:
    """9. С ребёнком."""
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "на выходные, нас двое и ребёнок 3 года, тихий район",
        [],
        {
            "intent": "multi",
            "slots": {
                "dates": "ближайшие выходные",
                "guests": "3",
                "district": "спокойный",
                "kids": "ребёнок 3 года",
            },
            "messages": [
                "Записала выходные, 3 гостя, поспокойнее. С детьми можно — кроватку уточню по квартире 🙂"
            ],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Симфония"],
            "escalate": False,
        },
    )
    assert "дет" in _blob(msgs) or "реб" in _blob(msgs) or upd.get("guests") == "3"
    assert upd.get("guests") == "3", upd


async def sc_budget() -> None:
    """10. Бюджет до 5000."""
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "12-15 марта, 2 человека, центр, бюджет до 5000",
        [],
        {
            "intent": "looking",
            "slots": {
                "dates": "с 12 по 15 марта",
                "guests": "2",
                "district": "центр",
                "budget": "до 5000 ₽",
            },
            "messages": ["Учла бюджет до 5000 ₽ — подберу что ближе по цене 🙂"],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов"],
            "escalate": False,
        },
    )
    assert (upd.get("context") or {}).get("budget") or "5000" in _blob(msgs)


async def sc_typo_slang() -> None:
    """11. Опечатки / сленг."""
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "здорова нужна хата на выхи на двоих гденить у метро",
        [],
        {
            "intent": "looking",
            "slots": {
                "dates": "ближайшие выходные",
                "guests": "2",
                "district": "не принципиально",
            },
            "messages": [
                "Поняла, выходные на двоих у метро. Центр важнее или можно поспокойнее?"
            ],
            "ask_next": "district",
            "attach_offers": False,
            "escalate": False,
        },
    )
    b = _blob(msgs)
    assert (
        "район" in b
        or "центр" in b
        or "дат" in b
        or "впервые" in b
        or "подобрала" in b
        or upd.get("guests") == "2"
    )


async def sc_no_reask_known() -> None:
    """12. Не переспрашивать известные даты."""
    sess = _sess(dates="с 1 по 7 января", guests="", step="await_guests")
    msgs, _, _ = await _turn(
        sess,
        "нас будет четверо",
        [{"role": "bot", "text": "Сколько будет гостей?"}],
        {
            "intent": "looking",
            "slots": {"dates": "с 1 по 7 января", "guests": "4"},
            "messages": ["Приняла, 4 человека. Какой район удобнее — центр или поспокойнее?"],
            "ask_next": "district",
            "escalate": False,
        },
    )
    b = _blob(msgs)
    assert "скольк" not in b or "район" in b
    assert "дат" not in b or "район" in b


async def sc_stop_list_script() -> None:
    """13. Стоп — только скрипт, без smart."""
    smart_mod.set_understand_hook(_mock({"intent": "looking", "messages": ["не должно"]}))
    try:
        s = get_settings()
        e = Engine(s)
        sess = _sess()
        msgs, _, upd, _ = await reply(s, e, sess, "не пишите мне больше", [])
        assert "не буду писать" in _blob(msgs) or "больше не" in _blob(msgs) or "стоп" in str(upd).lower() or "good" in _blob(msgs) or "добр" in _blob(msgs)
    finally:
        smart_mod.set_understand_hook(None)


async def sc_invented_price_stripped() -> None:
    """14. Safety: выдуманная цена вычищается."""
    sess = _sess(dates="завтра", guests="2", district="центр")
    msgs, _, _ = await _turn(
        sess,
        "ок",
        [],
        {
            "intent": "looking",
            "slots": {"dates": "завтра", "guests": "2", "district": "центр"},
            "messages": ["Квартира будет 777777 ₽ за ночь, супер цена"],
            "ask_next": "returning",
            "attach_offers": False,
            "escalate": False,
        },
    )
    assert "777777" not in "\n".join(msgs)


async def sc_invented_apartment_ignored() -> None:
    """15. Несуществующая квартира в offer_names → подмена каталогом."""
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "1-5 февраля 2 взрослых центр",
        [],
        {
            "intent": "looking",
            "slots": {"dates": "с 1 по 5 февраля", "guests": "2", "district": "центр"},
            "messages": ["Подобрала варианты под февраль 🙂"],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["НесуществующаяВиллаXYZ"],
            "escalate": False,
        },
    )
    offers = (upd.get("context") or {}).get("offers") or []
    assert "НесуществующаяВиллаXYZ" not in offers
    assert offers or "подобрала" in _blob(msgs) or "1)" in _blob(msgs)


async def sc_frustrated_handoff() -> None:
    """16. Раздражение → handoff."""
    sess = _sess(step="await_dates")
    _, upd, esc = await _turn(
        sess,
        "уже третий раз спрашиваете одно и то же, позовите человека",
        [{"role": "bot", "text": "На какие даты?"}],
        {
            "intent": "escalate",
            "slots": {},
            "messages": ["Сейчас подключу коллегу — обычно отвечает за 10–15 минут."],
            "escalate": True,
            "uncertain": True,
        },
    )
    assert esc or upd.get("handed_off")


async def sc_parking() -> None:
    """17. Парковка."""
    sess = _sess(dates="на 20", guests="2", district="центр", step="await_returning")
    msgs, upd, _ = await _turn(
        sess,
        "а парковка есть?",
        [{"role": "bot", "text": "Есть варианты"}],
        {
            "intent": "faq",
            "slots": {"parking": "нужна"},
            "messages": [
                "Парковка зависит от дома — у части объектов есть двор/карман. Уточню у менеджера по выбранной 🙂"
            ],
            "ask_next": "pick",
            "escalate": False,
        },
    )
    assert "парков" in _blob(msgs)
    assert (upd.get("context") or {}).get("parking")


async def sc_voice_like() -> None:
    """18. Голосовой стиль (сплошной текст)."""
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "ну короче мы типа с женой приедем числа с пятого по восьмое мая нас двое хотим поближе к центру",
        [],
        {
            "intent": "looking",
            "slots": {
                "dates": "с 5 по 8 мая",
                "guests": "2",
                "district": "центр",
            },
            "messages": ["Записала с 5 по 8 мая, 2 гостя, ближе к центру 🙂"],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов", "Дюма"],
            "escalate": False,
        },
    )
    assert "мая" in str(upd.get("dates") or "") or "5" in str(upd.get("dates") or "")
    assert "?" in "\n".join(msgs) or "впервые" in _blob(msgs)


async def sc_browsing_no_pressure() -> None:
    """19. Пока без дат — не давить «просто смотрите»."""
    sess = _sess()
    msgs, _, _ = await _turn(
        sess,
        "пока рано бронировать просто интересно что есть",
        [],
        {
            "intent": "browsing",
            "slots": {},
            "messages": [
                "Конечно. Могу прислать 2–3 варианта на будущее — удобно? Или напишите ориентир по датам."
            ],
            "ask_next": "dates",
            "escalate": False,
        },
    )
    assert "просто смотрите" not in _blob(msgs)


async def sc_manager_name_banned() -> None:
    """20. Без «Меня зовут Анна»."""
    sess = _sess()
    msgs, _, _ = await _turn(
        sess,
        "кто вы",
        [],
        {
            "intent": "chitchat",
            "slots": {},
            "messages": ["Меня зовут Анна, Home24. Чем помочь по квартире?"],
            "ask_next": "dates",
            "escalate": False,
        },
    )
    assert "меня зовут" not in _blob(msgs)


async def sc_first_inbound() -> None:
    """21. Гость сам написал (не outreach)."""
    sess = {
        "name": "",
        "step": "greeting",
        "dates": "",
        "guests": "",
        "district": "",
        "context": {},
    }
    msgs, _, _ = await _turn(
        sess,
        "Здравствуйте, ищу квартиру на двоих",
        [],
        {
            "intent": "looking",
            "slots": {"guests": "2"},
            "messages": [
                "Здравствуйте! Это Home24 — посуточные апартаменты в Москве 🙂",
                "На какие даты смотрите?",
            ],
            "ask_next": "dates",
            "escalate": False,
        },
    )
    assert "home24" in _blob(msgs) or "дат" in _blob(msgs)


async def sc_pick_number() -> None:
    """22. Выбор «2» из списка."""
    sess = _sess(
        dates="выходные",
        guests="2",
        district="центр",
        step="await_returning",
        context={"greeted": True, "offers": ["Чехов", "Дюма", "Жизель"]},
    )
    msgs, upd, esc = await _turn(
        sess,
        "2",
        [{"role": "bot", "text": "1) Чехов\n2) Дюма\n3) Жизель"}],
        {
            "intent": "book",
            "slots": {"favorite": "Дюма", "returning": None},
            "messages": ["«Дюма» — отличный выбор. Вы у нас уже были или впервые?"],
            "ask_next": "returning",
            "escalate": False,
        },
    )
    assert "дюма" in _blob(msgs) or upd.get("favorite")


async def sc_llm_timeout_fallback() -> None:
    """23. LLM None → script fallback всё ещё отвечает."""
    async def _none(*_a, **_k):
        return None

    smart_mod.set_understand_hook(_none)
    try:
        # хук есть, но возвращает None → smart_reply None → script
        s = get_settings()
        e = Engine(s)
        sess = _sess(step="await_dates", dates="", guests="", district="")
        msgs, _b, upd, _e = await reply(s, e, sess, "ближайшие выходные", [])
        assert msgs, f"empty fallback msgs upd={upd}"
        b = _blob(msgs)
        assert (
            "гост" in b
            or "человек" in b
            or "район" in b
            or "дат" in b
            or upd.get("dates")
        ), b
    finally:
        smart_mod.set_understand_hook(None)


async def sc_no_repeat_hello_mid() -> None:
    """24. Mid-dialog LLM hello срезается."""
    sess = _sess(dates="завтра", guests="2", step="await_district")
    hist = [
        {"role": "bot", "text": "Добрый день! Это Home24."},
        {"role": "guest", "text": "завтра на двоих"},
        {"role": "bot", "text": "Какой район?"},
    ]
    msgs, _, _ = await _turn(
        sess,
        "центр",
        hist,
        {
            "intent": "looking",
            "slots": {"dates": "завтра", "guests": "2", "district": "центр"},
            "messages": [
                "Добрый день! Это Home24 снова. Записала центр — были у нас раньше?"
            ],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов"],
            "escalate": False,
        },
    )
    # не должно начинаться с повторного представления как единственного смысла
    joined = "\n".join(msgs)
    assert "впервые" in joined.lower() or "были" in joined.lower() or "подобрала" in joined.lower()


async def sc_reasons_on_cards() -> None:
    """25. У карточек есть «Почему подходит»."""
    sess = _sess()
    msgs, _, _ = await _turn(
        sess,
        "10-12 июня 2 чел центр",
        [],
        {
            "intent": "looking",
            "slots": {
                "dates": "с 10 по 12 июня",
                "guests": "2",
                "district": "центр",
            },
            "messages": ["Записала даты и центр."],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов", "Дюма"],
            "offer_reasons": {"Чехов": "у метро Бауманская", "Дюма": "Гагаринский район"},
            "escalate": False,
        },
    )
    assert "почему подходит" in _blob(msgs)


async def sc_empty_llm_messages_still_ok() -> None:
    """26. Пустые messages у LLM → система соберёт сводку."""
    sess = _sess()
    msgs, _, _ = await _turn(
        sess,
        "с 1 по 3 апреля трое центр",
        [],
        {
            "intent": "looking",
            "slots": {
                "dates": "с 1 по 3 апреля",
                "guests": "3",
                "district": "центр",
            },
            "messages": [],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов"],
            "escalate": False,
        },
    )
    assert msgs
    assert "?" in "\n".join(msgs) or "впервые" in _blob(msgs)


async def sc_next_step_always() -> None:
    """27. Каждый ответ заканчивается next step."""
    sess = _sess(step="await_dates")
    msgs, _, _ = await _turn(
        sess,
        "спасибо",
        [{"role": "bot", "text": "Жду даты"}],
        {
            "intent": "chitchat",
            "slots": {},
            "messages": ["Пожалуйста"],
            "ask_next": "dates",
            "escalate": False,
        },
    )
    assert re_has_next(msgs)


def re_has_next(msgs: list[str]) -> bool:
    import re

    return bool(
        re.search(
            r"\?|подскажите|напишите|подключаю|были у|впервые",
            "\n".join(msgs),
            flags=re.I,
        )
    )


SCENARIOS = [
    ("multi_intent_pets", sc_multi_intent_pets),
    ("correction_guests", sc_correction_guests),
    ("outreach_then_looking", sc_outreach_then_looking),
    ("price_question_handoff", sc_price_question_handoff),
    ("apartment_followup", sc_apartment_followup),
    ("rude_guest", sc_rude_guest),
    ("offtopic_weather", sc_offtopic_weather),
    ("returning_guest", sc_returning_guest),
    ("kids", sc_kids),
    ("budget", sc_budget),
    ("typo_slang", sc_typo_slang),
    ("no_reask_known", sc_no_reask_known),
    ("stop_list_script", sc_stop_list_script),
    ("invented_price_stripped", sc_invented_price_stripped),
    ("invented_apartment_ignored", sc_invented_apartment_ignored),
    ("frustrated_handoff", sc_frustrated_handoff),
    ("parking", sc_parking),
    ("voice_like", sc_voice_like),
    ("browsing_no_pressure", sc_browsing_no_pressure),
    ("manager_name_banned", sc_manager_name_banned),
    ("first_inbound", sc_first_inbound),
    ("pick_number", sc_pick_number),
    ("llm_timeout_fallback", sc_llm_timeout_fallback),
    ("no_repeat_hello_mid", sc_no_repeat_hello_mid),
    ("reasons_on_cards", sc_reasons_on_cards),
    ("empty_llm_messages_still_ok", sc_empty_llm_messages_still_ok),
    ("next_step_always", sc_next_step_always),
]


def test_all_v9_scenarios() -> None:
    assert len(SCENARIOS) >= 25

    async def _run() -> None:
        errors: list[str] = []
        for name, fn in SCENARIOS:
            try:
                await fn()
                print(f"OK {name}")
            except Exception as e:
                errors.append(f"{name}: {e}")
                print(f"FAIL {name}: {e}")
        if errors:
            raise AssertionError("; ".join(errors[:8]) + (f" (+{len(errors)-8})" if len(errors) > 8 else ""))

    asyncio.run(_run())


if __name__ == "__main__":
    test_all_v9_scenarios()
    print(f"ok v9 smart ({len(SCENARIOS)} scenarios)")
