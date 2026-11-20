"""До 5 Telegram-аккаунтов компании (физические SIM). Менеджеры — только веб."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("home24.tg_accounts")
_LOCK = threading.RLock()
MAX_ACCOUNTS = 6
def default_accounts_path() -> Path:
    return Path(os.getenv("TG_ACCOUNTS_PATH") or "data/tg_accounts.json")


def norm_phone(phone: str) -> str:
    s = (phone or "").strip().replace(" ", "").replace("-", "")
    if not s or s == "—":
        return ""
    if s.startswith("00"):
        s = "+" + s[2:]
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return ""
    if s.startswith("+"):
        return "+" + digits
    if len(digits) == 11 and digits.startswith("8"):
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    return "+" + digits if not s.startswith("+") else "+" + digits


def _default_quiet_hours() -> int:
    try:
        return max(0, int(os.getenv("TG_QUIET_HOURS_AFTER_LOGIN") or "24"))
    except Exception:
        return 24


def format_quiet_countdown(remaining_sec: int) -> str:
    sec = max(0, int(remaining_sec))
    if sec <= 0:
        return ""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}ч {m:02d}м"
    if m > 0:
        return f"{m}м {s:02d}с"
    return f"{s}с"


@dataclass
class TgAccount:
    id: str
    label: str = ""
    phone: str = ""
    session: str = ""
    manager_id: str = ""  # к какому веб-менеджеру привязан (пусто = общий)
    is_main: bool = False
    daily_send_limit: int = 30
    weekly_send_limit: int = 210
    status: str = "ok"  # ok | paused | restricted | revoked
    status_note: str = ""
    enabled: bool = True
    telegram_user_id: str = ""  # Telethon me.id — для дедупа
    # после нового входа — не слать first-touch outreach до этого unix-ts
    no_outreach_until: float = 0.0
    # сколько часов тишины ставить при свежей сессии (настройка админа)
    quiet_hours_after_login: int = field(default_factory=_default_quiet_hours)
    # честный device fingerprint — один на слот, переиспользуется при каждом connect
    device_model: str = ""
    system_version: str = ""
    app_version: str = ""
    # откуда сессия: qr | code | tdata | legacy
    auth_source: str = ""
    # server — свой IP VPS; current — прокси этого контура; bought — купленный IP
    egress: str = "server"
    last_connect_at: float = 0.0
    last_disconnect_at: float = 0.0

    @property
    def paused(self) -> bool:
        return self.status in ("paused", "restricted", "revoked") or not self.enabled

    def quiet_remaining_sec(self, now: float | None = None) -> int:
        until = float(self.no_outreach_until or 0)
        if until <= 0:
            return 0
        t = time.time() if now is None else float(now)
        return max(0, int(until - t))

    def outreach_quiet_status(self, now: float | None = None) -> tuple[bool, str]:
        """True, reason — если first-touch outreach запрещён (тишина после входа)."""
        flag = (os.getenv("HOME24_SKIP_QUIET") or "").strip().lower()
        if flag in ("1", "true", "yes", "on"):
            return False, ""
        left = self.quiet_remaining_sec(now)
        if left <= 0:
            return False, ""
        return (
            True,
            f"тишина после входа: ещё {format_quiet_countdown(left)} "
            f"(ответы гостям работают)",
        )

    def apply_quiet_after_fresh_login(self) -> None:
        hours = max(0, int(self.quiet_hours_after_login or 0))
        if hours <= 0:
            return
        self.no_outreach_until = time.time() + hours * 3600.0

    def device_dict(self) -> dict[str, str]:
        return {
            "device_model": (self.device_model or "").strip(),
            "system_version": (self.system_version or "").strip(),
            "app_version": (self.app_version or "").strip(),
        }

    def ensure_device_fingerprint(self) -> dict[str, str]:
        """Заполнить пустые поля. Уже записанные не трогаем: смена ядра или
        версии процесса не должна выглядеть для Telegram как новое устройство.
        """
        from bot.device import default_device_fingerprint

        base = default_device_fingerprint()
        if not (self.device_model or "").strip():
            self.device_model = base["device_model"]
        if not (self.system_version or "").strip():
            self.system_version = base["system_version"]
        if not (self.app_version or "").strip():
            self.app_version = base["app_version"]
        return self.device_dict()

    def public_dict(self) -> dict[str, Any]:
        left = self.quiet_remaining_sec()
        return {
            "id": self.id,
            "label": self.label or self.id,
            "phone": self.phone or "—",
            "has_session": bool((self.session or "").strip()),
            "manager_id": self.manager_id or "",
            "is_main": self.is_main,
            "daily_send_limit": self.daily_send_limit,
            "weekly_send_limit": self.weekly_send_limit,
            "status": self.status,
            "status_note": self.status_note,
            "enabled": self.enabled,
            "paused": self.paused,
            "telegram_user_id": self.telegram_user_id or "",
            "revoked": self.status == "revoked",
            "quiet_hours_after_login": int(self.quiet_hours_after_login or 0),
            "no_outreach_until": float(self.no_outreach_until or 0),
            "quiet_remaining_sec": left,
            "quiet_active": left > 0,
            "quiet_label": (
                f"тишина ещё {format_quiet_countdown(left)}" if left > 0 else ""
            ),
            "device_model": self.device_model or "",
            "system_version": self.system_version or "",
            "app_version": self.app_version or "",
            "auth_source": self.auth_source or "",
            "egress": (self.egress or "server"),
            "last_connect_at": float(self.last_connect_at or 0),
            "last_disconnect_at": float(self.last_disconnect_at or 0),
            "tdata_warning": (self.auth_source or "") == "tdata",
        }


def _default_daily_for_new() -> int:
    return int(os.getenv("TG_ACCOUNT_NEW_DAILY_LIMIT") or "30")


SAFE_MAIN_DAILY = 30
SAFE_MAIN_WEEKLY = 210


def _default_daily_main() -> int:
    return min(int(os.getenv("DAILY_SEND_LIMIT") or str(SAFE_MAIN_DAILY)), SAFE_MAIN_DAILY)


def _default_weekly() -> int:
    return min(int(os.getenv("WEEKLY_SEND_LIMIT") or str(SAFE_MAIN_WEEKLY)), SAFE_MAIN_WEEKLY)


def _cap_main_account(acc: TgAccount) -> bool:
    """main не уходит выше 30/день и 210/неделю, даже если в json остались старые цифры."""
    if acc.id != "main":
        return False
    changed = False
    if int(acc.daily_send_limit or 0) > SAFE_MAIN_DAILY:
        acc.daily_send_limit = SAFE_MAIN_DAILY
        changed = True
    if int(acc.weekly_send_limit or 0) > SAFE_MAIN_WEEKLY:
        acc.weekly_send_limit = SAFE_MAIN_WEEKLY
        changed = True
    return changed


def _parse_until(raw: Any) -> float:
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        pass
    # ISO / datetime-local «2026-09-28T21:00»
    try:
        from datetime import datetime

        ss = s.replace("Z", "+00:00")
        if "T" in ss and len(ss) == 16:
            ss += ":00"
        return datetime.fromisoformat(ss).timestamp()
    except Exception:
        return 0.0


def _from_dict(raw: dict[str, Any]) -> TgAccount:
    qh = raw.get("quiet_hours_after_login")
    if qh is None:
        quiet_h = _default_quiet_hours()
    else:
        try:
            quiet_h = max(0, int(qh))
        except Exception:
            quiet_h = _default_quiet_hours()
    return TgAccount(
        id=str(raw.get("id") or "main"),
        label=str(raw.get("label") or raw.get("id") or ""),
        phone=str(raw.get("phone") or ""),
        session=str(raw.get("session") or ""),
        manager_id=str(raw.get("manager_id") or ""),
        is_main=bool(raw.get("is_main")),
        daily_send_limit=int(raw.get("daily_send_limit") or _default_daily_main()),
        weekly_send_limit=int(raw.get("weekly_send_limit") or _default_weekly()),
        status=str(raw.get("status") or "ok"),
        status_note=str(raw.get("status_note") or ""),
        enabled=bool(raw.get("enabled", True)),
        telegram_user_id=str(raw.get("telegram_user_id") or raw.get("user_id") or ""),
        no_outreach_until=_parse_until(raw.get("no_outreach_until")),
        quiet_hours_after_login=quiet_h,
        device_model=str(raw.get("device_model") or ""),
        system_version=str(raw.get("system_version") or ""),
        app_version=str(raw.get("app_version") or ""),
        auth_source=str(raw.get("auth_source") or ""),
        egress=str(raw.get("egress") or "server"),
        last_connect_at=float(raw.get("last_connect_at") or 0),
        last_disconnect_at=float(raw.get("last_disconnect_at") or 0),
    )


class TgAccountRegistry:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or default_accounts_path())
        self.accounts: dict[str, TgAccount] = {}
        self.load()

    def load(self) -> None:
        with _LOCK:
            if not self.path.exists():
                self._bootstrap()
                self.save()
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.accounts = {}
            for item in data.get("accounts") or []:
                if isinstance(item, dict):
                    a = _from_dict(item)
                    self.accounts[a.id] = a
            if not self.accounts:
                self._bootstrap()
            # авто-починка дублей (main+anna с одним телефоном/сессией)
            notes = self._repair_duplicates_unlocked()
            for n in notes:
                logger.warning("tg_accounts repair: %s", n)
            capped = False
            for acc in self.accounts.values():
                if _cap_main_account(acc):
                    capped = True
                    logger.warning(
                        "tg_accounts: main outreach capped to %s/day %s/week",
                        SAFE_MAIN_DAILY,
                        SAFE_MAIN_WEEKLY,
                    )
            if capped and self.path.exists():
                bak = self.path.with_name(self.path.name + ".bak-limits")
                if not bak.exists():
                    bak.write_bytes(self.path.read_bytes())
            if notes or capped:
                self.save()

    def _bootstrap(self) -> None:
        """Один main-аккаунт из TELEGRAM_SESSION / managers default."""
        sess = (os.getenv("TELEGRAM_SESSION") or "").strip()
        phone = (os.getenv("MANAGER_PHONE") or "").strip()
        # также подтянуть из managers.json default если есть
        try:
            from bot.managers import get_registry

            reg = get_registry()
            d = reg.default()
            if not sess and d.session:
                sess = d.session
            if not phone and d.phone:
                phone = d.phone
        except Exception:
            pass
        self.accounts = {
            "main": TgAccount(
                id="main",
                label="Основной",
                phone=phone,
                session=sess,
                is_main=True,
                daily_send_limit=_default_daily_main(),
                weekly_send_limit=_default_weekly(),
            )
        }

    def save(self) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"accounts": [asdict(a) for a in self.accounts.values()]}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            tmp.replace(self.path)

    def list_public(self) -> list[dict[str, Any]]:
        return [a.public_dict() for a in self.accounts.values()]

    def get(self, account_id: str) -> TgAccount | None:
        return self.accounts.get(account_id)

    def freeze_device_fingerprint(self, account_id: str) -> dict[str, str]:
        """Зафиксировать отпечаток на диск до любого connect.

        Если записать его только после входа, обрыв между QR и save
        подставит другое устройство на следующем старте — Telegram
        воспринимает это как чужой клиент и отзывает сессию.
        """
        from bot.device import default_device_fingerprint

        account = self.accounts.get((account_id or "").strip())
        if account is None:
            return default_device_fingerprint()
        before = account.device_dict()
        frozen = account.ensure_device_fingerprint()
        if frozen != before:
            self.save()
            logger.info(
                "device frozen account=%s model=%s system=%s app=%s",
                account.id,
                frozen.get("device_model"),
                frozen.get("system_version"),
                frozen.get("app_version"),
            )
        return frozen

    def main(self) -> TgAccount | None:
        for a in self.accounts.values():
            if a.is_main:
                return a
        return next(iter(self.accounts.values()), None)

    def active_with_session(self) -> list[TgAccount]:
        return [
            a
            for a in self.accounts.values()
            if a.enabled
            and a.status == "ok"
            and (a.session or "").strip()
        ]

    def sole_shared(self) -> TgAccount | None:
        """Ровно один подключённый аккаунт компании → все менеджеры делят его.

        Считаем слоты с сессией (даже paused): иначе при ограничении одной SIM
        остальные менеджеры ошибочно «подхватят» чужой аккаунт.
        """
        connected = self.ready_with_session()
        if len(connected) != 1:
            return None
        only = connected[0]
        if only.status != "ok" or not only.enabled:
            return None
        return only

    def ready_with_session(self) -> list[TgAccount]:
        """Все enabled-аккаунты с сессией (вкл. paused — чтобы не поднимать второй клиент)."""
        return [
            a
            for a in self.accounts.values()
            if a.enabled and (a.session or "").strip()
        ]

    def for_manager(self, manager_id: str) -> TgAccount | None:
        """Аккаунт для отправки от имени менеджера.

        1 аккаунт → все менеджеры делят его.
        Несколько → только слот с manager_id (без чужого main / чужой SIM).
        """
        shared = self.sole_shared()
        if shared:
            return shared
        mid = (manager_id or "").strip()
        if not mid:
            return None
        for a in self.active_with_session():
            if a.manager_id == mid:
                return a
        return None

    def for_contact(
        self, tg_account_id: str, *, manager_id: str = ""
    ) -> TgAccount | None:
        """Клиент навсегда на одном аккаунте: вернуть его слот даже если paused.

        Не подменяет другим аккаунтом. Если слота ещё нет — for_manager.
        """
        aid = (tg_account_id or "").strip()
        if aid:
            a = self.accounts.get(aid)
            if a is not None:
                return a
            return None
        return self.for_manager(manager_id)

    def _unbind_manager(self, manager_id: str, *, except_id: str = "") -> None:
        mid = (manager_id or "").strip()
        if not mid:
            return
        for a in self.accounts.values():
            if a.id != except_id and a.manager_id == mid:
                a.manager_id = ""

    def set_session(
        self,
        account_id: str,
        session: str,
        *,
        phone: str | None = None,
        label: str | None = None,
    ) -> TgAccount:
        with _LOCK:
            a = self.accounts.get(account_id)
            if not a:
                raise KeyError(account_id)
            a.session = session or ""
            if phone is not None:
                a.phone = phone
            if label:
                a.label = label
            if a.status in ("revoked",) and session:
                a.status = "ok"
                a.status_note = ""
            self.save()
            return a

    def mark_paused(self, account_id: str, note: str, *, status: str = "restricted") -> None:
        with _LOCK:
            a = self.accounts.get(account_id)
            if not a:
                return
            a.status = status
            a.status_note = (note or "")[:500]
            self.save()
            logger.warning("tg account %s -> %s: %s", account_id, status, note)

    def mark_revoked(
        self,
        account_id: str,
        note: str,
        *,
        clear_session: bool = True,
    ) -> None:
        """Сессия мертва: слот остаётся, клиент не поднимается, дашборд живёт."""
        with _LOCK:
            a = self.accounts.get(account_id)
            if not a:
                return
            a.status = "revoked"
            a.status_note = (note or "сессия отозвана")[:500]
            if clear_session:
                a.session = ""
            self.save()
            logger.error("tg account %s revoked: %s", account_id, a.status_note)

    def session_already_used(self, session: str, *, except_id: str = "") -> TgAccount | None:
        sess = (session or "").strip()
        if not sess:
            return None
        for a in self.accounts.values():
            if a.id == except_id:
                continue
            if (a.session or "").strip() == sess:
                return a
        return None

    def find_by_identity(
        self,
        *,
        telegram_user_id: str = "",
        phone: str = "",
        session: str = "",
    ) -> TgAccount | None:
        uid = str(telegram_user_id or "").strip()
        phone_n = norm_phone(phone)
        sess = (session or "").strip()
        if uid:
            for a in self.accounts.values():
                if a.telegram_user_id and a.telegram_user_id == uid:
                    return a
        if phone_n:
            for a in self.accounts.values():
                if norm_phone(a.phone) == phone_n:
                    return a
        if sess:
            for a in self.accounts.values():
                if (a.session or "").strip() == sess:
                    return a
        return None

    def _same_identity(self, a: TgAccount, b: TgAccount) -> bool:
        if a.id == b.id:
            return True
        if a.telegram_user_id and b.telegram_user_id and a.telegram_user_id == b.telegram_user_id:
            return True
        pa, pb = norm_phone(a.phone), norm_phone(b.phone)
        if pa and pb and pa == pb:
            return True
        sa, sb = (a.session or "").strip(), (b.session or "").strip()
        if sa and sb and sa == sb:
            return True
        return False

    def _disable_as_duplicate(self, other: TgAccount, keep: TgAccount) -> str | None:
        """Отключить дубликат. None если уже в нужном состоянии (идемпотентно)."""
        note = (
            f"дубликат того же Telegram, что [{keep.id}] "
            f"(телефон/user_id/сессия). Отключён — войдите один раз в Аккаунтах."
        )
        changed = False
        if other.enabled:
            other.enabled = False
            changed = True
        if (other.session or "").strip():
            other.session = ""
            changed = True
        if other.status == "ok":
            other.status = "revoked"
            changed = True
        if (other.status_note or "") != note:
            other.status_note = note
            changed = True
        if other.manager_id and not keep.manager_id:
            keep.manager_id = other.manager_id
            changed = True
        if other.telegram_user_id and not keep.telegram_user_id:
            keep.telegram_user_id = other.telegram_user_id
            changed = True
        if norm_phone(other.phone) and not norm_phone(keep.phone):
            keep.phone = other.phone
            changed = True
        if not changed:
            return None
        return f"{other.id} disabled as duplicate of {keep.id}"

    def _repair_duplicates_unlocked(self) -> list[str]:
        notes: list[str] = []
        accounts = list(self.accounts.values())
        used: set[str] = set()
        for i, a in enumerate(accounts):
            if a.id in used:
                continue
            group = [a]
            used.add(a.id)
            for b in accounts[i + 1 :]:
                if b.id in used:
                    continue
                if self._same_identity(a, b):
                    group.append(b)
                    used.add(b.id)
            if len(group) <= 1:
                continue
            # предпочесть is_main, затем id=main, затем с сессией
            keep = sorted(
                group,
                [REDACTED] x: (
                    not x.is_main,
                    x.id != "main",
                    not bool((x.session or "").strip()),
                    x.id,
                ),
            )[0]
            if not keep.enabled:
                keep.enabled = True
                notes.append(f"{keep.id}: re-enabled as canonical slot")
            if keep.id == "main" and not keep.is_main:
                keep.is_main = True
                notes.append(f"{keep.id}: set is_main")
            for o in group:
                if o.id == keep.id:
                    continue
                msg = self._disable_as_duplicate(o, keep)
                if msg:
                    notes.append(msg)
        # один is_main среди enabled
        mains = [a for a in self.accounts.values() if a.is_main and a.enabled]
        if len(mains) > 1:
            keep_m = next((a for a in mains if a.id == "main"), mains[0])
            for a in mains:
                if a.id != keep_m.id:
                    a.is_main = False
                    notes.append(f"{a.id}: сняли is_main (оставлен {keep_m.id})")
        elif not any(a.is_main for a in self.accounts.values()) and self.accounts:
            if "main" in self.accounts:
                if not self.accounts["main"].is_main:
                    self.accounts["main"].is_main = True
                    notes.append("main: set is_main (none had it)")
            else:
                first = next(iter(self.accounts.values()))
                if not first.is_main:
                    first.is_main = True
                    notes.append(f"{first.id}: set is_main (none had it)")
        return notes

    def repair_duplicates(self) -> list[str]:
        """Идемпотентно. Возвращает notes только если что-то реально изменилось."""
        with _LOCK:
            notes = self._repair_duplicates_unlocked()
            if notes:
                self.save()
            return notes

    def unique_ready_ok(self) -> list[TgAccount]:
        """Аккаунты для старта: status=ok, не blacklist, без дублей сессии."""
        try:
            from bot.session_blacklist import is_blacklisted
        except Exception:
            def is_blacklisted(_s: str) -> bool:  # type: ignore
                return False

        ready = [
            a
            for a in self.accounts.values()
            if a.enabled and a.status == "ok" and (a.session or "").strip()
        ]
        seen: set[str] = set()
        out: list[TgAccount] = []
        for a in sorted(ready, [REDACTED] x: (not x.is_main, x.id != "main", x.id)):
            s = (a.session or "").strip()
            if is_blacklisted(s):
                if a.status != "revoked" or (a.session or "").strip():
                    a.status = "revoked"
                    a.status_note = (
                        "сессия в чёрном списке (отозвана ранее) — войдите заново"
                    )
                    a.session = ""
                    self.save()
                    logger.warning(
                        "cleared blacklisted session for account=%s — нужен новый вход",
                        a.id,
                    )
                continue
            if s in seen:
                logger.warning(
                    "skip duplicate session client for account=%s (already starting another)",
                    a.id,
                )
                continue
            seen.add(s)
            out.append(a)
        return out

    def reject_duplicate_phone(
        self, phone: str, *, except_id: str = ""
    ) -> str | None:
        """Если телефон уже в другом живом слоте — вернуть сообщение об ошибке."""
        phone_n = norm_phone(phone)
        if not phone_n:
            return None
        for a in self.accounts.values():
            if except_id and a.id == except_id:
                continue
            if not a.enabled:
                continue
            if norm_phone(a.phone) != phone_n:
                continue
            if (a.session or "").strip() or a.status == "ok":
                return (
                    f"Телефон {phone_n} уже привязан к аккаунту [{a.id}]. "
                    "Один номер — один слот. Удалите/отзовите старый вход "
                    "или войдите в существующий аккаунт."
                )
        return None

    def apply_authorized_session(
        self,
        *,
        session: str,
        phone: str = "",
        telegram_user_id: str | int = "",
        manager_id: str = "",
        preferred_account_id: str = "",
        label: str = "",
        auth_source: str = "",
        allow_phone_rebind: bool = True,
    ) -> TgAccount:
        """Сохранить живую сессию. Никогда не создаёт второй слот для того же TG-юзера."""
        sess = (session or "").strip()
        if not sess:
            raise ValueError("пустая сессия")
        uid = str(telegram_user_id or "").strip()
        phone_raw = (phone or "").strip()
        phone_n = norm_phone(phone_raw)
        mid = (manager_id or "").strip()
        preferred = (preferred_account_id or "").strip()

        with _LOCK:
            match = self.find_by_identity(
                telegram_user_id=uid, phone=phone_n or phone_raw, session=sess
            )
            # жёсткий запрет: новый слот с телефоном, который уже занят другим
            if not match and phone_n:
                dup = self.reject_duplicate_phone(phone_n, except_id=preferred)
                if dup and not allow_phone_rebind:
                    raise ValueError(dup)
                if dup and preferred and preferred not in self.accounts:
                    raise ValueError(dup)
            first_live = not any(
                (a.session or "").strip() and a.status == "ok" and a.enabled
                for a in self.accounts.values()
            )

            if match:
                account_id = match.id
            elif first_live and "main" in self.accounts:
                account_id = "main"
            elif first_live:
                account_id = "main"
            else:
                account_id = preferred or mid or f"sim{len(self.accounts) + 1}"

            if account_id not in self.accounts:
                if len(self.accounts) >= MAX_ACCOUNTS:
                    # переиспользовать пустой/revoked слот
                    spare = next(
                        (
                            a
                            for a in self.accounts.values()
                            if not (a.session or "").strip() or a.status == "revoked"
                        ),
                        None,
                    )
                    if spare:
                        account_id = spare.id
                    else:
                        raise ValueError(f"максимум {MAX_ACCOUNTS} Telegram-аккаунтов")

            prev_sess = ""
            if account_id in self.accounts:
                prev_sess = (self.accounts[account_id].session or "").strip()

            is_main = first_live or account_id == "main" or (
                match.is_main if match else False
            )
            if account_id not in self.accounts:
                if is_main:
                    for a in self.accounts.values():
                        a.is_main = False
                if mid:
                    self._unbind_manager(mid, except_id=account_id)
                daily = _default_daily_main() if is_main else _default_daily_for_new()
                self.accounts[account_id] = TgAccount(
                    id=account_id,
                    label=label or ("Основной" if account_id == "main" else account_id),
                    manager_id=mid,  # "" = общий (1 SIM на всех)
                    is_main=is_main or not self.accounts,
                    daily_send_limit=daily,
                    weekly_send_limit=_default_weekly(),
                    quiet_hours_after_login=_default_quiet_hours(),
                )
            else:
                a = self.accounts[account_id]
                if label:
                    a.label = label
                if mid:
                    self._unbind_manager(mid, except_id=account_id)
                # всегда пишем bind, в т.ч. очистку → общий
                a.manager_id = mid
                if is_main:
                    for x in self.accounts.values():
                        x.is_main = False
                    a.is_main = True

            a = self.accounts[account_id]
            # телефон уже у другого живого слота (не match) — отказ
            if phone_n:
                for o in self.accounts.values():
                    if o.id == a.id:
                        continue
                    if not o.enabled:
                        continue
                    if norm_phone(o.phone) == phone_n and (
                        (o.session or "").strip() or o.status == "ok"
                    ):
                        if not self._same_identity(a, o) and (
                            not uid or o.telegram_user_id != uid
                        ):
                            raise ValueError(
                                f"Телефон {phone_n} уже привязан к аккаунту [{o.id}]. "
                                "Один номер — один слот."
                            )
            a.session = sess
            if phone_raw:
                a.phone = phone_raw if phone_raw.startswith("+") else (phone_n or phone_raw)
            elif phone_n:
                a.phone = phone_n
            if uid:
                a.telegram_user_id = uid
            a.enabled = True
            a.status = "ok"
            a.status_note = ""
            a.ensure_device_fingerprint()
            if auth_source:
                a.auth_source = str(auth_source).strip()[:32]
            a.last_connect_at = time.time()
            # свежий вход (другая строка сессии) → тишина outreach; тот же sess — не трогать
            fresh_login = bool(sess) and sess != prev_sess
            if fresh_login:
                a.apply_quiet_after_fresh_login()
                logger.info(
                    "quiet period after login account=%s until=%.0f (+%sh)",
                    a.id,
                    a.no_outreach_until,
                    a.quiet_hours_after_login,
                )
            # первый живой — main; bind только если явно передан manager_id
            if first_live:
                for x in self.accounts.values():
                    x.is_main = False
                a.is_main = True
                a.manager_id = mid
            _cap_main_account(a)

            for o in list(self.accounts.values()):
                if o.id == a.id:
                    continue
                if self._same_identity(a, o):
                    self._disable_as_duplicate(o, a)

            self.save()
            try:
                from bot.session_blacklist import unblacklist_session

                unblacklist_session(sess)
            except Exception:
                pass
            logger.info(
                "tg session applied account=%s main=%s manager=%s user_id=%s phone=%s",
                a.id,
                a.is_main,
                a.manager_id,
                a.telegram_user_id,
                a.phone,
            )
            return a

    def upsert(
        self,
        *,
        account_id: str,
        label: str = "",
        manager_id: str = "",
        daily_send_limit: int | None = None,
        weekly_send_limit: int | None = None,
        is_main: bool = False,
        quiet_hours_after_login: int | None = None,
        no_outreach_until: Any = None,
    ) -> TgAccount:
        with _LOCK:
            if account_id not in self.accounts and len(self.accounts) >= MAX_ACCOUNTS:
                raise ValueError(f"максимум {MAX_ACCOUNTS} Telegram-аккаунтов")
            existing = self.accounts.get(account_id)
            if existing:
                if label:
                    existing.label = label
                if manager_id is not None:
                    mid = (manager_id or "").strip()
                    if mid:
                        self._unbind_manager(mid, except_id=account_id)
                    existing.manager_id = mid
                if daily_send_limit is not None:
                    existing.daily_send_limit = int(daily_send_limit)
                if weekly_send_limit is not None:
                    existing.weekly_send_limit = int(weekly_send_limit)
                _cap_main_account(existing)
                if quiet_hours_after_login is not None:
                    existing.quiet_hours_after_login = max(
                        0, int(quiet_hours_after_login)
                    )
                if no_outreach_until is not None:
                    existing.no_outreach_until = _parse_until(no_outreach_until)
                if is_main:
                    for a in self.accounts.values():
                        a.is_main = False
                    existing.is_main = True
                self.save()
                return existing
            daily = (
                int(daily_send_limit)
                if daily_send_limit is not None
                else (_default_daily_main() if is_main or not self.accounts else _default_daily_for_new())
            )
            weekly = int(weekly_send_limit) if weekly_send_limit is not None else _default_weekly()
            if is_main or not self.accounts:
                for a in self.accounts.values():
                    a.is_main = False
            mid = (manager_id or "").strip()
            if mid:
                self._unbind_manager(mid, except_id=account_id)
            qh = (
                max(0, int(quiet_hours_after_login))
                if quiet_hours_after_login is not None
                else _default_quiet_hours()
            )
            a = TgAccount(
                id=account_id,
                label=label or account_id,
                manager_id=mid,
                is_main=is_main or not self.accounts,
                daily_send_limit=daily,
                weekly_send_limit=weekly,
                quiet_hours_after_login=qh,
                no_outreach_until=_parse_until(no_outreach_until)
                if no_outreach_until is not None
                else 0.0,
            )
            _cap_main_account(a)
            self.accounts[account_id] = a
            self.save()
            return a

    def set_enabled(self, account_id: str, enabled: bool) -> bool:
        with _LOCK:
            a = self.accounts.get(account_id)
            if not a:
                return False
            a.enabled = bool(enabled)
            a.paused = not bool(enabled)
            self.save()
            return True

    def delete(self, account_id: str) -> bool:
        with _LOCK:
            if account_id not in self.accounts:
                return False
            if len(self.accounts) <= 1:
                raise ValueError("нельзя удалить единственный аккаунт")
            del self.accounts[account_id]
            if not any(a.is_main for a in self.accounts.values()):
                next(iter(self.accounts.values())).is_main = True
            self.save()
            return True


_reg: TgAccountRegistry | None = None


def get_tg_accounts(path: Path | str | None = None) -> TgAccountRegistry:
    global _reg
    if path is not None:
        return TgAccountRegistry(path)
    if _reg is None:
        _reg = TgAccountRegistry()
    return _reg


def reset_tg_accounts_cache() -> None:
    global _reg
    _reg = None
