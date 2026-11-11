#!/usr/bin/env python3
"""Build apartments.json from Yandex videos + Home24 guest copy."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
VIDEOS = json.loads((ROOT / "data-videos.json").read_text())
LUNAR_PUBLIC = "https://disk.yandex.ru/d/qEcIlAwweu9PVQ"
SALARYEVO_PUBLIC = "https://disk.yandex.ru/d/F0fTNy2NXCWrSg"
MATISS_PUBLIC = "https://disk.yandex.ru/d/FU-ezcYY42tGjw"
HOMLIN_PUBLIC = "https://disk.yandex.ru/d/hMG8nsN7pgBzew"
ARTMEN_PUBLIC = "https://disk.yandex.ru/d/u7W9-FhP5WI6ug"
VOYAZH_PUBLIC = "https://disk.yandex.ru/d/sgoDpoIgFACMOQ"
BRIZ_PUBLIC = "https://disk.yandex.ru/d/qHH59Igb1tedqA"
FERRARI_PUBLIC = "https://disk.yandex.ru/d/JgDRbxlWFoZagw"
PUBLIC = "https://disk.yandex.ru/d/ZLKt8eDXJYKdnQ"
YANDEX_FOLDER = "https://disk.yandex.ru/d/ZLKt8eDXJYKdnQ"
CATALOG_SIZE = 90


def load_lunar_files() -> list[dict]:
    dest = ROOT / "data" / "lunar-videos.json"
    cached: list[dict] = []
    if dest.exists():
        cached = json.loads(dest.read_text(encoding="utf-8"))
    try:
        import urllib.parse
        import urllib.request

        url = "https://cloud-api.yandex.net/v1/disk/public/resources?" + urllib.parse.urlencode(
            {"public_key": LUNAR_PUBLIC, "limit": 100}
        )
        with urllib.request.urlopen(url, timeout=25) as res:
            payload = json.load(res)
        items = payload.get("_embedded", {}).get("items", [])
        files = []
        for it in items:
            if it.get("type") != "file":
                continue
            files.append(
                {
                    "name": it["name"],
                    "path": it.get("path") or "/" + it["name"],
                    "size": it.get("size"),
                    "public_key": LUNAR_PUBLIC,
                    "folder": "/",
                    "object": "lunar",
                }
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(files, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("lunar disk files", len(files))
        return files
    except Exception as exc:
        print("lunar disk refresh skipped:", exc)
        return cached


LUNAR_FILES = load_lunar_files()


def load_salaryevo_files() -> list[dict]:
    dest = ROOT / "data" / "salaryevo-videos.json"
    cached: list[dict] = []
    if dest.exists():
        cached = json.loads(dest.read_text(encoding="utf-8"))
    try:
        import urllib.parse
        import urllib.request

        url = "https://cloud-api.yandex.net/v1/disk/public/resources?" + urllib.parse.urlencode(
            {"public_key": SALARYEVO_PUBLIC, "path": "/", "limit": 200}
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as res:
            payload = json.load(res)
        items = payload.get("_embedded", {}).get("items", [])
        files = []
        for it in items:
            if it.get("type") != "file":
                continue
            raw = it.get("path") or "/" + it["name"]
            if raw.startswith("disk:"):
                raw = raw[5:]
            if not raw.startswith("/"):
                raw = "/" + raw
            files.append(
                {
                    "name": it["name"],
                    "path": raw,
                    "size": it.get("size"),
                    "public_key": SALARYEVO_PUBLIC,
                    "folder": "/",
                    "object": "salaryevo",
                }
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(files, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("salaryevo disk files", len(files))
        return files
    except Exception as exc:
        print("salaryevo disk refresh skipped:", exc)
        return cached


SALARYEVO_FILES = load_salaryevo_files()


def load_matiss_files() -> list[dict]:
    dest = ROOT / "data" / "matiss-videos.json"
    cached: list[dict] = []
    if dest.exists():
        cached = json.loads(dest.read_text(encoding="utf-8"))
    try:
        import urllib.parse
        import urllib.request

        url = "https://cloud-api.yandex.net/v1/disk/public/resources?" + urllib.parse.urlencode(
            {"public_key": MATISS_PUBLIC, "path": "/", "limit": 200}
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as res:
            payload = json.load(res)
        items = payload.get("_embedded", {}).get("items", [])
        files = []
        for it in items:
            if it.get("type") != "file":
                continue
            raw = it.get("path") or "/" + it["name"]
            if raw.startswith("disk:"):
                raw = raw[5:]
            if not raw.startswith("/"):
                raw = "/" + raw
            low = (it.get("name") or "").lower()
            if not low.endswith((".mp4", ".mov", ".m4v", ".webm")):
                continue
            files.append(
                {
                    "name": it["name"],
                    "path": raw,
                    "size": it.get("size"),
                    "public_key": MATISS_PUBLIC,
                    "folder": "/",
                    "object": "matiss",
                }
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(files, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("matiss disk files", len(files))
        return files
    except Exception as exc:
        print("matiss disk refresh skipped:", exc)
        return cached


MATISS_FILES = load_matiss_files()


def load_object_files(slug: str, public_key: str) -> list[dict]:
    dest = ROOT / "data" / f"{slug}-videos.json"
    cached: list[dict] = []
    if dest.exists():
        cached = json.loads(dest.read_text(encoding="utf-8"))
    try:
        import urllib.parse
        import urllib.request

        url = "https://cloud-api.yandex.net/v1/disk/public/resources?" + urllib.parse.urlencode(
            {"public_key": public_key, "path": "/", "limit": 200}
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as res:
            payload = json.load(res)
        items = payload.get("_embedded", {}).get("items", [])
        files = []
        for it in items:
            if it.get("type") != "file":
                continue
            raw = it.get("path") or "/" + it["name"]
            if raw.startswith("disk:"):
                raw = raw[5:]
            if not raw.startswith("/"):
                raw = "/" + raw
            low = (it.get("name") or "").lower()
            if not low.endswith((".mp4", ".mov", ".m4v", ".webm")):
                continue
            files.append(
                {
                    "name": it["name"],
                    "path": raw,
                    "size": it.get("size"),
                    "public_key": public_key,
                    "folder": "/",
                    "object": slug,
                }
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(files, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{slug} disk files", len(files))
        return files
    except Exception as exc:
        print(f"{slug} disk refresh skipped:", exc)
        return cached


HOMLIN_FILES = load_object_files("homlin", HOMLIN_PUBLIC)
ARTMEN_FILES = load_object_files("artmen", ARTMEN_PUBLIC)
VOYAZH_FILES = load_object_files("voyazh", VOYAZH_PUBLIC)
BRIZ_FILES = load_object_files("briz", BRIZ_PUBLIC)
FERRARI_FILES = load_object_files("ferrari", FERRARI_PUBLIC)


def _nfc_low(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").lower()


def _is_coffee_name(name: str) -> bool:
    blob = _nfc_low(name)
    return "кофемаш" in blob or "кофевар" in blob


def _list_disk_folder(public_key: str, path: str) -> list[dict]:
    import urllib.parse
    import urllib.request

    url = "https://cloud-api.yandex.net/v1/disk/public/resources?" + urllib.parse.urlencode(
        {"public_key": public_key, "path": path, "limit": 100}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as res:
        payload = json.load(res)
    out = []
    for it in payload.get("_embedded", {}).get("items") or []:
        raw = it.get("path") or "/" + it.get("name", "")
        if raw.startswith("disk:"):
            raw = raw[5:]
        if not raw.startswith("/"):
            raw = "/" + raw
        out.append({"name": it.get("name") or "", "path": raw, "type": it.get("type"), "size": it.get("size")})
    return out


def load_shared_coffee() -> dict | None:
    dest = ROOT / "data" / "shared-videos.json"
    packed = None
    scans = [
        (LUNAR_PUBLIC, "/", "lunar"),
        (PUBLIC, "/", "main"),
        (PUBLIC, "/Видео материал ", "main"),
        (PUBLIC, "/Видео материал /Общее", "main"),
        (PUBLIC, "/Видео материал /Общее/", "main"),
    ]
    seen_dirs: set[tuple[str, str]] = set()
    for public_key, path, disk in scans:
        try:
            items = _list_disk_folder(public_key, path)
        except Exception:
            continue
        for it in items:
            if it["type"] == "file" and _is_coffee_name(it["name"]):
                packed = {
                    "title": "Как пользоваться кофемашиной",
                    "name": it["name"],
                    "url": f"{public_key}?path={quote(it['path'])}",
                    "path": it["path"],
                    "folderUrl": public_key,
                    "disk": disk,
                }
                break
            if it["type"] == "dir" and "общее" in _nfc_low(it["name"]):
                key = (public_key, it["path"])
                if key not in seen_dirs:
                    seen_dirs.add(key)
                    scans.append((public_key, it["path"], disk))
        if packed:
            break
    if packed is None:
        for v in list(LUNAR_FILES) + list(VIDEOS):
            if _is_coffee_name(v.get("name") or ""):
                disk = "lunar" if v in LUNAR_FILES or v.get("object") == "lunar" else "main"
                public_key = LUNAR_PUBLIC if disk == "lunar" else PUBLIC
                packed = {
                    "title": "Как пользоваться кофемашиной",
                    "name": v["name"],
                    "url": f"{public_key}?path={quote(v['path'])}",
                    "path": v["path"],
                    "folderUrl": public_key,
                    "disk": disk,
                }
                break
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({"videos": [packed] if packed else []}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("shared coffee", packed["name"] if packed else "not on disk yet")
    return packed


SHARED_COFFEE = load_shared_coffee()
COFFEE_FAQ = {
    "q": "Как пользоваться кофемашиной?",
    "a": "Короткое видео — во вкладке «Видео пользования техникой и не только». Капсулы или зерно обычно стоят рядом с машиной. После себя промойте рожок. Если машины нет или она не включается — напишите персональному менеджеру с 09:00 до 00:00.",
}

CONTACT_PHONE = "+7 977 717-60-97"
CONTACT_SITE = "https://home24.msk.ru"
CONTACT_HOURS = "09:00 до 00:00"
COMPANY = "Home24"

SITE_ROWS = json.loads((ROOT / "data" / "home24-site.json").read_text(encoding="utf-8"))


def norm_name(s: str) -> str:
    s = s.lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", s)


SITE_BY_NAME = {norm_name(row["title"]): row for row in SITE_ROWS}

# Same building on the site, different internal name in the guest catalog.
SITE_ALIASES = {
    "каштан": "кандинский",
    "одинцово": "кандинский",
    "севанская": "венера",
    "северная": "сага",
    "мята": "олимп",
    "котельники": "парамаунт",
    "вершины": "снежныепики",
}

SITE_VIDEO_ALIASES = {
    "севанская": "венера",
    "северная": "сага",
    "мята": "олимп",
    "котельники": "парамаунт",
    "вершины": "снежныепики",
}


def load_booking_site_videos() -> dict[str, list[dict]]:
    dest = ROOT / "data" / "home24-site-videos.json"
    cached: list[dict] = []
    if dest.exists():
        cached = json.loads(dest.read_text(encoding="utf-8"))
    rows = cached
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://home24.msk.ru/api/travelline/sync-state",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=40) as res:
            payload = json.load(res)
        cards = ((payload.get("state") or {}).get("cards")) or []
        fresh: list[dict] = []
        for card in cards:
            fields = card.get("fields") or {}
            title = fields.get("title") or {}
            name = (title.get("local") if isinstance(title, dict) else title) or ""
            name = str(name).strip()
            if not name or _nfc_low(name).startswith("парковка"):
                continue
            vids = fields.get("videos") or {}
            clips = vids.get("local") if isinstance(vids, dict) else vids
            if not isinstance(clips, list):
                continue
            packed = []
            for clip in clips:
                if not isinstance(clip, dict):
                    continue
                href = str(clip.get("url") or "")
                if "mozilla.net" in href or "flower.mp4" in href:
                    continue
                path = href.split("?", 1)[0]
                if not path.startswith("/api/media/") or not path.lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
                    continue
                packed.append(
                    {
                        "title": clip.get("title") or "Обзор",
                        "url": path,
                        "originalName": clip.get("originalName") or path.rsplit("/", 1)[-1],
                    }
                )
            if packed:
                fresh.append({"title": name, "videos": packed})
        if fresh:
            rows = fresh
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("booking site videos", len(rows))
    except Exception as exc:
        print("booking site videos refresh skipped:", exc)
    by_name: dict[str, list[dict]] = {}
    for row in rows:
        by_name[norm_name(row.get("title") or "")] = list(row.get("videos") or [])
    return by_name


BOOKING_VIDEOS = load_booking_site_videos()


def apply_site_videos(a: dict) -> None:
    if a.get("skipVideos"):
        return
    key = norm_name(a.get("name") or "")
    clips = BOOKING_VIDEOS.get(key) or BOOKING_VIDEOS.get(norm_name(SITE_VIDEO_ALIASES.get(key, "")))
    if not clips:
        return
    blob = _nfc_low(" ".join(f"{v.get('title', '')} {v.get('name', '')}" for v in a.get("videos") or []))
    if "обзор квартир" in blob or "как выглядит квартир" in blob or "видео о квартир" in blob:
        return
    packed = []
    for clip in clips:
        href = clip.get("url") or ""
        file_name = href.rsplit("/", 1)[-1]
        abs_url = href if href.startswith("http") else f"https://home24.msk.ru{href}"
        packed.append(
            {
                "title": "Как выглядит квартира",
                "name": clip.get("originalName") or file_name,
                "url": abs_url,
                "path": f"/{file_name}",
                "disk": "home24",
                "folderUrl": "https://home24.msk.ru",
            }
        )
    a["videos"] = packed + list(a.get("videos") or [])


def apply_site_address(a: dict) -> None:
    if a["slug"] in {"dyuma", "tven", "dickens", "shir", "lorien"} or a["slug"].startswith("lunar"):
        return
    key = norm_name(a["name"])
    row = SITE_BY_NAME.get(key) or SITE_BY_NAME.get(SITE_ALIASES.get(key, ""))
    if not row:
        return
    old = a["address"]
    if not a.get("pinAddress"):
        a["address"] = row["address"]
    a["coords"] = row["coords"]
    if row.get("metro"):
        a["metro"] = row["metro"]
    if not a.get("pinAddress") and old in a["how"]:
        a["how"] = a["how"].replace(old, a["address"])
    placeholder_how = (
        not a.get("pinAddress")
        and (
            "объект «" in old
            or a["how"].startswith("Адрес: Москва, объект")
            or "менеджер впишет" in a["how"]
            or "менеджер пришлёт" in a["how"]
            or "появится, когда менеджер" in a["how"]
        )
    )
    if placeholder_how:
        extra = f"\nОриентир: {a['metro']}." if a.get("metro") else ""
        coords = f"\nКоординаты: {a['coords']}." if a.get("coords") else ""
        a["how"] = (
            f"Адрес с сайта Home24: {a['address']}.{extra}{coords}\n"
            "Точка на карте стоит на доме — откройте «Смотреть на карте» или маршрут в навигаторе."
        )
    if a["coords"] and a["coords"] not in a["how"]:
        a["how"] = a["how"].rstrip() + f"\n\nКоординаты для навигатора: {a['coords']}."


def disk_url(path: str) -> str:
    if not path:
        return PUBLIC
    return f"{PUBLIC}?path={quote(path)}"


def file_url(v: dict) -> str:
    if v.get("public_url"):
        return v["public_url"].replace("https://yadi.sk/", "https://disk.yandex.ru/")
    return disk_url(v["path"])


def guess_title(filename: str) -> str:
    filename = unicodedata.normalize("NFC", filename)
    name = filename.rsplit(".", 1)[0]
    name = name.replace("_", " ").replace("-", " ").strip()
    mapping = [
        ("кофемаш", "Как пользоваться кофемашиной"),
        ("кофевар", "Как пользоваться кофемашиной"),
        ("телевизор", "Как пользоваться телевизором"),
        ("телек", "Как пользоваться телевизором"),
        ("телеизор", "Как пользоваться телевизором"),
        ("плит", "Как пользоваться варочной панелью"),
        ("варочн", "Как пользоваться варочной панелью"),
        ("вытяжк", "Как пользоваться вытяжкой"),
        ("духов", "Как пользоваться духовкой"),
        ("микроволн", "Как пользоваться микроволновкой"),
        ("стирал", "Как пользоваться стиральной машиной"),
        ("посудом", "Как пользоваться посудомойкой"),
        ("душ", "Как пользоваться душем"),
        ("ключниц", "Как открыть ключницу"),
        ("кючниц", "Как открыть ключницу"),
        ("коворкинг", "Как пройти в коворкинг и спортзал"),
        ("спортзал", "Как пройти в коворкинг и спортзал"),
        ("найти квартир", "Как найти квартиру"),
        ("пройти", "Как пройти к подъезду"),
        ("подъезд", "Как открыть подъезд"),
        ("подьезд", "Как открыть подъезд"),
        ("мусор", "Куда выносить мусор"),
        ("роутер", "Где роутер и как перезагрузить Wi‑Fi"),
        ("щиток", "Где щиток"),
        ("кондиц", "Как работает кондиционер"),
        ("подсветк", "Как включить подсветку кухни"),
        ("полотенц", "Как включить полотенцесушитель"),
        ("чайник", "Как включить чайник"),
        ("тост", "Как пользоваться тостером"),
        ("штор", "Как работают шторы"),
        ("диван", "Как разложить диван"),
        ("бойлер", "Как включить бойлер"),
        ("замок", "Электронный замок"),
        ("тамбур", "Как открыть тамбур"),
        ("проходн", "Проходные выключатели"),
        ("видео домофон", "Как пользоваться видеодомофоном"),
        ("домофон", "Ключ от домофона"),
        ("мастер кноп", "Мастер-кнопка"),
        ("теплым пол", "Тёплый пол (только зимой)"),
        ("проветриван", "Как поставить на проветривание"),
        ("отоплени", "Как включить батарею отопления"),
        ("батаре", "Как отключить батарею"),
        ("вода", "Где перекрыть воду"),
        ("белье", "Где лежит дополнительное бельё"),
        ("троих", "Как разместить троих гостей"),
        ("квартире", "Видео о квартире"),
        ("обзор", "Обзор квартиры"),
        ("обогрев", "Обогреватель"),
        ("холодиль", "Как работает холодильник"),
        ("фильтр", "Фильтр для воды"),
        ("свет", "Где включается свет"),
        ("кладов", "Кладовка"),
    ]
    low = name.lower()
    for needle, title in mapping:
        if needle in low:
            return title
    if name.lower().startswith("whatsapp") or name.lower().startswith("file_") or name.lower().startswith("video") or name.lower().startswith("merge"):
        return "Видеоинструкция"
    return name[0].upper() + name[1:] if name else "Видео"


UNIVERSAL_FAQ = [
    {
        "q": "Можно ли с собакой или кошкой?",
        "a": "Да, питомцы разрешены на всех объектах. Доплата 500 ₽ в сутки. Напишите менеджеру заранее, что едете с животным.",
    },
    {
        "q": "Можно ли продлить проживание?",
        "a": "Да, если после вас нет заезда. Напишите в чат как можно раньше — менеджер подтвердит даты и стоимость.",
    },
    {
        "q": "Во сколько заезд и выезд?",
        "a": "Заезд с 14:00, выезд до 12:00. Ранний заезд и поздний выезд — по договорённости, возможна доплата.",
    },
    {
        "q": "Нужен ли депозит?",
        "a": "Да, депозит 2 000 ₽. Возвращается при соблюдении правил проживания.",
    },
    {
        "q": "Можно ли курить?",
        "a": "В квартире курить нельзя: сигареты, вейп, кальян. Курение только на улице, в местах где это разрешено.",
    },
    {
        "q": "Дети едут с нами",
        "a": "Дети до 5 лет размещаются бесплатно. Дополнительный комплект белья — 500 ₽, если нужен отдельный спальный комплект.",
    },
    {
        "q": "Нужны документы для командировки",
        "a": "Да, даём чек и отчётные документы. Напишите менеджеру в чат.",
    },
    {
        "q": "Нет интернета / не работает розетка",
        "a": "Перезагрузите роутер (кнопка или вынуть питание на 10 секунд). Если нет света в розетке — проверьте автоматы в щитке. Если не помогло, сразу напишите нам в чат.",
    },
]

RULES = """Дорогие гости!

