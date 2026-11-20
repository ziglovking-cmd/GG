from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List

from app.domain import invitations as policy
from app.domain.invitations import settings_of

from . import timing
from .ports import InvitationRepository
from .preparation import CampaignAccountPreparation
from .runtime import CampaignRuntime
from .scheduling import InvitationScheduler
from .worker import AccountWorker


@dataclass
class CampaignRunner:
    repo: InvitationRepository
    runtime: CampaignRuntime
    preparation: CampaignAccountPreparation
    scheduler: InvitationScheduler
    worker: AccountWorker

    def spawn_worker(self, campaign_id: int, account_id: int) -> asyncio.Task:
        state = self.runtime.state[campaign_id]
        task = asyncio.create_task(
            self.worker.run(campaign_id, account_id, state["stop"]),
            name="campaign-%d-account-%d" % (campaign_id, account_id),
        )
        state.setdefault("worker_tasks", {})[account_id] = task
        return task

    async def run_campaign(self, campaign_id: int) -> None:
        campaign = self.repo.get_campaign(campaign_id)
        settings = settings_of(campaign)
        account_ids: List[int] = settings.get("account_ids") or []
        stop = asyncio.Event()
        state = self.runtime.state.setdefault(campaign_id, {})
        state["stop"] = stop
        state["workers"] = {}
        state["target_entity_by_account"] = {}
        state["worker_tasks"] = {}
        state["target_chat_id"] = int(campaign["target_chat_id"])

        self.repo.set_campaign_status('running', campaign_id)
        self.repo.log(
            'Кампания «%s» запущена' % campaign['name'],
            scope='invite',
            campaign_id=campaign_id,
        )

        prepared = await asyncio.gather(*[
            self.preparation.prepare(campaign, account_id) for account_id in account_ids
        ])
        if stop.is_set():
            return

        usable: List[int] = []
        waiting_for_connection: List[int] = []
        waiting_for_access: List[int] = []
        for account_id, entity in zip(account_ids, prepared):
            if entity is None:
                worker_info = state.get("workers", {}).get(account_id, {})
                worker_state = str(worker_info.get("state") or "")
                if "временный сбой подключения" in worker_state:
                    waiting_for_connection.append(account_id)
                elif "access_retry_at" in worker_info:
                    waiting_for_access.append(account_id)
                continue
            state["target_entity_by_account"][account_id] = entity
            usable.append(account_id)

        rotating = usable + waiting_for_connection + waiting_for_access
        if not rotating:
            self.repo.set_campaign_status('error', campaign_id)
            self.repo.log("Нет ни одного аккаунта, состоящего в целевом чате с правом приглашать. "
                   "Заведите аккаунты в целевой чат вручную и повторите.",
                   level="error", scope="invite", campaign_id=campaign_id)
            return

        self.repo.log(
            "В ротации %d аккаунт(ов), ожидают соединения: %d, "
            "перепроверки доступа: %d"
            % (len(rotating), len(waiting_for_connection), len(waiting_for_access)),
            scope="invite",
            campaign_id=campaign_id,
        )

        unreachable = self.repo.mark_unreachable(campaign_id, rotating)
        if unreachable:
            self.repo.log("Недоступно %d целей: нет @username и ни один аккаунт из ротации их не парсил. "
                   "Заведите инвайтеры в чат-донор и спарсите его каждым из них."
                   % unreachable, level="warn", scope="invite", campaign_id=campaign_id)

        self.scheduler.schedule_startup_stagger(campaign, rotating)
        self.repo.log(
            "Старт распределён волнами: до %d аккаунтов каждые %d минут, "
            "между параллельными кампаниями сдвиг %d минут, разброс до %d секунд"
            % (
                policy.START_STAGGER_BATCH_SIZE,
                policy.START_STAGGER_BATCH_INTERVAL // 60,
                policy.START_STAGGER_CAMPAIGN_INTERVAL // 60,
                policy.START_STAGGER_JITTER,
            ),
            scope="invite",
            campaign_id=campaign_id,
        )

        for account_id in rotating:
            self.spawn_worker(campaign_id, account_id)

        try:
            while not stop.is_set():
                active_tasks = [
                    task for task in state.get("worker_tasks", {}).values()
                    if not task.done()
                ]
                if not active_tasks:
                    # Короткое окно оставляет возможность вернуть последний
                    # технически выпавший воркер до завершения runner-а.
                    await timing.sleep(1, stop)
                    active_tasks = [
                        task for task in state.get("worker_tasks", {}).values()
                        if not task.done()
                    ]
                    if not active_tasks:
                        break
                await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            stop.set()
            raise
        finally:
            stop.set()
            remaining_tasks = [
                task for task in state.get("worker_tasks", {}).values()
                if not task.done()
            ]
            if remaining_tasks:
                await asyncio.gather(*remaining_tasks, return_exceptions=True)
            # Только v1-маркер доказывает, что RPC ещё не начинался. Старые
            # немаркированные in_progress неоднозначны и не должны автоматически
            # возвращаться в очередь после stop/crash.
            self.repo.requeue_safe_pre_rpc_claims(campaign_id)
            stats = self.repo.campaign_stats(campaign_id)
            left = stats.get("pending", 0) + stats.get("verifying", 0)
            status = "done" if left == 0 else "paused"
            self.repo.set_campaign_status(status, campaign_id)
            self.repo.log("Кампания остановлена. Приглашено %d, приватность %d, осталось %d"
                   % (stats.get("invited", 0), stats.get("privacy", 0), left),
                   scope="invite", campaign_id=campaign_id)
            self.runtime.runners.pop(campaign_id, None)

    def start(self, campaign_id: int) -> None:
        if campaign_id in self.runtime.runners and not self.runtime.runners[campaign_id].done():
            return
        self.runtime.runners[campaign_id] = asyncio.create_task(self.run_campaign(campaign_id))

    def stop(self, campaign_id: int) -> None:
        state = self.runtime.state.get(campaign_id)
        if state and state.get("stop"):
            state["stop"].set()
        self.repo.set_campaign_status('paused', campaign_id)
