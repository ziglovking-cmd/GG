"""Пул Telethon-клиентов: авторизация аккаунтов, прокси, учёт суточных лимитов."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import time
from datetime import date
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    AuthKeyUnregisteredError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    SessionPasswordNeededError,
    UserDeactivatedBanError,
)

from . import db
from .config import (
    SESSIONS_DIR,
    SILENT_LOSS_LOOKBACK_SECONDS,
    SILENT_LOSS_RESTRICT_THRESHOLD,
    get_api_credentials,
)
from .domain.invitations import phone_country

# account_id -> TelegramClient
_clients: Dict[int, TelegramClient] = {}
# Не допускаем одновременную работу нескольких запросов с одним SQLite-файлом
# Telethon-сессии (например, при повторном нажатии кнопки проверки прокси).
_account_locks: Dict[int, asyncio.Lock] = {}
# account_id -> phone_code_hash, живёт только на время авторизации
_pending_code: Dict[int, str] = {}


class AuthError(Exception):
    pass


def parse_proxy(raw: Optional[str]):
    """'socks5://user:pass@host:1080' -> кортеж прокси для Telethon. None если пусто."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    if "://" not in raw:
        raw = "socks5://" + raw
    u = urlparse(raw)
    scheme = (u.scheme or "socks5").lower()
    if not u.hostname or not u.port:
        raise AuthError("Прокси должен быть в формате socks5://user:pass@host:port")
    if scheme in ("socks5", "socks4", "http"):
        # словарь -> Telethon использует python-socks (asyncio), без PySocks
        cfg = {"proxy_type": scheme, "addr": u.hostname, "port": u.port, "rdns": True}
        if u.username:
            cfg["username"] = u.username
            cfg["password"] = u.password or ""
        return cfg
    if scheme in ("mtproxy", "mtproto"):
        secret = u.username or u.password or ""
        if not secret:
            raise AuthError("Для mtproxy нужен секрет: mtproxy://SECRET@host:port")
        return (u.hostname, u.port, secret)
    raise AuthError("Неизвестный тип прокси: " + scheme)


