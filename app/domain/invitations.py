"""Invitation rules and failures. No database, Telegram SDK, or web imports."""
from __future__ import annotations

from dataclasses import dataclass
import json
import random
import re
from typing import Any, Dict, Optional

CAMPAIGN_ACCOUNT_CONNECT_TIMEOUT = 35
CAMPAIGN_ACCOUNT_REQUEST_TIMEOUT = 20
CONNECTION_RETRY_ATTEMPTS = 6
# После положительного RPC-ответа проверяем конкретного пользователя через
# Telegram getParticipant (Telethon ``get_permissions``). Интервалы дают
# серверу до 26 секунд на распространение нового членства. Telegram не
# публикует SLA консистентности, поэтому отсутствие остаётся честным неуспехом.
MEMBERSHIP_VERIFY_DELAYS = (0, 1, 3, 7, 15)
MEMBERSHIP_RETRY_PAUSE = 15 * 60
# Durable protocol marker written before the one and only non-idempotent Invite
# RPC. A target carrying this prefix may only be resolved by exact membership
# verification; it must never return to the invitation queue.
INVITE_RPC_DURABLE_MARKER = "invite_rpc_at_most_once:v1"
# Право приглашать может временно читаться некорректно из-за устаревшей сущности
# чата или краткого сбоя Telegram. Не снимаем аккаунт навсегда: заново получаем
# чат и перепроверяем право с безопасным интервалом.
ACCESS_RECHECK_PAUSE = 15 * 60
# Аккаунты одной кампании стартуют волнами, чтобы десятки приглашений не
# уходили в одну секунду. Параллельные кампании сдвигаются на половину шага.
START_STAGGER_BATCH_SIZE = 10
START_STAGGER_BATCH_INTERVAL = 10 * 60
START_STAGGER_CAMPAIGN_INTERVAL = 5 * 60
START_STAGGER_JITTER = 60
# Пауза между любыми двумя приглашениями одной кампании, независимо от того,
# какой аккаунт их отправляет. Переопределяется в настройках кампании
# ключами invite_gap_min / invite_gap_max (секунды).
CAMPAIGN_INVITE_GAP_MIN = 15 * 60
CAMPAIGN_INVITE_GAP_MAX = 25 * 60
# Легитимная гигиена пула: один endpoint прокси не должен кормить десятки инвайтеров.
SHARED_PROXY_SOFT_LIMIT = 1
# Тримодальный джиттер паузы (идея из MIT tg-invite-machine): чаще середина диапазона.
JITTER_FAST_SHARE = 0.25
JITTER_MID_SHARE = 0.60


def humanized_delay_seconds(min_delay: int, max_delay: int) -> int:
    """Случайная пауза с уклоном в «человеческий» средний темп."""
    low = max(0, int(min_delay))
    high = max(low, int(max_delay))
    if high <= 0:
        return 0
    # Точный интервал (min==max) не размазываем — как custom-профиль в MIT inviters.
    if low == high:
        return low
    roll = random.random()
    if roll < JITTER_FAST_SHARE:
        return int(random.uniform(low * 0.85, low))
    if roll < JITTER_FAST_SHARE + JITTER_MID_SHARE:
        return int(random.uniform(low, high))
    return int(random.uniform(high, high * 1.15))


# Профили скорости (паттерн MIT tg-invite-machine; без обхода лимитов).
SPEED_PROFILES = {
    "cautious": (20 * 60, 35 * 60),
    "normal": (15 * 60, 25 * 60),
    "warmed": (8 * 60, 15 * 60),
}
DEFAULT_SPEED_PROFILE = "cautious"
DEFAULT_INVITE_MODE = "hybrid"  # force | link | hybrid


def speed_profile_bounds(profile: str) -> tuple[int, int]:
    if profile in SPEED_PROFILES:
        return SPEED_PROFILES[profile]
    return SPEED_PROFILES[DEFAULT_SPEED_PROFILE]


PHONE_COUNTRY_PREFIXES = (
    ("+7", "RU"),
    ("+380", "UA"),
    ("+375", "BY"),
    ("+998", "UZ"),
    ("+996", "KG"),
    ("+992", "TJ"),
    ("+993", "TM"),
    ("+994", "AZ"),
    ("+995", "GE"),
    ("+374", "AM"),
    ("+90", "TR"),
    ("+1", "US"),
    ("+44", "GB"),
    ("+49", "DE"),
    ("+33", "FR"),
    ("+48", "PL"),
    ("+420", "CZ"),
)


def phone_country(phone: str) -> Optional[str]:
    text = str(phone or "").strip().replace(" ", "")
    if not text.startswith("+"):
        text = "+" + text.lstrip("+")
    for prefix, code in sorted(PHONE_COUNTRY_PREFIXES, key=lambda item: -len(item[0])):
        if text.startswith(prefix):
            return code
    return None

TERMINAL_STATUSES = (
    "invited",
    "privacy",
    "already",
    "deleted",
    "failed",
    "skipped",
    "no_hash",
    "need_link",
)


PROTECTIVE_RECOVERY_MARKERS = (
    "PEER_FLOOD",
    "FloodWait",
    "спамблок",
    "ограничен в приглашениях",
    "Telegram счёл действия спамом",
)

TECHNICAL_RECOVERY_MARKERS = (
    "сбой подключения",
    "тайм-аут подключения",
    "проверьте прокси",
    "Прокси не смог установить соединение",
)


class WorkerRecoveryError(Exception):
    """Аккаунт нельзя безопасно вернуть в текущий запуск кампании."""


