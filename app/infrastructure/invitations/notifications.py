"""Best-effort asynchronous attempt notification adapter."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from app.application.invitations.ports import InvitationRepository


class CallbackAttemptNotifier:
    def __init__(self, repo: InvitationRepository) -> None:
        self.repo = repo
        self.callback = None

    def set(self, notifier: Optional[Callable[[Dict[str, Any]], Awaitable[None]]]) -> None:
        self.callback = notifier

    def queue(
        self,
        campaign_id: int,
        account_id: int,
        target: Optional[Dict[str, Any]],
        outcome: str,
        next_attempt_at: int,
        error: str = '',
    ) -> Optional[asyncio.Task[None]]:
        notifier = self.callback
        if notifier is None:
            return None
        payload = {
            "campaign_id": int(campaign_id),
            "account_id": int(account_id),
            "target_id": int(target["id"]) if target else 0,
            "user_id": int(target["user_id"]) if target else 0,
            "username": target.get("username") if target else None,
            "display": target.get("display") if target else None,
            "outcome": outcome,
            "error": error[:300] if error else "",
            "next_attempt_at": int(next_attempt_at or 0),
            "attempted_at": int(time.time()),
        }

        async def deliver() -> None:
            try:
                await notifier(payload)
            except Exception as e:
                self.repo.log(
                    "Не удалось отправить уведомление о попытке: %s" % str(e)[:200],
                    level="error",
                    scope="notifications",
                    campaign_id=campaign_id,
                    account_id=account_id,
                )

        return asyncio.create_task(deliver())
