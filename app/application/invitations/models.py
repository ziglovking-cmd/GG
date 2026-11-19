"""State local to a single invitation attempt."""
from asyncio import Event
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.domain.invitations import keeps_invite_interval


@dataclass
class Attempt:
    campaign_id: int
    account_id: int
    target: Dict[str, Any]
    info: Dict[str, Any]
    stop: Event
    invite_marker_durable: bool = False
    invite_rpc_started: bool = False
    halt_worker: bool = False
    outcome: Optional[str] = None
    next_attempt_at: int = 0
    notification_error: str = ""
    campaign_slot_at: int = 0

    @property
    def keeps_interval(self) -> bool:
        return keeps_invite_interval(self.invite_rpc_started, self.outcome)
