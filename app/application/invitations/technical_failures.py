"""Recover transport failures without resending a possibly accepted invitation."""
from dataclasses import dataclass
import time

from app.domain.invitations import (
    TransientConnectionExhausted,
    friendly_error,
    invite_verification_note,
)

from .models import Attempt
from .ports import AccountPort, InvitationRepository


@dataclass
class TechnicalFailureHandler:
    repo: InvitationRepository
    accounts: AccountPort

    async def handle(self, error: Exception, attempt: Attempt) -> None:
        exhausted = isinstance(error, TransientConnectionExhausted)
        cause = error.cause if exhausted else error
        attempt.notification_error = friendly_error(cause)
        if attempt.invite_marker_durable:
            self.keep_for_verification(attempt)
            message = (
                "Неоднозначный результат Invite RPC; повторная отправка "
                "запрещена, выполняется проверка членства: %s"
                % attempt.notification_error
            )
        else:
            attempt.outcome = "connection_error"
            self.repo.requeue_after_technical_failure(attempt.target["id"])
            attempt.info["state"] = (
                "временный сбой подключения — %d попыток, повтор без задержки"
                % error.attempts
                if exhausted
                else "временный технический сбой — повтор без задержки"
            )
            message = (
                "Временный технический сбой; воркер остаётся в кампании: %s"
                % attempt.notification_error
            )
        if exhausted:
            message = (
                "После %d попыток соединение не восстановлено; воркер остаётся "
                "в кампании и повторит подключение без задержки: %s"
                % (error.attempts, attempt.notification_error)
            )
        self.repo.log(
            message, level="warn", scope="invite",
            campaign_id=attempt.campaign_id, account_id=attempt.account_id,
        )
        await self.accounts.drop_client(attempt.account_id)

    def keep_for_verification(self, attempt: Attempt) -> None:
        attempt.outcome = "pending_confirmation"
        self.repo.save_verification_error(
            invite_verification_note("invite_rpc=ambiguous; %s" % attempt.notification_error),
            int(attempt.target["id"]),
        )
        attempt.info["verification_retry_at"] = int(time.time())
        attempt.info["state"] = "результат запроса неоднозначен, проверяю членство"
