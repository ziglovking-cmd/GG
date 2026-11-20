from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import accounts, db, inviting
from app.api import accounts as accounts_api, campaigns, chats, events, notifications, settings
from app.config import ROOT
from app.infrastructure.bot import updates


app = FastAPI(title="TG Audience")
db.connect()
WEB_DIR = ROOT / "web"

for router_module in (settings, notifications, accounts_api, chats, campaigns, events):
    app.include_router(router_module.router)


async def startup_notifications():
    # Только новый основной процесс может считать прежние RUNNERS потерянными.
    # Подключения к SQLite из отчётчика и диагностических команд статусы не меняют.
    db.pause_stale_running_campaigns()
    # Итоговые уведомления формирует отдельный campaign-reporter.  Не
    # регистрируем отправитель каждой попытки, чтобы бот не присылал по одному
    # сообщению на аккаунт после будущих перезапусков основного приложения.
    inviting.set_attempt_notifier(None)
    if updates.TASK is None or updates.TASK.done():
        updates.TASK = asyncio.create_task(updates.poll())


async def shutdown():
    inviting.set_attempt_notifier(None)
    if updates.TASK and not updates.TASK.done():
        updates.TASK.cancel()
        try:
            await updates.TASK
        except asyncio.CancelledError:
            pass
    updates.TASK = None
    runners = [task for task in inviting.RUNNERS.values() if not task.done()]
    for campaign_id in list(inviting.RUNNERS):
        inviting.stop(campaign_id)
    # Даём воркерам штатно завершиться: вернуть цели в очередь и снять
    # неиспользованные брони интервалов, а не обрываться отменой.
    if runners:
        await asyncio.wait(runners, timeout=15)
    for account_id in list(accounts._clients):
        await accounts.drop_client(account_id)


app.add_event_handler("startup", startup_notifications)
app.add_event_handler("shutdown", shutdown)


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
