"""Очередь ответов менеджера с панели → живой Telegram-клиент бота.

Панель и бот — разные процессы. У панели нет Telethon-сессии, поэтому
реальный чат кладётся в data/panel_outbox, а бот отправляет его своим клиентом.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

OUT = Path("data/panel_outbox")


def enqueue(chat_id: str, text: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{time.time_ns()}.json"
    path.write_text(
        json.dumps(
            {"chat_id": str(chat_id), "text": text},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def pending() -> list[Path]:
    if not OUT.exists():
        return []
    return sorted(p for p in OUT.glob("*.json") if p.is_file())
