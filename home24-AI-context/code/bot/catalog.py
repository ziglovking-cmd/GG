"""Каталог квартир из data/mailing.sqlite (без Wifi/секретов гостю).

Цены и вместимость — только из реальных полей БД (price_night / capacity)
или явных упоминаний в how. Если цены нет — не выдумываем.
"""

from __future__ import annotations

import logging
import random
import re
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("home24.catalog")

DEFAULT_PATH = Path("data/mailing.sqlite")

PRICE_UNKNOWN = "Цену по датам уточнит менеджер."

# Зоны: центр ≈ Садовое/ТТК + ближайшие центральные станции; спокойнее = окраины/область.
# Важно: «Москва» в area НЕ значит центр (Прокшино/Коммунарка тоже area=Москва).
CENTRAL_METRO_STEMS = (
    "бауман",
    "ленинск",
    "гагарин",
    "бутырск",
    "нижегород",
    "красноказармен",
    "балакирев",
)
OUTER_METRO_STEMS = (
    "прокшин",
    "коммунарк",
    "новомосковск",
    "бунинск",
    "саларьев",
    "румянцев",
    "одинцов",
    "котельник",
    "заречье",
    "мосрентген",
    "царицын",
    "нагатин",
    "лефортов",
    "хорошёв",
    "хорошев",
    "рокоссовск",
    "аминьев",
    "фитарев",
    "южнобутов",
    "мещерск",
    "лобановск",
)
CENTRAL_AREA_NAMES = frozenset({"бауманская", "гагаринский"})
CALM_AREA_NAMES = frozenset(
    {"коммунарка", "саларьево", "одинцово", "котельники", "заречье"}
)
CENTER_HINTS = CENTRAL_METRO_STEMS
CALM_AREAS = tuple(CALM_AREA_NAMES) + (
    "мосрентген",
    "бутов",
    "прокшин",
    "новомосковск",
)

_OPTIONAL_COLS = (
    ("price_night", "INTEGER"),
    ("capacity", "INTEGER"),
    ("photo_url", "TEXT"),
    ("price_source", "TEXT"),
    ("price_updated_at", "TEXT"),
)


def _connect(path: Path | str = DEFAULT_PATH) -> sqlite3.Connection | None:
    p = Path(path)
    if not p.exists():
        logger.warning("catalog missing: %s", p)
        return None
    con = sqlite3.connect(str(p), check_same_thread=False)
    con.row_factory = sqlite3.Row
    _ensure_optional_columns(con)
    return con


def _ensure_optional_columns(con: sqlite3.Connection) -> None:
    """Добавляет price_night / capacity / photo_url, если их ещё нет (NULL)."""
    existing = {r[1] for r in con.execute("PRAGMA table_info(objects)")}
    for name, typ in _OPTIONAL_COLS:
        if name not in existing:
            try:
                con.execute(f"ALTER TABLE objects ADD COLUMN {name} {typ}")
                con.commit()
                logger.info("catalog: added column objects.%s", name)
            except sqlite3.Error:
                logger.exception("catalog: failed to add column %s", name)


def _table_cols(con: sqlite3.Connection) -> set[str]:
    return {r[1] for r in con.execute("PRAGMA table_info(objects)")}


def _parse_price_from_text(blob: str) -> int | None:
    """Достаёт цену только из явных маркеров в тексте объекта (не из скрипта)."""
    if not blob:
        return None
    patterns = (
        r"(?:цена|стоимость|price(?:_night)?)\s*[:\-]?\s*(\d{3,6})\s*(?:₽|руб|/сут|/ночь)?",
        r"(\d{3,6})\s*(?:₽|руб\.?)\s*(?:/?\s*сут|/?\s*ночь|за\s*ночь)",
        r"от\s+(\d{3,6})\s*(?:₽|руб)",
    )
    for pat in patterns:
        m = re.search(pat, blob, re.I)
        if m:
            n = int(m.group(1))
            if 1500 <= n <= 100000:
                return n
    return None


