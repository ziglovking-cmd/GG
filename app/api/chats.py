from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import db, parsing
from app.api.schemas import CsvImportIn, ParseAllIn, ParseIn


router = APIRouter()


@router.post("/api/parse")
async def start_parse(body: ParseIn):
    job_id = parsing.new_job("parse", body.chat)
    asyncio.create_task(parsing.run_parse(
        job_id, body.account_id, body.chat, body.sources, body.deep,
        body.participants_limit, body.messages_limit, body.posts_limit))
    return {"job_id": job_id}


@router.post("/api/parse/all")
async def start_parse_all(body: ParseAllIn):
    account_ids = body.account_ids or [
        r["id"] for r in db.q(
            "SELECT id FROM accounts WHERE status='authorized' AND can_parse=1 ORDER BY id")
    ]
    if not account_ids:
        raise HTTPException(400, "Нет авторизованных аккаунтов с правом парсинга")
    job_id = parsing.new_job("parse-all", "%s — всеми аккаунтами" % body.chat)
    asyncio.create_task(parsing.run_parse_all(
        job_id, account_ids, body.chat, body.sources, body.deep,
        body.participants_limit, body.messages_limit, body.posts_limit, body.gap))
    return {"job_id": job_id, "accounts": len(account_ids)}


@router.get("/api/jobs")
def jobs():
    rows = []
    for job in sorted(parsing.JOBS.values(), key=lambda j: j["started_at"], reverse=True)[:20]:
        item = dict(job)
        sub = parsing.JOBS.get(job.get("current_sub") or "")
        if sub:
            item["added"] = job.get("added", 0) + sub.get("added", 0)
            item["found"] = item["added"]
            item["total"] = sub.get("total", job.get("total", 0))
        rows.append(item)
    return rows


@router.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str):
    if not parsing.request_stop(job_id):
        raise HTTPException(404, "Задача не найдена")
    return {"ok": True}


@router.get("/api/chats")
def chats():
    rows = db.rows_to_dicts(db.q("SELECT * FROM chats ORDER BY COALESCE(last_parsed_at,0) DESC"))
    for r in rows:
        r["parsed"] = db.q1("SELECT COUNT(*) c FROM members WHERE chat_id=?", (r["id"],))["c"]
    return rows


def _csv_bool(value: Any) -> int:
    return 1 if str(value or "").strip().lower() in {"1", "true", "yes", "да"} else 0


def _csv_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").strip()
        return int(text) if "." not in text else int(float(text))
    except (TypeError, ValueError):
        return default


