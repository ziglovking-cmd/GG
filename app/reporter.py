"""Отдельный бот-отчётчик, не перезапускающий рабочие кампании.

Процесс читает основную SQLite-базу только в режиме read-only, группирует
результаты близких по времени попыток в один цикл и отправляет суточную сводку
после контрольной синхронизации состава целевого чата.
"""
from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from .config import DATA_DIR, DB_PATH, get_bot_recipient, get_bot_settings


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
APP_BASE_URL = os.getenv("TG_AUDIENCE_URL", "http://tg-audience:8777").rstrip("/")
STATE_PATH = Path(os.getenv("REPORTER_STATE_PATH", str(DATA_DIR / "reporter_state.json")))
BOT_CONFIG_PATH = Path(os.getenv(
    "REPORTER_BOT_CONFIG_PATH", str(DATA_DIR / "reporter_bot.json")
))
BOT_COMMANDS_ENABLED = os.getenv("REPORTER_BOT_COMMANDS", "0") == "1"
POLL_SECONDS = max(10, int(os.getenv("REPORTER_POLL_SECONDS", "30")))
SETTLE_SECONDS = max(60, int(os.getenv("REPORTER_SETTLE_SECONDS", "600")))
INVITE_CONFIRM_DELAY_SECONDS = max(
    30, int(os.getenv("INVITE_CONFIRM_DELAY_SECONDS", "90"))
)
INVITE_VERIFY_MARKER = "ожидает подтверждения присутствия в целевом чате"
INVITE_RPC_DURABLE_MARKER = "invite_rpc_at_most_once:v1"
TARGET_CHAT = os.getenv("REPORTER_TARGET_CHAT", "@skyptop_new_delivery")
TARGET_CHAT_ID = int(os.getenv("REPORTER_TARGET_CHAT_ID", "4396252688"))
CAMPAIGN_NAMES: Tuple[str, ...] = (
    "6 часов",
    "6 часов вторая смена",
)
BOT_REPORT_BUTTON = "Получить отчёт по актуальным кампаниям"
BOT_REFRESH_CALLBACK = "refresh_status"

FATAL_STATE_MARKERS = (
    "аккаунт недоступен",
    "аккаунт не авторизован",
    "отключён пользователем",
    "нет прав приглашать",
    "перепроверка доступа",
    "сбой подключения",
    "тайм-аут подключения",
    "PEER_FLOOD",
    "спамблок Telegram",
    "целевой чат заполнен",
)


def _default_state() -> Dict[str, Any]:
    return {
        "cursors": {},
        "pending_waves": {},
        "campaign_health": {},
        "bot_update_offset": None,
        "last_daily_date": None,
        "membership": None,
    }


def _load_state() -> Dict[str, Any]:
    state = _default_state()
    if not STATE_PATH.exists():
        return state
    try:
        saved = json.loads(STATE_PATH.read_text("utf-8"))
        if isinstance(saved, dict):
            state.update(saved)
    except Exception as error:
        print("Не удалось прочитать состояние отчётчика: %s" % error, flush=True)
    return state


def _save_state(state: Dict[str, Any]) -> None:
    temp_path = STATE_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(STATE_PATH)
    os.chmod(STATE_PATH, 0o600)


