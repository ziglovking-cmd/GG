from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

# не трогаем повторно «sent» без ответа раньше этого окна
OUTREACH_RESEND_COOLDOWN_SEC = 14 * 24 * 3600  # 14 дней
# закрытый чат пропадает из живого списка через 2 дня, из базы — через неделю
HIDE_DONE_SEC = 2 * 86400
PURGE_DONE_SEC = 7 * 86400


def _session_context(row: dict[str, Any]) -> dict[str, Any]:
    ctx = row.get("context")
    if isinstance(ctx, dict):
        return ctx
    raw = row.get("context_json") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def dialog_tone(row: dict[str, Any]) -> str:
    """ready — договорились (срочно), work — в работе, done — закрыт."""
    ctx = _session_context(row)
    step = str(row.get("step") or "")
    closed = bool(
        int(row.get("archived") or 0)
        or step == "done"
        or ctx.get("stopped")
        or ctx.get("closed")
        or ctx.get("finished")
    )
    if closed:
        return "done"
    dates = str(row.get("dates") or "").strip()
    guests = str(row.get("guests") or "").strip()
    place = str(row.get("district") or "").strip() or str(row.get("favorite") or "").strip()
    if dates and guests and place:
        return "ready"
    return "work"


# Порядок важен для панели: сверху срочное, потом то, к чему надо вернуться.
LANES: tuple[tuple[str, str], ...] = (
    ("hot", "Срочно"),
    ("work", "В работе"),
    ("later", "Позже"),
    ("deal", "Сделка"),
    ("lost", "Не вышло"),
    ("issue", "Проблема"),
)
_LANE_ISSUE = frozenset({"pay", "cancel", "trouble", "extend"})
_GAVE_UP_RE = re.compile(
    r"(?i)(не\s*пишите|отпиш|не\s*интерес|не\s*надо|не\s*нужно|"
    r"ошиб(ся|лась)\s*номер|не\s*туда)"
)
_LATER_RE = re.compile(
    r"(?i)(подумаю|подумаем|позже\s*напиш|напишу\s*позже|не\s*сейчас|"
    r"пока\s*не\s*готов|чуть\s*позже|созвон)"
)


def _life_kind(row: dict[str, Any]) -> str:
    ctx = _session_context(row)
    path = str(ctx.get("reply_path") or "")
    if "/life/" in path:
        return path.rsplit("/", 1)[-1].strip().lower()
    guest = str(row.get("last_guest") or "").strip()
    if not guest:
        return ""
    try:
        from bot.life import match_life

        hit = match_life(guest)
    except Exception:
        return ""
    return (hit.kind if hit else "") or ""


def dialog_lane(row: dict[str, Any]) -> str:
    """Категория для смены: позже, сделка, отказ, проблема, срочно, в работе."""
    ctx = _session_context(row)
    kind = _life_kind(row)
    guest = str(row.get("last_guest") or "")
    dates = str(row.get("dates") or "").strip()
    guests = str(row.get("guests") or "").strip()
    place = str(row.get("district") or "").strip() or str(row.get("favorite") or "").strip()
    handed = bool(int(row.get("handed_off") or 0))
    deal = handed and bool(dates and guests and place) and kind not in _LANE_ISSUE
    if kind in _LANE_ISSUE:
        return "issue"
    if kind == "later" or (_LATER_RE.search(guest) and not (dates and guests and place)):
        return "later"
    stopped = bool(ctx.get("stopped") or ctx.get("closed") or ctx.get("finished"))
    step = str(row.get("step") or "")
    if kind == "wrong" or stopped or (step == "done" and not deal):
        return "lost"
    if guest and _GAVE_UP_RE.search(guest) and not deal:
        return "lost"
    if deal:
        return "deal"
    tone = dialog_tone(row)
    if tone == "ready":
        return "hot"
    if tone == "done":
        return "lost"
    return "work"


def empty_lane_census() -> dict[str, int]:
    return {[REDACTED] for key, _label in LANES}


def dialog_brief(row: dict[str, Any]) -> str:
    """Одна строка: даты, гости, район, квартира."""
    bits: list[str] = []
    dates = str(row.get("dates") or "").strip()
    guests = str(row.get("guests") or "").strip()
    district = str(row.get("district") or "").strip()
    favorite = str(row.get("favorite") or "").strip()
    if dates:
        bits.append(dates)
    if guests:
        low = guests.lower()
        if any(ch.isdigit() for ch in guests) and "гост" not in low:
            bits.append(f"{guests} гост.")
        else:
            bits.append(guests)
    if district:
        bits.append(district)
    if favorite and favorite.casefold() != district.casefold():
        bits.append(favorite)
    return " · ".join(bits)


def _moscow_today() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()


