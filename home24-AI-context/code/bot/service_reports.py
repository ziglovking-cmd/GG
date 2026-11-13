# -*- coding: utf-8 -*-
"""Сервисные отчёты в Избранное: по умолчанию выкл., без дублей и пачек."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("home24.service_reports")

# раз в процесс: аккаунты, по которым уже слали «online»
_online_sent_accounts: set[str] = set()
_last_online_ts: dict[str, float] = {}
_last_saved_any_ts: float = 0.0
_saved_lock = asyncio.Lock()

ONLINE_MIN_INTERVAL_SEC = 600  # 10 минут
SAVED_MIN_GAP_SEC = 3.0  # анти-пачка в Избранное


def reset_service_reports_state_for_tests() -> None:
    global _last_saved_any_ts
    _online_sent_accounts.clear()
    _last_online_ts.clear()
    _last_saved_any_ts = 0.0


def _load_service_blob() -> dict[str, Any]:
    try:
        from bot.dashboard import auth as dash_auth

        data = dash_auth.load_store()
        blob = data.get("service_reports")
        return dict(blob) if isinstance(blob, dict) else {}
    except Exception:
        return {}


def saved_messages_reports_enabled() -> bool:
    """Админ-переключатель. По умолчанию OFF — только панель."""
    blob = _load_service_blob()
    return bool(blob.get("saved_messages_reports", False))


def set_saved_messages_reports(enabled: bool) -> dict[str, Any]:
    from bot.dashboard import auth as dash_auth

    with dash_auth._LOCK:  # noqa: SLF001
        data = dash_auth.load_store()
        cur = data.get("service_reports")
        if not isinstance(cur, dict):
            cur = {}
        cur["saved_messages_reports"] = bool(enabled)
        data["service_reports"] = cur
        dash_auth.save_store(data)
    return {"saved_messages_reports": bool(enabled)}


def get_service_report_settings() -> dict[str, Any]:
    return {
        "saved_messages_reports": saved_messages_reports_enabled(),
        "online_min_interval_sec": ONLINE_MIN_INTERVAL_SEC,
        "saved_min_gap_sec": SAVED_MIN_GAP_SEC,
    }


def other_live_client_same_user(account_id: str, telegram_user_id: str | int) -> bool:
    """True если в процессе уже крутится другой слот с тем же Telegram user id."""
    uid = str(telegram_user_id or "").strip()
    if not uid:
        return False
    aid = (account_id or "").strip()
    try:
        from bot.hub import get_hub
        from bot.tg_accounts import get_tg_accounts

        hub = get_hub()
        tg = get_tg_accounts()
        for acc in tg.accounts.values():
            if aid and acc.id == aid:
                continue
            if str(acc.telegram_user_id or "").strip() != uid:
                continue
            client = hub.clients.get(acc.id)
            if client is None and acc.manager_id:
                client = hub.clients.get(acc.manager_id)
            if client is None:
                continue
            is_conn = getattr(client, "is_connected", None)
            try:
                connected = bool(is_conn()) if callable(is_conn) else True
            except Exception:
                connected = True
            if connected:
                return True
    except Exception:
        logger.debug("other_live_client check failed", exc_info=True)
    return False


def can_send_online_report(account_id: str, telegram_user_id: str | int = "") -> tuple[bool, str]:
    aid = (account_id or "").strip() or "main"
    if aid in _online_sent_accounts:
        return False, "уже отправлен в этом процессе"
    last = float(_last_online_ts.get(aid) or 0)
    if last and (time.time() - last) < ONLINE_MIN_INTERVAL_SEC:
        return False, "интервал 10 минут"
    if other_live_client_same_user(aid, telegram_user_id):
        return False, "другой клиент с тем же user id уже онлайн"
    return True, ""


async def _throttle_saved_messages() -> None:
    global _last_saved_any_ts
    async with _saved_lock:
        now = time.time()
        wait = SAVED_MIN_GAP_SEC - (now - _last_saved_any_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_saved_any_ts = time.time()


async def emit_service_report(
    client: Any,
    text: str,
    *,
    account_id: str = "",
    manager_id: str = "",
    report_to: str = "me",
    title: str = "Сервис",
    level: str = "info",
    force_telegram: bool = False,
) -> bool:
    """Всегда в панель; в Избранное — только если админ включил (или force)."""
    body = (text or "").strip()
    if not body:
        return False
    try:
        from bot.hub import get_hub

        get_hub().notify(
            title,
            body[:500],
            manager_id=manager_id or "",
            level=level,
        )
    except Exception:
        logger.debug("hub notify failed", exc_info=True)

    if not force_telegram and not saved_messages_reports_enabled():
        return False
    if client is None:
        return False
    await _throttle_saved_messages()
    try:
        await client.send_message(report_to or "me", body)
        return True
    except Exception:
        try:
            await client.send_message("me", body)
            return True
        except Exception:
            logger.exception("saved messages report failed account=%s", account_id)
            return False


async def report_account_online(
    client: Any,
    *,
    account_id: str,
    manager_id: str,
    telegram_user_id: str | int,
    text: str,
    report_to: str = "me",
    username: str = "",
) -> bool:
    """«Home24 online»: панель всегда; Избранное — с жёстким дедупом."""
    aid = (account_id or "").strip() or "main"
    uname = (username or "").strip()
    try:
        from bot.hub import get_hub

        get_hub().notify(
            "Аккаунт в сети",
            f"[{aid}] @{uname}" if uname else f"[{aid}] онлайн",
            manager_id=manager_id or "",
            level="info",
        )
    except Exception:
        logger.debug("online hub notify failed", exc_info=True)

    if not saved_messages_reports_enabled():
        logger.info("online report skipped (saved_messages_reports OFF) account=%s", aid)
        return False

    ok, why = can_send_online_report(aid, telegram_user_id)
    if not ok:
        logger.info("online report skipped account=%s: %s", aid, why)
        return False

    await _throttle_saved_messages()
    try:
        await client.send_message(report_to or "me", text)
    except Exception:
        try:
            await client.send_message("me", text)
        except Exception:
            logger.exception("online telegram report failed account=%s", aid)
            return False

    _online_sent_accounts.add(aid)
    _last_online_ts[aid] = time.time()
    logger.info("online report sent account=%s", aid)
    return True
