from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Dict

from app.domain import invitations as policy
from app.domain.invitations import (
    MembershipUnknownError,
    UserAlreadyParticipantError,
    invite_verification_note,
)

from .context import InviteContextResolver
from .failures import InvitationFailureHandler
from .models import Attempt
from .ports import AccountPort, AttemptNotifier, InvitationRepository, TelegramGateway
from .retry import ConnectionRetry
from .scheduling import InvitationScheduler
from .verification import MembershipVerification


@dataclass
class InvitationAttempt:
    repo: InvitationRepository
    accounts: AccountPort
    gateway: TelegramGateway
    context: InviteContextResolver
    retry: ConnectionRetry
    scheduler: InvitationScheduler
    verification: MembershipVerification
    notifier: AttemptNotifier
    failures: InvitationFailureHandler

    async def run(
        self,
        campaign_id: int,
        account_id: int,
        target: Dict[str, Any],
        info: Dict[str, Any],
        stop: asyncio.Event,
    ) -> Attempt:
        attempt = Attempt(campaign_id, account_id, target, info, stop)
        info["state"] = "подготовка приглашения %s: запрос ещё не отправлен" % (target["username"] or target["user_id"])
        try:
            await self.send(attempt)
        except asyncio.CancelledError:
            if not attempt.invite_marker_durable:
                self.repo.requeue_after_technical_failure(int(target["id"]))
            raise
        except Exception as error:
            await self.failures.handle(error, attempt)
        finally:
            notification_task = self.finish(attempt)
        if notification_task is not None:
            await notification_task
        return attempt

    async def send(self, attempt: Attempt) -> None:
        context = await self.retry.run(
            lambda: self.context.resolve(attempt.campaign_id, attempt.account_id, attempt.target),
            account_id=attempt.account_id,
            info=attempt.info,
            action="подключение к Telegram",
            stop=attempt.stop,
        )

        client, target_entity, peer = context
        # Early exit before reserving either queue.
        await self.ensure_absent(attempt, client, target_entity, peer)

        reserved_at = await self.scheduler.reserve_account_slot(attempt.account_id, attempt.stop, attempt.info)
        if reserved_at is None:
            self.repo.requeue_after_technical_failure(int(attempt.target["id"]))
            attempt.halt_worker = True
            return
        attempt.next_attempt_at = reserved_at
        account_delay = max(0, reserved_at - int(time.time()))

        # Общая очередь кампании: между приглашениями разных аккаунтов
        # выдерживается пауза invite_gap_min..invite_gap_max.
        attempt.campaign_slot_at = await self.scheduler.reserve_campaign_slot(attempt.campaign_id, attempt.stop, attempt.info) or 0
        if not attempt.campaign_slot_at:
            attempt.next_attempt_at = self.accounts.release_next_attempt(
                attempt.account_id, attempt.next_attempt_at
            )
            self.repo.requeue_after_technical_failure(int(attempt.target["id"]))
            attempt.halt_worker = True
            return
        # Ожидание очереди кампании не должно сокращать личный интервал
        # аккаунта: отсчитываем его заново от момента отправки.
        attempt.next_attempt_at = self.accounts.defer_next_attempt(attempt.account_id, account_delay)

        # Ожидание очереди может длиться часами: за это время соединение
        # успевает закрыться. Переподключаемся перед проверкой и отправкой.
        client, target_entity, peer = await self.retry.run(
            lambda: self.context.resolve(attempt.campaign_id, attempt.account_id, attempt.target),
            account_id=attempt.account_id,
            info=attempt.info,
            action="переподключение после очереди кампании",
            stop=attempt.stop,
        )

        # The queue may wait for hours; check again immediately before the RPC.
        await self.ensure_absent(attempt, client, target_entity, peer)
        if attempt.stop.is_set():
            attempt.next_attempt_at = self.accounts.release_next_attempt(
                attempt.account_id, attempt.next_attempt_at
            )
            self.repo.requeue_after_technical_failure(int(attempt.target["id"]))
            attempt.halt_worker = True
            return

        # Arm the target durably before the non-idempotent RPC. From this
        # commit onward, neither a transport error nor process cancellation
        # may return it to pending: only exact membership verification may
        # resolve the ambiguous request.
        if not self.repo.mark_invite_rpc_started(
            int(attempt.target["id"]),
            attempt.account_id,
            invite_verification_note(
                "precheck=not_member; invite_rpc=armed"
            ),
        ):
            raise RuntimeError(
                "Не удалось зафиксировать at-most-once marker перед Invite RPC"
            )
        attempt.invite_marker_durable = True
        attempt.invite_rpc_started = True
        attempt.info["state"] = "чтение чата перед приглашением %s" % (
            attempt.target["username"] or attempt.target["user_id"]
        )
        try:
            await asyncio.wait_for(
                self.gateway.simulate_pre_invite_reading(client, target_entity),
                timeout=policy.CAMPAIGN_ACCOUNT_REQUEST_TIMEOUT,
            )
        except Exception:
            # Pre-invite reading is hygiene, not a delivery signal.
            pass
        attempt.info["state"] = "отправляю запрос приглашения %s" % (
            attempt.target["username"] or attempt.target["user_id"]
        )
        await asyncio.wait_for(
            self.gateway.invite_one(client, target_entity, peer),
            timeout=policy.CAMPAIGN_ACCOUNT_REQUEST_TIMEOUT,
        )
        self.repo.save_verification_error(
            invite_verification_note('invite_rpc=returned'),
            int(attempt.target['id']),
        )
        self.repo.log(
            "Telegram принял запрос приглашения для %s; проверяю добавление в чат"
            % (attempt.target["username"] or attempt.target["user_id"]),
            scope="invite", campaign_id=attempt.campaign_id, account_id=attempt.account_id,
        )

        await self.verification.confirm(attempt, client, target_entity, peer)

    def finish(self, attempt: Attempt):
        notification_task = None
        # Сохраняем оба интервала после принятого или неоднозначного
        # запроса. Явный отказ Telegram освобождает и общую очередь,
        # и слот аккаунта до формирования уведомления.
        if not attempt.keeps_interval:
            if attempt.campaign_slot_at:
                self.scheduler.release_campaign_slot(attempt.campaign_id, attempt.campaign_slot_at)
            if attempt.next_attempt_at:
                attempt.next_attempt_at = self.accounts.release_next_attempt(
                    attempt.account_id, attempt.next_attempt_at
                )
        # Приватность сразу освобождает слот и не запускает шестичасовое ожидание,
        # поэтому отдельное уведомление для неё не создаём. Остальные реальные
        # запросы Telegram получают одно событие, независимо от результата.
        if (
            (attempt.invite_rpc_started and attempt.outcome != "privacy")
            or attempt.outcome == "connection_error"
        ):
            notification_task = self.notifier.queue(
                attempt.campaign_id,
                attempt.account_id,
                attempt.target,
                attempt.outcome or (
                    "pending_confirmation" if attempt.invite_marker_durable else "failed"
                ),
                attempt.next_attempt_at,
                attempt.notification_error,
            )


        return notification_task

    async def ensure_absent(
        self,
        attempt: Attempt,
        client: Any,
        target_entity: Any,
        peer: Any,
    ) -> None:
        membership, detail = await self.gateway.membership_state_once(client, target_entity, peer)
        if membership == "present":
            raise UserAlreadyParticipantError()
        if membership != "not_member":
            raise MembershipUnknownError(
                "Не удалось проверить членство перед приглашением: %s"
                % (detail or "неизвестный ответ Telegram")
            )