Чтобы отдых прошёл спокойно, договоримся о простых правилах.

• В квартире есть полотенца, тапочки, шампунь, гель, мыло, зубной набор, чай, кофе, сахар и соль.
• Мы не отель: дополнительное бельё сушится в квартире — пожалуйста, не используйте его.
• Напишите в чат фактическое время заезда и выезда.
• Курить в квартире нельзя.
• После выезда вынесите мусор — так горничная успеет подготовить квартиру следующему гостю.
• Питомцы разрешены, 500 ₽/сутки, предупредите заранее.
• Переобувайтесь в тапочки.
• Без шумных вечеринок и больших компаний — уважаем соседей.
• Заезд с 14:00, выезд до 12:00. Круглосуточное самостоятельное заселение.
• Депозит 2 000 ₽. Дети до 5 лет бесплатно.
• При бронировании на двоих бельё на одну двуспальную кровать. Максимум гостей обычно 4. Доп. комплект 500 ₽."""

PARKING_MOS = "https://parking.mos.ru/"
PARKING_MOS_LINE = f"Карта платных зон и оплата на сайте Московского паркинга: {PARKING_MOS}"

PARKING_OBLAST = f"""Это Московская область — городская зона «Московский паркинг» здесь не действует.

Ставьте машину на свободное преддомовое место у дома. Соблюдайте знаки и разметку. Шлагбаум жилого комплекса, если он есть, гостям не выдаём.

