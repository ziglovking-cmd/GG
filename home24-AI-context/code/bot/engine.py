"""Скрипт Home24 v2 — живой диалог без ИИ в основной ветке."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from bot.config import Settings
from bot import phrases as P

BUTTONS = {
    "greeting": [
        ("Да, ищу квартиру", "looking"),
        ("Расскажите про бонусы", "show_bonus"),
    ],
    "dates": [
        ("Ближайшие выходные", "dates_weekend"),
        ("Через 2-3 недели", "dates_soon"),
        ("Ещё не определились", "dates_unknown"),
    ],
    "guests": [
        ("1-2 человека", "g_12"),
        ("3-4 человека", "g_34"),
        ("Больше", "g_more"),
    ],
    "district": [
        ("Центр", "d_center"),
        ("Близко к центру", "d_near"),
        ("Зелёный / тихий", "d_green"),
        ("Спальный район", "d_sleep"),
        ("Подмосковье", "d_suburb"),
        ("Не принципиально", "d_any"),
    ],
    "browsing": [
        ("Давайте варианты", "browse_yes"),
        ("Не нужно, спасибо", "browse_no"),
    ],
    "bonus": [
        ("Хочу зарегистрироваться", "loyalty_register"),
        ("А если бронирую не напрямую?", "loyalty_via_agg"),
        ("Понятно, спасибо", "loyalty_done"),
    ],
    "returning": [
        ("Да, были", "ret_yes"),
        ("Нет, впервые", "ret_no"),
    ],
}

CALLBACK_MAP = {
    "looking": "looking",
    "browsing": "browsing",
    "show_bonus": "show_bonus",
    "dates_weekend": "dates",
    "dates_soon": "dates",
    "dates_unknown": "dates",
    "g_12": "guests",
    "g_34": "guests",
    "g_more": "guests",
    "d_center": "district",
    "d_near": "district",
    "d_green": "district",
    "d_sleep": "district",
    "d_suburb": "district",
    "d_calm": "district",
    "d_any": "district",
    "browse_yes": "browse_yes",
    "browse_no": "browse_no",
    "loyalty_register": "loyalty_register",
    "loyalty_via_agg": "loyalty_via_agg",
    "loyalty_done": "loyalty_done",
    "ret_yes": "ret_yes",
    "ret_no": "ret_no",
}

KEYWORD_INTENTS: list[tuple[list[str], str]] = [
    (["цена", "сколько стоит", "стоимость", "прайс"], "price"),
    (["скидк", "промокод", "дешевле"], "discount"),
    (["фото", "посмотреть квартиру", "картинк"], "photos"),
    (["адрес", "где находится", "локаци"], "address"),
    # как в script.md → «Ответы по словам гостя» (жалоба)
    (
        ["жалоб", "плохо было", "ужас", "кошмар", "возмущ", "недоволен", "недовольна", "сломал", "сломан", "грязн"],
        "complaint",
    ),
    (["менеджер", "оператор", "живой человек", "позовите"], "escalate"),
    # looking / browsing ДО hello — «Здравствуйте! Да, хотели бы снять…» = looking
    (
        [
            "ищу",
            "хочу снять",
            "хотели бы снять",
            "хотели снять",
            "нужна квартира",
            "забронировать",
            "подберите",
            "предложи",
            "в аренду",
            "арендовать",
            "хочу квартиру",
            "снять квартиру",
            "снять апартамент",
        ],
        "looking",
    ),
    (
        [
            "просто смотрю",
            "просто смотрим",
            "пока смотрю",
            "пока смотрим",
            "без плана",
            "сначала посмотрим",
            "сначала посмотреть",
            "просто посмотреть",
        ],
        "browsing",
    ),
    (["бонус", "баллы", "лояльность"], "show_bonus"),
    (["привет", "здравствуйте", "добрый день", "доброе утро", "добрый вечер"], "hello"),
    (["как дела", "как жизнь", "как настроение"], "howareyou"),
    (["спасибо", "благодар"], "thanks"),
]

# отказ / «не надо» — ветка D, не заявка менеджеру
_REFUSE_RE = re.compile(
    r"(?i)("
    r"уже\s+не\s+надо|не\s+надо|не\s+нужно|не\s+интересно|не\s+сейчас|"
    r"потом|отмен|отказ|забей|хватит|не\s+буду|не\s+хочу|"
    r"нет[,]?\s*спасибо|не\s+надо[,]?\s*спасибо|пока\s+не\s*надо|"
    r"ничего\s+не\s+надо|передумал"
    r")"
)

# жёсткий стоп рассылки — в стоп-лист, больше никогда не пишем
_STOP_RE = re.compile(
    r"(?i)("
    r"не\s*пишите|не\s*пиши\b|не\s*пишите\s*мне|не\s*надо\s*писать|"
    r"отпиш|отпиши|отписаться|отписка|"
    r"стоп\s*рассыл|уберите\s*(меня\s*)?из|исключите\s*(меня\s*)?из|удалите\s*(меня\s*)?(из\s*)?(базы|рассыл)|"
    r"прекратите\s*(писать|рассыл)|хватит\s*писать|больше\s*не\s*пишите|"
    r"не\s*интересу|не\s*интересн|leave\s*me\s*alone|do\s*not\s*write|"
    r"unsubscribe|\bopt[\s-]?out\b|\bstop\b"
    r")"
)


def is_stop_request(text: str) -> bool:
    """«Не пишите / стоп / отпишите» — навсегда в стоп-лист."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if t in ("стоп", "stop", "отписаться", "отписка", "unsubscribe"):
        return True
    return bool(_STOP_RE.search(t))


