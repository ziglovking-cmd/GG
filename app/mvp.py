"""MVP policy helpers: campaign gates, invite modes, warmup, ranking.

Patterns inspired by MIT-licensed open-source Telethon inviters
(Telegradd, tg-invite-machine), reimplemented for this codebase.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app import accounts, db
from app.config import (
    DEFAULT_INVITE_MODE,
    REQUIRE_PREFLIGHT_READY,
    REQUIRE_WARMUP_BEFORE_FORCE,
    SPEED_PROFILES,
)
from app.domain.invitations import phone_country, settings_of


class MvpGateError(Exception):
    pass


def speed_bounds(profile: str, account: Dict[str, Any]) -> Tuple[int, int]:
    if profile in SPEED_PROFILES:
        return SPEED_PROFILES[profile]
    return (
        int(account.get("min_delay") or SPEED_PROFILES["normal"][0]),
        int(account.get("max_delay") or SPEED_PROFILES["normal"][1]),
    )


def rank_inviter_accounts(account_ids: List[int]) -> List[int]:
    """Premium + больше своих hash + меньше недавних попыток → раньше в карусели."""
    scored: List[Tuple[int, int, int, int, int]] = []
    for account_id in account_ids:
        row = db.q1(
            """
            SELECT a.id, COALESCE(a.is_premium, 0) is_premium,
                   COALESCE(a.next_attempt_at, 0) next_attempt_at,
                   COALESCE(a.last_attempt_at, 0) last_attempt_at,
                   (SELECT COUNT(*) FROM hashes h WHERE h.account_id=a.id) hash_count
            FROM accounts a WHERE a.id=?
            """,
            (int(account_id),),
        )
        if not row:
            continue
        scored.append(
            (
                -int(row["is_premium"] or 0),
                -int(row["hash_count"] or 0),
                int(row["last_attempt_at"] or 0),
                int(row["next_attempt_at"] or 0),
                int(row["id"]),
            )
        )
    scored.sort()
    return [item[4] for item in scored]


def geo_mismatch_warning(account: Dict[str, Any]) -> Optional[str]:
    phone_code = phone_country(str(account.get("phone") or ""))
    proxy_code = str(account.get("proxy_country") or "").strip().upper() or None
    if phone_code and proxy_code and phone_code != proxy_code:
        return (
            "Гео номера (%s) ≠ гео прокси (%s). Для легитимного пула лучше совпадение."
            % (phone_code, proxy_code)
        )
    return None


def assert_campaign_start_allowed(campaign: Dict[str, Any]) -> Dict[str, Any]:
    """Жёсткие легитимные ворота перед force/hybrid стартом."""
    settings = settings_of(campaign)
    mode = str(settings.get("invite_mode") or DEFAULT_INVITE_MODE)
    if mode not in ("force", "link", "hybrid"):
        mode = DEFAULT_INVITE_MODE
    account_ids = [int(value) for value in settings.get("account_ids") or []]
    if not account_ids:
        raise MvpGateError("В кампании нет аккаунтов-инвайтеров")

    require_warmup = bool(
        settings.get("require_warmup", REQUIRE_WARMUP_BEFORE_FORCE)
    )
    warnings: List[str] = []

    if REQUIRE_PREFLIGHT_READY and mode in ("force", "hybrid"):
        status = str(campaign.get("preflight_status") or "not_run")
        if status not in ("ready", "warning"):
            raise MvpGateError(
                "Сначала пройдите «Проверить перед запуском» (статус: %s)"
                % status
            )

    problems: List[str] = []
    for account_id in account_ids:
        account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
        if not account:
            problems.append("аккаунт %d не найден" % account_id)
            continue
        if mode in ("force", "hybrid", "link"):
            try:
                accounts.assert_unique_invite_proxy(
                    account.get("proxy"),
                    account_id=account_id,
                    can_invite=bool(account.get("can_invite")),
                )
            except accounts.AuthError as exc:
                problems.append("%s: %s" % (account.get("label") or account_id, exc))
        if mode in ("force", "hybrid") and require_warmup and not int(
            account.get("warmup_done") or 0
        ):
            problems.append(
                "%s: нет отметки прогрева (warmup) перед force/hybrid"
                % (account.get("label") or account_id)
            )
        geo = geo_mismatch_warning(account)
        if geo:
            warnings.append("%s: %s" % (account.get("label") or account_id, geo))
        eligible, code, detail = accounts.invite_eligibility(account)
        if mode in ("force", "hybrid") and not eligible and code in (
            "restricted",
            "unauthorized",
            "disabled",
        ):
            problems.append("%s: %s" % (account.get("label") or account_id, detail))

    if problems:
        raise MvpGateError("Старт заблокирован:\n- " + "\n- ".join(problems[:12]))

    return {
        "invite_mode": mode,
        "account_ids": rank_inviter_accounts(account_ids),
        "speed_profile": str(settings.get("speed_profile") or "cautious"),
        "warnings": warnings,
    }
