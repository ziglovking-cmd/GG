# -*- coding: utf-8 -*-
"""Адреса квартир из script.md → «Карта квартир» / «Адреса».

Один источник: правите адрес в script.md — бот отвечает по-новому после перезапуска.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=4)
def load_addresses(path: str = "") -> dict[str, str]:
    """{'скандинавия': 'Фитарёвская улица, 17, Коммунарка, м. Коммунарка', ...}"""
    p = Path(path or os.getenv("SCRIPT_PATH") or "script.md")
    if not p.is_absolute():
        p = ROOT / p
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    start = text.find("\nАдреса:")
    if start == -1:
        return {}
    end = text.find("\n## ", start)
    out: dict[str, str] = {}
    for line in text[start:end if end != -1 else len(text)].splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        names, _, rest = line[2:].partition(". ")
        if not rest:
            continue
        place = re.sub(r"\bм, ", "м. ", rest.rstrip(".").replace(". ", ", "))
        for name in re.split(r",\s*|\s+и\s+", names):
            name = name.strip()
            if name:
                out[name.lower()] = place
    return out


_ASK_WHERE_RE = re.compile(r"(?i)адрес|\bгде\b|какое\s+метро|какая\s+станц|как\s+добрат|рядом\s+с\s+метро|метро\s+рядом|далеко\s+от\s+метро")


def _stem(name: str) -> str:
    # «Скандинавия» → «скандинави», «Дюма» → «дюм», «Сноу пикс» целиком
    return name if " " in name or len(name) <= 4 else name[:-1]


def address_answer(text: str) -> str:
    """Ответ «где квартира», если гость назвал квартиру из карты и спросил адрес/метро."""
    if not text or not _ASK_WHERE_RE.search(text):
        return ""
    low = text.lower()
    found: list[tuple[str, str]] = []
    for name, place in load_addresses().items():
        if re.search(rf"(?<![а-яё]){re.escape(_stem(name))}", low):
            found.append((name, place))
    if not found:
        # назвали квартиру, которой нет в карте скрипта — не выдумываем адрес
        m = re.search(r"(?:квартир\w*|\bу|про|адрес)\s+«?([А-ЯЁ][а-яё]{2,})»?", text)
        if m and m.group(1).lower() not in _NOT_NAMES:
            return f"«{m.group(1)}» в моём списке адресов нет. Адрес подскажет менеджер, и он будет в инструкции перед заездом."
        return ""
    name, place = found[0]
    link = link_for(name)
    tail = f"\nФото и описание: {link}" if link else ""
    return f"«{name[:1].upper() + name[1:]}»: {place}.{tail}"


_NOT_NAMES = {"вас", "квартиры", "квартира", "метро", "москвы", "центра", "нее", "неё", "этой"}


@lru_cache(maxsize=4)
def load_places(path: str = "") -> dict[str, tuple[str, str, str]]:
    """{'малевич': ('Одинцово, ул. Каштановая, 6', 'Одинцово', 'МЦД-1 «Одинцово»'), ...}"""
    p = Path(path or os.getenv("SCRIPT_PATH") or "script.md")
    if not p.is_absolute():
        p = ROOT / p
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    start = text.find("\nАдреса:")
    if start == -1:
        return {}
    ends = [i for i in (text.find("\nРайоны (", start), text.find("\nСсылки на квартиры:", start),
                        text.find("\n## ", start)) if i != -1]
    end = min(ends) if ends else -1
    out: dict[str, tuple[str, str, str]] = {}
    for line in text[start:end if end != -1 else len(text)].splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        raw_parts = [x.strip() for x in line[2:].rstrip(".").split(". ")]
        parts: list[str] = []
        for piece in raw_parts:
            # «м. Коломенская», «ул. Каштановая» — сокращение, а не конец части
            if parts and re.search(r"(?:^|[\s,])(?:м|ул|пер|пр|д|корп|стр)$", parts[-1]):
                parts[-1] = f"{parts[-1]}. {piece}"
            else:
                parts.append(piece)
        if len(parts) < 2:
            continue
        names, street = parts[0], parts[1]
        district = parts[2] if len(parts) > 3 else ""
        metro = parts[-1] if len(parts) > 2 else ""
        metro = re.sub(r",?\s*не московское метро", "", metro)
        metro = re.sub(r"своего метро нет,\s*ближайшее\s*", "", metro)
        if metro and not district and not metro.startswith(("м.", "МЦД")):
            district, metro = metro, ""
        for name in re.split(r",\s*|\s+и\s+", names):
            if name.strip():
                out[name.strip().lower()] = (street, district, metro)
    return out


def place_short(name: str) -> str:
    """«Одинцово, МЦД-1 «Одинцово»» / «Котельники, м. Котельники» / ''."""
    got = load_places().get((name or "").strip().lower())
    if not got:
        return ""
    _street, district, metro = got
    return ", ".join(x for x in (district, metro) if x)


# Ближе всего к центру — по карте квартир в script.md («Ближе остальных к центру, но не Арбат»)
CENTER_NAMES = ("чехов", "дягилев", "шаляпин", "маяковский")


@lru_cache(maxsize=4)
def load_links(path: str = "") -> dict[str, str]:
    """Ссылки для просмотра: раздел «Ссылки на квартиры:» в script.md («- Малевич: https://…»)."""
    p = Path(path or os.getenv("SCRIPT_PATH") or "script.md")
    if not p.is_absolute():
        p = ROOT / p
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    start = text.find("\nСсылки на квартиры:")
    if start == -1:
        return {}
    # не захватывать «Путеводители для гостя» — там другие URL
    ends = [
        i
        for i in (
            text.find("\nПутеводители для гостя:", start),
            text.find("\nАдреса путеводителей:", start),
            text.find("\n## ", start),
        )
        if i != -1
    ]
    end = min(ends) if ends else -1
    out: dict[str, str] = {}
    for line in text[start:end if end != -1 else len(text)].splitlines():
        m = re.match(r"^\s*-\s*(.+?)\s*[:—-]\s*(https?://\S+)\s*$", line)
        if m:
            for name in re.split(r",\s*", m.group(1)):
                out[name.strip().lower()] = m.group(2)
    return out


def _key(name: str) -> str:
    return re.sub(r"[«»\"']", "", (name or "").strip().lower().replace("ё", "е"))


def link_for(name: str) -> str:
    """Ссылка на страницу квартиры; «Матисс» найдёт и «матис», «Скандинавия» — «сканди»."""
    links = {_key(k): v for k, v in load_links().items()}
    [REDACTED]
    if not [REDACTED] ""
    if key in links:
        return links[key]
    for k, v in links.items():
        if len(k) >= 4 and (key.startswith(k) or k.startswith(key)):
            return v
    return ""


@lru_cache(maxsize=4)
def load_pets(path: str = "") -> tuple[frozenset[str], frozenset[str], int, int]:
    """(можно, доплата_1500, fee_обычная, fee_особая) из раздела «Питомцы» script.md."""
    p = Path(path or os.getenv("SCRIPT_PATH") or "script.md")
    if not p.is_absolute():
        p = ROOT / p
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return frozenset(), frozenset(), 500, 1500
    start = text.find("\nПитомцы (")
    if start == -1:
        start = text.find("\nПитомцы:")
    if start == -1:
        return frozenset(), frozenset(), 500, 1500
    end = text.find("\nСсылки на квартиры:", start)
    chunk = text[start : end if end != -1 else len(text)]
    allowed: set[str] = set()
    fee1500: set[str] = set()
    fee_default = 500
    fee_special = 1500
    m_def = re.search(r"(?i)обычно\s+(\d[\d\s]*)\s*₽", chunk)
    if m_def:
        fee_default = int(re.sub(r"\s+", "", m_def.group(1)))
    m_sp = re.search(r"(?i)эверест.*?(\d[\d\s]*)\s*₽", chunk)
    if m_sp:
        fee_special = int(re.sub(r"\s+", "", m_sp.group(1)))
    section = ""
    for line in chunk.splitlines():
        low = line.strip().lower()
        if low.startswith("можно с животными"):
            section = "ok"
            continue
        if low.startswith("доплата 1500") or low.startswith("доплата 1 500"):
            section = "fee1500"
            continue
        if not line.strip().startswith("- "):
            continue
        names = line.strip()[2:]
        for name in re.split(r",\s*", names):
            [REDACTED]
            if not [REDACTED]
            if section == "ok":
                allowed.add(key)
            elif section == "fee1500":
                fee1500.add(key)
                allowed.add(key)
    return frozenset(allowed), frozenset(fee1500), fee_default, fee_special


def _pet_name_match(title: str, names: frozenset[str]) -> bool:
    [REDACTED]
    if not [REDACTED] False
    if key in names:
        return True
    for n in names:
        if len(n) >= 4 and (key.startswith(n) or n.startswith(key) or n in key or key in n):
            return True
    return False


def known_apartment_titles() -> list[str]:
    """Все имена квартир из карты/районов (без каталога SQLite)."""
    names: list[str] = []
    seen: set[str] = set()
    for key in load_addresses():
        title = key.strip()
        if title and title not in seen:
            seen.add(title)
            names.append(title)
    for _area, _aliases, flats in load_areas():
        for f in flats:
            title = str(f).strip()
            if title and title not in seen:
                seen.add(title)
                names.append(title)
    return names


def resolve_apartment_title(text: str, *, offers: list[str] | None = None) -> str:
    """Найти квартиру в тексте: сначала из предложенных, потом из карты."""
    raw = (text or "").strip()
    if not raw:
        return ""
    low = raw.lower().replace("ё", "е")
    # предложения из текущего списка
    for name in offers or []:
        n = str(name or "").strip()
        if not n:
            continue
        stem = n.lower().replace("ё", "е")
        stem = stem if " " in stem or len(stem) <= 4 else stem[:-1]
        if re.search(rf"(?<![а-яёa-z]){re.escape(stem)}", low):
            return n
    # каталог, если есть
    try:
        from bot.catalog import find_by_name_fuzzy

        hit = find_by_name_fuzzy(raw)
        if hit and hit.get("name"):
            return str(hit["name"])
    except Exception:
        pass
    # карта / районы из script.md
    best = ""
    best_len = 0
    for title in known_apartment_titles():
        stem = title.lower().replace("ё", "е")
        stem = stem if " " in stem or len(stem) <= 4 else stem[:-1]
        if len(stem) < 3:
            continue
        if re.search(rf"(?<![а-яёa-z]){re.escape(stem)}", low) and len(stem) > best_len:
            best = title[:1].upper() + title[1:] if title.islower() else title
            # канонический регистр из адресов
            for key in load_addresses():
                if [REDACTED] title:
                    best = key[:1].upper() + key[1:]
                    break
            best_len = len(stem)
    return best


def allows_pets(title: str) -> bool:
    """Можно ли с животными в этой квартире (по таблице /pets)."""
    allowed, _fee1500, _d, _s = load_pets()
    return _pet_name_match(title, allowed)


def pets_fee_rub(title: str) -> int | None:
    """Доплата за животных ₽/сутки или None, если нельзя."""
    allowed, fee1500, fee_default, fee_special = load_pets()
    if not _pet_name_match(title, allowed):
        return None
    if _pet_name_match(title, fee1500):
        return fee_special
    return fee_default


def pets_note(title: str) -> str:
    """«(можно с животными, доплата 500 ₽/сутки)» или ''."""
    fee = pets_fee_rub(title)
    if fee is None:
        return ""
    fee_s = f"{fee:,}".replace(",", "\u00a0")
    return f"(можно с животными, доплата {fee_s}\u00a0₽/сутки)"


@lru_cache(maxsize=4)
def load_areas(path: str = "") -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    """[('Прокшино', ('прокшин', 'лобановск', …), ('сноу пикс', 'вояж', …)), …] из раздела «Районы» script.md."""
    p = Path(path or os.getenv("SCRIPT_PATH") or "script.md")
    if not p.is_absolute():
        p = ROOT / p
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    start = text.find("\nРайоны (")
    if start == -1:
        return []
    end = text.find("\nСсылки на квартиры:", start)
    out = []
    for line in text[start:end if end != -1 else len(text)].splitlines():
        m = re.match(r"^\s*-\s*([^(:]+?)\s*(?:\(([^)]*)\))?\s*:\s*(.+)$", line)
        if not m:
            continue
        area = m.group(1).strip()
        aliases = [_key(area)] + [_key(a) for a in (m.group(2) or "").split(",") if a.strip()]
        flats = tuple(_key(x) for x in m.group(3).split(",") if x.strip())
        out.append((area, tuple(a for a in aliases if a), flats))
    return out


def areas_for_place(place: str) -> list[str]:
    """Районы из script.md, которые гость назвал («в Прокшино» → ['Прокшино']).

    При нескольких совпадениях берём самые длинные алиасы — «близко к центру»
    не должно тянуть за собой голый «Центр».
    """
    low = _key(place)
    if not low:
        return []
    scored: list[tuple[int, str]] = []
    for area, aliases, _flats in load_areas():
        best = 0
        for a in aliases:
            stem = re.sub(r"(ский|ская|ское|ий|ая|ое|о|а|е|и|ы)$", "", a) if len(a) > 5 else a
            if stem and stem in low:
                best = max(best, len(stem))
        if best:
            scored.append((best, area))
    if not scored:
        return []
    top = max(score for score, _ in scored)
    return [area for score, area in scored if score == top]


def _flat_in([REDACTED] flats: tuple[str, ...]) -> bool:
    return any(
        [REDACTED] f
        or key.startswith(f)
        or f.startswith(key)
        or re.search(rf"(?<![а-яa-z]){re.escape(f)}(?![а-яa-z])", key)
        for f in flats
    )


def in_area(title: str, place: str) -> bool:
    """Квартира в районе, который назвал гость (сначала «Районы», иначе район из «Адреса»)."""
    [REDACTED]
    if not [REDACTED] False
    wanted = set(areas_for_place(place))
    listed_here = False
    for area, _aliases, flats in load_areas():
        if not _flat_in(key, flats):
            continue
        listed_here = True
        # квартира явно в разделе «Районы» — не подмешивать чужой район из строки адреса
        # (скрин: Казбек/Белуха не в Коммунарке, Хомлин — Прокшино)
        if area in wanted:
            return True
    if listed_here:
        return False
    district = (load_places().get(key) or ("", "", ""))[1]
    if district and len(_key(district)) >= 5:
        d = re.sub(r"(ский|ская|ское|о|а|е)$", "", _key(district))
        if d and d in _key(place):
            return True
    return False


@lru_cache(maxsize=4)
def load_guides(path: str = "") -> dict[str, str]:
    """{'чехов': 'https://…/g/chekhov', …} из «Путеводители для гостя»."""
    p = Path(path or os.getenv("SCRIPT_PATH") or "script.md")
    if not p.is_absolute():
        p = ROOT / p
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    start = text.find("\nПутеводители для гостя:")
    if start == -1:
        return {}
    end_marks = [text.find("\nАдреса путеводителей:", start), text.find("\n## ", start)]
    ends = [i for i in end_marks if i != -1]
    end = min(ends) if ends else -1
    out: dict[str, str] = {}
    for line in text[start:end if end != -1 else len(text)].splitlines():
        m = re.match(r"^\s*-\s*(.+?)\s*[:—-]\s*(https?://\S+)\s*$", line)
        if not m:
            continue
        url = m.group(2).rstrip(".,)")
        for name in re.split(r",\s*", m.group(1)):
            [REDACTED]
            if [REDACTED] = url
    return out


@lru_cache(maxsize=4)
def load_guide_addresses(path: str = "") -> list[tuple[str, tuple[str, ...]]]:
    """[(короткий адрес, ('чехов', 'дягилев', …)), …]."""
    p = Path(path or os.getenv("SCRIPT_PATH") or "script.md")
    if not p.is_absolute():
        p = ROOT / p
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    start = text.find("\nАдреса путеводителей:")
    if start == -1:
        return []
    end = text.find("\n## ", start)
    out: list[tuple[str, tuple[str, ...]]] = []
    for line in text[start:end if end != -1 else len(text)].splitlines():
        m = re.match(r"^\s*-\s*(.+?)\s*:\s*(.+)\s*$", line)
        if not m:
            continue
        addr = m.group(1).strip()
        names = tuple(_key(n) for n in re.split(r",\s*", m.group(2)) if _key(n))
        if addr and names:
            out.append((addr, names))
    return out


def guide_for_name(name: str) -> tuple[str, str]:
    """(отображаемое имя, url) или ('', '')."""
    guides = load_guides()
    [REDACTED]
    if not [REDACTED] "", ""
    if key in guides:
        return name.strip(), guides[key]
    for k, url in guides.items():
        if len(k) >= 4 and (key.startswith(k) or k.startswith(key) or k in key or key in k):
            title = k[:1].upper() + k[1:]
            return title, url
    return "", ""


def _addr_norm(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"(?i)\b(г|город|ул|улица|пер|переулок|пр|проспект|п-д|проезд|ш|шоссе|д|дом|к|корп|стр|кв)\b\.?", " ", t)
    t = re.sub(r"[«»\"'.,;:/\\()]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _addr_tokens(text: str) -> set[str]:
    return {w for w in _addr_norm(text).split() if len(w) >= 2}


def guides_for_address(text: str) -> list[tuple[str, str]]:
    """Квартиры с путеводителем по адресу гостя: [(имя, url), …]."""
    raw = (text or "").strip()
    if not raw:
        return []
    # сначала точное имя квартиры в тексте
    by_name: list[tuple[str, str]] = []
    low = raw.lower().replace("ё", "е")
    for key, url in load_guides().items():
        stem = key if " " in key or len(key) <= 4 else key[:-1]
        if len(stem) >= 3 and re.search(rf"(?<![а-яa-z]){re.escape(stem)}", low):
            title = key[:1].upper() + key[1:]
            by_name.append((title, url))
    if len(by_name) == 1:
        return by_name
    if len(by_name) > 1:
        return by_name

    guest_tok = _addr_tokens(raw)
    if len(guest_tok) < 1:
        return []
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for addr, names in load_guide_addresses():
        addr_tok = _addr_tokens(addr)
        # улица + дом: пересечение с числом/корпусом или почти все токены адреса
        nums = {t for t in addr_tok if re.search(r"\d", t)}
        words = {t for t in addr_tok if not re.search(r"\d", t) and len(t) >= 4}
        if nums and not (nums & guest_tok):
            continue
        if words and not (words & guest_tok):
            # короткие улицы «рим» нет — требуем хотя бы один длинный токен
            if not any(w in _addr_norm(raw) for w in words):
                continue
        elif not nums and not words:
            continue
        for key in names:
            if key in seen:
                continue
            url = load_guides().get(key) or ""
            if not url:
                # alias key may differ; try guide_for_name
                title, url = guide_for_name(key)
            else:
                title = key[:1].upper() + key[1:]
            if url:
                seen.add(key)
                hits.append((title, url))
    if hits:
        return hits

    # полный адрес из «Адреса» script.md
    for name, place in load_addresses().items():
        place_tok = _addr_tokens(place)
        nums = {t for t in place_tok if re.search(r"\d", t)}
        words = {t for t in place_tok if not re.search(r"\d", t) and len(t) >= 5}
        if nums and not (nums & guest_tok):
            continue
        if words and not (words & guest_tok) and not any(w in _addr_norm(raw) for w in words):
            continue
        title, url = guide_for_name(name)
        if url and name not in seen:
            seen.add(name)
            hits.append((title or name[:1].upper() + name[1:], url))
    return hits


GUIDE_ASK_LINE = "Подскажите, пожалуйста, ваш адрес — пришлю инструкцию по проживанию 🙂"

GUIDE_MULTI_LINE = (
    "На этом адресе несколько квартир. "
    "Подскажите, пожалуйста, название — и сразу пришлю нужную инструкцию 🙂"
)

GUIDE_UNKNOWN_LINE = (
    "Не нашла этот адрес в списке. "
    "Напишите название квартиры или адрес как в брони — пришлю инструкцию 🙂"
)


def format_guide_message(name: str, url: str) -> str:
    """Текст гостю со ссылкой на путеводитель."""
    title = (name or "вашей квартиры").strip()
    if title and not title.startswith("«"):
        title = f"«{title}»"
    return (
        f"Спасибо! Вот путеводитель по вашей квартире {title}.\n\n"
        f"В нём — как пользоваться техникой, где парковка, как пройти "
        f"и всё для комфортного проживания:\n\n"
        f"{url}\n\n"
        f"Если что-то останется неясным — напишите, я рядом 🙂"
    )
