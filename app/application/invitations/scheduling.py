from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Dict, List, Optional, Tuple

from app.domain import invitations as policy
from app.domain.invitations import (
    humanized_delay_seconds,
    settings_of,
    speed_profile_bounds,
    startup_stagger_delay,
)

from . import timing
from .ports import AccountPort, InvitationRepository
from .runtime import CampaignRuntime


@dataclass
class InvitationScheduler:
    repo: InvitationRepository
    accounts: AccountPort
    runtime: CampaignRuntime

    def running_campaign_slot(self, campaign: Dict[str, Any]) -> Tuple[int, int]:
        campaign_id = int(campaign["id"])
        rows = self.repo.running_for_chat(int(campaign['target_chat_id']))
        campaign_ids = [int(row["id"]) for row in rows]
        state = self.runtime.state.setdefault(campaign_id, {})
        existing = state.get("startup_stagger_slot")
        if existing is not None:
            slot = max(0, int(existing))
            return slot, max(1, len(campaign_ids), slot + 1)

        used = {
            int(self.runtime.state[other_id]["startup_stagger_slot"])
            for other_id in campaign_ids
            if other_id != campaign_id
            and other_id in self.runtime.state
            and self.runtime.state[other_id].get("startup_stagger_slot") is not None
        }
        slot = 0
        while slot in used:
            slot += 1
        state["startup_stagger_slot"] = slot
        return slot, max(1, len(campaign_ids), slot + 1)

    def schedule_startup_stagger(
        self,
        campaign: Dict[str, Any],
        account_ids: List[int],
        now: Optional[int] = None,
    ) -> Dict[int, int]:
        """Сохраняет стартовые слоты, не сокращая существующие таймеры аккаунтов."""
        base = int(now if now is not None else time.time())
        rank, active_campaigns = self.running_campaign_slot(campaign)
        scheduled: Dict[int, int] = {}
        workers = self.runtime.state.setdefault(int(campaign["id"]), {}).setdefault("workers", {})
        for position, account_id in enumerate(account_ids):
            delay = startup_stagger_delay(position, rank, active_campaigns)
            next_at = self.accounts.defer_next_attempt(account_id, delay, now=base)
            scheduled[account_id] = next_at
            remaining = max(0, next_at - base)
            if remaining:
                workers.setdefault(account_id, {})["state"] = (
                    "стартовая рассинхронизация: %d мин"
                    % max(1, (remaining + 59) // 60)
                )
        return scheduled

    async def reserve_account_slot(
        self,
        account_id: int,
        stop: asyncio.Event,
        info: Dict[str, Any],
    ) -> Optional[int]:
        """Атомарно резервирует следующий запрос конкретного аккаунта.

        Блокировка общая для всех кампаний этого аккаунта, но разные аккаунты
        используют разные блокировки и поэтому продолжают работать параллельно.
        """
        lock = self.runtime.account_locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            while not stop.is_set():
                account = self.repo.get_account(account_id)
                eligible, eligibility_code, eligibility_detail = self.accounts.invite_eligibility(
                    account
                )
                if not eligible and eligibility_code not in {"cooldown", "quota"}:
                    info["state"] = eligibility_detail
                    return None

                now = int(time.time())
                cooldown = int(account.get("cooldown_until") or 0) - now
                scheduled = int(account.get("next_attempt_at") or 0) - now
                remaining = max(cooldown, scheduled)
                if remaining > 0:
                    info["state"] = "до следующей попытки %d мин" % max(
                        1, (remaining + 59) // 60
                    )
                    await timing.sleep(min(remaining, 60), stop)
                    continue

                if eligibility_code == "quota":
                    info["state"] = "суточный лимит исчерпан"
                    await timing.sleep(300, stop)
                    continue

                delay = humanized_delay_seconds(
                    int(account["min_delay"]),
                    max(int(account["min_delay"]), int(account["max_delay"])),
                )
                return self.accounts.schedule_next_attempt(account_id, delay, now=now)
        return None

    def campaign_gap_bounds(self, campaign_id: int) -> Tuple[int, int]:
        campaign = self.repo.get_campaign(campaign_id)
        settings = settings_of(campaign) if campaign else {}
        if "invite_gap_min" in settings or "invite_gap_max" in settings:
            low = max(0, int(settings.get("invite_gap_min", policy.CAMPAIGN_INVITE_GAP_MIN)))
            high = max(low, int(settings.get("invite_gap_max", policy.CAMPAIGN_INVITE_GAP_MAX)))
            return low, high
        if settings.get("speed_profile"):
            return speed_profile_bounds(str(settings["speed_profile"]))
        low = max(0, int(policy.CAMPAIGN_INVITE_GAP_MIN))
        high = max(low, int(policy.CAMPAIGN_INVITE_GAP_MAX))
        return low, high

    async def reserve_campaign_slot(
        self,
        campaign_id: int,
        stop: asyncio.Event,
        info: Dict[str, Any],
    ) -> Optional[int]:
        """Ждёт общей очереди кампании и бронирует следующий интервал.

        Возвращает момент, раньше которого другой аккаунт этой кампании не
        отправит приглашение. Бронь хранится в БД и переживает перезапуск.
        """
        lock = self.runtime.campaign_locks.setdefault(campaign_id, asyncio.Lock())
        async with lock:
            logged_wait_until = 0
            while not stop.is_set():
                row = self.repo.campaign_next_invite(campaign_id)
                if not row:
                    return None
                now = int(time.time())
                wave_remaining = int(row.get("wave_pause_until") or 0) - now
                queue_remaining = int(row["next_invite_at"] or 0) - now
                remaining = max(wave_remaining, queue_remaining)
                if remaining > 0:
                    wait_until = max(
                        int(row.get("wave_pause_until") or 0),
                        int(row["next_invite_at"] or 0),
                    )
                    if logged_wait_until != wait_until:
                        if wave_remaining >= queue_remaining and wave_remaining > 0:
                            self.repo.log(
                                "Ожидание паузы между волнами: ещё %d сек; "
                                "следующее приглашение пока не отправлено" % remaining,
                                scope="invite",
                                campaign_id=campaign_id,
                            )
                        else:
                            self.repo.log(
                                "Ожидание общего интервала кампании: ещё %d сек; "
                                "следующее приглашение пока не отправлено" % remaining,
                                scope="invite",
                                campaign_id=campaign_id,
                            )
                        logged_wait_until = wait_until
                    info["state"] = (
                        "очередь кампании: запрос ещё не отправлен, ожидание %d мин"
                        % max(1, (remaining + 59) // 60)
                    )
                    await timing.sleep(min(remaining, 60), stop)
                    continue
                if logged_wait_until:
                    self.repo.log(
                        "Общий интервал кампании завершён; продолжаю подготовку приглашения",
                        scope="invite", campaign_id=campaign_id,
                    )
                # Мягкий потолок confirmed/сутки на целевой чат (Frankenstein).
                soft_cap = self._chat_soft_cap_message(campaign_id, row)
                if soft_cap is not None:
                    info["state"] = soft_cap
                    await timing.sleep(600, stop)
                    continue
                low, high = self.campaign_gap_bounds(campaign_id)
                next_at = now + humanized_delay_seconds(low, high)
                self.repo.reserve_campaign(next_at, campaign_id)
                return next_at
        return None

    def _chat_soft_cap_message(
        self, campaign_id: int, row: Dict[str, Any]
    ) -> Optional[str]:
        settings = settings_of({"settings": row.get("settings") or "{}"})
        cap = int(settings.get("chat_daily_confirmed_soft_cap") or 0)
        if cap <= 0:
            return None
        chat_id = int(row.get("target_chat_id") or 0)
        if not chat_id:
            campaign = self.repo.get_campaign(campaign_id)
            chat_id = int((campaign or {}).get("target_chat_id") or 0)
        if not chat_id:
            return None
        confirmed = self.repo.chat_confirmed_today(chat_id)
        if confirmed >= cap:
            return (
                "мягкий лимит чата: %d confirmed сегодня (cap %d) — жду до завтра"
                % (confirmed, cap)
            )
        return None

    def release_campaign_slot(self, campaign_id: int, reserved_at: int) -> None:
        """Отменяет бронь, если приглашение так и не было отправлено."""
        self.repo.release_campaign(campaign_id, int(reserved_at))