def _parse_capacity_from_text(how: str) -> int | None:
    m = re.search(r"до\s+(\d+)\s+гост", how or "", re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*гост", how or "", re.I)
    if m:
        return int(m.group(1))
    return None


def _row_get(r: sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        return r[key]
    except (IndexError, KeyError):
        return default


def classify_zone(obj: dict[str, Any]) -> dict[str, Any]:
    """Пометить квартиру: is_central / is_calm / zone (center|calm|other)."""
    area = str(obj.get("area") or "")
    metro = str(obj.get("metro") or "")
    address = str(obj.get("address") or "")
    blob = f"{area} {metro} {address}".lower()
    area_l = area.lower().strip()

    outer = any(s in blob for s in OUTER_METRO_STEMS) or area_l in CALM_AREA_NAMES
    central = (not outer) and (
        area_l in CENTRAL_AREA_NAMES or any(s in blob for s in CENTRAL_METRO_STEMS)
    )
    calm = outer or area_l in CALM_AREA_NAMES
    if central:
        zone = "center"
    elif calm:
        zone = "calm"
    else:
        zone = "other"
    return {
        "is_central": bool(central),
        "is_calm": bool(calm),
        "zone": zone,
    }


def _row_public(r: sqlite3.Row) -> dict[str, Any]:
    """Публичная карточка — без wifi/паролей. Цена только из БД/how."""
    how = r["how"] or ""
    raw_price = _row_get(r, "price_night")
    price: int | None = None
    if raw_price is not None and str(raw_price).strip() != "":
        try:
            price = int(raw_price)
        except (TypeError, ValueError):
            price = None
    if price is None:
        price = _parse_price_from_text(how)

    raw_cap = _row_get(r, "capacity")
    capacity: int | None = None
    if raw_cap is not None and str(raw_cap).strip() != "":
        try:
            capacity = int(raw_cap)
        except (TypeError, ValueError):
            capacity = None
    if capacity is None:
        capacity = _parse_capacity_from_text(how)

    photo = (_row_get(r, "photo_url") or "") or ""
    base = {
        "id": r["id"],
        "slug": r["slug"],
        "name": r["name"],
        "area": r["area"] or "",
        "address": r["address"] or "",
        "metro": r["metro"] or "",
        "maps_url": r["maps_url"] or "",
        "guide_url": r["guide_url"] or "",
        "photo_url": photo,
        "how": how[:400],
        "checkin": r["checkin"] or "",
        "checkout": r["checkout"] or "",
        "price_night": price,  # int | None — None = неизвестно
        "capacity": capacity,  # int | None
    }
    base.update(classify_zone(base))
    base["area_label"] = area_label(base)
    return base


def area_label(obj: dict[str, Any]) -> str:
    """Подпись района для карточки: не голое «Москва», а метро/локация."""
    area = str(obj.get("area") or "").strip()
    metro = str(obj.get("metro") or "").strip()
    address = str(obj.get("address") or "").strip()
    if area and area.lower() not in ("москва", "moscow", "—", "-"):
        return area
    # из метро: «Хорошёво · 10 минут» / «м. Ленинский проспект» / «5 минут от м. …»
    if metro:
        m = re.search(r"(?i)м\.\s*([^·,\n]+)", metro)
        if m:
            return m.group(1).strip()[:48]
        # первая часть до ·
        head = metro.split("·")[0].strip()
        head = re.sub(
            r"(?i)^\d+\s*минут\w*\s*(?:пешком\s*)?(?:от\s*)?",
            "",
            head,
        ).strip(" .,—")
        head = re.sub(r"(?i)^от\s+", "", head).strip()
        if head and head.lower() not in ("москва",):
            return head[:48]
    # из адреса — районный ориентир после «Москва,»
    if address:
        m = re.search(r"(?i)москва,?\s*(.+)", address)
        chunk = (m.group(1) if m else address).strip()
        # ул./проспект — коротко
        m2 = re.search(
            r"(?i)((?:ул\.|улица|пр\.|проспект|пер\.|переулок|шоссе)[^,]+)",
            chunk,
        )
        if m2:
            return m2.group(1).strip()[:48]
        return chunk.split(",")[0].strip()[:48]
    return area or "Москва"


def district_preference(district: str | None) -> str:
    """center | near | sleep | green | suburb | calm | any."""
    d = (district or "").lower().replace("ё", "е")
    if re.search(r"подмосков|за\s*мкад|в\s*област|\bsuburb\b", d):
        return "suburb"
    if re.search(r"близко\s*к\s*цен|ближе\s*к\s*цен|недалеко\s*от\s*цен|деловой|\bnear\b", d):
        return "near"
    if re.search(r"зелен|лесопарк|новая\s*москва|\bgreen\b", d):
        return "green"
    if re.search(r"спальн|окраин|\bsleep\b", d):
        return "sleep"
    if re.search(r"(?<!близко к )(?<!ближе к )(?<!недалеко от )центр|центральн|в центре|\bcenter\b|\bcentral\b|\bcentre\b", d):
        return "center"
    if re.search(r"спокой|тихий|тих\w*\s*район|подальше|\bcalm\b|\bquiet\b", d):
        return "calm"
    return "any"


_GENERIC_PLACE = re.compile(
    r"не\s*принцип|без\s*разницы|любо[йя]|не\s*важно|любой\s*район|^москва$"
)


def named_place_stem(district: str | None) -> str:
    """Конкретное место из каталога (Прокшино), не зона «центр/спокойный»."""
    raw = (district or "").strip().lower()
    if not raw or district_preference(raw) != "any":
        return ""
    if _GENERIC_PLACE.search(raw):
        return ""
    compact = re.sub(r"[^a-zа-яё0-9]+", "", raw)
    if len(compact) < 4:
        return ""
    stem = re.sub(r"(ский|ская|ское|ого|ино|но)$", "", compact)
    if len(stem) < 4:
        stem = compact[:6]
    return stem[:10]


def _place_blob(obj: dict[str, Any]) -> str:
    return " ".join(
        str(obj.get(k) or "")
        for k in ("area", "metro", "address", "area_label", "name")
    ).lower()


def matches_named_place(obj: dict[str, Any], district: str | None) -> bool:
    stem = named_place_stem(district)
    if not stem:
        return True
    blob = _place_blob(obj)
    compact = re.sub(r"[^a-zа-яё0-9]+", "", blob)
    return stem in compact or stem in blob


def catalog_place_names(path: Path | str = DEFAULT_PATH) -> list[str]:
    """Уникальные районы и станции из каталога, длинные первыми."""
    con = _connect(path)
    if not con:
        return []
    try:
        names: set[str] = set()
        for area, metro in con.execute(
            "SELECT area, metro FROM objects"
        ):
            for raw in (area, (metro or "").split("·")[0]):
                name = (raw or "").strip()
                low = name.lower()
                if len(name) < 4 or low in ("москва", "центр"):
                    continue
                names.add(name)
        return sorted(names, key=len, reverse=True)
    finally:
        con.close()


def match_catalog_place(text: str | None, path: Path | str = DEFAULT_PATH) -> str | None:
    """Если гость назвал станцию/район из каталога — вернуть это имя."""
    low = (text or "").lower()
    if not low:
        return None
    for name in catalog_place_names(path):
        nlow = name.lower()
        stem = named_place_stem(nlow) or nlow[:5]
        if nlow in low or (len(stem) >= 4 and stem in low):
            return name
    return None


def fits_district(obj: dict[str, Any], district: str | None) -> bool:
    # Зоны и локации из script.md «Районы» (таблица квартир по районам) — главный фильтр
    try:
        from bot.apartments_map import areas_for_place, in_area

        if district and areas_for_place(str(district)):
            return in_area(str(obj.get("name") or ""), str(district))
    except Exception:
        pass
    pref = district_preference(district)
    if pref == "any":
        return matches_named_place(obj, district)
    z = obj.get("zone") or classify_zone(obj)["zone"]
    if pref == "center" and z != "center":
        return False
    if pref in ("calm", "sleep", "green", "suburb") and not (z == "calm" or obj.get("is_calm")):
        return False
    if pref == "near" and z == "calm":
        return False
    return matches_named_place(obj, district)


def reason_for_offer(
    obj: dict[str, Any],
    *,
    district: str | None = None,
    guests: str | None = None,
) -> str:
    """Короткая честная причина — без ложного «центр» для окраин."""
    bits: list[str] = []
    pref = district_preference(district)
    z = obj.get("zone") or classify_zone(obj)["zone"]
    metro = (obj.get("metro") or "").strip()
    label = (obj.get("area_label") or area_label(obj) or "").strip()
    # метро уже есть отдельной строкой карточки — в причине его не повторяем
    place = ""
    if label and label.lower() != metro.lower() and label.lower() not in metro.lower():
        place = label[:48]
    if pref == "center" and z == "center":
        bits.append("в центре" + (f", {place}" if place else ""))
    elif pref == "center" and z != "center":
        bits.append("ближе к центру из доступных" + (f" ({place})" if place else ""))
    elif pref == "near":
        bits.append("близко к центру" + (f", {place}" if place else ""))
    elif pref == "sleep":
        bits.append("спальный район" + (f", {place}" if place else ""))
    elif pref == "green":
        bits.append("тихий зелёный район" + (f", {place}" if place else ""))
    elif pref == "suburb":
        bits.append("Подмосковье" + (f", {place}" if place else ""))
    elif pref == "calm" and (z == "calm" or obj.get("is_calm")):
        bits.append("спокойный район" + (f", {place}" if place else ""))
    else:
        if place:
            bits.append(place)
    need = _parse_guests(guests)
    cap = obj.get("capacity")
    if isinstance(cap, int) and cap > 0 and need:
        if cap >= need:
            bits.append(f"вместит {need}")
        else:
            bits.append(f"до {cap} гостей")
    # не оставлять пустое / «Москва, до N»
    out = ", ".join(b for b in bits if b and b.lower() != "москва")
    return out or (place or "из каталога")


def format_price_line(obj: dict[str, Any]) -> str:
    price = obj.get("price_night")
    if isinstance(price, int) and price > 0:
        return f"{price} ₽/сутки"
    return PRICE_UNKNOWN


_APT_NUM_RE = re.compile(
    r"(?i)(?:^|[,;]\s*|\s+)(?:кв\.?|квартира)\s*№?\s*\d+\w*"
)
_INTERNAL_CARD_RE = re.compile(
    r"(?i)инструкц|кнопк\w*\s*[«\"]?\s*маршрут|в этой инструкции"
)


def client_address(address: str) -> str:
    """Гостю не показываем номер квартиры."""
    text = _APT_NUM_RE.sub("", address or "")
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;")
    return text


def client_blurb(line: str) -> str:
    """Внутренние фразы инструкции на карточку не попадают."""
    text = (line or "").strip()
    if not text or _INTERNAL_CARD_RE.search(text):
        return ""
    return text


def format_card(obj: dict[str, Any]) -> str:
    label = obj.get("area_label") or area_label(obj) or obj.get("area") or ""
    title = str(obj.get("name") or "")
    pet = ""
    try:
        from bot.apartments_map import pets_note

        pet = pets_note(title)
    except Exception:
        pet = ""
    head = f"«{title}»" + (f" {pet}" if pet else "") + (f" · {label}" if label else "")
    lines = [head.strip(" ·")]
    if obj.get("metro"):
        lines.append(obj["metro"])
    address = client_address(str(obj.get("address") or ""))
    if address:
        lines.append(address)
    cap = obj.get("capacity")
    if isinstance(cap, int) and cap > 0:
        lines.append(f"До {cap} гостей")
    lines.append(format_price_line(obj))
    # коротко из how — первая содержательная строка после адреса
    how = obj.get("how") or ""
    for part in how.split("\n"):
        p = part.strip()
        if len(p) > 40 and not p.lower().startswith("адрес"):
            # не дублировать цену/вместимость из how в описание
            if re.search(r"(?i)цена|₽|руб|/сут|до\s+\d+\s+гост", p):
                continue
            blurb = client_blurb(p)
            if not blurb:
                continue
            lines.append(blurb[:160].rstrip(".") + ".")
            break
    try:
        from bot.apartments_map import link_for

        site_link = link_for(str(obj.get("name") or ""))
    except Exception:
        site_link = ""
    if site_link:
        lines.append(f"Фото и описание: {site_link}")  # страница квартиры на нашем сайте
    link = obj.get("photo_url") or obj.get("maps_url") or obj.get("guide_url")
    if link and link != site_link:
        lines.append(f"Карта/фото: {link}")
    return "\n".join(lines)


def list_areas(path: Path | str = DEFAULT_PATH) -> list[str]:
    con = _connect(path)
    if not con:
        return []
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT area FROM objects WHERE area IS NOT NULL AND area!='' ORDER BY area"
        )]
    finally:
        con.close()


