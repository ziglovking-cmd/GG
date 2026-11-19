#!/usr/bin/env python3
"""Pull official addresses + coordinates from home24.msk.ru Travelline sync."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://home24.msk.ru/api/travelline/sync-state"


def loc(fields: dict, key: str) -> str:
    v = fields.get(key)
    if isinstance(v, dict):
        return str(v.get("local") or "").strip()
    return str(v or "").strip()


def clean_address(raw: str) -> str:
    s = raw.strip()
    s = s.replace("ул. ул.", "ул. ")
    s = re.sub(r",\s*,", ", ", s)
    s = s.replace("1я магистарльная", "1-я Магистральная")
    s = s.replace("1я магистральная", "1-я Магистральная")
    s = s.replace("ул. Севанская улица", "ул. Севанская")
    s = s.replace("ул. Василия Ощепкова дом 3", "ул. Василия Ощепкова, д. 3")
    s = s.replace("д. 1/2", "д. 1 к. 2")
    return s


def score(row: dict) -> int:
    n = 0
    if row["coords"]:
        n += 10
        n += min(len(row["coords"]), 24)
    if "Тверская" in row["address"]:
        n -= 40
    if row["title"].lower().startswith("парковка"):
        n -= 100
    return n


def main() -> None:
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-1023"},
    )
    last_err: Exception | None = None
    data = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if data is None:
        raise RuntimeError(f"cannot fetch {URL}: {last_err}")
    cards = data["state"]["cards"]
    by_title: dict[str, list[dict]] = {}
    for c in cards:
        f = c["fields"]
        title = loc(f, "title")
        if not title or title.lower().startswith("парковка"):
            continue
        blob = loc(f, "addressCoordinates")
        address, coords = blob, ""
        if "·" in blob:
            address, coords = [p.strip() for p in blob.split("·", 1)]
        row = {
            "title": title,
            "address": clean_address(address),
            "coords": coords.replace(",", ", ") if "," in coords and ", " not in coords else coords,
            "metro": loc(f, "metroWalk"),
            "specs": loc(f, "specs"),
            "status": c.get("status"),
        }
        by_title.setdefault(title, []).append(row)
    rows = [max(group, key=score) for group in by_title.values()]
    rows.sort(key=lambda r: r["title"])
    dest = ROOT / "data" / "home24-site.json"
    dest.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", dest, "objects", len(rows))


if __name__ == "__main__":
    main()
