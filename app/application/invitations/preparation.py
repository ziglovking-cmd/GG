from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Dict, Optional

from app.domain import invitations as policy
from app.domain.invitations import TransientConnectionExhausted, friendly_error

from .ports import AccountPort, AttemptNotifier, InvitationRepository, TelegramGateway
from .retry import ConnectionRetry
from .runtime import CampaignRuntime


@dataclass
class CampaignAccountPreparation:
    repo: InvitationRepository
    accounts: AccountPort
    gateway: TelegramGateway
    retry: ConnectionRetry
    runtime: CampaignRuntime
    notifier: AttemptNotifier

    async def prepare(
        self,
        campaign: Dict[str, Any],
        account_id: int,
        connect_timeout: float = policy.CAMPAIGN_ACCOUNT_CONNECT_TIMEOUT,
        request_timeout: float = policy.CAMPAIGN_ACCOUNT_REQUEST_TIMEOUT,
    ) -> Optional[Any]:
        """Подключает один аккаунт, не позволяя ему заблокировать запуск всего пула."""
        workers = self.runtime.state.setdefault(campaign["id"], {}).setdefault("workers", {})
        info = workers.setdefault(account_id, {})
        account = self.repo.get_account(account_id)
        if not account:
            info["state"] = "аккаунт удалён"
            return None
        eligible, eligibility_code, eligibility_detail = self.accounts.invite_eligibility(
            account,
            check_cooldown=False,
            check_quota=False,
        )
        if not eligible:
            info["state"] = (
                "отключён пользователем"
                if eligibility_code == "disabled"
                else eligibility_detail
            )
            if eligibility_code != "unauthorized":
                return None
            self.notifier.queue(
                campaign["id"], account_id, None, "unauthorized", 0,
                "Аккаунт не авторизован",
            )
            return None

        async def prepare_once() -> tuple[bool, Optional[Any]]:
            client = await asyncio.wait_for(
                self.accounts.get_client(account_id), timeout=connect_timeout
            )
            authorized = await asyncio.wait_for(
                self.gateway.is_authorized(client), timeout=request_timeout
            )
            if not authorized:
                return False, None
            entity = await asyncio.wait_for(
                self.gateway.resolve_target_chat(client, campaign["target_chat_id"]),
                timeout=request_timeout,
            )
            return True, entity

        try:
            authorized, entity = await self.retry.run(
                prepare_once,
                account_id=account_id,
                info=info,
                action="запуск аккаунта",
            )
            if not authorized:
                info["state"] = "аккаунт не авторизован"
                self.repo.log(
                    "Аккаунт не авторизован — пропущен",
                    level="warn",
                    scope="invite",
                    campaign_id=campaign["id"],
                    account_id=account_id,
                )
                self.notifier.queue(
                    campaign["id"], account_id, None, "unauthorized", 0,
                    "Аккаунт не авторизован",
                )
                return None
            assert entity is not None
            if not self.gateway.can_invite(entity):
                info["access_retry_at"] = int(time.time()) + policy.ACCESS_RECHECK_PAUSE
                info["state"] = "перепроверка доступа через %d мин" % max(
                    1, policy.ACCESS_RECHECK_PAUSE // 60
                )
                self.repo.log(
                    "Telegram не подтвердил право приглашать участников; аккаунт "
                    "останется в ротации и автоматически перепроверит доступ через %d мин"
                    % max(1, policy.ACCESS_RECHECK_PAUSE // 60),
                    level="warn",
                    scope="invite",
                    campaign_id=campaign["id"],
                    account_id=account_id,
                )
                self.notifier.queue(
                    campaign["id"], account_id, None, "no_rights", 0,
                    "Нет права приглашать участников в целевой чат",
                )
                return None
            info.pop("technical_retry_at", None)
            info.pop("access_retry_at", None)
            return entity
        except TransientConnectionExhausted as e:
            error_message = friendly_error(e.cause)
            info.pop("technical_retry_at", None)
            info["state"] = (
                "временный сбой подключения — %d попыток, повтор без задержки"
                % e.attempts
            )
            self.repo.log(
                "При запуске выполнено %d попыток подключения; аккаунт остаётся в "
                "кампании и повторит подключение автоматически: %s"
                % (e.attempts, error_message),
                level="warn",
                scope="invite",
                campaign_id=campaign["id"],
                account_id=account_id,
            )
            self.notifier.queue(
                campaign["id"], account_id, None, "connection_error", 0,
                error_message,
            )
            return None
        except Exception as e:
            error_message = friendly_error(e)
            info.pop("technical_retry_at", None)
            info["state"] = (
                "сбой подключения — проверьте прокси"
                if self.gateway.is_rpc_error(e)
                else "временный сбой подключения — повтор без задержки"
            )
            self.repo.log(
                "Аккаунт не может работать с целевым чатом: %s" % error_message,
                level="warn",
                scope="invite",
                campaign_id=campaign["id"],
                account_id=account_id,
            )
            self.notifier.queue(
                campaign["id"], account_id, None, "connection_error", 0,
                error_message,
            )
            return None
