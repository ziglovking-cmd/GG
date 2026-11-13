# -*- coding: utf-8 -*-
"""Флаги процесса: дашборд не должен падать вместе с Telegram-сессией."""

from __future__ import annotations

import os

# Включается из run_home24 при совместном запуске панели + ботов.
_DASHBOARD_KEEPALIVE = False


def set_dashboard_keepalive(on: bool = True) -> None:
    global _DASHBOARD_KEEPALIVE
    _DASHBOARD_KEEPALIVE = bool(on)
    os.environ["HOME24_DASHBOARD_KEEPALIVE"] = "1" if on else "0"


def dashboard_keepalive() -> bool:
    if _DASHBOARD_KEEPALIVE:
        return True
    return (os.getenv("HOME24_DASHBOARD_KEEPALIVE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_session_dead_error(exc: BaseException | str) -> bool:
    name = type(exc).__name__ if not isinstance(exc, str) else exc
    markers = (
        "SessionRevoked",
        "AuthKeyUnregistered",
        "AuthKeyDuplicated",
        "UserDeactivated",
        "UserDeactivatedBan",
        "SessionExpired",
        "AuthKeyError",
    )
    if any(m in name for m in markers):
        return True
    # широкий AuthKey* (кроме несвязанных)
    if "AuthKey" in name and "Duplicated" not in name:
        return True
    if "AuthKeyDuplicated" in name:
        return True
    return False
