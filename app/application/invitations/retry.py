from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from app.domain import invitations as policy
from app.domain.invitations import TransientConnectionExhausted, friendly_error

from .ports import AccountPort, InvitationRepository, TelegramGateway


@dataclass
class ConnectionRetry:
    repo: InvitationRepository
    accounts: AccountPort
    gateway: TelegramGateway

    async def run(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        account_id: int,
        info: Dict[str, Any],
        action: str,
        stop: Optional[asyncio.Event] = None,
    ) -> Any:
        """Повторяет только сетевые ошибки, не обходя ответы и лимиты Telegram."""
        last_error: Optional[BaseException] = None
        attempts = max(1, int(policy.CONNECTION_RETRY_ATTEMPTS))
        for attempt in range(1, attempts + 1):
            if stop is not None and stop.is_set():
                raise asyncio.CancelledError()
            try:
                result = await operation()
                if attempt > 1:
                    self.repo.log(
                        "%s: соединение восстановлено с попытки %d/%d"
                        % (action, attempt, attempts),
                        scope="invite",
                        account_id=account_id,
                    )
                return result
            except Exception as error:
                if not self.gateway.is_transient_connection_error(error):
                    raise
                last_error = error
                try:
                    await asyncio.wait_for(self.accounts.drop_client(account_id), timeout=5)
                except Exception:
                    pass
                if attempt >= attempts:
                    break
                info["state"] = (
                    "%s: повтор подключения %d/%d без задержки"
                    % (action, attempt + 1, attempts)
                )
                self.repo.log(
                    "%s: временный сетевой сбой, повтор %d/%d без задержки: %s"
                    % (action, attempt + 1, attempts, friendly_error(error)),
                    level="warn",
                    scope="invite",
                    account_id=account_id,
                )
                # Даём другим задачам обработать остановку, не назначая таймер.
                await asyncio.sleep(0)
        assert last_error is not None
        raise TransientConnectionExhausted(last_error, attempts) from last_error
