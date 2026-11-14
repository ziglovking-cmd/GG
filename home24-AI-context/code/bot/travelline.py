"""Свободные квартиры из календаря TravelLine (тот же поиск, что на home24.msk.ru).

Цены и занятость только из ответа поиска. Если календарь недоступен — вызывающий
код оставляет прежнюю фразу «не подтверждаю», без выдуманных дат.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("home24.travelline")

PROPERTY_ID = "48944"
SEARCH_URL = "https://home24.msk.ru/api/travelline/room-stays/search"
SYNC_URL = "https://home24.msk.ru/api/travelline/sync-state"
ROOMS_PATH = Path("data/travelline_rooms.json")
UA = "Home24Calendar/1.0 (+home24.msk.ru)"

_MONTHS: tuple[tuple[str, int], ...] = (
    ("январ", 1),
    ("феврал", 2),
    ("март", 3),
    ("апрел", 4),
    ("ма[йя]", 5),
    ("июн", 6),
    ("июл", 7),
    ("август", 8),
    ("сентябр", 9),
    ("октябр", 10),
    ("ноябр", 11),
    ("декабр", 12),
)
_MONTH_GEN = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_ZONE_ONLY = frozenset(
    {
        "центр",
        "в центре",
        "ближе к центру",
        "близко к центру",
        "спокойный",
        "спокойный район",
        "поспокойнее",
        "потише",
        "спальный район",
        "тихий зелёный район",
        "тихий зеленый район",
        "подмосковье",
        "не принципиально",
    }
)
_STREET_TYPE = (
    r"(проезд|проспект|улиц\w*|шоссе|бульвар\w*|переул\w*|набережн\w*|тупик)"
)

SearchHook = Callable[[date, date, int], "list[Stay] | None"]

_hook: SearchHook | None = None
_lock = threading.Lock()
_rooms_at: float = 0.0
_rooms: list["Room"] = []
_search_cache: dict[tuple[str, str, int], tuple[float, list["Stay"]]] = {}
_ROOMS_TTL = 6 * 3600
_SEARCH_TTL = 10 * 60


@dataclass
class Room:
    room_id: str
    title: str
    address: str
    guests: int | None


@dataclass
class Stay:
    room_id: str
    title: str
    address: str = ""
    guests: int | None = None
    available: int = 1
    price_night: int | None = None
    price_total: int | None = None
    night_prices: tuple[int, ...] = ()
    raw_name: str = ""


def set_search_hook(hook: SearchHook | None) -> None:
    """Тесты подставляют календарь без сети. None — снова живой поиск."""
    global _hook
    _hook = hook


def _norm(text: str) -> str:
    s = (text or "").lower().replace("ё", "е")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def display_title(title: str) -> str:
    """«Апартаменты «Артмен» от Home24» → «Артмен»: гостю — короткое имя квартиры, как в скрипте."""
    t = " ".join((title or "").split())
    m = re.search(r"«([^»]+)»", t)
    if m:
        t = m.group(1)
    t = re.sub(r"(?i)\s*(?:от|by)\s+(?:home|nome|хоум)\s*24.*$", "", t)
    t = re.sub(r"(?i)^(?:апартаменты|апартамент|квартира|студия|apartments?|studio)\s+", "", t)
    t = re.sub(r"(?i)\s+(?:studio|студия|apartments?|flat)$", "", t)
    t = t.strip(" «»\"'")
    return t[:1].upper() + t[1:] if t else (title or "")


def _title_key(title: str) -> str:
    s = _norm(title)
    s = re.sub(r"\s+от\s+home\s*24.*$", "", s)
    s = re.sub(
        r"\s+(studio|студия|апартаменты|квартира|однокомнатная|двухкомнатная|"
        r"евро-трешка|двухуровневая)$",
        "",
        s,
    )
    s = re.sub(r"\s+", " ", s).strip(" «»\"'")
    return s


def _month_num(text: str) -> int | None:
    t = _norm(text)
    for stem, num in _MONTHS:
        if re.search(stem, t):
            return num
    return None


def _dated(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _roll(month: int, day: int, today: date) -> date | None:
    found = _dated(today.year, month, day)
    if found is None:
        return None
    if found < today:
        found = _dated(today.year + 1, month, day)
    return found


def stay_span(phrase: str | None, today: date | None = None) -> tuple[date, date] | None:
    """Фраза гостя → заезд и выезд. Без месяца (кроме завтра/выходных) — None."""
    today = today or date.today()
    t = _norm(phrase or "")
    if not t or re.search(r"не определ|пока не знаю|еще не знаю|ещё не знаю", t):
        return None
    if re.search(r"\bсегодня\b", t):
        return today, today + timedelta(days=1)
    if re.search(r"\bпослезавтра\b", t):
        start = today + timedelta(days=2)
        return start, start + timedelta(days=1)
    if re.search(r"\bзавтра\b", t):
        start = today + timedelta(days=1)
        return start, start + timedelta(days=1)
    if re.search(r"нов(ый|ого)\s+год|новогодн", t):
        if today.month == 1 and today.day <= 2:
            start = date(today.year - 1, 12, 31)
        elif today.month == 12 and today.day == 31:
            start = today
        elif (today.month, today.day) < (12, 31):
            start = date(today.year, 12, 31)
        else:
            start = date(today.year + 1, 12, 31)
        return start, date(start.year + 1, 1, 2)
    if re.search(r"выходн", t):
        wd = today.weekday()
        if wd == 6:
            start = today + timedelta(days=6)
        else:
            start = today + timedelta(days=(5 - wd) % 7)
        return start, start + timedelta(days=2)

    m = re.search(
        r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\s*[-–—]\s*"
        r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?",
        t,
    )
    if m:
        y1 = int(m.group(3)) if m.group(3) else today.year
        y2 = int(m.group(6)) if m.group(6) else y1
        if y1 < 100:
            y1 += 2000
        if y2 < 100:
            y2 += 2000
        a = _dated(y1, int(m.group(2)), int(m.group(1)))
        b = _dated(y2, int(m.group(5)), int(m.group(4)))
        if a and b and b > a:
            return a, b

    m = re.search(r"(?:с\s*)?(\d{1,2})\s*(?:по|-|–|—)\s*(\d{1,2})", t)
    if m:
        month = _month_num(t)
        if not month:
            return None
        a = _roll(month, int(m.group(1)), today)
        b = _roll(month, int(m.group(2)), today)
        if a and b:
            if b <= a:
                b = _dated(a.year + 1, month, int(m.group(2)))
            if b and b > a:
                return a, b
    return None


def span_label(arrival: date, departure: date) -> str:
    if arrival.month == departure.month and arrival.year == departure.year:
        return f"{arrival.day}–{departure.day} {_MONTH_GEN[arrival.month]}"
    return (
        f"{arrival.day} {_MONTH_GEN[arrival.month]} – "
        f"{departure.day} {_MONTH_GEN[departure.month]}"
    )


def _nights_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "ночь"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "ночи"
    return "ночей"


def _street(text: str) -> tuple[str, str] | None:
    m = re.search(rf"([а-я]{{4,}})\s+{_STREET_TYPE}", _norm(text))
    if not m:
        return None
    stem = re.sub(r"(ский|ская|ское|ий|ая|ое)$", "", m.group(1))
    if len(stem) < 5:
        stem = m.group(1)
    kind = m.group(2)
    kind = re.sub(r"(улиц|бульвар|переул|набережн).*", lambda g: g.group(0)[:6], kind)
    if kind.startswith("улиц"):
        kind = "улиц"
    elif kind.startswith("бульвар"):
        kind = "бульвар"
    elif kind.startswith("переул"):
        kind = "переул"
    elif kind.startswith("набереж"):
        kind = "набереж"
    return stem, kind


def _is_zone(place: str) -> bool:
    return _norm(place) in _ZONE_ONLY


def matches_place(stay: Stay, place: str) -> bool:
    """Улица с типом важнее района: проезд не равен проспекту.

    Зоны и локации из раздела «Районы» script.md — через in_area
    (центр / близко к центру / спальный / зелёный / Подмосковье / Прокшино…).
    """
    raw = _norm(place)
    if not raw:
        return False
    street = _street(raw)
    addr = _norm(stay.address)
    title = _title_key(stay.title)
    if street:
        stem, kind = street
        if stem in addr and kind in addr:
            return True
        return False
    if title and (title == raw or f" {title} " in f" {raw} " or title in raw):
        return True
    try:
        from bot.apartments_map import areas_for_place, in_area

        # «Прокшино» / «Близко к центру» → квартиры из раздела «Районы» в script.md
        if areas_for_place(place):
            return in_area(stay.title, place)
        if in_area(stay.title, place):
            return True
    except Exception:
        pass
    if _is_zone(raw):
        return False
    token = re.sub(r"[^а-яa-z0-9 ]+", "", raw).strip()
    stem = re.sub(r"(ский|ская|ское|о|а|е)$", "", token.split(" ")[0])
    if len(stem) >= 5 and (stem in addr or stem in title):
        return True
    return False


def _http_json(
    url: str,
    body: bytes | None = None,
    timeout: float = 20.0,
    retries: int = 1,
) -> Any | None:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    for attempt in range(max(1, retries)):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "ignore"))
        except Exception as exc:
            logger.warning("travelline fetch failed: %s", type(exc).__name__)
            if attempt + 1 < retries:
                time.sleep(0.6)
    return None


def _rooms_file_fresh() -> bool:
    try:
        age = time.time() - ROOMS_PATH.stat().st_mtime
    except OSError:
        return False
    return age < _ROOMS_TTL


def _load_rooms(force: bool = False) -> list[Room]:
    global _rooms_at, _rooms
    now = time.monotonic()
    with _lock:
        if _rooms and not force and now - _rooms_at < _ROOMS_TTL:
            return list(_rooms)
        cached = _read_rooms_file()
        if cached and not force and _rooms_file_fresh():
            _rooms = cached
            _rooms_at = now
            return list(cached)
    payload = _http_json(SYNC_URL, timeout=12.0)
    rooms = _rooms_from_sync(payload) if isinstance(payload, dict) else []
    with _lock:
        if rooms:
            _rooms = rooms
            _rooms_at = time.monotonic()
            _write_rooms_file(rooms)
            return list(rooms)
        if cached:
            _rooms = cached
            _rooms_at = time.monotonic()
            return list(cached)
        return list(_rooms)


def _rooms_from_sync(payload: dict[str, Any]) -> list[Room]:
    state = payload.get("state") or payload
    cards = state.get("cards") if isinstance(state, dict) else None
    if not isinstance(cards, list):
        return []
    out: list[Room] = []
    for card in cards:
        if not isinstance(card, dict) or card.get("status") != "published":
            continue
        title = str(_field(card, "title") or "").strip()
        if not title or _norm(title).startswith("парковка"):
            continue
        addr = str(_field(card, "addressCoordinates") or _field(card, "address") or "")
        addr = re.split(r"\s*·\s*", addr)[0].strip()
        guests_raw = _field(card, "guests")
        guests: int | None
        try:
            guests = int(guests_raw) if guests_raw not in (None, "") else None
        except (TypeError, ValueError):
            guests = None
        if guests is not None and guests < 1:
            guests = None
        out.append(
            Room(
                room_id=str(card.get("travellineRoomTypeId") or ""),
                title=title,
                address=addr,
                guests=guests,
            )
        )
    return [r for r in out if r.room_id]


def _field(card: dict[str, Any], key: str) -> Any:
    blob = (card.get("fields") or {}).get(key) or {}
    if not isinstance(blob, dict):
        return blob
    local = blob.get("local")
    if local not in (None, ""):
        return local
    return blob.get("travelline")


def _read_rooms_file() -> list[Room]:
    try:
        raw = json.loads(ROOMS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = raw.get("rooms") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out: list[Room] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        guests = it.get("guests")
        try:
            guests_i = int(guests) if guests not in (None, "") else None
        except (TypeError, ValueError):
            guests_i = None
        out.append(
            Room(
                room_id=str(it["id"]),
                title=str(it.get("title") or ""),
                address=str(it.get("address") or ""),
                guests=guests_i,
            )
        )
    return out


def _write_rooms_file(rooms: list[Room]) -> None:
    try:
        ROOMS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "rooms": [
                {
                    "id": r.room_id,
                    "title": r.title,
                    "address": r.address,
                    "guests": r.guests,
                }
                for r in rooms
            ],
        }
        ROOMS_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.warning("travelline room cache write failed")


def search_stays(arrival: date, departure: date, adults: int) -> list[Stay] | None:
    """None — календарь не ответил. Пустой список — на даты никто не свободен."""
    adults = max(1, min(int(adults or 1), 8))
    if _hook is not None:
        try:
            return _hook(arrival, departure, adults)
        except Exception:
            logger.exception("travelline hook failed")
            return None
    key = (arrival.isoformat(), departure.isoformat(), adults)
    now = time.monotonic()
    with _lock:
        hit = _search_cache.get(key)
        if hit and now - hit[0] < _SEARCH_TTL:
            return list(hit[1])
    body = json.dumps(
        {
            "propertyIds": [PROPERTY_ID],
            "arrivalDate": arrival.isoformat(),
            "departureDate": departure.isoformat(),
            "adults": adults,
            "childAges": [],
        }
    ).encode()
    payload = _http_json(SEARCH_URL, body, timeout=18.0, retries=2)
    if not isinstance(payload, dict) or "roomStays" not in payload:
        return None
    rooms = {r.room_id: r for r in _load_rooms()}
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    names = {
        str(rt.get("id")): str(rt.get("name") or "")
        for rt in (content.get("roomTypes") or [])
        if isinstance(rt, dict)
    }
    nights = max(1, (departure - arrival).days)
    out: list[Stay] = []
    seen: set[str] = set()
    for stay in payload.get("roomStays") or []:
        if not isinstance(stay, dict):
            continue
        rt = stay.get("roomType") if isinstance(stay.get("roomType"), dict) else {}
        rid = str(rt.get("id") or "")
        if not rid or rid in seen:
            continue
        avail = stay.get("availability")
        try:
            avail_n = int(avail) if avail is not None else 1
        except (TypeError, ValueError):
            avail_n = 1
        if avail_n <= 0:
            continue
        room = rooms.get(rid)
        raw_name = names.get(rid) or (room.title if room else "")
        title = room.title if room and room.title else _title_key(raw_name) or raw_name
        title = display_title(title)
        total = stay.get("total") if isinstance(stay.get("total"), dict) else {}
        price_total = _pos_int(total.get("priceBeforeTax") or total.get("price"))
        daily = stay.get("dailyRates") if isinstance(stay.get("dailyRates"), list) else []
        night_prices: list[int] = []
        for day in daily:
            if not isinstance(day, dict):
                continue
            one = _pos_int(day.get("priceBeforeTax") or day.get("price"))
            if one:
                night_prices.append(one)
        if night_prices and len(set(night_prices)) == 1 and (
            not price_total or night_prices[0] * nights == price_total
        ):
            night_price = night_prices[0]
        elif price_total and nights and price_total % nights == 0 and not night_prices:
            night_price = price_total // nights
        else:
            night_price = None
        guests = room.guests if room else None
        if guests is not None and guests < adults:
            continue
        seen.add(rid)
        out.append(
            Stay(
                room_id=rid,
                title=title,
                address=room.address if room else "",
                guests=guests,
                available=avail_n,
                price_night=night_price,
                price_total=price_total,
                night_prices=tuple(night_prices),
                raw_name=raw_name,
            )
        )
    with _lock:
        _search_cache[key] = (now, out)
    return out


def _pos_int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _money(stay: Stay, nights: int) -> str:
    """Ночь и итог только если они сходятся. Иначе итог и вилка по ночам."""
    prices = [p for p in (stay.night_prices or ()) if p]
    if not prices and stay.price_night:
        prices = [stay.price_night]
    if stay.price_total and nights > 1:
        span = f"{stay.price_total} ₽ за {nights} {_nights_word(nights)}"
        if prices and min(prices) == max(prices) and prices[0] * nights == stay.price_total:
            return f"{prices[0]} ₽/ночь, {span}"
        if len(prices) > 1 and min(prices) != max(prices):
            return f"{min(prices)}–{max(prices)} ₽/ночь, {span}"
        return span
    if prices:
        return f"{prices[0]} ₽/ночь"
    if stay.price_total:
        return f"{stay.price_total} ₽ за период"
    return ""


def describe_availability(
    arrival: date,
    departure: date,
    stays: list[Stay],
    place: str = "",
    *,
    limit: int | None = None,
    next_step: bool = True,
) -> str:
    return describe_availability_offer(arrival, departure, stays, place, limit=limit, next_step=next_step)[0]


def describe_availability_offer(
    arrival: date,
    departure: date,
    stays: list[Stay],
    place: str = "",
    *,
    limit: int | None = None,
    next_step: bool = True,
) -> tuple[str, list[str]]:
    """Текст для гостя + названия предложенных квартир (по ним гость выбирает номером или словом)."""
    when = span_label(arrival, departure)
    nights = max(1, (departure - arrival).days)
    place_s = " ".join((place or "").split())
    picked = [s for s in stays if matches_place(s, place_s)] if place_s else list(stays)
    picked.sort(key=lambda s: (s.price_total or s.price_night or 10**9, s.title))
    if place_s and not picked:
        return f"По «{place_s}» на {when} в календаре свободных квартир нет.", []
    if not picked:
        return f"На {when} в календаре свободных квартир нет.", []
    show_money = _prices_on()
    if place_s and len(picked) == 1 and _street(place_s) is None and _title_key(picked[0].title) in _norm(place_s):
        stay = picked[0]
        money = _guest_money(stay, nights, detail=True) if show_money else ""
        tail = f", {money}." if money else "."
        nxt = " Передать менеджеру на бронь?" if next_step else ""
        from bot.apartments_map import link_for

        link = link_for(stay.title)
        if link:
            tail += f"\nФото и описание: {link}\n"
            nxt = nxt.lstrip()
        return f"«{stay.title}» на {when} по календарю свободна{tail}{nxt}", [stay.title]
    # по району — все свободные; без района — по limit (если задан)
    if place_s or limit is None:
        shown = list(picked)
        rest = 0
    else:
        shown = picked[:limit]
        rest = len(picked) - limit
    names = [s.title for s in shown]
    more = (
        f" {'Свободна' if rest % 10 == 1 and rest % 100 != 11 else 'Свободны'} ещё {rest} {_flats_word(rest)}, "
        "напишите «ещё», покажу."
        if rest > 0 else ""
    )
    if place_s:
        # «Прокшино, 20–24 декабря: …» — без «По «Прокшино»» и без «Какая ближе?» при одном варианте (скрин 66)
        head = f"{place_s[:1].upper() + place_s[1:]}, {when}"
        from bot.apartments_map import link_for

        from bot.apartments_map import pets_note

        if len(shown) == 1:
            stay = shown[0]
            money = _guest_money(stay, nights) if show_money else ""
            pet = pets_note(stay.title)
            line = (
                f"{head}: по календарю свободна «{stay.title}»"
                + (f" {pet}" if pet else "")
                + (f", {money}" if money else "")
                + "."
            )
            link = link_for(stay.title)
            if link:
                line += f"\nФото и описание: {link}\n"
            if next_step:
                line += (" " if not link else "") + "Передать менеджеру на бронь? Могу показать варианты и в других районах."
            return line, names
        rows = []
        for i, stay in enumerate(shown, 1):
            money = _guest_money(stay, nights) if show_money else ""
            pet = pets_note(stay.title)
            link = link_for(stay.title)
            rows.append(
                f"{i}) «{stay.title}»"
                + (f" {pet}" if pet else "")
                + (f", {money}" if money else "")
                + (f"\n{link}" if link else "")
            )
        tail = "\n\nКакая нравится? Напишите номер или название, передам менеджеру." if next_step else ""
        return f"{head}, по календарю свободны:\n\n" + "\n".join(rows) + (f"\n\n{more.strip()}" if more else "") + tail, names
    from bot.apartments_map import link_for, pets_note

    # без района — тоже карточки со ссылками, не простыня через «;»
    rows = []
    any_link = False
    for i, stay in enumerate(shown, 1):
        money = _guest_money(stay, nights) if show_money else ""
        pet = pets_note(stay.title)
        link = link_for(stay.title)
        row = (
            f"{i}) «{stay.title}»"
            + (f" {pet}" if pet else "")
            + (f", {money}" if money else "")
        )
        if link:
            row += f"\n{link}"
            any_link = True
        rows.append(row)
    tail = ""
    if more:
        tail += f"\n\n{more.strip()}"
    if not any_link:
        import os

        site = (os.getenv("SITE_URL") or "https://home24.msk.ru/").strip()
        tail += f"\n\nПосмотреть квартиры: {site}"
    if next_step:
        tail += (
            "\n\nКакой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье? "
            "Выберу из свободных."
        )
    return (
        f"На {when} по календарю свободны:\n\n" + "\n".join(rows) + tail
    ).rstrip(), names


def _prices_on() -> bool:
    """Цены из календаря. По скрипту цену называет менеджер — выключить: TRAVELLINE_PRICES=0."""
    import os

    return (os.getenv("TRAVELLINE_PRICES") or "1").strip().lower() not in ("0", "false", "no", "off")


def _rub(n: int) -> str:
    # неразрывный пробел в тысячах: Telegram не превращает «2976–3500» в ссылку-номер
    return f"{int(n):,}".replace(",", "\u00a0") + "\u00a0₽"


def _guest_money(stay: Stay, nights: int = 1, *, detail: bool = False) -> str:
    """«13 671 ₽ за 3 ночи» / «от 3 200 ₽ за ночь» — без вилок «4371–4750», их Telegram делает ссылкой."""
    prices = [p for p in (stay.night_prices or ()) if p] or ([stay.price_night] if stay.price_night else [])
    if stay.price_total and nights > 1:
        total = f"{_rub(stay.price_total)} за {nights} {_nights_word(nights)}"
        if detail and prices and len(set(prices)) == 1 and prices[0] * nights == stay.price_total:
            return f"{_rub(prices[0])} за ночь, {total}"
        return total
    if prices:
        return f"{_rub(prices[0])} за ночь" if len(set(prices)) == 1 else f"от {_rub(min(prices))} за ночь"
    if stay.price_total:
        return f"{_rub(stay.price_total)} за период"
    return ""


def _flats_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "квартира"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "квартиры"
    return "квартир"


def hint_place(text: str, stays: list[Stay]) -> str:
    """Если гость назвал квартиру или кусок адреса — не показывать чужие."""
    raw = _norm(text)
    if not raw:
        return ""
    for stay in stays:
        key = _title_key(stay.title)
        if len(key) >= 4 and re.search(rf"(?<![а-яa-z]){re.escape(key)}(?![а-яa-z])", raw):
            return stay.title
    for token in re.findall(r"[а-яa-z]{5,}", raw):
        if _is_zone(token):
            continue
        stem = re.sub(r"(ский|ская|ское|о|а|е)$", "", token)
        if len(stem) < 5:
            continue
        if any(stem in _norm(stay.address) for stay in stays):
            return token
    return ""


def availability_reply(
    dates_phrase: str,
    adults: int,
    place: str = "",
    today: date | None = None,
    text: str = "",
    next_step: bool = True,
) -> str | None:
    span = stay_span(dates_phrase, today)
    if not span:
        return None
    stays = search_stays(span[0], span[1], adults)
    if stays is None:
        return None
    if not _norm(place):
        place = hint_place(text or dates_phrase, stays)
    return describe_availability(span[0], span[1], stays, place, next_step=next_step)


def availability_offer(
    dates_phrase: str,
    adults: int,
    place: str = "",
    today: date | None = None,
    text: str = "",
    next_step: bool = True,
) -> tuple[str | None, list[str]]:
    """Как availability_reply, но ещё и названия предложенных квартир."""
    span = stay_span(dates_phrase, today)
    if not span:
        return None, []
    stays = search_stays(span[0], span[1], adults)
    if stays is None:
        return None, []
    if not _norm(place):
        place = hint_place(text or dates_phrase, stays)
    return describe_availability_offer(span[0], span[1], stays, place, next_step=next_step)


def same_title(catalog_name: str, stay: Stay) -> bool:
    a = _title_key(catalog_name)
    b = _title_key(stay.title)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def free_offer_cards(
    dates_phrase: str,
    adults: int,
    *,
    limit: int | None = None,
    today: date | None = None,
    exclude: list[str] | None = None,
    lead: str = "",
    district: str = "",
    only_area: bool = False,
) -> tuple[str, list[str]]:
    """Карточки из календаря: все свободные по району (или все свободные, если район не задан).

    district: «центр» — квартиры ближе к центру по карте из script.md; район — квартиры этого района.
    limit: None — без обрезки (по умолчанию); число — максимум карточек.
    ('', []) — нет дат, нет связи с TravelLine или свободных нет.
    """
    from bot.apartments_map import CENTER_NAMES, link_for, place_short

    span = stay_span(dates_phrase, today)
    if not span:
        return "", []
    try:
        stays = search_stays(span[0], span[1], adults)
    except Exception:
        return "", []
    if not stays:
        return "", []
    nights = max(1, (span[1] - span[0]).days)
    skip = {(x or "").strip().lower() for x in (exclude or [])}
    stays = [s for s in stays if s.title.strip().lower() not in skip]
    if not stays:
        return "", []
    when = span_label(span[0], span[1])
    want = (district or "").strip()
    want_l = want.lower()
    note = ""
    show_where = True
    try:
        from bot.reply_guard import is_open_district

        open_pref = (not want) or is_open_district(want)
    except Exception:
        open_pref = want_l in ("", "не принципиально", "любой", "любая", "любой район", "без разницы", "на ваш выбор")
    if want_l == "центр":
        central = [
            s
            for s in stays
            if s.title.strip().lower() in CENTER_NAMES or matches_place(s, "Центр")
        ]
        if central:
            stays = central
            # у центра оставляем короткий район в карточке (Басманный / …)
        elif only_area:
            return "", []
        else:
            # скрин 24, 11.11: на «Центр» пришли Одинцово и Котельники — теперь честно
            note = "В центре на эти даты по календарю свободных нет. Вот что свободно в других районах:"
    elif not open_pref:
        local = [
            s
            for s in stays
            if matches_place(s, want) or want_l in place_short(s.title).lower()
        ]
        if local:
            stays = local
            show_where = False  # район гость уже назвал — «Коммунарка, м. Коммунарка» у Прокшино только путает
        else:
            # чужие районы не подмешиваем (only_area или любой именованный район)
            return "", []
    # open_pref / пустой district → все свободные на даты из календаря
    picked = sorted(stays, key=lambda s: (s.price_total or s.price_night or 10**9, s.title))
    if limit is not None:
        picked = picked[: max(0, int(limit))]
    show_money = _prices_on()
    lines = []
    any_link = False
    from bot.apartments_map import pets_note

    for i, stay in enumerate(picked, 1):
        money = _guest_money(stay, nights) if show_money else ""
        where = place_short(stay.title) if show_where else ""
        pet = pets_note(stay.title)
        row = (
            f"{i}) «{stay.title}»"
            + (f" {pet}" if pet else "")
            + (f", {where}" if where else "")
            + (f", {money}" if money else "")
        )
        link = link_for(stay.title)
        if link:
            row += f"\n{link}"
            any_link = True
        lines.append(row)
    head = lead or note or f"Свободны по календарю на {when}:"
    tail = (
        f"Если подходит, напишите номер (1–{len(picked)}) или название."
        if len(picked) > 1
        else "Если подходит, напишите, передам менеджеру на бронь."
    )
    if not any_link:
        import os

        site = (os.getenv("SITE_URL") or "https://home24.msk.ru/").strip()
        tail = f"Посмотреть квартиры: {site}\n\n{tail}"
    text = head + "\n\n" + "\n".join(lines) + "\n\n" + tail
    return text, [s.title for s in picked]
