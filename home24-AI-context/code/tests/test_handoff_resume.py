# -*- coding: utf-8 -*-
"""После паузы менеджера бот снова отвечает гостю из рассылки."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.handoff_hold import HOLD_SEC, handoff_hold_active, resume_step
from bot.smart import _craft_early, _normalize_slots


def test_manager_pause_expires() -> None:
    now = time.time()
    fresh = [{"role": "manager", "text": "я тут", "created_at": now - 60}]
    stale = [{"role": "manager", "text": "я тут", "created_at": now - HOLD_SEC - 5}]
    assert handoff_hold_active(fresh, now=now)
    assert not handoff_hold_active(stale, now=now)
    assert not handoff_hold_active([], now=now)


def test_resume_step_follows_known_slots() -> None:
    assert resume_step({"dates": "", "guests": ""}) == "await_dates"
    assert resume_step({"dates": "в январе", "guests": ""}) == "await_guests"


def test_confusion_restates_january_and_asks_guests() -> None:
    sess = {
        "step": "await_guests",
        "dates": "в январе",
        "guests": "",
        "district": "",
        "context": {"pets": "собака"},
    }
    out = _craft_early(sess, "Я не понимаю", [])
    assert out is not None
    blob = out[0][0].lower()
    assert "январ" in blob
    assert "собак" in blob
    assert "сколько вас будет" in blob
    assert "число людей" not in blob
    assert "район" not in blob
    assert out[2]["step"] == "await_guests"
    where = _craft_early(sess, "Где?", [])
    assert where is not None
    assert where[2]["step"] == "await_guests"
    assert not where[2].get("district")
    assert "район" not in where[0][0].lower()
    assert "сколько вас будет" in where[0][0].lower()


def test_ping_after_outreach_keeps_january_and_dog() -> None:
    sess = {
        "step": "handed_off",
        "dates": "",
        "guests": "",
        "district": "",
        "handed_off": 1,
        "context": {"pets": "собака", "greeted": True},
    }
    history = [
        {"role": "guest", "text": "Да я думала на Новый год заехать с собакой"},
        {"role": "guest", "text": "Ну может в январе"},
        {"role": "bot", "text": "Точную цену передам менеджеру."},
        {"role": "guest", "text": "Ничего не поняла"},
    ]
    out = _craft_early(sess, "Привет\nЗдарова\nКу-ку епта\nДядь", history)
    assert out is not None
    blob = out[0][0].lower()
    assert "январ" in blob
    assert "собак" in blob or "животн" in blob
    assert "район" in blob or "сколько вас" in blob
    assert "заковырист" not in blob
    assert "по делу" not in blob
    assert out[2]["dates"] == "в январе"
    assert out[2]["step"] in ("await_district", "await_guests")


def test_price_on_month_asks_dates_without_handoff() -> None:
    sess = {
        "step": "await_guests",
        "dates": "в январе",
        "guests": "",
        "district": "",
        "handed_off": 0,
        "context": {"pets": "собака"},
    }
    out = _craft_early(sess, "А какая цена?", [])
    assert out is not None
    blob = out[0][0].lower()
    assert "январ" in blob
    assert "собак" in blob
    assert "на какие даты" in blob
    assert "число людей" not in blob
    assert "жду числа" not in blob
    assert out[3] is False
    assert out[2].get("handed_off") != 1
    assert out[2]["step"] == "await_dates"
    assert out[2]["dates"] == "в январе"
    assert (out[2].get("context") or {}).get("reply_path") == "smart:rule/calendar-span"


def test_model_does_not_invent_guest_count() -> None:
    slots = _normalize_slots(
        {"guests": "4", "dates": "с 1 по 5 февраля", "budget": "до 9000 ₽", "pets": "собака"},
        "А какая цена?",
        {"dates": "в январе", "guests": "", "context": {}},
    )
    assert "guests" not in slots
    assert slots.get("dates") == "в январе"
    assert "budget" not in slots
    assert "pets" not in slots


# ── v10.4: менеджер молчит 15 минут → бот сам отвечает на сообщения, пришедшие в паузу ──

def test_unanswered_after_hold_waits_full_pause() -> None:
    from bot.handoff_hold import unanswered_after_hold

    now = time.time()
    msgs = [
        {"id": 1, "role": "bot", "text": "Сейчас подключу менеджера, он напишет вам здесь минут через 10–15.", "created_at": now - 600},
        {"id": 2, "role": "guest", "text": "А с собакой можно?", "created_at": now - 300},
    ]
    assert unanswered_after_hold(msgs, now=now) == []  # прошло 10 минут — ещё ждём менеджера
    later = now + 6 * 60  # 16 минут после передачи
    got = unanswered_after_hold(msgs, now=later)
    assert [m["id"] for m in got] == [2]


def test_unanswered_after_hold_manager_answered() -> None:
    from bot.handoff_hold import unanswered_after_hold

    now = time.time()
    msgs = [
        {"id": 1, "role": "bot", "text": "Сейчас подключу менеджера", "created_at": now - 3600},
        {"id": 2, "role": "guest", "text": "Жду", "created_at": now - 3500},
        {"id": 3, "role": "manager", "text": "Здравствуйте! Я тут", "created_at": now - 3400},
    ]
    assert unanswered_after_hold(msgs, now=now) == []  # менеджер ответил — бот не лезет
    msgs.append({"id": 4, "role": "guest", "text": "А парковка есть?", "created_at": now - 600})
    got = unanswered_after_hold(msgs, now=now)  # менеджер молчит уже ~57 минут после своей реплики
    assert [m["text"] for m in got] == ["А парковка есть?"]


def test_unanswered_after_hold_collects_all_guest_messages() -> None:
    from bot.handoff_hold import unanswered_after_hold

    now = time.time()
    msgs = [
        {"id": 1, "role": "bot", "text": "Сейчас подключу менеджера", "created_at": now - 1000},
        {"id": 2, "role": "guest", "text": "Алло", "created_at": now - 900},
        {"id": 3, "role": "guest", "text": "Нам на выходные, двое", "created_at": now - 800},
    ]
    got = unanswered_after_hold(msgs, now=now)
    assert [m["id"] for m in got] == [2, 3]


def test_store_lists_held_chats() -> None:
    import tempfile

    from bot.store import Store

    with tempfile.TemporaryDirectory() as td:
        st = Store(str(Path(td) / "h.db"))
        st.save_session("100", handed_off=1, step="handed_off", manager_id="anna")
        st.save_session("200", handed_off=0, step="await_dates", manager_id="anna")
        st.save_session("300", handed_off=1, step="handed_off", manager_id="olga")
        assert set(st.list_held_chats(manager_id="anna")) == {"100"}
        assert set(st.list_held_chats()) == {"100", "300"}


def test_reply_after_hold_continues_funnel() -> None:
    """После паузы бот отвечает на вопрос гостя и продолжает с того, что ещё не выяснено."""
    import asyncio

    from bot import smart as smart_mod
    from bot.ai import reply
    from bot.config import get_settings
    from bot.engine import Engine
    from bot.handoff_hold import resume_step

    async def _no_llm(system, messages):
        return None

    sess = {"name": "Ия", "step": "handed_off", "handed_off": 1, "dates": "с 3 по 6 декабря", "guests": "3",
            "district": "", "returning": "да", "context": {}}
    # что делает _stay_quiet_for_manager, когда пауза истекла
    sess["handed_off"] = 0
    sess["step"] = resume_step(sess)
    history = [
        {"role": "bot", "text": "Сейчас подключу менеджера, он напишет вам здесь минут через 10–15."},
        {"role": "guest", "text": "А с собакой можно?"},
    ]
    smart_mod.set_understand_hook(_no_llm)
    try:
        s = get_settings()
        msgs, _b, upd, esc = asyncio.run(reply(s, Engine(s), sess, "А с собакой можно?", history))
    finally:
        smart_mod.set_understand_hook(None)
    blob = " ".join(msgs).lower()
    assert msgs and not esc
    assert "питом" in blob or "собак" in blob or "животн" in blob
    assert "на какие даты" not in blob and "сколько вас" not in blob


def test_take_unanswered_once_per_batch() -> None:
    import tempfile

    from bot.handoff_hold import take_unanswered
    from bot.store import Store

    with tempfile.TemporaryDirectory() as td:
        st = Store(str(Path(td) / "t.db"))
        st.save_session("500", handed_off=1, step="handed_off", manager_id="anna")
        st.add_message("500", "bot", "Сейчас подключу менеджера, он напишет вам здесь минут через 10–15.", manager_id="anna")
        st.add_message("500", "guest", "Алло", manager_id="anna")
        st.add_message("500", "guest", "Нам на выходные", manager_id="anna")
        now = time.time()
        assert take_unanswered(st, "500", "anna", now=now) == ""  # пауза ещё идёт
        later = now + 16 * 60
        assert take_unanswered(st, "500", "olga", now=later) == ""  # чужой менеджер
        assert take_unanswered(st, "500", "anna", now=later) == "Алло\nНам на выходные"
        assert take_unanswered(st, "500", "anna", now=later + 60) == ""  # второй раз не отвечаем
        st.add_message("500", "guest", "Ау?", manager_id="anna")
        assert take_unanswered(st, "500", "anna", now=later + 120) == "Алло\nНам на выходные\nАу?"
        st.mark_stopped(chat_id="500")
        st.add_message("500", "guest", "Ещё", manager_id="anna")
        assert take_unanswered(st, "500", "anna", now=later + 180) == ""  # стоп-лист


# ── v10.5 (скрин 33, 11.11) ──

def test_already_answered_blocks_duplicate() -> None:
    from bot.handoff_hold import already_answered

    now = time.time()
    line = "С питомцами можно не во всех квартирах, подберу такие, где можно."
    msgs = [
        {"role": "guest", "text": "А с собакой можно?", "created_at": now - 120},
        {"role": "bot", "text": line, "created_at": now - 60},
    ]
    assert already_answered(msgs, [line], now=now)
    assert not already_answered(msgs, ["Другой ответ"], now=now)
    assert not already_answered(msgs, [line], now=now + 3600)  # давно — это уже новый разговор


def test_take_unanswered_shares_claim_with_restart_resume() -> None:
    import tempfile

    from bot.handoff_hold import take_unanswered
    from bot.store import Store

    with tempfile.TemporaryDirectory() as td:
        st = Store(str(Path(td) / "c.db"))
        st.save_session("700", handed_off=1, step="handed_off")
        st.add_message("700", "bot", "Сейчас подключу менеджера")
        st.add_message("700", "guest", "А с собакой можно?")
        last_id = st.recent_messages("700")[-1]["id"]
        assert st.claim_meta(f"resume:700:{last_id}")  # «догон» после рестарта уже взял
        assert take_unanswered(st, "700", now=time.time() + 16 * 60) == ""


def test_free_offer_cards_from_calendar() -> None:
    from datetime import date

    from bot.travelline import Stay, free_offer_cards, set_search_hook

    set_search_hook(lambda a, d, n: [
        Stay(room_id="1", title="Малевич", address="Москва, ул. Пример, 1", price_night=3162, price_total=6324, available=1),
        Stay(room_id="2", title="Юниверсал", address="Москва, ул. Пример, 2", price_night=3069, price_total=6138, available=1),
    ])
    try:
        text, names = free_offer_cards("с 5 по 7 декабря", 2, today=date(2026, 11, 11))
    finally:
        set_search_hook(None)
    assert names == ["Юниверсал", "Малевич"]
    assert "1) «Юниверсал»" in text and "6 138" in text
    assert "номер (1–2)" in text


def test_ok_is_not_a_district_for_calendar() -> None:
    from bot.travelline import Stay, set_search_hook

    set_search_hook(lambda a, d, n: [])
    try:
        sess = {"step": "await_returning", "dates": "с 5 по 7 декабря", "guests": "2", "district": "",
                "returning": "да", "context": {}}
        hist = [{"role": "bot", "text": "С питомцами можно не во всех квартирах, подберу такие, где можно."}]
        out = _craft_early(sess, "Хорошо", hist)
    finally:
        set_search_hook(None)
    assert out is not None
    blob = " ".join(out[0])
    assert "«Хорошо»" not in blob
    assert blob == "😊"


# ── v10.6 (скрин 66, 11.11): свободные из календаря → выбор, «ещё варианты» ──

def _tl_hook_two():
    from bot.travelline import Stay

    return lambda a, d, n: [
        Stay(room_id="2", title="Карма", address="Москва, Прокшинский проспект, д. 9", price_night=4371, price_total=17484, available=1),
        Stay(room_id="3", title="Юниверсал", address="Москва, ул. Пример, д. 1", price_night=3069, price_total=12276, available=1),
    ]


def _calendar_turn(text, sess, hist):
    from bot.travelline import set_search_hook

    set_search_hook(_tl_hook_two())
    try:
        return _craft_early(sess, text, hist)
    finally:
        set_search_hook(None)


def test_single_free_flat_wording_and_yes_books_it() -> None:
    sess = {"step": "await_district", "dates": "с 20 по 24 декабря", "guests": "2", "district": "",
            "returning": "да", "context": {}}
    out = _calendar_turn("Прокшино", sess, [{"role": "bot", "text": "С 20 по 24 декабря, двое. Какой район вам удобнее?"}])
    assert out is not None
    line = out[0][0]
    assert line.startswith("Прокшино, 20–24 декабря: по календарю свободна «Карма»")
    assert "Какая ближе" not in line and "По «Прокшино»" not in line
    sess2 = {**sess, **{k: v for k, v in out[2].items() if k != "context"}, "context": out[2]["context"]}
    hist = [{"role": "bot", "text": line}]
    for yes in ("Да", "давайте", "Карма", "1"):
        got = _calendar_turn(yes, dict(sess2), hist)
        assert got is not None, yes
        assert got[3] is True and got[2].get("favorite") == "Карма", yes
        assert "Отлично, «Карма» на 20–24 декабря" in got[0][0]


def test_more_variants_from_calendar() -> None:
    sess = {"step": "await_returning", "dates": "с 20 по 24 декабря", "guests": "2", "district": "Прокшино",
            "returning": "да", "context": {"tl_offers": ["Карма"], "tl_dates": "с 20 по 24 декабря"}}
    hist = [{"role": "bot", "text": "Прокшино, 20–24 декабря: по календарю свободна «Карма». Передать менеджеру на бронь?"}]
    out = _calendar_turn("а ещё варианты есть?", sess, hist)
    assert out is not None and out[3] is False
    assert "«Юниверсал»" in out[0][0] and "«Карма»" not in out[0][0]
    assert out[2]["context"]["tl_offers"] == ["Юниверсал"]


def test_yes_after_slots_is_not_outreach_consent() -> None:
    from bot.phrases import outreach_offer

    sess = {"context": {"offer_open": True, "offer": "need"}}
    assert outreach_offer(sess, "Добрый вечер! Это Home24… Может, скоро понадобится?") == "need"
    assert outreach_offer(sess, "Прокшино, 20–24 декабря: по календарю свободна «Карма». Передать менеджеру на бронь?") == ""


# ── v10.7 (скрины 22–24): «центр» не подменяется Одинцово, у карточек район и метро ──

def test_center_cards_are_central_or_honest() -> None:
    from datetime import date

    from bot.travelline import Stay, free_offer_cards, set_search_hook

    mk = lambda i, n, p: Stay(room_id=str(i), title=n, address="x", price_night=p, price_total=p * 2, available=1)
    set_search_hook(lambda a, d, n: [mk(1, "Малевич", 3424), mk(2, "Чехов", 4100)])
    try:
        text, names = free_offer_cards("с 15 по 17 ноября", 2, district="центр", today=date(2026, 11, 11))
    finally:
        set_search_hook(None)
    assert names == ["Чехов"]
    assert "Басманный, м. Бауманская" in text
    set_search_hook(lambda a, d, n: [mk(1, "Малевич", 3424), mk(3, "Юниверсал", 3638)])
    try:
        text, names = free_offer_cards("с 15 по 17 ноября", 2, district="центр", today=date(2026, 11, 11))
    finally:
        set_search_hook(None)
    assert text.startswith("В центре на эти даты по календарю свободных нет")
    assert "Одинцово, МЦД-1" in text and "Котельники, м. Котельники" in text
    assert "home24.msk.ru" in text  # ссылок на квартиры нет — одна ссылка на сайт


def test_deposit_facts() -> None:
    from bot.smart import _NAIVE_FACTS

    def fact(t):
        return [f for r, f in _NAIVE_FACTS if r.search(t)][0]

    assert "2 000 ₽" in fact("А залог у вас сколько?")
    assert fact("как возвращается залог?").startswith("Залог возвращаем после выезда")


def test_site_links_from_script() -> None:
    from bot.apartments_map import link_for

    assert link_for("Чехов").startswith("https://home24.msk.ru/apartments/")
    assert link_for("Матисс") and link_for("Скандинавия") and link_for("Сноу пикс")
    assert link_for("Неизвестная") == ""


def test_avail_request_keeps_district_and_rechecks_for_guests() -> None:
    from bot.travelline import Stay, set_search_hook

    set_search_hook(lambda a, d, n: [Stay(room_id="2", title="Карма", address="Москва, Прокшинский проспект, д. 9",
                                          price_night=4433, price_total=13299 if n < 3 else 15699, available=1)])
    try:
        sess = {"step": "await_dates", "dates": "", "guests": "", "district": "", "returning": "да", "context": {}}
        out = _craft_early(sess, "Пришлите свободные квартиры в Прокшино с 12.12 - 15.12", [])
        assert out is not None and out[2]["district"] == "Прокшино"
        assert "Сколько вас будет" in out[0][0]
        sess2 = {**sess, "dates": out[2]["dates"], "district": "Прокшино", "context": out[2]["context"]}
        got = _craft_early(sess2, "3", [{"role": "bot", "text": out[0][0]}])
    finally:
        set_search_hook(None)
    assert got is not None
    assert got[0][0].startswith("Трое. Прокшино, 12–15 декабря")
    assert "15 699" in got[0][0] and got[2]["guests"] == "3"