def is_refusal(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if is_stop_request(t):
        return True
    if t in ("нет", "не", "неа", "не надо", "не нужно", "пока", "отмена"):
        return True
    # «хочу отменить бронь» — вопрос по проживанию, а не отказ от переписки
    if re.search(r"отмен\w*\s+(мою\s+|нашу\s+)?(брон|заказ|заезд|проживан)|перенес\w*|перенос", t):
        return False
    return bool(_REFUSE_RE.search(t))


def parse_budget(text: str) -> str | None:
    """Бюджет из свободной речи: «до 5 тысяч», «бюджет 4000»."""
    t = (text or "").lower()
    m = re.search(
        r"(?:бюджет|до|макс(?:имум)?|не\s*дороже|около)\s*"
        r"(\d{3,6})\s*(?:тыс|т\.?\s*р|руб|₽)?",
        t,
    )
    if m:
        n = int(m.group(1))
        if n < 100:  # «5 тыс»
            n *= 1000
        if 1500 <= n <= 50000:
            return f"до {n} ₽"
    m = re.search(r"\b(\d)\s*тыс", t)
    if m:
        return f"до {int(m.group(1)) * 1000} ₽"
    return None


def parse_objection(text: str) -> str | None:
    """Короткая пометка возражения для отчёта менеджеру."""
    t = (text or "").lower()
    tags = []
    if re.search(r"дорого|дешевл|бюджет", t):
        tags.append("цена")
    if re.search(r"далеко|метро|транспорт", t):
        tags.append("локация")
    if re.search(r"грязн|фото\s*не|не\s*нрав", t):
        tags.append("не зашло по виду")
    if re.search(r"позже|не\s*сейчас|через\s*месяц", t):
        tags.append("позже")
    return ", ".join(tags) if tags else None


def _fmt(text: str, sess: dict[str, Any], settings: Settings) -> str:
    return P.fill(
        text,
        sess,
        site=settings.site_url,
        channel=settings.channel_url,
        vk=settings.vk_url,
    )


_MONTH_GENITIVE: list[tuple[str, str]] = [
    ("январ", "января"),
    ("феврал", "февраля"),
    ("март", "марта"),
    ("апрел", "апреля"),
    ("ма[йя]", "мая"),
    ("июн", "июня"),
    ("июл", "июля"),
    ("август", "августа"),
    ("сентябр", "сентября"),
    ("октябр", "октября"),
    ("ноябр", "ноября"),
    ("декабр", "декабря"),
]


def _month_genitive_in(text: str) -> str | None:
    t = (text or "").lower()
    for stem, gen in _MONTH_GENITIVE:
        if re.search(stem, t):
            return gen
    return None


def normalize_dates_phrase(dates: str | None) -> str:
    """«1 по 7 января» → «с 1 по 7 января»; подчистить пробелы."""
    d = (dates or "").strip()
    if not d:
        return ""
    d = re.sub(r"\s+", " ", d)
    m = re.fullmatch(r"(\d{1,2})\s+по\s+(\d{1,2})\s+(.+)", d, flags=re.I)
    if m:
        return f"с {m.group(1)} по {m.group(2)} {m.group(3).strip()}"
    m = re.fullmatch(r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\s+(.+)", d)
    if m:
        return f"с {m.group(1)} по {m.group(2)} {m.group(3).strip()}"
    return d


def format_guests_phrase(guests: str | int | None) -> str:
    """1 гость / 2–4 человека / 5+ человек (и диапазоны 1-2 / 3-4 / 5+)."""
    g = str(guests or "").strip()
    if not g:
        return "гости уточним"
    low = g.lower().replace("–", "-")
    if low in ("1-2", "1–2"):
        return "1–2 человека"
    if low in ("3-4", "3–4"):
        return "3–4 человека"
    if low in ("5+", "5 и больше", "больше"):
        return "5+ человек"
    m = re.search(r"(\d+)", g)
    if not m:
        return g
    n = int(m.group(1))
    mod100 = n % 100
    mod10 = n % 10
    if mod10 == 1 and mod100 != 11:
        return f"{n} гость"
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return f"{n} человека"
    return f"{n} человек"


def format_booking_summary(sess: dict[str, Any]) -> str:
    from bot.reply_guard import guest_district_phrase

    raw_dates = str(sess.get("dates") or "")
    if raw_dates == "ещё не определились":
        raw_dates = "даты пока открыты"
    dates = normalize_dates_phrase(raw_dates or "даты уточним") or "даты уточним"
    guests = format_guests_phrase(sess.get("guests"))
    district = guest_district_phrase(str(sess.get("district") or "")) or "район уточним"
    return f"Поняла: {dates}, {guests}, {district}."


def _ctx_upd(sess: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Сохранить context + уже собранные слоты (даты/гости/…), чтобы не терять в цепочке."""
    out = dict(updates)
    if "context" in sess and "context" not in out:
        out["context"] = sess["context"]
    for key in ("dates", "guests", "district", "favorite", "returning"):
        if out.get(key):
            continue
        val = sess.get(key)
        if val:
            out[key] = val
    return out


def _has_word(hay: str, needle: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", hay, flags=re.I) is not None


def _has_stem(hay: str, stem: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(stem)}\w*", hay, flags=re.I) is not None


def keyword_intent(text: str) -> str | None:
    low = text.lower()
    found: list[str] = []
    for keys, intent in KEYWORD_INTENTS:
        for k in keys:
            hit = False
            if " " in k:
                hit = k in low
            elif _has_word(low, k) or (len(k) >= 4 and _has_stem(low, k)):
                hit = True
            if hit:
                found.append(intent)
                break
    if not found:
        return None
    # приоритет: деловой интент важнее вежливого «здравствуйте»
    for pref in (
        "complaint",
        "escalate",
        "looking",
        "browsing",
        "show_bonus",
        "price",
        "discount",
        "photos",
        "address",
        "howareyou",
        "thanks",
        "hello",
    ):
        if pref in found:
            return pref
    return found[0]


def match_button(text: str) -> str | None:
    t = text.strip().lower()
    exact = {
        "да, ищу квартиру": "looking",
        "пока просто смотрю": "browsing",
        "расскажите про бонусы": "show_bonus",
        "ближайшие выходные": "dates_weekend",
        "через 2-3 недели": "dates_soon",
        "ещё не определились": "dates_unknown",
        "еще не определились": "dates_unknown",
        "ещё не определился": "dates_unknown",
        "еще не определился": "dates_unknown",
        "1-2 человека": "g_12",
        "3-4 человека": "g_34",
        "больше": "g_more",
        "центр": "d_center",
        "близко к центру": "d_near",
        "зелёный / тихий": "d_green",
        "зеленый / тихий": "d_green",
        "спальный район": "d_sleep",
        "подмосковье": "d_suburb",
        "спокойный район": "d_calm",
        "не принципиально": "d_any",
        "давайте варианты": "browse_yes",
        "давайте киньте": "browse_yes",
        "не нужно, спасибо": "browse_no",
        "хочу зарегистрироваться": "loyalty_register",
        "а если бронирую не напрямую?": "loyalty_via_agg",
        "понятно, спасибо": "loyalty_done",
        "да, были": "ret_yes",
        "нет, впервые": "ret_no",
        "looking": "looking",
        "browsing": "browsing",
        "show_bonus": "show_bonus",
    }
    if t in exact:
        return exact[t]
    if len(t) > 40:
        return None
    aliases = {
        "looking": ["ищу квартиру", "да ищу", "подберите", "предложи"],
        "browsing": ["просто смотрю", "просто смотрим", "пока смотрю", "пока смотрим"],
        "show_bonus": ["про бонусы", "про баллы"],
        "dates_weekend": ["выходные"],
        "dates_soon": ["2-3 недели", "через 2"],
        "dates_unknown": ["не определ", "пока не знаю"],
        "g_12": ["1-2", "двое", "нас двое"],
        "g_34": ["3-4", "трое", "четверо"],
        "g_more": ["компания", "5+", "больше 4"],
        "d_near": ["близко к центру", "ближе к центру", "недалеко от центра"],
        "d_green": ["зелён", "зелен", "тихий зелён", "тихий зелен"],
        "d_sleep": ["спальн"],
        "d_suburb": ["подмосков"],
        "d_calm": ["спокойн", "потише"],
        "d_center": ["в центре", "центральн"],
        "d_any": ["без разницы", "не принцип"],
        "browse_yes": ["да кинь", "да пришли", "давайте варианты", "давайте киньте"],
        "browse_no": ["не нужно", "не надо"],
        "loyalty_register": ["зарегистрир"],
        "loyalty_via_agg": ["букинг", "островок", "не напрямую"],
        "ret_yes": ["да были", "были у вас"],
        "ret_no": ["впервые", "не были", "нет впервые"],
    }
    for code, words in aliases.items():
        for w in words:
            if w in t:
                return code
    return None


_WEEKDAY_STEMS = (
    ("понедельник", "понедельник", "понедельника"),
    ("вторник", "вторник", "вторника"),
    ("сред", "среда", "среды"),
    ("четверг", "четверг", "четверга"),
    ("пятниц", "пятница", "пятницы"),
    ("суббот", "суббота", "субботы"),
    ("воскресень", "воскресенье", "воскресенья"),
)


def _match_weekday_token(token: str) -> tuple[str, str] | None:
    """(nominative, genitive) или None."""
    tok = (token or "").lower().strip()
    for stem, nom, gen in _WEEKDAY_STEMS:
        if stem == "сред":
            if re.match(r"сред[аыуе]?", tok):
                return nom, gen
        elif tok.startswith(stem):
            return nom, gen
    return None


def _parse_weekday_range(t: str) -> str | None:
    """«пятницу-воскресенье» / «с пятницы по воскресенье» → «с пятницы по воскресенье»."""
    m = re.search(r"(?i)\bс\s+([а-яё]+)\s+по\s+([а-яё]+)\b", t)
    if m:
        a = _match_weekday_token(m.group(1))
        b = _match_weekday_token(m.group(2))
        if a and b:
            return f"с {a[1]} по {b[0]}"
    m = re.search(r"(?i)(?:\bна\s+)?([а-яё]+)\s*[-–—]\s*([а-яё]+)\b", t)
    if m:
        a = _match_weekday_token(m.group(1))
        b = _match_weekday_token(m.group(2))
        if a and b:
            return f"с {a[1]} по {b[0]}"
    return None


def parse_dates(text: str, *, allow_day_1_3: bool = False) -> str | None:
    """Даты без путаницы с числом гостей и часами («человек 6», «на 3 часа» — не дата)."""
    got = _parse_dates_raw(text, allow_day_1_3=allow_day_1_3)
    if got:
        # «с понедельника по пятница» → «по пятницу»
        got = re.sub(r"\bпо (пятниц|суббот|сред)а\b", r"по \1у", got)
        low_all = (text or "").lower()
        span = re.search(r"на\s+(неделю|две\s+недели|сутки|двое\s+суток|пару\s+дней)", low_all)
        if span and re.fullmatch(r"\d{1,2} [а-я]+", got):
            got = f"с {got} на {span.group(1)}"  # «20 ноября на неделю» — срок не терять
        elif span and got in ("завтра", "сегодня", "послезавтра"):
            got = f"{got} на {span.group(1)}"
    bare = re.fullmatch(r"на (\d{1,2})", got or "")
    if bare:
        n = bare.group(1)
        low = (text or "").lower()
        if re.search(
            rf"(человек\w*|гост\w*|взросл\w*|нас)\s*{n}\b|\b{n}\s*(человек|гост|взросл|чел\b)",
            low,
        ) or (int(n) <= 12 and re.search(rf"\b{n}\s*час", low)):
            return None
    return got


def _parse_dates_raw(text: str, *, allow_day_1_3: bool = False) -> str | None:
    """Вытащить даты из любой каши: «на 26», «26-27», «вторник след недели».

    allow_day_1_3: голое «1»/«2»/«3» как день месяца (только на шаге await_dates).
    Иначе 1–3 часто = гости / номер варианта.
    """
    t = text.lower().strip()
    if not t or is_refusal(t):
        return None

    if re.search(r"\bзавтра\b", t):
        return "завтра"
    if re.search(r"\bпослезавтра\b", t):
        return "послезавтра"
    if re.search(r"\bсегодня\b", t):
        return "сегодня"
    # «с 30 декабря по 2 января» — диапазон через месяц
    m = re.search(
        r"\bс\s*(\d{1,2})\s+([а-я]+)\s+по\s+(\d{1,2})\s+([а-я]+)",
        t,
    )
    if m and _month_genitive_in(m.group(2)) and _month_genitive_in(m.group(4)):
        return f"с {m.group(1)} {_month_genitive_in(m.group(2))} по {m.group(3)} {_month_genitive_in(m.group(4))}"
    # «7.12-9.12» / «3.12 по 6.12» / «с 3.12 до 6.12»
    m = re.search(
        r"\b(\d{1,2})[./](\d{1,2})(?:[./]\d{2,4})?\s*(?:[-–—]|по|до)\s*(\d{1,2})[./](\d{1,2})\b",
        t,
    )
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(4)) <= 12:
        m1, m2 = _MONTH_GENITIVE[int(m.group(2)) - 1][1], _MONTH_GENITIVE[int(m.group(4)) - 1][1]
        if m1 == m2:
            return f"с {int(m.group(1))} по {int(m.group(3))} {m1}"
        return f"с {int(m.group(1))} {m1} по {int(m.group(3))} {m2}"
    if re.search(r"длинн\w*\s+выходн", t):
        return "на длинные выходные"
    if re.search(r"следующ\w*\s+выходн|след\.?\s*выходн", t):
        return "следующие выходные"
    if re.search(r"выходн", t):
        return "ближайшие выходные"
    if re.search(r"майск", t):
        return "на майские"
    if re.search(r"каникул", t):
        return "на каникулы"
    if re.search(r"январск", t):
        return "на январские"
    if re.search(r"нов\w{0,8}\s+год|новогодн", t):
        return "на Новый год"
    if re.search(r"через\s*2|2-3\s*недел|через\s*две", t):
        return "через 2-3 недели"
    if re.search(r"через\s*недел", t):
        return "через неделю"
    if re.search(
        r"не\s*определ|(пока|ещё|еще)\s*не\s*(знаю|знаем|решил\w*|понятно)|"
        r"не\s*(знаю|знаем)\s*пока|даты\s*не\s*(знаю|знаем)|точных\s*дат\s*нет|ориентировочно\s*потом",
        t,
    ) or re.fullmatch(
        r"\s*(?:тоже|пока|ещё|еще|я|мы|честно)?\s*(?:не\s*знаю|не\s*знаем|хз|без\s*понятия|понятия\s*не\s*имею|"
        r"не\s*решил\w*|не\s*определил\w*)(?:\s*(?:пока|ещё|еще))?[\s.!)(]*",
        t,
    ):
        return "ещё не определились"

    # диапазон дней недели раньше одиночного «пятница»
    wd_range = _parse_weekday_range(t)
    if wd_range:
        return wd_range

    # будни раньше «следующей недели», иначе «вторник следующей» съешься
    weekdays = (
        ("понедельник", "понедельник"),
        ("вторник", "вторник"),
        ("сред", "среда"),
        ("четверг", "четверг"),
        ("пятниц", "пятница"),
        ("суббот", "суббота"),
        ("воскресень", "воскресенье"),
    )
    for stem, name in weekdays:
        if stem == "сред":
            if not re.search(r"сред[аыуе]?", t):
                continue
        elif not re.search(stem, t):
            continue
        if re.search(
            rf"(следующ|след\.?)\w*.{{0,16}}{stem}|{stem}.{{0,16}}(следующ|след\.?|недел)",
            t,
        ):
            return f"следующий {name}" if name != "среда" else "следующая среда"
        if re.search(rf"(?:на\s+)?{stem}", t):
            return name

    if re.search(r"на\s+следующ\w*\s+недел|следующ\w*\s+недел", t):
        return "на следующей неделе"

    # диапазон 26-27 / 26–28 / с 26 по 28 / с 12 по 15 (+ месяц, если есть)
    m = re.search(r"\bс\s*(\d{1,2})\s*(?:по|-|–|—)\s*(\d{1,2})\b(?![./]\d)", t)
    if m:
        month = _month_genitive_in(t)
        if month:
            return f"с {m.group(1)} по {m.group(2)} {month}"
        return f"{m.group(1)}–{m.group(2)}"
    # «1 по 7 января» без «с»
    m = re.search(r"(?<![./\d])(\d{1,2})\s+по\s+(\d{1,2})\b(?![./]\d)", t)
    if m:
        month = _month_genitive_in(t)
        if month:
            return f"с {m.group(1)} по {m.group(2)} {month}"
        return f"с {m.group(1)} по {m.group(2)}"
    # «5-7 октября» / «5–7 окт»
    m = re.search(
        r"\b(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*"
        r"(ноябр|декабр|январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр)\w*",
        t,
    )
    if m:
        month = _month_genitive_in(m.group(0))
        if month:
            return f"с {m.group(1)} по {m.group(2)} {month}"
        return m.group(0).strip()[:40]
    m = re.search(r"\b(\d{1,2})\s*[-–—]\s*(\d{1,2})\b", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= 31 and 1 <= b <= 31:
            month = _month_genitive_in(t)
            if month:
                return f"с {a} по {b} {month}"
            return f"{a}–{b}"

    # 26.09 / 26/09/26
    m = re.search(r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?", t)
    if m:
        return m.group(0)

    folded = _dates_with_nights(t)
    if folded:
        return folded

    # «на 26», «26 число», «26-го», «ориентировочно на 26»
    if "этаж" not in t and "вариант" not in t:
        m = re.search(
            r"(?:на|к|с)\s+(\d{1,2})(?:\s*-?\s*[еогогому]*|\s*числ|\s*го)?\b",
            t,
        )
        if m and 1 <= int(m.group(1)) <= 31:
            after = t[m.end():]
            if not re.search(
                r"^\s*(январ|феврал|март|апрел|ма[йяеию]|июн|июл|август|сентябр|октябр|ноябр|декабр)",
                after,
            ):
                return f"на {m.group(1)}"
        m = re.search(r"\b(\d{1,2})\s*-?\s*(?:го|е|ое)?\s*числ", t)
        if m and 1 <= int(m.group(1)) <= 31:
            return f"на {m.group(1)}"
        # «ну газ в 10» — обрывок дня, не время заезда и не загадка
        if len(t) <= 40 and not re.search(
            r"заезд|выезд|утр|час|вечер|ноч|минут|этаж", t
        ):
            m = re.search(r"(?:^|[\s,])в\s+(\d{1,2})(?:\s*-?\s*го)?\s*[.!]?\s*$", t)
            if m and 4 <= int(m.group(1)) <= 31:
                return f"на {m.group(1)}"
        # голое «26» / «26.» — день месяца. 1–3 без allow = гости/№ варианта.
        m = re.fullmatch(r"\s*(\d{1,2})\s*[.)]?\s*", t)
        if m:
            n = int(m.group(1))
            if 4 <= n <= 31 or (allow_day_1_3 and 1 <= n <= 31):
                return f"на {n}"
            return None
        # «ориентировочно 26» без «на»
        m = re.search(r"(?:ориентировочно|примерно|где[- ]то|чисел)\s+(\d{1,2})\b", t)
        if m and 1 <= int(m.group(1)) <= 31:
            return f"на {m.group(1)}"

    # «8 марта» / «23 февраля» целиком, не голое «на 8»
    m = re.search(
        r"\b(\d{1,2})\s*"
        r"(январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]\w*|июн\w*|июл\w*|"
        r"август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)",
        t,
    )
    if m and 1 <= int(m.group(1)) <= 31 and not m.group(2).startswith("маяк"):
        return f"{m.group(1)} {m.group(2)}"

    # фраза с месяцем
    if re.search(r"\d", t) and re.search(
        r"(ноябр|декабр|январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр)",
        t,
    ):
        # вырезать кусок вокруг даты, не весь роман
        m = re.search(
            r".{0,8}\d{1,2}.{0,4}(ноябр|декабр|январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр)\w*.{0,8}",
            t,
        )
        if m:
            return m.group(0).strip()[:40]
        if len(t) <= 48:
            return text.strip()[:40]
    # «может в январе» без числа — это уже даты, не повод переспрашивать месяц
    if not re.search(r"\d", t):
        bare_months = (
            (r"январ", "в январе"),
            (r"феврал", "в феврале"),
            (r"\bмарт", "в марте"),
            (r"апрел", "в апреле"),
            (r"(?:^|[^а-яё])ма[йеяю]\w*", "в мае"),
            (r"июн", "в июне"),
            (r"июл", "в июле"),
            (r"август", "в августе"),
            (r"сентябр", "в сентябре"),
            (r"октябр", "в октябре"),
            (r"ноябр", "в ноябре"),
            (r"декабр", "в декабре"),
        )
        for stem, phrase in bare_months:
            if phrase == "в мае" and re.search(r"маяк", t):
                continue
            if re.search(stem, t):
                return phrase
        if re.search(r"праздник", t) and len(t) <= 40:
            return "в праздники"
    return None


def _count_kids(t: str) -> int:
    """Сколько детей упомянуто (дети считаются гостями)."""
    if not re.search(r"реб[её]н|дочк|сын[ауом]?|младен|\bдет(?:и|ей|ями)?\b", t):
        return 0
    m = re.search(r"(\d+)\s*(?:реб|дет)", t)
    if m:
        return max(1, int(m.group(1)))
    if re.search(r"(?:двое|два)\s*(?:дет|реб)", t):
        return 2
    if re.search(r"(?:трое|три)\s*(?:дет|реб)", t):
        return 3
    return 1


def _count_adults_phrase(t: str) -> int | None:
    if re.search(r"нас\s*четверо|\bчетверо\b|вчетвером", t):
        return 4
    if re.search(r"нас\s*трое|\bтрое\b|втроем|втроём", t):
        return 3
    if re.search(
        r"нас\s*двое|\bдвое\b|вдвоем|вдвоём|на\s*двоих|с\s*жен|с\s*муж|"
        r"с\s*парн|с\s*девуш|с\s*парнем|двое\s*взрослы|"
        r"мам\w*\s+и\s+пап|пап\w*\s+и\s+мам",
        t,
    ):
        return 2
    if re.search(r"\b(один|одна|я один|только я|один я)\b", t):
        return 1
    return None


_GUESTS_NEG_RE = re.compile(
    r"(?:^|[\s,.!])(?:нет\s*[,.]?\s*)?не\s+(?:одна|один|двое|трое|четверо|пятеро|\d{1,2})\b"
    r"(?:\s*(?:чел\w*|гост\w*|человек))?\s*[.!)]*\s*$",
    re.I,
)


def is_guests_negation(text: str) -> bool:
    """«Нет, не двое» — гость поправляет число, но нового не назвал."""
    t = (text or "").lower().strip()
    if not t or re.search(r"\bа\s+(?:будет\s+)?\d|\bа\s+(?:двое|трое|четверо|пятеро)", t):
        return False
    return bool(_GUESTS_NEG_RE.search(t))


def parse_guests(text: str) -> str | None:
    """Число гостей. Точный счёт > диапазон; дети входят в число гостей."""
    t = text.lower().strip()
    if is_refusal(t):
        return None

    # правка «не 3, а 4» / «а будет 4» — \bа, чтобы не ловить «на 12» из дат
    m = re.search(
        r"(?i)не\s+\d+\s*[,.]?\s*\bа(?:\s+будет)?\s+(\d+)\s*(?:чел|человек|гост)?",
        t,
    )
    if m and 1 <= int(m.group(1)) <= 20:
        return m.group(1)
    m = re.search(
        r"(?i)\bа\s+будет\s+(\d+)\s*(?:чел|человек|гост)?",
        t,
    )
    if m and 1 <= int(m.group(1)) <= 20 and re.search(r"(?i)не\s+\d|исправ|вместо", t):
        return m.group(1)

    if is_guests_negation(t):
        return None

    kids = _count_kids(t)
    adults = _count_adults_phrase(t)
    # «нас четверо, двое детей» / «из них двое детей» — дети уже внутри общего числа
    if adults is not None and kids and kids < adults and (
        re.search(r"из\s*них", t)
        or (
            re.search(r"нас\s+\w+\s*,\s*(из\s*них\s+)?\w+\s+(дет|реб)", t)
            and not re.search(r"\bи\s+(\w+\s+)?(дет|реб)|плюс|\+|ещ[её]", t)
        )
    ):
        return str(adults)
    # «нас двое и ребёнок» → 3 (не «1-2»)
    if adults is not None and kids:
        return str(adults + kids)
    if kids and re.search(r"семь[еёй]|с\s*муж|с\s*жен|с\s*парн", t):
        return str(2 + kids)
    if kids and adults is None and re.search(r"с\s*реб[её]н|с\s*доч|с\s*сын", t):
        # «с ребёнком» без числа взрослых — двое (взр.+реб.) минимум, если нет «один»
        return "2"

    # явный диапазон кнопкой — только если так сказали
    if re.search(r"\b1-2\b|один-два", t) and not kids:
        return "1-2"
    if re.search(r"\b3-4\b", t) and not kids:
        return "3-4"
    if re.search(r"5\+|больше\s*\d|компани", t):
        return "5+"

    # точные «двое» / «трое» без детей
    if adults is not None:
        return str(adults)
    if re.search(r"\bтрое\b", t):
        return "3"
    if re.search(r"\bчетверо\b", t):
        return "4"
    for word, num in (("пятеро", "5"), ("шестеро", "6"), ("семеро", "7")):
        if re.search(rf"\b{word}\b", t):
            return num
    # «я с сыном и дочкой» — трое
    if re.search(
        r"\bя\s+с\s+(мам|пап|муж|жен|сын|доч|подруг|друг|сестр|брат|коллег|парн|девушк|бабушк|дедушк|реб)\w*\s+и\s+(мам|пап|муж|жен|сын|доч|подруг|друг|сестр|брат|коллег|парн|девушк|бабушк|дедушк|реб)\w*",
        t,
    ):
        return "3"
    # «я с мамой», «я с подругой», «я и муж» — двое
    if re.search(
        r"\bя\s+(с|и)\s+(мам|пап|муж|жен|сын|доч|подруг|друг|сестр|брат|коллег|парн|девушк|бабушк|дедушк)\w*\b",
        t,
    ) and not re.search(r"\bи\s+(с\s+)?(дет|реб|сын|доч)\w*.*\bи\b", t):
        return "2"

    m = re.search(r"(\d+)\s*(?:чел|человек|гост|персон|взрослы)", t)
    if m:
        n = int(m.group(1))
        return str(n + kids) if kids else str(n)
    m = re.search(r"около\s+(\d+)\b", t)
    if m:
        return m.group(1)
    # «я буду 1» / «я буду один»
    m = re.search(r"\bя\s+буду\s+(\d+)\b", t)
    if m and 1 <= int(m.group(1)) <= 20:
        return m.group(1)
    m = re.search(r"\bя\s+буду\s+(один|одна|сам|сама)\b", t)
    if m:
        return "1"
    m = re.search(r"(?:буду|будем|нас|человек|гост(?:ей|я)?)\s+(\d+)\b", t)
    if m:
        n = int(m.group(1))
        return str(n + kids) if kids else str(n)
    # «нас будет 3», «будет 3 человека» (но не «будет 3 декабря» / «3.12»)
    m = re.search(r"(?:\bнас\s+)?\bбуд(?:ет|ем)\s+(\d{1,2})\b(?![./]\d)(?!\s*(?:-?го|числ|ноч|сут|дн|недел))", t)
    if m and 1 <= int(m.group(1)) <= 20 and not _month_genitive_in(t[m.end():m.end() + 14]):
        return m.group(1)
    m = re.search(r"(?:буду|будем)\s+я\s+(\d+)\b", t)
    if m and 1 <= int(m.group(1)) <= 20:
        return m.group(1)
    m = re.search(r"(?:буду|будем)\s+я\s+(один|одна|сам|сама)\b", t)
    if m:
        return "1"
    m = re.search(r"\bна\s+(одного|двоих|троих|четверых)\b", t)
    if m:
        return {"одного": "1", "двоих": "2", "троих": "3", "четверых": "4"}[m.group(1)]
    if re.search(r"\b(один|одна|я один|только я|один я)\b", t):
        return "1"
    if re.search(r"\d{1,2}[./]\d{1,2}", t):
        return None
    if re.search(r"\b\d{1,2}\s*[-–—]\s*\d{1,2}\b", t):
        return None
    # «3))», «3!» — число со смайликом
    m = re.fullmatch(r"\s*(\d+)\s*[)(.!,\s]*", t)
    if m and 1 <= int(m.group(1)) <= 20:
        return m.group(1)
    # «3. можно с собакой?» — число гостей и сразу вопрос
    m = re.match(r"\s*(\d{1,2})\s*[.,!)]+\s+(?=[а-яё])", t)
    if m and 1 <= int(m.group(1)) <= 20 and not re.match(r"\s*\d{1,2}\s*[.,]\s*\d", t) and not re.search(
        r"(?i)вариант|номер|квартир|этаж", t
    ):
        return m.group(1)
    return None


def _month_num(text: str) -> int | None:
    t = (text or "").lower()
    for stem, gen in _MONTH_GENITIVE:
        if re.search(stem, t):
            return _MONTH_GENITIVE.index((stem, gen)) + 1
    return None


def _dates_with_nights(text: str, today: date | None = None) -> str | None:
    """«на 24 октября на 2 суток» → «24–26 октября» (выезд через 2 ночи)."""
    nights = parse_nights(text)
    if not nights:
        return None
    t = (text or "").lower()
    m = re.search(
        r"\b(\d{1,2})\s*"
        r"(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)",
        t,
    )
    if not m:
        return None
    day = int(m.group(1))
    month = _month_num(m.group(2))
    if not month or not 1 <= day <= 31:
        return None
    today = today or date.today()
    try:
        start = date(today.year, month, day)
    except ValueError:
        return None
    if start < today:
        try:
            start = date(today.year + 1, month, day)
        except ValueError:
            return None
    end = start + timedelta(days=int(nights))
    if start.month == end.month and start.year == end.year:
        return f"{start.day}–{end.day} {_MONTH_GENITIVE[start.month - 1][1]}"
    return (
        f"{start.day} {_MONTH_GENITIVE[start.month - 1][1]} – "
        f"{end.day} {_MONTH_GENITIVE[end.month - 1][1]}"
    )


def parse_nights(text: str) -> str | None:
    """Число ночей / суток из фразы («на 2 ночи», «трое суток»)."""
    t = text.lower().strip()
    if not t or is_refusal(t):
        return None
    m = re.search(r"\bна\s+(\d{1,2})\s*(?:ноч|сутк)", t)
    if m and 1 <= int(m.group(1)) <= 60:
        return m.group(1)
    m = re.search(r"\b(\d{1,2})\s*(?:ноч(?:и|ь|ей)?|сут(?:ки|ок))\b", t)
    if m and 1 <= int(m.group(1)) <= 60:
        return m.group(1)
    words = {
        "одну ночь": "1",
        "одну ноч": "1",
        "две ночи": "2",
        "две ноч": "2",
        "три ночи": "3",
        "трое суток": "3",
        "двое суток": "2",
    }
    for w, n in words.items():
        if w in t:
            return n
    return None


def parse_district(text: str) -> str | None:
    t = text.lower().strip()
    if is_refusal(t):
        return None
    if re.search(r"не\s*принцип|без\s*разницы|любо[йя]|не\s*важно", t):
        return "не принципиально"
    # «сами район выберите» — не название района и не повод подставить чужой
    if re.search(
        r"сами\s*(уже\s*)?(район\s*)?(выбер|выбир)|"
        r"выбер(ите|и)\s*(район|сами)|"
        r"на\s*ваш\s*выбор|вам\s*виднее|район\s*(не\s*важен|на\s*вас)",
        t,
    ):
        return "не принципиально"
    # «не центр» / «не в самом центре» — спокойнее, не зона «центр»
    if re.search(r"(?i)не\s+(в\s+)?(самом\s+)?центр", t):
        return "спокойный район"
    if re.search(r"подмосков|за\s*мкад|в\s*област", t):
        return "Подмосковье"
    if re.search(r"близко\s*к\s*цен|ближе\s*к\s*цен|недалеко\s*от\s*цен|поближе\s*к\s*цен|деловой", t):
        return "Близко к центру"
    if re.search(r"зелён|зелен|лесопарк|новая\s*москва", t):
        return "Тихий зелёный район"
    if re.search(r"спальн|окраин", t):
        return "Спальный район"
    # тихая / без шума / спокойно → спокойный район (спальный + зелёный)
    if re.search(
        r"спокойн|тих[аои]|без\s*шум|не\s*шум|тише|тишин|"
        r"потише|подальше\s*от\s*шум|не\s*шумный",
        t,
    ):
        return "спокойный район"
    # центр / в центре / центральный
    if re.search(r"центр|в\s*центре|центральн", t):
        return "центр"
    # названный район / метро: «Нагатино», «у метро Сокол», «м. Коммунарка»
    m = re.search(r"(?:\bм\.|\bметро|\bрайон[еа]?|\bв\s+район[еа])\s+([а-яё][а-яё\-]{3,}(?:\s+[а-яё\-]{4,})?)", t)
    if m and not re.search(r"^(центр|любо|спокой|тих|не\b|без\b|поближе|ближе|рядом|зелен|зелён|спальн|подмосков)", m.group(1)) and not re.search(
        r"(ой|ый|ий|ая|ое|ые|ого|ую)$", m.group(1).split()[0]
    ):  # «район крутой» — оценка, не название
        return _place_title(m.group(1))
    for stem, name in _MOSCOW_PLACES:
        if re.search(rf"(?<![а-яё]){stem}", t):
            return name
    return None


# Районы и метро, которые гости называют чаще всего (+ адреса из script.md: Коммунарка, Ленинский)
_MOSCOW_PLACES: tuple[tuple[str, str], ...] = (
    ("нагатин", "Нагатино"),
    ("коммунарк", "Коммунарка"),
    (r"ленинск\w*\s+проспект", "Ленинский проспект"),
    ("бауманск", "Бауманская"),
    ("басманн", "Басманный"),
    ("бутырск", "Бутырский"),
    ("арбат", "Арбат"),
    ("хамовник", "Хамовники"),
    ("таганк", "Таганка"),
    ("китай-город", "Китай-город"),
    ("пресн", "Пресня"),
    ("сокольник", "Сокольники"),
    ("измайлов", "Измайлово"),
    ("вднх", "ВДНХ"),
    ("марьин", "Марьино"),
    ("люблин", "Люблино"),
    ("бутов", "Бутово"),
    ("чертанов", "Чертаново"),
    ("митин", "Митино"),
    ("строгин", "Строгино"),
    ("кунцев", "Кунцево"),
    ("раменк", "Раменки"),
    ("прокшин", "Прокшино"),
    ("лобановск", "Прокшино"),
    ("очаков", "Очаково"),
    ("стройкомбинат", "Очаково"),
    ("потапов", "Очаково"),
    ("сколков", "Сколково"),
    (r"москва[\s-]сити|\bсити\b", "Москва-Сити"),
    ("фитар[её]вск", "Коммунарка"),
)


def _place_title(raw: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in raw.split())


def extract_notes(text: str) -> str:
    """Лишние пожелания из длинного сообщения — для менеджера, не для гостя."""
    t = (text or "").strip()
    if len(t) < 40:
        return ""
    # убрать уже вытащенные слоты — оставить суть
    low = t.lower()
    keep = []
    for part in re.split(r"[.!?,\n]+", t):
        p = part.strip()
        if len(p) < 8:
            continue
        pl = p.lower()
        if parse_dates(p) and len(p) < 28:
            continue
        if re.fullmatch(r".{0,10}(ищу|привет|здравствуй|подбер).{0,20}", pl):
            continue
        keep.append(p)
    note = "; ".join(keep)[:220]
    # только если есть смысловой хвост (ребёнок/тихо/парковка…)
    if re.search(
        r"(?i)реб[её]н|тих|шум|парк|лифт|животн|собак|кот|wifi|вайф|балкон|кухн",
        note,
    ):
        return note
    if len(t) >= 80:
        return t[:180]
    return ""


def parse_returning(text: str) -> str | None:
    t = text.lower().strip()
    if re.search(r"(не\s*был|не\s*были|не\s*останавлив|впервые|первый\s*раз)", t):
        return "нет"
    if t.strip(" !.)") in ("был", "была", "были"):
        return "да"
    if t in ("нет", "неа", "нет.", "нет,"):
        return "нет"
    if re.search(r"\bнет\b", t) and not re.search(
        r"да[,]?\s*был|были\s*у|уже\s*был|у\s*вас\s*.{0,24}был", t
    ):
        # «нет, впервые» / голое нет на шаге returning
        if len(t) <= 24:
            return "нет"
    # «я у вас уже был», «уже был», «был у вас», «да были»
    if re.search(
        r"(да[,]?\s*был|да[,]?\s*были|были\s*у|уже\s*был|уже\s*были|"
        r"у\s*вас\s*.{0,24}был|был[аи]?\s*у\s*вас|уже\s*останавлив|постоянн|"
        r"^был[аи]?\b.{0,30}(раньше|году|летом|зимой|весной|осенью|раз|месяц)|останавливал(ась|ся|ись))",
        t,
    ):
        return "да"
    if re.search(r"\bда\b", t) and len(t) <= 20 and "не" not in t:
        return "да"
    return None


def _step_ask(step: str) -> tuple[list[str], list[tuple[str, str]] | None]:
    """Всегда есть ответ+вопрос на шаге — тепло, на «вы», без канцелярита."""
    asks = {
        "await_district": (
            [P.district_choice_message()],
            None,
        ),
        "await_dates": (
            ["Подскажите, пожалуйста, на какие даты планируете поездку? 🙂"],
            BUTTONS["dates"],
        ),
        "await_guests": (
            ["Подскажите, пожалуйста, сколько будет гостей?"],
            BUTTONS["guests"],
        ),
        "await_returning": (
            ["Какой вариант берём (1–3 или название)? И вы у нас уже были или впервые?"],
            BUTTONS["returning"],
        ),
        "await_favorite": (
            ["Напишите, пожалуйста, название или адрес квартиры 🙂"],
            None,
        ),
        "await_intent": (
            [P.district_choice_message()],
            BUTTONS["greeting"],
        ),
        "browsing": (
            ["Скинуть пару вариантов на потом?"],
            BUTTONS["browsing"],
        ),
        "bonus": (
            ["Прислать ссылку на бонусы или коротко рассказать?"],
            BUTTONS["bonus"],
        ),
    }
    return asks.get(
        step,
        (
            ["Подскажите, пожалуйста, на какие даты планируете поездку?"],
            BUTTONS["greeting"],
        ),
    )


def is_waiting_nudge(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if re.fullmatch(r"[?？.…\s❤️👍🙏🔥💯]+", t):
        return True
    return bool(
        re.search(
            r"(?i)^(ну\s*)?(что\s*там|как\s*там|ал+о|ау+|есть\s*кто|вы\s*тут|"
            r"ну\s*что|э+й|хей|долго|жду|ну\.+|и\?+)$",
            t,
        )
        or re.search(r"(?i)ну\s*что\s*там|что\s*там\s*с|когда\s*вариант|где\s*вариант", t)
    )


class Engine:
    """Диалог по home24-bot-script-v2 — скрипт как живой собеседник."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def greeting(
        self, sess: dict[str, Any], *, outreach: bool = False
    ) -> tuple[list[str], list[tuple[str, str]], dict[str, Any]]:
        msgs, upd = P.greeting_msgs(sess, outreach=outreach)
        return msgs, BUTTONS["greeting"], upd

    def soft_close(self, sess: dict[str, Any]) -> tuple[list[str], None, dict[str, Any], bool]:
        """Ветка D — вариативное мягкое завершение. Без заявки менеджеру."""
        msgs = P.soft_close_msgs(
            sess, site=self.s.site_url, channel=self.s.channel_url, vk=self.s.vk_url
        )
        return msgs, None, _ctx_upd(sess, {"step": "done"}), False

    def _offers_after_slots(
        self,
        sess: dict[str, Any],
        *,
        district: str,
        guests: str,
    ) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool]:
        """После района, дат и числа гостей — сверка TravelLine и карточки со ссылками/ценами."""
        tmp = {**sess, "district": district, "guests": guests}
        # квартира уже выбрана — не слать снова список, идём к комфорту/сверке
        if str(tmp.get("favorite") or "").strip():
            return self.ask_comfort_or_handoff(tmp)
        msgs = list(P.pick(P.GUESTS_OK, sess, "guests_ok"))
        perk_now = str((sess.get("context") or {}).get("perk") or "")
        perk_told = perk_now in ("", "visit", "orient", "told", "offered", "wait")
        offered: list[str] = []
        from_calendar = False
        cards = ""
        try:
            need_m = re.search(r"\d+", str(guests or "2"))
            adults = int(need_m.group(0)) if need_m else 2
            try:
                from bot.travelline import free_offer_cards

                cards, offered = free_offer_cards(
                    str(tmp.get("dates") or ""),
                    adults,
                    district=district,
                )
                from_calendar = bool(cards)
            except Exception:
                cards, offered = "", []
            from bot.reply_guard import is_open_district

            open_pref = is_open_district(district) or not str(district or "").strip()
            if not cards and open_pref:
                # район не важен — каталог только если календарь недоступен
                from bot.catalog import budget_from_sess, offer_bundle

                cards, offered = offer_bundle(
                    district="не принципиально",
                    guests=str(guests or ""),
                    budget=budget_from_sess(tmp),
                    limit=20,
                )
            elif not cards and not open_pref:
                # именованный район: чужие квартиры не подмешиваем
                label = str(district or "").strip() or "этом районе"
                return self.handoff_looking(
                    {**tmp, "returning": sess.get("returning") or ""},
                    note=(
                        f"В районе «{label}» на ваши даты по календарю TravelLine "
                        "свободных квартир нет — подберёт менеджер или посмотрим другой район."
                    ),
                )
            if not cards:
                return self.handoff_looking(
                    {**tmp, "returning": sess.get("returning") or ""},
                    note="По календарю на эти даты свободных нет — подберёт менеджер.",
                )
            if cards:
                msgs.append(cards)
                if adults >= 5:
                    msgs.append(
                        "По вместимости на большую компанию места ограничены — "
                        "это ближайшие варианты, менеджер уточнит свободные под вас."
                    )
        except Exception:
            msgs.append(P.HANDOFF_LINE)
        if str(sess.get("returning") or "").strip() not in ("да", "нет"):
            msgs.append("Подскажите, пожалуйста — вы у нас уже были или впервые?")
        ctx = dict(sess.get("context") or {})
        if offered:
            ctx["offers"] = offered
        if perk_told:
            ctx["perk"] = "told"
        if from_calendar:
            ctx["tl_offers"] = offered
            ctx["tl_dates"] = str(tmp.get("dates") or "")
        return (
            msgs,
            BUTTONS["returning"],
            _ctx_upd(sess, {"guests": guests, "district": district, "step": "await_returning", "context": ctx}),
            False,
        )

    def ask_comfort_or_handoff(
        self, sess: dict[str, Any], *, note: str = ""
    ) -> tuple[list[str], None, dict[str, Any], bool]:
        """После выбора квартиры — доп. комфорт → сверка итога → менеджер."""
        fav = str(sess.get("favorite") or "").strip()
        ctx = dict(sess.get("context") or {})
        if note:
            prev = str(ctx.get("prefs") or "")
            ctx["prefs"] = (prev + "; " + note).strip("; ")[:300] if prev else note[:300]
        if fav and not ctx.get("comfort_asked") and str(sess.get("step") or "") != "await_comfort":
            ctx["comfort_asked"] = True
            head = f"Отлично, «{fav}» 🙂"
            return (
                [head, P.COMFORT_EXTRAS_ASK],
                None,
                _ctx_upd(sess, {"step": "await_comfort", "favorite": fav, "context": ctx}),
                False,
            )
        if fav and not ctx.get("report_docs") and str(sess.get("step") or "") not in (
            "await_docs",
            "await_booking_confirm",
        ):
            from bot.phrases import REPORT_DOCS_ASK

            return (
                [REPORT_DOCS_ASK],
                None,
                _ctx_upd(sess, {"step": "await_docs", "favorite": fav, "context": ctx}),
                False,
            )
        if fav and str(sess.get("step") or "") != "await_booking_confirm":
            from bot.smart import _booking_summary_state

            return _booking_summary_state(
                {**sess, "favorite": fav, "context": ctx}, ctx_extra=ctx
            )
        return self.handoff_looking({**sess, "context": ctx}, note="")

    def handoff_looking(self, sess: dict[str, Any], *, note: str = "") -> tuple[list[str], None, dict[str, Any], bool]:
        """Финал ветки looking — заявка гостю + полный отчёт в context для админа."""
        line = P.pick(P.HANDOFF, sess, "handoff")
        bits = []
        if note:
            bits.append(note)
        try:
            extra = str((sess.get("context") or {}).get("notes") or "").strip()
            if extra:
                bits.append(f"Пожелания учла.")
        except Exception:
            pass
        # script.md: гостю ровно фраза передачи; заметки (вместимость, постоянный гость) — только менеджеру в отчёт
        ctx = dict(sess.get("context") or {})
        report = P.client_report({**sess, "context": ctx}, guest_text="")
        ctx["report"] = report
        if note and note not in str(ctx.get("prefs") or ""):
            prev = str(ctx.get("prefs") or "")
            ctx["prefs"] = (prev + "; " + note).strip("; ")[:300] if prev else note[:300]
        upd = {
            "step": "done",
            "handed_off": 1,
            "favorite": sess.get("favorite") or "",
            "returning": sess.get("returning") or "",
            "dates": sess.get("dates") or "",
            "guests": sess.get("guests") or "",
            "district": sess.get("district") or "",
            "context": ctx,
        }
        return [line], None, _ctx_upd(sess, upd), True

    def handle(
        self, sess: dict[str, Any], text: str, *, intent: str | None = None
    ) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool]:
        btn = match_button(text)
        code = intent or (CALLBACK_MAP.get(btn) if btn else None) or keyword_intent(text)
        step = sess.get("step") or "greeting"
        updates: dict[str, Any] = {}
        buttons: list[tuple[str, str]] | None = None
        low = (text or "").strip().lower()

        # менеджер ведёт чат — бот молчит (шаг и флаг должны совпадать)
        if sess.get("handed_off") or step == "handed_off":
            return [], None, {"handed_off": 1, "step": "handed_off"}, False

        # после выбора квартиры — ответ про лёд/чай/удлинитель/питомца
        if step == "await_comfort":
            from bot.smart import _comfort_extras_reply

            got = _comfort_extras_reply(sess, text)
            if got:
                return got

        if step == "await_docs":
            from bot.smart import _docs_reply

            got = _docs_reply(sess, text)
            if got:
                return got

        # сверка итога перед менеджером
        if step == "await_booking_confirm":
            from bot.smart import _booking_confirm_reply

            got = _booking_confirm_reply(sess, text)
            if got:
                return got

        # стоп-лист: вежливо прощаемся, больше не пишем
        if is_stop_request(text):
            lead = P.pick(P.STOP_ACK, sess, "stop")
            return (
                [lead],
                None,
                _ctx_upd(
                    sess,
                    {
                        "step": "done",
                        "handed_off": 1,
                        "stop_requested": True,
                        "context": {
                            **(sess.get("context") or {}),
                            "stopped": True,
                            "objection": "стоп-лист / не писать",
                        },
                    },
                ),
                False,
            )

        # «подумаем / прдумаем» — не кидать список районов
        if not btn and P.is_later_think(text) and not parse_dates(text) and not parse_guests(text) and not parse_district(text):
            return (
                [P.LATER_LINE],
                None,
                _ctx_upd(sess, {"step": "done"}),
                False,
            )

        # —— «Да» на предложение из рассылки → факты, а не даты (script.md + addon services_da)
        if not btn and not parse_dates(text) and not parse_guests(text):
            offered = P.offer_reply(dict(sess), text, services_question=bool(re.search(r"(?i)услуг", text)))
            if offered:
                o_msgs, o_ctx, o_step = offered
                o_buttons = BUTTONS["dates"] if o_step == "await_dates" and o_msgs[0].endswith("?") else None
                return o_msgs, o_buttons, _ctx_upd(sess, {"step": o_step, "context": o_ctx}), False

        # «ну что там?» — не молчим, напоминаем где мы
        if is_waiting_nudge(text):
            msgs, btns = _step_ask(step if step not in ("greeting", "done", "handed_off") else "await_intent")
            lead = "Я тут)"
            if step == "await_returning" and (sess.get("context") or {}).get("offers"):
                lead = "Варианты выше — напишите, пожалуйста, номер (1–3) или название."
            elif step == "done" and sess.get("handed_off"):
                return (
                    ["Обычно менеджер отвечает минут за 10–15 в рабочее время."],
                    None,
                    {},
                    False,
                )
            if lead == "Я тут)":
                # script.md: «ну что там» → «Я тут) Что осталось уточнить?»
                return ["Я тут) Что осталось уточнить?"], btns, _ctx_upd(sess, {}), False
            return [lead, *msgs], btns, _ctx_upd(sess, {}), False

        # «Уважаемый менеджер, ответьте мне» — просьба ответить, не передача (аудит S1/S10)
        if code == "escalate":
            from bot.faq import _POLITE_ANSWER_RE, _REAL_HANDOFF_RE

            if _POLITE_ANSWER_RE.search(low) and not _REAL_HANDOFF_RE.search(low):
                return ["Да, я тут, слушаю вас."], None, _ctx_upd(sess, {}), False

        # —— жалобы / эскалация —— без эмодзи
        if code in ("complaint", "escalate"):
            return (
                [
                    "Очень жаль, что так вышло. Напишите подробнее, "
                    "я сразу передам администратору, разберёмся."
                ]
                if code == "complaint"
                else [P.HANDOFF_LINE],
                None,
                {"handed_off": 1, "step": "handed_off"},
                True,
            )

        # —— отказ: на старте «нет» = browsing; на returning «нет» = впервые ——
        if is_refusal(text):
            if step == "await_returning" and low in ("нет", "не", "неа", "нет."):
                # это ответ «впервые», не прощание
                pass
            elif step in ("greeting", "await_intent") and low in (
                "нет",
                "не",
                "неа",
                "пока",
                "не сейчас",
                "потом",
            ):
                code = "browsing"
            elif step == "await_returning" and re.search(
                r"(?i)не\s*пойд|не\s*нрав|не\s*подход|другие|ещё\s*вариант|еще\s*вариант",
                text,
            ):
                # ниже в await_returning — с exclude и без зацикливания
                pass
            else:
                return self.soft_close(sess)

        # —— расширенный FAQ (цена, вайфай, питомцы, тупые вопросы…) ——
        # не перебиваем чистый ответ на шаг воронки (голая дата / число гостей)
        funnel_answer = False
        if step == "await_dates" and (btn or parse_dates(text, allow_day_1_3=True)):
            funnel_answer = True
        elif step == "await_guests" and (btn or parse_guests(text)):
            funnel_answer = True
        elif step == "await_district" and (btn or parse_district(text)):
            funnel_answer = True
        elif step == "await_returning" and (btn or parse_returning(text)):
            funnel_answer = True
        elif btn in ("looking", "browsing", "show_bonus", "browse_yes", "browse_no") or code in (
            "looking",
            "browsing",
            "show_bonus",
            "hello",
            "howareyou",
            "thanks",
        ):
            funnel_answer = True

        if not funnel_answer and not btn:
            try:
                from bot.faq import faq_then_resume, match_faq

                hit = match_faq(text)
            except Exception:
                hit = None
            if hit:
                faq_msgs, special = hit
                if special == "escalate":
                    return (
                        faq_msgs,
                        None,
                        {"handed_off": 1, "step": "handed_off"},
                        True,
                    )
                if special in ("hello", "thanks"):
                    code = special
                elif special in ("troll", "tricky"):
                    return faq_msgs, None, _ctx_upd(sess, {}), False
                else:
                    msgs, buttons = faq_then_resume(faq_msgs, step, BUTTONS)
                    upd: dict[str, Any] = {}
                    # «…Рассказать?» в ответе — следующее «да» = рассказать, а не воронка
                    topic = P.offer_topic_in(faq_msgs[-1] if faq_msgs else "")
                    if topic:
                        msgs = list(faq_msgs)  # без вопроса воронки поверх предложения
                        upd["context"] = {
                            **(sess.get("context") or {}),
                            "offer": topic,
                            "offer_open": True,
                        }
                    if special == "bonus_hint" and step in ("greeting", "await_intent", "done"):
                        upd = {"step": "bonus"}
                        buttons = BUTTONS["bonus"]
                    return msgs, buttons, _ctx_upd(sess, upd), False

        _FUNNEL = (
            "await_district",
            "await_dates",
            "await_guests",
            "await_returning",
            "await_favorite",
        )

        if code == "hello":
            # после outreach / уже поздоровались — не здороваться снова и не представлять Home24
            if P.already_greeted(sess) and step in ("greeting", "await_intent"):
                return (
                    [P.district_choice_message()],
                    None,
                    _ctx_upd(sess, {"step": "await_district"}),
                    False,
                )
            if step in ("greeting", "await_intent", "done"):
                if step == "done":
                    msgs, btns, upd = self.greeting({**sess, "handed_off": 0})
                    upd["handed_off"] = 0
                    return msgs, btns, upd, False
                # первое входящее (гость написал сам) — тёплое приветствие один раз
                msgs = P.inbound_hello_msgs(sess)
                ctx = dict(sess.get("context") or {})
                ctx["greeted"] = True
                return (
                    msgs,
                    BUTTONS["greeting"],
                    _ctx_upd(sess, {"step": "await_intent", "context": ctx}),
                    False,
                )
            # привет mid-воронки — без повторного «Здравствуйте», сразу вопрос шага
            ask = {
                "await_district": (P.district_choice_message(), None),
                "await_dates": ("На какие даты примерно смотрите?", BUTTONS["dates"]),
                "await_guests": ("Сколько человек будет?", BUTTONS["guests"]),
                "await_returning": (
                    "Какой вариант берём (1–3 / название) — и были у нас раньше?",
                    BUTTONS["returning"],
                ),
                "await_favorite": ("Напишите название или адрес квартиры 🙂", None),
                "browsing": ("Могу прислать пару вариантов на будущее?", BUTTONS["browsing"]),
                "bonus": ("Могу прислать ссылку на бонусы?", BUTTONS["bonus"]),
            }.get(step)
            if ask:
                q, btns = ask
                return [f"Хорошо 🙂 {q}"], btns, _ctx_upd(sess, {}), False
            return ["Хорошо, продолжим 🙂 Чем могу помочь?"], None, _ctx_upd(sess, {}), False

        if code == "howareyou":
            msgs = P.howareyou_msgs(sess)
            if step in ("greeting", "await_intent", "done"):
                return msgs, BUTTONS["greeting"], _ctx_upd(sess, {"step": "await_intent"}), False
            return msgs, None, _ctx_upd(sess, {}), False

        if code == "thanks" and step not in (
            "await_dates",
            "await_guests",
            "await_district",
            "await_returning",
            "await_favorite",
        ):
            return [P.pick(P.THANKS, sess, "thanks")], None, _ctx_upd(sess, {}), False

        # короткий да/нет на старте
        if step in ("greeting", "await_intent") and not code:
            if low in ("да", "да.", "даа", "угу", "ага", "ищу", "хочу", "йес", "yes"):
                code = "looking"
            elif low in ("нет", "не", "пока", "не сейчас", "потом"):
                code = "browsing"

        # —— вход в ветки ——
        # воронка: район → даты → гости → календарь TravelLine
        if (code == "looking" or btn == "looking") and step not in _FUNNEL:
            slots_dates = parse_dates(text)
            slots_guests = parse_guests(text)
            slots_dist = parse_district(text)
            if slots_dates or slots_guests or slots_dist:
                upd: dict[str, Any] = {}
                if slots_dist:
                    upd["district"] = slots_dist
                if slots_dates:
                    upd["dates"] = slots_dates
                if slots_guests:
                    upd["guests"] = slots_guests
                # все три слота — сразу к карточкам из календаря
                if upd.get("district") and upd.get("dates") and upd.get("guests"):
                    return self.handle(
                        {**sess, **upd, "step": "await_guests"},
                        str(upd["guests"]),
                    )
                if not upd.get("district"):
                    bits = []
                    if slots_guests:
                        bits.append(f"{slots_guests} гост.")
                    if slots_dates:
                        bits.append(str(slots_dates))
                    lead = (
                        ("Поняла: " + ", ".join(bits) + ".\n\n" + P.district_choice_message())
                        if bits
                        else P.district_choice_message()
                    )
                    return [lead], None, _ctx_upd(sess, {**upd, "step": "await_district"}), False
                if not upd.get("dates"):
                    msgs = list(P.pick(P.DISTRICT_OK, sess, "district_ok"))
                    return msgs, BUTTONS["dates"], _ctx_upd(sess, {**upd, "step": "await_dates"}), False
                msgs = list(P.pick(P.DATES_OK, sess, "dates_ok"))
                return msgs, BUTTONS["guests"], _ctx_upd(sess, {**upd, "step": "await_guests"}), False
            return (
                [P.district_choice_message()],
                None,
                _ctx_upd(sess, {"step": "await_district"}),
                False,
            )

        if (code == "looking" or btn == "looking") and step in _FUNNEL:
            # уже в воронке — игнор «ищу», ниже обработаем как ответ шага / слоты
            code = None

        if (code == "browsing" or btn == "browsing") and step not in _FUNNEL:
            variant = P.pick(P.BROWSING_START, sess, "browsing")
            return list(variant), BUTTONS["browsing"], _ctx_upd(sess, {"step": "browsing"}), False

        if code == "show_bonus" or btn == "show_bonus":
            return (
                [
                    "Ой, это моя любимая тема 😄",
                    "Если бронируете напрямую у нас — баллы: 500 за регистрацию, дальше с каждого проживания. "
                    "1 балл = 1 ₽.",
                ],
                BUTTONS["bonus"],
                {"step": "bonus"},
                False,
            )

        # mid-воронка: «сначала посмотрим / скиньте варианты» — карточки, слоты не сбрасываем
        if step in ("await_dates", "await_guests", "await_district") and not btn:
            try:
                from bot.catalog import budget_from_sess, offer_bundle, wants_variants

                if (
                    wants_variants(text)
                    and parse_dates(text) is None
                    and parse_guests(text) is None
                    and parse_district(text) is None
                ):
                    cards, offered = offer_bundle(
                        district=str(sess.get("district") or "не принципиально"),
                        guests=str(sess.get("guests") or "2"),
                        budget=budget_from_sess(sess),
                        limit=3,
                    )
                    ctx = dict(sess.get("context") or {})
                    if offered:
                        ctx["offers"] = offered
                    if step == "await_district":
                        ask, btns = "выберите район", None
                    elif step == "await_dates":
                        ask, btns = "подскажите даты поездки", BUTTONS["dates"]
                    else:
                        ask, btns = "подскажите, сколько будет гостей", BUTTONS["guests"]
                    msgs = ["Хорошо, пришлю пару вариантов посмотреть 🙂"]
                    if cards:
                        msgs.append(cards)
                    msgs.append(f"Если подходит, номер или название. Или {ask}.")
                    return msgs, btns, _ctx_upd(sess, {"context": ctx}), False
            except Exception:
                pass

        # —— воронка looking: район → даты → гости → календарь ——
        if step == "await_district" or (code == "district" and btn):
            if btn == "d_center":
                district = "центр"
            elif btn == "d_near":
                district = "Близко к центру"
            elif btn == "d_green":
                district = "Тихий зелёный район"
            elif btn == "d_sleep":
                district = "Спальный район"
            elif btn == "d_suburb":
                district = "Подмосковье"
            elif btn == "d_calm":
                district = "спокойный район"
            elif btn == "d_any":
                district = "не принципиально"
            else:
                district = parse_district(text)
                if not district:
                    raw = re.sub(r"[\s)(!.…🙂😊]+$", "", (text or "").strip())
                    if (
                        2 <= len(raw) <= 40
                        and "?" not in (text or "")
                        and not re.search(
                            r"(?i)вариант|посмотр|скин|пришл|предлож|давайте|"
                            r"сначала|квартир|ищу|подбер|спасиб|привет|"
                            r"сколь?ко|цен|стоит|можно|есть ли|почему|когда|зачем",
                            raw,
                        )
                        and parse_dates(raw) is None
                        and parse_guests(raw) is None
                        and parse_returning(raw) is None
                    ):
                        district = raw[:60]
                    else:
                        msgs, btns = _step_ask("await_district")
                        return msgs, btns, _ctx_upd(sess, {}), False
            fav = str(sess.get("favorite") or "")
            if fav:
                return (
                    [
                        f"Поняла, район «{district}».",
                        f"По «{fav}» — были у нас раньше или впервые?",
                    ],
                    BUTTONS["returning"],
                    _ctx_upd(
                        sess,
                        {
                            "district": district,
                            "favorite": fav,
                            "step": "await_returning",
                        },
                    ),
                    False,
                )
            # район выбран — спрашиваем даты (если уже есть — гостей / календарь)
            if sess.get("dates") and sess.get("guests"):
                return self.handle(
                    {**sess, "district": district, "step": "await_guests"},
                    str(sess.get("guests") or "2"),
                )
            if sess.get("dates"):
                msgs = list(P.pick(P.DATES_OK, sess, "dates_ok"))
                return (
                    msgs,
                    BUTTONS["guests"],
                    _ctx_upd(sess, {"district": district, "step": "await_guests"}),
                    False,
                )
            msgs = list(P.pick(P.DISTRICT_OK, sess, "district_ok"))
            return (
                msgs,
                BUTTONS["dates"],
                _ctx_upd(sess, {"district": district, "step": "await_dates"}),
                False,
            )

        if step == "await_dates" or (code == "dates" and btn):
            if btn == "dates_weekend":
                dates = "ближайшие выходные"
            elif btn == "dates_soon":
                dates = "через 2-3 недели"
            elif btn == "dates_unknown":
                dates = "ещё не определились"
            else:
                dates = parse_dates(text, allow_day_1_3=True)
                if not dates:
                    if re.search(r"(?i)ищу|квартир|подбер|брон", text):
                        return (
                            ["Хорошо 🙂 Подскажите, пожалуйста, на какие даты планируете поездку?"],
                            BUTTONS["dates"],
                            _ctx_upd(sess, {}),
                            False,
                        )
                    msgs, btns = _step_ask("await_dates")
                    return msgs, btns, _ctx_upd(sess, {}), False
            # без района сначала добираем район
            if not sess.get("district"):
                return (
                    [P.district_choice_message()],
                    None,
                    _ctx_upd(
                        sess,
                        {
                            "dates": dates,
                            "step": "await_district",
                            "favorite": sess.get("favorite") or "",
                        },
                    ),
                    False,
                )
            msgs = list(P.pick(P.DATES_OK, sess, "dates_ok"))
            return (
                msgs,
                BUTTONS["guests"],
                _ctx_upd(
                    sess,
                    {
                        "dates": dates,
                        "step": "await_guests",
                        "favorite": sess.get("favorite") or "",
                    },
                ),
                False,
            )

        if step == "await_guests" or (code == "guests" and btn):
            if btn == "g_12":
                guests = "1-2"
            elif btn == "g_34":
                guests = "3-4"
            elif btn == "g_more":
                guests = "5+"
            else:
                guests = parse_guests(text)
                if not guests:
                    msgs, btns = _step_ask("await_guests")
                    return msgs, btns, _ctx_upd(sess, {}), False
            fav = str(sess.get("favorite") or "")
            if fav:
                return (
                    [
                        f"Поняла, вас {guests}.",
                        f"По «{fav}» — были у нас раньше или впервые?",
                    ],
                    BUTTONS["returning"],
                    _ctx_upd(
                        sess,
                        {
                            "guests": guests,
                            "favorite": fav,
                            "step": "await_returning",
                            "district": sess.get("district") or "не принципиально",
                        },
                    ),
                    False,
                )
            if not sess.get("district"):
                return (
                    [P.district_choice_message()],
                    None,
                    _ctx_upd(sess, {"guests": guests, "step": "await_district"}),
                    False,
                )
            if not sess.get("dates"):
                msgs = list(P.pick(P.DISTRICT_OK, sess, "district_ok"))
                return (
                    msgs,
                    BUTTONS["dates"],
                    _ctx_upd(sess, {"guests": guests, "step": "await_dates"}),
                    False,
                )
            # район + даты + гости → свободные квартиры из TravelLine с ссылками и ценами
            return self._offers_after_slots(
                {**sess, "guests": guests},
                district=str(sess.get("district") or "не принципиально"),
                guests=guests,
            )

        if step == "await_returning":
            from bot.catalog import budget_from_sess, find_by_name_fuzzy, offer_bundle, parse_offer_pick, wants_variants

            ctx = dict(sess.get("context") or {})
            offers = [str(x) for x in (ctx.get("offers") or []) if x]
            favorite = str(sess.get("favorite") or "")

            # просят варианты / не знают квартиры — сначала каталог, не handoff в пустоту
            wants_cards = (
                wants_variants(text)
                or re.search(
                    r"(?i)не\s*знаю\s*(ваш|квартир)|какие\s*есть|покажи|скинь|предложи|"
                    r"не\s*видел|не\s*смотрел",
                    text,
                )
                or not offers
            ) and parse_offer_pick(text) is None and find_by_name_fuzzy(text) is None

            # другие варианты — только если явно не выбор номера
            if (
                re.search(
                    r"(?i)не\s*пойд|не\s*нрав|не\s*подход|не\s*то\b|другие|ещё\s*вариант|еще\s*вариант",
                    text,
                )
                and parse_offer_pick(text) is None
            ) or (wants_cards and not offers):
                ret_early = parse_returning(text)
                cards, new_offers = offer_bundle(
                    district=str(sess.get("district") or "не принципиально"),
                    guests=str(sess.get("guests") or "2"),
                    budget=budget_from_sess(sess),
                    limit=3,
                    exclude_names=offers if offers else None,
                )
                upd_extra: dict[str, Any] = {"context": ctx}
                if ret_early:
                    upd_extra["returning"] = ret_early
                if cards:
                    ctx["offers"] = new_offers
                    upd_extra["context"] = ctx
                    lead = "Вот варианты 🙂" if not offers else "Другие варианты 🙂"
                    if cards.lstrip().lower().startswith("подобрала"):
                        lead = ""  # в карточках уже есть «Подобрала…», второй заголовок не нужен
                    return (
                        [
                            *( [lead] if lead else [] ),
                            cards,
                            "Номер / название — или «впервые» / «были у нас».",
                        ],
                        BUTTONS["returning"],
                        _ctx_upd(sess, upd_extra),
                        False,
                    )
                if not offers:
                    # каталог реально пуст — тогда уж handoff
                    return self.handoff_looking(
                        {**sess, "returning": ret_early or sess.get("returning") or ""},
                        note="Каталог не подошёл по вместимости — подберёт менеджер.",
                    )

            num = parse_offer_pick(text)
            if num and offers and 1 <= num <= len(offers):
                favorite = offers[num - 1]
            else:
                hit = find_by_name_fuzzy(text)
                if hit:
                    favorite = str(hit["name"])

            ret = parse_returning(text)
            if ret is None and (btn == "ret_yes" or code == "ret_yes"):
                ret = "да"
            if ret is None and (btn == "ret_no" or code == "ret_no"):
                ret = "нет"
            # уже отвечали «впервые / были» раньше в этом шаге
            if ret is None and sess.get("returning") in ("да", "нет"):
                ret = str(sess.get("returning"))

            if favorite and not ret:
                return (
                    [
                        f"Отлично, беру «{favorite}» 🙂",
                        "Были у нас раньше или впервые?",
                    ],
                    BUTTONS["returning"],
                    _ctx_upd(sess, {"favorite": favorite, "context": ctx}),
                    False,
                )

            if ret == "да":
                if favorite:
                    return self.ask_comfort_or_handoff(
                        {**sess, "favorite": favorite, "returning": "да"},
                        note=f"Постоянный гость, предпочитает «{favorite}».",
                    )
                return (
                    ["Здорово) Напомните название или адрес квартиры, отмечу как постоянного гостя."],
                    None,
                    _ctx_upd(
                        sess,
                        {"returning": "да", "step": "await_favorite", "favorite": favorite or ""},
                    ),
                    False,
                )

            if ret == "нет":
                # впервые: нет карточек или явно просят варианты — сначала каталог
                if not favorite and (
                    not offers
                    or wants_variants(text)
                    or re.search(
                        r"(?i)не\s*знаю\s*(ваш|квартир)|какие\s*есть|покажи|скинь|предложи",
                        text,
                    )
                ):
                    cards, new_offers = offer_bundle(
                        district=str(sess.get("district") or "не принципиально"),
                        guests=str(sess.get("guests") or "2"),
                        budget=budget_from_sess(sess),
                        limit=3,
                        exclude_names=offers if offers else None,
                    )
                    if cards:
                        ctx["offers"] = new_offers
                        return (
                            [
                                "Хорошо, впервые — сейчас пришлю варианты 🙂",
                                cards,
                                "Если подходит, номер или название.",
                            ],
                            BUTTONS["returning"],
                            _ctx_upd(sess, {"returning": "нет", "context": ctx}),
                            False,
                        )
                note = f"Интересует «{favorite}»." if favorite else ""
                return self.ask_comfort_or_handoff(
                    {**sess, "favorite": favorite, "returning": "нет"},
                    note=note,
                )

            if favorite:
                return (
                    [f"«{favorite}» беру в работу. Вы у нас уже были или впервые?"],
                    BUTTONS["returning"],
                    _ctx_upd(sess, {"favorite": favorite, "context": ctx}),
                    False,
                )
            return (
                ["Напишите номер варианта (1–3) / название — или «впервые» / «были у нас»."],
                BUTTONS["returning"],
                _ctx_upd(sess, {"context": ctx}),
                False,
            )

        if step == "await_favorite":
            from bot.catalog import find_by_name_fuzzy

            fav = text.strip()[:120]
            if len(fav) < 2:
                msgs, btns = _step_ask("await_favorite")
                return msgs, btns, _ctx_upd(sess, {}), False
            hit = find_by_name_fuzzy(fav)
            name = str(hit["name"]) if hit else fav
            return self.handoff_looking(
                {**sess, "favorite": name, "returning": "да"},
                note=f"Постоянный гость, предпочитает «{name}».",
            )

        # —— browsing / done после карточек ——
        if step in ("browsing", "done"):
            from bot.catalog import budget_from_sess, find_by_name_fuzzy, offer_bundle, parse_offer_pick

            ctx = dict(sess.get("context") or {})
            offers = [str(x) for x in (ctx.get("offers") or []) if x]

            # выбор номера / названия → фиксируем любимое, спрашиваем даты (не каталог снова)
            num = parse_offer_pick(text)
            favorite = ""
            if num and offers and 1 <= num <= len(offers):
                favorite = offers[num - 1]
            else:
                hit = find_by_name_fuzzy(text)
                if hit:
                    favorite = str(hit["name"])

            if favorite:
                return (
                    [
                        f"Отлично, беру «{favorite}» 🙂",
                        "Подскажите даты — забронируем?",
                    ],
                    BUTTONS["dates"],
                    _ctx_upd(
                        sess,
                        {
                            "favorite": favorite,
                            "step": "await_dates",
                            "handed_off": 0,
                            "context": ctx,
                        },
                    ),
                    False,
                )

            # «1 меня устраивает», а offers пустые — не крутить browsing-меню
            if num is not None:
                return (
                    [
                        "Не вижу номер в последнем списке — напишите название квартиры "
                        "(например «Чехов»), или скажите «ещё варианты»."
                    ],
                    None,
                    _ctx_upd(sess, {"context": ctx}),
                    False,
                )

            if step == "browsing" and (
                code == "browse_yes"
                or btn == "browse_yes"
                or low in ("да", "давайте", "ок", "угу", "ага")
            ):
                cards, offered = offer_bundle(
                    district=str(sess.get("district") or "не принципиально"),
                    guests=str(sess.get("guests") or "2"),
                    budget=budget_from_sess(sess),
                    limit=3,
                )
                if cards:
                    msgs = [cards, f"Ещё каталог на сайте: {self.s.site_url}"]
                else:
                    msgs = [
                        f"Ловите каталог: {self.s.site_url}",
                        f"Новинки в канале: {self.s.channel_url}",
                    ]
                msgs.append("Если подходит, номер (1–3) или название, забронируем 🙂")
                if offered:
                    ctx["offers"] = offered
                return (
                    msgs,
                    None,
                    _ctx_upd(sess, {"step": "done", "context": ctx}),
                    False,
                )
            if step == "browsing" and (
                code == "browse_no" or btn == "browse_no" or is_refusal(text)
            ):
                return self.soft_close(sess)
            if step == "browsing" and code == "looking":
                return self.handle({**sess, "step": "await_intent"}, "looking")
            if step == "browsing":
                return (
                    ["Могу прислать пару вариантов на будущее — или пока оставим на потом?"],
                    BUTTONS["browsing"],
                    {},
                    False,
                )
            # step == done без выбора — ниже общий done

        # —— bonus ——
        if step == "bonus":
            if code == "loyalty_register" or btn == "loyalty_register":
                return (
                    [
                        f"Вот ссылка, регистрация за минуту: {self.s.loyalty_url}\n"
                        "Как зарегистрируетесь — баллы сразу на счёт."
                    ],
                    BUTTONS["bonus"],
                    {},
                    False,
                )
            if code == "loyalty_via_agg" or btn == "loyalty_via_agg":
                return (
                    [
                        "Если через Букинг/Островок — баллы не начисляются, комиссию забирает сервис.\n"
                        "А если в следующий раз напишете нам напрямую — и дешевле, и баллы капают 🙂"
                    ],
                    BUTTONS["bonus"],
                    {},
                    False,
                )
            if code == "loyalty_done" or btn == "loyalty_done" or is_refusal(text) or code == "thanks":
                return self.soft_close(sess)
            return (
                ["Могу прислать ссылку на регистрацию или коротко про бронь через агрегаторы — что удобнее?"],
                BUTTONS["bonus"],
                {},
                False,
            )

        if step in ("done",):
            # новый заход после завершения
            if code in ("looking", "browsing", "show_bonus", "hello") or low in ("да", "привет"):
                return self.handle({**sess, "step": "await_intent", "handed_off": 0}, text)
            return self.soft_close(sess)

        if step == "greeting":
            msgs, btns, upd = self.greeting(sess)
            return msgs, btns, upd, False

        if step in ("greeting", "await_intent"):
            return (
                [
                    "Подскажите, пожалуйста, на какие даты планируете поездку?"
                ],
                BUTTONS["greeting"],
                {"step": "await_intent"},
                False,
            )

        # неизвестно — мягкий вопрос шага (не пустой ответ)
        msgs, btns = _step_ask(step if step in (
            "await_dates", "await_guests", "await_district", "await_returning",
            "await_favorite", "await_intent", "browsing", "bonus",
        ) else "await_intent")
        return msgs, btns, _ctx_upd(sess, {"step": step if step.startswith("await_") or step in ("browsing", "bonus") else "await_intent"}), False
