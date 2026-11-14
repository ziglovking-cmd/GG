# -*- coding: utf-8 -*-
"""In-process registry: at most one live TelegramClient per account id.

Coordinates with instance_guard file locks so login and bot never share
an auth key simultaneously.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("home24.client_registry")

_LOCK = threading.RLock()
# account_id → {"client": TelegramClient|None, "role": str, "since": float, "session_fp": str}
_LIVE: dict[str, dict[str, Any]] = {}


def _fp(session: str) -> str:
    s = (session or "").strip()
    if len(s) < 12:
        return s
    return f"{s[:8]}…{s[-4:]}:{len(s)}"


def is_held(account_id: str) -> bool:
    aid = (account_id or "").strip() or "main"
    with _LOCK:
        return aid in _LIVE


def holder(account_id: str) -> dict[str, Any] | None:
    aid = (account_id or "").strip() or "main"
    with _LOCK:
        row = _LIVE.get(aid)
        return dict(row) if row else None


def claim(
    account_id: str,
    client: Any,
    *,
    role: str,
    session: str = "",
) -> tuple[bool, str]:
    """Register client as the sole owner of this account session in-process."""
    from bot.instance_guard import acquire_account

    aid = (account_id or "").strip() or "main"
    ok, msg = acquire_account(aid, role=role)
    if not ok:
        return False, msg
    with _LOCK:
        prev = _LIVE.get(aid)
        if prev and prev.get("client") is not None and prev.get("client") is not client:
            # Lock не снимаем: его держит уже живой клиент. Снять — значит
            # пустить второй процесс в тот же auth key.
            other = prev.get("role") or "?"
            return (
                False,
                f"В процессе уже есть TelegramClient для [{aid}] (role={other}). "
                "Два подключения с одной сессией запрещены.",
            )
        _LIVE[aid] = {
            "client": client,
            "role": role,
            "since": time.time(),
            "session_fp": _fp(session),
        }
        logger.info("client claimed account=%s role=%s", aid, role)
        return True, "ok"


async def release(account_id: str, *, disconnect: bool = True) -> None:
    """Drop registry entry and optionally disconnect the client."""
    from bot.instance_guard import release_account

    aid = (account_id or "").strip() or "main"
    client = None
    with _LOCK:
        row = _LIVE.pop(aid, None)
        if row:
            client = row.get("client")
    if disconnect and client is not None:
        try:
            await client.disconnect()
        except Exception:
            logger.debug("disconnect on release failed account=%s", aid, exc_info=True)
    release_account(aid)
    logger.info("client released account=%s", aid)


async def disconnect_all() -> None:
    """Закрыть все сокеты этого процесса до того, как снимется lock."""
    with _LOCK:
        ids = list(_LIVE.keys())
    for aid in ids:
        await release(aid, disconnect=True)


def snapshot() -> list[dict[str, Any]]:
    with _LOCK:
        out = []
        for aid, row in _LIVE.items():
            out.append(
                {
                    "account_id": aid,
                    "role": row.get("role"),
                    "since": row.get("since"),
                    "session_fp": row.get("session_fp"),
                    "connected": row.get("client") is not None,
                }
            )
        return out
