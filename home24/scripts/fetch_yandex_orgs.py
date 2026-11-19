#!/usr/bin/env python3
"""Find Yandex Maps org cards (объявления) for each Home24 apartment."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "data" / "apartments.json").read_text(encoding="utf-8"))["apartments"]
OUT = ROOT / "data" / "yandex-maps.json"
CACHE = Path("/tmp/org-meta.json")
PROGRESS = Path("/tmp/yandex-orgs2.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}
TABLE = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def fold(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", s)


def lat_name(s: str) -> str:
    out = []
    for ch in (s or "").lower():
        out.append(TABLE.get(ch, ch if ch.isalnum() else ""))
    return "".join(out)


def street_keys(addr: str) -> list[str]:
    a = (addr or "").lower().replace("ё", "е")
    a = re.sub(
        r"\b(г|город|ул|улица|д|дом|к|корп|корпус|стр|строение|кв|квартира|подъезд|этаж|студия|жк|пос|поселок|область)\b",
        " ",
        a,
    )
    toks = re.findall(r"[а-я]{4,}", a)
    skip = {"москва", "одинцово", "котельники", "новомосковский", "административный", "округ"}
    return [t for t in toks if t not in skip]


def house_nums(addr: str) -> set[str]:
    return set(re.findall(r"\d+", addr or ""))


def fetch(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


org_cache: dict = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def org_meta(slug: str, oid: str) -> dict:
    key = f"{slug}/{oid}"
    if key in org_cache and not org_cache[key].get("error"):
        return org_cache[key]
    url = f"https://yandex.ru/maps/org/{slug}/{oid}/"
    try:
        _final, html = fetch(url)
    except Exception as exc:  # noqa: BLE001
        meta = {"error": str(exc), "url": url, "slug": slug, "id": oid}
        org_cache[key] = meta
        return meta
    title = ""
    m = re.search(r'property="og:title" content="([^"]+)"', html)
    if m:
        title = m.group(1)
    addr = ""
    m = re.search(r'"address" content="([^"]+)"', html)
    if m:
        addr = m.group(1)
    if not addr:
        m = re.search(r'"address":"([^"]+)"', html)
        if m:
            addr = m.group(1)
    meta = {
        "url": url,
        "slug": slug,
        "id": oid,
        "title": title,
        "address": addr,
        "closed": "Больше не работает" in html,
        "furniture": "магазин мебели" in html,
        "lodging": any(
            x in html.lower()
            for x in ["жильё посуточно", "жилье посуточно", "гостиница", "апартамент", "квартира"]
        ),
    }
    org_cache[key] = meta
    CACHE.write_text(json.dumps(org_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def parse_orgs(html: str, final: str = "") -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for src in (final, html):
        for m in re.finditer(r"/maps/org/([a-z0-9_]+)/(\d+)/", src):
            slug, oid = m.group(1), m.group(2)
            if oid in seen:
                continue
            seen.add(oid)
            items.append((slug, oid))
    return items


def score(meta: dict, apt: dict) -> int:
    if meta.get("error"):
        return -100
    if meta.get("furniture") or meta.get("closed"):
        return -50
    title = meta.get("title") or ""
    addr = meta.get("address") or ""
    sl = meta.get("slug") or ""
    nf = fold(apt["name"])
    lf = lat_name(apt["name"])
    s = 0
    home = "home24" in sl or "home_24" in sl or "home24" in fold(title) or "номе24" in fold(title)
    if home:
        s += 8
    else:
        s -= 8
    if nf and nf in fold(title):
        s += 20
    if lf and len(lf) >= 4 and lf in sl.replace("_", ""):
        s += 14
    if len(nf) >= 4 and nf[:4] in fold(title):
        s += 6
    hits = sum(1 for t in street_keys(apt.get("address") or "") if t in fold(addr))
    s += 6 * hits
    hn = house_nums(apt.get("address") or "")
    on = house_nums(addr)
    if hn and on and hn & on:
        s += 8
    if meta.get("lodging"):
        s += 3
    if "сочи" in fold(title + addr) and "сочи" not in fold(apt.get("address") or ""):
        s -= 30
    if any(x in fold(addr) for x in ("ставропол", "реутов", "подольск", "люберц")):
        s -= 20
    return s


def search(apt: dict) -> dict:
    name = apt["name"]
    addr = apt.get("address") or ""
    queries = [f"{name} от Home24", f"{name} Home24"]
    street = " ".join(street_keys(addr)[:2])
    if street:
        queries.append(f"Home24 {street}")
    cands: list[dict] = []
    seen: set[str] = set()
    for q in queries:
        params = ""
        if apt.get("coords") and "," in apt["coords"]:
            lat, lon = [x.strip() for x in apt["coords"].split(",", 1)]
            params = f"?ll={lon},{lat}&z=16"
        url = "https://yandex.ru/maps/213/moscow/search/" + urllib.parse.quote(q) + params
        try:
            final, html = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print("search fail", name, exc)
            time.sleep(0.3)
            continue
        for slug, oid in parse_orgs(html, final)[:6]:
            if oid in seen:
                continue
            seen.add(oid)
            # skip obvious non-home24 unless first result
            if "home24" not in slug and "home_24" not in slug and len(cands) > 2:
                continue
            meta = dict(org_meta(slug, oid), query=q)
            meta["score"] = score(meta, apt)
            cands.append(meta)
            time.sleep(0.12)
        time.sleep(0.18)
        if cands and max(c["score"] for c in cands) >= 26:
            break
    cands.sort(key=lambda x: -x["score"])
    best = cands[0] if cands and cands[0]["score"] >= 14 else None
    return {
        "slug": apt["slug"],
        "name": name,
        "address": addr,
        "mapsOrgUrl": best["url"] if best else None,
        "orgTitle": (best or {}).get("title"),
        "orgAddress": (best or {}).get("address"),
        "score": (best or {}).get("score"),
        "top": [{k: c.get(k) for k in ("url", "title", "address", "score")} for c in cands[:4]],
    }


def main() -> None:
    done: dict[str, dict] = {}
    if PROGRESS.exists():
        for row in json.loads(PROGRESS.read_text(encoding="utf-8")):
            done[row["slug"]] = row
    out = []
    for i, apt in enumerate(CATALOG, 1):
        if apt["slug"] in done and (done[apt["slug"]].get("mapsOrgUrl") or done[apt["slug"]].get("scanned")):
            row = done[apt["slug"]]
        else:
            row = search(apt)
            row["scanned"] = True
            done[apt["slug"]] = row
            PROGRESS.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        out.append(row)
        print(f"{i:02d} {apt['name']:18s} {str(row.get('score') or '-'):>4} {row.get('mapsOrgUrl') or 'NONE'}")
    slim = [
        {
            "slug": r["slug"],
            "name": r["name"],
            "mapsOrgUrl": r.get("mapsOrgUrl"),
            "orgTitle": r.get("orgTitle"),
            "orgAddress": r.get("orgAddress"),
        }
        for r in out
    ]
    OUT.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("found", sum(1 for r in slim if r["mapsOrgUrl"]), "/", len(slim), "->", OUT)


if __name__ == "__main__":
    main()
