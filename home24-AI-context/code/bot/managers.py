"""Веб-менеджеры продаж (работают только в панели).

Telegram-сессии — в bot.tg_accounts (до 5 SIM компании).
Один клиент → один менеджер и один Telegram-аккаунт навсегда.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()

def default_managers_path() -> Path:
    return Path(os.getenv("MANAGERS_PATH") or "data/managers.json")


DEFAULT_MANAGERS_PATH = default_managers_path()


@dataclass
class ManagerConfig:
    id: str
    name: str
    phone: str = ""
    session: str = ""  # legacy; предпочтительно tg_accounts
    report_chat: str = "me"
    admin_ids: list[int] = field(default_factory=list)
    daily_send_limit: int = 30  # legacy hint; реальный кап на tg-аккаунте
    weekly_send_limit: int = 210
    work_hours_start: int = 10
    work_hours_end: int = 20
    work_timezone: str = "Europe/Moscow"
    enabled: bool = True
    share_weight: int = 1  # доля дневной очереди (кастомные shares)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone or "—",
            "has_session": bool((self.session or "").strip()),
            "report_chat": self.report_chat or "me",
            "daily_send_limit": self.daily_send_limit,
            "weekly_send_limit": self.weekly_send_limit,
            "work_hours_start": self.work_hours_start,
            "work_hours_end": self.work_hours_end,
            "work_timezone": self.work_timezone,
            "enabled": self.enabled,
            "share_weight": self.share_weight,
            "admin_ids": list(self.admin_ids),
        }


def _slug(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9а-яё_+-]+", "-", s, flags=re.I)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "manager"


def _from_dict(raw: dict[str, Any]) -> ManagerConfig:
    aids = raw.get("admin_ids") or []
    if isinstance(aids, str):
        aids = [int(x) for x in aids.split(",") if x.strip().isdigit()]
    else:
        aids = [int(x) for x in aids if str(x).isdigit() or isinstance(x, int)]
    return ManagerConfig(
        id=str(raw.get("id") or _slug(str(raw.get("name") or "manager"))),
        name=str(raw.get("name") or raw.get("id") or "Менеджер"),
        phone=str(raw.get("phone") or ""),
        session=str(raw.get("session") or ""),
        report_chat=str(raw.get("report_chat") or "me"),
        admin_ids=aids,
        daily_send_limit=int(raw.get("daily_send_limit") or 30),
        weekly_send_limit=int(raw.get("weekly_send_limit") or 210),
        work_hours_start=int(raw.get("work_hours_start") or 10),
        work_hours_end=int(raw.get("work_hours_end") or 20),
        work_timezone=str(raw.get("work_timezone") or "Europe/Moscow"),
        enabled=bool(raw.get("enabled", True)),
        share_weight=max(1, int(raw.get("share_weight") or 1)),
    )


class ManagerRegistry:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or default_managers_path())
        self.default_manager_id: str = "default"
        self.managers: dict[str, ManagerConfig] = {}
        self.load()

    def load(self) -> None:
        with _LOCK:
            if not self.path.exists():
                self._bootstrap_from_env()
                self.save()
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.default_manager_id = str(
                data.get("default_manager_id") or "default"
            )
            self.managers = {}
            for item in data.get("managers") or []:
                if not isinstance(item, dict):
                    continue
                m = _from_dict(item)
                self.managers[m.id] = m
            if not self.managers:
                self._bootstrap_from_env()
            if self.default_manager_id not in self.managers:
                self.default_manager_id = next(iter(self.managers))

    def _bootstrap_from_env(self) -> None:
        """Один менеджер из .env — обратная совместимость."""
        name = (os.getenv("MANAGER_DISPLAY_NAME") or "Анна").strip()
        mid = _slug(name) if name else "default"
        if mid == "анна":
            mid = "anna"
        phone = (os.getenv("MANAGER_PHONE") or "").strip()
        sess = (os.getenv("TELEGRAM_SESSION") or "").strip()
        admin_raw = os.getenv("ADMIN_USER_IDS") or ""
        admin_ids = [int(x) for x in admin_raw.split(",") if x.strip().isdigit()]
        m = ManagerConfig(
            id=mid,
            name=name or "Менеджер",
            phone=phone,
            session=sess,
            report_chat="me",
            admin_ids=admin_ids,
            daily_send_limit=int(
                os.getenv("DAILY_SEND_LIMIT")
                or os.getenv("OUTREACH_MAX_PER_DAY")
                or "30"
            ),
            weekly_send_limit=int(os.getenv("WEEKLY_SEND_LIMIT") or "210"),
            work_hours_start=int(os.getenv("WORK_HOURS_START") or "10"),
            work_hours_end=int(os.getenv("WORK_HOURS_END") or "20"),
            work_timezone=(os.getenv("WORK_TIMEZONE") or "Europe/Moscow").strip(),
            enabled=True,
            share_weight=1,
        )
        self.managers = {m.id: m}
        self.default_manager_id = m.id

    def save(self) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "default_manager_id": self.default_manager_id,
                "managers": [asdict(m) for m in self.managers.values()],
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self.path)

    def get(self, manager_id: str) -> ManagerConfig | None:
        return self.managers.get(manager_id)

    def default(self) -> ManagerConfig:
        m = self.managers.get(self.default_manager_id)
        if m:
            return m
        return next(iter(self.managers.values()))

    def enabled_list(self) -> list[ManagerConfig]:
        return [m for m in self.managers.values() if m.enabled]

    def list_public(self) -> list[dict[str, Any]]:
        return [m.public_dict() for m in self.managers.values()]

    def set_session(self, manager_id: str, session: str, *, phone: str | None = None) -> None:
        with _LOCK:
            m = self.managers.get(manager_id)
            if not m:
                raise KeyError(f"unknown manager: {manager_id}")
            m.session = session or ""
            if phone is not None:
                m.phone = phone
            self.save()

    def clear_session(self, manager_id: str) -> None:
        self.set_session(manager_id, "")

    def upsert(
        self,
        *,
        manager_id: str,
        name: str,
        phone: str = "",
        daily_send_limit: int = 30,
        weekly_send_limit: int = 210,
        work_hours_start: int = 10,
        work_hours_end: int = 20,
        work_timezone: str = "Europe/Moscow",
        report_chat: str = "me",
        share_weight: int = 1,
        make_default: bool = False,
        enabled: bool | None = None,
    ) -> ManagerConfig:
        with _LOCK:
            mid = _slug(manager_id)
            existing = self.managers.get(mid)
            m = ManagerConfig(
                id=mid,
                name=name or (existing.name if existing else mid),
                phone=phone or (existing.phone if existing else ""),
                session=existing.session if existing else "",
                report_chat=report_chat or "me",
                admin_ids=list(existing.admin_ids) if existing else [],
                daily_send_limit=daily_send_limit,
                weekly_send_limit=weekly_send_limit,
                work_hours_start=work_hours_start,
                work_hours_end=work_hours_end,
                work_timezone=work_timezone,
                enabled=existing.enabled if enabled is None and existing else (
                    True if enabled is None else bool(enabled)
                ),
                share_weight=max(1, int(share_weight or (existing.share_weight if existing else 1))),
            )
            self.managers[mid] = m
            if make_default or not self.managers:
                self.default_manager_id = mid
            self.save()
            return m

    def set_share(self, manager_id: str, weight: int) -> None:
        with _LOCK:
            m = self.managers.get(manager_id)
            if not m:
                raise KeyError(manager_id)
            m.share_weight = max(1, int(weight))
            self.save()

    def set_enabled(self, manager_id: str, enabled: bool) -> None:
        with _LOCK:
            m = self.managers.get(manager_id)
            if not m:
                raise KeyError(manager_id)
            m.enabled = bool(enabled)
            self.save()

    def resolve_id(self, raw: str) -> str | None:
        """id или имя → id."""
        [REDACTED] or "").strip()
        if not [REDACTED] None
        if key in self.managers:
            return key
        low = key.lower().lstrip("@")
        for m in self.managers.values():
            if m.id.lower() == low or m.name.lower() == low:
                return m.id
        slug = _slug(key)
        if slug in self.managers:
            return slug
        return None


_registry: ManagerRegistry | None = None


def get_registry(path: Path | str | None = None) -> ManagerRegistry:
    global _registry
    if path is not None:
        return ManagerRegistry(path)
    if _registry is None:
        _registry = ManagerRegistry()
    return _registry


def reset_registry_cache() -> None:
    global _registry
    _registry = None
