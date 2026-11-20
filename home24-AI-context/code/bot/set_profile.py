"""Обновить профиль менеджер-аккаунта под Home24."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from telethon.tl.functions.account import (
    CheckUsernameRequest,
    UpdateProfileRequest,
    UpdateUsernameRequest,
)
from telethon.tl.functions.photos import UploadProfilePhotoRequest

from bot.config import get_settings
from bot.login import ensure_login

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("home24.profile")

def _avatar_path() -> Path:
    packaged = Path(__file__).resolve().parent / "dashboard" / "brand" / "avatar.jpg"
    override = Path("data/brand/avatar.jpg")
    if override.is_file():
        return override
    return packaged


AVATAR = _avatar_path()
# приоритет: свободный и узнаваемый
USERNAME_CANDIDATES = [
    "home24_msk",
    "home24manager",
    "home24_manager",
    "manager_home24",
    "home24_moscow",
    "home24_booking",
    "home24_apart",
    "home24guest",
    "msk_home24",
    "home24_rent",
]


async def main() -> int:
    settings = get_settings()
    client, _sess = await ensure_login(settings.api_id, settings.api_hash, settings.session)
    me = await client.get_me()
    logger.info("before: %s @%s id=%s", me.first_name, me.username, me.id)

    # имя + био
    await client(
        UpdateProfileRequest(
            first_name="Home24",
            last_name="",
            about="Home24 · апартаменты в Москве",
        )
    )
    logger.info("profile name/about updated")

    # аватар с официального логотипа сайта
    if AVATAR.exists():
        file = await client.upload_file(str(AVATAR))
        await client(UploadProfilePhotoRequest(file=file))
        logger.info("avatar uploaded from %s", AVATAR)
    else:
        logger.warning("avatar missing: %s", AVATAR)

    # юзернейм
    chosen = None
    for u in USERNAME_CANDIDATES:
        try:
            ok = await client(CheckUsernameRequest(u))
        except Exception as e:
            logger.info("check @%s: %s", u, e)
            continue
        if not ok:
            logger.info("@%s занят", u)
            continue
        try:
            await client(UpdateUsernameRequest(u))
            chosen = u
            logger.info("username set @%s", u)
            break
        except Exception as e:
            logger.warning("set @%s failed: %s", u, e)

    me2 = await client.get_me()
    print(
        f"OK name={me2.first_name!r} {me2.last_name!r} username=@{me2.username} "
        f"chosen={chosen}"
    )
    await client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
