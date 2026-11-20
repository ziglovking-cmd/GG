"""Сценарий Марии: услуги, «что у вас есть», не переспрашивать «одна»."""

from bot.phrases import greeting_msgs
from bot.smart import _craft_early


def _one(sess, text):
    got = _craft_early(dict(sess), text, [])
    assert got, text
    return got[0][0], got[2]


def test_outreach_offers_news_not_dates():
    msgs, upd = greeting_msgs({"name": "Мария", "context": {}}, outreach=True)
    text = " ".join(msgs).lower()
    assert "home24" in text and text.rstrip().endswith("?")
    assert "напишите примерно даты" not in text
    assert upd["context"]["perk"] == "visit"
    assert upd["context"]["offer_open"] is True and upd["context"]["offer"]
    msgs2, _ = greeting_msgs(
        {
            "name": "Мария",
            "context": {"stay_when": "сентябре", "stay_place": "Твен"},
        },
        outreach=True,
    )
    blob = " ".join(msgs2)
    assert "сентябре" in blob and "Твен" in blob


def test_what_do_you_have_describes_the_flats():
    line, _ = _one({}, "А что у вас есть?")
    assert "квартир" in line.lower()
    assert "ремонт" in line.lower()
    assert "дат" in line.lower()
    assert "сколько" not in line.lower()


def test_alone_with_dog_does_not_ask_headcount():
    line, state = _one(
        {"dates": "на Новый год"},
        "еду одна с собакой",
    )
    assert "сколько" not in line.lower()
    assert "животн" in line.lower() or "собак" in line.lower() or "питом" in line.lower()
    assert state["guests"] == "1"
    assert state["context"]["pets"] == "собака"


def test_count_and_district_are_not_repeated():
    line, state = _one({}, "я одна, ближе к центру")
    assert "сколько" not in line.lower()
    assert "район" not in line.lower()
    assert "дат" in line.lower()
    assert state["guests"] == "1"
    assert state["district"] == "Близко к центру"


def test_perk_thread():
    sess = {"context": {"perk": "visit", "outreach": True}}
    line, state = _one(sess, "Вообще планировала, но пока не знаю, а что за услуги?")
    # аудит S7 + скрин 11.11: на вопрос про услуги — сразу список, без «за день до заезда»
    assert "организац" in line.lower() and "романтическ" in line.lower()
    assert "фотосесс" in line.lower() and "только для двоих" in line.lower()
    assert "за день до заезда" not in line.lower()
    assert "дат" not in line.lower()
    assert state["context"]["perk"] == "orient"

    sess["context"] = state["context"]
    line, state = _one(sess, "пока думаю, может в декабре")
    assert "декабр" in line.lower()
    assert "бесплатн" not in line.lower()
    assert "дополнительную услугу" not in line.lower()
    assert state["dates"] == "в декабре"
    assert state["context"]["perk"] == "told"

    sess["context"] = state["context"]
    sess["dates"] = state["dates"]
    line, state = _one(sess, "да, класс, я напишу как буду точно знать, а какие услуги есть?")
    assert "организац" in line.lower() and "фотосесс" in line.lower()
    assert "за день до заезда" not in line.lower()
    assert "бесплатн" not in line.lower()
    assert state["context"]["perk"] == "told"

    sess["context"] = state["context"]
    line, state = _one(sess, "а какие услуги есть?")
    assert "организац" in line.lower()
    assert "за день до заезда" not in line.lower()
    assert state["step"] != "handed_off"