Если поедете в Москву, зоны и оплату смотрите здесь: {PARKING_MOS}"""

PARKING_TINANO = f"""Во дворе и на преддомовых карманах у дома места обычно бесплатные. Шлагбаум и подземный паркинг жильцов мы не открываем.

В Коммунарке на части улиц уже есть городская платная зона. Смотрите знаки у бордюра: если табличка «Московский паркинг» — оплатите на сайте или в приложении, иначе придёт штраф.

{PARKING_MOS_LINE}"""

PARKING_MIXED = f"""У дома ищите свободные дворовые / преддомовые места без знака оплаты — они обычно бесплатные. Шлагбаум жилого комплекса гостям не выдаём.

На ближайших улицах может быть зона «Московский паркинг». Смотрите знаки и разметку. Если улица платная — оплатите на сайте Московского паркинга.

{PARKING_MOS_LINE}"""

PARKING_STREET = f"""На улицах вокруг дома действует платная городская парковка («Московский паркинг»). Смотрите знаки: тариф обычно 40–80 ₽/час в будни, воскресенье и праздники часто бесплатно.

Дворовые карманы без таблички оплаты обычно бесплатные. Подземный паркинг и шлагбаум комплекса гостям не выдаём.

{PARKING_MOS_LINE}"""

PARKING_JK = f"""Местная улично-дорожная сеть этого ЖК включена в «Московский паркинг» (платная зона). Смотрите знаки во дворе-проездах: если зона платная — оплатите на сайте.

Шлагбаум и подземные машиноместа жильцов гостям не выдаём.

{PARKING_MOS_LINE}"""

PARKING_LUNAR = f"""На Ленинском проспекте у ЖК LUNAR — платная городская парковка (около 40–80 ₽/час в будни).

Подземный паркинг LUNAR только для своих машиномест, гостевой карты нет.

Ищите место на прилегающих проездах по знакам: где нет таблички оплаты — стоять можно бесплатно, не нарушая разметку.

{PARKING_MOS_LINE}"""

PARKING_MAGISTRAL = f"""Во дворе дома парковка в основном для резидентов. Шлагбаум гостям не выдаём.

На 1-й Магистральной и рядом — городская платная зона и отдельные платные стоянки. Смотрите знаки.

{PARKING_MOS_LINE}"""

PARKING_YUB = f"""Улица Южнобутовская включена в платную городскую зону (около 40 ₽/час).

Дворовые места без знака оплаты обычно бесплатные. Шлагбаум комплекса гостям не выдаём.

