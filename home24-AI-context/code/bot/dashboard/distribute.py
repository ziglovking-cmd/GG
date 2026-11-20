"""Распределение клиентов и дневной очереди по веб-менеджерам (shares)."""

from __future__ import annotations

import logging
from typing import Any

from bot.dashboard import auth as dash_auth
from bot.managers import get_registry
from bot.store import Store, _moscow_today

logger = logging.getLogger("home24.distribute")


def active_manager_ids() -> list[str]:
    """Только активные веб-менеджеры: enabled в панели и в managers.json."""
    reg = get_registry()
    users = {
        u["manager_id"]: u
        for u in dash_auth.list_users_public()
        if u["role"] == "manager" and u.get("enabled") and u.get("manager_id")
    }
    out: list[str] = []
    if users:
        for mid, u in users.items():
            m = reg.get(mid)
            if m is not None and not m.enabled:
                continue
            out.append(mid)
    else:
        # нет пользователей панели — все enabled из registry
        out = [m.id for m in reg.enabled_list()]
    return sorted(set(out))


def share_weights(manager_ids: list[str] | None = None) -> dict[str, int]:
    """Веса только по активным; отключённые не участвуют → доля уходит остальным."""
    reg = get_registry()
    mids = manager_ids if manager_ids is not None else active_manager_ids()
    weights: dict[str, int] = {}
    for mid in mids:
        m = reg.get(mid)
        w = int(getattr(m, "share_weight", 1) or 1) if m else 1
        weights[mid] = max(1, w)
    return weights


