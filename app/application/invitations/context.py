from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict

from app.domain import invitations as policy

from .ports import AccountPort, InvitationRepository, TelegramGateway
from .runtime import CampaignRuntime


@dataclass
class InviteContextResolver:
    repo: InvitationRepository
    accounts: AccountPort
    gateway: TelegramGateway
    runtime: CampaignRuntime

    async def resolve(
        self,
        campaign_id: int,
        account_id: int,
        target: Dict[str, Any],
    ) -> tuple[Any, Any, Any]:
        """Один сетевой проход: клиент, целевой чат и пользователь."""
        state = self.runtime.state[campaign_id]
        client = await asyncio.wait_for(
            self.accounts.get_client(account_id), timeout=policy.CAMPAIGN_ACCOUNT_CONNECT_TIMEOUT
        )
        target_entity = state.setdefault("target_entity_by_account", {}).get(account_id)
        if target_entity is None:
            target_chat_id = int(state.get("target_chat_id") or 0)
            if not target_chat_id:
                row = self.repo.get_campaign(campaign_id)
                target_chat_id = int(row["target_chat_id"] if row else 0)
            target_entity = await asyncio.wait_for(
                self.gateway.resolve_target_chat(client, target_chat_id),
                timeout=policy.CAMPAIGN_ACCOUNT_REQUEST_TIMEOUT,
            )
            state["target_entity_by_account"][account_id] = target_entity
        peer = await asyncio.wait_for(
            self.gateway.resolve_peer(
                client,
                account_id,
                int(target.get("resolved_user_id") or target["user_id"]),
                target["username"],
            ),
            timeout=policy.CAMPAIGN_ACCOUNT_REQUEST_TIMEOUT,
        )
        resolved_id = self.gateway.user_id(peer)
        if resolved_id is not None:
            if resolved_id != int(target.get("resolved_user_id") or 0):
                self.repo.save_resolved_id(resolved_id, int(target['id']))
                target["resolved_user_id"] = resolved_id
        return client, target_entity, peer