def proxy_endpoint(raw: Optional[str]) -> Optional[str]:
    """Стабильный ключ прокси без пароля: host:port (схема игнорируется)."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    if "://" not in text:
        text = "socks5://" + text
    parsed = urlparse(text)
    if not parsed.hostname or not parsed.port:
        return None
    return "%s:%d" % (parsed.hostname.lower(), int(parsed.port))


def shared_proxy_accounts(
    proxy: Optional[str],
    *,
    exclude_account_id: Optional[int] = None,
    invite_only: bool = True,
) -> list[Dict[str, Any]]:
    """Аккаунты, уже сидящие на том же host:port."""
    endpoint = proxy_endpoint(proxy)
    if not endpoint:
        return []
    rows = db.rows_to_dicts(
        db.q(
            """
            SELECT id, label, phone, proxy, can_invite, status
            FROM accounts
            ORDER BY id
            """
        )
    )
    shared: list[Dict[str, Any]] = []
    for row in rows:
        if exclude_account_id is not None and int(row["id"]) == int(exclude_account_id):
            continue
        if invite_only and not int(row.get("can_invite") or 0):
            continue
        if proxy_endpoint(row.get("proxy")) == endpoint:
            shared.append(row)
    return shared


def assert_unique_invite_proxy(
    proxy: Optional[str],
    *,
    account_id: Optional[int] = None,
    can_invite: bool = True,
) -> None:
    """Легитимное правило: один invite-аккаунт — один endpoint прокси."""
    if not can_invite:
        return
    if not proxy or not str(proxy).strip():
        raise AuthError(
            "Для инвайтинга нужен отдельный стабильный прокси (1 аккаунт = 1 IP). "
            "Без прокси Telegram связывает аккаунты по вашему IP."
        )
    twins = shared_proxy_accounts(proxy, exclude_account_id=account_id, invite_only=True)
    if twins:
        labels = ", ".join(
            str(row.get("label") or row.get("phone") or row["id"]) for row in twins[:5]
        )
        raise AuthError(
            "Этот прокси (host:port) уже используется другим инвайтером: %s. "
            "Нужен отдельный стабильный IP на каждый аккаунт — ротация двух IP "
            "на одном аккаунте не помогает."
            % labels
        )


def register_delivery_outcome(account_id: int, outcome: str) -> Optional[str]:
    """После тихих потерь без confirmed снимает аккаунт с ротации.

    Не обходит лимиты Telegram: просто перестаёт жечь плохой аккаунт/IP.
    """
    if outcome != "unconfirmed":
        return None
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (int(account_id),)))
    if not account or bool(account.get("invite_restricted")):
        return None
    since = int(time.time()) - int(SILENT_LOSS_LOOKBACK_SECONDS)
    silent = db.q1(
        """
        SELECT COUNT(*) c
        FROM invite_confirmations c
        JOIN targets t ON t.id = c.target_id
        WHERE t.account_id=? AND c.result='not_present' AND c.checked_at>=?
        """,
        (int(account_id), since),
    )
    confirmed = db.q1(
        """
        SELECT COUNT(*) c
        FROM invite_confirmations c
        JOIN targets t ON t.id = c.target_id
        WHERE t.account_id=? AND c.result='confirmed' AND c.checked_at>=?
        """,
        (int(account_id), since),
    )
    silent_count = int(silent["c"] if silent else 0)
    confirmed_count = int(confirmed["c"] if confirmed else 0)
    if silent_count < int(SILENT_LOSS_RESTRICT_THRESHOLD) or confirmed_count > 0:
        return None
    reason = (
        "Тихие потери: Telegram принял Invite RPC, но пользователя в чате нет "
        "(%d раз за 7 дней без confirmed). Аккаунт снят с ротации — смените на "
        "отдельный стабильный residential/mobile IP и прогрейте аккаунт, затем "
        "восстановите вручную."
        % silent_count
    )
    restrict_invites(int(account_id), reason)
    db.log(reason, level="error", scope="invite", account_id=int(account_id))
    return reason


def build_client(account: Dict[str, Any]) -> TelegramClient:
    api_id, api_hash = get_api_credentials()
    if not api_id or not api_hash:
        raise AuthError("Не заданы api_id / api_hash. Укажите их на вкладке «Настройки».")

    proxy_raw = account.get("proxy")
    proxy = parse_proxy(proxy_raw)
    kwargs: Dict[str, Any] = {
        "device_model": "Desktop",
        "system_version": "Windows 10",
        "app_version": "5.3.1 x64",
        "proxy": proxy,
        # InviteToChannelRequest/AddChatUserRequest are non-idempotent.  Telethon
        # otherwise retries some RPC/server failures internally (and its sender
        # re-sends pending requests after auto-reconnect), bypassing the durable
        # at-most-once state machine in app.inviting.
        "request_retries": 0,
        "auto_reconnect": False,
        "flood_sleep_threshold": 0,
        "raise_last_call_error": True,
    }
    if proxy_raw and proxy_raw.strip().lower().startswith(("mtproxy", "mtproto")):
        from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

        kwargs["connection"] = ConnectionTcpMTProxyRandomizedIntermediate

    session_path = str(SESSIONS_DIR / account["session_name"])
    return TelegramClient(session_path, api_id, api_hash, **kwargs)


async def get_client(account_id: int, connect: bool = True) -> TelegramClient:
    client = _clients.get(account_id)
    if client is None:
        account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
        if not account:
            raise AuthError("Аккаунт не найден")
        client = build_client(account)
        _clients[account_id] = client
    if connect and not client.is_connected():
        await client.connect()
    return client


async def drop_client(account_id: int) -> None:
    client = _clients.pop(account_id, None)
    if client is None:
        return
    # После таймаута connect() клиент может считать себя отключённым, но его
    # SQLite-сессия всё ещё остаётся открытой. Закрываем оба ресурса явно.
    with suppress(Exception):
        await client.disconnect()
    with suppress(Exception):
        client.session.close()


def set_status(account_id: int, status: str, error: Optional[str] = None) -> None:
    db.ex("UPDATE accounts SET status=?, last_error=? WHERE id=?", (status, error, account_id))


async def refresh_status(account_id: int) -> str:
    """Проверяет фактическую авторизацию и обновляет карточку аккаунта."""
    try:
        client = await get_client(account_id)
        if await client.is_user_authorized():
            me = await client.get_me()
            db.ex(
                "UPDATE accounts SET status='authorized', tg_user_id=?, tg_username=?, "
                "is_premium=?, last_error=NULL WHERE id=?",
                (me.id, me.username, int(bool(getattr(me, "premium", False))), account_id),
            )
            return "authorized"
        set_status(account_id, "new")
        return "new"
    except (AuthKeyUnregisteredError, UserDeactivatedBanError) as e:
        set_status(account_id, "banned", str(e))
        return "banned"
    except Exception as e:  # прокси недоступен, неверный api_id и т.п.
        set_status(account_id, "error", str(e))
        return "error"


async def test_proxy(account_id: int) -> Dict[str, Any]:
    """Проверяет, что через заданный прокси доходит рукопожатие с Telegram."""
    lock = _account_locks.setdefault(account_id, asyncio.Lock())
    async with lock:
        return await _test_proxy_locked(account_id)


async def _test_proxy_locked(account_id: int) -> Dict[str, Any]:
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
    if not account:
        raise AuthError("Аккаунт не найден")

    await drop_client(account_id)  # чистое соединение, а не переиспользованное
    started = time.time()
    try:
        client = await get_client(account_id, connect=False)
        await asyncio.wait_for(client.connect(), timeout=25)
    except asyncio.TimeoutError:
        await drop_client(account_id)
        db.log("Прокси не отвечает: таймаут подключения", level="error",
               scope="proxy", account_id=account_id)
        return {"ok": False, "error": "Таймаут: прокси не отвечает за 25 секунд"}
    except Exception as e:
        await drop_client(account_id)
        db.log("Прокси не работает: %s" % e, level="error", scope="proxy", account_id=account_id)
        return {"ok": False, "error": str(e)}

    latency = int((time.time() - started) * 1000)
    try:
        authorized = await client.is_user_authorized()
    except Exception:
        authorized = False

    dc = getattr(getattr(client.session, "dc_id", None), "real", None) or client.session.dc_id
    verdict = "хорошо" if latency < 800 else "медленно" if latency < 2500 else "очень медленно"
    db.log("Прокси проверен: подключение %d мс (%s), DC %s" % (latency, verdict, dc),
           scope="proxy", account_id=account_id)
    return {"ok": True, "latency_ms": latency, "verdict": verdict,
            "dc": dc, "authorized": authorized,
            "proxy": bool(account.get("proxy"))}


async def send_code(account_id: int) -> str:
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
    if not account:
        raise AuthError("Аккаунт не найден")
    client = await get_client(account_id)
    if await client.is_user_authorized():
        await refresh_status(account_id)
        return "authorized"
    try:
        sent = await client.send_code_request(account["phone"])
    except ApiIdInvalidError:
        raise AuthError("api_id / api_hash неверны")
    except PhoneNumberBannedError:
        set_status(account_id, "banned", "Номер заблокирован Telegram")
        raise AuthError("Номер заблокирован Telegram")
    _pending_code[account_id] = sent.phone_code_hash
    set_status(account_id, "needs_code")
    db.log("Код отправлен на " + account["phone"], scope="auth", account_id=account_id)
    return "needs_code"


async def sign_in(account_id: int, code: str) -> str:
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
    if not account:
        raise AuthError("Аккаунт не найден")
    client = await get_client(account_id)
    phone_code_hash = _pending_code.get(account_id)
    if not phone_code_hash:
        raise AuthError("Сначала запросите код")
    try:
        await client.sign_in(
            phone=account["phone"], code=code.strip(), phone_code_hash=phone_code_hash
        )
    except SessionPasswordNeededError:
        set_status(account_id, "needs_password")
        return "needs_password"
    except PhoneCodeInvalidError:
        raise AuthError("Неверный код")
    except PhoneCodeExpiredError:
        _pending_code.pop(account_id, None)
        raise AuthError("Код истёк, запросите новый")
    _pending_code.pop(account_id, None)
    return await refresh_status(account_id)


async def sign_in_password(account_id: int, password: str) -> str:
    client = await get_client(account_id)
    try:
        await client.sign_in(password=password)
    except Exception as e:
        raise AuthError("Пароль двухфакторной аутентификации не подошёл: %s" % e)
    _pending_code.pop(account_id, None)
    return await refresh_status(account_id)


async def logout(account_id: int) -> None:
    try:
        client = await get_client(account_id)
        if await client.is_user_authorized():
            await client.log_out()
    except Exception:
        pass
    await drop_client(account_id)
    set_status(account_id, "new")


# ---------------------------------------------------------------- лимиты

def _today() -> str:
    return date.today().isoformat()


def roll_counter(account: Dict[str, Any]) -> Dict[str, Any]:
    """Сбрасывает суточный счётчик при смене даты."""
    if account.get("counter_day") != _today():
        db.ex(
            "UPDATE accounts SET invites_today=0, successful_today=0, counter_day=? WHERE id=?",
            (_today(), account["id"]),
        )
        account = dict(account, invites_today=0, successful_today=0, counter_day=_today())
    return account


def schedule_next_attempt(account_id: int, delay: int, now: Optional[int] = None) -> int:
    """Сохраняет следующий допустимый момент; переживает остановку и перезапуск."""
    next_at = int(now if now is not None else time.time()) + max(0, int(delay))
    db.ex("UPDATE accounts SET next_attempt_at=? WHERE id=?", (next_at, account_id))
    return next_at


def release_next_attempt(account_id: int, reserved_at: int) -> int:
    """Отменяет именно эту бронь интервала после пропуска по приватности.

    Условие по reserved_at не позволяет стереть более новую бронь, если тот же
    аккаунт уже успела использовать другая кампания.
    """
    db.ex(
        "UPDATE accounts SET next_attempt_at=0 WHERE id=? AND next_attempt_at=?",
        (account_id, int(reserved_at)),
    )
    row = db.q1("SELECT next_attempt_at FROM accounts WHERE id=?", (account_id,))
    return int(row["next_attempt_at"] if row else 0)


def defer_next_attempt(account_id: int, seconds: int, now: Optional[int] = None) -> int:
    """Продлевает ожидание, но никогда не сокращает уже установленный интервал."""
    candidate = int(now if now is not None else time.time()) + max(0, int(seconds))
    db.ex(
        "UPDATE accounts SET next_attempt_at="
        "CASE WHEN next_attempt_at>? THEN next_attempt_at ELSE ? END WHERE id=?",
        (candidate, candidate, account_id),
    )
    row = db.q1("SELECT next_attempt_at FROM accounts WHERE id=?", (account_id,))
    return int(row["next_attempt_at"] if row else candidate)


def set_cooldown(account_id: int, seconds: int, reason: str = "") -> None:
    until = int(time.time()) + max(0, int(seconds))
    db.ex("UPDATE accounts SET cooldown_until=? WHERE id=?", (until, account_id))
    if reason:
        db.log(
            "Аккаунт на паузе %d мин: %s" % (max(1, seconds // 60), reason),
            level="warn",
            scope="limits",
            account_id=account_id,
        )


def restrict_invites(account_id: int, reason: str) -> None:
    """Ставит бессрочный защитный блок до явного восстановления оператором."""
    now_ts = int(time.time())
    db.ex(
        """
        UPDATE accounts
        SET invite_restricted=1,
            invite_restriction_reason=?,
            invite_restricted_at=?,
            last_error=?
        WHERE id=?
        """,
        (reason[:300], now_ts, reason[:300], account_id),
    )


def restore_invites(account_id: int, now: Optional[int] = None) -> None:
    """Явно снимает постоянный блок, но не позволяет обойти активный cooldown."""
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
    if not account:
        raise AuthError("Аккаунт не найден")
    now_ts = int(now if now is not None else time.time())
    cooldown_left = int(account.get("cooldown_until") or 0) - now_ts
    if cooldown_left > 0:
        raise AuthError(
            "Защитная пауза Telegram ещё действует: %d мин"
            % max(1, (cooldown_left + 59) // 60)
        )
    if account.get("status") != "authorized":
        raise AuthError("Сначала подтвердите авторизацию Telegram-сессии")
    db.ex(
        """
        UPDATE accounts
        SET invite_restricted=0,
            invite_restriction_reason=NULL,
            invite_restricted_at=NULL,
            last_error=CASE
                WHEN UPPER(COALESCE(last_error,'')) LIKE '%PEER_FLOOD%'
                THEN NULL ELSE last_error END
        WHERE id=?
        """,
        (account_id,),
    )


def quota_left(account: Dict[str, Any]) -> int:
    """Суточный лимит относится только к подтверждённым приглашениям.

    Приватность, удалённый пользователь, переполненный список чатов и
    технические ошибки не должны лишать аккаунт следующего реального инвайта.
    """
    account = roll_counter(account)
    return max(0, int(account["daily_limit"]) - int(account["successful_today"]))


def invite_eligibility(
    account: Optional[Dict[str, Any]],
    *,
    now: Optional[int] = None,
    check_cooldown: bool = True,
    check_quota: bool = True,
) -> Tuple[bool, str, str]:
    """Единое решение о допуске аккаунта к отправке приглашения.

    Возвращает ``(eligible, code, detail)``. Постоянное ограничение имеет
    приоритет над истёкшим cooldown, поэтому PEER_FLOOD никогда не исчезает из
    ротации автоматически через сутки.
    """
    if not account:
        return False, "missing", "Аккаунт удалён"
    if account.get("status") != "authorized":
        return False, "unauthorized", "Telegram-сессия не авторизована"
    if not account.get("can_invite"):
        return False, "disabled", "Инвайтинг отключён в карточке аккаунта"
    if bool(account.get("invite_restricted")):
        reason = str(
            account.get("invite_restriction_reason")
            or "Telegram ограничил приглашения"
        )
        return (
            False,
            "restricted",
            "%s; требуется явное ручное восстановление" % reason,
        )

    now_ts = int(now if now is not None else time.time())
    if check_cooldown:
        cooldown_left = int(account.get("cooldown_until") or 0) - now_ts
        if cooldown_left > 0:
            return (
                False,
                "cooldown",
                "Защитная пауза Telegram ещё %d мин"
                % max(1, (cooldown_left + 59) // 60),
            )
    if check_quota and quota_left(account) <= 0:
        return False, "quota", "Суточный лимит подтверждённых приглашений исчерпан"
    return True, "ready", "Аккаунт допущен к инвайтингу"


def is_available(account: Dict[str, Any]) -> bool:
    return invite_eligibility(account)[0]


def mark_warmup(
    account_id: int,
    done: bool = True,
    notes: str = "",
) -> Dict[str, Any]:
    """Оператор подтверждает ручной прогрев аккаунта перед force/hybrid."""
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
    if not account:
        raise AuthError("Аккаунт не найден")
    now_ts = int(time.time())
    db.ex(
        """
        UPDATE accounts
        SET warmup_done=?, warmup_checked_at=?, warmup_notes=?
        WHERE id=?
        """,
        (1 if done else 0, now_ts if done else None, (notes or "")[:300] or None, account_id),
    )
    return {
        "id": account_id,
        "warmup_done": bool(done),
        "warmup_checked_at": now_ts if done else None,
        "warmup_notes": (notes or "")[:300] or None,
    }


_SPAMBOT_OK = (
    "свободен от каких-либо ограничений",
    "в данный момент у вашего аккаунта нет ограничений",
    "никаких ограничений на ваш аккаунт нет",
    "good news, no limits are currently applied",
    "free as a bird",
)
_SPAMBOT_LIMITED = (
    "на ваш аккаунт наложены ограничения",
    "ваш аккаунт ограничен",
    "you are limited",
    "limitations",
    "sending too many messages",
    "temporary limitation",
    "limited for",
    "account is limited",
)


def classify_spambot_reply(reply_text: str) -> Tuple[str, str]:
    lowered = (reply_text or "").lower()
    for phrase in _SPAMBOT_OK:
        if phrase in lowered:
            return "clean", "Ограничений нет"
    for phrase in _SPAMBOT_LIMITED:
        if phrase in lowered:
            return "limited", "Наложен спамблок"
    return "unknown", (reply_text or "")[:120].strip() or "Нет ответа"


async def check_spambot(account_id: int) -> Dict[str, Any]:
    """Диалог с @SpamBot: только аудит, без обхода ограничений Telegram."""
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
    if not account:
        raise AuthError("Аккаунт не найден")
    client = await get_client(account_id)
    if not await client.is_user_authorized():
        payload = {"status": "unauthorized", "detail": "Сессия не авторизована"}
        _store_spambot(account_id, payload)
        return payload
    try:
        async with client.conversation("@SpamBot", timeout=12) as dialog:
            await dialog.send_message("/start")
            response = await dialog.get_response()
            text = response.raw_text or ""
            status, detail = classify_spambot_reply(text)
            payload = {"status": status, "detail": detail, "raw": text[:300]}
    except asyncio.TimeoutError:
        payload = {"status": "unknown", "detail": "Таймаут ответа @SpamBot"}
    except Exception as exc:
        payload = {"status": "error", "detail": str(exc)[:200]}
    _store_spambot(account_id, payload)
    return payload


def _store_spambot(account_id: int, payload: Dict[str, Any]) -> None:
    db.ex(
        """
        UPDATE accounts
        SET spambot_status=?, spambot_detail=?, spambot_checked_at=?
        WHERE id=?
        """,
        (
            str(payload.get("status") or "unknown"),
            str(payload.get("detail") or "")[:300],
            int(time.time()),
            account_id,
        ),
    )


def inferred_phone_country(phone: str) -> Optional[str]:
    return phone_country(phone)
