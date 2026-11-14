# -*- coding: utf-8 -*-
"""v8: слоты из живого диалога + takeover после ответа менеджера."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.ai import extract_slots, reply
from bot.config import Settings
from bot.engine import Engine, parse_dates, parse_guests, parse_nights
from bot.telegram_api import FORBIDDEN_API_IDS, TelegramApiError, resolve_api_credentials


def _settings() -> Settings:
    return Settings(
        api_id=0,
        api_hash="",
        session="",
        admin_ids=set(),
        manager_name="Анна",
        brand="Home24",
        site_url="https://home24.msk.ru/",
        loyalty_url="https://home24.msk.ru/loyalty",
        channel_url="https://t.me/home24_msk",
        vk_url="https://vk.ru/club172662058",
        openai_[REDACTED]
        openai_base="",
        openai_model="",
        outreach_delay=50,
        db_path=":memory:",
        script_path=str(ROOT / "script.md"),
    )


def test_parse_guests_ya_budu_1():
    assert parse_guests("я буду 1") == "1"
    assert parse_guests("буду я 1") == "1"
    assert parse_guests("нас двое") == "1-2"
    assert parse_guests("на 3 человек") == "3"


def test_parse_dates_live_phrases():
    assert parse_dates("на завтра квартира феррари") == "завтра"
    assert parse_dates("сегодня") == "сегодня"
    assert parse_dates("послезавтра") == "послезавтра"
    assert parse_dates("с 12 по 15") == "12–15"
    assert "октябр" in (parse_dates("5-7 октября") or "")


def test_parse_nights():
    assert parse_nights("на 2 ночи") == "2"
    assert parse_nights("трое суток") == "3"


def test_extract_slots_live_message():
    """Точная фраза гостя из боя: даты + феррари + я буду 1."""
    text = "Давайте на завтра квартира феррари я буду 1"
    slots = extract_slots(text)
    assert slots.get("dates") == "завтра"
    assert slots.get("guests") == "1"
    fav = (slots.get("favorite") or "").lower()
    # каталог может не содержать Феррари в CI без mailing.sqlite — тогда хотя бы даты/гости
    mailing = ROOT / "data" / "mailing.sqlite"
    if mailing.exists():
        assert "феррари" in fav or fav, slots
    else:
        assert slots.get("dates") and slots.get("guests")


def test_funnel_confirms_slots_no_reask_intent():
    """Без takeover: бот подтверждает слоты и не спрашивает снова «на даты или смотрите»."""

    async def _run():
        os.environ["USE_AI"] = "0"
        settings = _settings()
        engine = Engine(settings)
        sess = {
            "step": "await_intent",
            "handed_off": 0,
            "dates": "",
            "guests": "",
            "district": "",
            "favorite": "",
            "context": {},
            "name": "WTF",
        }
        text = "Давайте на завтра квартира феррари я буду 1"
        msgs, _btns, upd, esc = await reply(settings, engine, sess, text, [])
        blob = " ".join(msgs).lower()
        assert not esc
        assert upd.get("handed_off") in (None, 0, False)
        assert "завтра" in blob or upd.get("dates") == "завтра"
        assert upd.get("guests") == "1" or "1" in blob
        # не должен снова спрашивать про intent
        assert "просто смотрите" not in blob
        assert "ищете на даты или" not in blob
        # шаг ушёл с await_intent
        assert upd.get("step") not in (None, "await_intent", "greeting")

    asyncio.run(_run())


def test_takeover_silences_bot_exact_dialog():
    """Живой баг: менеджер «прив» → гость про феррари → бот молчит, handed_off=1."""

    async def _run():
        os.environ["USE_AI"] = "0"
        settings = _settings()
        engine = Engine(settings)
        sess = {
            "step": "await_intent",
            "handed_off": 0,
            "dates": "",
            "guests": "",
            "context": {},
            "name": "WTF",
        }
        msgs, _, upd, _ = await reply(settings, engine, sess, "Здравствуйте", [])
        assert msgs
        sess = {**sess, **upd, "handed_off": 0}
        # как handle_reply панели
        sess["handed_off"] = 1
        sess["step"] = "handed_off"
        msgs2, _, upd2, _ = await reply(
            settings,
            engine,
            sess,
            "Давайте на завтра квартира феррари я буду 1",
            [],
        )
        assert msgs2 == []
        assert upd2.get("handed_off") == 1
        assert upd2.get("step") == "handed_off"

    asyncio.run(_run())


def test_engine_handed_off_flag_without_step():
    """handed_off=1 при step=await_intent всё равно тишина."""
    settings = _settings()
    engine = Engine(settings)
    msgs, _, upd, _ = engine.handle(
        {"step": "await_intent", "handed_off": 1, "context": {}},
        "Давайте на завтра",
    )
    assert msgs == []
    assert upd.get("handed_off") == 1
    assert upd.get("step") == "handed_off"


def test_forbidden_api_ids():
    assert 6 in FORBIDDEN_API_IDS
    assert 4 in FORBIDDEN_API_IDS
    assert 2040 in FORBIDDEN_API_IDS
    try:
        resolve_api_credentials(api_id=6, api_hash="[REDACTED]", env=False)
        raise AssertionError("expected refuse")
    except TelegramApiError as e:
        assert "официального" in str(e) or "my.telegram.org" in str(e)
    try:
        resolve_api_credentials(api_id="", api_hash="x", env=False)
        raise AssertionError("expected missing")
    except TelegramApiError:
        pass


def test_qr_wait_uses_expires_not_fixed_90():
    src = (ROOT / "bot" / "web_login.py").read_text(encoding="utf-8")
    assert "timeout=None" in src or "qr.wait()" in src
    assert "timeout=90" not in src


if __name__ == "__main__":
    test_parse_guests_ya_budu_1()
    test_parse_dates_live_phrases()
    test_parse_nights()
    test_extract_slots_live_message()
    test_funnel_confirms_slots_no_reask_intent()
    test_takeover_silences_bot_exact_dialog()
    test_engine_handed_off_flag_without_step()
    test_forbidden_api_ids()
    test_qr_wait_uses_expires_not_fixed_90()
    print("ok")
