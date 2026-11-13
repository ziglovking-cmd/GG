# -*- coding: utf-8 -*-
"""Квартиры с пользовательской карты Яндекса: адрес, район, метро.

Источник: конструктор
um=constructor:bdeef0c08aec1d97b5aa903542582d5c940e2a892be6fc3f5a1600ea514169ca
Цены и свободные даты здесь не хранятся — их даёт календарь.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Home:
    address: str
    names: tuple[str, ...]
    area: str
    metro: str
    zone: str  # calm | inner | outer | south
    [REDACTED]


HOMES: tuple[Home, ...] = (
    Home("проезд Стройкомбината, 1", ("Белуха", "Казбек", "Эльбрус", "Аннапурна"), "Очаково", "м. Очаково", "calm", "ochakovo"),
    Home("Бачуринская улица, 9Ак1", ("Вайт",), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("Фитарёвская улица, 17", ("Скандинавия",), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("Фитарёвская улица, 6", ("Россо",), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("улица Василия Ощепкова, 1", ("Шамбала",), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("улица Василия Ощепкова, 3", ("Романс",), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("улица Василия Ощепкова, 6", ("Матисс",), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("микрорайон Эдальго, 5", ("Идальго",), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("улица Лобановский Лес, 11", ("Хомлин", "Бриз", "Нуар"), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("улица Лобановский Лес, 13", ("Сноу пикс", "Вояж"), "Коммунарка", "м. Коммунарка", "calm", "kommunarka"),
    Home("Прокшинский проспект, 9", ("Артмен и Карма",), "Прокшино", "м. Прокшино", "calm", "prokshino"),
    Home("Мосрентген квартал № 2, 5с3", ("Артледи",), "Мосрентген", "своего метро нет, ближайшее м. Саларьево", "calm", "mosrentgen"),
    Home("Южнобутовская улица, 76", ("Дзен",), "Южное Бутово", "м. Бунинская аллея", "calm", "butovo"),
    Home("Профсоюзная улица, 110к3", ("Минт", "Санлайт", "Аквамарин"), "Коньково", "м. Беляево", "calm", "belyaevo"),
    Home("Севанская улица, 7к2", ("Марс", "Венера", "Меркурий"), "Марьино", "м. Марьино", "calm", "maryino"),
    Home("Котельники, Сосновая улица, 1к2", ("Юниверсал", "Мирамакс", "Парамаунт"), "Котельники", "м. Котельники", "calm", "kotelniki"),
    Home("Тюменский проезд, 3к1", ("Чаплин",), "Гольяново", "м. Щёлковская", "calm", "east"),
    Home("Открытое шоссе, 14Д", ("Талисман",), "Метрогородок", "м. Бульвар Рокоссовского", "calm", "east"),
    Home("Тагильская улица, 2к1", ("Монро",), "Гольяново", "м. Бульвар Рокоссовского", "calm", "east"),
    Home("Одинцово, Северная улица, 9", ("Фрейя", "Сага", "Эллида", "Энигма"), "Одинцово", "МЦД-1 «Одинцово», не московское метро", "calm", "odintsovo"),
    Home("Одинцово, Верхне-Пролетарская улица, 7", ("Дарк", "Милк", "Грин"), "Одинцово", "МЦД-1 «Одинцово», не московское метро", "calm", "odintsovo"),
    Home("Одинцово, ул. Каштановая, 6", ("Дега", "Малевич", "Кандинский", "Ван Гог", "Мондриан"), "Одинцово", "МЦД-1 «Одинцово», не московское метро", "calm", "odintsovo"),
    Home("2-й Нагатинский проезд, 2/3", ("Сойка",), "Нагатино", "м. Коломенская", "south", "nagatino"),
    Home("Нагатинская набережная, 10А", ("Сапфир",), "Нагатинский Затон", "м. Нагатинский Затон", "south", "nagatino"),
    Home("Газгольдерная улица, 10", ("Магнолия",), "Даниловский", "м. Дубровка", "south", "zil"),
    Home("улица Руставели, 14", ("Рим",), "Бутырский", "м. Бутырская", "outer", "butyrskaya"),
    Home("Красноказарменная улица, 15к4", ("Монблан",), "Лефортово", "м. Авиамоторная", "outer", "lefortovo"),
    Home("1-я Магистральная улица, 25", ("Индиго", "Сандал", "Рубин", "Олимп", "Эверест"), "Хорошёво", "м. Хорошёвская", "outer", "khoroshevo"),
    Home("Балакиревский пер, 23", ("Чехов", "Дягилев", "Шаляпин", "Маяковский"), "Басманный", "м. Бауманская", "inner", "baumanskaya"),
)

_INNER = next(h for h in HOMES if h.[REDACTED] "baumanskaya")
_KOTELNIKI = next(h for h in HOMES if h.[REDACTED] "kotelniki")

_NAME_TO_HOME: list[tuple[str, Home]] = []
for _home in HOMES:
    for _name in _home.names:
        _NAME_TO_HOME.append((_name.lower().replace("ё", "е"), _home))
_NAME_TO_HOME.sort([REDACTED] item: len(item[0]), reverse=True)

_AREA_STEMS: tuple[tuple[str, str], ...] = (
    (r"арбат", "arbat"),
    (r"котельник", "kotelniki"),
    (r"коммунарк|фитар|бачурин|ощепков|лобанов|эдальго|идальго|стройкомбинат", "kommunarka"),
    (r"прокшин", "prokshino"),
    (r"мосрентген|артледи", "mosrentgen"),
    (r"бутов", "butovo"),
    (r"беляев|коньков|профсоюз", "belyaevo"),
    (r"марьин|севанск", "maryino"),
    (r"щелков|тюменск|чаплин|гольянов", "east"),
    (r"рокоссов|метрогород|открыт\w*\s+шоссе|тагильск|монро|талисман", "east"),
    (r"одинцов|каштанов", "odintsovo"),
    (r"нагатин", "nagatino"),
    (r"газгольдер|дубровк|\bзил\b", "zil"),
    (r"руставели|бутырск", "butyrskaya"),
    (r"лефортов|красноказарм|авиамотор", "lefortovo"),
    (r"хорош|магистральн", "khoroshevo"),
    (r"бауман|балакирев|басман", "baumanskaya"),
)


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def homes_by_key([REDACTED] -> list[Home]:
    return [h for h in HOMES if h.[REDACTED] key]


def find_names(text: str) -> list[tuple[str, Home | None]]:
    """Имена с карты и названия из строки календаря «Имя — 1234»."""
    raw = _norm(text)
    found: list[tuple[str, Home | None]] = []
    seen: set[str] = set()
    for stem, home in _NAME_TO_HOME:
        if stem in seen:
            continue
        if re.search(rf"(?<![а-яa-z]){re.escape(stem)}(?![а-яa-z])", raw):
            seen.add(stem)
            label = next(n for n in home.names if n.lower().replace("ё", "е") == stem)
            found.append((label, home))
    for token in re.findall(r"([A-Za-zА-ЯЁа-яё]{4,})\s+[—-]\s*\d", text or ""):
        stem = token.lower().replace("ё", "е")
        if stem in seen:
            continue
        seen.add(stem)
        home = next((h for name, h in _NAME_TO_HOME if name == stem), None)
        label = token[:1].upper() + token[1:]
        found.append((label, home))
    return found


def _area_key(text: str) -> str | None:
    t = _norm(text)
    for rx, key in _AREA_STEMS:
        if re.search(rx, t):
            return key
    try:
        from bot.engine import parse_district
    except Exception:
        return None
    district = parse_district(text) or ""
    d = _norm(district)
    if "арбат" in d:
        return "arbat"
    if "котельник" in d:
        return "kotelniki"
    if re.search(r"спокой", d):
        return "calm"
    if d.strip() in {"центр", "в центре"}:
        return "center"
    return None


def _fmt_home(home: Home) -> str:
    names = ", ".join(home.names)
    return f"{names} — {home.address}, {home.area}, {home.metro}"


def _fmt_names(pairs: list[tuple[str, Home | None]]) -> str:
    bits: list[str] = []
    seen_addr: set[str] = set()
    for label, home in pairs:
        if home is None:
            bits.append(f"{label} на карте не отмечен, адрес не подтверждаю")
            continue
        if home.address in seen_addr:
            continue
        seen_addr.add(home.address)
        bits.append(_fmt_home(home))
    return ". ".join(bits)


def _cluster_line([REDACTED] -> str:
    homes = homes_by_key(key)
    if not homes:
        return ""
    area = homes[0].area
    metro = homes[0].metro
    names: list[str] = []
    for home in homes:
        names.extend(home.names)
    shown = ", ".join(names[:8])
    more = f" и ещё {len(names) - 8}" if len(names) > 8 else ""
    return f"{area}, {metro}: {shown}{more}"


def _calm_line() -> str:
    return (
        "Поспокойнее на карте — это не один район. "
        "Коммунарка, м. Коммунарка; Котельники, метро одно — «Котельники»; "
        "Одинцово, МЦД-1, без московского метро; Южное Бутово; "
        "восток — м. Щёлковская и м. Бульвар Рокоссовского. "
        "Какой из них ближе?"
    )


def _arbat_line(dates: str, pairs: list[tuple[str, Home | None]]) -> str:
    known = [p for p in pairs if p[1] is not None or p[0]]
    if known:
        head = "Нет, не рядом с Новым Арбатом"
        if dates:
            head = f"На {dates} не рядом с Новым Арбатом"
        return (
            f"{head}. {_fmt_names(known)}. "
            "У Нового Арбата на карте квартир нет."
        )
    head = "У Нового Арбата на карте квартир нет"
    if dates:
        head = f"На {dates} у Нового Арбата квартир нет"
    return (
        f"{head}. Ближе остальных к центру — {_fmt_home(_INNER)}. Это не Арбат."
    )


def _kotelniki_line(dates: str) -> str:
    fact = (
        "Котельники — город у МКАД. Метро одно, «Котельники»: "
        "район и станция называются одинаково, второй станции с другим именем нет. "
        f"{_fmt_home(_KOTELNIKI)}."
    )
    if dates:
        return f"На {dates}. {fact}"
    return fact


def is_geography_question(text: str) -> bool:
    raw = text or ""
    t = _norm(raw).strip()
    if not t:
        return False
    if re.fullmatch(r"(?:а\s+)?это\s+ты\??", t) or re.fullmatch(r"как\s+быть\??", t):
        return False
    if re.search(r"это\s+что|что\s+это", t) and "какой" not in t:
        return False
    if re.search(r"я\s+(?:же\s+)?(?:выше|уже)\s+(?:писал|писала)", t):
        return False
    if re.search(r"как\s+настроен|как\s+дела\b", t):
        return False
    if re.search(r"рядом|это\s+какой|это\s+где|какой\s+район|где\s+это", t):
        return True
    if re.search(r"метро", t) and re.search(r"отлича|какой|где|это", t):
        return True
    area = _area_key(raw)
    named = [p for p in find_names(raw) if p[1] is not None]
    if named and re.search(r"где|метро|район|рядом|адрес", t):
        return True
    if area in {"arbat", "kotelniki", "center", "calm"} or (area and area not in {"calm", "center"}):
        if "?" in raw or re.search(r"\bесть\b|квартир|свобод|рядом", t):
            if area == "calm" and not re.search(r"какой|где|это|метро|рядом", t):
                return False
            return True
    if area and re.search(r"где|метро|рядом", t):
        return True
    return False


def _history_blob(history: list[dict] | None) -> str:
    bits: list[str] = []
    for item in reversed(history or []):
        if (item.get("role") or "") == "bot" and str(item.get("text") or "").strip():
            bits.append(str(item.get("text") or ""))
        if len(bits) >= 6:
            break
    return "\n".join(reversed(bits))


def geography_line(
    text: str,
    sess: dict | None = None,
    history: list[dict] | None = None,
) -> tuple[str, str | None] | None:
    """Полный ответ по карте. Второй элемент — район, который можно записать в слот."""
    if not is_geography_question(text):
        return None
    sess = sess or {}
    t = _norm(text)
    try:
        from bot.engine import parse_dates
    except Exception:
        parse_dates = lambda _s: None  # type: ignore
    dates = parse_dates(text) or ""
    if dates == "ещё не определились":
        dates = ""
    district_now = str(sess.get("district") or "")
    hist = _history_blob(history)
    blob = f"{text}\n{district_now}\n{hist}"
    area_from_text = _area_key(text)
    asks_which = bool(re.search(r"это\s+какой|это\s+где|где\s+это|какой\s+район", t))
    area = area_from_text or (_area_key(district_now) if asks_which else None)
    own = [(n, h) for n, h in find_names(text) if h is not None]
    pulled: list[tuple[str, Home | None]] = []
    if re.search(r"\b(они|эти|тех|вариант)", t) or (re.search(r"метро", t) and re.search(r"отлича", t)):
        pulled = find_names(hist)

    if re.search(r"метро", t) and re.search(r"отлича", t):
        if re.search(r"котельник", _norm(blob)):
            return _kotelniki_line(""), None
        if pulled:
            return f"Это разные станции, квартиры не в одном месте. {_fmt_names(pulled)}.", None
        return (
            "Станции разные, потому что квартиры в разных районах. Напишите название — скажу метро и адрес.",
            None,
        )

    if re.search(r"это\s+какой|это\s+где|какой\s+район|где\s+это", t) and not re.search(
        r"арбат|котельник", t
    ):
        if re.search(r"котельник", _norm(district_now)) or area == "kotelniki":
            return _kotelniki_line(""), "Котельники"
        if area and area not in {"calm", "center", "arbat"}:
            return _cluster_line(area) + ".", None
        if re.search(r"спокой|тих", _norm(district_now)) or area == "calm":
            return _calm_line(), None
        if area == "center" or re.search(r"центр", _norm(district_now)):
            return (
                f"В центре и у Нового Арбата квартир нет. Ближе остальных — {_fmt_home(_INNER)}. Это не центр Садового.",
                None,
            )
        return _calm_line(), None

    if own and not re.search(r"арбат", t):
        home = own[0][1]
        if area_from_text and home and home.key != area_from_text and area_from_text not in {"calm", "center"}:
            stored = {"kotelniki": "Котельники", "kommunarka": "Коммунарка"}.get(area_from_text)
            return f"Нет. {_fmt_names(own)}.", stored
        return f"{_fmt_names(own)}.", None

    if area == "arbat" or re.search(r"арбат", t):
        line = _arbat_line(dates, pulled or own)
        if re.search(r"рядом", t) and not line.lower().startswith("нет"):
            line = f"Нет, не рядом. {line}"
        return line, "Новый Арбат"

    if area == "kotelniki" or re.search(r"котельник", t):
        return _kotelniki_line(dates), "Котельники"

    if area == "center":
        return (
            f"В центре и у Нового Арбата квартир нет. Ближе остальных — {_fmt_home(_INNER)}.",
            None,
        )

    if area == "calm":
        return _calm_line(), None

    if own:
        return f"{_fmt_names(own)}.", None

    if area:
        line = _cluster_line(area)
        if not line:
            return None
        if dates:
            line = f"На {dates}. {line}"
        stored = {
            "kotelniki": "Котельники",
            "kommunarka": "Коммунарка",
            "odintsovo": "Одинцово",
            "lefortovo": "Лефортово",
            "khoroshevo": "Хорошёво",
        }.get(area)
        return line + ".", stored

    return None


def district_fact(district: str) -> str:
    """Факт, когда гость уже назвал район. Для «центра» это ближайшие квартиры, не эхо слова."""
    [REDACTED] or "")
    if [REDACTED] "center":
        return (
            f"В центре и у Нового Арбата квартир нет. Ближе остальных — {_fmt_home(_INNER)}."
        )
    if [REDACTED] "calm":
        # «поспокойнее» — предпочтение, не список районов.
        return ""
    if [REDACTED] "arbat":
        return _arbat_line("", [])
    if [REDACTED] "kotelniki":
        return _kotelniki_line("")
    if [REDACTED] = _cluster_line(key)
        return f"{line}." if line else ""
    return ""


def area_blurb(district: str) -> str:
    """Короткий факт по району с карты. Пусто, если района на карте нет."""
    [REDACTED] or "")
    if [REDACTED] "arbat":
        return _arbat_line("", [])
    if [REDACTED] "kotelniki":
        return _kotelniki_line("")
    if key in {"center", "calm"}:
        return ""
    if not [REDACTED] ""
    line = _cluster_line(key)
    return f"{line}." if line else ""


def map_brief_for_llm() -> str:
    """Короткий факт для system: где какая квартира. Без цен."""
    lines = [
        "Карта квартир (факт, не выдумывать адреса и метро):",
        "- Новый Арбат и Садовое: квартир нет.",
        f"- Ближе остальных к центру, но не Арбат: {_fmt_home(_INNER)}.",
        "- Хорошёво и Лефортово — не центр.",
        f"- Лефортово: {_fmt_home(next(h for h in HOMES if h.[REDACTED] 'lefortovo'))}.",
        f"- Хорошёво: {_fmt_home(next(h for h in HOMES if h.[REDACTED] 'khoroshevo'))}.",
        f"- Бутырская: {_fmt_home(next(h for h in HOMES if h.[REDACTED] 'butyrskaya'))}.",
        "- Котельники: метро одно, «Котельники», район и станция называются одинаково. "
        f"{_fmt_home(_KOTELNIKI)}.",
        "- Очаково: Белуха, Казбек, Эльбрус, Аннапурна.",
        "- Коммунарка, м. Коммунарка: Вайт, Скандинавия, Россо, Феррари, Шамбала, Романс, Матисс, Идальго.",
        "- Прокшино, м. Прокшино: Артмен, Карма, Хомлин, Бриз, Нуар, Сноу пикс, Вояж. "
        "Мосрентген, метро в посёлке нет: Артледи.",
        "- Южное Бутово: Дзен. Коньково, м. Беляево: Минт, Санлайт, Аквамарин. Марьино: Марс, Венера, Меркурий.",
        "- Восток: Чаплин — м. Щёлковская; Талисман и Монро — м. Бульвар Рокоссовского.",
        "- Одинцово, МЦД-1, не московское метро: Фрейя, Сага, Эллида, Энигма, Дарк, Милк, Грин, "
        "Дега, Малевич, Кандинский, Ван Гог, Мондриан.",
        "- Нагатино: Сойка — м. Коломенская; Сапфир — м. Нагатинский Затон. Магнолия — м. Дубровка.",
        "Если названия нет в этом списке — скажи, что на карте его нет. Цену и свободные даты не выдумывай. "
        "На вопрос «где / рядом / какое метро» ответь целиком: место, метро, какие квартиры.",
    ]
    return "\n".join(lines)
