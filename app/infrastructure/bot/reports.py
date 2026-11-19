from __future__ import annotations

import asyncio
from datetime import datetime
import time
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from app import accounts, db, inviting
from app.config import get_bot_recipient, get_bot_settings
from app.infrastructure.bot import client


BOT_REFRESH_CALLBACK = "refresh_status"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def status_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "🔄 Обновить отчёт", "callback_data": BOT_REFRESH_CALLBACK}
        ]]
    }


def moscow_time(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), MOSCOW_TZ).strftime("%d.%m.%Y, %H:%M МСК")


def campaign_worker_counts(campaign: Dict[str, Any], running: bool) -> tuple[int, int]:
    account_ids = [int(value) for value in db.settings_of(campaign).get("account_ids", [])]
    total = len(account_ids)
    if not running:
        return 0, total
    workers = (inviting.STATE.get(campaign["id"], {}).get("workers") or {})
    fatal_markers = (
        "аккаунт недоступен",
        "аккаунт не авторизован",
        "отключён пользователем",
        "нет прав приглашать",
        "перепроверка доступа",
        "сбой подключения",
        "тайм-аут подключения",
        "PEER_FLOOD",
        "спамблок Telegram",
        "целевой чат заполнен",
    )
    active = 0
    for account_id in account_ids:
        worker = workers.get(account_id)
        account = db.row_to_dict(db.q1(
            "SELECT * FROM accounts WHERE id=?", (account_id,)
        ))
        state = str((worker or {}).get("state") or "")
        eligible = accounts.invite_eligibility(
            account,
            check_quota=False,
        )[0]
        if (
            worker
            and eligible
            and int(account["cooldown_until"] or 0) <= int(time.time())
            and not any(marker in state for marker in fatal_markers)
        ):
            active += 1
    return active, total


def report_text() -> str:
    now = datetime.now(MOSCOW_TZ)
    campaigns = db.rows_to_dicts(db.q("SELECT * FROM campaigns ORDER BY id DESC LIMIT 20"))
    lines = [
        "📊 TG Audience — отчёт",
        now.strftime("%d.%m.%Y, %H:%M МСК"),
        "",
    ]
    if not campaigns:
        lines.append("Кампаний пока нет.")
        return "\n".join(lines)

    for campaign in campaigns:
        campaign_id = int(campaign["id"])
        running = campaign_id in inviting.RUNNERS and not inviting.RUNNERS[campaign_id].done()
        active, total = campaign_worker_counts(campaign, running)
        if running and active == total and total:
            status = "🟢 работает"
        elif running and active:
            status = "🟡 работают не все"
        elif running:
            status = "🔴 нет работающих аккаунтов"
        elif campaign["status"] == "done":
            status = "✅ завершена"
        elif campaign["status"] == "draft":
            status = "📝 черновик"
        else:
            status = "⏸ остановлена"

        stats = inviting.campaign_stats(campaign_id)
        pending = (
            int(stats.get("pending", 0))
            + int(stats.get("in_progress", 0))
            + int(stats.get("verifying", 0))
        )
        lines.extend([
            "%s — %s" % (campaign["name"], status),
            "Аккаунты: %d/%d · приглашено: %d · осталось: %d" % (
                active, total, int(stats.get("invited", 0)), pending,
            ),
            "Приватность: %d · ошибки: %d" % (
                int(stats.get("privacy", 0)), int(stats.get("failed", 0)),
            ),
            "",
        ])
    return "\n".join(lines).strip()


async def send_report() -> None:
    token, _ = get_bot_settings()
    chat_id, label = get_bot_recipient()
    if not token or not chat_id:
        return
    await asyncio.to_thread(
        client.request,
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": report_text(),
            "reply_markup": status_keyboard(),
        },
    )
    db.log("Отчёт о кампаниях отправлен: %s" % (label or "личный чат"),
           scope="notifications")