def find_by_name(query: str, path: Path | str = DEFAULT_PATH) -> dict[str, Any] | None:
    """Строгий поиск: «Да» не должно находить «Идальго»."""
    con = _connect(path)
    if not con:
        return None
    raw = (query or "").strip()
    # убрать кавычки «» ""
    q = re.sub(r"^[«»\"'\s]+|[«»\"'\s]+$", "", raw).lower()
    q = re.sub(r"^(квартира|вариант|студия)\s+", "", q).strip()
    # слишком короткое / служебные слова — не имя квартиры
    if len(q) < 4 or q in {
        "да",
        "нет",
        "ок",
        "ага",
        "угу",
        "привет",
        "здравствуйте",
        "другие",
        "вариант",
        "варианты",
        "ещё",
        "еще",
        "можно",
        "надо",
        "хочу",
        "бронь",
    }:
        return None
    try:
        rows = con.execute("SELECT * FROM objects").fetchall()
        # 1) точное имя / slug
        for r in rows:
            name = (r["name"] or "").lower().strip()
            slug = (r["slug"] or "").lower().strip()
            if q == name or q == slug:
                return _row_public(r)
        # 2) имя целиком как слово в фразе гостя («хочу Феррари на выходные»)
        for r in rows:
            name = (r["name"] or "").lower().strip()
            slug = (r["slug"] or "").lower().strip()
            if len(name) >= 4 and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", q):
                return _row_public(r)
            if len(slug) >= 4 and re.search(rf"(?<!\w){re.escape(slug)}(?!\w)", q):
                return _row_public(r)
        # 3) гость написал префикс имени ≥4 символов (ферра → феррари), не наоборот
        for r in rows:
            name = (r["name"] or "").lower().strip()
            slug = (r["slug"] or "").lower().strip()
            if len(q) >= 4 and (name.startswith(q) or slug.startswith(q)):
                return _row_public(r)
        return None
    finally:
        con.close()


