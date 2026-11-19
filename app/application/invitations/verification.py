from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Dict

from app.domain import invitations as policy
from app.domain.invitations import friendly_error, invite_verification_note

from .context import InviteContextResolver
from .models import Attempt
from .ports import InvitationRepository, TelegramGateway


@dataclass
class MembershipVerification:
    repo: InvitationRepository
    gateway: TelegramGateway
    context: InviteContextResolver

    async def verify(self, client: Any, target_entity: Any, peer: Any) -> tuple[str, str, str]:
        """Ограниченно опрашивает членство ровно одного пользователя."""
        last_technical_error = ""
        saw_unknown = False
        checks = 0
        for delay in policy.MEMBERSHIP_VERIFY_DELAYS:
            if delay > 0:
                await asyncio.sleep(delay)
            checks += 1
            membership, detail = await self.gateway.membership_state_once(
                client, target_entity, peer
            )
            if membership == "present":
                return "present", "", "confirmed"
            if membership == "unknown":
                saw_unknown = True
                last_technical_error = detail

        if saw_unknown:
            return (
                "unknown",
                "Не удалось достоверно подтвердить присутствие пользователя: %s"
                % (last_technical_error or "точечная проверка недоступна"),
                "verification_error",
            )
        else:
            return (
                "not_member",
                "Telegram не подтвердил присутствие пользователя после %d проверок"
                % checks,
                "not_present",
            )

    async def retry_pending(self, campaign_id: int, account_id: int, info: Dict[str, Any]) -> bool:
        """Повторяет точечную проверку UNKNOWN без повторного инвайта.

        Берём только записи с маркерами нового core-flow: для них непосредственно
        перед Invite RPC уже было доказано отсутствие пользователя. Старые
        ``verifying`` без такого pre-check нельзя безопасно засчитать.
        """
        now_ts = int(time.time())
        if int(info.get("verification_retry_at") or 0) > now_ts:
            return False
        row = self.repo.pending_verification(
            campaign_id,
            account_id,
            policy.INVITE_RPC_DURABLE_MARKER + '%',
        )
        if not row:
            info.pop("verification_retry_at", None)
            return False

        target = dict(row)
        info["state"] = "повторно проверяю фактическое присутствие пользователя"
        try:
            client, target_entity, peer = await self.context.resolve(
                campaign_id, account_id, target
            )
            membership, detail, result = await self.verify(
                client, target_entity, peer
            )
        except Exception as error:
            membership = "unknown"
            detail = "Не удалось достоверно подтвердить присутствие пользователя: %s" % (
                friendly_error(error)
            )
            result = "verification_error"

        if membership == "present":
            self.repo.finalize_invite_confirmation(int(target["id"]), True)
            info.pop("verification_retry_at", None)
            info["state"] = "присутствие подтверждено повторной проверкой"
        elif membership == "not_member":
            self.repo.finalize_invite_confirmation(
                int(target["id"]),
                False,
                error=detail,
                result=result,
            )
            info.pop("verification_retry_at", None)
            info["state"] = "Telegram не добавил пользователя"
        else:
            self.repo.save_verification_error(invite_verification_note(detail), int(target['id']))
            info["verification_retry_at"] = now_ts + policy.MEMBERSHIP_RETRY_PAUSE
            info["state"] = "подтверждение недоступно, повтор через %d мин" % max(
                1, policy.MEMBERSHIP_RETRY_PAUSE // 60
            )
        return True

    async def confirm(self, attempt: Attempt, client: Any, target_entity: Any, peer: Any) -> None:
        # Положительный RPC-ответ означает только принятие запроса. Точно
        # проверяем того же пользователя тем же аккаунтом.
        attempt.info["state"] = "проверяю фактическое присутствие пользователя"
        membership_after, confirmation_error, confirmation_result = (
            await self.verify(client, target_entity, peer)
        )
        if membership_after == "present":
            final_status = self.repo.finalize_invite_confirmation(
                int(attempt.target["id"]),
                True,
            )
            if final_status == "invited":
                attempt.outcome = "invited"
                attempt.info["state"] = "присутствие подтверждено"
            else:
                attempt.outcome = "pending_confirmation"
                attempt.notification_error = (
                    "Подтверждение получено, но цель уже имеет статус %s"
                    % final_status
                )
        elif membership_after == "not_member":
            attempt.notification_error = confirmation_error
            self.repo.finalize_invite_confirmation(
                int(attempt.target["id"]),
                False,
                error=confirmation_error,
                result=confirmation_result,
            )
            attempt.outcome = "unconfirmed"
            attempt.info["state"] = "Telegram не добавил пользователя"
        else:
            # UNKNOWN нельзя превращать ни в invited, ни в достоверное
            # отсутствие. Оставляем durable verifying для последующей
            # точечной проверки; счётчики остаются неизменными.
            attempt.notification_error = confirmation_error
            self.repo.save_verification_error(
                invite_verification_note('invite_rpc=returned; %s' % confirmation_error),
                int(attempt.target['id']),
            )
            attempt.info["verification_retry_at"] = (
                int(time.time()) + policy.MEMBERSHIP_RETRY_PAUSE
            )
            attempt.outcome = "pending_confirmation"
            attempt.info["state"] = "подтверждение технически недоступно, ожидается повтор"
