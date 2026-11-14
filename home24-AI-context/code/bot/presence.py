# -*- coding: utf-8 -*-
"""Офлайн-присутствие + окна проверки входящих (без «вечного online»)."""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

logger = logging.getLogger("home24.presence")

_META_[REDACTED]


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or str(default)).strip())
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float((os.getenv(name) or str(default)).strip()))
    except Exception:
        return default


def default_check_settings() -> dict[str, Any]:
    return {
        "interval_min": _env_float("HOME24_CHECK_INTERVAL_MIN", 3.0),
        "jitter": _env_float("HOME24_CHECK_JITTER", 0.30),
        "night_start_hour": _env_int("HOME24_NIGHT_START", 23),
        "night_end_hour": _env_int("HOME24_NIGHT_END", 8),
        "night_interval_min": _env_float("HOME24_NIGHT_INTERVAL_MIN", 15.0),
        # после последнего сообщения гостя — столько минут отвечаем сразу, потом снова окна
        "active_idle_min": _env_float("HOME24_ACTIVE_IDLE_MIN", 10.0),
        "enabled": (os.getenv("HOME24_CHECK_WINDOWS") or "1").strip().lower()
        not in ("0", "false", "no", "off"),
    }


def get_check_settings(store: Any | None = None) -> dict[str, Any]:
    base = default_check_settings()
    if store is None:
        return base
    try:
        raw = store.get_meta(_META_KEY) or ""
        if not raw:
            return base
        import json

        data = json.loads(raw)
        if isinstance(data, dict):
            out = {**base, **data}
            out["interval_min"] = max(0.5, float(out.get("interval_min") or 3))
            out["jitter"] = min(0.9, max(0.0, float(out.get("jitter") or 0.3)))
            out["night_interval_min"] = max(
                out["interval_min"], float(out.get("night_interval_min") or 15)
            )
            out["active_idle_min"] = max(1.0, float(out.get("active_idle_min") or 10))
            out["night_start_hour"] = int(out.get("night_start_hour") or 23) % 24
            out["night_end_hour"] = int(out.get("night_end_hour") or 8) % 24
            out["enabled"] = bool(out.get("enabled", True))
            return out
    except Exception:
        logger.debug("check settings read", exc_info=True)
    return base


def save_check_settings(store: Any, data: dict[str, Any]) -> dict[str, Any]:
    merged = get_check_settings(store)
    for k, v in (data or {}).items():
        if k in merged or k == "enabled":
            merged[k] = v
    merged["interval_min"] = max(0.5, float(merged.get("interval_min") or 3))
    merged["jitter"] = min(0.9, max(0.0, float(merged.get("jitter") or 0.3)))
    merged["night_interval_min"] = max(
        merged["interval_min"], float(merged.get("night_interval_min") or 15)
    )
    merged["active_idle_min"] = max(1.0, float(merged.get("active_idle_min") or 10))
    merged["night_start_hour"] = int(merged.get("night_start_hour") or 23) % 24
    merged["night_end_hour"] = int(merged.get("night_end_hour") or 8) % 24
    merged["enabled"] = bool(merged.get("enabled", True))
    import json

    store.set_meta(_META_KEY, json.dumps(merged, ensure_ascii=False))
    return merged


class ActiveConversation:
    """Пока гости пишут — отвечаем сразу; после тишины active_idle_min → окна проверки."""

    def __init__(self) -> None:
        self._last_guest_ts: float = 0.0
        self._was_active: bool = False

    def touch(self, settings: dict[str, Any] | None = None) -> None:
        """Гость написал (не handed_off) — войти/продлить active mode."""
        self._last_guest_ts = time.time()
        self._was_active = True

    def is_active(self, settings: dict[str, Any] | None = None) -> bool:
        s = settings or default_check_settings()
        idle_sec = max(60.0, float(s.get("active_idle_min") or 10) * 60.0)
        if self._last_guest_ts <= 0:
            return False
        return (time.time() - self._last_guest_ts) < idle_sec

    def just_left_active(self, settings: dict[str, Any] | None = None) -> bool:
        """True один раз после выхода из active mode (для offline)."""
        now_active = self.is_active(settings)
        if self._was_active and not now_active:
            self._was_active = False
            return True
        if now_active:
            self._was_active = True
        return False

    @property
    def last_guest_ts(self) -> float:
        return self._last_guest_ts


def is_night(settings: dict[str, Any] | None = None, *, hour: int | None = None) -> bool:
    s = settings or default_check_settings()
    h = hour if hour is not None else time.localtime().tm_hour
    # 0 — валидный час; нельзя писать `or 23` (0 → 23)
    a = int(s["night_start_hour"]) if "night_start_hour" in s else 23
    b = int(s["night_end_hour"]) if "night_end_hour" in s else 8
    if a == b:
        return False
    if a < b:
        return a <= h < b
    # через полночь (23→8)
    return h >= a or h < b


def next_wait_seconds(
    settings: dict[str, Any] | None = None, *, hour: int | None = None
) -> float:
    s = settings or default_check_settings()
    night = is_night(s, hour=hour)
    if night:
        base = float(s["night_interval_min"]) if "night_interval_min" in s else 15.0
    else:
        base = float(s["interval_min"]) if "interval_min" in s else 3.0
    base *= 60.0
    jitter = float(s["jitter"]) if "jitter" in s else 0.3
    # ±jitter
    factor = 1.0 + random.uniform(-jitter, jitter)
    return max(20.0, base * factor)


async def set_offline(client: Any) -> None:
    """После любого действия — offline, без вечного зелёного статуса."""
    try:
        from telethon.tl.functions.account import UpdateStatusRequest

        await client(UpdateStatusRequest(offline=True))
    except Exception:
        logger.debug("UpdateStatus offline failed", exc_info=True)