def wants_variants(text: str) -> bool:
    """Просьба «покажи варианты», но НЕ выбор «3 вариант / этот подходит»."""
    t = (text or "").lower().strip()
    # выбор конкретного варианта — не каталог заново
    if re.search(
        r"(?i)(\b[1-3]\s*вариант|вариант\s*[1-3]|беру\s*[1-3]|мне\s*[1-3]|"
        r"подходит|устраивает|этот|эту|перв(ый|ая|ое)|втор(ой|ая)|трет(ий|ья))",
        t,
    ):
        return False
    if re.search(r"(?i)не\s*(пойд|нрав|подход|то\b)", t):
        return True  # другие варианты
    if re.search(
        r"(?i)("
        r"сначала\s*посмотр|посмотрим\s*квартир|просто\s*посмотр|"
        r"можно\s*сначала|давайте\s*сначала|"
        r"покаж(и|ите)\s*(вариант|квартир)|"
        r"скин(ь|ьте)\s*(вариант|квартир)|"
        r"пришл(и|ите)\s*(вариант|квартир)|"
        r"предлож(и|ите)\s*(вариант|квартир)|"
        r"кинь(те)?\s*(вариант|квартир)|"
        r"какие\s*(у\s*вас\s*)?(есть|квартир)|"
        r"что\s*есть|другие\s*(вариант|квартир)|"
        r"ещё\s*(вариант|квартир)|еще\s*(вариант|квартир)|"
        r"подбер(и|ите)|не\s*прис(лал|лали)|не\s*скин"
        r")",
        t,
    ):
        return True
    keys = (
        "другие вариант",
        "ещё вариант",
        "еще вариант",
        "ещё квартир",
        "еще квартир",
        "покажи вариант",
        "пришли вариант",
        "не прислал",
        "не скинул",
        "что есть",
        "подбери",
        "подберите",
        "какие есть",
        "скинь вариант",
        "другие квартир",
    )
    return any(k in t for k in keys)


