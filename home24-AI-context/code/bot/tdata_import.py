"""Импорт сессии из Telegram Desktop tdata (opentele-ng, UseCurrentSession).

Inspired by opentele / opentele-ng examples (MIT).
Не трогаем оригинальный tdata — копируем во временную папку.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("home24.tdata")


@dataclass
class TdataAccountInfo:
    index: int
    user_id: int
    phone: str
    username: str
    first_name: str
    session: str


def default_tdata_path() -> Path | None:
    """%APPDATA%\\Telegram Desktop\\tdata на Windows; иначе None."""
    appdata = os.environ.get("APPDATA") or os.environ.get("HOME")
    if not appdata:
        return None
    # Windows Telegram Desktop
    p = Path(appdata) / "Telegram Desktop" / "tdata"
    if p.is_dir():
        return p
    # Linux Telegram Desktop (иногда)
    p2 = Path(appdata) / ".local" / "share" / "TelegramDesktop" / "tdata"
    if p2.is_dir():
        return p2
    return None


def telegram_desktop_running() -> bool:
    """Грубая проверка: процесс Telegram.exe / telegram-desktop."""
    try:
        import psutil  # optional

        names = {"telegram.exe", "telegram-desktop", "telegramdesktop"}
        for proc in psutil.process_iter(["name"]):
            n = (proc.info.get("name") or "").lower()
            if n in names or n.startswith("telegram"):
                return True
    except Exception:
        # fallback без psutil — через tasklist на Windows
        if os.name == "nt":
            try:
                import subprocess

                out = subprocess.check_output(
                    ["tasklist", "/FI", "IMAGENAME eq Telegram.exe"],
                    text=True,
                    errors="ignore",
                )
                return "Telegram.exe" in out
            except Exception:
                return False
    return False


def copy_tdata(src: Path) -> Path:
    """Копия tdata во временный каталог (оригинал не меняем)."""
    if not src.is_dir():
        raise FileNotFoundError(f"tdata не найден: {src}")
    tmp = Path(tempfile.mkdtemp(prefix="home24_tdata_"))
    dest = tmp / "tdata"
    shutil.copytree(src, dest, dirs_exist_ok=True)
    return dest


async def list_accounts_from_tdata(
    tdata_path: Path, *, egress: str = ""
) -> list[TdataAccountInfo]:
    """Загрузить аккаунты из копии tdata и вернуть phone/username + StringSession."""
    from opentele.api import UseCurrentSession
    from opentele.td import TDesktop
    from telethon.sessions import StringSession

    from bot.proxy import proxy_for_slot

    tdesk = TDesktop(str(tdata_path))
    if not tdesk.isLoaded():
        raise RuntimeError(
            "Не удалось прочитать tdata. Закройте Telegram Desktop и попробуйте снова."
        )

    accounts = list(tdesk.accounts or [])
    if not accounts and tdesk.mainAccount:
        accounts = [tdesk.mainAccount]

    proxy = proxy_for_slot(egress, have_slot=bool((egress or "").strip()))
    out: list[TdataAccountInfo] = []
    for i, acc in enumerate(accounts):
        client = None
        try:
            client = await acc.ToTelethon(
                session=StringSession(),
                flag=UseCurrentSession,
            )
            # Тот же IP, что у слота. Иначе Desktop-сессия оживает с чужого адреса
            # и Telegram отзывает её вместе с рабочим клиентом.
            if proxy and hasattr(client, "set_proxy"):
                client.set_proxy(proxy)
            await client.connect()
            if not await client.is_user_authorized():
                continue
            me = await client.get_me()
            sess = StringSession.save(client.session)
            out.append(
                TdataAccountInfo(
                    index=i,
                    user_id=int(me.id),
                    phone=("+" + me.phone) if me.phone and not str(me.phone).startswith("+") else (me.phone or ""),
                    username=me.username or "",
                    first_name=me.first_name or "",
                    session=sess,
                )
            )
        except Exception as e:
            logger.warning("tdata account %s: %s", i, type(e).__name__)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    return out


def account_public_dict(a: TdataAccountInfo) -> dict[str, Any]:
    """Без StringSession — для JSON в браузер."""
    return {
        "index": a.index,
        "user_id": a.user_id,
        "phone": a.phone or "—",
        "username": ("@" + a.username) if a.username else "—",
        "first_name": a.first_name or "—",
        "label": f"{a.first_name or 'аккаунт'} · {a.phone or 'без телефона'} · @{a.username or '—'}",
    }
