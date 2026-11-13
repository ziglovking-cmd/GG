# -*- coding: utf-8 -*-
"""Проверка TELEGRAM_API_ID / HASH — только свои ключи с my.telegram.org."""

from __future__ import annotations

import os

# Известные id официальных клиентов Telegram (Android/iOS/Desktop/…).
# Свой userbot с ними → Telegram массово рвёт сессии («terminate all sessions»).
FORBIDDEN_API_IDS: frozenset[int] = frozenset(
    {
        1,
        4,
        5,
        6,
        8,
        2040,
        21724,
        2496,
        17349,
        611335,
        2834,
        303030,
        10840,
        11287697,  # Telegram X historically
    }
)

MSG_MISSING = (
    "TELEGRAM_API_ID не задан. Получите свои api_id и api_hash на "
    "https://my.telegram.org → API development tools и пропишите в .env "
    "(и в панели → Аккаунты). Не используйте чужие/официальные ключи."
)

MSG_FORBIDDEN = (
    "TELEGRAM_API_ID={id} — это ключ официального клиента Telegram. "
    "С ним Windows-userbot часто получает «terminate all sessions». "
    "Создайте СВОИ api_id/api_hash на https://my.telegram.org и пропишите в .env."
)


class TelegramApiError(RuntimeError):
    """Нельзя стартовать TelegramClient с этими ключами."""


def resolve_api_credentials(
    *,
    api_id: int | str | None = None,
    api_hash: str | None = None,
    env: bool = True,
) -> tuple[int, str]:
    """Вернуть (api_id, api_hash) или бросить TelegramApiError."""
    raw_id = api_id
    raw_hash = api_hash
    if env:
        if raw_id is None or raw_id == "" or raw_id == 0:
            raw_id = (os.getenv("TELEGRAM_API_ID") or "").strip()
        if raw_hash is None:
            raw_hash = (os.getenv("TELEGRAM_API_HASH") or "").strip()
    if raw_id is None or str(raw_id).strip() == "":
        raise TelegramApiError(MSG_MISSING)
    try:
        aid = int(str(raw_id).strip())
    except (TypeError, ValueError) as e:
        raise TelegramApiError(MSG_MISSING) from e
    if aid <= 0:
        raise TelegramApiError(MSG_MISSING)
    if aid in FORBIDDEN_API_IDS:
        raise TelegramApiError(MSG_FORBIDDEN.format(id=aid))
    h = (raw_hash or "").strip()
    if not h or h in {
        "eb06d4abfb49dc3eeb1aeb98ae0f581e",  # official Android
        "014b35b6184100b085b0d0572f9b5103",  # official Desktop
    }:
        raise TelegramApiError(
            "TELEGRAM_API_HASH пуст или принадлежит официальному клиенту. "
            "Укажите свой hash с https://my.telegram.org."
        )
    return aid, h


def api_credentials_ok() -> tuple[bool, str]:
    try:
        resolve_api_credentials()
        return True, ""
    except TelegramApiError as e:
        return False, str(e)