def parse_offer_pick(text: str) -> int | None:
    """1|2|3 если гость выбирает вариант из списка."""
    t = (text or "").lower().strip()
    # «3 вариант», «вариант 3», «№2»
    m = re.search(r"вариант\s*[№#]?\s*([1-3])\b", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([1-3])\s*вариант", t)
    if m:
        return int(m.group(1))
    m = re.search(r"[№#]\s*([1-3])\b", t)
    if m:
        return int(m.group(1))
    # «давайте 1», «дайте 2», «беру 3», «номер 1»
    m = re.search(
        r"(?i)(?:давайте|дайте|беру|возьму|номер|выберу|выбираю)\s*[№#]?\s*([1-3])\b",
        t,
    )
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)\b(перв(ый|ая|ое|ую|ого)|втор(ой|ая|ое|ую|ого)|трет(ий|ья|ье|ью|ьего))\b", t)
    if m:
        w = m.group(1)
        if w.startswith("перв"):
            return 1
        if w.startswith("втор"):
            return 2
        return 3
    # «1 меня устраивает», «мне 3», «беру 2», «так хорошо 3»
    if re.search(
        r"(?i)(подходит|устраивает|беру|хочу\s+эт|нравит|пойдёт|пойдет|ок|хорошо|беру\s)",
        t,
    ) or re.search(r"(?i)\bмне\s+[1-3]\b", t):
        m = re.search(r"\b([1-3])\b", t)
        if m:
            return int(m.group(1))
    # «1 впервые» / «2 были» — номер + returning в одной фразе
    if re.search(r"(?i)впервые|не\s*был|были\s*у|постоянн", t):
        m = re.search(r"\b([1-3])\b", t)
        if m:
            return int(m.group(1))
    # голое «1» / «2» / «3» — только если короткое сообщение
    if re.fullmatch(r"\s*[1-3]\s*[.)]?\s*", t):
        return int(re.search(r"[1-3]", t).group(0))
    return None


