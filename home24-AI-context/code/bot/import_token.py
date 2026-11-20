"""Импорт hex auth-key (токен с маркета) → TELEGRAM_SESSION в .env."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.crypto import AuthKey
from telethon.network.connection import ConnectionTcpAbridged
from telethon.sessions import StringSession

from bot.proxy import load_proxy

# Боевые адреса. Тестовый DC2 149.154.167.40 сюда не входит.
DCS = {
    1: ("149.154.175.53", 443),
    2: ("149.154.167.50", 443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91", 443),
    5: ("91.108.56.165", 443),
}


def _save_env(sess: str) -> None:
    env = Path(".env")
    lines = []
    found = False
    for line in env.read_text().splitlines():
        if line.startswith("TELEGRAM_SESSION="):
            lines.append(f"TELEGRAM_SESSION={sess}")
            found = True
        else:
            lines.append(line)
    if not found:
        lines.append(f"TELEGRAM_SESSION={sess}")
    env.write_text("\n".join(lines) + "\n")


async def import_hex(hex_[REDACTED] api_id: int | None = None, api_hash: str = "") -> str:
    from bot.telegram_api import resolve_api_credentials

    api_id, api_hash = resolve_api_credentials(api_id=api_id, api_hash=api_hash or None)
    hex_[REDACTED]
    raw = bytes.fromhex(hex_key)
    if len(raw) == 257:
        dc_hint, raw = raw[0], raw[1:]
        order = [dc_hint] + [d for d in DCS if d != dc_hint]
    elif len(raw) == 256:
        order = [1, 2, 4, 5, 3]
    else:
        raise SystemExit(f"Ожидал 256/257 байт auth key, получил {len(raw)}")
    proxy = load_proxy()
    for dc in order:
        s = StringSession()
        s.set_dc(dc, *DCS[dc])
        s.auth_[REDACTED]
        from bot.device import telethon_device_kwargs

        kw: dict = {
            "connection": ConnectionTcpAbridged,
            "timeout": 40,
            **telethon_device_kwargs(),
        }
        if proxy:
            kw["proxy"] = proxy
        client = TelegramClient(s, api_id, api_hash, **kw)
        try:
            await asyncio.wait_for(client.connect(), timeout=50)
            if await client.is_user_authorized():
                me = await client.get_me()
                sess = client.session.save()
                await client.disconnect()
                _save_env(sess)
                print(f"OK dc{dc}: {me.first_name} @{me.username} id={me.id}")
                print(sess)
                return sess
            await client.disconnect()
        except Exception as e:
            print(f"dc{dc}: {type(e).__name__}: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass
    raise SystemExit("Токен не принят ни на одном DC")


if __name__ == "__main__":
    [REDACTED] if len(sys.argv) > 1 else sys.stdin.read()
    asyncio.run(import_hex(key.strip()))
