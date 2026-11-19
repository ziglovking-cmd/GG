from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Optional

from app.config import (
    get_bot_recipient,
    get_bot_settings,
    get_bot_update_offset,
    save_bot_update_offset,
)
from app.infrastructure.bot import client, reports


BOT_REFRESH_CALLBACK = "refresh_status"
TASK: Optional[asyncio.Task] = None


async def process_update(token: str, chat_id: int, update: Dict[str, Any]) -> None:
    callback = update.get("callback_query") or {}
    callback_message = callback.get("message") or {}
    callback_chat = callback_message.get("chat") or {}
    if callback.get("data") == BOT_REFRESH_CALLBACK and int(callback_chat.get("id") or 0) == chat_id:
        await asyncio.to_thread(
            client.request,
            token,
            "answerCallbackQuery",
            {"callback_query_id": callback.get("id"), "text": "Обновляю данные"},
        )
        await reports.send_report()
        return

    message = update.get("message") or {}
    message_chat = message.get("chat") or {}
    text = str(message.get("text") or "").strip()
    if int(message_chat.get("id") or 0) == chat_id and re.match(r"^/status(?:@\w+)?(?:\s|$)", text):
        await reports.send_report()


async def poll() -> None:
    while True:
        token, _ = get_bot_settings()
        chat_id, _ = get_bot_recipient()
        if not token or not chat_id:
            await asyncio.sleep(3)
            continue
        offset = get_bot_update_offset()
        request_payload: Dict[str, Any] = {
            "timeout": 0,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            request_payload["offset"] = offset
        try:
            updates = await asyncio.to_thread(
                client.request, token, "getUpdates", request_payload
            ) or []
            for update in updates:
                update_id = int(update.get("update_id") or 0)
                try:
                    await process_update(token, int(chat_id), update)
                finally:
                    if update_id:
                        save_bot_update_offset(update_id + 1)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(10)
            continue
        await asyncio.sleep(2)