{PARKING_MOS_LINE}"""


def parking_kind(address: str, slug: str, area: str) -> str:
    a = (address or "").lower().replace("ё", "е")
    ar = (area or "").lower()
    if any(x in a for x in ("одинцово", "одинцовск", "каштан", "северная", "медовая", "заречье", "верхне-пролетар", "котельники", "сосновая")):
        return "oblast"
    if slug in {"dyuma", "tven", "dickens"} or ("ленинский" in a and "38" in a):
        return "lunar"
    if "магистральн" in a:
        return "magistral"
    if "южнобутовск" in a:
        return "yub"
    if "красноказармен" in a or "руставел" in a or "2-й нагатинский" in a or "2-и нагатинский" in a or slug == "soyka":
        return "jk"
    if slug in {"baumanskaya", "chekhov", "dyagilev", "mayakovskiy"} or "балакирев" in a:
        return "street"
    if "газгольдер" in a or "нагатинск" in a:
        return "street"
    if any(
        x in a
        for x in (
            "фитарев",
            "ощепков",
            "лобанов",
            "прокшин",
            "магеллан",
            "бачурин",
            "трехпол",
            "трёхпол",
            "мосрентген",
            "эдальго",
        )
    ) or "коммунар" in ar:
        return "tinano"
    return "mixed"


def parking_pack(address: str, slug: str, area: str) -> tuple[str, str, str]:
    kind = parking_kind(address, slug, area)
    if kind == "oblast":
        return (
            PARKING_OBLAST,
            "Нет городской зоны Москвы. Ставьте на свободное преддомовое место у дома. Если окажетесь в Москве: https://parking.mos.ru/",
            "Парковка бесплатная преддомовая (Московская область, городской паркинг не действует).",
        )
    if kind == "tinano":
        return (
            PARKING_TINANO,
            "Двор и карманы у дома обычно бесплатные. На части улиц Коммунарки уже «Московский паркинг» — смотрите знаки. Карта и оплата: https://parking.mos.ru/",
            "Двор обычно бесплатный; на части улиц Коммунарки может быть платная зона — смотрите знаки.",
        )
    if kind == "lunar":
        return (
            PARKING_LUNAR,
            "На Ленинском проспекте — платная городская зона. Подземный паркинг LUNAR гостям не выдаём. Карта и оплата: https://parking.mos.ru/",
            "На Ленинском — платная городская парковка; подземный паркинг ЖК гостям недоступен.",
        )
    if kind == "magistral":
        return (
            PARKING_MAGISTRAL,
            "Двор в основном для резидентов. На улице — платная городская зона. Карта и оплата: https://parking.mos.ru/",
            "Двор для резидентов; на улице возможна платная городская парковка.",
        )
    if kind == "yub":
        return (
            PARKING_YUB,
            "Южнобутовская — платная городская зона. Двор без знака оплаты обычно бесплатный. Карта и оплата: https://parking.mos.ru/",
            "На Южнобутовской платная городская зона; двор обычно бесплатный.",
        )
    if kind == "jk":
        return (
            PARKING_JK,
            "Проезды этого ЖК в платной зоне «Московский паркинг». Смотрите знаки. Карта и оплата: https://parking.mos.ru/. Шлагбаум не выдаём.",
            "Проезды ЖК в платной городской зоне — смотрите знаки.",
        )
    if kind == "street":
        return (
            PARKING_STREET,
            "На улицах вокруг дома платная городская парковка. Двор без знака оплаты обычно бесплатный. Карта и оплата: https://parking.mos.ru/",
            "На улицах платная городская парковка; двор без знака оплаты обычно бесплатный.",
        )
    return (
        PARKING_MIXED,
        "Двор обычно бесплатный. На ближайших улицах может быть «Московский паркинг» — смотрите знаки. Карта и оплата: https://parking.mos.ru/",
        "Двор обычно бесплатный; на улице возможна платная зона — смотрите знаки.",
    )


CHECKIN = """Заезд с 14:00, самостоятельно.

1. Дойдите до подъезда по адресу и видео «как пройти».
2. Код домофона и код ключницы менеджер присылает в чате бронирования в день заезда.
3. Наберите код ключницы ровными цифрами, потяните ручку вниз, возьмите ключи, откройте квартиру.
4. Как заселитесь — напишите в чат.

Ключи после выезда верните в ключницу кольцом вниз и перетасуйте цифры."""

CHECKIN_HOUR_BY_SLUG = {
    "voyazh": "15:00",
    "mondrian": "15:00",
    "simfoniya": "15:00",
    "ekvator": "15:00",
    "olimp": "15:00",
    "everest": "15:00",
}


def checkin_hour(slug: str) -> str:
    return CHECKIN_HOUR_BY_SLUG.get(slug, "14:00")


def apply_checkin_hour(a: dict) -> None:
    hour = checkin_hour(a["slug"])
    if hour == "14:00":
        return
    a["checkin"] = (a.get("checkin") or "").replace("Заезд с 14:00", f"Заезд с {hour}")
    a["rules"] = (a.get("rules") or "").replace("Заезд с 14:00", f"Заезд с {hour}")
    next_faq = []
    for item in a.get("faq") or []:
        copied = dict(item)
        ans = copied.get("a") or ""
        if "Заезд с 14:00" in ans:
            copied["a"] = ans.replace("Заезд с 14:00", f"Заезд с {hour}")
        next_faq.append(copied)
    a["faq"] = next_faq


CHECKOUT = """Выезд до 12:00.

• Закройте дверь на ключ.
• Верните ключи в ключницу (код тот же, что при заселении), перетасуйте цифры.
• Ключи кладите кольцом вниз.
• Вынесите мусор.
• Напишите в чат, что выехали.

Ждём вас снова!"""

WIFI_HELP = """Если интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00)."""

WIFI_GENERIC = f"""Сеть и пароль Wi‑Fi для этой квартиры появятся в инструкции, как только менеджер внесёт их в таблицу.

