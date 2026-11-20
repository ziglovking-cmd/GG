from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException

from app import db
from app.api.schemas import BotTokenIn
from app.config import get_bot_recipient, get_bot_settings, save_bot_recipient, save_bot_settings
from app.infrastructure.bot import client, reports


router = APIRouter()


BOT_TOKEN_RE = re.compile(r"^[0-9]{5,20}:[A-Za-z0-9_-]{20,}$")


@router.get("/api/notifications/settings")
def get_notification_settings():
    token, username = get_bot_settings()
    chat_id, recipient_label = get_bot_recipient()
    return {
        "token_set": bool(token),
        "bot_username": username,
        "recipient_set": bool(chat_id),
        "recipient_label": recipient_label,
        "notifications_enabled": bool(token and chat_id),
        "notification_mode": "after_attempt",
        "bot_controls": True,
    }


@router.post("/api/notifications/settings")
async def post_notification_settings(body: BotTokenIn):
    token = body.bot_token.strip()
    if not BOT_TOKEN_RE.fullmatch(token):
        raise HTTPException(400, "Токен имеет неверный формат. Скопируйте его целиком из BotFather.")
    try:
        identity = await asyncio.to_thread(client.identity, token)
    except ValueError as e:
        raise HTTPException(400, str(e))
    save_bot_settings(token, identity["username"])
    db.log("Токен Telegram-бота @%s проверен и сохранён" % identity["username"],
           scope="notifications")
    return {"ok": True, "bot_username": identity["username"]}


@router.post("/api/notifications/connect")
async def connect_notification_recipient():
    token, _ = get_bot_settings()
    if not token:
        raise HTTPException(400, "Сначала сохраните токен Telegram-бота.")
    try:
        updates = await asyncio.to_thread(
            client.request, token, "getUpdates",
            {"timeout": 0, "allowed_updates": ["message"]},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    recipient = client.recipient_from_updates(updates)
    if not recipient:
        raise HTTPException(
            400,
            "Не найдено сообщение /start. Откройте бота, нажмите Start и повторите.",
        )
    chat_id, label = recipient
    save_bot_recipient(chat_id, label)
    db.log("Получатель уведомлений подключён: %s" % label, scope="notifications")
    return {"ok": True, "recipient_label": label}


@router.post("/api/notifications/test")
async def send_notification_test():
    token, _ = get_bot_settings()
    chat_id, label = get_bot_recipient()
    if not token:
        raise HTTPException(400, "Сначала сохраните токен Telegram-бота.")
    if not chat_id:
        raise HTTPException(400, "Сначала найдите получателя после команды /start.")
    try:
        await asyncio.to_thread(
            client.request, token, "sendMessage",
            {
                "chat_id": chat_id,
                "text": (
                    "✅ TG Audience подключён\n\n"
                    "Уведомления будут приходить после каждой фактической попытки "
                    "приглашения, которая запускает интервал аккаунта.\n\n"
                    "Свежая сводка доступна по команде /status и кнопке «Обновить отчёт»."
                ),
                "reply_markup": reports.status_keyboard(),
            },
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.log("Тестовое уведомление отправлено: %s" % (label or "личный чат"),
           scope="notifications")
    return {"ok": True}


@router.post("/api/notifications/report")
async def send_notification_report_now():
    token, _ = get_bot_settings()
    chat_id, _ = get_bot_recipient()
    if not token or not chat_id:
        raise HTTPException(400, "Сначала подключите бота и получателя уведомлений.")
    try:
        await reports.send_report()
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}
