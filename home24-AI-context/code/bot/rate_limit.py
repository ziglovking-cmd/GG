"""Лимиты первых сообщений рассылки: дневной кап, рабочие часы МСК, равномерный темп.

Ответы гостям (диалог) в кап не входят — учитываем только outreach first-touch.
FloodWait — ждём сколько сказал Telegram, без обхода.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Безопасный темп одного аккаунта: 30/день, 210/неделя.
DEFAULT_DAILY = int(
    os.getenv("DAILY_SEND_LIMIT")
    or os.getenv("OUTREACH_MAX_PER_DAY")
    or "30"
)
DEFAULT_WEEKLY = int(os.getenv("WEEKLY_SEND_LIMIT") or "210")
# потолок часа; 0 в env выключает его
_DEFAULT_HOUR_RAW = (os.getenv("OUTREACH_MAX_PER_HOUR") or "").strip()
DEFAULT_PER_HOUR = int(_DEFAULT_HOUR_RAW) if _DEFAULT_HOUR_RAW else 4

DEFAULT_WORK_START = int(os.getenv("WORK_HOURS_START") or "10")
DEFAULT_WORK_END = int(os.getenv("WORK_HOURS_END") or "20")
DEFAULT_TZ_NAME = (os.getenv("WORK_TIMEZONE") or "Europe/Moscow").strip()
# минимальная пауза между первыми сообщениями (сек), даже если очередь маленькая
MIN_GAP_SEC = float(os.getenv("OUTREACH_MIN_GAP_SEC") or "240")


def _tz(name: str = DEFAULT_TZ_NAME):
    try:
        return ZoneInfo(name)
    except Exception:
        # Windows без tzdata — фиксированный МСК (UTC+3, без DST)
        return timezone(timedelta(hours=3))


class OutreachLimiter:
    def __init__(
        self,
        store: Any,
        *,
        daily_limit: int | None = None,
        weekly_limit: int | None = None,
        per_hour: int | None = None,
        work_start: int | None = None,
        work_end: int | None = None,
        tz_name: str | None = None,
        manager_id: str = "",
        account_id: str = "",
        # legacy kwargs from older tests
        per_day: int | None = None,
    ) -> None:
        self.store = store
        self.manager_id = (manager_id or "").strip()
        self.account_id = (account_id or "").strip()
        self.daily_limit = int(
            daily_limit if daily_limit is not None else (per_day if per_day is not None else DEFAULT_DAILY)
        )
        self.weekly_limit = int(weekly_limit if weekly_limit is not None else DEFAULT_WEEKLY)
        self.per_hour = int(per_hour if per_hour is not None else DEFAULT_PER_HOUR)
        self.work_start = int(work_start if work_start is not None else DEFAULT_WORK_START)
        self.work_end = int(work_end if work_end is not None else DEFAULT_WORK_END)
        self.tz_name = tz_name or DEFAULT_TZ_NAME
        self.tz = _tz(self.tz_name)
        if self.work_end <= self.work_start:
            self.work_end = self.work_start + 1

    def _scope(self) -> str:
        """Счётчики на Telegram-аккаунт; manager_id — доля менеджера."""
        if self.account_id:
            return f"acc:{self.account_id}"
        if self.manager_id:
            return f"mgr:{self.manager_id}"
        return "global"

    def _key(self, prefix: str, suffix: str) -> str:
        return f"{prefix}:{self._scope()}:{suffix}"

    def _mgr_key(self, prefix: str, suffix: str) -> str:
        mid = self.manager_id or "_"
        return f"{prefix}:mgr:{mid}:{suffix}"

    # --- time helpers (Europe/Moscow by default) ---

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def day_key(self, when: datetime | None = None) -> str:
        return (when or self.now()).strftime("%Y-%m-%d")

    def hour_key(self, when: datetime | None = None) -> str:
        return (when or self.now()).strftime("%Y-%m-%dT%H")

    def window_seconds(self) -> int:
        return max(1, (self.work_end - self.work_start) * 3600)

    def in_work_hours(self, when: datetime | None = None) -> bool:
        n = when or self.now()
        return self.work_start <= n.hour < self.work_end

    def seconds_until_window_open(self, when: datetime | None = None) -> float:
        n = when or self.now()
        if self.in_work_hours(n):
            return 0.0
        start_today = n.replace(hour=self.work_start, minute=0, second=0, microsecond=0)
        if n.hour < self.work_start:
            target = start_today
        else:
            target = start_today + timedelta(days=1)
        return max(0.0, (target - n).total_seconds())

    def seconds_until_window_end(self, when: datetime | None = None) -> float:
        n = when or self.now()
        if not self.in_work_hours(n):
            return 0.0
        end = n.replace(hour=self.work_end, minute=0, second=0, microsecond=0)
        return max(0.0, (end - n).total_seconds())

    # --- counters (only first-touch outreach) ---

    def _get_counter(self, [REDACTED] -> int:
        raw = self.store.get_meta(key) or "0"
        try:
            return int(raw)
        except Exception:
            return 0

    def _bump(self, [REDACTED] -> None:
        self.store.set_meta(key, str(self._get_counter(key) + 1))

    @property
    def per_day(self) -> int:
        """Alias for older call sites / tests."""
        return self.daily_limit

    def sent_today(self) -> int:
        return self._get_counter(self._key("outreach_cnt_d", self.day_key()))

    def sent_week(self) -> int:
        """Скользящие 7 суток (МСК)."""
        n = self.now()
        total = 0
        for i in range(7):
            day = (n - timedelta(days=i)).strftime("%Y-%m-%d")
            total += self._get_counter(self._key("outreach_cnt_d", day))
        return total

    def manager_sent_today(self) -> int:
        return self._get_counter(self._mgr_key("outreach_mgr_d", self.day_key()))

    def manager_sent_week(self) -> int:
        n = self.now()
        total = 0
        for i in range(7):
            day = (n - timedelta(days=i)).strftime("%Y-%m-%d")
            total += self._get_counter(self._mgr_key("outreach_mgr_d", day))
        return total

    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.sent_today())

    def remaining_week(self) -> int:
        return max(0, self.weekly_limit - self.sent_week())

    def _quiet_status(self) -> tuple[bool, str, int]:
        """Тишина после нового входа на аккаунте (first-touch запрещён)."""
        if not self.account_id:
            return False, "", 0
        try:
            from bot.tg_accounts import get_tg_accounts

            acc = get_tg_accounts().get(self.account_id)
            if not acc:
                return False, "", 0
            blocked, why = acc.outreach_quiet_status()
            return blocked, why, acc.quiet_remaining_sec()
        except Exception:
            return False, "", 0

    def counts(self) -> dict[str, Any]:
        sent = self.sent_today()
        week = self.sent_week()
        remaining = max(0, self.daily_limit - sent)
        n = self.now()
        paused, reason = self.pause_active()
        quiet, quiet_why, quiet_left = self._quiet_status()
        return {
            "day": sent,
            "sent_today": sent,
            "remaining_today": remaining,
            "max_day": self.daily_limit,
            "daily_limit": self.daily_limit,
            "sent_week": week,
            "weekly_limit": self.weekly_limit,
            "remaining_week": max(0, self.weekly_limit - week),
            "manager_sent_today": self.manager_sent_today(),
            "manager_sent_week": self.manager_sent_week(),
            "hour": self._get_counter(self._key("outreach_cnt_h", self.hour_key())),
            "max_hour": self.per_hour,
            "in_work_hours": self.in_work_hours(n),
            "work_start": self.work_start,
            "work_end": self.work_end,
            "timezone": self.tz_name,
            "moscow_time": n.strftime("%H:%M"),
            "day_key": self.day_key(n),
            "manager_id": self.manager_id,
            "account_id": self.account_id,
            "paused_today": paused,
            "pause_reason": reason,
            "quiet_active": quiet,
            "quiet_reason": quiet_why,
            "quiet_remaining_sec": quiet_left,
        }

    def can_send(self, *, ignore_window: bool = False) -> tuple[bool, str]:
        quiet, quiet_why, _left = self._quiet_status()
        if quiet:
            return False, quiet_why
        if not ignore_window and not self.in_work_hours():
            wait = self.seconds_until_window_open()
            hh = int(wait // 3600)
            mm = int((wait % 3600) // 60)
            return (
                False,
                f"вне рабочих часов {self.work_start}:00–{self.work_end}:00 "
                f"{self.tz_name} (сейчас {self.now().strftime('%H:%M')}, "
                f"откроется через {hh}ч {mm}м)",
            )
        c = self.counts()
        if c["sent_today"] >= self.daily_limit:
            return (
                False,
                f"дневной лимит: {c['sent_today']}/{self.daily_limit} "
                f"(остаток завтра, очередь pending сохранится)",
            )
        if c["sent_week"] >= self.weekly_limit:
            return (
                False,
                f"недельный лимит: {c['sent_week']}/{self.weekly_limit} "
                f"(скользящие 7 дней)",
            )
        paused, reason = self.pause_active()
        if paused:
            return False, reason
        if self.per_hour > 0 and c["hour"] >= self.per_hour:
            return False, f"лимит часа: {c['hour']}/{self.per_hour}"
        return True, ""

    def spacing_delay_sec(self, *, queue_left: int | None = None) -> float:
        """Пауза до следующего первого сообщения: равномерно до конца окна."""
        remaining_quota = self.remaining_today()
        if remaining_quota <= 0:
            return self.seconds_until_window_open() or float(self.window_seconds())
        # сколько ещё хотим отправить сегодня с учётом длины очереди
        to_pace = remaining_quota
        if queue_left is not None:
            to_pace = max(1, min(remaining_quota, queue_left))
        left_sec = self.seconds_until_window_end()
        if left_sec <= 0:
            return self.seconds_until_window_open() or MIN_GAP_SEC
        # to_pace сообщений за left_sec → промежуток left_sec/to_pace
        gap = left_sec / float(to_pace)
        return max(MIN_GAP_SEC, gap)

    def planned_today(self, pending_count: int) -> int:
        """Сколько из очереди уйдёт сегодня (или после открытия окна)."""
        if pending_count <= 0:
            return 0
        if not self.in_work_hours():
            return min(pending_count, self.daily_limit)
        return min(pending_count, self.remaining_today())

    def status_lines(self, *, pending_count: int | None = None) -> list[str]:
        c = self.counts()
        lines = [
            f"Сегодня первые сообщения: {c['sent_today']}/{c['daily_limit']} "
            f"(осталось {c['remaining_today']})",
            f"Неделя (7 дн.): {c['sent_week']}/{c['weekly_limit']} "
            f"(осталось {c['remaining_week']})",
            f"Часы отправки: {c['work_start']}:00–{c['work_end']}:00 {c['timezone']} "
            f"(сейчас {c['moscow_time']}"
            + (", окно открыто" if c["in_work_hours"] else ", окно закрыто")
            + ")",
        ]
        if pending_count is not None:
            plan = self.planned_today(pending_count)
            carry = max(0, pending_count - plan)
            lines.append(
                f"Очередь pending: {pending_count} → сегодня ~{plan}, перенос на завтра: {carry}"
            )
            if plan > 0 and c["in_work_hours"]:
                gap = self.spacing_delay_sec(queue_left=plan)
                lines.append(
                    f"Интервал между первыми: ~{int(gap // 60)} мин {int(gap % 60)} сек"
                )
        if self.per_hour > 0:
            lines.append(f"Потолок часа: {c['hour']}/{c['max_hour']}")
        return lines

    def record_send(self, *, manager_id: str | None = None) -> None:
        """Только после успешного первого outreach-сообщения.

        manager_id — веб-менеджер, которому засчитать долю (может отличаться
        от self.manager_id при общей очереди аккаунта бота).
        """
        self._bump(self._key("outreach_cnt_h", self.hour_key()))
        self._bump(self._key("outreach_cnt_d", self.day_key()))
        mid = (manager_id if manager_id is not None else self.manager_id) or ""
        if mid:
            [REDACTED]
            self._bump(key)

    def pause_active(self) -> tuple[bool, str]:
        """Есть ли стоп на сегодня (FloodWait/PeerFlood)."""
        pause_until = self.store.get_meta(self._key("outreach_pause_until", "day"))
        if not pause_until:
            return False, ""
        try:
            if float(pause_until) > time.time():
                reason = self.store.get_meta(self._key("outreach_pause_reason", "day")) or (
                    "отправка остановлена на сегодня"
                )
                return True, reason
        except Exception:
            pass
        return False, ""

    def pause_for_day(self, reason: str) -> None:
        """FloodWait/PeerFlood — стоп до конца рабочих суток МСК + предупреждение в панели."""
        n = self.now()
        # work_end=20 → стоп до 20:00; work_end=24 (тесты) → до конца суток
        if self.work_end >= 24:
            end = n.replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(seconds=1)
        else:
            end = n.replace(hour=self.work_end, minute=0, second=0, microsecond=0)
            if n >= end:
                end = end + timedelta(days=1)
        self.store.set_meta(self._key("outreach_pause_until", "day"), str(end.timestamp()))
        self.store.set_meta(
            self._key("outreach_pause_reason", "day"), (reason or "")[:500]
        )
        self.set_last_error(reason)
        try:
            from bot.hub import get_hub

            hub = get_hub()
            hub.bus.publish(
                "account_warning",
                account_id=self.account_id,
                manager_id=self.manager_id,
                title="Стоп рассылки на сегодня",
                message=reason,
                level="error",
            )
            hub.notify(
                "Стоп рассылки на сегодня",
                reason,
                manager_id=self.manager_id or "",
                level="error",
            )
        except Exception:
            pass

    @classmethod
    def for_account(
        cls,
        store: Any,
        account: Any,
        *,
        manager_id: str = "",
    ) -> "OutreachLimiter":
        return cls(
            store,
            account_id=getattr(account, "id", "") or "",
            manager_id=manager_id,
            daily_limit=int(getattr(account, "daily_send_limit", None) or DEFAULT_DAILY),
            weekly_limit=int(getattr(account, "weekly_send_limit", None) or DEFAULT_WEEKLY),
            work_start=DEFAULT_WORK_START,
            work_end=DEFAULT_WORK_END,
            tz_name=DEFAULT_TZ_NAME,
        )

    @classmethod
    def for_manager(cls, store: Any, manager: Any) -> "OutreachLimiter":
        """Совместимость: лимит аккаунта менеджера (или shared)."""
        try:
            from bot.tg_accounts import get_tg_accounts

            acc = get_tg_accounts().for_manager(getattr(manager, "id", "") or "")
            if acc:
                return cls.for_account(store, acc, manager_id=getattr(manager, "id", "") or "")
        except Exception:
            pass
        return cls(
            store,
            manager_id=getattr(manager, "id", "") or "",
            daily_limit=int(getattr(manager, "daily_send_limit", None) or DEFAULT_DAILY),
            weekly_limit=int(getattr(manager, "weekly_send_limit", None) or DEFAULT_WEEKLY),
            work_start=int(getattr(manager, "work_hours_start", None) or DEFAULT_WORK_START),
            work_end=int(getattr(manager, "work_hours_end", None) or DEFAULT_WORK_END),
            tz_name=str(getattr(manager, "work_timezone", None) or DEFAULT_TZ_NAME),
        )

    def set_last_error(self, text: str) -> None:
        self.store.set_meta("last_error", (text or "")[:500])
        self.store.set_meta("last_error_at", str(time.time()))

    def last_error(self) -> str:
        return self.store.get_meta("last_error") or ""


def chunk_sleep_seconds(total: float, *, chunk: float = 30.0) -> list[float]:
    """Разбить долгое ожидание на куски (чтобы ловить /stop)."""
    if total <= 0:
        return []
    out: list[float] = []
    left = total
    while left > 0:
        step = min(chunk, left)
        out.append(step)
        left -= step
    return out