class TransientConnectionExhausted(Exception):
    """Все быстрые повторы временного сетевого подключения исчерпаны."""

    def __init__(self, cause: BaseException, attempts: int) -> None:
        self.cause = cause
        self.attempts = attempts
        super().__init__(friendly_error(cause))


class InviteNotAcceptedError(Exception):
    """Telegram явно вернул пользователя в ``missing_invitees``."""


class MembershipUnknownError(Exception):
    """Точечную проверку членства нельзя считать ни успехом, ни отсутствием."""


class RPCError(Exception):
    """A definitive remote rejection, distinct from a transport failure."""

    def __init__(self, message: str = '', *, seconds: int = 0) -> None:
        self.seconds = seconds
        super().__init__(message)


class ChannelPrivateError(RPCError):
    pass


class ChatAdminRequiredError(RPCError):
    pass


class ChatWriteForbiddenError(RPCError):
    pass


class FloodWaitError(RPCError):
    pass


class InputUserDeactivatedError(RPCError):
    pass


class PeerFloodError(RPCError):
    pass


class PeerIdInvalidError(RPCError):
    pass


class UserAlreadyParticipantError(RPCError):
    pass


class UserBannedInChannelError(RPCError):
    pass


class UserChannelsTooMuchError(RPCError):
    pass


class UserNotMutualContactError(RPCError):
    pass


class UserPrivacyRestrictedError(RPCError):
    pass


class UsersTooMuchError(RPCError):
    pass


def friendly_error(error: BaseException) -> str:
    """Не показывает пользователю внутреннюю ошибку несовместимости библиотек."""
    text = str(error).strip() or error.__class__.__name__
    if "ConnectionError() takes no keyword arguments" in text:
        return "Прокси не смог установить соединение с Telegram"
    text = re.sub(r"((?:socks5|socks4|https?|mtproxy|mtproto)://)[^@\s]+@", r"\1***@", text)
    return text[:300]


def invite_verification_note(detail: str) -> str:
    """Preserves the at-most-once marker while updating verification detail."""
    suffix = str(detail or "ожидается точечная проверка членства").strip()
    return ("%s; %s" % (INVITE_RPC_DURABLE_MARKER, suffix))[:300]


def startup_stagger_delay(
    position: int,
    campaign_rank: int,
    active_campaigns: int,
    jitter: Optional[int] = None,
) -> int:
    """Возвращает задержку первого запуска аккаунта в секундах."""
    group = max(0, int(position)) // START_STAGGER_BATCH_SIZE
    # Для двух кампаний остаётся шаг 10 минут. Если кампаний станет больше,
    # расширяем волну, чтобы их стартовые слоты не накладывались друг на друга.
    group_interval = max(
        START_STAGGER_BATCH_INTERVAL,
        max(1, int(active_campaigns)) * START_STAGGER_CAMPAIGN_INTERVAL,
    )
    random_shift = (
        random.randint(0, START_STAGGER_JITTER)
        if jitter is None
        else min(START_STAGGER_JITTER, max(0, int(jitter)))
    )
    return (
        max(0, int(campaign_rank)) * START_STAGGER_CAMPAIGN_INTERVAL
        + group * group_interval
        + random_shift
    )


def protective_recovery_reason(
    account: Dict[str, Any],
    worker: Dict[str, Any],
    now_ts: int,
) -> Optional[str]:
    if bool(account.get("invite_restricted")):
        return (
            str(account.get("invite_restriction_reason") or "Ограничение Telegram")
            + "; восстановите аккаунт вручную после окончания защитной паузы"
        )
    combined = "%s %s" % (
        str(worker.get("state") or ""),
        str(account.get("last_error") or ""),
    )
    cooldown_left = max(0, int(account.get("cooldown_until") or 0) - now_ts)
    if cooldown_left and any(marker in combined for marker in PROTECTIVE_RECOVERY_MARKERS):
        minutes = max(1, (cooldown_left + 59) // 60)
        return "Защитное ограничение Telegram ещё действует: %d мин" % minutes
    if account.get("status") == "banned":
        return "Telegram-сессия заблокирована; восстановление через кампанию невозможно"
    return None


def settings_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def settings_of(campaign: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(campaign.get("settings") or "{}")
    except (ValueError, TypeError):
        return {}


def keeps_invite_interval(rpc_started: bool, outcome: Optional[str]) -> bool:
    """An armed request with no outcome may already have reached Telegram."""
    return rpc_started and outcome in {None, "invited", "unconfirmed", "pending_confirmation"}


@dataclass(frozen=True)
class TargetSelection:
    skip_bots: bool = True
    skip_deleted: bool = True
    only_username: bool = False
    only_active: bool = False
    min_messages: int = 1
    only_premium: bool = False
    skip_dormant: bool = False
    active_first: bool = True
    limit: int = 100000

    @classmethod
    def from_filters(cls, filters: Dict[str, Any]) -> TargetSelection:
        return cls(
            skip_bots=bool(filters.get("skip_bots", True)),
            skip_deleted=bool(filters.get("skip_deleted", True)),
            only_username=bool(filters.get("only_username")),
            only_active=bool(filters.get("only_active")),
            min_messages=int(filters.get("min_messages", 1)) if filters.get("only_active") else 1,
            only_premium=bool(filters.get("only_premium")),
            skip_dormant=bool(filters.get("skip_dormant")),
            active_first=bool(filters.get("active_first", True)),
            limit=int(filters.get("limit") or 100000),
        )
