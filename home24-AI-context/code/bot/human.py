"""Человечные паузы и «печатает…» по script.md v2."""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any

from telethon import Button, TelegramClient
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction

# Исходящие от бота: id сообщений + счётчик in-flight send
_BOT_MSG_IDS: dict[str, set[int]] = {}
_BOT_UNTIL: dict[str, float] = {}
_BOT_SENDING: dict[str, int] = {}


def mark_bot_outbound(chat_id: Any, msg_id: int = 0, *, ttl: float = 60.0) -> None:
    [REDACTED]
    _BOT_UNTIL[key] = time.time() + ttl
    if msg_id:
        _BOT_MSG_IDS.setdefault(key, set()).add(int(msg_id))


def begin_bot_send(chat_id: Any) -> None:
    [REDACTED]
    _BOT_SENDING[key] = _BOT_SENDING.get(key, 0) + 1
    mark_bot_outbound(key, 0, ttl=90.0)


def end_bot_send(chat_id: Any) -> None:
    [REDACTED]
    _BOT_SENDING[key] = max(0, _BOT_SENDING.get(key, 0) - 1)


def was_bot_outbound(chat_id: Any, msg_id: int | None = None) -> bool:
    [REDACTED]
    if _BOT_SENDING.get(key, 0) > 0:
        return True
    until = _BOT_UNTIL.get(key, 0.0)
    if until and time.time() > until:
        _BOT_MSG_IDS.pop(key, None)
        _BOT_UNTIL.pop(key, None)
        return False
    ids = _BOT_MSG_IDS.get(key) or set()
    if msg_id is not None:
        return int(msg_id) in ids
    return bool(ids)


def split_human(text: str) -> list[str]:
    """Длиннее ~3 строк → 2 коротких сообщения (как в мессенджере)."""
    text = (text or "").strip()
    if not text:
        return []
    # каталог квартир — одним сообщением, не режем карточки пополам
    if (
        "Вот несколько вариантов" in text
        or "Подобрала несколько вариантов" in text
        or re.search(r"(?m)^\d\)\s*«", text)
    ):
        return [text]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 3 and len(text) <= 220:
        return [text]
    # режем по пустой строке или пополам по предложениям
    if "\n\n" in text:
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        if 1 < len(parts) <= 3:
            return parts[:2] if len(parts) > 2 else parts
    if len(lines) > 3:
        mid = (len(lines) + 1) // 2
        return ["\n".join(lines[:mid]), "\n".join(lines[mid:])]
    # по предложениям
    sents = re.split(r"(?<=[.!?…])\s+", text)
    if len(sents) >= 2:
        mid = (len(sents) + 1) // 2
        return [" ".join(sents[:mid]).strip(), " ".join(sents[mid:]).strip()]
    return [text]


def flatten_msgs(texts: list[str], *, max_msgs: int = 3) -> list[str]:
    out: list[str] = []
    for t in texts:
        out.extend(split_human(t))
    # не больше 2 сообщений за ход — по скрипту
    if len(out) <= max_msgs:
        return [x for x in out if x]
    # склеиваем хвост
    head, tail = out[: max_msgs - 1], out[max_msgs - 1 :]
    return head + ["\n".join(tail)]


def _buttons(pairs: list[tuple[str, str]] | None):
    if not pairs:
        return None
    # resize только на первой кнопке (Telethon)
    rows = []
    for i, (text, _) in enumerate(pairs):
        if i == 0:
            rows.append([Button.text(text, resize=True)])
        else:
            rows.append([Button.text(text)])
    return rows


def typing_seconds(text: str) -> float:
    """1–2.5с база + набор по длине, как живой человек."""
    n = len(text or "")
    base = random.uniform(1.2, 2.6)
    # ~35–50 зн/сек «печати», но с потолком
    type_time = min(4.5, n / random.uniform(35, 50))
    return base + type_time


async def _show_typing(client: TelegramClient, entity: Any, seconds: float) -> None:
    deadline = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < deadline:
        try:
            await client(SetTypingRequest(entity, SendMessageTypingAction()))
        except Exception:
            try:
                async with client.action(entity, "typing"):
                    await asyncio.sleep(min(3.0, deadline - asyncio.get_event_loop().time()))
                    return
            except Exception:
                await asyncio.sleep(min(2.0, max(0.1, deadline - asyncio.get_event_loop().time())))
                return
        chunk = min(3.0, max(0.1, deadline - asyncio.get_event_loop().time()))
        await asyncio.sleep(chunk)


# анти-дубль по чату: второй outbound того же хода не раньше N сек
_LAST_SEND_TS: dict[str, float] = {}
_SAME_TURN_GAP_SEC = 8.0


def consolidate_outbound(texts: list[str], *, max_msgs: int = 2) -> list[str]:
    """Склеить дубли дат/гостей и ограничить число пузырей за один ход."""
    msgs = flatten_msgs(texts, max_msgs=max_msgs)
    if len(msgs) >= 2:
        lows = [m.lower() for m in msgs]
        date_asks = sum(
            1 for m in lows if re.search(r"на какие даты|даты примерно|сколько будет гост", m)
        )
        # только явный дубль вопроса про даты — не трогаем первое inbound-приветствие
        if date_asks >= 2:
            prefer = [
                m
                for m in msgs
                if re.search(r"на какие даты|даты|гост", m.lower())
                and not re.search(r"это home24|рада вас|соскучились", m.lower())
            ]
            msgs = (prefer or msgs)[:1]
    return msgs


async def human_send(
    client: TelegramClient,
    entity: Any,
    texts: list[str],
    buttons: list[tuple[str, str]] | None = None,
    *,
    max_msgs: int = 2,
) -> None:
    msgs = consolidate_outbound(texts, max_msgs=max_msgs)
    if not msgs:
        return
    chat_[REDACTED] "user_id", None) or getattr(entity, "id", None) or entity)
    begin_bot_send(chat_key)
    try:
        for i, text in enumerate(msgs):
            # защита: если предыдущий send этого чата был < N сек назад — не слать второй пузырь
            # (не режет outreach: между пузырями sleep 1.5–3с, а gap проверяем только vs предыдущего хода)
            if i == 0:
                last = _LAST_SEND_TS.get(chat_key, 0.0)
                if last and (time.time() - last) < _SAME_TURN_GAP_SEC and len(msgs) > 1:
                    # повторный вызов human_send слишком быстро — один пузырь
                    msgs = msgs[:1]
                    text = msgs[0]
                await asyncio.sleep(random.uniform(0.4, 1.0))
            else:
                await asyncio.sleep(random.uniform(1.5, 3.0))
            await _show_typing(client, entity, typing_seconds(text))
            sent = await client.send_message(
                entity,
                text,
                buttons=_buttons(buttons) if i == len(msgs) - 1 else None,
            )
            _LAST_SEND_TS[chat_key] = time.time()
            try:
                cid = str(getattr(sent, "chat_id", None) or chat_key)
                mark_bot_outbound(cid, int(getattr(sent, "id", 0) or 0), ttl=90.0)
            except Exception:
                pass
    finally:
        end_bot_send(chat_key)
        try:
            from bot.presence import set_offline

            await set_offline(client)
        except Exception:
            pass
