"""Ephemeral task ownership and synchronization for one application instance."""
import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CampaignRuntime:
    runners: dict[int, asyncio.Task] = field(default_factory=dict)
    state: dict[int, dict[str, Any]] = field(default_factory=dict)
    account_locks: dict[int, asyncio.Lock] = field(default_factory=dict)
    campaign_locks: dict[int, asyncio.Lock] = field(default_factory=dict)
    recovery_locks: dict[tuple[int, int], asyncio.Lock] = field(default_factory=dict)
