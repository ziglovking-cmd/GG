"""Общий runtime: Telegram-клиенты (аккаунты компании) + шина событий дашборда."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

logger = logging.getLogger("home24.hub")


class EventBus:
    def __init__(self, *, history: int = 400) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._lock = asyncio.Lock()

    def publish(self, kind: str, **payload: Any) -> None:
        evt = {"kind": kind, "ts": time.time(), **payload}
        self._history.append(evt)
        dead: list[asyncio.Queue] = []
        for q in list(self._subs):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                dead.append(q)
            except Exception:
                dead.append(q)
        for q in dead:
            self._subs.discard(q)

    def subscribe(self, *, maxsize: int = 200) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs.add(q)
        for evt in self._history:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                break
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)


def is_technical_logger(name: str) -> bool:
    """Шум панели/сети: aiohttp.access, telethon.network и т.п."""
    n = (name or "").strip().lower()
    if not n:
        return False
    if n == "aiohttp.access" or n.startswith("aiohttp."):
        return True
    if n.startswith("telethon.network") or n.startswith("telethon.client.updates"):
        return True
    if n.startswith("asyncio") or n.startswith("urllib3"):
        return True
    return False


class LogRing:
    def __init__(self, n: int = 800) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=n)

    def add(self, level: str, logger_name: str, message: str, *, manager_id: str = "") -> None:
        item = {
            "ts": time.time(),
            "level": level,
            "logger": logger_name,
            "message": message[:2000],
            "manager_id": manager_id,
            "technical": is_technical_logger(logger_name),
        }
        self._items.append(item)
        get_hub().bus.publish("log", **item)

    def list(
        self,
        *,
        level: str = "",
        manager_id: str = "",
        limit: int = 200,
        technical: bool = False,
    ) -> list[dict[str, Any]]:
        rows = list(self._items)
        if not technical:
            rows = [r for r in rows if not r.get("technical")]
        if level:
            rows = [r for r in rows if r["level"].lower() == level.lower()]
        if manager_id:
            rows = [r for r in rows if r.get("manager_id") == manager_id or not r.get("manager_id")]
        return rows[-limit:]


class HubLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            # access INFO не кладём в журнал (даже в technical) — слишком шумно;
            # WARNING+ и прочий technical остаются для тумблера
            if record.name == "aiohttp.access" and record.levelno < logging.WARNING:
                return
            if record.name.startswith("telethon.network") and record.levelno < logging.WARNING:
                return
            mid = getattr(record, "manager_id", "") or ""
            msg = self.format(record)
            get_hub().logs.add(record.levelname, record.name, msg, manager_id=str(mid))
        except Exception:
            pass


class RuntimeHub:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.logs = LogRing()
        # ключи: manager_id и/или tg account_id → TelegramClient
        self.clients: dict[str, Any] = {}
        self.outreach: dict[str, dict[str, Any]] = {}
        self.notifications: deque[dict[str, Any]] = deque(maxlen=200)
        self.unread: dict[str, int] = {}  # manager_id -> count
        self._log_handler_attached = False

    def attach_logging(self) -> None:
        if self._log_handler_attached:
            return
        h = HubLogHandler()
        h.setLevel(logging.INFO)
        h.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(h)
        self._log_handler_attached = True

    def register_client(
        self, manager_id: str, client: Any, *, account_id: str = ""
    ) -> None:
        self.clients[manager_id] = client
        if account_id:
            self.clients[account_id] = client
        self.bus.publish(
            "session", manager_id=manager_id, account_id=account_id, status="online"
        )

    def unregister_client(self, manager_id: str, *, account_id: str = "") -> None:
        self.clients.pop(manager_id, None)
        if account_id:
            self.clients.pop(account_id, None)
        self.bus.publish(
            "session", manager_id=manager_id, account_id=account_id, status="offline"
        )

    def get_client(self, manager_id: str = "", *, account_id: str = "") -> Any | None:
        """Клиент Telethon: сначала слот аккаунта (навсегда у клиента), потом менеджер."""
        aid = (account_id or "").strip()
        if aid and aid in self.clients:
            return self.clients[aid]
        mid = (manager_id or "").strip()
        if mid and mid in self.clients:
            return self.clients[mid]
        try:
            from bot.tg_accounts import get_tg_accounts

            tg = get_tg_accounts()
            acc = tg.for_contact(aid, manager_id=mid) if aid else tg.for_manager(mid)
            if acc:
                c = self.clients.get(acc.id) or (
                    self.clients.get(acc.manager_id) if acc.manager_id else None
                )
                if c:
                    return c
        except Exception:
            pass
        # один подключенный аккаунт компании — все менеджеры делят его
        if len(self.clients) == 1:
            return next(iter(self.clients.values()))
        return self.clients.get("main")

    def notify(
        self,
        title: str,
        body: str = "",
        *,
        manager_id: str = "",
        level: str = "info",
        chat_id: str = "",
    ) -> None:
        item = {
            "kind": "notify",
            "ts": time.time(),
            "title": title,
            "body": body,
            "manager_id": manager_id,
            "level": level,
            "chat_id": chat_id,
        }
        self.notifications.appendleft(item)
        if manager_id:
            self.unread[manager_id] = self.unread.get(manager_id, 0) + 1
        self.bus.publish(**item)

    def clear_unread(self, manager_id: str) -> None:
        self.unread[manager_id] = 0

    def set_outreach(self, manager_id: str, **fields: Any) -> None:
        cur = self.outreach.setdefault(manager_id, {})
        cur.update(fields)
        cur["updated_at"] = time.time()
        self.bus.publish("queue", manager_id=manager_id, **cur)


_HUB: RuntimeHub | None = None


def get_hub() -> RuntimeHub:
    global _HUB
    if _HUB is None:
        _HUB = RuntimeHub()
        _HUB.attach_logging()
    return _HUB