_COMMON_WORD_RE = re.compile(
    r"(парков|квартир|метро|кухн|вайфа|заезд|заед|выезд|есть|можно|сколь|цен|стоит|район|центр|"
    r"гост|челов|даты|дата|когда|какой|какая|какие|где|нужн|хочу|будет|давай|первый|второй|третий|"
    r"спасиб|здравст|добрый|привет|ночь|ночью|утра|вечер|собак|кошк|питом|ребён|ребен|дет|балл|бонус|"
    r"скидк|оплат|карт|залог|ключ|уборк|завтрак|трансфер|паспорт|документ|подуша|полотен|кофе|"
    r"нравит|вариант|номер|название|были|впервые|раньше|тоже|очень|просто|пока|ещё|еще|"
    r"роман|сюрприз|девушк|праздн|рожден|отмет|юбиле|годовщ|вечер|день|хотим|человек)"
)


def find_by_name_fuzzy(query: str, path: Path | str = DEFAULT_PATH) -> dict[str, Any] | None:
    """Строгий + мягкий поиск (Чехла → Чехов)."""
    hit = find_by_name(query, path)
    if hit:
        return hit
    raw = (query or "").strip()
    q = re.sub(r"^[«»\"'\s]+|[«»\"'\s]+$", "", raw).lower()
    q = re.sub(r"^(квартира|вариант|студия)\s+", "", q).strip()
    if len(q) < 3:
        return None
    con = _connect(path)
    if not con:
        return None
    try:
        import difflib

        rows = con.execute("SELECT * FROM objects").fetchall()
        names = [(r, (r["name"] or "").lower()) for r in rows]
        # «парковка есть?» — не «Парамаунт»: сравниваем отдельные слова, частые слова пропускаем
        tokens = [w for w in re.findall(r"[а-яёa-z]+", q) if len(w) >= 3 and not _COMMON_WORD_RE.match(w)]
        if not tokens:
            return None
        best = None
        best_score = 0.0
        for r, name in names:
            if not name:
                continue
            for tok in tokens:
                if tok == name or (len(tok) >= 4 and (name.startswith(tok) or tok.startswith(name[: max(4, len(tok) - 1)]))):
                    return _row_public(r)
                pref = 0
                for a, b in zip(tok, name):
                    if a != b:
                        break
                    pref += 1
                ratio = difflib.SequenceMatcher(None, tok, name).ratio()
                if (pref >= 4 and ratio >= 0.7) or (
                    pref >= 3
                    and len(tokens) == 1
                    and len(tok) <= 6
                    and difflib.SequenceMatcher(None, tok, name).ratio() >= 0.6  # «пароль» ≠ «Парамаунт»
                ):
                    score = 0.55 + 0.1 * pref  # чехл/чехов, ферра/феррари
                elif len(tok) >= 4 and abs(len(tok) - len(name)) <= 2:
                    score = difflib.SequenceMatcher(None, tok, name).ratio()
                else:
                    score = 0.0
                if score > best_score:
                    best_score = score
                    best = r
        if best is not None and best_score >= 0.65:
            return _row_public(best)
        return None
    finally:
        con.close()


def budget_max_rub(budget: str | None) -> int | None:
    """«до 5000 ₽» / «бюджет 6 тысяч» → 5000."""
    if not budget:
        return None
    t = str(budget).lower()
    m = re.search(r"(\d{3,6})", t)
    if m:
        n = int(m.group(1))
        if 1500 <= n <= 100000:
            return n
    m = re.search(r"(\d)\s*тыс", t)
    if m:
        return int(m.group(1)) * 1000
    return None


