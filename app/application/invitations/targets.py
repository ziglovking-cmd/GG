
from dataclasses import dataclass
from typing import Any

from app.domain.invitations import TargetSelection

from .ports import InvitationRepository


@dataclass
class CampaignTargetBuilder:
    repo: InvitationRepository

    def build_targets(
        self,
        campaign_id: int,
        source_chat_ids: list[int],
        filters: dict[str, Any],
    ) -> int:
        if not source_chat_ids:
            return 0
        return self.repo.populate_targets(
            campaign_id, source_chat_ids, TargetSelection.from_filters(filters)
        )
