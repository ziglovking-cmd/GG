"""Регрессии: pick без цикла, привет ≠ как дела, слоты из составного."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.catalog import parse_offer_pick, wants_variants
from bot.config import get_settings
from bot.engine import Engine, keyword_intent, parse_returning
from bot import phrases as P


def test_parse_picks() -> None:
    assert parse_offer_pick("Так хорошо 3 вариант мне подходит") == 3
    assert parse_offer_pick("1 меня устраивает") == 1
    assert parse_offer_pick("беру 2") == 2
    assert parse_offer_pick("первый") == 1
    assert parse_offer_pick("привет") is None
    # выбор ≠ просьба каталога
    assert wants_variants("3 вариант мне подходит") is False
    assert wants_variants("1 меня устраивает") is False
    assert wants_variants("ещё варианты") is True
    assert wants_variants("сначала посмотрим квартиры") is True
    assert wants_variants("можно сначала варианты") is True
    assert wants_variants("покажите варианты") is True
    assert wants_variants("скиньте варианты") is True


def test_hello_not_howareyou() -> None:
    assert keyword_intent("Здравствуйте") == "hello"
    assert keyword_intent("привет") == "hello"
    assert keyword_intent("как дела") == "howareyou"
    assert keyword_intent("сначала посмотрим") == "browsing"
    # HELLO_MID не отвечает «у меня всё отлично»
    for variant in P.HELLO_MID:
        blob = " ".join(variant).lower()
        assert "отлично" not in blob
        assert "у меня всё" not in blob


def test_returning() -> None:
    assert parse_returning("Нет не был") == "нет"
    assert parse_returning("впервые") == "нет"
    assert parse_returning("да были") == "да"
    assert parse_returning("я у вас уже был") == "да"
    assert parse_returning("уже был") == "да"
    assert parse_returning("был у вас") == "да"


def test_dates_and_dump() -> None:
    from bot.engine import parse_dates, parse_district, parse_guests

    assert parse_dates("Ну ориентировочно на 26") == "на 26"
    assert parse_dates("26-27") == "26–27"
    assert parse_dates("на вторник след недели") == "следующий вторник"
    assert parse_dates("квартиру Феррари на 13 часов") == "на 13"
    assert parse_guests("с ребёнком на 26-27") == "2"
    assert parse_guests("буду я 1") == "1"
    assert parse_guests("и буду я 1") == "1"
    assert parse_district("нужна тихая") == "спокойный район"


def test_ferrari_compound_slots() -> None:
    """Парсеры для живого кейса: Феррари + 13 + 1 гость + уже был."""
    from bot.ai import extract_slots

    text = "Да я у вас уже был думаю можно квартиру Феррари на 13 часов и буду я 1"
    slots = extract_slots(text)
    assert slots.get("dates") == "на 13"
    assert slots.get("guests") == "1"
    assert slots.get("returning") == "да"


def test_thanks_not_blocked_by_zhdat() -> None:
    """«буду ждать» не должно матчить запрет «дат» как дату."""
    import re

    low = "спасибо буду ждать❤️"
    thanks_post = bool(
        re.search(
            r"(?i)спасиб|благодар|буду\s*ждать|\bжду\b|ок\.?$|хорошо\.?$",
            low,
        )
    ) and not re.search(
        r"(?i)ещё|еще|хочу|брон|квартир|вариант|\bдат[аые]|\bищ[уёе]|подбер",
        low,
    )
    assert thanks_post is True
    # старый баг: «дат» внутри «ждать»
    assert re.search(r"(?i)дат", low)  # сырой «дат» есть
    assert not re.search(r"(?i)\bдат[аые]", low)


async def _run_engine() -> None:
    s = get_settings()
    e = Engine(s)

    # привет mid-воронки — не «как дела»
    msgs, _, upd, _ = e.handle({"step": "await_guests", "dates": "пн"}, "Здравствуйте")
    assert upd.get("step") in (None, "await_guests") or "step" not in upd or upd["step"] == "await_guests"
    blob = " ".join(msgs).lower()
    assert "отлично" not in blob
    assert "человек" in blob or "сколько" in blob or "гост" in blob or "дат" in blob

    # howareyou отдельно
    msgs2, _, _, _ = e.handle({"step": "await_intent"}, "как дела?")
    blob2 = " ".join(msgs2).lower()
    assert any(
        x in blob2 for x in ("хорошо", "норм", "отлично", "связи", "квартир", "дат", "ищет")
    )

    # looking mid-funnel не сбрасывает
    msgs3, _, upd3, _ = e.handle(
        {"step": "await_dates", "dates": ""}, "Ищу квартиру"
    )
    assert upd3.get("step") != "await_intent"
    assert any("дат" in m.lower() for m in msgs3)

    # pick 3 на await_returning
    offers = ["А", "Б", "Чехов"]
    msgs4, _, upd4, esc4 = e.handle(
        {
            "step": "await_returning",
            "dates": "пн",
            "guests": "1",
            "district": "центр",
            "context": {"offers": offers},
        },
        "3 вариант мне подходит",
    )
    assert upd4.get("favorite") == "Чехов"
    assert esc4 is False
    assert "чехов" in " ".join(msgs4).lower()
    # не должно быть нового каталога
    assert "вот несколько" not in " ".join(msgs4).lower()

    # после favorite + нет не был → handoff
    msgs5, _, upd5, esc5 = e.handle(
        {
            "step": "await_returning",
            "dates": "пн",
            "guests": "1",
            "district": "центр",
            "favorite": "Чехов",
            "context": {"offers": offers},
        },
        "Нет не был",
    )
    assert esc5 is True
    assert upd5.get("step") == "done"
    assert upd5.get("favorite") == "Чехов"
    assert "вот несколько" not in " ".join(msgs5).lower()

    # browsing pick с offers
    msgs6, _, upd6, _ = e.handle(
        {"step": "done", "context": {"offers": ["Феррари", "Чаплин", "Чехов"]}},
        "1 меня устраивает",
    )
    assert upd6.get("favorite") == "Феррари"
    assert upd6.get("step") == "await_dates"
    assert "феррари" in " ".join(msgs6).lower()

    # составное looking со слотами
    msgs7, _, upd7, _ = e.handle(
        {"step": "await_intent"},
        "подберите квартиру я думаю в центре буду 1",
    )
    assert upd7.get("guests") == "1" or upd7.get("step") in (
        "await_dates",
        "await_guests",
        "await_district",
        "await_returning",
    )
    # не должен сразу кинуть browsing-меню без дат
    assert upd7.get("step") != "browsing"

    # favorite уже есть → после гостей не каталог
    msgs8, _, upd8, _ = e.handle(
        {
            "step": "await_guests",
            "dates": "пн",
            "favorite": "Чехов",
        },
        "2 человека",
    )
    assert upd8.get("step") == "await_returning"
    assert "вот несколько" not in " ".join(msgs8).lower()
    assert "чехов" in " ".join(msgs8).lower()

    # mid-funnel «сначала посмотрим» → карточки, шаг дат не сбрасывается
    msgs9, _, upd9, _ = e.handle(
        {"step": "await_dates", "dates": "", "guests": "", "district": ""},
        "сначала посмотрим квартиры?",
    )
    blob9 = " ".join(msgs9).lower()
    assert "вот несколько" in blob9 or "вариант" in blob9
    assert upd9.get("step") in (None, "await_dates") or upd9.get("step") == "await_dates"

    # await_district не глотает «можно сначала варианты» как район
    msgs10, _, upd10, _ = e.handle(
        {
            "step": "await_district",
            "dates": "на 27",
            "guests": "5",
        },
        "можно сначала варианты",
    )
    blob10 = " ".join(msgs10).lower()
    assert "можно сначала варианты" not in blob10
    assert upd10.get("district") == "не принципиально"
    assert "вот несколько" in blob10 or "вариант" in blob10

    # гости в сводке без «? человек»
    msgs11, _, upd11, _ = e.handle(
        {"step": "await_district", "dates": "пн", "guests": "2"},
        "центр",
    )
    assert "Поняла: пн, 2 человека, центр." in msgs11[0]
    assert "? человек" not in " ".join(msgs11)
    assert "2" in " ".join(msgs11)

    print("OK engine regressions")


async def _run_ai_happy() -> None:
    from bot.ai import reply

    s = get_settings()
    e = Engine(s)
    sess = {
        "name": "Тест",
        "step": "await_intent",
        "dates": "",
        "guests": "",
        "district": "",
        "handed_off": 0,
        "context": {},
    }
    flow = [
        "Ищу квартиру нас будет около 5 в тихом районе на 27",
        "Не был а можете предложить варианты я просто не знаю ваши квартиры",
        "1",
    ]
    for text in flow:
        msgs, _, upd, esc = await reply(s, e, sess, text, [])
        for k, v in upd.items():
            if k == "context":
                sess["context"] = v
            elif v is not None and v != "":
                sess[k] = v
        if esc:
            sess["handed_off"] = 1
        print(">", text[:50], "→", sess.get("step"), "fav", sess.get("favorite"), "esc", esc)
        assert msgs, f"empty reply for {text}"
        blob = " ".join(msgs)
        assert "? человек" not in blob
        assert "уточним человек" not in blob
    assert sess.get("favorite"), "should have picked apartment"
    assert sess.get("handed_off") or sess.get("step") == "done"
    print("OK ai happy path")


async def _run_ferrari_live() -> None:
    """Живой кейс @home24m: не спрашивать даты заново, если всё уже сказано."""
    from bot.ai import reply

    text = "Да я у вас уже был думаю можно квартиру Феррари на 13 часов и буду я 1"
    s = get_settings()
    e = Engine(s)
    sess = {
        "name": "Спиногрыз",
        "step": "await_intent",
        "dates": "",
        "guests": "",
        "district": "",
        "favorite": "",
        "returning": "",
        "handed_off": 0,
        "context": {"phr_inbound": 1},
    }
    msgs, _, upd, esc = await reply(s, e, sess, text, [])
    blob = " ".join(msgs).lower()
    assert upd.get("favorite") == "Феррари"
    assert upd.get("dates") == "на 13"
    assert upd.get("guests") == "1"
    assert upd.get("returning") == "да"
    assert esc is True
    # v8: эскалация → handed_off=1 + step=handed_off (раньше иногда step=done)
    assert upd.get("step") in ("done", "handed_off")
    assert upd.get("handed_off") == 1 or upd.get("step") == "done"
    assert "на какие даты смотрите — забронируем" not in blob
    assert "феррари" in blob
    print("OK ferrari live compound")


if __name__ == "__main__":
    test_parse_picks()
    test_hello_not_howareyou()
    test_returning()
    test_dates_and_dump()
    test_ferrari_compound_slots()
    test_thanks_not_blocked_by_zhdat()
    asyncio.run(_run_engine())
    asyncio.run(_run_ai_happy())
    asyncio.run(_run_ferrari_live())
    print("ALL OK")