{WIFI_HELP}"""

WIFI_TABLE: dict[str, dict] = {}
_wifi_path = ROOT / "data" / "wifi.json"
if _wifi_path.exists():
    _raw = json.loads(_wifi_path.read_text(encoding="utf-8"))
    rows = _raw if isinstance(_raw, list) else _raw.get("apartments") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("slug"):
            WIFI_TABLE[str(row["slug"])] = row
        name = str(row.get("name") or "").strip()
        if name:
            WIFI_TABLE[norm_name(name)] = row


def format_wifi_networks(networks: list) -> str:
    lines: list[str] = []
    for n in networks:
        ssid = str(n.get("ssid") or "").strip()
        password = str(n.get("password") or "").strip()
        if not ssid and not password:
            continue
        if ssid:
            lines.append(f"Сеть: {ssid}")
        if password:
            lines.append(f"Пароль: {password}")
        lines.append("")
    lines.append(WIFI_HELP)
    return "\n".join(lines).strip()


def apply_wifi(a: dict) -> None:
    key = norm_name(a["name"])
    extra = {"бауманская": "чехов"}
    row = (
        WIFI_TABLE.get(a["slug"])
        or WIFI_TABLE.get(key)
        or WIFI_TABLE.get(norm_name(SITE_ALIASES.get(key, "")))
        or WIFI_TABLE.get(norm_name(extra.get(key, "")))
    )
    if not row:
        return
    networks = row.get("networks")
    if not networks:
        ssid = str(row.get("ssid") or "").strip()
        password = str(row.get("password") or "").strip()
        networks = [{"ssid": ssid, "password": password}] if (ssid or password) else []
    if networks:
        a["wifi"] = format_wifi_networks(networks)


def apply_shared_videos(a: dict) -> None:
    if a.get("skipVideos"):
        return
    if not SHARED_COFFEE or not a.get("ready"):
        return
    blob = _nfc_low(" ".join(f"{v.get('title', '')} {v.get('name', '')}" for v in a.get("videos") or []))
    if "кофемаш" in blob or "кофевар" in blob:
        return
    a["videos"] = list(a.get("videos") or []) + [SHARED_COFFEE]
    if not any("кофемаш" in _nfc_low(item.get("q") or "") for item in a.get("faq") or []):
        a["faq"] = list(a.get("faq") or []) + [{**COFFEE_FAQ, "video": SHARED_COFFEE["url"]}]



def videos_for(*needles: str, exclude: tuple[str, ...] = ()) -> list[dict]:
    out = []
    seen = set()
    for v in VIDEOS:
        blob = (v.get("folder", "") + " " + v.get("path", "") + " " + v.get("name", "")).lower()
        if any(n.lower() in blob for n in needles):
            if any(x.lower() in blob for x in exclude):
                continue
            key = v["path"]
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "title": guess_title(v["name"]),
                    "name": v["name"],
                    "url": file_url(v),
                    "path": v["path"],
                    "folderUrl": disk_url(v["folder"]),
                }
            )
    return out


def folder_for(*needles: str) -> str:
    folders: list[str] = []
    for v in VIDEOS:
        blob = v.get("folder", "").lower()
        if any(n.lower() in blob for n in needles):
            folders.append(v["folder"])
    if not folders:
        return ""
    return min(set(folders), key=len)


def lunar_videos(unit: str) -> list[dict]:
    packed = []
    for v in LUNAR_FILES:
        nfc = unicodedata.normalize("NFC", v["name"]).lower()
        numbered_229 = "229" in nfc
        numbered_261 = "261" in nfc
        numbered_262 = "262" in nfc
        if numbered_229 and unit != "229":
            continue
        if (numbered_261 or numbered_262) and not numbered_229:
            if unit == "229":
                continue
            if unit == "261" and not numbered_261:
                continue
            if unit == "262" and not numbered_262:
                continue
        packed.append(
            {
                "title": guess_title(v["name"]),
                "name": v["name"],
                "url": f"{LUNAR_PUBLIC}?path={quote(v['path'])}",
                "path": v["path"],
                "folderUrl": LUNAR_PUBLIC,
                "disk": "lunar",
            }
        )
    def rank(item: dict) -> tuple:
        nfc = unicodedata.normalize("NFC", item["name"]).lower()
        amenity = "коворкинг" in nfc or "спортзал" in nfc
        entrance = ("подъезд" in nfc or "найти" in nfc) or ("пройти" in nfc and not amenity)
        return (
            0 if entrance else 1,
            0 if amenity else 1,
            0 if "штор" in nfc else 1,
            item["name"],
        )

    packed.sort(key=rank)
    return packed


def salaryevo_videos() -> list[dict]:
    packed = []
    for v in SALARYEVO_FILES:
        low = unicodedata.normalize("NFC", v["name"]).lower()
        if not low.endswith((".mp4", ".mov", ".m4v", ".webm")):
            continue
        packed.append(
            {
                "title": guess_title(v["name"]),
                "name": v["name"],
                "url": f"{SALARYEVO_PUBLIC}?path={quote(v['path'])}",
                "path": v["path"],
                "folderUrl": SALARYEVO_PUBLIC,
                "disk": "salaryevo",
            }
        )

    def rank(item: dict) -> tuple:
        nfc = unicodedata.normalize("NFC", item["name"]).lower()
        return (
            0 if "кофемаш" in nfc or "кофевар" in nfc else 1,
            0 if "плит" in nfc or "варочн" in nfc else 1,
            item["title"],
        )

    packed.sort(key=rank)
    return packed


def _clip_title(filename: str) -> str:
    stem = unicodedata.normalize("NFC", filename).rsplit(".", 1)[0].strip()
    low = stem.lower()
    if low.startswith(("как ", "куда ")):
        return stem[0].upper() + stem[1:] if stem else guess_title(filename)
    return guess_title(filename)


def matiss_videos() -> list[dict]:
    packed = []
    for v in MATISS_FILES:
        packed.append(
            {
                "title": _clip_title(v["name"]),
                "name": v["name"],
                "url": f"{MATISS_PUBLIC}?path={quote(v['path'])}",
                "path": v["path"],
                "folderUrl": MATISS_PUBLIC,
                "disk": "matiss",
            }
        )

    def rank(item: dict) -> tuple:
        nfc = unicodedata.normalize("NFC", item["name"]).lower()
        return (
            0 if "мусор" in nfc else 1,
            0 if "бойлер" in nfc else 1,
            0 if "плит" in nfc or "индукц" in nfc else 1,
            0 if "вытяж" in nfc else 1,
            0 if "стирал" in nfc else 1,
            0 if "телевиз" in nfc else 1,
            0 if "полотенц" in nfc else 1,
            0 if "подсвет" in nfc else 1,
            item["title"],
        )

    packed.sort(key=rank)
    return packed


def _object_videos(files: list[dict], public_key: str, disk: str) -> list[dict]:
    packed = []
    for v in files:
        packed.append(
            {
                "title": _clip_title(v["name"]),
                "name": v["name"],
                "url": f"{public_key}?path={quote(v['path'])}",
                "path": v["path"],
                "folderUrl": public_key,
                "disk": disk,
            }
        )

    def rank(item: dict) -> tuple:
        nfc = unicodedata.normalize("NFC", item["name"]).lower()
        return (
            0 if "квартир" in nfc and "видео" in nfc else 1,
            0 if "мусор" in nfc else 1,
            0 if "бойлер" in nfc else 1,
            0 if "плит" in nfc or "индукц" in nfc else 1,
            0 if "вытяж" in nfc else 1,
            0 if "стирал" in nfc else 1,
            0 if "телевиз" in nfc else 1,
            0 if "полотенц" in nfc else 1,
            0 if "подсвет" in nfc else 1,
            item["title"],
        )

    packed.sort(key=rank)
    return packed


def homlin_videos() -> list[dict]:
    return _object_videos(HOMLIN_FILES, HOMLIN_PUBLIC, "homlin")


def artmen_videos() -> list[dict]:
    return _object_videos(ARTMEN_FILES, ARTMEN_PUBLIC, "artmen")


def voyazh_videos() -> list[dict]:
    return _object_videos(VOYAZH_FILES, VOYAZH_PUBLIC, "voyazh")


def briz_videos() -> list[dict]:
    return _object_videos(BRIZ_FILES, BRIZ_PUBLIC, "briz")


def ferrari_videos() -> list[dict]:
    return _object_videos(FERRARI_FILES, FERRARI_PUBLIC, "ferrari")


def _video_dedupe_keys(v: dict) -> list[str]:
    keys: list[str] = []
    title = re.sub(r"\s+", " ", _nfc_low(v.get("title") or "")).strip()
    if title:
        keys.append("t:" + title)
    name = v.get("name") or ""
    stem = unicodedata.normalize("NFC", name).rsplit(".", 1)[0]
    stem = re.sub(r"\s+", " ", stem).strip().lower()
    if stem:
        keys.append("n:" + stem)
    guessed = re.sub(r"\s+", " ", _nfc_low(guess_title(name))).strip()
    if guessed:
        keys.append("t:" + guessed)
    return keys


def dedupe_videos(vids: list[dict]) -> list[dict]:
    """Keep first clip when title or filename stem already appeared (Ferrari overlap with main disk)."""
    seen: set[str] = set()
    out: list[dict] = []
    for v in vids:
        keys = _video_dedupe_keys(v)
        if any(k in seen for k in keys):
            continue
        for k in keys:
            seen.add(k)
        out.append(v)
    return out


OLIMP_TRASH = {
    "title": "Куда выносить мусор",
    "name": "мусорные баки где находятся.MP4",
    "url": "https://disk.yandex.ru/i/Awg5CaySAoLHdw",
    "path": "/Видео материал /мята/мусорные баки где находятся.MP4",
    "folderUrl": "https://disk.yandex.ru/d/ZLKt8eDXJYKdnQ?path=%2F%D0%92%D0%B8%D0%B4%D0%B5%D0%BE%20%D0%BC%D0%B0%D1%82%D0%B5%D1%80%D0%B8%D0%B0%D0%BB%20%20%2F%D0%BC%D1%8F%D1%82%D0%B0",
}


LUNAR_ADDRESS = "Москва, Ленинский проспект, д. 38А, ЖК LUNAR"
LUNAR_METRO = "5 минут пешком от м. Ленинский проспект"
LUNAR_COORDS = "55.7064, 37.5820"
LUNAR_DISTRICT = """ЖК LUNAR на первой линии Ленинского проспекта, 5 минут пешком от метро «Ленинский проспект».
В комплексе коворкинг и спортзал — как пройти, смотрите видео во вкладке «Видео пользования техникой и не только».
Рядом Воробьёвы горы, набережная Москвы-реки, МГУ, магазины и кафе на первых этажах."""
LUNAR_PETS_FAQ = [
    {
        "q": "Можно ли с собакой или кошкой в Лунаре?",
        "a": "Да. С животными можно, доплата 500 ₽ в сутки. Напишите персональному менеджеру заранее, что едете с питомцем.",
    }
]


def apt(
    slug: str,
    name: str,
    *,
    area: str,
    address: str,
    metro: str = "",
    coords: str = "",
    wifi: str = "",
    how: str = "",
    district: str = "",
    review: str = "",
    needles: tuple[str, ...] = (),
    extra_faq: list | None = None,
    extra_videos: list | None = None,
    exclude_videos: tuple[str, ...] = (),
    checkin: str = "",
    ready: bool = True,
    disk_public: str = "",
    pin_address: bool = False,
    skip_videos: bool = False,
) -> dict:
    vids = videos_for(*needles, exclude=exclude_videos) if needles else []
    if extra_videos:
        vids = extra_videos + vids
    vids = dedupe_videos(vids)
    folder = folder_for(*needles) if needles else ""
    faq = list(UNIVERSAL_FAQ)
    if extra_faq:
        faq = extra_faq + faq
    guest_disk = disk_public or (disk_url(folder) if folder else PUBLIC)
    return {
        "slug": slug,
        "name": name,
        "area": area,
        "address": address,
        "metro": metro,
        "coords": coords,
        "ready": ready,
        "wifi": wifi or WIFI_GENERIC,
        "how": how
        or f"Адрес: {address}."
        + (f"\nОриентир: {metro}." if metro else "")
        + (f"\nКоординаты: {coords}" if coords else "")
        + "\nМаршрут удобно строить в Яндекс.Навигаторе или Google Maps. Видео «как пройти» — в папке на Диске, если оно снято.",
        "parking": "",
        "parkingHint": "",
        "checkin": checkin or CHECKIN,
        "rules": RULES,
        "checkout": CHECKOUT,
        "district": district
        or f"Рядом с домом обычно есть магазин у дома, аптека и остановки. Точечный список кафе и магазинов смотрите в папке объекта на Диске и уточняйте у менеджера.",
        "review": review
        or "После выезда будем благодарны за отзыв на Яндекс.Картах по карточке этой квартиры. Ссылку на отзыв может прислать менеджер.",
        "contacts": (
            f"Ваш персональный менеджер: {CONTACT_PHONE}\n"
            f"На связи с {CONTACT_HOURS}. Напишите в Telegram или позвоните.\n"
            f"Сайт: {CONTACT_SITE}\nКомпания {COMPANY}."
        ),
        "diskUrl": guest_disk,
        "diskFolder": folder,
        "videos": vids,
        "faq": faq,
        "pinAddress": pin_address,
        "skipVideos": skip_videos,
    }


def lunar_apt(*, slug: str, name: str, unit: str, floor: str, curtains: bool = False) -> dict:
    how = f"""Адрес: {LUNAR_ADDRESS} (Гагаринский район).

