"""Хвост лички после подъёма аккаунта.

Берём входящие новее последнего нашего сообщения в Telegram.
Старый ответ в базе не повод пропускать новые пузыри, которых в базе ещё нет.
"""

from __future__ import annotations

from typing import Any


def incoming_tail(
    messages: list[dict[str, Any]],
    *,
    cutoff: float = 0,
) -> list[dict[str, Any]]:
    """messages — от новых к старым, как iter_messages.

    Останавливаемся на первом исходящем или на сообщении старше cutoff.
    Возвращаем входящие от старых к новым.
    """
    tail: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("out"):
            break
        ts = float(msg.get("ts") or 0)
        if cutoff and ts and ts < cutoff:
            break
        text = str(msg.get("text") or "").strip()
        if not text or text.startswith("/"):
            continue
        tail.append(msg)
    tail.reverse()
    return tail
