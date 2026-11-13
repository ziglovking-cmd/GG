"""Один и тот же слот с разных сторон: праздник, месяц, питомец, «позже»."""

from bot.engine import parse_dates
from bot.smart import _craft_early


def _line(sess, text):
    got = _craft_early(dict(sess), text, [])
    assert got, text
    return got[0][0], got[2]


def test_day_keeps_its_month():
    assert parse_dates("на 8 марта") == "8 марта"
    assert parse_dates("на 23 февраля с девушкой") == "23 февраля"
    assert parse_dates("на 26") == "на 26"
    assert parse_dates("На 24 октября на 2 суток") == "24–26 октября"
    assert parse_dates("с 1 по 7 января") == "с 1 по 7 января"


def test_holiday_names():
    assert parse_dates("к новому году с мужем") == "на Новый год"
    assert parse_dates("на майские") == "на майские"
    assert parse_dates("на каникулы") == "на каникулы"
    assert parse_dates("ближе к маю") == "в мае"
    assert parse_dates("на январские") == "на январские"
    assert parse_dates("Ну может в январе") == "в январе"


def test_new_year_with_dog_asks_guests_not_dates():
    line, state = _line({}, "Да я думала на Новый год заехать с собакой")
    # «даты» в ответе FAQ про животных не считаем вопросом про даты заезда
    assert "на какие даты" not in line.lower()
    assert "собак" in line.lower() or "животн" in line.lower()
    assert "сколько" in line.lower() or "район" in line.lower()
    assert state["dates"] == "на Новый год"
    assert state["context"]["pets"] == "собака"


def test_month_with_known_guests_asks_district():
    line, state = _line({"guests": "2"}, "Ну может в январе")
    assert "сколько" not in line.lower()
    assert "район" in line.lower()
    assert state["dates"] == "в январе"


def test_date_and_company_do_not_reask_either():
    line, state = _line({}, "к новому году с мужем")
    assert "дат" not in line.lower()
    assert "сколько" not in line.lower()
    assert "двое" in line.lower()
    assert state["guests"] == "2"


def test_pet_with_count_and_holiday():
    line, state = _line({}, "с собакой, нас двое, на новый год")
    assert line.count("?") == 1
    assert "сколько" not in line.lower()
    assert "собак" in line.lower()
    assert state["context"]["pets"] == "собака"
    assert state["guests"] == "2"


def test_woman_alone_with_cat():
    line, state = _line({}, "я одна, с кошкой, на выходные")
    assert "одна" in line.lower()
    assert "кошк" in line.lower()
    assert "сколько" not in line.lower()
    assert state["context"]["pets"] == "кошка"


def test_later_from_several_wordings():
    for text in ("Да я пока не думала", "подумаю и напишу", "даты скажу позже"):
        line, state = _line({}, text)
        assert "дат" not in line.lower() or "когда будете" in line.lower()
        assert state["context"]["reply_path"].endswith("later")


def test_unknown_when_does_not_ask_the_next_slot():
    # v10.3 (скрин 46): гость думает — не допрашиваем про гостей и даты, предлагаем пару квартир на примете
    line, state = _line({}, "пока не знаю когда")
    assert "сколько" not in line.lower()
    assert "на какие даты" not in line.lower()
    assert state["dates"] == "ещё не определились"
