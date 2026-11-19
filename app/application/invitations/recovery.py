from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Callable, Dict

from app.domain import invitations as policy
from app.domain.invitations import WorkerRecoveryError, protective_recovery_reason, settings_of

from .ports import AccountPort, InvitationRepository
from .preparation import CampaignAccountPreparation
from .runtime import CampaignRuntime


@dataclass
class CampaignAccountRecovery:
    repo: InvitationRepository
    accounts: AccountPort
    runtime: CampaignRuntime
    preparation: CampaignAccountPreparation
    spawn_worker: Callable[[int, int], asyncio.Task]

    async def recover_campaign_account(self, campaign_id: int, account_id: int) -> Dict[str, Any]:
        """Проверяет соединение и возвращает завершившийся воркер в живую кампанию.

        Суточная квота и next_attempt_at не сбрасываются. Защитные паузы Telegram
        также не обходятся; снимается только техническая пауза после сбоя соединения.
        """
        lock = self.runtime.recovery_locks.setdefault((campaign_id, account_id), asyncio.Lock())
        async with lock:
            campaign = self.repo.get_campaign(campaign_id)
            if not campaign:
                raise WorkerRecoveryError("Кампания не найдена")
            configured_ids = {
                int(value) for value in settings_of(campaign).get("account_ids", [])
            }
            if account_id not in configured_ids:
                raise WorkerRecoveryError("Аккаунт не входит в эту кампанию")

            runner = self.runtime.runners.get(campaign_id)
            state = self.runtime.state.get(campaign_id) or {}
            stop = state.get("stop")
            if not runner or runner.done() or not stop or stop.is_set():
                raise WorkerRecoveryError("Кампания сейчас не запущена")

            current_task = (state.get("worker_tasks") or {}).get(account_id)
            if current_task and not current_task.done():
                return {
                    "ok": True,
                    "already_active": True,
                    "state": str(
                        (state.get("workers") or {}).get(account_id, {}).get("state")
                        or "аккаунт уже в ротации"
                    ),
                }

            account = self.repo.get_account(account_id)
            if not account:
                raise WorkerRecoveryError("Аккаунт удалён")
            worker = state.setdefault("workers", {}).setdefault(account_id, {})
            blocked = protective_recovery_reason(account, worker, int(time.time()))
            if blocked:
                raise WorkerRecoveryError(blocked)

            old_state = str(worker.get("state") or "")
            technical_failure = any(
                marker in (old_state + " " + str(account.get("last_error") or ""))
                for marker in policy.TECHNICAL_RECOVERY_MARKERS
            )
            worker["state"] = "проверяю прокси и Telegram-сессию"
            proxy_result = await self.accounts.test_proxy(account_id)
            if not proxy_result.get("ok"):
                worker["state"] = "сбой подключения — проверьте прокси"
                raise WorkerRecoveryError(
                    "Прокси не прошёл проверку: %s" % proxy_result.get("error", "нет соединения")
                )
            if not proxy_result.get("authorized"):
                worker["state"] = "аккаунт не авторизован"
                self.accounts.set_status(account_id, "new", "Сессия не авторизована")
                raise WorkerRecoveryError("Прокси работает, но Telegram-сессия не авторизована")

            # Включаем инвайтинг и снимаем только техническую паузу. Общий
            # next_attempt_at намеренно не меняется — шестичасовой интервал сохранён.
            if technical_failure:
                self.repo.restore_technical_account(account_id)
            else:
                self.repo.restore_account(account_id)

            entity = await self.preparation.prepare(campaign, account_id)
            if entity is None:
                raise WorkerRecoveryError(
                    str(worker.get("state") or "Аккаунт не прошёл проверку целевого чата")
                )
            state.setdefault("target_entity_by_account", {})[account_id] = entity
            worker["state"] = "восстановлен · готов к работе"
            self.spawn_worker(campaign_id, account_id)
            self.repo.log(
                "Аккаунт проверен и возвращён в текущую кампанию без её остановки",
                scope="invite",
                campaign_id=campaign_id,
                account_id=account_id,
            )
            return {
                "ok": True,
                "already_active": False,
                "state": worker["state"],
                "latency_ms": proxy_result.get("latency_ms"),
                "verdict": proxy_result.get("verdict"),
            }
