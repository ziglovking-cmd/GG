from __future__ import annotations

from dataclasses import dataclass
import time

from app.domain import invitations as policy
from app.domain.invitations import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    InputUserDeactivatedError,
    InviteNotAcceptedError,
    PeerFloodError,
    PeerIdInvalidError,
    UserAlreadyParticipantError,
    UserBannedInChannelError,
    UserChannelsTooMuchError,
    UserNotMutualContactError,
    UserPrivacyRestrictedError,
    UsersTooMuchError,
)

from .models import Attempt
from .ports import AccountPort, InvitationRepository
from .runtime import CampaignRuntime
from .technical_failures import TechnicalFailureHandler


@dataclass
class InvitationFailureHandler:
    repo: InvitationRepository
    accounts: AccountPort
    runtime: CampaignRuntime
    technical: TechnicalFailureHandler

    async def handle(self, error: Exception, attempt: Attempt) -> None:
        if isinstance(error, (UserPrivacyRestrictedError, UserNotMutualContactError)):
            attempt.outcome = "privacy"
            attempt.notification_error = "настройки приватности"
            self.repo.mark(
                attempt.target['id'],
                'privacy',
                attempt.account_id,
                attempt.notification_error,
            )
            if attempt.invite_rpc_started:
                attempt.info["privacy"] = int(attempt.info.get("privacy", 0)) + 1
        elif isinstance(error, InviteNotAcceptedError):
            attempt.outcome = "rejected"
            attempt.notification_error = str(error)
            attempt.info["state"] = "Telegram отклонил приглашение, пользователь не добавлен"
            self.repo.finalize_invite_confirmation(
                int(attempt.target["id"]),
                False,
                error=attempt.notification_error,
                result="not_present",
            )
        elif isinstance(error, UserAlreadyParticipantError):
            attempt.outcome = "already"
            self.repo.mark(attempt.target["id"], "already", attempt.account_id, "уже в чате")
        elif isinstance(error, InputUserDeactivatedError):
            attempt.outcome = "deleted"
            self.repo.mark(attempt.target["id"], "deleted", attempt.account_id, "аккаунт удалён")
        elif isinstance(error, UserChannelsTooMuchError):
            attempt.outcome = "failed"
            self.repo.mark(
                attempt.target['id'],
                'failed',
                attempt.account_id,
                'у юзера слишком много чатов',
            )
        elif isinstance(error, PeerIdInvalidError):
            attempt.outcome = "no_hash"
            self.repo.mark(
                attempt.target['id'],
                'no_hash',
                attempt.account_id,
                'нет access_hash для этого аккаунта',
            )
        elif isinstance(error, ValueError):
            attempt.outcome = "failed"
            self.repo.mark(attempt.target["id"], "failed", attempt.account_id, str(error)[:200])

        elif isinstance(error, PeerFloodError):
            attempt.outcome = "peer_flood"
            attempt.notification_error = "PEER_FLOOD — Telegram счёл действия спамом"
            self.repo.mark(
                attempt.target['id'],
                'failed',
                attempt.account_id,
                attempt.notification_error,
            )
            self.accounts.set_cooldown(attempt.account_id, 24 * 3600, attempt.notification_error)
            self.accounts.restrict_invites(
                attempt.account_id,
                attempt.notification_error,
            )
            attempt.halt_worker = True
            attempt.info["state"] = "PEER_FLOOD, требуется ручное восстановление"
            self.repo.log("Аккаунт получил PEER_FLOOD и выведен из ротации до ручного восстановления",
                   level="error", scope="invite", campaign_id=attempt.campaign_id, account_id=attempt.account_id)
        elif isinstance(error, FloodWaitError):
            attempt.outcome = "flood_wait"
            attempt.notification_error = "FloodWait %ds" % error.seconds
            self.repo.mark(
                attempt.target['id'],
                'failed',
                attempt.account_id,
                attempt.notification_error,
            )
            self.accounts.set_cooldown(attempt.account_id, error.seconds + 5, attempt.notification_error)
            attempt.info["state"] = "FloodWait %d мин" % max(1, error.seconds // 60)
        elif isinstance(error, UserBannedInChannelError):
            attempt.outcome = "banned"
            attempt.notification_error = "аккаунт ограничен в приглашениях"
            self.repo.mark(
                attempt.target['id'],
                'failed',
                attempt.account_id,
                attempt.notification_error,
            )
            self.accounts.set_cooldown(attempt.account_id, 48 * 3600, attempt.notification_error)
            attempt.halt_worker = True
            attempt.info["state"] = "спамблок Telegram, пауза 48 часов"
            self.repo.log("Аккаунт ограничен Telegram в приглашениях (спамблок), пауза 48 часов",
                   level="error", scope="invite", campaign_id=attempt.campaign_id, account_id=attempt.account_id)
        elif isinstance(error, (ChatAdminRequiredError, ChatWriteForbiddenError, ChannelPrivateError)):
            attempt.outcome = "no_rights"
            attempt.notification_error = "Telegram не подтвердил право приглашать"
            self.repo.mark(
                attempt.target['id'],
                'failed',
                attempt.account_id,
                attempt.notification_error,
            )
            self.runtime.state[attempt.campaign_id].setdefault('target_entity_by_account', {}).pop(
                attempt.account_id,
                None,
            )
            attempt.info["access_retry_at"] = int(time.time()) + policy.ACCESS_RECHECK_PAUSE
            attempt.info["state"] = "перепроверка доступа через %d мин" % max(
                1, policy.ACCESS_RECHECK_PAUSE // 60
            )
            self.repo.log(
                "Telegram временно не подтвердил право приглашать; аккаунт остаётся "
                "в кампании, доступ будет перепроверен автоматически через %d мин"
                % max(1, policy.ACCESS_RECHECK_PAUSE // 60),
                level="warn", scope="invite", campaign_id=attempt.campaign_id,
                account_id=attempt.account_id,
            )
        elif isinstance(error, UsersTooMuchError):
            attempt.outcome = "chat_full"
            attempt.notification_error = "целевой чат заполнен"
            self.repo.mark(
                attempt.target['id'],
                'failed',
                attempt.account_id,
                attempt.notification_error,
            )
            attempt.halt_worker = True
            attempt.info["state"] = "целевой чат заполнен"
            self.repo.log("Целевой чат заполнен — кампания остановлена",
                   level="error", scope="invite", campaign_id=attempt.campaign_id)
            attempt.stop.set()
        else:
            await self.technical.handle(error, attempt)
