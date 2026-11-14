# -*- coding: utf-8 -*-
"""Стереть историю бота с одним гостем и вернуть его в очередь рассылки.

Запуск (бот должен быть ОСТАНОВЛЕН — закройте окно run_windows.bat / start.bat):

    python scripts/reset_contact.py [REDACTED]
    python scripts/reset_contact.py [REDACTED] --yes      # без вопроса «точно?»

Что делает:
  1. Копия базы: data/home24.db.bak_reset_<время>
  2. Удаляет переписку бота (messages), состояние диалога (sessions), очередь входящих
  3. Снимает стоп-лист по номеру и чату
  4. Ставит контакт в статус pending — следующая рассылка напишет ему первое письмо заново

Переписку в самом Telegram скрипт не трогает (её удаляют в приложении, если нужно).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def norm_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return "+" + digits


def variants(phone: str) -> list[str]:
    d = phone.lstrip("+")
    out = {phone, d}
    if d.startswith("7") and len(d) == 11:
        out.add("8" + d[1:])
    return sorted(out)


def db_path() -> Path:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    p = Path(os.getenv("DATABASE_PATH") or "data/home24.db")
    if not p.is_absolute():
        p = ROOT / p
    if p.is_dir():
        p = p / "home24.db"
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phone", help="номер гостя, например [REDACTED]")
    ap.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    ap.add_argument("--db", help="путь к базе (по умолчанию из .env / data/home24.db)")
    args = ap.parse_args()

    path = Path(args.db) if args.db else db_path()
    if not path.exists():
        print(f"База не найдена: {path}")
        return 2
    phone = norm_phone(args.phone)
    keys = variants(phone)

    con = sqlite3.connect(str(path), timeout=5)
    con.row_factory = sqlite3.Row
    marks = ",".join("?" * len(keys))
    contacts = con.execute(f"SELECT * FROM contacts WHERE phone IN ({marks})", keys).fetchall()
    chat_ids = {str(r["chat_id"]) for r in contacts if str(r["chat_id"] or "").strip()}
    cols = {r[1] for r in con.execute("PRAGMA table_info(contacts)").fetchall()}
    if "telegram_user_id" in cols:
        chat_ids |= {str(r["telegram_user_id"]) for r in contacts if str(r["telegram_user_id"] or "").strip()}

    if not contacts:
        print(f"Контакт {phone} в базе не найден. Добавьте его: в Telegram боту /add {phone} Имя")
        return 1

    cm = ",".join("?" * len(chat_ids)) or "''"
    n_msgs = con.execute(f"SELECT COUNT(*) FROM messages WHERE chat_id IN ({cm})", list(chat_ids)).fetchone()[0]
    print(f"Контакт: {phone}")
    for r in contacts:
        print(f"  статус {r['status']}, менеджер {r['manager_id'] or '—'}, имя {r['name'] or '—'}, чат {r['chat_id'] or '—'}")
    print(f"  сообщений в истории бота: {n_msgs}")
    if not args.yes and input("Стереть историю и поставить в очередь рассылки? [да/нет] ").strip().lower() not in ("да", "д", "y", "yes"):
        print("Отменено.")
        return 0

    backup = path.with_name(f"{path.name}.bak_reset_{time.strftime('%Y%m%d_%H%M%S')}")
    con.close()
    shutil.copy2(path, backup)
    con = sqlite3.connect(str(path), timeout=5)

    with con:
        if chat_ids:
            ids = list(chat_ids)
            con.execute(f"DELETE FROM messages WHERE chat_id IN ({cm})", ids)
            con.execute(f"DELETE FROM sessions WHERE chat_id IN ({cm})", ids)
            con.execute(f"DELETE FROM inbound_queue WHERE chat_id IN ({cm})", ids)
            con.execute(
                f"DELETE FROM global_stops WHERE key IN ({cm})", [f"chat:{c}" for c in ids]
            )
        con.execute(
            f"DELETE FROM global_stops WHERE key IN ({marks})", [f"phone:{k}" for k in keys]
        )
        extra = ", send_on=''" if "send_on" in cols else ""
        extra += ", tg_status=''" if "tg_status" in cols else ""
        con.execute(
            f"UPDATE contacts SET status='pending', last_error=''{extra}, updated_at=? "
            f"WHERE phone IN ({marks})",
            [time.time(), *keys],
        )
    con.close()
    print(f"Готово. Копия базы до изменений: {backup}")
    print("Запустите бота и начните рассылку: в Telegram команда /send, затем /send go (или кнопка в панели).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
