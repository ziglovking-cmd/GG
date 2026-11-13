# -*- coding: utf-8 -*-
"""Временный каталог для офлайн-прогонов, когда data/mailing.sqlite нет (адреса из script.md, без цен).

Настоящий каталог не трогается: если data/mailing.sqlite есть, используется он.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CAP = {"вояж": 6, "романс": 4, "матисс": 4, "матис": 4}


def build_test_catalog() -> Path:
    from bot.apartments_map import load_addresses

    path = Path(tempfile.mkdtemp(prefix="home24cat_")) / "mailing.sqlite"
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE objects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, area TEXT, "
        "address TEXT, metro TEXT, coords TEXT, guide_url TEXT, maps_url TEXT, review_url TEXT, wifi_ssid TEXT, "
        "wifi_password TEXT, parking_hint TEXT, checkin TEXT, checkout TEXT, manager_phone TEXT, guest_message TEXT, "
        "how TEXT, price_night INTEGER, capacity INTEGER, photo_url TEXT)"
    )
    for i, (name, place) in enumerate(sorted(load_addresses().items()), 1):
        parts = [p.strip() for p in place.split(",")]
        metro = next((p[3:] for p in parts if p.startswith("м. ")), "")
        area = parts[-2] if len(parts) >= 3 and not parts[-2].startswith("м.") else (metro or "")
        con.execute(
            "INSERT INTO objects (id, slug, name, area, address, metro, checkin, checkout, how, capacity) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (i, f"obj{i}", name.capitalize(), area, ", ".join(parts[:2]), metro, "15:00", "12:00",
             "Квартира посуточно, кофемашина, бесконтактное заселение.", _CAP.get(name, 4)),
        )
    con.commit()
    con.close()
    return path


def use_test_catalog_if_missing() -> str:
    """Подменяет подключение каталога на временный, если настоящего нет. Возвращает пометку для отчёта."""
    import bot.catalog as cat

    if (ROOT / "data" / "mailing.sqlite").exists():
        return "каталог: настоящий"
    test_path = build_test_catalog()
    orig = cat._connect

    def _connect(path=None):  # noqa: ANN001
        return orig(test_path)

    cat._connect = _connect
    return "каталог: тестовый (адреса из script.md, без цен)"