def attempt_text(payload: Dict[str, Any]) -> Optional[str]:
    campaign = db.row_to_dict(db.q1(
        "SELECT * FROM campaigns WHERE id=?", (payload["campaign_id"],)
    ))
    account = db.row_to_dict(db.q1(
        "SELECT * FROM accounts WHERE id=?", (payload["account_id"],)
    ))
    if not campaign or not account:
        return None

    outcome_labels = {
        "pending_confirmation": ("⏳", "запрос отправлен, ожидается подтверждение"),
        "invited": ("✅", "пользователь приглашён"),
        "unconfirmed": ("🔴", "Telegram не добавил пользователя"),
        "rejected": ("🔴", "Telegram отклонил запрос приглашения"),
        "already": ("ℹ️", "уже состоит в чате"),
        "deleted": ("⚪", "аккаунт пользователя удалён"),
        "failed": ("🔴", "ошибка приглашения"),
        "connection_error": ("🚨", "сбой подключения — проверьте прокси"),
        "unauthorized": ("🚨", "аккаунт не авторизован"),
        "peer_flood": ("🚨", "PEER_FLOOD — аккаунт снят с кампании"),
        "flood_wait": ("🟠", "FloodWait — включена защитная пауза"),
        "banned": ("🚨", "Telegram ограничил приглашения"),
        "no_rights": ("🔴", "нет права приглашать в целевой чат"),
        "chat_full": ("🔴", "целевой чат заполнен"),
    }
    icon, result = outcome_labels.get(payload.get("outcome"), ("🔴", "неизвестный результат"))
    campaign_id = int(campaign["id"])
    running = campaign_id in inviting.RUNNERS and not inviting.RUNNERS[campaign_id].done()
    active, total = campaign_worker_counts(campaign, running)
    stats = inviting.campaign_stats(campaign_id)
    pending = (
        int(stats.get("pending", 0))
        + int(stats.get("in_progress", 0))
        + int(stats.get("verifying", 0))
    )
    next_at = max(
        int(account.get("next_attempt_at") or 0),
        int(account.get("cooldown_until") or 0),
        int(payload.get("next_attempt_at") or 0),
    )
    target = None
    if payload.get("username"):
        target = "@" + payload["username"]
    elif payload.get("display") or payload.get("user_id"):
        target = str(payload.get("display") or "").strip() or str(payload.get("user_id"))
    next_line = moscow_time(next_at) if next_at > int(time.time()) else "без ожидания"
    heading = "Сбой аккаунта" if payload.get("outcome") in {
        "connection_error", "unauthorized", "peer_flood", "banned", "no_rights"
    } else "Отработал аккаунт"
    lines = [
        "%s %s" % (icon, heading),
        "Кампания: %s" % campaign["name"],
        "Аккаунт: %s" % account["label"],
        "Результат: %s" % result,
    ]
    if target:
        lines.append("Цель: %s" % target)
    if payload.get("error"):
        lines.append("Причина: %s" % str(payload["error"])[:300])
    lines.extend([
        "Время: %s" % moscow_time(payload.get("attempted_at") or int(time.time())),
        "Следующая попытка: %s" % next_line,
        "",
        "Статус кампании",
        "Аккаунты в строю: %d/%d" % (active, total),
        "Приглашено: %d · осталось: %d" % (int(stats.get("invited", 0)), pending),
        "Приватность: %d · ошибки: %d" % (
            int(stats.get("privacy", 0)), int(stats.get("failed", 0)),
        ),
        "Сегодня у аккаунта: попыток %d/%d · успешно %d" % (
            int(account.get("invites_today") or 0),
            int(account.get("daily_limit") or 0),
            int(account.get("successful_today") or 0),
        ),
    ])
    return "\n".join(lines)


async def send_attempt(payload: Dict[str, Any]) -> None:
    token, _ = get_bot_settings()
    chat_id, _ = get_bot_recipient()
    if not token or not chat_id:
        return
    text = attempt_text(payload)
    if not text:
        return
    await asyncio.to_thread(
        client.request,
        token,
        "sendMessage",
        {"chat_id": chat_id, "text": text, "reply_markup": status_keyboard()},
    )
