# -*- coding: utf-8 -*-
"""Выгрузить настоящие переписки бота с гостями — для разбора и новых образцов.

    python scripts/export_dialogs.py                 # последние 14 дней
    python scripts/export_dialogs.py --days 30 --min-guest 2

Создаёт data/real_dialogs.md: каждый чат — «Гость / Бот / Менеджер» по порядку.
Номера телефонов в тексте заменяются на +7•••, имя гостя остаётся.
Бота можно не останавливать: база открывается только на чтение.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE = {"guest": "Гость", "user": "Гость", "bot": "Бот", "manager": "Менеджер", "admin": "Менеджер"}
_PHONE_RE = re.compile(r"(\+?[78][\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2})")


def db_path() -> Path:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    p = Path(os.getenv("DATABASE_PATH") or "data/home24.db")
    p = p if p.is_absolute() else ROOT / p
    return p / "home24.db" if p.is_dir() else p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--min-guest", type=int, default=2, help="минимум реплик гостя в чате")
    ap.add_argument("--out", default="data/real_dialogs.md")
    ap.add_argument("--db")
    args = ap.parse_args()
    path = Path(args.db) if args.db else db_path()
    if not path.exists():
        print(f"База не найдена: {path}")
        return 2
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    since = time.time() - args.days * 86400
    rows = con.execute(
        "SELECT chat_id, role, text, sender_label, created_at FROM messages "
        "WHERE created_at >= ? ORDER BY chat_id, created_at, id",
        (since,),
    ).fetchall()
    names = {
        str(r["chat_id"]): r["name"]
        for r in con.execute("SELECT chat_id, name FROM sessions").fetchall()
    }
    chats: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        chats.setdefault(str(r["chat_id"]), []).append(r)
    out = [f"# Переписки бота за {args.days} дн. (выгружено {time.strftime('%d.%m.%Y %H:%M')})", ""]
    kept = 0
    for chat_id, msgs in chats.items():
        if sum(1 for m in msgs if m["role"] in ("guest", "user")) < args.min_guest:
            continue
        kept += 1
        first = time.strftime("%d.%m %H:%M", time.localtime(msgs[0]["created_at"]))
        out.append(f"## {kept}. {names.get(chat_id) or 'Гость'} · {first}")
        for m in msgs:
            who = ROLE.get(m["role"], m["role"])
            if m["sender_label"] and who != "Гость":
                who = f"{who} ({m['sender_label']})"
            text = _PHONE_RE.sub("+7•••", (m["text"] or "").strip()).replace("\n", " / ")
            out.append(f"- **{who}:** {text}")
        out.append("")
    dest = Path(args.out)
    dest = dest if dest.is_absolute() else ROOT / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"Чатов: {kept}. Файл: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