@router.post("/api/members/import")
def import_members(body: CsvImportIn):
    raw = body.csv_text.lstrip("\ufeff")
    if not raw.strip():
        raise HTTPException(400, "CSV-файл пуст")
    if len(raw.encode("utf-8")) > 10 * 1024 * 1024:
        raise HTTPException(400, "CSV-файл больше 10 МБ")

    sample = raw[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t,")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(400, "Не найдена строка с заголовками")

    aliases = {
        "user_id": {"user_id", "id", "telegram_id", "telegram id"},
        "username": {"username", "user_name", "login", "юзернейм"},
        "first_name": {"first_name", "first name", "name", "имя"},
        "last_name": {"last_name", "last name", "surname", "фамилия"},
        "phone": {"phone", "telephone", "телефон"},
        "is_bot": {"is_bot", "bot"},
        "is_deleted": {"is_deleted", "deleted"},
        "is_premium": {"is_premium", "premium"},
        "last_seen": {"last_seen", "last seen"},
        "msg_count": {"msg_count", "messages", "message_count", "сообщений"},
        "sources": {"sources", "source", "источник"},
    }
    normalized = {str(h).strip().lower(): h for h in reader.fieldnames if h is not None}
    columns = {
        key: next((normalized[a] for a in names if a in normalized), None)
        for key, names in aliases.items()
    }
    if not columns["user_id"] and not columns["username"]:
        raise HTTPException(400, "Нужен столбец user_id или username")

    min_row = db.q1("SELECT MIN(id) value FROM chats")
    minimum = int(min_row["value"] or 0)
    chat_id = minimum - 1 if minimum <= -1 else -1
    title = (body.name or "Импорт CSV").strip()[:120] or "Импорт CSV"
    now = int(time.time())

    rows_by_id: Dict[int, tuple] = {}
    skipped = 0
    for index, row in enumerate(reader, start=2):
        if index > 100002:
            raise HTTPException(400, "В одном файле допускается не более 100 000 строк")
        username = str(row.get(columns["username"], "") or "").strip()
        username = username.removeprefix("@").split("?")[0].rstrip("/")
        if "/" in username:
            username = username.rsplit("/", 1)[-1]
        user_id = _csv_int(row.get(columns["user_id"])) if columns["user_id"] else 0
        if not user_id and username:
            digest = hashlib.sha256(username.lower().encode("utf-8")).digest()
            synthetic = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
            user_id = -(synthetic or 1)
        if not user_id or (not username and user_id < 0):
            skipped += 1
            continue

        def value(key: str) -> str:
            column = columns.get(key)
            return str(row.get(column, "") or "").strip() if column else ""

        rows_by_id[user_id] = (
            chat_id, user_id, username or None, value("first_name") or None,
            value("last_name") or None, value("phone") or None,
            _csv_bool(value("is_bot")), _csv_bool(value("is_deleted")),
            _csv_bool(value("is_premium")), value("last_seen") or None,
            max(0, _csv_int(value("msg_count"))), value("sources") or "csv", now,
        )

    if not rows_by_id:
        raise HTTPException(400, "Не найдено ни одной строки с user_id или username")

    db.ex(
        "INSERT INTO chats (id,title,kind,members_count,last_parsed_at) VALUES (?,?,?,?,?)",
        (chat_id, title, "csv", len(rows_by_id), now),
    )
    db.exmany(
        """INSERT INTO members (chat_id,user_id,username,first_name,last_name,phone,
                                is_bot,is_deleted,is_premium,last_seen,msg_count,sources,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        list(rows_by_id.values()),
    )
    db.log("CSV «%s» импортирован: %d записей, пропущено %d" %
           (title, len(rows_by_id), skipped), scope="import")
    return {"chat_id": chat_id, "imported": len(rows_by_id), "skipped": skipped}


@router.get("/api/members")
def members(chat_id: int, limit: int = 200, offset: int = 0, search: str = ''):
    where = ["chat_id=?"]
    params: List[Any] = [chat_id]
    if search:
        where.append("(username LIKE ? OR first_name LIKE ? OR last_name LIKE ?)")
        params += ["%%%s%%" % search] * 3
    clause = " AND ".join(where)
    total = db.q1("SELECT COUNT(*) c FROM members WHERE " + clause, params)["c"]
    rows = db.rows_to_dicts(db.q(
        "SELECT * FROM members WHERE %s ORDER BY msg_count DESC, user_id LIMIT ? OFFSET ?" % clause,
        params + [limit, offset]))
    return {"total": total, "items": rows}


@router.get("/api/members/export")
def export_members(chat_id: int):
    rows = db.q("SELECT * FROM members WHERE chat_id=? ORDER BY msg_count DESC", (chat_id,))
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["user_id", "username", "first_name", "last_name", "phone",
                     "is_bot", "is_deleted", "is_premium", "last_seen", "msg_count", "sources"])
    for r in rows:
        writer.writerow([r["user_id"], r["username"] or "", r["first_name"] or "",
                         r["last_name"] or "", r["phone"] or "", r["is_bot"], r["is_deleted"],
                         r["is_premium"], r["last_seen"] or "", r["msg_count"], r["sources"]])
    buf.seek(0)
    return StreamingResponse(
        iter([("﻿" + buf.getvalue()).encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="members_%s.csv"' % chat_id},
    )


@router.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: int):
    db.ex("DELETE FROM members WHERE chat_id=?", (chat_id,))
    db.ex("DELETE FROM chats WHERE id=?", (chat_id,))
    return {"ok": True}