Ориентир: около 5 минут пешком от метро «Ленинский проспект», рядом МЦК «Площадь Гагарина».

Подъезд в доме один — видео «как пройти к подъезду» общее для Дюма, Твена и Диккенса.

Ваша квартира «{name}» — № {unit}, {floor}.
Как дойти до коворкинга и спортзала — отдельное видео во вкладке «Видео пользования техникой и не только» (как только файл лежит на Диске объекта).

Маршрут удобно строить в навигаторе по адресу. Координаты: {LUNAR_COORDS}."""
    checkin = f"""Заезд с 14:00, самостоятельно.

1. Дойдите до ЖК LUNAR, Ленинский проспект, 38А. Подъезд один — видео во вкладке «Путь».
2. Код домофона и доступ в день заезда приходят в чате бронирования. Есть видео про видеодомофон и ключ от домофона.
3. {floor}, квартира № {unit}, слоган «{name}».
4. Как заселитесь — напишите в чат.

С животными можно: 500 ₽ в сутки, предупредите нас заранее."""
    extra = list(LUNAR_PETS_FAQ)
    extra.append(
        {
            "q": "Где коворкинг и спортзал?",
            "a": "В комплексе ЖК LUNAR. Подъезд один на все три квартиры. Видео «как пройти в коворкинг и спортзал» — во вкладке «Видео пользования техникой и не только», когда ролик загружен на Диск.",
        }
    )
    if curtains:
        extra.append(
            {
                "q": "Где пульт электроштор?",
                "a": "В квартире «Диккенс» (229) электрошторы управляются пультом. Короткое видео — во вкладке «Видео пользования техникой и не только».",
            }
        )
    return apt(
        slug,
        name,
        area="Гагаринский",
        address=LUNAR_ADDRESS,
        metro=LUNAR_METRO,
        coords=LUNAR_COORDS,
        extra_videos=lunar_videos(unit),
        disk_public=LUNAR_PUBLIC,
        how=how,
        checkin=checkin,
        extra_faq=extra,
        district=LUNAR_DISTRICT,
    )


SALARYEVO_ADDRESS = "Москва, ул. Трёхполье, д. 6к1, подъезд 8, 1 этаж"
SALARYEVO_METRO = "Саларьево · 10–15 минут пешком"
SALARYEVO_COORDS = "55.612634, 37.414149"
SALARYEVO_DISTRICT = """Саларьево, Новомосковский округ. Дом на ул. Трёхполье, 6к1.

До метро «Саларьево» около 10–15 минут пешком. Рядом ТЦ «Саларис», магазины, кафе и остановки.

Квартиры «Шир» и «Лориэн» в одном подъезде: видео и бытовая техника одинаковые."""


def salaryevo_apt(*, slug: str, name: str) -> dict:
    how = f"""Адрес: {SALARYEVO_ADDRESS}.

Ориентир: метро «Саларьево», 10–15 минут пешком. Координаты: {SALARYEVO_COORDS}.

Подъезд 8, первый этаж. Квартиры «Шир» и «Лориэн» стоят рядом — инструкции и видео одни и те же.

Ваша квартира — «{name}». Маршрут удобно строить в навигаторе по адресу."""
    checkin = f"""Заезд с 14:00, самостоятельно.

1. Дойдите до ул. Трёхполье, д. 6к1, подъезд 8.
2. Код домофона и код ключницы приходят в чате бронирования в день заезда.
3. 1 этаж, квартира «{name}».
4. Наберите код ключницы ровными цифрами, потяните ручку вниз, возьмите ключи, откройте квартиру.
5. Как заселитесь — напишите в чат.

Ключи после выезда верните в ключницу кольцом вниз и перетасуйте цифры."""
    extra = [
        {
            "q": "Шир и Лориэн — это разные инструкции?",
            "a": "Нет. Две квартиры в одном подъезде, 8-й подъезд, 1 этаж. Видео техники и тексты одинаковые, отличается только слоган в ссылке.",
        }
    ]
    return apt(
        slug,
        name,
        area="Саларьево",
        address=SALARYEVO_ADDRESS,
        metro=SALARYEVO_METRO,
        coords=SALARYEVO_COORDS,
        extra_videos=salaryevo_videos(),
        disk_public=SALARYEVO_PUBLIC,
        how=how,
        checkin=checkin,
        extra_faq=extra,
        district=SALARYEVO_DISTRICT,
    )


APARTMENTS = [
    apt(
        "ferrari",
        "Феррари",
        area="Коммунарка",
        address="Москва, ул. Фитарёвская, д. 6, ЖК «Аквилон Парк»",
        metro="5 минут на транспорте до метро, ~1,3 км от ст. Коммунарка",
        how="""Адрес: Москва, ул. Фитарёвская, д. 6, ЖК «Аквилон Парк», Коммунарка.

Студия «Феррари» — яркая квартира с кондиционером, посудомойкой и рабочим местом, до 4 гостей (двуспальная кровать + диван-кровать).

Проложите маршрут в навигаторе по адресу или названию ЖК «Аквилон Парк». Около дома — магазины, кафе, аптека, детские и спортивные площадки.

Видео о квартире, телевизоре, мусоре и размещении троих гостей — по ссылке на Яндекс.Диске.""",
        district="""Коммунарка: около 20 минут на машине до аэропорта Внуково.
Рядом Липовый парк, детские площадки во дворе ЖК, магазины и кафе.
Медицина: ММКЦ «Коммунарка», медцентр «Ступеньки».
Спорт: Арена Плэй Юг, фитнес Escalada.""",
        needles=("Ferrari",),
        extra_videos=ferrari_videos(),
        disk_public=FERRARI_PUBLIC,
        extra_faq=[
            {
                "q": "Где лежит дополнительное бельё?",
                "a": "Дополнительное бельё есть в квартире — смотрите видео «Для троих гостей» на Диске. Комплект, который сушится для следующих гостей, использовать нельзя.",
            }
        ],
    ),
    apt(
        "matiss",
        "Матисс",
        area="Коммунарка",
        address="Москва, ул. Василия Ощепкова, д. 6, подъезд 5, этаж 4, кв. 632, ЖК «Москвичка»",
        metro="7 минут пешком от м. Новомосковская (Троицкая линия)",
        coords="55.554725, 37.466977",
        wifi="Сеть: ELTEX - 19C8\nПароль: GP21232106\n\nРоутер в квартире над входной дверью. Если интернет не работает — перезагрузите роутер. Не помогло — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="""Адрес: г. Москва, ул. Василия Ощепкова, д. 6, подъезд 5, этаж 4, квартира 632, ЖК «Москвичка».

Координаты: 55.554725, 37.466977 — вставьте в навигатор или откройте карту в этой инструкции.

От м. Новомосковская (Троицкая линия) около 7 минут пешком.""",
        checkin="""Заезд с 14:00.

1. Код домофона: «632», два гудка — дверь откроется.
2. 4 этаж, квартира 632.
3. Возле двери ключница. Код ключницы приходит в чате бронирования. Цифры ровные, затем потяните ручку вниз.
4. Возьмите ключи и откройте квартиру.
5. Как заселитесь — напишите в чат.""",
        district="""Всего 20 минут на машине до Внуково, 4 станции метро до автовокзала «Саларис».
