# -*- coding: utf-8 -*-
"""Пауза после передачи менеджеру короткая: гость не остаётся без ответа."""

from __future__ import annotations

import time
from typing import Any

# Столько менеджер может вести чат молча, потом бот снова отвечает.
HOLD_SEC = 15 * 60


def handoff_hold_active(
    messages: list[dict[str, Any]] | None, *, now: float | None = None
) -> bool:
    """Молчим, только если менеджер или сам бот писали в последние 15 минут."""
    now_ts = time.time() if now is None else float(now)
    last_staff = 0.0
    for msg in messages or []:
        if (msg.get("role") or "") not in ("manager", "bot"):
            continue
        try:
            ts = float(msg.get("created_at") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts > last_staff:
            last_staff = ts
    if last_staff <= 0:
        return False
    return (now_ts - last_staff) < HOLD_SEC


def resume_step(sess: dict[str, Any]) -> str:
    dates = str(sess.get("dates") or "").strip()
    guests = str(sess.get("guests") or "").strip()
    district = str(sess.get("district") or "").strip()
    returning = str(sess.get("returning") or sess.get("returning_guest") or "").strip()
    if not dates:
        return "await_dates"
    if not guests:
        return "await_guests"
    if not district:
        return "await_district"
    if not returning:
        return "await_returning"
    return "await_returning"


def unanswered_after_hold(
    messages: list[dict[str, Any]] | None, *, now: float | None = None
) -> list[dict[str, Any]]:
    """Сообщения гостя, на которые за 15 минут не ответили ни менеджер, ни бот.

    Пусто, если пауза ещё идёт или после последней реплики менеджера/бота гость ничего не писал.
    """
    now_ts = time.time() if now is None else float(now)
    last_staff = 0.0
    last_staff_idx = -1
    for i, msg in enumerate(messages or []):
        if (msg.get("role") or "") in ("manager", "bot"):
            try:
                ts = float(msg.get("created_at") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            last_staff = max(last_staff, ts)
            last_staff_idx = i
    if last_staff <= 0 or (now_ts - last_staff) < HOLD_SEC:
        return []
    tail = list(messages or [])[last_staff_idx + 1 :]
    return [m for m in tail if (m.get("role") or "") == "guest" and str(m.get("text") or "").strip()]


HOLD_SORRY_LINE = "Извините за ожидание) Менеджер пока занят, я ему напомнила, он ответит вам здесь."
HOLD_NOTE = "Менеджер скоро напишет вам здесь по брони)"


def take_unanswered(store: Any, chat_id: str, manager_id: str = "", *, now: float | None = None) -> str:
    """Текст неотвеченных сообщений гостя, если пауза менеджера истекла ('' — отвечать не надо).

    Помечает их как обработанные (context.hold_answered_id), чтобы бот не отвечал по кругу.
    """
    if store.is_stopped_chat(chat_id):
        return ""
    sess = store.get_session(chat_id)
    ctx = dict(sess.get("context") or {})
    if ctx.get("stopped"):
        return ""
    owner = str(sess.get("manager_id") or "").strip()
    if manager_id and owner and owner != manager_id:
        return ""
    pending = unanswered_after_hold(store.recent_messages(chat_id, limit=40), now=now)
    if not pending:
        return ""
    last_id = int(pending[-1].get("id") or 0)
    if last_id and int(ctx.get("hold_answered_id") or 0) >= last_id:
        return ""
    # тот же ключ, что у «догона» после рестарта (main._restore_inbound_queue): отвечает кто-то один
    if hasattr(store, "claim_meta") and not store.claim_meta(f"resume:{chat_id}:{last_id or pending[-1].get('text')}"):
        return ""
    ctx["hold_answered_id"] = last_id
    store.save_session(chat_id, context=ctx)
    return "\n".join(str(m.get("text") or "").strip() for m in pending)


def already_answered(messages: list[dict[str, Any]] | None, outgoing: list[str], *, window: float = 600.0,
                     now: float | None = None) -> bool:
    """Тот же ответ уже ушёл гостю за последние 10 минут (второй процесс/путь) — не дублировать."""
    now_ts = time.time() if now is None else float(now)
    first = " ".join((outgoing or [""])[0].split()).lower()
    if not first:
        return False
    for msg in reversed(messages or []):
        role = msg.get("role") or ""
        if role in ("guest", "user"):
            continue
        if role != "bot":
            return False
        try:
            ts = float(msg.get("created_at") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if now_ts - ts > window:
            return False
        if " ".join(str(msg.get("text") or "").split()).lower() == first:
            return True
    return False
