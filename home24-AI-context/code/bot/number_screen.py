# -*- coding: utf-8 -*-
"""Файл с номерами: кто есть в Telegram, кого нет, и на какой день очередь."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from bot.outreach_jobs import parse_outreach_lines

_SKIP = {"@bdoxa"}
_OWN_PHONES = {"[REDACTED]"}
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def moscow_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def is_number_file(name: str) -> bool:
    n = (name or "").lower().strip()
    return n.endswith((".csv", ".txt", ".tsv", ".xlsx"))


def _skip_key(phone: str) -> bool:
    [REDACTED] or "").strip().lower()
    if key in _SKIP or key in {p.lower() for p in _OWN_PHONES}:
        return True
    digits = re.sub(r"\D", "", key)
    if digits in {"[REDACTED]", "[REDACTED]"}:
        return True
    return False


def pairs_from_text(text: str) -> tuple[list[dict[str, str]], int]:
    rows = parse_outreach_lines(text.replace(";", "\n").replace("\t", "\n"))
    if not rows and "," in text:
        reader = csv.reader(io.StringIO(text))
        lines = []
        for row in reader:
            if not row:
                continue
            phone = (row[0] or "").strip()
            name = (row[1] if len(row) > 1 else "").strip()
            if phone:
                lines.append(f"{phone}, {name}" if name else phone)
        rows = parse_outreach_lines("\n".join(lines))
    out = []
    seen: set[str] = set()
    dropped = 0
    for row in rows:
        phone = row["phone"]
        if _skip_key(phone):
            dropped += 1
            continue
        if phone.lower() in seen:
            continue
        seen.add(phone.lower())
        out.append(row)
    return out, dropped


def _xlsx_text(data: bytes) -> str:
    lines: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ElementTree.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
        sheets = sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet"))
        if not sheets:
            return ""
        root = ElementTree.fromstring(zf.read(sheets[0]))
        for row in root.findall("m:sheetData/m:row", _NS):
            cells: list[str] = []
            for cell in row.findall("m:c", _NS):
                kind = cell.get("t") or ""
                value = cell.find("m:v", _NS)
                raw = value.text if value is not None and value.text else ""
                if kind == "s" and raw.isdigit():
                    idx = int(raw)
                    raw = shared[idx] if idx < len(shared) else ""
                inline = cell.find("m:is", _NS)
                if inline is not None:
                    raw = "".join(t.text or "" for t in inline.iter("{%s}t" % _NS["m"]))
                cells.append(raw.strip())
            if any(cells):
                lines.append(", ".join(cells))
    return "\n".join(lines)


def pairs_from_file(data: bytes, filename: str) -> list[dict[str, str]]:
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        text = _xlsx_text(data)
    else:
        text = data.decode("utf-8-sig", errors="replace")
    return pairs_from_text(text)


def take_day(load: dict[str, int], *, daily: int, start: date) -> str:
    """Ближайший день, где ещё есть место в дневном лимите."""
    day = start
    for _ in range(400):
        [REDACTED]
        if int(load.get(key) or 0) < daily:
            load[key] = int(load.get(key) or 0) + 1
            return key
        day += timedelta(days=1)
    return day.isoformat()


def format_report(stats: dict[str, Any]) -> str:
    days = stats.get("days") or {}
    lines = [
        "Файл проверен. Никому не писал.",
        f"В Telegram: {stats.get('in_tg', 0)}",
        f"Нет в Telegram: {stats.get('missing', 0)}",
        f"Свои и служебные: {stats.get('skipped_own', 0)}",
        f"Уже писали или стоп: {stats.get('already', 0)}",
    ]
    if days:
        lines.append(f"По дням, лимит {stats.get('daily', 0)}:")
        for day in sorted(days):
            shown = datetime.fromisoformat(day).strftime("%d.%m")
            lines.append(f"{shown} — {days[day]}")
    if stats.get("stopped_early"):
        lines.append("Остановился раньше: лимит Telegram, хвост файла не трогал.")
    return "\n".join(lines)


async def screen_pairs(
    pairs: list[dict[str, str]],
    *,
    store: Any,
    checker: Any,
    daily: int,
    manager_id: str,
    account_id: str = "",
    sent_today: int = 0,
    pause: Any = None,
    progress: Any = None,
) -> dict[str, Any]:
    """checker(phone, name) -> (user_id | None, status). pause() между живыми запросами."""
    load = store.day_load()
    today = moscow_today().isoformat()
    load[today] = int(load.get(today) or 0) + max(0, int(sent_today))
    days: dict[str, int] = {}
    missing: list[str] = []
    in_tg = already = 0
    stopped_early = False
    total = len(pairs)
    for index, row in enumerate(pairs, start=1):
        if progress and index % 25 == 0:
            await progress(index, total)
        phone = row["phone"]
        name = row.get("name") or ""
        known = store.contact_by_phone(phone)
        if known and (known.get("status") == "stopped"):
            already += 1
            continue
        if known and known.get("tg_status") == "нет в Telegram":
            missing.append(phone)
            continue
        try:
            uid, status = await checker(phone, name)
        except Exception as e:
            name_e = type(e).__name__
            if "PeerFlood" in name_e:
                stopped_early = True
                break
            if "FloodWait" not in name_e:
                raise
            seconds = int(getattr(e, "seconds", 0) or 30)
            if pause:
                await pause(seconds + 1)
            uid, status = await checker(phone, name)
        if not uid or status == "нет в Telegram":
            store.reject_not_telegram(phone, name=name, manager_id=manager_id)
            missing.append(phone)
            continue
        if known and known.get("status") == "pending":
            old = (known.get("send_on") or "").strip() or today
            if load.get(old, 0) > 0:
                load[old] -= 1
        day = take_day(load, daily=max(1, int(daily)), start=moscow_today())
        placed = store.schedule_contact(
            phone,
            name=name,
            send_on=day,
            manager_id=manager_id,
            telegram_user_id=str(uid),
            tg_status=status or "ok",
            tg_account_id=account_id,
        )
        if placed == "scheduled":
            in_tg += 1
            days[day] = days.get(day, 0) + 1
        else:
            already += 1
    return {
        "in_tg": in_tg,
        "missing": len(missing),
        "missing_phones": missing,
        "already": already,
        "skipped_own": 0,
        "days": days,
        "daily": daily,
        "stopped_early": stopped_early,
    }