В доме: «ВкусВилл», «Верный» 24 часа, кафе, фитнес, закрытый двор.
ММКЦ Коммунарка: ул. Сосенский Стан, 8, стр. 3.
Прогулки: площадь Туве Янссон, квартал 165.""",
        needles=("матис",),
        extra_videos=matiss_videos(),
        disk_public=MATISS_PUBLIC,
    ),
    apt("artledi", "Артледи", area="Москва", address="Москва, объект «Артледи» — точный подъезд и квартиру менеджер пришлёт в чате", needles=("артледи",)),
    apt("chaplin", "Чаплин", area="Москва", address="Москва, объект «Чаплин» — адрес и подъезд в чате бронирования", needles=("чаплин",)),
    apt("rosso", "Россо", area="Москва", address="Москва, объект «Россо» (ориентир: подъезды 7–8, переход через двор)", needles=("россо",)),
    apt("montblanc", "Монблан", area="Москва", address="Москва, объект «Монблан»", needles=("монблан",)),
    apt("dzen", "Дзен", area="Москва", address="Москва, объект «Дзен» (тамбур, ключница, проходные выключатели)", needles=("дзен",)),
    apt(
        "briz",
        "Бриз",
        area="Москва",
        address="Москва, объект «Бриз»",
        needles=("бриз",),
        extra_videos=briz_videos(),
        disk_public=BRIZ_PUBLIC,
    ),
    apt("belyaevo", "Беляево", area="Беляево", address="Москва, район Беляево, объект «Беляево»", metro="м. Беляево", needles=("беляево",)),
    apt("kotelniki", "Котельники", area="Котельники", address="Московская область / Москва, Котельники", metro="м. Котельники", needles=("Котельники",)),
    apt("paramount", "Парамаунт", area="Котельники", address="Котельники, объект «Парамаунт»",         needles=("парамаунт",)),
    apt("universal", "Юниверсал", area="Котельники", address="Котельники, объект «Юниверсал»", needles=("юниверсал",)),
    apt("dega", "Дега", area="Одинцово", address="Одинцово, объект «Дега»", needles=("дега",)),
    apt("kandinsky", "Кандинский", area="Одинцово", address="Одинцово, объект «Кандинский»", needles=("кндинский", "кандин")),
    apt("chekhov", "Чехов", area="Бауманская", address="Москва, район Бауманской, объект «Чехов»", metro="м. Бауманская", needles=("Чехов",)),
    apt(
        "vershiny",
        "Снежные пики",
        area="Москва",
        address="Москва, ул. Лобановский лес, д. 13, подъезд 8, этаж 4, кв. 851",
        wifi="Сеть: Keenetic -1168\nПароль: 8jRErYad\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="""Адрес: Москва, ул. Лобановский лес, д. 13, подъезд 8, этаж 4, квартира 851.

