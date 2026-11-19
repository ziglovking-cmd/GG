#!/usr/bin/env python3
"""Build a compact knowledge DB for an AI mailing bot from apartments.json."""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "apartments.json"
OUT_DIR = ROOT / "data" / "mailing-bot"
BASE = "https://89-111-184-212.sslip.io"


def parse_wifi(text: str) -> list[dict]:
    networks: list[dict] = []
    pending: list[str] = []
    prepared = re.sub(r"(?i)wi[\s\-‑]?fi\s*:", "\n", text or "")
    prepared = re.sub(r"(?i)(?<=\S)(?=(сеть|пароль|логин|ssid)\s*:)", "\n", prepared)

    def flush(pw: str) -> None:
        nonlocal pending
        ssids = pending or [""]
        pending = []
        for ssid in ssids:
            if ssid or pw:
                networks.append({"ssid": ssid, "password": pw})

    for raw in prepared.split("\n"):
        line = raw.strip().strip('"').strip()
        if not line:
            continue
        m = re.match(r"(?i)^(сеть|ssid|логин)\s*:\s*(.*)$", line)
        if m:
            val = m.group(2).strip()
            if val:
                pending.extend([x.strip() for x in re.split(r"/\s+", val) if x.strip()])
            continue
        m = re.match(r"(?i)^пароль\s*:\s*(.*)$", line)
        if m:
            flush(m.group(1).strip())
            continue
    for ssid in pending:
        networks.append({"ssid": ssid, "password": ""})
    return [n for n in networks if n.get("ssid") or n.get("password")]


def checkin_from(a: dict) -> str:
    m = re.search(r"Заезд с (\d{1,2}:\d{2})", a.get("checkin") or a.get("guestMessage") or "")
    hour = m.group(1) if m else "14:00"
    return f"с {hour}"


def rows_from_catalog(payload: dict) -> list[dict]:
    out = []
    for a in payload["apartments"]:
        nets = parse_wifi(a.get("wifi") or "")
        out.append(
            {
                "id": a["id"],
                "slug": a["slug"],
                "name": a["name"],
                "area": a.get("area") or "",
                "address": a.get("address") or "",
                "metro": a.get("metro") or "",
                "coords": a.get("coords") or "",
                "guide_url": f"{BASE}/g/{a['slug']}",
                "maps_url": a.get("mapsOrgUrl") or "",
                "review_url": (a.get("mapsOrgUrl") or "").rstrip("/") + "/reviews/" if a.get("mapsOrgUrl") else "",
                "wifi_ssid": " / ".join(n["ssid"] for n in nets if n.get("ssid")),
                "wifi_password": " / ".join(n["password"] for n in nets if n.get("password")),
                "parking_hint": a.get("parkingHint") or "",
                "checkin": checkin_from(a),
                "checkout": "до 12:00",
                "manager_phone": payload.get("phone") or "+7 977 717-60-97",
                "guest_message": a.get("guestMessage") or "",
                "how": a.get("how") or "",
            }
        )
    return out


TEMPLATES = [
    {
        "key": "checkin",
        "title": "Заезд",
        "body": "Здравствуйте! Квартира «{name}».\n\nИнструкция: {guide_url}\n\nАдрес: {address}\nЗаезд {checkin}, выезд {checkout}.\n{parking_hint}\n\nWi‑Fi: {wifi_ssid}\nПароль: {wifi_password}\n\nКод домофона и ключницы пришлём в день заезда.\nМенеджер: {manager_phone}",
    },
    {
        "key": "wifi",
        "title": "Только Wi‑Fi",
        "body": "Wi‑Fi в «{name}»\nСеть: {wifi_ssid}\nПароль: {wifi_password}\n\nЕсли не ловит — перезагрузите роутер у входной двери. Не ожило — напишите нам.",
    },
    {
        "key": "checkout",
        "title": "Выезд",
        "body": "Напоминаем: выезд из «{name}» до 12:00.\nКлючи в ключницу кольцом вниз, цифры перетасуйте, мусор вынесите, напишите в чат.\nИнструкция: {guide_url}",
    },
    {
        "key": "review",
        "title": "Отзыв",
        "body": "Спасибо, что жили в «{name}»! Будем благодарны за отзыв на Яндекс.Картах:\n{review_url}",
    },
]


def main() -> None:
    payload = json.loads(SRC.read_text(encoding="utf-8"))
    objects = rows_from_catalog(payload)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUT_DIR / "knowledge.json"
    json_path.write_text(
        json.dumps(
            {
                "company": payload.get("company") or "Home24",
                "phone": payload.get("phone"),
                "site": payload.get("site"),
                "guide_origin": BASE,
                "bot": "@GostSill_bot",
                "objects": objects,
                "templates": TEMPLATES,
                "ai_system": (
                    "Ты менеджер Home24. Пишешь короткие сообщения гостю на русском. "
                    "Берёшь только факты из карточки объекта. Не выдумывай коды домофона и ключницы. "
                    "Гостевая ссылка всегда https. Не упоминай горничных и коды уборки."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    csv_path = OUT_DIR / "objects.csv"
    fields = list(objects[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(objects)

    db_path = OUT_DIR / "mailing.sqlite"
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE objects (
          id INTEGER PRIMARY KEY,
          slug TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          area TEXT,
          address TEXT,
          metro TEXT,
          coords TEXT,
          guide_url TEXT,
          maps_url TEXT,
          review_url TEXT,
          wifi_ssid TEXT,
          wifi_password TEXT,
          parking_hint TEXT,
          checkin TEXT,
          checkout TEXT,
          manager_phone TEXT,
          guest_message TEXT,
          how TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE templates (
          key TEXT PRIMARY KEY,
          title TEXT,
          body TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE contacts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          telegram_id INTEGER,
          name TEXT,
          object_slug TEXT,
          checkin_date TEXT,
          checkout_date TEXT,
          note TEXT
        )
        """
    )
    cur.executemany(
        """
        INSERT INTO objects VALUES (
          :id,:slug,:name,:area,:address,:metro,:coords,:guide_url,:maps_url,:review_url,
          :wifi_ssid,:wifi_password,:parking_hint,:checkin,:checkout,:manager_phone,:guest_message,:how
        )
        """,
        objects,
    )
    cur.executemany("INSERT INTO templates(key,title,body) VALUES (:key,:title,:body)", TEMPLATES)
    con.commit()
    con.close()

    md = [f"# Home24 knowledge — {len(objects)} объектов\n"]
    for o in objects:
        md.append(f"## {o['name']} (`{o['slug']}`)")
        md.append(f"- Адрес: {o['address']}")
        if o["metro"]:
            md.append(f"- Метро: {o['metro']}")
        md.append(f"- Инструкция: {o['guide_url']}")
        if o["maps_url"]:
            md.append(f"- Яндекс.Карты: {o['maps_url']}")
        if o["wifi_ssid"]:
            md.append(f"- Wi‑Fi: {o['wifi_ssid']} / {o['wifi_password']}")
        md.append("")
    (OUT_DIR / "knowledge.md").write_text("\n".join(md), encoding="utf-8")
    print("objects", len(objects))
    print("wrote", json_path)
    print("wrote", csv_path)
    print("wrote", db_path)
    print("wrote", OUT_DIR / "knowledge.md")


if __name__ == "__main__":
    main()
