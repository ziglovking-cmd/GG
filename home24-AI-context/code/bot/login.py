"""Вход Telethon: проверка сохранённой сессии (без печати 2FA).

Интерактивный вход — bot/web_login.py (веб-страница).
Клиент: честный device_model/system_version из platform / слота аккаунта.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession

from bot.device import telethon_device_kwargs
from bot.proxy import client_transport

logger = logging.getLogger("home24.login")

# специальный код для start.bat: сессия мертва, нужен веб-логин
EXIT_SESSION_DEAD = 42


def make_client(
    api_id: int,
    api_hash: str,
    session: str,
    *,
    device: dict[str, Any] | None = None,
    account_id: str = "",
) -> TelegramClient:
    """Создать клиент. device — fingerprint из слота tg_accounts (если есть)."""
    from bot.telegram_api import resolve_api_credentials

    api_id, api_hash = resolve_api_credentials(api_id=api_id, api_hash=api_hash, env=True)
    stored = device
    egress = ""
    if account_id:
        try:
            from bot.tg_accounts import get_tg_accounts

            tg = get_tg_accounts()
            if stored is None:
                stored = tg.freeze_device_fingerprint(account_id)
            acc = tg.get(account_id)
            if acc:
                egress = (getattr(acc, "egress", "") or "").strip()
        except Exception:
            logger.debug("account egress/device skipped", exc_info=True)
    connection, proxy = client_transport(egress, have_slot=bool(account_id))
    kw: dict = {
        "connection": connection,
        "timeout": 40,
        **telethon_device_kwargs(stored),
    }
    # egress слота: server — прямой IP или постоянный MTProxy,
    # current/bought — свой SOCKS. current/bought без строки не падаем на IP сервера.
    if proxy:
        kw["proxy"] = proxy
    return TelegramClient(StringSession(session or None), api_id, api_hash, **kw)


def _want_web_login() -> bool:
    return (os.getenv("HOME24_WEB_LOGIN") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
        "",
    )


def _exit_need_login(reason: str, *, wipe: bool = True) -> None:
    logger.error("%s — open web login (wipe=%s)", reason, wipe)
    if _want_web_login():
        exc = SystemExit(EXIT_SESSION_DEAD)
        exc.wipe = wipe  # type: ignore[attr-defined]
        raise exc
    raise SystemExit(
        "TELEGRAM_SESSION пустая или отозвана. Запустите: python -m bot.web_login"
    )


async def _session_still_valid(client: TelegramClient) -> tuple[bool, str]:
    """GetState, но FloodWait и обрыв сети не считаем смертью ключа.

    is_user_authorized() глотает любой RPCError и возвращает False.
    Из-за этого FloodWait стирал сессию с диска, и аккаунт «вылетал».
    Возвращает (жива, причина_для_стирания). Пустая причина — ключ оставить.
    """
    from telethon.errors import (
        AuthKeyDuplicatedError,
        AuthKeyUnregisteredError,
        FloodWaitError,
        SessionRevokedError,
        UserDeactivatedBanError,
        UserDeactivatedError,
    )
    from telethon.tl.functions.updates import GetStateRequest

    try:
        await client(GetStateRequest())
    except (
        AuthKeyUnregisteredError,
        SessionRevokedError,
        AuthKeyDuplicatedError,
        UserDeactivatedError,
        UserDeactivatedBanError,
    ) as e:
        return False, type(e).__name__
    except FloodWaitError as e:
        logger.warning("GetState FloodWait %ss — сессию не стираем", getattr(e, "seconds", 0))
        return False, ""
    except Exception as e:
        name = type(e).__name__
        if "AuthKeyUnregistered" in name or "SessionRevoked" in name or "AuthKeyDuplicated" in name:
            return False, name
        logger.warning("GetState failed (%s) — сессию не стираем", name)
        return False, ""
    return True, ""


async def ensure_login(
    api_id: int,
    api_hash: str,
    session: str,
    *,
    account_id: str = "",
    device: dict[str, Any] | None = None,
) -> tuple[TelegramClient, str]:
    """Подключиться с сохранённой сессией. Без QR-циклов и без авто-перезапроса кода.

    На AuthKeyUnregistered / SessionRevoked — сразу выход (нужен ручной вход),
    без reconnect-loop.
    """
    if not (session or "").strip():
        _exit_need_login("session missing", wipe=False)

    from bot.client_registry import claim, release
    from bot.instance_guard import acquire_account

    aid = (account_id or "").strip() or "main"
    ok, msg = acquire_account(aid, role="bot")
    if not ok:
        logger.error("account lock: %s", msg)
        raise RuntimeError(msg)

    from bot.instance_guard import pause_before_telegram, release_account

    await pause_before_telegram(aid)
    client = make_client(
        api_id, api_hash, session, device=device, account_id=aid
    )
    try:
        await client.connect()
    except Exception as e:
        name = type(e).__name__
        try:
            await client.disconnect()
        except Exception:
            pass
        release_account(aid)
        if "AuthKeyUnregistered" in name or "SessionRevoked" in name or "AuthKeyDuplicated" in name:
            _exit_need_login(name, wipe=True)
        # Сеть оборвалась — ключ на диске не трогаем.
        _exit_need_login(name, wipe=False)

    alive, fatal = await _session_still_valid(client)
    if not alive:
        try:
            await client.disconnect()
        except Exception:
            pass
        release_account(aid)
        await release(aid, disconnect=False)
        _exit_need_login(fatal or "session unauthorized", wipe=bool(fatal))

    sess = client.session.save()
    claimed, cmsg = claim(aid, client, role="bot", session=sess)
    if not claimed:
        try:
            await client.disconnect()
        except Exception:
            pass
        release_account(aid)
        raise RuntimeError(cmsg)
    return client, sess