От м. Прокшино около 10 минут пешком. Маршрут — кнопка «Маршрут» в этой инструкции.""",
        needles=("вершины", "снежные пики", "снежныепики"),
        exclude_videos=("ключ для уборки",),
        pin_address=True,
    ),
    apt(
        "voyazh",
        "Вояж",
        area="Москва",
        address="Москва, объект «Вояж»",
        needles=("вояж",),
        extra_videos=voyazh_videos(),
        disk_public=VOYAZH_PUBLIC,
    ),
    apt(
        "olimp",
        "Олимп",
        area="Москва",
        address="Москва, объект «Олимп»",
        needles=("олимп",),
        extra_videos=[OLIMP_TRASH],
    ),
    apt("myata", "Мята", area="Москва", address="Москва, объект «Мята»", needles=("мята",), exclude_videos=("штор",)),
    apt(
        "saga",
        "Сага",
        area="Одинцово",
        address="г. Одинцово, ул. Северная, д. 9, подъезд 2, 2 этаж, кв. 213, студия 4, ЖК «Одинбург»",
        wifi="Сеть: 213\nПароль: 89057486464\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Одинцово, ул. Северная, д. 9, подъезд 2, 2 этаж, кв. 213, студия 4, ЖК «Одинбург».\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt("scandi", "Скандинавия", area="Москва", address="Москва, объект «Скандинавия» (бойлер — видео включения и отключения)", needles=("сканадинавия", "сканди")),
    apt("forest", "Форест", area="Москва", address="Москва, объект «Форест» (на объекте особенность с гигиеническим душем — смотрите памятку)", needles=("форест",)),
    apt("sapfir", "Сапфир", area="Москва", address="Москва, объект «Сапфир»", needles=("сапфир",)),
    apt(
        "homlin",
        "Хомлин",
        area="Москва",
        address="Москва, объект «Хомлин»",
        needles=("хомлин",),
        extra_videos=homlin_videos(),
        disk_public=HOMLIN_PUBLIC,
    ),
    apt("shambala", "Шамбала", area="Москва", address="Москва, объект «Шамбала»", needles=("шамбала",)),
    apt("talisman", "Талисман", area="Москва", address="Москва, объект «Талисман»", needles=("талисман",)),
    apt("rim", "Рим", area="Москва", address="Москва, объект «Рим»", needles=("рим",)),
    apt("romans", "Романс", area="Москва", address="Москва, объект «Романс»", needles=("романс",)),
    apt("nuar", "Нуар", area="Москва", address="Москва, объект «Нуар»", needles=("нуар",)),
    apt("gizelle", "Жизель", area="Москва", address="Москва, объект «Жизель»", needles=("жизель",)),
    apt("idalgo", "Идальго", area="Москва", address="Москва, объект «Идальго»", needles=("идальго",)),
    apt("karma", "Карма", area="Москва", address="Москва, объект «Карма»", needles=("карма",)),
    apt(
        "artmen",
        "Артмен",
        area="Москва",
        address="Москва, объект «Артмен» (посудомойка и микроволновка — отдельные видео в папке)",
        needles=("артмен",),
        extra_videos=artmen_videos(),
        disk_public=ARTMEN_PUBLIC,
    ),
    apt("white", "Вайт", area="Москва", address="Москва, объект «Вайт»", needles=("вайт",)),
    apt("soyka", "Сойка", area="Москва", address="Москва, объект «Сойка» (электронный замок — видео)", needles=("сойка",)),
    apt("everest", "Эверест", area="Москва", address="Москва, объект «Эверест»", needles=("эверест",)),
    apt(
        "med",
        "Мёд",
        area="Заречье",
        address="Одинцовский г.о., пос. Заречье, ул. Медовая, д. 1, подъезд 2, 1 этаж, кв. 39, студия 3",
        wifi="Сеть: TP-Link_8420_5G\nПароль: 72363324\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: Одинцовский г.о., пос. Заречье, ул. Медовая, д. 1, подъезд 2, 1 этаж, кв. 39, студия 3.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "pero",
        "Перо",
        area="Заречье",
        address="Одинцовский г.о., пос. Заречье, ул. Медовая, д. 1, подъезд 2, 1 этаж, кв. 39, студия 1",
        wifi="Сеть: TP-Link_8420_5G\nПароль: 72363324\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: Одинцовский г.о., пос. Заречье, ул. Медовая, д. 1, подъезд 2, 1 этаж, кв. 39, студия 1.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "rubin",
        "Рубин",
        area="Москва",
        address="г. Москва, ул. 1-я Магистральная, д. 25, подъезд единственный, этаж 12, кв. 264, студия 3",
        wifi="Сеть: MGTS_GPON5_vFv9\nПароль: XHbM6Gy2\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Москва, ул. 1-я Магистральная, д. 25, подъезд единственный, этаж 12, кв. 264, студия 3.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "sandal",
        "Сандал",
        area="Москва",
        address="г. Москва, ул. 1-я Магистральная, д. 25, подъезд единственный, этаж 12, кв. 264, студия 2",
        wifi="Сеть: MGTS_GPON5_vFv9\nПароль: XHbM6Gy2\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Москва, ул. 1-я Магистральная, д. 25, подъезд единственный, этаж 12, кв. 264, студия 2.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "sunlight",
        "Санлайт",
        area="Москва",
        address="г. Москва, ул. Профсоюзная, д. 110, к. 3, подъезд 8, 1 этаж, кв. 141, студия 3",
        wifi="Сеть: Zyxel_141_sun\nПароль: 2208128755\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Москва, ул. Профсоюзная, д. 110, к. 3, подъезд 8, 1 этаж, кв. 141, студия 3.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "simfoniya",
        "Симфония",
        area="Москва",
        address="г. Москва, ул. Липовый парк, д. 2, подъезд 5, 9 этаж, кв. 243",
        wifi="Пароль: 89183852111\nНазвание сети на роутере, если оно не подписано — спросите менеджера.\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Москва, ул. Липовый парк, д. 2, подъезд 5, 9 этаж, кв. 243.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "city",
        "Сити",
        area="Москва",
        address="г. Москва, ул. Лазурная, д. 9, подъезд 3, 1 этаж, кв. 96",
        wifi="Сеть: Dir-842-0AC1.5G\nПароль: 69538674\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Москва, ул. Лазурная, д. 9, подъезд 3, 1 этаж, кв. 96.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "freya",
        "Фрейя",
        area="Одинцово",
        address="г. Одинцово, ул. Северная, д. 9, подъезд 2, 2 этаж, кв. 213, студия 1, ЖК «Одинбург»",
        wifi="Сеть: 213\nПароль: 89057486464\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Одинцово, ул. Северная, д. 9, подъезд 2, 2 этаж, кв. 213, студия 1, ЖК «Одинбург».\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "shalyapin",
        "Шаляпин",
        area="Москва",
        address="г. Москва, Балакиревский переулок, д. 23, 1 этаж, кв. 102, студия 2",
        wifi="Сеть: MGTS_GPON_cSS6\nПароль: EfknKg7R\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Москва, Балакиревский переулок, д. 23, 1 этаж, кв. 102, студия 2.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "ellida",
        "Эллида",
        area="Одинцово",
        address="г. Одинцово, ул. Северная, д. 9, подъезд 2, 2 этаж, кв. 213, студия 2, ЖК «Одинбург»",
        wifi="Сеть: 213\nПароль: 89057486464\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Одинцово, ул. Северная, д. 9, подъезд 2, 2 этаж, кв. 213, студия 2, ЖК «Одинбург».\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "elbrus",
        "Эльбрус",
        area="Москва",
        address="г. Москва, проезд Стройкомбината, д. 1, подъезд 2, этаж 33, кв. 1092, студия 1",
        wifi="Сеть: home24\nПароль: home24home24\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Москва, проезд Стройкомбината, д. 1, подъезд 2, этаж 33, кв. 1092, студия 1.\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "enigma",
        "Энигма",
        area="Одинцово",
        address="г. Одинцово, ул. Северная, д. 9, подъезд 2, 2 этаж, кв. 213, студия 3, ЖК «Одинбург»",
        wifi="Сеть: 213\nПароль: 89057486464\n\nЕсли интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно в квартире у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00).",
        how="Адрес: г. Одинцово, ул. Северная, д. 9, подъезд 2, 2 этаж, кв. 213, студия 3, ЖК «Одинбург».\n\nМаршрут — кнопка «Маршрут» в этой инструкции.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "siesta",
        "Сиеста",
        area="Москва",
        address="Адрес менеджер пришлёт в чате бронирования.",
        how="Адрес и подъезд придут в чате бронирования. Остальное — в этой инструкции: Wi‑Fi, правила, FAQ.",
        pin_address=True,
        skip_videos=True,
    ),
    apt(
        "ekvator",
        "Экватор",
        area="Москва",
        address="Адрес менеджер пришлёт в чате бронирования.",
        how="Адрес и подъезд придут в чате бронирования. Остальное — в этой инструкции: Wi‑Fi, правила, FAQ.",
        pin_address=True,
        skip_videos=True,
    ),
    lunar_apt(slug="dyuma", name="Дюма", unit="261", floor="6 этаж"),
    lunar_apt(slug="tven", name="Твен", unit="262", floor="6 этаж"),
    lunar_apt(slug="dickens", name="Диккенс", unit="229", floor="5 этаж", curtains=True),
    salaryevo_apt(slug="shir", name="Шир"),
    salaryevo_apt(slug="lorien", name="Лориэн"),
]

def slugify(name: str) -> str:
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya", " ": "-",
    }
    out = []
    for ch in name.lower():
        out.append(table.get(ch, ch if ch.isalnum() else "-"))
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug or "object"


# Pad remaining slots with other published Home24 apartments (real street addresses).
SKIP_PAD_NAMES = {
    "каштан",
    "одинцово",
    "вп",
    "бульваррокоссовского",
    "севанская",
    "бауманская",
    "заречье",
    "снежныепики",
    "северная",
    "сиеста",
    "экватор",
}
existing = {a["slug"] for a in APARTMENTS}
used_names = {norm_name(a["name"]) for a in APARTMENTS}
used_names.add("снежныепики")
used_names.add("северная")
used_names.add("сиеста")
used_names.add("экватор")
for row in SITE_ROWS:
    if len(APARTMENTS) >= CATALOG_SIZE:
        break
    title_key = norm_name(row["title"])
    if title_key in used_names or title_key in SKIP_PAD_NAMES:
        continue
    slug = slugify(row["title"])
    if slug in existing:
        continue
    area = row["address"].split(",")[0].strip()
    APARTMENTS.append(
        apt(
            slug,
            row["title"],
            area=area,
            address=row["address"],
            metro=row.get("metro") or "",
            coords=row.get("coords") or "",
            ready=True,
        )
    )
    existing.add(slug)
    used_names.add(title_key)

APARTMENTS = APARTMENTS[:CATALOG_SIZE]
for a in APARTMENTS:
    apply_site_address(a)
    apply_wifi(a)
    apply_site_videos(a)
    apply_shared_videos(a)
    a["videos"] = dedupe_videos(list(a.get("videos") or []))
    park_text, park_faq, park_hint = parking_pack(a.get("address") or "", a["slug"], a.get("area") or "")
    a["parking"] = park_text
    a["parkingHint"] = park_hint
    a["faq"] = [{"q": "Платная ли парковка?", "a": park_faq}, *[x for x in a.get("faq") or [] if x.get("q") != "Платная ли парковка?"]]
    apply_checkin_hour(a)
    a.pop("pinAddress", None)
    a.pop("skipVideos", None)

maps_path = ROOT / "data" / "yandex-maps.json"
MAPS_BY_SLUG: dict[str, dict] = {}
if maps_path.exists():
    MAPS_BY_SLUG = {r["slug"]: r for r in json.loads(maps_path.read_text(encoding="utf-8"))}

for a in APARTMENTS:
    m = MAPS_BY_SLUG.get(a["slug"]) or {}
    url = (m.get("mapsOrgUrl") or "").strip()
    if url:
        a["mapsOrgUrl"] = url
        a["review"] = (
            "После выезда будем благодарны за отзыв на Яндекс.Картах по карточке этой квартиры.\n\n"
            f"{url}\n"
            f"{url.rstrip('/')}/reviews/"
        )
    else:
        a.pop("mapsOrgUrl", None)
        a["review"] = (
            a.get("review")
            or "После выезда будем благодарны за отзыв на Яндекс.Картах. Ссылку на карточку пришлёт менеджер, если её ещё нет в каталоге."
        )
base = "https://89-111-184-212.sslip.io"
for i, a in enumerate(APARTMENTS, 1):
    a["id"] = i
    a["guestMessage"] = (
        f"Здравствуйте! Квартира «{a['name']}».\n"
        f"\n"
        f"Инструкция: {base}/g/{a['slug']}\n"
        f"\n"
        f"Адрес: {a['address']}\n"
        f"Заезд с {checkin_hour(a['slug'])}, выезд до 12:00.\n"
        f"{a.get('parkingHint') or ''}\n"
        f"\n"
        f"Менеджер: {CONTACT_PHONE}"
    ).replace("\n\n\n", "\n\n")

out = {
    "company": COMPANY,
    "phone": CONTACT_PHONE,
    "site": CONTACT_SITE,
    "yandexPublic": PUBLIC,
    "apartments": APARTMENTS,
}
dest = ROOT / "data" / "apartments.json"
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("apartments", len(APARTMENTS), "with videos", sum(1 for a in APARTMENTS if a["videos"]))
print("with coffee", sum(1 for a in APARTMENTS if any("кофемаш" in _nfc_low(v.get("title", "") + v.get("name", "")) for v in a["videos"])))
print("with site tour", sum(1 for a in APARTMENTS if any(v.get("disk") == "home24" for v in a["videos"])))
print("yandex videos", sum(len([v for v in a["videos"] if v.get("disk") != "home24"]) for a in APARTMENTS))
print("with coords", sum(1 for a in APARTMENTS if a["coords"]))
print("wrote", dest)

lines = [
    "Home24 — ссылки на инструкции для гостей",
    "Открывать в браузере. MAX и VPN не нужны.",
    base,
    "",
]
for a in APARTMENTS:
    lines.append(f"{a['id']}. {a['name']}")
    lines.append(f"{base}/g/{a['slug']}")
    if a["videos"]:
        lines.append(f"Видео: {base}/g/{a['slug']}/video  ({len(a['videos'])} шт.)")
    if a.get("mapsOrgUrl"):
        lines.append(f"Яндекс.Карты: {a['mapsOrgUrl']}")
    lines.append(a["address"])
    lines.append("")
(ROOT / "public" / "guest-links.txt").write_text("\n".join(lines), encoding="utf-8")
print("wrote guest-links", len(APARTMENTS))
