"""Честный отпечаток устройства для Telethon (без маскировки под официальный клиент).

device_model / system_version — из platform (реальные данные ОС).
app_version — версия нашего бота. Значения фиксированы на машине между рестартами
и сохраняются в слоте аккаунта (data/tg_accounts.json), чтобы каждое подключение
использовало один и тот же fingerprint.
"""

from __future__ import annotations

import platform
from functools import lru_cache
from typing import Any

from bot.version import APP_NAME, __version__


@lru_cache(maxsize=1)
def default_device_fingerprint() -> dict[str, str]:
    """Стабильные честные значения для этой машины (без спуфинга Desktop)."""
    system = (platform.system() or "Unknown").strip()
    release = (platform.release() or "").strip()
    machine = (platform.machine() or "").strip()

    if machine:
        device_model = f"{system} {machine}".strip()
    else:
        device_model = system or "PC"

    system_version = f"{system} {release}".strip() if release else system
    app_version = f"{APP_NAME}/{__version__}"

    return {
        "device_model": device_model[:128],
        "system_version": system_version[:128],
        "app_version": app_version[:128],
        "lang_code": "ru",
        "system_lang_code": "ru",
    }


def telethon_device_kwargs(stored: dict[str, Any] | None = None) -> dict[str, str]:
    """Параметры TelegramClient. Если в слоте уже сохранены — переиспользуем."""
    base = dict(default_device_fingerprint())
    if stored:
        for key in ("device_model", "system_version", "app_version"):
            val = str(stored.get(key) or "").strip()
            if val:
                base[key] = val[:128]
    return base
