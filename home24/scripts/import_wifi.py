#!/usr/bin/env python3
"""Parse the apartment xlsx into data/wifi.json (SSID + password only)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "wifi.json"
CATALOG = ROOT / "data" / "apartments.json"

NAME_ALIASES = {
    "матис": "матисс",
    "дарк": "даркблю",
    "грин": "гринграсс",
    "милк": "милкшейк",
    "снежныевершины": "вершины",
    "снежныепики": "вершины",
    "сага": "сага",
    "каштан": "кандинский",
    "одинцово": "кандинский",
    "севанская": "венера",
    "мята": "олимп",
    "бауманская": "чехов",
    "котельники": "парамаунт",
}


def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", s)


def parse_wifi_blob(text: str) -> list[dict]:
    if not text:
        return []
    t = str(text).replace("\xa0", " ").replace("\r", "\n")
    t = re.sub(r"(?i)wi[\s\-‑]?fi\s*:", "\n", t)
    t = re.sub(
        r"(?i)(?<=\S)(?=(сеть|пароль|логин|имя(?:\s*сети)?|ssid)\s*:)",
        "\n",
        t,
    )
    networks: list[dict] = []
    pending_ssids: list[str] = []

    def flush_password(pw: str) -> None:
        nonlocal pending_ssids
        pw = pw.strip().strip('"').strip()
        ssids = [s for s in pending_ssids if s] or [""]
        pending_ssids = []
        for ssid in ssids:
            networks.append({"ssid": ssid, "password": pw})

    for raw in t.split("\n"):
        line = raw.strip().strip('"').strip()
        if not line:
            continue
        low = line.lower().strip(":")
        if low in {"или", "or", "wifi", "wi-fi", "wi‑fi"}:
            continue
        m = re.match(r"(?i)^(сеть|ssid|логин|имя(?:\s*сети)?)\s*:\s*(.*)$", line)
        if m:
            val = m.group(2).strip()
            if val:
                pending_ssids.extend([x.strip() for x in re.split(r"/\s+", val) if x.strip()])
            continue
        m = re.match(r"(?i)^сеть\s+(?!.*:)(.+)$", line)
        if m:
            pending_ssids.append(m.group(1).strip())
            continue
        m = re.match(r"(?i)^пароль\s*:\s*(.*)$", line)
        if m:
            flush_password(m.group(1))
            continue
        if pending_ssids and not re.search(r"(?i)^\S+\s*:", line):
            pending_ssids.append(line)
    if pending_ssids:
        for ssid in pending_ssids:
            networks.append({"ssid": ssid, "password": ""})
    # drop empty
    return [n for n in networks if n.get("ssid") or n.get("password")]


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "wifi-source.xlsx"
    wb = load_workbook(src, data_only=True)
    ws = wb[wb.sheetnames[0]]
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["apartments"]
    by_name = {norm(a["name"]): a for a in catalog}
    by_slug = {a["slug"]: a for a in catalog}

    items = []
    unmatched = []
    for row in ws.iter_rows(min_row=2, max_col=3, values_only=True):
        name = str(row[1] or "").strip()
        blob = row[2]
        if not name:
            continue
        nets = parse_wifi_blob("" if blob is None else str(blob))
        key = NAME_ALIASES.get(norm(name), norm(name))
        apt = by_name.get(key)
        rec = {"name": name, "networks": nets}
        if apt:
            rec["slug"] = apt["slug"]
        else:
            unmatched.append(name)
        items.append(rec)

    # also index by slug for catalog apply
    payload = {"source": src.name, "apartments": items, "unmatched": unmatched}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with_nets = sum(1 for i in items if i["networks"])
    print("rows", len(items), "with wifi", with_nets, "unmatched", unmatched)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
