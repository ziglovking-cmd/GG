"""Finish pending Telethon login from data/pending_login.json (ONE code already requested).

Usage:
  python scripts/complete_login.py 12345
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.network.connection import ConnectionTcpAbridged
from telethon.sessions import StringSession

from bot.proxy import load_proxy

load_dotenv(".env")

STATE_PATH = Path("data/pending_login.json")


def _save_env_session(sess: str) -> None:
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


async def main(code: str) -> None:
    code = "".join(ch for ch in code.strip() if ch.isdigit())
    if len(code) < 5:
        raise SystemExit(f"need 5-digit code, got {code!r}")

    if not STATE_PATH.exists():
        raise SystemExit(f"missing {STATE_PATH}")

    state = json.loads(STATE_PATH.read_text())
    if state.get("completed"):
        raise SystemExit("pending login already completed")
    phone = state["phone"]
    phone_code_hash = state["phone_code_hash"]
    sess = state["session"]
    api_id = int(state.get("api_id") or os.getenv("TELEGRAM_API_ID") or "6")
    api_hash = (os.getenv("TELEGRAM_API_HASH") or "").strip()
    pwd = (os.getenv("TELEGRAM_2FA") or "").strip()

    from bot.device import telethon_device_kwargs

    proxy = load_proxy()
    kw: dict = {
        "connection": ConnectionTcpAbridged,
        "timeout": 40,
        **telethon_device_kwargs(),
    }
    if proxy:
        kw["proxy"] = proxy

    client = TelegramClient(StringSession(sess), api_id, api_hash, **kw)
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not pwd:
                raise SystemExit("2FA required but TELEGRAM_2FA empty")
            await client.sign_in([REDACTED]

        if not await client.is_user_authorized():
            raise SystemExit("sign-in finished but still unauthorized")

        me = await client.get_me()
        new_sess = client.session.save()
        _save_env_session(new_sess)

        # also refresh db meta session for next bot start
        try:
            import sqlite3

            db = Path(os.getenv("DATABASE_PATH") or "data/home24.db")
            if db.exists():
                con = sqlite3.connect(db)
                con.execute(
                    "INSERT INTO meta(key,value) VALUES('telethon_session',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (new_sess,),
                )
                con.execute(
                    "INSERT INTO meta(key,value) VALUES('owner_id',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(me.id),),
                )
                con.commit()
                con.close()
        except Exception as e:
            print("db meta update skipped:", e)

        state["completed"] = True
        state["completed_at"] = time.time()
        state["user_id"] = me.id
        state["username"] = me.username
        state["phone_logged"] = me.phone
        # drop live session from disk after success (already in .env)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")

        print(
            f"OK signed in as {me.first_name} @{me.username} id={me.id} phone={me.phone}"
        )
        print("TELEGRAM_SESSION saved to .env")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/complete_login.py <code>")
    asyncio.run(main(sys.argv[1]))
