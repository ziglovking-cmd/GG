"""Idempotently restore past exports into an existing chat; never replace live rows."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import time


def prepare(chat_id: int, paths: list[Path]) -> dict:
    by_id = {}
    files = []
    for path in paths:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=";,\t")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if "user_id" not in (reader.fieldnames or []):
            raise ValueError("CSV must contain real Telegram user_id")
        rows = list(reader)
        files.append({"name": path.name, "rows": len(rows),
                      "sha256": hashlib.sha256(raw).hexdigest()})
        for row in rows:
            user_id = int(row["user_id"])
            if user_id <= 0:
                raise ValueError("Restore requires positive Telegram IDs")
            old = by_id.get(user_id, {})
            combined = dict(row, user_id=user_id)
            combined["msg_count"] = max(int(old.get("msg_count") or 0), int(row.get("msg_count") or 0))
            combined["sources"] = ",".join(sorted(set(filter(None,
                str(old.get("sources") or "").split(",") + str(row.get("sources") or "").split(",")))))
            by_id[user_id] = combined
    return {"chat_id": int(chat_id), "files": files, "rows": list(by_id.values())}


def merge(payload: dict, database: Path, backup_dir: Path) -> dict:
    chat_id = int(payload["chat_id"])
    incoming = {int(r["user_id"]) for r in payload["rows"]}
    if any(uid <= 0 for uid in incoming):
        raise ValueError("Only real Telegram IDs can be restored")
    os.umask(0o077)
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect("file:" + str(database) + "?mode=rw", uri=True, timeout=30)
    backup_path = backup_dir / ("app-before-csv-merge-%d.db" % time.time_ns())
    backup = sqlite3.connect(backup_path)
    try:
        conn.backup(backup)
    finally:
        backup.close()
    now = int(time.time())
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM chats WHERE id=?", (chat_id,)).fetchone() is None:
            raise ValueError("Target chat does not exist; refusing to create a different base")
        before = {r[0] for r in conn.execute("SELECT user_id FROM members WHERE chat_id=?", (chat_id,))}
        rows = []
        for r in payload["rows"]:
            boolean = lambda key: int(str(r.get(key) or "").lower() in {"1", "true", "yes"})
            rows.append((chat_id, int(r["user_id"]), r.get("username") or None,
                         r.get("first_name") or None, r.get("last_name") or None,
                         r.get("phone") or None, boolean("is_bot"), boolean("is_deleted"),
                         boolean("is_premium"), r.get("last_seen") or "",
                         max(0, int(r.get("msg_count") or 0)), r.get("sources") or "csv_restore", now))
        conn.executemany(
            "INSERT INTO members (chat_id,user_id,username,first_name,last_name,phone,"
            "is_bot,is_deleted,is_premium,last_seen,msg_count,sources,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO NOTHING", rows)
        after = {r[0] for r in conn.execute("SELECT user_id FROM members WHERE chat_id=?", (chat_id,))}
        if after != before | incoming:
            raise RuntimeError("Restoration did not preserve the exact union of Telegram IDs")
        conn.execute("UPDATE chats SET members_count=? WHERE id=?", (len(after), chat_id))
        conn.execute("INSERT INTO events(ts,scope,message) VALUES (?,?,?)", (now, "import",
            "Восстановлена накопительная база чата %d из %d CSV: добавлено %d, всего %d"
            % (chat_id, len(payload.get("files", [])), len(after - before), len(after))))
        conn.commit()
        check = conn.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError("SQLite quick_check: " + str(check))
        result = {"chat_id": chat_id, "before": len(before), "csv_unique_ids": len(incoming),
                  "added": len(after - before), "after": len(after), "missing_csv_ids": len(incoming - after),
                  "removed_live_ids": len(before - after), "quick_check": check,
                  "backup": str(backup_path), "files": payload.get("files", [])}
        (backup_dir / "csv-merge-summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", nargs="+", type=Path)
    parser.add_argument("--chat-id", type=int)
    parser.add_argument("--apply", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    if args.prepare:
        if args.chat_id is None:
            parser.error("--chat-id required")
        json.dump(prepare(args.chat_id, args.prepare), sys.stdout, ensure_ascii=False)
    elif args.apply and args.backup_dir:
        print(json.dumps(merge(json.load(sys.stdin), args.apply, args.backup_dir), ensure_ascii=False))
    else:
        parser.error("Use --prepare ... --chat-id ID or --apply DB --backup-dir DIR")
