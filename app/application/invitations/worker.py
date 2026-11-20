from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

from . import timing
from .attempts import InvitationAttempt
from .ports import AccountPort, InvitationRepository
from .preparation import CampaignAccountPreparation
from .runtime import CampaignRuntime
from .verification import MembershipVerification


@dataclass
class AccountWorker:
    repo: InvitationRepository
    accounts: AccountPort
    runtime: CampaignRuntime
    preparation: CampaignAccountPreparation
    verification: MembershipVerification
    attempts: InvitationAttempt

    async def run(self, campaign_id: int, account_id: int, stop: asyncio.Event) -> None:
        state = self.runtime.state.setdefault(campaign_id, {})
        workers = state.setdefault("workers", {})
        info = workers.setdefault(account_id, {})
        # Внутренний ограничитель считает отправленные Telegram-запросы, даже если
        # пользователь позже не появится в чате. Пользовательские счётчики при этом
        # увеличиваются только после отдельного подтверждения состава чата.
        requests_in_batch = 0

        while not stop.is_set():
            account = self.repo.get_account(account_id)
            eligible, eligibility_code, eligibility_detail = self.accounts.invite_eligibility(
                account,
                check_cooldown=False,
                check_quota=False,
            )
            if not eligible:
                info["state"] = eligibility_detail
                return

            info.pop("technical_retry_at", None)

            # Ошибка доступа к чату не должна навсегда выводить аккаунт из ротации.
            # После ожидания заново получаем сущность чата и актуальные права.
            if "access_retry_at" in info:
                access_retry = int(info.get("access_retry_at") or 0) - int(time.time())
                if access_retry > 0:
                    info["state"] = "перепроверка доступа через %d мин" % max(
                        1, (access_retry + 59) // 60
                    )
                    await timing.sleep(min(access_retry, 60), stop)
                    continue

                campaign = self.repo.get_campaign(campaign_id)
                if not campaign:
                    info["state"] = "кампания удалена"
                    return
                entity = await self.preparation.prepare(campaign, account_id)
                if stop.is_set():
                    return
                if entity is None:
                    # Доступ перепроверяется по таймеру; технический сбой
                    # подключения повторяем без дополнительного ожидания.
                    if (
                        "access_retry_at" in info
                        or "временный сбой подключения" in info.get("state", "")
                    ):
                        await asyncio.sleep(0)
                        continue
                    return
                state.setdefault("target_entity_by_account", {})[account_id] = entity
                info.pop("access_retry_at", None)
                info["state"] = "доступ к чату подтверждён · готов к работе"

            if await self.verification.retry_pending(campaign_id, account_id, info):
                if info.pop("halt_after_silent_loss", None):
                    info["state"] = "снят с ротации после тихих потерь"
                    return
                if not self.repo.has_unresolved_targets(campaign_id):
                    info["state"] = "цели закончились"
                    return
                continue

            cooldown = int(account["cooldown_until"] or 0) - int(time.time())
            if cooldown > 0:
                info["state"] = "пауза %d мин" % max(1, cooldown // 60)
                await timing.sleep(min(cooldown, 60), stop)
                continue

            scheduled = int(account.get("next_attempt_at") or 0) - int(time.time())
            if scheduled > 0:
                info["state"] = "до следующей попытки %d мин" % max(1, (scheduled + 59) // 60)
                await timing.sleep(min(scheduled, 60), stop)
                continue

            if self.accounts.quota_left(account) <= 0:
                info["state"] = "суточный лимит исчерпан"
                await timing.sleep(300, stop)
                continue

            target = self.repo.claim_target(campaign_id, account_id)
            if target is None:
                if not self.repo.has_unresolved_targets(campaign_id):
                    info["state"] = "цели закончились"
                    return
                info["state"] = "нет подходящих целей (нет своего access_hash)"
                await timing.sleep(30, stop)
                continue

            attempt = await self.attempts.run(campaign_id, account_id, target, info, stop)
            if attempt.halt_worker:
                return
            # Safe connection retries are limited to context resolution before the
            # durable marker. They do not consume the account slot.
            if attempt.outcome == "connection_error":
                await asyncio.sleep(0)
                continue

            if not attempt.keeps_interval:
                if attempt.outcome == "privacy":
                    info["state"] = "приватность — пропускаю"
                if not self.repo.has_unresolved_targets(campaign_id):
                    return
                continue

            # Внутренний batch учитывает отправленный Telegram-запрос. Публичные
            # счётчики при этом изменил только атомарный confirmed-переход выше.
            requests_in_batch += 1

            # Release/retain policy above is complete. If this outcome made the
            # campaign terminal, do not sleep merely because next_attempt_at is in
            # the future.
            if not self.repo.has_unresolved_targets(attempt.campaign_id):
                attempt.info["state"] = "цели закончились"
                return

            if requests_in_batch >= int(account["batch_size"] or 8):
                requests_in_batch = 0
                pause = int(account["batch_pause"] or 2700)
                # Пауза пачки может только продлить базовый интервал, но не сократить его.
                attempt.next_attempt_at = self.accounts.defer_next_attempt(attempt.account_id, pause)

            if (
                attempt.outcome == "pending_confirmation"
                and int(attempt.info.get("verification_retry_at") or 0) <= int(time.time())
            ):
                continue

            remaining = max(0, attempt.next_attempt_at - int(time.time()))
            attempt.info["state"] = "до следующей попытки %d мин" % max(1, (remaining + 59) // 60)
            await timing.sleep(min(remaining, 60), attempt.stop)
