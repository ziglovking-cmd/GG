# -*- coding: utf-8 -*-
"""Тишина outreach после свежего входа в аккаунт."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.rate_limit import OutreachLimiter
from bot.store import Store
from bot.tg_accounts import TgAccountRegistry, format_quiet_countdown, reset_tg_accounts_cache


def test_format_quiet_countdown() -> None:
    assert format_quiet_countdown(0) == ""
    assert "ч" in format_quiet_countdown(3661)
    assert "м" in format_quiet_countdown(125)


def test_fresh_session_sets_quiet_period() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "tg.json"
    os.environ["TG_ACCOUNTS_PATH"] = str(path)
    os.environ["TG_QUIET_HOURS_AFTER_LOGIN"] = "24"
    reset_tg_accounts_cache()
    reg = TgAccountRegistry(path)
    reg.accounts.clear()
    reg.upsert(account_id="main", is_main=True, quiet_hours_after_login=24)
    assert reg.get("main").no_outreach_until == 0

    before = time.time()
    acc = reg.apply_authorized_session(
        session="SESS_NEW_1",
        phone="[REDACTED]",
        telegram_user_id="1001",
        manager_id="",
        preferred_account_id="main",
    )
    assert acc.quiet_remaining_sec() > 23 * 3600
    assert acc.no_outreach_until >= before + 23 * 3600
    blocked, why = acc.outreach_quiet_status()
    assert blocked
    assert "тишина" in why

    # тот же sess повторно — тишину не продлеваем
    until = acc.no_outreach_until
    time.sleep(0.05)
    acc2 = reg.apply_authorized_session(
        session="SESS_NEW_1",
        phone="[REDACTED]",
        telegram_user_id="1001",
        preferred_account_id="main",
    )
    assert acc2.no_outreach_until == until

    # новая сессия — новая тишина
    time.sleep(0.05)
    acc3 = reg.apply_authorized_session(
        session="SESS_NEW_2",
        phone="[REDACTED]",
        telegram_user_id="1001",
        preferred_account_id="main",
    )
    assert acc3.no_outreach_until > until


def test_quiet_blocks_outreach_limiter() -> None:
    from bot.tg_accounts import get_tg_accounts

    tmp = Path(tempfile.mkdtemp())
    path = tmp / "tg.json"
    db = tmp / "db.sqlite"
    os.environ["TG_ACCOUNTS_PATH"] = str(path)
    reset_tg_accounts_cache()
    reg = get_tg_accounts()
    reg.accounts.clear()
    a = reg.upsert(account_id="main", is_main=True, quiet_hours_after_login=24)
    a.no_outreach_until = time.time() + 3600
    a.session = "S"
    a.status = "ok"
    reg.save()

    store = Store(str(db))
    lim = OutreachLimiter.for_account(store, reg.get("main"))
    # обойти окно часов для изоляции quiet
    lim.work_start = 0
    lim.work_end = 24
    can, why = lim.can_send()
    assert not can
    assert "тишина" in why
    c = lim.counts()
    assert c["quiet_active"] is True
    assert c["quiet_remaining_sec"] > 0

    # снять тишину — can_send ок (в пределах лимитов)
    a.no_outreach_until = 0
    reg.save()
    can2, why2 = lim.can_send()
    assert can2, why2


def test_quiet_hours_zero_skips_auto() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "tg.json"
    reset_tg_accounts_cache()
    reg = TgAccountRegistry(path)
    reg.accounts.clear()
    reg.upsert(account_id="main", is_main=True, quiet_hours_after_login=0)
    acc = reg.apply_authorized_session(
        session="S1",
        telegram_user_id="9",
        preferred_account_id="main",
    )
    assert acc.no_outreach_until == 0
    assert not acc.outreach_quiet_status()[0]


def test_admin_can_set_no_outreach_until() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "tg.json"
    reset_tg_accounts_cache()
    reg = TgAccountRegistry(path)
    reg.accounts.clear()
    until = time.time() + 7200
    a = reg.upsert(
        account_id="main",
        is_main=True,
        no_outreach_until=until,
        quiet_hours_after_login=12,
    )
    assert abs(a.no_outreach_until - until) < 1
    assert a.quiet_hours_after_login == 12
    pub = a.public_dict()
    assert pub["quiet_active"] is True
    assert "тишина" in pub["quiet_label"]


if __name__ == "__main__":
    test_format_quiet_countdown()
    test_fresh_session_sets_quiet_period()
    test_quiet_blocks_outreach_limiter()
    test_quiet_hours_zero_skips_auto()
    test_admin_can_set_no_outreach_until()
    print("ok")