def budget_from_sess(sess: dict[str, Any] | None) -> str | None:
    if not sess:
        return None
    b = str((sess.get("context") or {}).get("budget") or "").strip()
    return b or None


def _parse_guests(guests: str | None) -> int:
    if not guests:
        return 2
    m = re.search(r"\d+", str(guests))
    if m:
        return int(m.group(0))
    if "5" in str(guests) or "+" in str(guests):
        return 5
    return 2


def pick_apartments(
    *,
    district: str | None = None,
    guests: str | None = None,
    budget: str | None = None,
    limit: int = 3,
    path: Path | str = DEFAULT_PATH,
    hard_district: bool = True,
) -> list[dict[str, Any]]:
    """Подбор. При hard_district — сначала только зона (центр/спокойный), иначе nearest."""
    objs, _note = pick_apartments_with_note(
        district=district,
        guests=guests,
        budget=budget,
        limit=limit,
        path=path,
        hard_district=hard_district,
    )
    return objs


def pick_apartments_with_note(
    *,
    district: str | None = None,
    guests: str | None = None,
    budget: str | None = None,
    limit: int = 3,
    path: Path | str = DEFAULT_PATH,
    hard_district: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """(карточки, пояснение если зона не нашлась и показали ближайшие)."""
    con = _connect(path)
    if not con:
        return [], ""
    try:
        rows = [_row_public(r) for r in con.execute("SELECT * FROM objects")]
    finally:
        con.close()

    need = _parse_guests(guests)
    max_rub = budget_max_rub(budget)
    pref = district_preference(district)
    script_area = False
    try:
        from bot.apartments_map import areas_for_place, in_area

        if district and areas_for_place(str(district)):
            script_area = True
            rows = [o for o in rows if in_area(str(o.get("name") or ""), str(district))]
            if not rows:
                label = (district or "").strip() or "этом месте"
                return [], f"В {label} сейчас нет квартир под эти условия."
    except Exception:
        script_area = False
    place = named_place_stem(district)
    if place and not script_area:
        rows = [o for o in rows if matches_named_place(o, district)]
        if not rows:
            label = (district or "").strip() or "этом месте"
            return [], f"В {label} сейчас нет квартир под эти условия."

    def score_rows(
        min_cap: int,
        *,
        enforce_budget: bool,
        zone_mode: str,
    ) -> list[tuple[int, dict[str, Any]]]:
        """zone_mode: strict | nearest | any."""
        scored: list[tuple[int, dict[str, Any]]] = []
        for obj in rows:
            score = 0
            z = obj.get("zone") or "other"
            if zone_mode == "strict" and not script_area:
                if pref == "center" and z != "center":
                    continue
                if pref in ("calm", "sleep", "green", "suburb") and not (
                    z == "calm" or obj.get("is_calm")
                ):
                    continue
                if pref == "near" and z == "calm":
                    continue
            elif zone_mode == "nearest" and not script_area:
                # ослабление: центр → other ближе окраин; calm → other ок
                if pref == "center" and z == "calm":
                    score -= 4
                elif pref == "center" and z == "other":
                    score -= 1
                elif pref in ("calm", "sleep", "green", "suburb") and z == "center":
                    score -= 2

            cap = obj.get("capacity")
            if isinstance(cap, int):
                if cap < min_cap:
                    continue
                if cap >= need:
                    score += 2
            else:
                if min_cap > 4:
                    continue
                score += 0

            price = obj.get("price_night")
            if max_rub is not None:
                if isinstance(price, int) and price > 0:
                    if price > max_rub:
                        if enforce_budget:
                            continue
                        score -= 3
                    else:
                        score += 3
                else:
                    score -= 1

            if zone_mode == "strict":
                score += 4
            score += random.randint(0, 1)
            scored.append((score, obj))
        scored.sort(key=lambda x: -x[0])
        return scored

    def take(scored: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
        picked: list[dict[str, Any]] = []
        seen_metro: set[str] = set()
        for _, obj in scored:
            metro_key = (obj.get("metro") or obj.get("area") or obj["name"]).lower()[:40]
            if metro_key in seen_metro and len(picked) < limit:
                continue
            picked.append(obj)
            seen_metro.add(metro_key)
            if len(picked) >= limit:
                break
        if len(picked) < limit:
            for _, obj in scored:
                if obj not in picked:
                    picked.append(obj)
                if len(picked) >= limit:
                    break
        return picked[:limit]

    note = ""
    modes: list[str]
    if hard_district and pref in ("center", "calm"):
        modes = ["strict", "nearest"]
    else:
        modes = ["any"]

    picked: list[dict[str, Any]] = []
    for mode in modes:
        scored = score_rows(need, enforce_budget=True, zone_mode=mode)
        if not scored and need > 2:
            scored = score_rows(max(2, need - 1), enforce_budget=True, zone_mode=mode)
        if not scored and max_rub is not None:
            scored = score_rows(need, enforce_budget=False, zone_mode=mode)
        if not scored:
            scored = score_rows(1, enforce_budget=False, zone_mode=mode)
        picked = take(scored)
        if picked:
            if mode == "nearest" and pref == "center":
                note = (
                    "В самом центре под ваши условия сейчас нет подходящих — "
                    "вот ближайшие варианты (не центр):"
                )
            elif mode == "nearest" and pref == "calm":
                note = (
                    "В тихих районах под ваши условия мало вариантов — "
                    "вот ближайшее, что нашлось:"
                )
            break
    return picked, note


def cards_message(
    district: str | None = None,
    guests: str | None = None,
    budget: str | None = None,
    limit: int = 3,
    path: Path | str = DEFAULT_PATH,
    *,
    exclude_names: list[str] | None = None,
) -> str | None:
    msg, _ = offer_bundle(
        district=district,
        guests=guests,
        budget=budget,
        limit=limit,
        path=path,
        exclude_names=exclude_names,
    )
    return msg


def offer_bundle(
    district: str | None = None,
    guests: str | None = None,
    budget: str | None = None,
    limit: int = 3,
    path: Path | str = DEFAULT_PATH,
    *,
    exclude_names: list[str] | None = None,
) -> tuple[str | None, list[str]]:
    """Текст карточек + список имён (чтобы «вариант 3» мапился в квартиру)."""
    items = pick_apartments(
        district=district,
        guests=guests,
        budget=budget,
        limit=limit + 3,
        path=path,
    )
    if exclude_names:
        ex = {n.lower() for n in exclude_names}
        items = [o for o in items if (o.get("name") or "").lower() not in ex]
    items = items[:limit]
    if not items:
        return None, []
    parts = ["Подобрала несколько вариантов под вас 🙂"]
    for i, obj in enumerate(items, 1):
        parts.append(f"{i}) {format_card(obj)}")
    parts.append(
        "Если подходит, напишите номер (1–3) или название. "
        "Наличие на эти даты отсюда не подтверждаю."
    )
    return "\n\n".join(parts), [str(o.get("name") or "") for o in items]


def priced_count(path: Path | str = DEFAULT_PATH) -> tuple[int, int]:
    """(с ценой, всего)."""
    con = _connect(path)
    if not con:
        return 0, 0
    try:
        rows = [_row_public(r) for r in con.execute("SELECT * FROM objects")]
        with_price = sum(
            1 for o in rows if isinstance(o.get("price_night"), int) and o["price_night"] > 0
        )
        return with_price, len(rows)
    finally:
        con.close()


def catalog_summary(path: Path | str = DEFAULT_PATH) -> str:
    """Факты для LLM: только то, что есть в БД. Без ориентировочных цен."""
    areas = list_areas(path)
    if not areas:
        return "каталог пуст"
    with_price, total = priced_count(path)
    bits = [f"Районы: {', '.join(areas)}", f"Объектов: {total}"]
    if with_price:
        bits.append(f"С ценой в БД: {with_price}")
    else:
        bits.append("Цен в БД нет — не называй цифры, скажи что менеджер уточнит")
    return ". ".join(bits)


def catalog_facts_for_llm(
    names: list[str] | None = None,
    path: Path | str = DEFAULT_PATH,
    limit: int = 8,
) -> str:
    """Короткие факты по объектам для LLM — только поля из БД."""
    con = _connect(path)
    if not con:
        return ""
    try:
        rows = [_row_public(r) for r in con.execute("SELECT * FROM objects")]
    finally:
        con.close()
    if names:
        want = {n.lower() for n in names if n}
        rows = [o for o in rows if (o.get("name") or "").lower() in want]
    rows = rows[:limit]
    lines = []
    for o in rows:
        price = format_price_line(o)
        cap = f", до {o['capacity']} гостей" if o.get("capacity") else ""
        lines.append(f"«{o['name']}» · {o['area']}{cap} · {price}")
    return "\n".join(lines)