def split_quota(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Разделить total по весам; остаток — round-robin по sorted ids.

    Пример старого капа (команда из 5): 172 → 34+34+34+35+35.
    Безопасный кап main: 30/день, 210/неделя.
    """
    if total <= 0 or not weights:
        return {k: 0 for k in weights}
    wsum = sum(weights.values()) or 1
    base = {k: (total * w) // wsum for k, w in weights.items()}
    assigned = sum(base.values())
    rem = total - assigned
    order = sorted(weights.keys())
    i = 0
    while rem > 0 and order:
        base[order[i % len(order)]] += 1
        rem -= 1
        i += 1
    return base


def daily_shares_for_account(daily_limit: int) -> dict[str, int]:
    """Доля первых сообщений на менеджера сегодня (от капа аккаунта)."""
    weights = share_weights()
    return split_quota(int(daily_limit), weights)


def manager_remaining_share(
    store: Store,
    manager_id: str,
    *,
    daily_limit: int,
    account_id: str = "",
) -> int:
    """Сколько ещё первых сообщений можно закрепить/отправить менеджеру сегодня."""
    shares = daily_shares_for_account(daily_limit)
    quota = int(shares.get(manager_id) or 0)
    if quota <= 0:
        return 0
    from bot.rate_limit import OutreachLimiter
    from bot.tg_accounts import get_tg_accounts

    acc = None
    try:
        tg = get_tg_accounts()
        acc = tg.get(account_id) if account_id else tg.for_manager(manager_id)
        if acc is None:
            acc = tg.main()
    except Exception:
        acc = None
    if acc is not None:
        lim = OutreachLimiter.for_account(store, acc, manager_id=manager_id)
    else:
        lim = OutreachLimiter(store, manager_id=manager_id, daily_limit=daily_limit)
    return max(0, quota - lim.manager_sent_today())


def redistribute_unassigned(store: Store, *, mode: str | None = None) -> dict[str, Any]:
    """Раздать pending без manager_id. mode=even|manual; even учитывает share_weight."""
    mode = mode or dash_auth.get_distribution_mode()
    if mode == "manual":
        return {"mode": mode, "assigned": 0, "skipped": "manual"}
    mids = active_manager_ids()
    if not mids:
        return {"mode": mode, "assigned": 0, "skipped": "no_managers"}
    weights = share_weights(mids)
    slots: list[str] = []
    for mid, w in sorted(weights.items()):
        slots.extend([mid] * w)
    if not slots:
        return {"mode": mode, "assigned": 0, "skipped": "no_managers"}
    rows = store._conn.execute(
        "SELECT phone FROM contacts WHERE status='pending' "
        "AND (manager_id='' OR manager_id IS NULL) "
        "AND (tg_status IS NULL OR tg_status='' OR tg_status!='нет в Telegram') "
        "ORDER BY id"
    ).fetchall()
    assigned = 0
    for i, row in enumerate(rows):
        mid = slots[i % len(slots)]
        store._conn.execute(
            "UPDATE contacts SET manager_id=? WHERE phone=? AND (manager_id='' OR manager_id IS NULL)",
            (mid, row["phone"]),
        )
        assigned += 1
    store._conn.commit()
    logger.info("redistribute mode=%s assigned=%s managers=%s", mode, assigned, mids)
    return {
        "mode": mode,
        "assigned": assigned,
        "managers": mids,
        "shares": daily_shares_for_account(
            int(__import__("os").getenv("DAILY_SEND_LIMIT") or "30")
        ),
        "weights": weights,
    }


def build_day_queue(
    store: Store,
    *,
    daily_limit: int,
    account_id: str = "",
    only_manager_id: str = "",
) -> list[dict[str, Any]]:
    """Очередь первых сообщений на сегодня: доли → assign manager_id сразу.

    Уже отправленные сегодня вычитаются из квоты. Свободные pending
    раздаются round-robin по весам (не «заполнить первого полностью»).
    only_manager_id — только доля одного менеджера (для его /send).
    """
    shares = daily_shares_for_account(daily_limit)
    if only_manager_id:
        shares = {only_manager_id: int(shares.get(only_manager_id) or 0)}

    need_left: dict[str, int] = {}
    for mid, quota in shares.items():
        rem = manager_remaining_share(
            store, mid, daily_limit=daily_limit, account_id=account_id
        )
        need_left[mid] = min(int(quota), rem)

    out: list[dict[str, Any]] = []
    # 1) уже закреплённые за менеджером pending
    for mid, need in list(need_left.items()):
        if need <= 0:
            continue
        batch = store.list_outreach_batch(
            limit=need, manager_id=mid, default_manager_id=""
        )
        for c in batch:
            d = dict(c)
            d["manager_id"] = mid
            if account_id:
                d["tg_account_id"] = account_id
            out.append(d)
        need_left[mid] = need - len(batch)

    # 2) свободные — round-robin по весам среди тех, кому ещё нужна квота
    weights = share_weights(list(need_left.keys()))
    slots: list[str] = []
    for mid, w in sorted(weights.items()):
        if need_left.get(mid, 0) > 0:
            slots.extend([mid] * w)
    if slots:
        total_need = sum(need_left.values())
        free = store._conn.execute(
            """
            SELECT * FROM contacts WHERE status='pending'
              AND (manager_id='' OR manager_id IS NULL)
              AND (tg_status IS NULL OR tg_status='' OR tg_status!='нет в Telegram')
              AND (send_on='' OR send_on IS NULL OR send_on<=?)
              AND (tg_account_id='' OR tg_account_id IS NULL OR tg_account_id=?)
            ORDER BY id LIMIT ?
            """,
            (_moscow_today(), account_id or "", total_need),
        ).fetchall()
        si = 0
        for row in free:
            # найти следующего менеджера с остатком квоты
            tries = 0
            while tries < len(slots) and need_left.get(slots[si % len(slots)], 0) <= 0:
                si += 1
                tries += 1
            if tries >= len(slots):
                break
            mid = slots[si % len(slots)]
            si += 1
            store._conn.execute(
                "UPDATE contacts SET manager_id=? WHERE phone=?",
                (mid, row["phone"]),
            )
            d = dict(row)
            d["manager_id"] = mid
            if account_id:
                d["tg_account_id"] = account_id
            out.append(d)
            need_left[mid] = need_left.get(mid, 0) - 1
        store._conn.commit()

    logger.info(
        "day queue size=%s shares=%s only=%s",
        len(out),
        shares,
        only_manager_id or "*",
    )
    return out


def on_manager_disabled(store: Store, manager_id: str) -> dict[str, Any]:
    """Долю отключённого раздаём остальным (только незакреплённые + его pending без sent)."""
    reg = get_registry()
    try:
        reg.set_enabled(manager_id, False)
    except Exception:
        pass
    # pending этого менеджера без отправки → снова в общий пул
    store._conn.execute(
        "UPDATE contacts SET manager_id='' WHERE manager_id=? AND status='pending'",
        (manager_id,),
    )
    store._conn.commit()
    return redistribute_unassigned(store)


def on_manager_enabled(manager_id: str) -> None:
    try:
        get_registry().set_enabled(manager_id, True)
    except Exception:
        pass


def on_manager_telegram_linked(store: Store, manager_id: str) -> dict[str, Any]:
    result = redistribute_unassigned(store)
    result["linked_manager"] = manager_id
    return result


def on_account_linked(store: Store, account_id: str, manager_id: str = "") -> dict[str, Any]:
    result = redistribute_unassigned(store)
    result["linked_account"] = account_id
    result["linked_manager"] = manager_id
    return result