class Store:
    def __init__(self, path: str) -> None:
        # Windows-friendly: каталог → файл внутри; :memory: без mkdir
        raw = str(path or "").strip()
        if raw in (":memory:",) or raw.startswith("file:"):
            self._path = raw
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._init()
            return
        p = Path(raw)
        if p.exists() and p.is_dir():
            p = p / "home24.db"
        p.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(p)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        c = self._conn
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contacts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              phone TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL DEFAULT '',
              username TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              chat_id TEXT NOT NULL DEFAULT '',
              last_error TEXT NOT NULL DEFAULT '',
              manager_id TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              chat_id TEXT PRIMARY KEY,
              name TEXT NOT NULL DEFAULT '',
              step TEXT NOT NULL DEFAULT 'greeting',
              dates TEXT NOT NULL DEFAULT '',
              guests TEXT NOT NULL DEFAULT '',
              district TEXT NOT NULL DEFAULT '',
              returning_guest TEXT NOT NULL DEFAULT '',
              favorite TEXT NOT NULL DEFAULT '',
              handed_off INTEGER NOT NULL DEFAULT 0,
              manager_id TEXT NOT NULL DEFAULT '',
              context_json TEXT NOT NULL DEFAULT '{}',
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id TEXT NOT NULL,
              role TEXT NOT NULL,
              text TEXT NOT NULL,
              sender_label TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS global_stops (
              key TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inbound_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id TEXT NOT NULL,
              text TEXT NOT NULL,
              message_id TEXT NOT NULL DEFAULT '',
              manager_id TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              UNIQUE(chat_id, message_id, manager_id)
            );
            """
        )
        # миграции для уже существующих БД
        cols_c = {r[1] for r in c.execute("PRAGMA table_info(contacts)").fetchall()}
        if "manager_id" not in cols_c:
            c.execute(
                "ALTER TABLE contacts ADD COLUMN manager_id TEXT NOT NULL DEFAULT ''"
            )
        cols_s = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
        if "manager_id" not in cols_s:
            c.execute(
                "ALTER TABLE sessions ADD COLUMN manager_id TEXT NOT NULL DEFAULT ''"
            )
            cols_s.add("manager_id")
        for col, decl in (
            ("archived", "INTEGER NOT NULL DEFAULT 0"),
            ("pinned", "INTEGER NOT NULL DEFAULT 0"),
            ("note", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in cols_s:
                c.execute(f"ALTER TABLE sessions ADD COLUMN {col} {decl}")
        cols_m = {r[1] for r in c.execute("PRAGMA table_info(messages)").fetchall()}
        if "sender_label" not in cols_m:
            c.execute(
                "ALTER TABLE messages ADD COLUMN sender_label TEXT NOT NULL DEFAULT ''"
            )
        cols_c = {r[1] for r in c.execute("PRAGMA table_info(contacts)").fetchall()}
        for col, decl in (
            ("telegram_user_id", "TEXT NOT NULL DEFAULT ''"),
            ("tg_status", "TEXT NOT NULL DEFAULT ''"),
            ("tg_account_id", "TEXT NOT NULL DEFAULT ''"),
            ("send_on", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in cols_c:
                c.execute(f"ALTER TABLE contacts ADD COLUMN {col} {decl}")
        c.commit()

    def get_meta(self, [REDACTED] -> str:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE [REDACTED] (key,)
        ).fetchone()
        return row["value"] if row else ""

    def set_meta(self, [REDACTED] value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def claim_meta(self, [REDACTED] value: str = "") -> bool:
        """Один раз на все аккаунты. False, если ключ уже занят."""
        cur = self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO NOTHING",
            (key, value or str(time.time())),
        )
        self._conn.commit()
        return int(cur.rowcount or 0) == 1

    def add_contact(
        self,
        phone: str,
        name: str = "",
        username: str = "",
        *,
        manager_id: str = "",
    ) -> None:
        """Добавить в очередь. stopped/глобальный стоп не сбрасываем; sent — после 14 дней."""
        now = time.time()
        phone_n = phone.strip()
        if self.is_globally_stopped(phone=phone_n):
            self._conn.execute(
                """
                INSERT INTO contacts(phone,name,username,status,manager_id,created_at,updated_at)
                VALUES(?,?,?,'stopped',?,?,?)
                ON CONFLICT(phone) DO UPDATE SET
                  name=CASE WHEN excluded.name!='' THEN excluded.name ELSE contacts.name END,
                  username=CASE WHEN excluded.username!='' THEN excluded.username ELSE contacts.username END,
                  status='stopped',
                  updated_at=excluded.updated_at
                """,
                (phone_n, name, username.lstrip("@"), manager_id or "", now, now),
            )
            self._conn.commit()
            return
        row = self._conn.execute(
            "SELECT status, updated_at, manager_id FROM contacts WHERE phone=?",
            (phone_n,),
        ).fetchone()
        if row:
            st = row["status"]
            if st == "stopped":
                self._conn.execute(
                    """
                    UPDATE contacts SET
                      name=CASE WHEN ?!='' THEN ? ELSE name END,
                      username=CASE WHEN ?!='' THEN ? ELSE username END,
                      updated_at=?
                    WHERE phone=?
                    """,
                    (name, name, username.lstrip("@"), username.lstrip("@"), now, phone_n),
                )
                self._conn.commit()
                return
            if st == "sent" and (now - float(row["updated_at"] or 0)) < OUTREACH_RESEND_COOLDOWN_SEC:
                # глобальный 14-дневный лимит — не возвращаем в pending ни одному менеджеру
                self._conn.execute(
                    """
                    UPDATE contacts SET
                      name=CASE WHEN ?!='' THEN ? ELSE name END,
                      username=CASE WHEN ?!='' THEN ? ELSE username END,
                      updated_at=?
                    WHERE phone=?
                    """,
                    (name, name, username.lstrip("@"), username.lstrip("@"), now, phone_n),
                )
                self._conn.commit()
                return
            # уже закреплён за менеджером — не переназначаем молча
            mid = manager_id or (row["manager_id"] or "")
            self._conn.execute(
                """
                UPDATE contacts SET
                  name=CASE WHEN ?!='' THEN ? ELSE name END,
                  username=CASE WHEN ?!='' THEN ? ELSE username END,
                  status='pending',
                  manager_id=CASE
                    WHEN manager_id!='' THEN manager_id
                    ELSE ?
                  END,
                  last_error='',
                  tg_status=CASE
                    WHEN tg_status='нет в Telegram' THEN ''
                    ELSE tg_status
                  END,
                  telegram_user_id=CASE
                    WHEN tg_status='нет в Telegram' THEN ''
                    ELSE telegram_user_id
                  END,
                  updated_at=?
                WHERE phone=?
                """,
                (
                    name,
                    name,
                    username.lstrip("@"),
                    username.lstrip("@"),
                    mid,
                    now,
                    phone_n,
                ),
            )
            self._conn.commit()
            return
        self._conn.execute(
            """
            INSERT INTO contacts(phone,name,username,status,manager_id,created_at,updated_at)
            VALUES(?,?,?,'pending',?,?,?)
            """,
            (phone_n, name, username.lstrip("@"), manager_id or "", now, now),
        )
        self._conn.commit()

    def list_contacts(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM contacts WHERE status=? ORDER BY id LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM contacts ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def list_outreach_batch(
        self,
        limit: int = 50,
        *,
        manager_id: str | None = None,
        default_manager_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Pending для менеджера: свои + незакреплённые (если это default).

        Чужих клиентов не отдаём — два аккаунта не пишут одному человеку.
        """
        due = "(send_on='' OR send_on IS NULL OR send_on<=?)"
        today = _moscow_today()
        if not manager_id:
            rows = self._conn.execute(
                f"SELECT * FROM contacts WHERE status='pending' AND {due} ORDER BY id LIMIT ?",
                (today, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        if default_manager_id and manager_id == default_manager_id:
            rows = self._conn.execute(
                f"""
                SELECT * FROM contacts
                WHERE status='pending'
                  AND (manager_id=? OR manager_id='' OR manager_id IS NULL)
                  AND {due}
                ORDER BY id LIMIT ?
                """,
                (manager_id, today, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""
                SELECT * FROM contacts
                WHERE status='pending' AND manager_id=? AND {due}
                ORDER BY id LIMIT ?
                """,
                (manager_id, today, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def assign_manager(
        self,
        phone: str,
        manager_id: str,
        *,
        allow_reassign: bool = False,
    ) -> tuple[bool, str]:
        """Закрепить клиента за менеджером. После sent/stopped — нельзя (анти-ротация)."""
        phone_n = phone.strip()
        row = self._conn.execute(
            "SELECT * FROM contacts WHERE phone=?", (phone_n,)
        ).fetchone()
        if not row:
            return False, "контакт не найден"
        st = row["status"]
        cur = (row["manager_id"] or "").strip()
        if st in ("sent", "stopped") and cur and cur != manager_id and not allow_reassign:
            return False, f"нельзя переносить: статус {st}, менеджер {cur}"
        if cur and cur != manager_id and st == "sent" and not allow_reassign:
            return False, "клиенту уже писали с другого аккаунта"
        if (
            cur
            and cur != manager_id
            and not allow_reassign
            and st not in ("pending", "failed", "skipped", "")
        ):
            return False, f"уже закреплён за {cur}"
        # если уже sent тем же — ок обновить имя/id
        now = time.time()
        self._conn.execute(
            "UPDATE contacts SET manager_id=?, updated_at=? WHERE phone=?",
            (manager_id, now, phone_n),
        )
        chat_id = row["chat_id"] or ""
        if chat_id:
            self._conn.execute(
                "UPDATE sessions SET manager_id=? WHERE chat_id=?",
                (manager_id, str(chat_id)),
            )
        self._conn.commit()
        return True, "ok"

    def import_contacts_csv(
        self,
        text: str,
        *,
        default_manager_id: str,
    ) -> dict[str, int]:
        """CSV: phone_or_username,name,manager_id (manager_id опционален)."""
        import csv
        import io

        ok = skip = bad = 0
        reader = csv.reader(io.StringIO(text.strip()))
        for i, row in enumerate(reader):
            if not row or all(not (c or "").strip() for c in row):
                continue
            # header
            if i == 0 and re_header(row):
                continue
            phone = (row[0] if len(row) > 0 else "").strip()
            name = (row[1] if len(row) > 1 else "").strip()
            mid = (row[2] if len(row) > 2 else "").strip() or default_manager_id
            if not phone or phone.lower() in ("phone", "телефон", "username"):
                bad += 1
                continue
            if phone.startswith("@") or phone.startswith("+") or phone[0].isdigit():
                uname = phone if phone.startswith("@") else ""
                self.add_contact(
                    phone=phone.lower() if phone.startswith("@") else phone,
                    name=name,
                    username=uname,
                    manager_id=mid,
                )
                ok += 1
            else:
                bad += 1
        return {"ok": ok, "skip": skip, "bad": bad}

    def contact_manager_id(self, *, phone: str = "", chat_id: str = "") -> str:
        if phone:
            row = self._conn.execute(
                "SELECT manager_id FROM contacts WHERE phone=?", (phone.strip(),)
            ).fetchone()
            if row:
                return (row["manager_id"] or "").strip()
        if chat_id:
            row = self._conn.execute(
                "SELECT manager_id FROM contacts WHERE chat_id=?", (str(chat_id),)
            ).fetchone()
            if row and (row["manager_id"] or "").strip():
                return (row["manager_id"] or "").strip()
            sess = self._conn.execute(
                "SELECT manager_id FROM sessions WHERE chat_id=?", (str(chat_id),)
            ).fetchone()
            if sess:
                return (sess["manager_id"] or "").strip()
        return ""

    def stats_for_manager(self, manager_id: str, *, default_manager_id: str = "") -> dict[str, int]:
        def cnt(q: str, args: tuple = ()) -> int:
            return int(self._conn.execute(q, args).fetchone()[0])

        if default_manager_id and manager_id == default_manager_id:
            pending = cnt(
                """SELECT COUNT(*) FROM contacts WHERE status='pending'
                   AND (manager_id=? OR manager_id='' OR manager_id IS NULL)""",
                (manager_id,),
            )
        else:
            pending = cnt(
                "SELECT COUNT(*) FROM contacts WHERE status='pending' AND manager_id=?",
                (manager_id,),
            )
        return {
            "pending": pending,
            "sent": cnt(
                "SELECT COUNT(*) FROM contacts WHERE status='sent' AND manager_id=?",
                (manager_id,),
            ),
            "failed": cnt(
                "SELECT COUNT(*) FROM contacts WHERE status='failed' AND manager_id=?",
                (manager_id,),
            ),
            "stopped": cnt(
                "SELECT COUNT(*) FROM contacts WHERE status='stopped' AND manager_id=?",
                (manager_id,),
            ),
            "all": cnt(
                "SELECT COUNT(*) FROM contacts WHERE manager_id=?",
                (manager_id,),
            ),
        }

    def add_global_stop(self, *, phone: str = "", chat_id: str = "") -> None:
        now = time.time()
        if phone:
            self._conn.execute(
                "INSERT OR REPLACE INTO global_stops(key,kind,created_at) VALUES(?,?,?)",
                (f"phone:{phone.strip()}", "phone", now),
            )
        if chat_id:
            self._conn.execute(
                "INSERT OR REPLACE INTO global_stops(key,kind,created_at) VALUES(?,?,?)",
                (f"chat:{chat_id}", "chat", now),
            )
        self._conn.commit()

    def is_globally_stopped(self, *, phone: str = "", chat_id: str = "") -> bool:
        if phone:
            row = self._conn.execute(
                "SELECT 1 FROM global_stops WHERE [REDACTED]
                (f"phone:{phone.strip()}",),
            ).fetchone()
            if row:
                return True
        if chat_id:
            row = self._conn.execute(
                "SELECT 1 FROM global_stops WHERE [REDACTED]
                (f"chat:{chat_id}",),
            ).fetchone()
            if row:
                return True
        return False

    def recently_sent_global(self, *, phone: str = "", chat_id: str = "") -> bool:
        """Глобальный 14-дневный лимит повторной первой отправки."""
        now = time.time()
        if phone:
            row = self._conn.execute(
                "SELECT status, updated_at FROM contacts WHERE phone=?",
                (phone.strip(),),
            ).fetchone()
            if (
                row
                and row["status"] == "sent"
                and (now - float(row["updated_at"] or 0)) < OUTREACH_RESEND_COOLDOWN_SEC
            ):
                return True
        if chat_id:
            row = self._conn.execute(
                "SELECT status, updated_at FROM contacts WHERE chat_id=?",
                (str(chat_id),),
            ).fetchone()
            if (
                row
                and row["status"] == "sent"
                and (now - float(row["updated_at"] or 0)) < OUTREACH_RESEND_COOLDOWN_SEC
            ):
                return True
        return False


    def update_contact(self, phone: str, **fields: Any) -> None:
        if not fields:
            return
        if "updated_at" not in fields:
            fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE contacts SET {cols} WHERE phone=?",
            (*fields.values(), phone),
        )
        self._conn.commit()

    def mark_stopped(self, *, phone: str = "", chat_id: str = "") -> None:
        """Глобальный стоп-лист: больше никогда не пишем ни с какого аккаунта."""
        now = time.time()
        self.add_global_stop(phone=phone, chat_id=chat_id)
        if phone:
            self._conn.execute(
                "UPDATE contacts SET status='stopped', last_error='stop-list', updated_at=? WHERE phone=?",
                (now, phone),
            )
        if chat_id:
            self._conn.execute(
                "UPDATE contacts SET status='stopped', last_error='stop-list', updated_at=? WHERE chat_id=?",
                (now, str(chat_id)),
            )
            row = self.get_session(str(chat_id))
            ctx = dict(row.get("context") or {})
            ctx["stopped"] = True
            self.save_session(
                str(chat_id), handed_off=1, step="done", context=ctx
            )
        self._conn.commit()

    def is_stopped_chat(self, chat_id: str) -> bool:
        if self.is_globally_stopped(chat_id=str(chat_id)):
            return True
        row = self._conn.execute(
            "SELECT status FROM contacts WHERE chat_id=?", (str(chat_id),)
        ).fetchone()
        if row and row["status"] == "stopped":
            return True
        sess = self._conn.execute(
            "SELECT context_json FROM sessions WHERE chat_id=?", (str(chat_id),)
        ).fetchone()
        if sess:
            try:
                ctx = json.loads(sess["context_json"] or "{}")
                return bool(ctx.get("stopped"))
            except Exception:
                return False
        return False

    def contact_by_chat(self, chat_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM contacts WHERE chat_id=?", (str(chat_id),)
        ).fetchone()
        return dict(row) if row else None

    def day_load(self) -> dict[str, int]:
        """Сколько pending уже занимает каждый день. Пустой send_on — на сегодня."""
        today = _moscow_today()
        counts: dict[str, int] = {}
        rows = self._conn.execute(
            """
            SELECT COALESCE(send_on, '') AS day, COUNT(*) AS n
            FROM contacts WHERE status='pending'
            GROUP BY COALESCE(send_on, '')
            """
        ).fetchall()
        for row in rows:
            day = (row["day"] or "").strip() or today
            counts[day] = counts.get(day, 0) + int(row["n"])
        return counts

    def schedule_contact(
        self,
        phone: str,
        *,
        name: str = "",
        send_on: str,
        manager_id: str = "",
        telegram_user_id: str = "",
        tg_status: str = "",
        tg_account_id: str = "",
    ) -> str:
        """Поставить номер на день. Уже отправленным и стоп не возвращаем в очередь."""
        now = time.time()
        phone_n = phone.strip()
        row = self.contact_by_phone(phone_n)
        if row and row.get("status") == "stopped":
            return "stopped"
        if (
            row
            and row.get("status") == "sent"
            and (now - float(row.get("updated_at") or 0)) < OUTREACH_RESEND_COOLDOWN_SEC
        ):
            return "already"
        self.add_contact(
            phone=phone_n,
            name=name,
            username=phone_n if phone_n.startswith("@") else "",
            manager_id=manager_id,
        )
        self._conn.execute(
            """
            UPDATE contacts SET
              send_on=?,
              telegram_user_id=CASE WHEN ?!='' THEN ? ELSE telegram_user_id END,
              tg_status=CASE WHEN ?!='' THEN ? ELSE tg_status END,
              tg_account_id=CASE WHEN ?!='' THEN ? ELSE tg_account_id END,
              updated_at=?
            WHERE phone=? AND status='pending'
            """,
            (
                send_on,
                telegram_user_id,
                telegram_user_id,
                tg_status,
                tg_status,
                tg_account_id,
                tg_account_id,
                now,
                phone_n,
            ),
        )
        self._conn.commit()
        fresh = self.contact_by_phone(phone_n)
        if fresh and fresh.get("status") == "pending" and (fresh.get("send_on") or "") == send_on:
            return "scheduled"
        if fresh and fresh.get("status") == "sent":
            return "already"
        return "skipped"

    def reject_not_telegram(
        self,
        phone: str,
        *,
        name: str = "",
        manager_id: str = "",
    ) -> None:
        now = time.time()
        phone_n = phone.strip()
        self.add_contact(
            phone=phone_n,
            name=name,
            username=phone_n if phone_n.startswith("@") else "",
            manager_id=manager_id,
        )
        self._conn.execute(
            """
            UPDATE contacts SET
              status='skipped',
              tg_status='нет в Telegram',
              send_on='',
              last_error='нет в Telegram',
              updated_at=?
            WHERE phone=? AND status NOT IN ('sent', 'stopped')
            """,
            (now, phone_n),
        )
        self._conn.commit()

    def contact_by_phone(self, phone: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM contacts WHERE phone=?", (phone.strip(),)
        ).fetchone()
        return dict(row) if row else None

    def set_contact_telegram(
        self,
        phone: str,
        *,
        telegram_user_id: str = "",
        tg_status: str = "",
        tg_account_id: str = "",
    ) -> None:
        """Кэш Telegram user id / статус «нет в Telegram» / аккаунт касания."""
        phone_n = phone.strip()
        now = time.time()
        row = self.contact_by_phone(phone_n)
        if not row:
            return
        # tg_account_id назначается один раз навсегда
        cur_acc = (row.get("tg_account_id") or "").strip()
        acc = cur_acc or (tg_account_id or "").strip()
        self._conn.execute(
            """
            UPDATE contacts SET
              telegram_user_id=CASE WHEN ?!='' THEN ? ELSE telegram_user_id END,
              tg_status=?,
              tg_account_id=?,
              updated_at=?
            WHERE phone=?
            """,
            (
                telegram_user_id,
                telegram_user_id,
                tg_status or row.get("tg_status") or "",
                acc,
                now,
                phone_n,
            ),
        )
        self._conn.commit()

    def stats(self) -> dict[str, int]:
        def cnt(q: str) -> int:
            return int(self._conn.execute(q).fetchone()[0])

        return {
            "all": cnt("SELECT COUNT(*) FROM contacts"),
            "pending": cnt("SELECT COUNT(*) FROM contacts WHERE status='pending'"),
            "sent": cnt("SELECT COUNT(*) FROM contacts WHERE status='sent'"),
            "failed": cnt("SELECT COUNT(*) FROM contacts WHERE status='failed'"),
            "stopped": cnt("SELECT COUNT(*) FROM contacts WHERE status='stopped'"),
            "skipped": cnt("SELECT COUNT(*) FROM contacts WHERE status='skipped'"),
            "dialogs": cnt("SELECT COUNT(*) FROM sessions"),
            "handed_off": cnt("SELECT COUNT(*) FROM sessions WHERE handed_off=1"),
        }

    def _session_from_row(self, row: Any) -> dict[str, Any]:
        d = dict(row)
        d["returning"] = d.pop("returning_guest", "") or ""
        try:
            d["context"] = json.loads(d.pop("context_json") or "{}")
        except Exception:
            d["context"] = {}
        d["archived"] = int(d.get("archived") or 0)
        d["pinned"] = int(d.get("pinned") or 0)
        d["note"] = d.get("note") or ""
        return d

    def peek_session(self, chat_id: str) -> dict[str, Any] | None:
        """Сессия, если чат уже есть. Не создаёт пустую строку."""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE chat_id=?", (str(chat_id),)
        ).fetchone()
        if not row:
            return None
        return self._session_from_row(row)

    def get_session(self, chat_id: str) -> dict[str, Any]:
        found = self.peek_session(chat_id)
        if found:
            return found
        now = time.time()
        self._conn.execute(
            "INSERT INTO sessions(chat_id,updated_at) VALUES(?,?)",
            (chat_id, now),
        )
        self._conn.commit()
        return {
            "chat_id": chat_id,
            "name": "",
            "step": "greeting",
            "dates": "",
            "guests": "",
            "district": "",
            "returning": "",
            "favorite": "",
            "handed_off": 0,
            "manager_id": "",
            "archived": 0,
            "pinned": 0,
            "note": "",
            "context": {},
            "updated_at": now,
        }

    def save_session(self, chat_id: str, **fields: Any) -> None:
        # строка должна существовать, иначе UPDATE молча ничего не пишет
        # и диалог не появляется в панели
        self.get_session(str(chat_id))
        # stop_requested — служебный флаг, в колонку не пишем
        fields.pop("stop_requested", None)
        if "returning" in fields:
            fields["returning_guest"] = fields.pop("returning")
        ctx = fields.pop("context", None)
        if ctx is not None:
            fields["context_json"] = json.dumps(ctx, ensure_ascii=False)
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE sessions SET {cols} WHERE chat_id=?",
            (*fields.values(), chat_id),
        )
        self._conn.commit()

    def add_message(
        self,
        chat_id: str,
        role: str,
        text: str,
        *,
        sender_label: str = "",
        manager_id: str = "",
        emit: bool = True,
    ) -> dict[str, Any]:
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO messages(chat_id,role,text,sender_label,created_at) "
            "VALUES(?,?,?,?,?)",
            (chat_id, role, text, sender_label or "", now),
        )
        self._conn.commit()
        # гость написал в архивный чат — чат снова в живой смене
        if role == "guest":
            row = self._conn.execute(
                "SELECT archived FROM sessions WHERE chat_id=?", (str(chat_id),)
            ).fetchone()
            if row and int(row["archived"] or 0):
                self._conn.execute(
                    "UPDATE sessions SET archived=0, updated_at=? WHERE chat_id=?",
                    (now, str(chat_id)),
                )
                self._conn.commit()
        msg = {
            "id": int(cur.lastrowid or 0),
            "chat_id": str(chat_id),
            "role": role,
            "text": text,
            "sender_label": sender_label or "",
            "created_at": now,
            "manager_id": manager_id,
        }
        if emit:
            try:
                from bot.hub import get_hub

                get_hub().bus.publish("message", **msg)
            except Exception:
                pass
        return msg

    def recent_messages(self, chat_id: str, limit: int = 12) -> list[dict[str, str]]:
        rows = self._conn.execute(
            "SELECT role,text,sender_label,created_at,id FROM messages "
            "WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [
            {
                "role": r["role"],
                "text": r["text"],
                "sender_label": r["sender_label"] or "",
                "created_at": r["created_at"],
                "id": r["id"],
            }
            for r in reversed(rows)
        ]

    def list_messages(self, chat_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.recent_messages(chat_id, limit=limit)

    def list_dialogs(
        self,
        *,
        manager_id: str = "",
        default_manager_id: str = "",
        limit: int = 80,
        admin: bool = False,
        only_archived: bool = False,
        now: float | None = None,
        census: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Диалоги для дашборда.

        Живой список: срочные и в работе, плюс закрытые младше 2 дней.
        Архив: снятые вручную и закрытые, которые уже скрыты из смены.
        Закрытые старше недели вычищаются здесь же (сессия и сообщения).
        """
        now_ts = float(now if now is not None else time.time())
        self.purge_finished(now=now_ts)
        if census is not None:
            census.clear()
            census.update(empty_lane_census())
        fetch_limit = max(int(limit) * 5, 400)
        order = "ORDER BY COALESCE(s.pinned,0) DESC, s.updated_at DESC"
        if admin and not manager_id:
            rows = self._conn.execute(
                f"""
                SELECT s.*, c.phone, c.status AS contact_status, c.name AS contact_name,
                       c.tg_status, c.telegram_user_id, c.tg_account_id
                FROM sessions s
                LEFT JOIN contacts c ON c.chat_id = s.chat_id
                WHERE 1=1
                {order}
                LIMIT ?
                """,
                (fetch_limit,),
            ).fetchall()
        elif default_manager_id and manager_id == default_manager_id:
            rows = self._conn.execute(
                f"""
                SELECT s.*, c.phone, c.status AS contact_status, c.name AS contact_name,
                       c.tg_status, c.telegram_user_id, c.tg_account_id
                FROM sessions s
                LEFT JOIN contacts c ON c.chat_id = s.chat_id
                WHERE (s.manager_id=? OR s.manager_id='' OR s.manager_id IS NULL
                       OR c.manager_id=? OR c.manager_id='' OR c.manager_id IS NULL)
                {order}
                LIMIT ?
                """,
                (manager_id, manager_id, fetch_limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""
                SELECT s.*, c.phone, c.status AS contact_status, c.name AS contact_name,
                       c.tg_status, c.telegram_user_id, c.tg_account_id
                FROM sessions s
                LEFT JOIN contacts c ON c.chat_id = s.chat_id
                WHERE (s.manager_id=? OR c.manager_id=?)
                {order}
                LIMIT ?
                """,
                (manager_id, manager_id, fetch_limit),
            ).fetchall()
        hide_before = now_ts - HIDE_DONE_SEC
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                ctx = json.loads(d.pop("context_json") or "{}")
            except Exception:
                ctx = {}
            d["context"] = ctx
            d["returning"] = d.pop("returning_guest", "") or ""
            last = self._conn.execute(
                "SELECT role,text,sender_label,created_at FROM messages "
                "WHERE chat_id=? ORDER BY id DESC LIMIT 1",
                (d["chat_id"],),
            ).fetchone()
            d["last_message"] = dict(last) if last else None
            d["archived"] = int(d.get("archived") or 0)
            d["pinned"] = int(d.get("pinned") or 0)
            d["note"] = d.get("note") or ""
            guest = self._conn.execute(
                "SELECT text FROM messages WHERE chat_id=? AND role IN ('guest','user') "
                "ORDER BY id DESC LIMIT 1",
                (d["chat_id"],),
            ).fetchone()
            d["last_guest"] = (guest["text"] if guest else "") or ""
            d["tone"] = dialog_tone(d)
            d["lane"] = dialog_lane(d)
            d["brief"] = dialog_brief(d)
            activity = float(
                ((d["last_message"] or {}).get("created_at") or 0)
                or d.get("updated_at")
                or 0
            )
            stale_done = (
                d["tone"] == "done"
                and not d["pinned"]
                and activity < hide_before
            )
            if only_archived:
                if not (d["archived"] or stale_done):
                    continue
            elif d["archived"] or stale_done:
                continue
            if census is not None:
                census[d["lane"]] = int(census.get(d["lane"]) or 0) + 1
            d["_activity"] = activity
            out.append(d)
        tone_rank = {"ready": 0, "work": 1, "done": 2}
        out.sort(
            [REDACTED] d: (
                0 if d["pinned"] else 1,
                tone_rank.get(str(d.get("tone") or ""), 1),
                -float(d.get("_activity") or 0),
            )
        )
        for d in out:
            d.pop("_activity", None)
            d.pop("last_guest", None)
        return out[: int(limit)]

    def purge_finished(
        self, *, older_than_sec: float = PURGE_DONE_SEC, now: float | None = None
    ) -> int:
        """Закрытые чаты старше недели: сессия, сообщения, очередь. Контакты остаются."""
        now_ts = float(now if now is not None else time.time())
        cutoff = now_ts - float(older_than_sec)
        rows = self._conn.execute(
            """
            SELECT chat_id, step, archived, pinned, context_json, dates, guests,
                   district, favorite, updated_at
            FROM sessions
            """
        ).fetchall()
        n = 0
        for r in rows:
            d = dict(r)
            try:
                d["context"] = json.loads(d.get("context_json") or "{}")
            except Exception:
                d["context"] = {}
            if int(d.get("pinned") or 0):
                continue
            if dialog_tone(d) != "done":
                continue
            if float(d.get("updated_at") or 0) >= cutoff:
                continue
            cid = str(d["chat_id"])
            self._conn.execute("DELETE FROM messages WHERE chat_id=?", (cid,))
            self._conn.execute("DELETE FROM inbound_queue WHERE chat_id=?", (cid,))
            self._conn.execute("DELETE FROM sessions WHERE chat_id=?", (cid,))
            n += 1
        if n:
            self._conn.commit()
        return n

    def search_messages(
        self,
        query: str,
        *,
        manager_id: str = "",
        admin: bool = False,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Поиск по тексту переписки. Менеджер видит только свои чаты."""
        q = (query or "").casefold().strip()
        if len(q) < 2:
            return []
        if admin and not manager_id:
            rows = self._conn.execute(
                """
                SELECT m.chat_id, m.role, m.text, m.created_at, s.name, s.manager_id
                FROM messages m
                JOIN sessions s ON s.chat_id = m.chat_id
                ORDER BY m.id DESC
                LIMIT 2000
                """
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT m.chat_id, m.role, m.text, m.created_at, s.name, s.manager_id
                FROM messages m
                JOIN sessions s ON s.chat_id = m.chat_id
                WHERE s.manager_id=?
                ORDER BY m.id DESC
                LIMIT 2000
                """,
                (manager_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            if q in (r["text"] or "").casefold():
                out.append(dict(r))
                if len(out) >= limit:
                    break
        return out

    def desk_snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        """Сводка для админа: кто ждёт, что в архиве, что можно убрать."""
        now = float(now if now is not None else time.time())
        rows = self._conn.execute(
            """
            SELECT s.chat_id, s.name, s.archived, s.pinned, s.handed_off,
                   s.manager_id, s.updated_at, s.note, s.step,
                   (SELECT role FROM messages m
                     WHERE m.chat_id=s.chat_id ORDER BY m.id DESC LIMIT 1) AS last_role,
                   (SELECT text FROM messages m
                     WHERE m.chat_id=s.chat_id ORDER BY m.id DESC LIMIT 1) AS last_text,
                   (SELECT created_at FROM messages m
                     WHERE m.chat_id=s.chat_id ORDER BY m.id DESC LIMIT 1) AS last_at
            FROM sessions s
            """
        ).fetchall()
        waiting: list[dict[str, Any]] = []
        quiet = 0
        live = archived = pinned = on_bot = on_mgr = 0
        cutoff = now - 3 * 86400
        for r in rows:
            is_arch = int(r["archived"] or 0)
            is_pin = int(r["pinned"] or 0)
            if is_arch:
                archived += 1
                continue
            live += 1
            if is_pin:
                pinned += 1
            if int(r["handed_off"] or 0):
                on_mgr += 1
            else:
                on_bot += 1
            last_role = r["last_role"] or ""
            last_at = float(r["last_at"] or r["updated_at"] or 0)
            if last_role == "guest":
                waiting.append(
                    {
                        "chat_id": r["chat_id"],
                        "name": r["name"] or r["chat_id"],
                        "manager_id": r["manager_id"] or "",
                        "last_text": (r["last_text"] or "")[:140],
                        "wait_sec": max(0, int(now - last_at)) if last_at else 0,
                        "note": r["note"] or "",
                    }
                )
            elif not is_pin and float(r["updated_at"] or 0) < cutoff:
                quiet += 1
        waiting.sort([REDACTED] x: x["wait_sec"], reverse=True)
        since = now - 86400
        messages_24h = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE created_at>=?", (since,)
            ).fetchone()[0]
        )
        guest_24h = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE role='guest' AND created_at>=?",
                (since,),
            ).fetchone()[0]
        )
        return {
            "live": live,
            "archived": archived,
            "pinned": pinned,
            "on_bot": on_bot,
            "on_manager": on_mgr,
            "waiting": len(waiting),
            "waiting_items": waiting[:12],
            "quiet_ready": quiet,
            "messages_24h": messages_24h,
            "guest_24h": guest_24h,
        }

    def archive_quiet(self, *, older_than_sec: float = 3 * 86400, now: float | None = None) -> int:
        """Архив чатов без ответа гостя и без булавки, старше порога."""
        now = float(now if now is not None else time.time())
        cutoff = now - float(older_than_sec)
        cur = self._conn.execute(
            """
            UPDATE sessions SET archived=1
            WHERE COALESCE(archived,0)=0
              AND COALESCE(pinned,0)=0
              AND updated_at < ?
              AND chat_id NOT IN (
                SELECT chat_id FROM messages
                WHERE id IN (SELECT MAX(id) FROM messages GROUP BY chat_id)
                  AND role='guest'
              )
            """,
            (cutoff,),
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def remove_global_stop(self, *, phone: str = "", chat_id: str = "") -> None:
        if phone:
            self._conn.execute(
                "DELETE FROM global_stops WHERE [REDACTED] (f"phone:{phone.strip()}",)
            )
            self._conn.execute(
                "UPDATE contacts SET status='pending', last_error='', updated_at=? "
                "WHERE phone=? AND status='stopped'",
                (time.time(), phone.strip()),
            )
        if chat_id:
            self._conn.execute(
                "DELETE FROM global_stops WHERE [REDACTED] (f"chat:{chat_id}",)
            )
            row = self.get_session(str(chat_id))
            ctx = dict(row.get("context") or {})
            ctx.pop("stopped", None)
            self.save_session(str(chat_id), handed_off=0, context=ctx)
            self._conn.execute(
                "UPDATE contacts SET status='pending', last_error='', updated_at=? "
                "WHERE chat_id=? AND status='stopped'",
                (time.time(), str(chat_id)),
            )
        self._conn.commit()

    def list_stops(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT key,kind,created_at FROM global_stops ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def guest_replied(self, chat_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE chat_id=? AND role='guest' LIMIT 1",
            (str(chat_id),),
        ).fetchone()
        return bool(row)

    def enqueue_inbound(
        self,
        chat_id: str,
        text: str,
        *,
        message_id: str = "",
        manager_id: str = "",
        created_at: float | None = None,
    ) -> None:
        """Persist a guest message waiting for a check-window (survives restart)."""
        now = float(created_at if created_at is not None else time.time())
        mid = (manager_id or "").strip()
        cid = str(chat_id)
        msg_id = str(message_id or "")
        if not msg_id:
            row = self._conn.execute(
                "SELECT id FROM inbound_queue WHERE chat_id=? AND manager_id=? AND text=? "
                "ORDER BY id DESC LIMIT 1",
                (cid, mid, text),
            ).fetchone()
            if row:
                return
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO inbound_queue"
                "(chat_id,text,message_id,manager_id,created_at) VALUES(?,?,?,?,?)",
                (cid, text, msg_id, mid, now),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def list_inbound_queue(
        self, *, manager_id: str = "", limit: int = 200
    ) -> list[dict[str, Any]]:
        mid = (manager_id or "").strip()
        if mid:
            rows = self._conn.execute(
                "SELECT * FROM inbound_queue WHERE manager_id=? ORDER BY id ASC LIMIT ?",
                (mid, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM inbound_queue ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def dequeue_inbound(
        self,
        chat_id: str,
        *,
        message_id: str = "",
        manager_id: str = "",
        text: str = "",
    ) -> None:
        mid = (manager_id or "").strip()
        cid = str(chat_id)
        msg_id = str(message_id or "")
        if msg_id:
            self._conn.execute(
                "DELETE FROM inbound_queue WHERE chat_id=? AND manager_id=? AND message_id=?",
                (cid, mid, msg_id),
            )
        elif text:
            self._conn.execute(
                "DELETE FROM inbound_queue WHERE id IN ("
                "SELECT id FROM inbound_queue WHERE chat_id=? AND manager_id=? AND text=? "
                "ORDER BY id ASC LIMIT 1)",
                (cid, mid, text),
            )
        else:
            self._conn.execute(
                "DELETE FROM inbound_queue WHERE chat_id=? AND manager_id=?",
                (cid, mid),
            )
        self._conn.commit()

    def clear_inbound_queue(self, *, manager_id: str = "") -> int:
        mid = (manager_id or "").strip()
        if mid:
            cur = self._conn.execute(
                "DELETE FROM inbound_queue WHERE manager_id=?", (mid,)
            )
        else:
            cur = self._conn.execute("DELETE FROM inbound_queue")
        self._conn.commit()
        return int(cur.rowcount or 0)

    def list_held_chats(self, *, manager_id: str = "", limit: int = 300) -> list[str]:
        """Чаты, переданные менеджеру (бот в них сейчас молчит)."""
        rows = self._conn.execute(
            "SELECT chat_id, manager_id FROM sessions WHERE handed_off=1 OR step='handed_off' "
            "ORDER BY updated_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        out: list[str] = []
        for r in rows:
            owner = str(r["manager_id"] or "").strip()
            if manager_id and owner and owner != manager_id:
                continue
            out.append(str(r["chat_id"]))
        return out

    def last_message_role(self, chat_id: str) -> str:
        row = self._conn.execute(
            "SELECT role FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT 1",
            (str(chat_id),),
        ).fetchone()
        return str(row["role"]) if row else ""


def re_header(row: list[str]) -> bool:
    head = ",".join(row).lower()
    return "phone" in head or "телефон" in head or "username" in head