def _read_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(
        "file:%s?mode=ro" % DB_PATH, uri=True, timeout=5
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _write_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _db_rows(sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    with _read_connection() as connection:
        return [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]


def _ensure_invite_confirmation_schema() -> None:
    """Включает двухфазный учёт: ответ Telegram -> проверка состава чата."""
    with _write_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invite_confirmations (
                target_id     INTEGER PRIMARY KEY,
                checked_at    INTEGER NOT NULL,
                result        TEXT NOT NULL,
                member_count  INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute("DROP TRIGGER IF EXISTS trg_verify_invited_target")
        connection.execute("DROP TRIGGER IF EXISTS trg_block_parallel_target_claim")
        connection.execute(
            """
            CREATE TRIGGER trg_block_parallel_target_claim
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
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER trg_verify_invited_target
            AFTER UPDATE OF status ON targets
            WHEN NEW.status='invited'
             AND OLD.status!='invited'
             AND NOT EXISTS (
                 SELECT 1 FROM invite_confirmations
                 WHERE target_id=NEW.id AND result='confirmed'
             )
            BEGIN
                UPDATE targets
                SET status='verifying', error='ожидает подтверждения присутствия в целевом чате'
                WHERE id=NEW.id;
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_block_verifying_requeue
            BEFORE UPDATE OF status ON targets
            WHEN OLD.status='verifying' AND NEW.status IN ('pending','in_progress')
            BEGIN
                SELECT RAISE(ABORT, 'verifying target cannot return to the invite queue');
            END
            """
        )


def _target_identity(person: Dict[str, Any]) -> str:
    resolved_user_id = person.get("resolved_user_id")
    if resolved_user_id:
        return "id:" + str(resolved_user_id)
    username = str(person.get("username") or "").strip().lstrip("@").lower()
    if username:
        return "u:" + username
    return "id:" + str(person.get("user_id") or "")


def _dedupe_running_targets() -> int:
    """Оставляет общую ожидающую цель только в одной активной кампании."""
    with _write_connection() as connection:
        target_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(targets)").fetchall()
        }
        resolved_select = (
            "t.resolved_user_id" if "resolved_user_id" in target_columns
            else "NULL AS resolved_user_id"
        )
        rows = [dict(row) for row in connection.execute(
            """
            SELECT t.id, t.campaign_id, t.user_id, %s,
                   t.username, t.status
            FROM targets t JOIN campaigns c ON c.id=t.campaign_id
            WHERE c.target_chat_id=? AND c.status='running'
              AND t.status IN (
                  'pending','in_progress','verifying','invited','already','privacy','deleted'
              )
            ORDER BY t.id
            """ % resolved_select,
            (TARGET_CHAT_ID,),
        ).fetchall()]
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(_target_identity(row), []).append(row)

        skipped: List[int] = []
        terminal = {
            "in_progress", "verifying", "invited", "already", "privacy", "deleted"
        }
        for identity, items in grouped.items():
            pending = [item for item in items if item["status"] == "pending"]
            campaigns = {int(item["campaign_id"]) for item in items}
            if len(campaigns) < 2 or not pending:
                continue
            blockers = [item for item in items if item["status"] in terminal]
            if blockers:
                skipped.extend(int(item["id"]) for item in pending)
                continue
            # Если все копии ещё ожидают, равномерно распределяем владельца
            # по стабильному хэшу цели, а остальные копии исключаем.
            ordered = sorted(pending, key=lambda item: int(item["campaign_id"]))
            digest = hashlib.sha256(identity.encode("utf-8")).digest()
            owner = int.from_bytes(digest[:4], "big") % len(ordered)
            skipped.extend(
                int(item["id"]) for index, item in enumerate(ordered)
                if index != owner
            )

        if skipped:
            now_ts = int(time.time())
            connection.executemany(
                """
                UPDATE targets
                SET status='skipped', account_id=NULL,
                    error='исключён как дубль параллельной кампании', attempted_at=NULL
                WHERE id=? AND status='pending'
                """,
                [(target_id,) for target_id in skipped],
            )
            connection.execute(
                """
                INSERT INTO events (ts,level,scope,message)
                VALUES (?,'info','invite',?)
                """,
                (now_ts, "Исключены общие цели параллельных кампаний: %d" % len(skipped)),
            )
    return len(skipped)


def _api_request(path: str, payload: Optional[Dict[str, Any]] = None,
                 timeout: int = 30) -> Any:
    body = None
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = "POST"
    request = urllib.request.Request(
        APP_BASE_URL + "/api" + path,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "TG-Audience-Reporter/1.0"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _private_bot_config() -> Dict[str, Any]:
    if not BOT_CONFIG_PATH.exists():
        return {}
    try:
        private_config = json.loads(BOT_CONFIG_PATH.read_text("utf-8"))
        return private_config if isinstance(private_config, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _bot_credentials() -> Tuple[Optional[str], Optional[int]]:
    token: Optional[str] = None
    chat_id: Optional[int] = None
    private_config = _private_bot_config()
    if private_config:
        try:
            token = str(private_config.get("bot_token") or "").strip() or None
            if private_config.get("bot_chat_id") is not None:
                chat_id = int(private_config["bot_chat_id"])
            elif isinstance(private_config.get("bot_chat_ids"), list):
                chat_id = next(
                    (int(value) for value in private_config["bot_chat_ids"] if value),
                    None,
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            token = None
            chat_id = None
    if not token or not chat_id:
        token, _ = get_bot_settings()
        chat_id, _ = get_bot_recipient()
    return token, chat_id


def _bot_recipient_ids() -> List[int]:
    """Все личные чаты для одинаковых отчётов, с поддержкой старого формата."""
    private_config = _private_bot_config()
    recipient_ids: List[int] = []
    raw_ids: List[Any] = []
    if private_config.get("bot_chat_id") is not None:
        raw_ids.append(private_config["bot_chat_id"])
    configured_ids = private_config.get("bot_chat_ids")
    if isinstance(configured_ids, list):
        raw_ids.extend(configured_ids)
    for value in raw_ids:
        try:
            chat_id = int(value)
        except (TypeError, ValueError):
            continue
        if chat_id and chat_id not in recipient_ids:
            recipient_ids.append(chat_id)
    if not recipient_ids:
        _, chat_id = _bot_credentials()
        if chat_id:
            recipient_ids.append(int(chat_id))
    return recipient_ids


def _bot_request(method: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    token, _ = _bot_credentials()
    if not token:
        raise RuntimeError("Бот уведомлений не настроен")
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.telegram.org/bot%s/%s" % (token, method),
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "TG-Audience-Reporter/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 409 and method == "getUpdates":
            raise RuntimeError("У бота уже работает другой получатель обновлений")
        raise RuntimeError("Telegram Bot API вернул HTTP %d" % error.code)
    if not response_payload.get("ok"):
        raise RuntimeError("Telegram не подтвердил запрос отчётчика")
    return response_payload.get("result")


def _report_keyboard() -> Dict[str, Any]:
    return {
        "keyboard": [[{"text": BOT_REPORT_BUTTON}]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def _split_bot_message(text: str, limit: int = 3500) -> List[str]:
    """Делит длинный отчёт на сообщения, сохраняя границы строк.

    Telegram допускает не более 4096 символов в одном сообщении. Оставляем
    запас для эмодзи и отправляем большой пул аккаунтов несколькими частями.
    """
    source = str(text or "")
    if len(source) <= limit:
        return [source]

    chunks: List[str] = []
    current = ""
    for line in source.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current.rstrip("\n"))
                current = ""
            chunks.append(line[:limit].rstrip("\n"))
            line = line[limit:]
        if current and len(current) + len(line) > limit:
            chunks.append(current.rstrip("\n"))
            current = ""
        current += line
    if current or not chunks:
        chunks.append(current.rstrip("\n"))
    return [chunk for chunk in chunks if chunk]


def _send_bot_message(text: str) -> None:
    chat_ids = _bot_recipient_ids()
    if not chat_ids:
        raise RuntimeError("Бот или получатель уведомлений не настроен")
    chunks = _split_bot_message(text)
    errors: List[Exception] = []
    for chat_id in chat_ids:
        try:
            for index, chunk in enumerate(chunks):
                payload: Dict[str, Any] = {
                    "chat_id": chat_id,
                    "text": chunk,
                }
                if BOT_COMMANDS_ENABLED and index == len(chunks) - 1:
                    payload["reply_markup"] = _report_keyboard()
                _bot_request("sendMessage", payload)
        except Exception as error:
            errors.append(error)
            print(
                "Не удалось отправить отчёт одному из получателей: %s" % error,
                flush=True,
            )
    if errors and len(errors) == len(chat_ids):
        raise errors[0]


def _current_campaigns() -> List[Dict[str, Any]]:
    campaigns = _api_request("/campaigns")
    relevant = [
        item for item in campaigns
        if int(item.get("target_chat_id") or 0) == TARGET_CHAT_ID
    ]
    current = [
        item for item in relevant
        if bool(item.get("running")) or item.get("status") == "running"
    ]
    order = {name: index for index, name in enumerate(CAMPAIGN_NAMES)}
    return sorted(
        current,
        key=lambda item: (order.get(str(item.get("name")), len(order)), int(item["id"])),
    )


def _prune_inactive_campaign_state(
    state: Dict[str, Any], campaigns: Sequence[Dict[str, Any]]
) -> bool:
    """Не даёт старым волнам остановленных кампаний породить бот-отчёт."""
    active = {str(int(campaign["id"])) for campaign in campaigns}
    changed = False
    for field in ("pending_waves", "campaign_health"):
        stored = state.setdefault(field, {})
        stale = [key for key in stored if key not in active]
        for key in stale:
            del stored[key]
            changed = True
    return changed


def _latest_cursor(campaign_id: int) -> Dict[str, Any]:
    rows = _db_rows(
        """
        SELECT id, attempted_at FROM targets
        WHERE campaign_id=? AND attempted_at IS NOT NULL
        ORDER BY attempted_at DESC, id DESC LIMIT 1
        """,
        (campaign_id,),
    )
    if not rows:
        return {"attempted_at": 0, "seen": []}
    attempted_at = int(rows[0]["attempted_at"])
    seen = _db_rows(
        "SELECT id, status FROM targets WHERE campaign_id=? AND attempted_at=?",
        (campaign_id, attempted_at),
    )
    return {
        "attempted_at": attempted_at,
        "seen": ["%s:%s" % (row["id"], row["status"]) for row in seen],
    }


def _new_attempts(campaign_id: int, cursor: Dict[str, Any]) -> List[Dict[str, Any]]:
    attempted_at = int(cursor.get("attempted_at") or 0)
    seen = set(cursor.get("seen") or [])
    rows = _db_rows(
        """
        SELECT id, user_id, username, display, status, account_id, attempted_at
        FROM targets
        WHERE campaign_id=? AND attempted_at IS NOT NULL
          AND attempted_at>=?
        ORDER BY attempted_at, id
        """,
        (campaign_id, attempted_at),
    )
    return [
        row for row in rows
        if int(row["attempted_at"]) > attempted_at
        or "%s:%s" % (row["id"], row["status"]) not in seen
    ]


def _update_pending_waves(state: Dict[str, Any], campaigns: Sequence[Dict[str, Any]]) -> bool:
    changed = False
    cursors = state.setdefault("cursors", {})
    pending = state.setdefault("pending_waves", {})
    for campaign in campaigns:
        key = str(campaign["id"])
        if key not in cursors:
            cursors[key] = _latest_cursor(int(campaign["id"]))
            changed = True
            continue
        rows = _new_attempts(int(campaign["id"]), cursors[key])
        if not rows:
            continue
        last_attempted_at = max(int(row["attempted_at"]) for row in rows)
        previous_cursor = cursors[key]
        seen = set(previous_cursor.get("seen") or []) if (
            int(previous_cursor.get("attempted_at") or 0) == last_attempted_at
        ) else set()
        seen.update(
            "%s:%s" % (row["id"], row["status"])
            for row in rows if int(row["attempted_at"]) == last_attempted_at
        )
        cursors[key] = {"attempted_at": last_attempted_at, "seen": sorted(seen)}
        last = max(rows, key=lambda row: (int(row["attempted_at"]), int(row["id"])))
        wave = pending.setdefault(key, {
            "campaign_id": int(campaign["id"]),
            "started_at": int(rows[0]["attempted_at"]),
            "last_activity_at": 0,
            "invited": [],
            "attempts": 0,
            "attempt_ids": [],
        })
        # Статус может измениться после контрольной проверки присутствия.
        # Не оставляем в отчёте приглашённых, которых проверка не подтвердила.
        invited_ids = {
            int(item["id"]) for item in _db_rows(
                "SELECT id FROM targets WHERE campaign_id=? AND status='invited'",
                (int(campaign["id"]),),
            )
        }
        wave["invited"] = [
            item for item in wave.get("invited", [])
            if int(item["id"]) in invited_ids
        ]
        wave["last_activity_at"] = max(
            int(wave.get("last_activity_at") or 0),
            int(last["attempted_at"]),
        )
        known_attempt_ids = {int(value) for value in wave.get("attempt_ids", [])}
        new_attempt_ids = {
            int(row["id"]) for row in rows if int(row["id"]) not in known_attempt_ids
        }
        wave["attempts"] = int(wave.get("attempts") or 0) + len(new_attempt_ids)
        wave["attempt_ids"] = sorted(known_attempt_ids | new_attempt_ids)
        known_ids = {int(item["id"]) for item in wave.get("invited", [])}
        for row in rows:
            if row["status"] == "invited" and int(row["id"]) not in known_ids:
                wave.setdefault("invited", []).append(row)
                known_ids.add(int(row["id"]))
        changed = True
    return changed


def _health_kind(working: bool, reason: str) -> str:
    if working:
        return "working"
    # Воркеры появляются не одновременно во время запуска. Такое короткое
    # промежуточное состояние не считаем срывом цикла.
    if reason == "воркер не запущен":
        return "unknown"
    return "failed"


def _update_failure_waves(
    state: Dict[str, Any],
    campaigns: Sequence[Dict[str, Any]],
    details: Dict[int, Dict[str, Any]],
    accounts: Sequence[Dict[str, Any]],
    now_ts: int,
) -> bool:
    """Добавляет общий отчёт при выпадении воркера без попытки по цели."""
    changed = False
    previous_health = state.setdefault("campaign_health", {})
    pending = state.setdefault("pending_waves", {})
    account_by_id = {int(item["id"]): item for item in accounts}

    for campaign in campaigns:
        campaign_id = int(campaign["id"])
        key = str(campaign_id)
        detail = details.get(campaign_id, campaign)
        running = bool(detail.get("running"))
        workers = {int(item["account_id"]): item for item in detail.get("workers", [])}
        account_ids = [int(value) for value in detail.get("settings", {}).get("account_ids", [])]
        current_accounts: Dict[str, str] = {}
        for account_id in account_ids:
            account = account_by_id.get(
                account_id, {"id": account_id, "status": "missing", "can_invite": 0}
            )
            working, reason = _account_reason(
                account, workers.get(account_id), running, now_ts
            )
            current_accounts[str(account_id)] = _health_kind(working, reason)

        current = {
            "running": running,
            "status": str(detail.get("status") or campaign.get("status") or ""),
            "accounts": current_accounts,
        }
        previous = previous_health.get(key)
        failure_started = False
        if isinstance(previous, dict):
            if bool(previous.get("running")) and not running:
                failure_started = True
            previous_accounts = previous.get("accounts") or {}
            if any(
                previous_accounts.get(account_id) == "working" and kind == "failed"
                for account_id, kind in current_accounts.items()
            ):
                failure_started = True

        if previous != current:
            previous_health[key] = current
            changed = True

        if failure_started:
            wave = pending.setdefault(key, {
                "campaign_id": campaign_id,
                "started_at": now_ts,
                "last_activity_at": 0,
                "invited": [],
                "attempts": 0,
            })
            wave["last_activity_at"] = max(
                int(wave.get("last_activity_at") or 0), now_ts
            )
            wave["failure_event"] = True
            changed = True

    return changed


def _account_reason(account: Dict[str, Any], worker: Optional[Dict[str, Any]],
                    running: bool, now_ts: int) -> Tuple[bool, str]:
    if not account.get("can_invite"):
        return False, "отключён"
    if account.get("status") != "authorized":
        return False, "не авторизован"
    state = str((worker or {}).get("state") or "")
    if int(account.get("cooldown_until") or 0) > now_ts:
        reason = str(account.get("last_error") or state or "защитная пауза")
        minutes = max(1, (int(account["cooldown_until"]) - now_ts + 59) // 60)
        return False, "%s, ещё %d мин" % (reason, minutes)
    if any(marker in state for marker in FATAL_STATE_MARKERS):
        return False, state
    if not running:
        return False, "кампания остановлена"
    if worker is None:
        return False, "воркер не запущен"
    return True, state or "работает"


def _format_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), MOSCOW_TZ).strftime("%d.%m %H:%M")


def _format_next_window(timestamps: Sequence[int], now_ts: int) -> str:
    future = sorted(int(value) for value in timestamps if int(value or 0) > now_ts)
    if not future:
        return "нет запланированного интервала"
    start = datetime.fromtimestamp(future[0], MOSCOW_TZ)
    end = datetime.fromtimestamp(future[-1], MOSCOW_TZ)
    if start.date() == end.date():
        return "%s, с %s до %s МСК" % (
            start.strftime("%d.%m"), start.strftime("%H:%M"), end.strftime("%H:%M")
        )
    return "с %s до %s МСК" % (_format_timestamp(future[0]), _format_timestamp(future[-1]))


def _display_target(target: Dict[str, Any]) -> str:
    username = str(target.get("username") or "").strip().lstrip("@")
    if username:
        return "@" + username
    display = str(target.get("display") or "").strip()
    return display or "ID %s" % target.get("user_id")


def _build_cycle_report(
    campaigns: Sequence[Dict[str, Any]],
    details: Dict[int, Dict[str, Any]],
    accounts: Sequence[Dict[str, Any]],
    pending_waves: Dict[str, Dict[str, Any]],
    now_ts: int,
) -> str:
    account_by_id = {int(item["id"]): item for item in accounts}
    lines = [
        "📊 Отчёт по циклу приглашений",
        datetime.fromtimestamp(now_ts, MOSCOW_TZ).strftime("%d.%m.%Y, %H:%M МСК"),
        "",
    ]
    next_windows: List[Tuple[str, str]] = []
    for campaign in campaigns:
        campaign_id = int(campaign["id"])
        detail = details.get(campaign_id, campaign)
        wave = pending_waves.get(str(campaign_id), {})
        invited = wave.get("invited", [])
        attempts = int(wave.get("attempts") or 0)
        if invited:
            cycle_result = "✅ цикл отработал"
        elif wave.get("failure_event") and not attempts:
            cycle_result = "❌ цикл не отработал — причины указаны ниже"
        elif attempts:
            cycle_result = "⚠️ цикл завершён без успешных приглашений"
        else:
            cycle_result = "⏳ в этом отчётном цикле попыток не зафиксировано"
        lines.extend([
            "Компания %s" % campaign["name"],
            "Результат: %s" % cycle_result,
            "Пригласили конкретно — %d человек" % len(invited),
            "Пользователи:",
        ])
        if invited:
            lines.extend("• %s" % _display_target(item) for item in invited)
        else:
            lines.append("• никого")

        workers = {int(item["account_id"]): item for item in detail.get("workers", [])}
        account_ids = [int(value) for value in detail.get("settings", {}).get("account_ids", [])]
        running = bool(detail.get("running"))
        active_next: List[int] = []
        lines.append("Аккаунты:")
        for account_id in account_ids:
            account = account_by_id.get(account_id, {"id": account_id, "label": str(account_id)})
            working, reason = _account_reason(account, workers.get(account_id), running, now_ts)
            icon = "✅" if working else "❌"
            lines.append("%s %s — %s" % (icon, account.get("label") or account_id, reason))
            if working:
                active_next.append(int(account.get("next_attempt_at") or 0))
        next_windows.append((campaign["name"], _format_next_window(active_next, now_ts)))
        lines.append("")

    lines.append("Следующий интервал приглашения")
    for name, window in next_windows:
        lines.append("%s: %s" % (name, window))
    return "\n".join(lines).strip()


def _cycle_ready(state: Dict[str, Any], now_ts: int) -> bool:
    waves = list(state.get("pending_waves", {}).values())
    if not waves:
        return False
    return all(
        now_ts - int(wave.get("last_activity_at") or 0) >= SETTLE_SECONDS
        for wave in waves
    )


def _send_cycle_report(state: Dict[str, Any], campaigns: Sequence[Dict[str, Any]],
                       now_ts: int) -> None:
    if not campaigns:
        return
    details = {
        int(campaign["id"]): _api_request("/campaigns/%d" % int(campaign["id"]))
        for campaign in campaigns
    }
    accounts = _api_request("/accounts")
    text = _build_cycle_report(
        campaigns, details, accounts, state.get("pending_waves", {}), now_ts
    )
    _send_bot_message(text)
    state["pending_waves"] = {}
    _save_state(state)
    print("Групповой отчёт по циклу отправлен", flush=True)


def _send_current_report(state: Dict[str, Any], now_ts: int) -> None:
    campaigns = _current_campaigns()
    if not campaigns:
        print("Актуальный отчёт не отправлен: работающих кампаний нет", flush=True)
        return
    details = {
        int(campaign["id"]): _api_request("/campaigns/%d" % int(campaign["id"]))
        for campaign in campaigns
    }
    accounts = _api_request("/accounts")
    text = _build_cycle_report(
        campaigns, details, accounts, state.get("pending_waves", {}), now_ts
    )
    _send_bot_message(text)
    print("Актуальный отчёт отправлен по запросу из бота", flush=True)


def _poll_bot_commands(state: Dict[str, Any]) -> None:
    _, chat_id = _bot_credentials()
    if not chat_id:
        return
    offset = state.get("bot_update_offset")
    request_payload: Dict[str, Any] = {
        "timeout": 0,
        "limit": 100,
        "allowed_updates": ["message", "callback_query"],
    }
    if offset:
        request_payload["offset"] = int(offset)
    updates = _bot_request("getUpdates", request_payload) or []

    # Первый запуск только отмечает старые обновления прочитанными: бот не
    # должен внезапно ответить на накопленные за прошлые дни команды.
    if offset is None:
        state["bot_update_offset"] = (
            max((int(item.get("update_id") or 0) for item in updates), default=-1) + 1
        )
        _save_state(state)
        return

    changed = False
    for update in updates:
        update_id = int(update.get("update_id") or 0)
        callback = update.get("callback_query") or {}
        callback_message = callback.get("message") or {}
        callback_chat = callback_message.get("chat") or {}
        message = update.get("message") or {}
        message_chat = message.get("chat") or {}
        text = str(message.get("text") or "").strip()
        requested = (
            int(message_chat.get("id") or 0) == int(chat_id)
            and (
                text == BOT_REPORT_BUTTON
                or text == "🔄 Обновить отчёт"
                or text.startswith("/status")
            )
        )
        if (
            callback.get("data") == BOT_REFRESH_CALLBACK
            and int(callback_chat.get("id") or 0) == int(chat_id)
        ):
            _bot_request("answerCallbackQuery", {
                "callback_query_id": callback.get("id"),
                "text": "Обновляю данные",
            })
            requested = True
        if requested:
            _send_current_report(state, int(time.time()))
        if update_id:
            state["bot_update_offset"] = update_id + 1
            changed = True
    if changed:
        _save_state(state)


def _day_bounds(day: date) -> Tuple[int, int]:
    start = datetime.combine(day, datetime_time.min, tzinfo=MOSCOW_TZ)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def _invited_between(start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
    return _db_rows(
        """
        SELECT t.user_id, t.username, t.display, t.attempted_at, c.name campaign_name
        FROM targets t JOIN campaigns c ON c.id=t.campaign_id
        WHERE c.target_chat_id=? AND t.status='invited'
          AND t.attempted_at>=? AND t.attempted_at<?
        ORDER BY t.attempted_at, t.id
        """,
        (TARGET_CHAT_ID, start_ts, end_ts),
    )


def _all_invited() -> List[Dict[str, Any]]:
    return _db_rows(
        """
        SELECT t.user_id, t.username, t.display, MAX(t.attempted_at) attempted_at
        FROM targets t JOIN campaigns c ON c.id=t.campaign_id
        WHERE c.target_chat_id=? AND t.status='invited'
        GROUP BY t.user_id, t.username, t.display
        """,
        (TARGET_CHAT_ID,),
    )


def _working_sync_account() -> int:
    accounts = _api_request("/accounts")
    campaigns = _current_campaigns()
    active_ids: Set[int] = set()
    now_ts = int(time.time())
    for campaign in campaigns:
        detail = _api_request("/campaigns/%d" % int(campaign["id"]))
        workers = {int(item["account_id"]): item for item in detail.get("workers", [])}
        for account in accounts:
            account_id = int(account["id"])
            if account_id not in workers:
                continue
            working, _ = _account_reason(account, workers[account_id], bool(detail.get("running")), now_ts)
            if working and account.get("can_parse"):
                active_ids.add(account_id)
    candidates = [item for item in accounts if int(item["id"]) in active_ids]
    if not candidates:
        candidates = [
            item for item in accounts
            if item.get("status") == "authorized" and item.get("can_parse")
            and item.get("can_invite") and int(item.get("cooldown_left") or 0) <= 0
        ]
    if not candidates:
        raise RuntimeError("Нет доступного аккаунта для проверки состава чата")
    return int(max(candidates, key=lambda item: int(item.get("next_attempt_in") or 0))["id"])


def _load_all_members(chat_id: int) -> List[Dict[str, Any]]:
    members: List[Dict[str, Any]] = []
    limit = 1000
    offset = 0
    while True:
        page = _api_request("/members?chat_id=%d&limit=%d&offset=%d" % (chat_id, limit, offset))
        items = page.get("items", [])
        members.extend(items)
        if not items or len(members) >= int(page.get("total") or 0):
            break
        offset += limit
    return members


def _fresh_membership(previous_count: int = 0) -> Tuple[List[Dict[str, Any]], int, int]:
    account_id = _working_sync_account()
    started_at = int(time.time()) - 2
    result = _api_request(
        "/campaigns/sync-target",
        {"account_id": account_id, "target_chat": TARGET_CHAT},
        timeout=900,
    )
    stored = _load_all_members(int(result["chat_id"]))
    current = [
        {
            "user_id": str(item["user_id"]),
            "username": str(item.get("username") or "").strip().lstrip("@"),
        }
        for item in stored
        if int(item.get("updated_at") or 0) >= started_at
    ]
    reference = int(previous_count or 0)
    if not current:
        raise RuntimeError("Telegram не вернул текущий состав чата")
    if reference >= 10 and len(current) < int(reference * 0.7):
        raise RuntimeError("Telegram вернул подозрительно неполный состав чата")
    return current, int(result["chat_id"]), account_id


def _identity_key(person: Dict[str, Any]) -> str:
    username = str(person.get("username") or "").strip().lstrip("@").lower()
    return "u:" + username if username else "id:" + str(person.get("user_id") or "")


def _member_indexes(members: Sequence[Dict[str, Any]]) -> Tuple[Set[str], Set[str]]:
    ids = {str(item.get("user_id")) for item in members if item.get("user_id") is not None}
    usernames = {
        str(item.get("username") or "").strip().lstrip("@").lower()
        for item in members if str(item.get("username") or "").strip()
    }
    return ids, usernames


def _present(person: Dict[str, Any], indexes: Tuple[Set[str], Set[str]]) -> bool:
    ids, usernames = indexes
    resolved_user_id = person.get("resolved_user_id")
    if resolved_user_id:
        # A username may be recycled by Telegram. Once preflight resolved the
        # real numeric identity, a same-name account must never confirm it.
        return str(resolved_user_id) in ids
    user_id = str(person.get("user_id") or "")
    username = str(person.get("username") or "").strip().lstrip("@").lower()
    return bool((user_id and user_id in ids) or (username and username in usernames))


def _confirmation_candidates(now_ts: int) -> List[Dict[str, Any]]:
    return _db_rows(
        """
        SELECT t.id, t.campaign_id, t.user_id, t.resolved_user_id,
               t.username, t.display,
               t.account_id, t.attempted_at, t.status
        FROM targets t
        JOIN campaigns c ON c.id=t.campaign_id
        LEFT JOIN invite_confirmations v ON v.target_id=t.id
        WHERE c.target_chat_id=? AND c.status IN ('running','paused','done')
          AND v.target_id IS NULL
          AND t.attempted_at IS NOT NULL AND t.attempted_at<=?
          AND t.status='verifying'
          AND (
              t.error LIKE ?
              OR t.error LIKE 'запрос отправлен, проверяю фактическое присутствие%'
              OR t.error LIKE 'Не удалось достоверно подтвердить присутствие%'
          )
        ORDER BY t.attempted_at, t.id
        """,
        (
            TARGET_CHAT_ID,
            now_ts - INVITE_CONFIRM_DELAY_SECONDS,
            INVITE_RPC_DURABLE_MARKER + "%",
        ),
    )


def _reject_unconfirmed_target(
    connection: sqlite3.Connection,
    target: Dict[str, Any],
    status: str,
    error: str,
    result: str,
    member_count: int,
    now_ts: int,
) -> bool:
    target_id = int(target["id"])
    # Candidate rows are loaded before BEGIN IMMEDIATE. Core confirmation may
    # win that race, so decisions must use the current row under the writer
    # transaction and may only transition the still-ambiguous state.
    current = connection.execute(
        "SELECT * FROM targets WHERE id=?",
        (target_id,),
    ).fetchone()
    if current is None or str(current["status"] or "") != "verifying":
        return False

    account_id = int(current["account_id"] or 0)
    changed = connection.execute(
        """
        UPDATE targets SET status=?, error=?
        WHERE id=? AND status='verifying'
        """,
        (status, error, target_id),
    ).rowcount
    if not changed:
        return False
    connection.execute(
        """
        INSERT OR REPLACE INTO invite_confirmations
            (target_id,checked_at,result,member_count)
        VALUES (?,?,?,?)
        """,
        (target_id, now_ts, result, member_count),
    )
    if not account_id:
        return True
    # Неуспех не расходует суточную квоту, но Telegram уже получил запрос.
    # Сохраняем защитный интервал аккаунта, чтобы немедленный повтор не вызвал
    # PEER_FLOOD. Следующая цель будет обработана по обычному расписанию.
    connection.execute(
        """
        INSERT INTO events (ts,level,scope,campaign_id,account_id,message)
        VALUES (?,'warn','invite',?,?,?)
        """,
        (now_ts, int(current["campaign_id"]), account_id, error),
    )
    return True


def _confirm_present_target(
    connection: sqlite3.Connection,
    target: Dict[str, Any],
    member_count: int,
    now_ts: int,
) -> bool:
    """Засчитывает приглашение только после подтверждённого присутствия."""
    target_id = int(target["id"])
    # candidates загружаются до BEGIN IMMEDIATE. За это время core мог уже
    # подтвердить ту же цель, поэтому stale dict нельзя использовать для
    # решения о переходе и счётчиках.
    current = connection.execute(
        "SELECT * FROM targets WHERE id=?",
        (target_id,),
    ).fetchone()
    if current is None or str(current["status"] or "") != "verifying":
        return False

    account_id = int(current["account_id"] or 0)
    connection.execute(
        """
        INSERT OR REPLACE INTO invite_confirmations
            (target_id,checked_at,result,member_count)
        VALUES (?,?, 'confirmed', ?)
        """,
        (target_id, now_ts, member_count),
    )
    changed = connection.execute(
        """
        UPDATE targets SET status='invited',error=NULL
        WHERE id=? AND status='verifying'
        """,
        (target_id,),
    ).rowcount
    if not changed:
        return False

    if account_id:
        counter_day = date.today().isoformat()
        connection.execute(
            """
            UPDATE accounts
            SET invites_today=CASE WHEN counter_day=? THEN invites_today+1 ELSE 1 END,
                successful_today=CASE WHEN counter_day=? THEN successful_today+1 ELSE 1 END,
                counter_day=?
            WHERE id=?
            """,
            (counter_day, counter_day, counter_day, account_id),
        )

    identity = (
        current["username"]
        or current["resolved_user_id"]
        or current["user_id"]
    )
    label = "@" + str(identity).lstrip("@") if current["username"] else str(identity)
    connection.execute(
        """
        INSERT INTO events (ts,level,scope,campaign_id,account_id,message)
        VALUES (?,'info','invite',?,?,?)
        """,
        (
            now_ts,
            int(current["campaign_id"]),
            account_id or None,
            "Приглашён %s" % label,
        ),
    )
    return True


def _confirm_pending_invites(state: Dict[str, Any], now_ts: int) -> bool:
    """Подтверждает успех только свежим составом целевого чата."""
    candidates = _confirmation_candidates(now_ts)
    if not candidates:
        return False

    previous = state.get("membership") or {}
    previous_count = len(previous.get("current_members") or [])
    current, chat_id, account_id = _fresh_membership(previous_count)
    indexes = _member_indexes(current)
    state["membership"] = {
        "chat_id": chat_id,
        "synced_at": now_ts,
        "account_id": account_id,
        "current_members": current,
    }

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for target in candidates:
        grouped.setdefault(_target_identity(target), []).append(target)

    confirmed = 0
    rejected = 0
    duplicates = 0
    with _write_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for targets in grouped.values():
            present = _present(targets[0], indexes)
            ordered = sorted(
                targets,
                key=lambda item: (
                    int(item.get("attempted_at") or 0), int(item["id"])
                ),
            )
            if present:
                winner = ordered[0]
                if _confirm_present_target(connection, winner, len(current), now_ts):
                    confirmed += 1
                for duplicate in ordered[1:]:
                    if _reject_unconfirmed_target(
                        connection,
                        duplicate,
                        "skipped",
                        "дубль подтверждённого приглашения параллельной кампании",
                        "duplicate",
                        len(current),
                        now_ts,
                    ):
                        duplicates += 1
            else:
                # Полный snapshot Telegram может быть усечён для больших чатов
                # или при скрытых участниках. Поэтому отсутствие в нём — не
                # доказательство неуспеха. Reporter остаётся только резервным
                # источником положительного подтверждения; отрицательный итог
                # даёт точечный getParticipant в основном процессе.
                continue

    if confirmed or rejected or duplicates:
        print(
            "Проверка приглашений: подтверждено %d, не подтверждено %d, дублей %d"
            % (confirmed, rejected, duplicates),
            flush=True,
        )
    return True


def _daily_departures(
    previous_current: Sequence[Dict[str, Any]],
    current: Sequence[Dict[str, Any]],
    invited_today: Sequence[Dict[str, Any]],
    all_invited: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    previous_indexes = _member_indexes(previous_current)
    current_indexes = _member_indexes(current)
    invited_today_keys = {_identity_key(item) for item in invited_today}
    unique_invited = {_identity_key(item): item for item in all_invited}
    return [
        person for key, person in unique_invited.items()
        if (_present(person, previous_indexes) or key in invited_today_keys)
        and not _present(person, current_indexes)
    ]


def _ensure_membership_baseline(state: Dict[str, Any]) -> None:
    if state.get("membership"):
        return
    current, chat_id, account_id = _fresh_membership()
    state["membership"] = {
        "chat_id": chat_id,
        "synced_at": int(time.time()),
        "account_id": account_id,
        "current_members": current,
    }
    _save_state(state)
    print("Создан базовый снимок состава: %d участников" % len(current), flush=True)


def _send_daily_report(state: Dict[str, Any], now: datetime) -> None:
    day_start, next_day = _day_bounds(now.date())
    cutoff = min(int(now.timestamp()) + 1, next_day)
    invited = _invited_between(day_start, cutoff)
    invited_unique = {_identity_key(item): item for item in invited}
    previous = state.get("membership") or {}
    previous_current = list(previous.get("current_members", []))
    current, chat_id, account_id = _fresh_membership(len(previous_current))
    left = _daily_departures(
        previous_current, current, invited, _all_invited()
    )
    lines = [
        "🌙 Итоги дня — %s" % now.strftime("%d.%m.%Y"),
        "Приглашено за день: %d" % len(invited_unique),
        "Отписалось по проверенному составу: %d" % len(left),
        "Сейчас участников в чате: %d" % len(current),
        "Проверка выполнена: %s МСК" % datetime.now(MOSCOW_TZ).strftime("%H:%M"),
    ]
    _send_bot_message("\n".join(lines))
    state["last_daily_date"] = now.date().isoformat()
    state["membership"] = {
        "chat_id": chat_id,
        "synced_at": int(time.time()),
        "account_id": account_id,
        "current_members": current,
    }
    _save_state(state)
    print("Ежедневный отчёт отправлен", flush=True)


def _daily_due(state: Dict[str, Any], now: datetime) -> bool:
    return (
        now.hour == 23
        and now.minute >= 59
        and state.get("last_daily_date") != now.date().isoformat()
    )


def run() -> None:
    state = _load_state()
    _ensure_invite_confirmation_schema()
    while True:
        try:
            deduplicated = _dedupe_running_targets()
            if deduplicated:
                print(
                    "Исключены общие цели работающих кампаний: %d" % deduplicated,
                    flush=True,
                )
            campaigns = _current_campaigns()
            now_ts = int(time.time())
            changed = _confirm_pending_invites(state, now_ts)
            if _prune_inactive_campaign_state(state, campaigns):
                changed = True
            if _update_pending_waves(state, campaigns):
                changed = True
            details = {
                int(campaign["id"]): _api_request(
                    "/campaigns/%d" % int(campaign["id"])
                )
                for campaign in campaigns
            }
            accounts = _api_request("/accounts")
            if _update_failure_waves(
                state, campaigns, details, accounts, now_ts
            ):
                changed = True
            if changed:
                _save_state(state)
            if _cycle_ready(state, now_ts):
                _send_cycle_report(state, campaigns, now_ts)
            if BOT_COMMANDS_ENABLED:
                _poll_bot_commands(state)
            now = datetime.now(MOSCOW_TZ)
            if campaigns and not state.get("membership"):
                _ensure_membership_baseline(state)
            if campaigns and _daily_due(state, now):
                _send_daily_report(state, now)
        except (urllib.error.URLError, TimeoutError, sqlite3.Error, RuntimeError, ValueError) as error:
            print("Ошибка отчётчика: %s" % error, flush=True)
        except Exception as error:
            print("Непредвиденная ошибка отчётчика: %s" % error, flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
