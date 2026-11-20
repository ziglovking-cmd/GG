# -*- coding: utf-8 -*-
"""v9.2 — зона района, одна сводка, correction без resend, path logging."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot.ai import reply
from bot.catalog import (
    classify_zone,
    fits_district,
    pick_apartments_with_note,
    reason_for_offer,
    _connect,
    _row_public,
    DEFAULT_PATH,
)
from bot.config import get_settings
from bot.engine import Engine, normalize_dates_phrase, parse_dates, parse_guests
from bot import smart as smart_mod


def _j(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def _mock(payload: dict):
    async def _hook(system, messages, **_k):
        return _j(**payload), "mock/v9.2"

    return _hook


def _sess(**kw):
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


async def _turn(sess, text, history, payload):
    smart_mod.set_understand_hook(_mock(payload))
    try:
        s = get_settings()
        e = Engine(s)
        msgs, _b, upd, esc = await reply(s, e, sess, text, history)
        for k, v in upd.items():
            if k == "context":
                sess["context"] = v
            elif v not in (None, ""):
                sess[k] = v
        if esc:
            sess["handed_off"] = 1
        history.append({"role": "guest", "text": text})
        for m in msgs:
            history.append({"role": "bot", "text": m})
        return msgs, upd, esc
    finally:
        smart_mod.set_understand_hook(None)


def test_zone_homlin_not_center() -> None:
    con = _connect(DEFAULT_PATH)
    rows = [_row_public(r) for r in con.execute("SELECT * FROM objects")]
    con.close()
    by = {o["name"]: o for o in rows}
    assert by["Хомлин"]["zone"] == "calm"
    assert not by["Хомлин"]["is_central"]
    assert by["Чехов"]["is_central"]
    assert by["Дюма"]["is_central"]
    # Прокшино / Коммунарка never center
    for o in rows:
        metro = (o.get("metro") or "").lower()
        if "прокшин" in metro or "коммунарк" in metro:
            assert not o["is_central"], o["name"]


def test_center_pick_hard_filter() -> None:
    objs, note = pick_apartments_with_note(district="центр", guests="3", limit=3)
    assert objs
    for o in objs:
        assert o["is_central"] or o["zone"] == "center", (o["name"], o["zone"], note)
        why = reason_for_offer(o, district="центр", guests="3")
        assert "прокшин" not in why.lower()
        assert "коммунарк" not in why.lower()
        # meaningful
        assert why and why.lower() != "москва"
        assert "до 4 гостей" not in why or "в центре" in why


def test_reason_never_claims_center_for_outer() -> None:
    con = _connect(DEFAULT_PATH)
    rows = [_row_public(r) for r in con.execute("SELECT * FROM objects")]
    con.close()
    outer = next(o for o in rows if "прокшин" in (o.get("metro") or "").lower())
    why = reason_for_offer(outer, district="центр", guests="2")
    assert "в центре" not in why.lower()


def test_dates_grammar() -> None:
    assert normalize_dates_phrase("1 по 7 января") == "с 1 по 7 января"
    assert parse_dates("1 по 7 января") == "с 1 по 7 января"
    assert parse_guests("нас двое и ребёнок") == "3"


def test_district_english_normalized() -> None:
    from bot.catalog import district_preference
    from bot.smart import _normalize_district_label

    assert _normalize_district_label("center") == "центр"
    assert _normalize_district_label("calm") == "спокойный район"
    assert district_preference("center") == "center"
    objs, _ = pick_apartments_with_note(district="center", guests="3", limit=3)
    assert objs and all(o["is_central"] for o in objs)


async def _sc_one_summary() -> None:
    sess = _sess()
    msgs, upd, _ = await _turn(
        sess,
        "январь 1–7, 3 человека, центр, можно с собакой?",
        [{"role": "bot", "text": "Добрый день! Это Home24."}],
        {
            "intent": "multi",
            "slots": {
                "dates": "1 по 7 января",
                "guests": "3",
                "district": "центр",
                "pets": "собака",
            },
            "messages": [
                "Поняла: с 1 по 7 января на 3 человек в центре. Подберу с парковкой. Метро или цена?"
            ],
            "ask_next": "returning",
            "attach_offers": True,
            "offer_names": ["Чехов", "Дюма", "Диккенс"],
            "escalate": False,
        },
    )
    assert len(msgs) <= 2, msgs
    blob = "\n".join(msgs)
    # одна сводка — не два «Отметила/Поняла» блока про даты
    leads = sum(
        1
        for w in ("записала:", "приняла:", "отметила:", "хорошо, зафиксировала:")
        if w in blob.lower()
    )
    assert leads <= 1, blob
    assert "на 3 человек" not in blob.lower()
    assert "парковк" not in blob.lower() or "собак" in blob.lower()
    assert upd.get("guests") == "3"
    dates = str(upd.get("dates") or "")
    assert dates.startswith("с ") or "с 1" in dates
    offers = (upd.get("context") or {}).get("offers") or []
    for name in offers:
        from bot.catalog import find_by_name

        hit = find_by_name(name)
        assert hit and hit.get("is_central"), (name, hit)


def test_one_summary_and_center_offers() -> None:
    asyncio.run(_sc_one_summary())


async def _sc_correction_no_resend() -> None:
    # все три вмещают 4
    sess = _sess(
        dates="с 1 по 7 января",
        guests="3",
        district="центр",
        step="await_returning",
        context={"greeted": True, "offers": ["Чехов", "Дюма", "Олимп"]},
    )
    msgs, upd, _ = await _turn(
        sess,
        "не 3 а 4 человека",
        [{"role": "bot", "text": "1) Чехов\n2) Дюма\n3) Олимп"}],
        {
            "intent": "correction",
            "slots": {"guests": "4", "dates": "с 1 по 7 января", "district": "центр"},
            "messages": ["ок"],
            "ask_next": "pick",
            "attach_offers": True,
            "offer_names": ["Чехов", "Дюма", "Олимп"],
            "escalate": False,
        },
    )
    blob = "\n".join(msgs)
    assert "Поняла, 4 человека" in blob or "поняла, 4" in blob.lower()
    assert "вмест" in blob.lower() or "4" in blob
    # не полные карточки снова
    assert "Почему подходит" not in blob
    assert "1)" not in blob
    assert upd.get("guests") == "4"


def test_correction_keeps_cards_if_fit() -> None:
    asyncio.run(_sc_correction_no_resend())


def test_prokshino_not_kommunarka() -> None:
    objs, note = pick_apartments_with_note(district="Прокшино", guests="2", limit=3)
    assert objs, note
    for o in objs:
        blob = f"{o.get('metro') or ''} {o.get('area') or ''}".lower()
        assert "прокшин" in blob, (o["name"], blob)
        assert "коммунарк" not in blob
    assert fits_district(
        {"metro": "Коммунарка · 12 минут пешком", "area": "Коммунарка", "zone": "calm"},
        "Прокшино",
    ) is False


def test_guest_place_beats_calm_slot() -> None:
    async def _run():
        sess = _sess()
        msgs, upd, _ = await _turn(
            sess,
            "Есть в планах приехать в Прокшино с 1-4 ноября на праздники.",
            [{"role": "bot", "text": "Добрый день! Это Home24."}],
            {
                "intent": "looking",
                "slots": {
                    "dates": "с 1 по 4 ноября",
                    "district": "спокойный район",
                    "guests": None,
                },
                "messages": [
                    "Поняла, Прокшино на праздники — подходит квартира «Бриз» за 4280 ₽/сутки. На сколько человек планируете."
                ],
                "ask_next": "guests",
                "attach_offers": True,
                "offer_names": ["Бриз", "Феррари", "Россо"],
                "escalate": False,
            },
        )
        blob = "\n".join(msgs)
        assert upd.get("district") == "Прокшино", upd.get("district")
        assert "Коммунарка" not in blob
        assert "Феррари" not in blob
        assert "Россо" not in blob
        assert "Подобрала несколько" not in blob
        assert "человек" in blob.lower() or "гост" in blob.lower()

    asyncio.run(_run())


def test_reply_path_logged() -> None:
    async def _run():
        sess = _sess(step="await_dates")
        msgs, upd, _ = await _turn(
            sess,
            "какая погода",
            [],
            {"intent": "chitchat", "messages": ["+5"]},
        )
        path = (upd.get("context") or {}).get("reply_path") or ""
        assert path.startswith("smart"), path
        assert "не проверяю" in "\n".join(msgs).lower()

    asyncio.run(_run())


def test_all_v9_2() -> None:
    test_zone_homlin_not_center()
    test_center_pick_hard_filter()
    test_reason_never_claims_center_for_outer()
    test_dates_grammar()
    test_one_summary_and_center_offers()
    test_correction_keeps_cards_if_fit()
    test_prokshino_not_kommunarka()
    test_guest_place_beats_calm_slot()
    test_reply_path_logged()
    print("ok v9.2 district/llm")


if __name__ == "__main__":
    test_all_v9_2()
