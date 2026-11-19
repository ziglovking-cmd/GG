"""SQLite-хранилище: аккаунты, чаты, участники, access_hash, кампании, лог."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date, datetime, time as datetime_time
from typing import Any, Dict, Iterable, List, Optional

from .config import DB_PATH

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
INVITE_CLAIM_MARKER = "invite_claim_pre_rpc:v1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT NOT NULL,
    phone         TEXT NOT NULL,
    session_name  TEXT NOT NULL UNIQUE,
    proxy         TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    tg_user_id    INTEGER,
    tg_username   TEXT,
    can_parse     INTEGER NOT NULL DEFAULT 1,
    can_invite    INTEGER NOT NULL DEFAULT 1,
    daily_limit   INTEGER NOT NULL DEFAULT 25,
    min_delay     INTEGER NOT NULL DEFAULT 90,
    max_delay     INTEGER NOT NULL DEFAULT 240,
    batch_size    INTEGER NOT NULL DEFAULT 8,
    batch_pause   INTEGER NOT NULL DEFAULT 2700,
    invites_today INTEGER NOT NULL DEFAULT 0,
    successful_today INTEGER NOT NULL DEFAULT 0,
    counter_day   TEXT,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    cooldown_until INTEGER NOT NULL DEFAULT 0,
    invite_restricted INTEGER NOT NULL DEFAULT 0,
    invite_restriction_reason TEXT,
    invite_restricted_at INTEGER,
    last_error    TEXT,
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
    id             INTEGER PRIMARY KEY,
    title          TEXT,
    username       TEXT,
    kind           TEXT,
    members_count  INTEGER,
    is_megagroup   INTEGER DEFAULT 0,
    last_parsed_at INTEGER
);

CREATE TABLE IF NOT EXISTS members (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    username    TEXT,
    first_name  TEXT,
    last_name   TEXT,
    phone       TEXT,
    is_bot      INTEGER DEFAULT 0,
    is_deleted  INTEGER DEFAULT 0,
    is_premium  INTEGER DEFAULT 0,
    last_seen   TEXT,
    msg_count   INTEGER DEFAULT 0,
    sources     TEXT DEFAULT '',
    updated_at  INTEGER,
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_members_user ON members(user_id);

-- access_hash действителен только для аккаунта, который его получил
CREATE TABLE IF NOT EXISTS hashes (
    account_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    access_hash INTEGER NOT NULL,
    updated_at  INTEGER,
    PRIMARY KEY (account_id, user_id)
);

CREATE TABLE IF NOT EXISTS campaigns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    target_chat_id INTEGER NOT NULL,
    target_title   TEXT,
    settings       TEXT NOT NULL DEFAULT '{}',
    status         TEXT NOT NULL DEFAULT 'draft',
    created_at     INTEGER NOT NULL,
    preflight_status TEXT NOT NULL DEFAULT 'not_run',
    preflight_summary TEXT,
    preflight_checked_at INTEGER,
    next_invite_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS targets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id  INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    username     TEXT,
    display      TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    account_id   INTEGER,
    error        TEXT,
    attempted_at INTEGER,
    resolved_user_id INTEGER,
    preflight_status TEXT,
    preflight_error TEXT,
    preflight_checked_at INTEGER,
    UNIQUE (campaign_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_targets_campaign ON targets(campaign_id, status);

CREATE TABLE IF NOT EXISTS invite_confirmations (
    target_id     INTEGER PRIMARY KEY,
    checked_at    INTEGER NOT NULL,
    result        TEXT NOT NULL,
    member_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    level       TEXT NOT NULL DEFAULT 'info',
    scope       TEXT,
    campaign_id INTEGER,
    account_id  INTEGER,
    message     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

-- Место незаконченного прохода по сообщениям: следующий запуск продолжает с него.
-- id сообщений в обычных группах свои у каждого аккаунта, поэтому ключ с account_id.
CREATE TABLE IF NOT EXISTS parse_cursors (
    chat_id     INTEGER NOT NULL,
    account_id  INTEGER NOT NULL,
    source      TEXT NOT NULL,
    offset_id   INTEGER NOT NULL,
    scanned     INTEGER NOT NULL DEFAULT 0,
    total       INTEGER,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (chat_id, account_id, source)
);

CREATE TRIGGER IF NOT EXISTS trg_block_parallel_target_claim
BEFORE UPDATE OF status ON targets
WHEN OLD.status='pending' AND NEW.status='in_progress'
 AND EXISTS (
     SELECT 1
     FROM targets other
     JOIN campaigns current_campaign ON current_campaign.id=NEW.campaign_id
     JOIN campaigns other_campaign ON other_campaign.id=other.campaign_id
     WHERE other.id!=NEW.id
       AND other.campaign_id!=NEW.campaign_id
       AND other_campaign.target_chat_id=current_campaign.target_chat_id
       AND other.status IN (
           'in_progress','verifying','invited','already','privacy','deleted'
       )
       AND (
           other.user_id=NEW.user_id
           OR (
               NULLIF(TRIM(other.username),'') IS NOT NULL
               AND NULLIF(TRIM(NEW.username),'') IS NOT NULL
               AND LOWER(TRIM(other.username))=LOWER(TRIM(NEW.username))
           )
       )
 )
BEGIN
    SELECT RAISE(IGNORE);
END;

CREATE TRIGGER IF NOT EXISTS trg_verify_invited_target
AFTER UPDATE OF status ON targets
WHEN NEW.status='invited'
 AND OLD.status!='invited'
 AND NOT EXISTS (
     SELECT 1 FROM invite_confirmations
     WHERE target_id=NEW.id AND result='confirmed'
 )
BEGIN
    UPDATE targets
    SET status='verifying',
        error='попытка invited заблокирована: отсутствует подтверждение членства'
    WHERE id=NEW.id;
END;

-- Once the durable at-most-once marker is written, automatic retry is only a
-- targeted membership check. Re-queuing would permit a second Invite RPC.
CREATE TRIGGER IF NOT EXISTS trg_block_verifying_requeue
BEFORE UPDATE OF status ON targets
WHEN OLD.status='verifying' AND NEW.status IN ('pending','in_progress')
BEGIN
    SELECT RAISE(ABORT, 'verifying target cannot return to the invite queue');
END;
"""


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            # timeout + busy_timeout: writer (reporter) and invite workers can
            # contend across processes; wait instead of failing with
            # "database is locked" on the first conflict.
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA busy_timeout=30000")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _conn.executescript(SCHEMA)
            # Миграция существующих баз: старый invites_today хранит число
            # попыток. Отдельно считаем только подтверждённые приглашения.
            columns = {row["name"] for row in _conn.execute("PRAGMA table_info(accounts)")}
            if "successful_today" not in columns:
                _conn.execute(
                    "ALTER TABLE accounts ADD COLUMN successful_today INTEGER NOT NULL DEFAULT 0"
                )
                day_start = int(datetime.combine(date.today(), datetime_time.min).timestamp())
                _conn.execute(
                    """
                    UPDATE accounts
                    SET successful_today = (
                        SELECT COUNT(*) FROM targets
                        WHERE targets.account_id = accounts.id
                          AND targets.status = 'invited'
                          AND targets.attempted_at >= ?
                    )
                    """,
                    (day_start,),
                )
            if "next_attempt_at" not in columns:
                _conn.execute(
                    "ALTER TABLE accounts ADD COLUMN next_attempt_at INTEGER NOT NULL DEFAULT 0"
                )
            # PEER_FLOOD нельзя считать обычной временной паузой: окончание
            # cooldown не доказывает, что Telegram снял ограничение. Отдельный
            # флаг сохраняется до явного решения оператора.
            restriction_column_missing = "invite_restricted" not in columns
            for name, definition in (
                ("invite_restricted", "INTEGER NOT NULL DEFAULT 0"),
                ("invite_restriction_reason", "TEXT"),
                ("invite_restricted_at", "INTEGER"),
            ):
                if name not in columns:
                    _conn.execute(
                        "ALTER TABLE accounts ADD COLUMN %s %s" % (name, definition)
                    )
            if restriction_column_missing:
                # Безопасно переносим уже известные PEER_FLOOD из старой БД.
                # Миграция выполняется только при первом добавлении столбца,
                # поэтому последующее ручное восстановление не откатится.
                _conn.execute(
                    """
                    UPDATE accounts
                    SET invite_restricted=1,
                        invite_restriction_reason=COALESCE(last_error, 'PEER_FLOOD'),
                        invite_restricted_at=?
                    WHERE UPPER(COALESCE(last_error,'')) LIKE '%PEER_FLOOD%'
                    """,
                    (int(time.time()),),
                )
            campaign_columns = {
                row["name"] for row in _conn.execute("PRAGMA table_info(campaigns)")
            }
            for name, definition in (
                ("preflight_status", "TEXT NOT NULL DEFAULT 'not_run'"),
                ("preflight_summary", "TEXT"),
                ("preflight_checked_at", "INTEGER"),
                # Общий для всех аккаунтов кампании момент следующего приглашения.
                ("next_invite_at", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in campaign_columns:
                    _conn.execute(
                        "ALTER TABLE campaigns ADD COLUMN %s %s" % (name, definition)
                    )
            target_columns = {
                row["name"] for row in _conn.execute("PRAGMA table_info(targets)")
            }
            for name, definition in (
                ("resolved_user_id", "INTEGER"),
                ("preflight_status", "TEXT"),
                ("preflight_error", "TEXT"),
                ("preflight_checked_at", "INTEGER"),
            ):
                if name not in target_columns:
                    _conn.execute(
                        "ALTER TABLE targets ADD COLUMN %s %s" % (name, definition)
                    )
            # Старый ``invited`` без сохранённого доказательства нельзя
            # подтвердить задним числом: неизвестно, был ли человек в чате до
            # запроса. Делаем такой результат честным терминальным неуспехом.
            _conn.execute(
                """
                UPDATE targets
                SET status='failed',
                    error='старый успех отменён: нет подтверждения членства'
                WHERE status='invited'
                  AND NOT EXISTS (
                      SELECT 1 FROM invite_confirmations confirmation
                      WHERE confirmation.target_id=targets.id
                        AND confirmation.result='confirmed'
                  )
                """
            )
            # Счётчики сегодняшнего дня должны отражать тот же подтверждённый
            # набор, а не исторические optimistic-success записи.
            today = date.today().isoformat()
            day_start = int(
                datetime.combine(date.today(), datetime_time.min).timestamp()
            )
            _conn.execute(
                """
                UPDATE accounts
                SET successful_today=(
                        SELECT COUNT(*) FROM targets
                        WHERE targets.account_id=accounts.id
                          AND targets.status='invited'
                          AND targets.attempted_at>=?
                    ),
                    invites_today=(
                        SELECT COUNT(*) FROM targets
                        WHERE targets.account_id=accounts.id
                          AND targets.status='invited'
                          AND targets.attempted_at>=?
                    )
                WHERE counter_day=?
                """,
                (day_start, day_start, today),
            )
            _conn.commit()
        return _conn


def pause_stale_running_campaigns() -> None:
    """Ставит старые запуски на паузу только при старте основного приложения.

    Обычное подключение к базе из теста или диагностической команды не должно
    менять статусы кампаний, которыми управляет уже работающий процесс.
    """
    with _lock:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Under the v1 at-most-once protocol, a marked ``in_progress`` row
            # is provably before the Invite RPC (the next transition is the
            # committed ``verifying`` marker). It is therefore safe to requeue
            # after a hard crash. Unmarked legacy rows stay untouched because
            # old versions could crash after sending while still in_progress.
            conn.execute(
                """
                UPDATE targets
                SET status='pending',account_id=NULL,error=NULL
                WHERE status='in_progress' AND error=?
                """,
                (INVITE_CLAIM_MARKER,),
            )
            conn.execute("UPDATE campaigns SET status='paused' WHERE status='running'")
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def q(sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
    with _lock:
        cur = connect().execute(sql, tuple(params))
        return cur.fetchall()


def q1(sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    rows = q(sql, params)
    return rows[0] if rows else None


def ex(sql: str, params: Iterable[Any] = ()) -> int:
    with _lock:
        conn = connect()
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.lastrowid


def exmany(sql: str, seq: Iterable[Iterable[Any]]) -> None:
    with _lock:
        conn = connect()
        conn.executemany(sql, [tuple(s) for s in seq])
        conn.commit()


def save_parsed_members(chat_id: int, member_rows: Iterable[Iterable[Any]],
                        hash_rows: Iterable[Iterable[Any]]) -> int:
    """Обновляет общую базу чата; считает только вставки в одной транзакции."""
    members = [tuple(row) for row in member_rows]
    hashes = [tuple(row) for row in hash_rows]
    if not members:
        return 0
    if any(row[0] != chat_id for row in members):
        raise ValueError("Все пользователи должны относиться к одному чату")
    with _lock:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            before = conn.execute(
                "SELECT COUNT(*) FROM members WHERE chat_id=?", (chat_id,)
            ).fetchone()[0]
            conn.executemany(
                """
                INSERT INTO members (chat_id,user_id,username,first_name,last_name,phone,
                                     is_bot,is_deleted,is_premium,last_seen,msg_count,sources,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    phone=COALESCE(excluded.phone, members.phone),
                    is_bot=excluded.is_bot,
                    is_deleted=excluded.is_deleted,
                    is_premium=excluded.is_premium,
                    last_seen=CASE WHEN excluded.last_seen != '' THEN excluded.last_seen ELSE members.last_seen END,
                    msg_count=MAX(members.msg_count, excluded.msg_count),
                    sources=CASE WHEN instr(members.sources, excluded.sources) > 0
                                 THEN members.sources
                                 ELSE trim(members.sources || ',' || excluded.sources, ',') END,
                    updated_at=excluded.updated_at
                """, members,
            )
            conn.executemany(
                "INSERT INTO hashes (account_id,user_id,access_hash,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(account_id,user_id) DO UPDATE SET access_hash=excluded.access_hash, "
                "updated_at=excluded.updated_at", hashes,
            )
            after = conn.execute(
                "SELECT COUNT(*) FROM members WHERE chat_id=?", (chat_id,)
            ).fetchone()[0]
            conn.commit()
            return after - before
        except Exception:
            conn.rollback()
            raise


def delete_campaign(campaign_id: int) -> bool:
    """Deletes a stopped campaign and its dependent rows atomically."""
    with _lock:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM campaigns WHERE id=?", (int(campaign_id),)
            ).fetchone()
            if exists is None:
                conn.rollback()
                return False
            conn.execute(
                "DELETE FROM invite_confirmations WHERE target_id IN "
                "(SELECT id FROM targets WHERE campaign_id=?)",
                (int(campaign_id),),
            )
            conn.execute("DELETE FROM targets WHERE campaign_id=?", (int(campaign_id),))
            conn.execute("DELETE FROM campaigns WHERE id=?", (int(campaign_id),))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise


def claim_invite_target(
    campaign_id: int,
    account_id: int,
) -> Optional[Dict[str, Any]]:
    """Atomically selects and claims the next pending target for an account.

    Selection and the ``pending`` → ``in_progress`` update happen in one
    ``BEGIN IMMEDIATE`` transaction so parallel workers cannot both observe
    the same pending row before either claim commits.
    """
    with _lock:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT t.* FROM targets t
                WHERE t.campaign_id = ? AND t.status = 'pending'
                  AND ( (t.username IS NOT NULL AND t.username != '')
                        OR EXISTS (
                            SELECT 1 FROM hashes h
                            WHERE h.account_id = ? AND h.user_id = t.user_id
                        ) )
                ORDER BY t.id LIMIT 1
                """,
                (int(campaign_id), int(account_id)),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            changed = conn.execute(
                """
                UPDATE targets
                SET status='in_progress', account_id=?, error=?
                WHERE id=? AND status='pending'
                """,
                (int(account_id), INVITE_CLAIM_MARKER, int(row["id"])),
            ).rowcount
            if changed != 1:
                conn.rollback()
                return None
            conn.commit()
            return dict(row)
        except Exception:
            conn.rollback()
            raise


def mark_invite_rpc_started(
    target_id: int,
    account_id: int,
    marker: str,
    attempted_at: Optional[int] = None,
) -> bool:
    """Durably arms at-most-once protection immediately before Invite RPC."""
    with _lock:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """
                UPDATE targets
                SET status='verifying', account_id=?, error=?, attempted_at=?
                WHERE id=? AND status='in_progress' AND account_id=?
                """,
                (
                    int(account_id),
                    str(marker)[:300],
                    int(attempted_at if attempted_at is not None else time.time()),
                    int(target_id),
                    int(account_id),
                ),
            ).rowcount
            if changed != 1:
                conn.rollback()
                return False
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise


def finalize_invite_confirmation(
    target_id: int,
    confirmed: bool,
    error: str = "",
    result: Optional[str] = None,
    checked_at: Optional[int] = None,
    member_count: int = 0,
) -> str:
    """Атомарно завершает двухфазный инвайт и возвращает итоговый статус.

    ``invited`` и оба пользовательских счётчика появляются только в одной
    транзакции с записью ``invite_confirmations.result='confirmed'``. Поэтому
    ни падение процесса, ни параллельный отчётчик не могут оставить видимый
    успех без доказательства присутствия пользователя.
    """
    now_ts = int(checked_at if checked_at is not None else time.time())
    with _lock:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute(
                """
                SELECT t.*, c.target_chat_id
                FROM targets t
                JOIN campaigns c ON c.id=t.campaign_id
                WHERE t.id=?
                """,
                (int(target_id),),
            ).fetchone()
            if target is None:
                conn.rollback()
                return "missing"

            current_status = str(target["status"] or "")
            if current_status != "verifying":
                conn.rollback()
                return current_status

            if confirmed:
                # Запись доказательства должна предшествовать UPDATE: старые
                # базы могут содержать защитный trigger, запрещающий invited
                # без подтверждения.
                conn.execute(
                    """
                    INSERT OR REPLACE INTO invite_confirmations
                        (target_id,checked_at,result,member_count)
                    VALUES (?,?,'confirmed',?)
                    """,
                    (int(target_id), now_ts, max(0, int(member_count))),
                )
                changed = conn.execute(
                    """
                    UPDATE targets SET status='invited',error=NULL
                    WHERE id=? AND status='verifying'
                    """,
                    (int(target_id),),
                ).rowcount
                if changed and target["account_id"]:
                    counter_day = date.today().isoformat()
                    conn.execute(
                        """
                        UPDATE accounts
                        SET invites_today=CASE
                                WHEN counter_day=? THEN invites_today+1 ELSE 1 END,
                            successful_today=CASE
                                WHEN counter_day=? THEN successful_today+1 ELSE 1 END,
                            counter_day=?
                        WHERE id=?
                        """,
                        (
                            counter_day,
                            counter_day,
                            counter_day,
                            int(target["account_id"]),
                        ),
                    )
                identity = (
                    target["username"]
                    or target["resolved_user_id"]
                    or target["user_id"]
                )
                label = (
                    "@" + str(identity).lstrip("@")
                    if target["username"]
                    else str(identity)
                )
                if changed:
                    conn.execute(
                        """
                        INSERT INTO events
                            (ts,level,scope,campaign_id,account_id,message)
                        VALUES (?,'info','invite',?,?,?)
                        """,
                        (
                            now_ts,
                            int(target["campaign_id"]),
                            int(target["account_id"] or 0) or None,
                            "Приглашён %s (присутствие подтверждено)" % label,
                        ),
                    )
                conn.commit()
                return "invited" if changed else current_status

            final_error = error or (
                "Telegram не подтвердил присутствие пользователя в целевом чате"
            )
            changed = conn.execute(
                """
                UPDATE targets SET status='failed',error=?
                WHERE id=? AND status='verifying'
                """,
                (final_error[:300], int(target_id)),
            ).rowcount
            if changed:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO invite_confirmations
                        (target_id,checked_at,result,member_count)
                    VALUES (?,?,?,?)
                    """,
                    (
                        int(target_id),
                        now_ts,
                        result or "not_present",
                        max(0, int(member_count)),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO events
                        (ts,level,scope,campaign_id,account_id,message)
                    VALUES (?,'warn','invite',?,?,?)
                    """,
                    (
                        now_ts,
                        int(target["campaign_id"]),
                        int(target["account_id"] or 0) or None,
                        final_error[:300],
                    ),
                )
            conn.commit()
            return "failed" if changed else current_status
        except Exception:
            conn.rollback()
            raise


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


def log(message: str, level: str = "info", scope: str = "", campaign_id: Optional[int] = None,
        account_id: Optional[int] = None) -> None:
    ex(
        "INSERT INTO events (ts, level, scope, campaign_id, account_id, message) VALUES (?,?,?,?,?,?)",
        (int(time.time()), level, scope, campaign_id, account_id, message),
    )


def settings_of(campaign: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(campaign.get("settings") or "{}")
    except Exception:
        return {}
