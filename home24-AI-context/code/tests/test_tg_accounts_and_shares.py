"""Telegram-аккаунты компании, доли менеджеров, недельный кап, кэш контактов."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.dashboard.distribute import daily_shares_for_account, split_quota
from bot.managers import ManagerRegistry, reset_registry_cache
from bot.rate_limit import OutreachLimiter
from bot.store import Store
from bot.tg_accounts import TgAccountRegistry, reset_tg_accounts_cache


def test_split_quota_five_managers() -> None:
    w = {f"m{i}": 1 for i in range(5)}
    q = split_quota(172, w)
    assert sum(q.values()) == 172
    assert min(q.values()) == 34
    assert max(q.values()) == 35  # 172 = 34*5 + 2


def test_tg_accounts_max_six() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "tg.json"
    reset_tg_accounts_cache()
    reg = TgAccountRegistry(path)
    reg.accounts.clear()
    for i in range(6):
        reg.upsert(account_id=f"a{i}", label=f"A{i}", is_main=(i == 0))
    assert len(reg.accounts) == 6
    try:
        reg.upsert(account_id="a6", label="X")
        assert False, "should raise"
    except ValueError:
        pass


def test_new_account_defaults_to_30_daily() -> None:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "tg.json"
    os.environ["TG_ACCOUNT_NEW_DAILY_LIMIT"] = "30"
    os.environ["DAILY_SEND_LIMIT"] = "172"
    os.environ["WEEKLY_SEND_LIMIT"] = "1200"
    reg = TgAccountRegistry(path)
    reg.accounts.clear()
    main = reg.upsert(account_id="main", label="Main", is_main=True)
    assert main.daily_send_limit == 30
    assert main.weekly_send_limit == 210
    extra = reg.upsert(account_id="sim2", label="SIM2", manager_id="anna")
    assert extra.daily_send_limit == 30
    assert extra.weekly_send_limit == 210
    assert extra.manager_id == "anna"


def test_sole_shared_account() -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = TgAccountRegistry(tmp / "tg.json")
    reg.accounts.clear()
    reg.upsert(account_id="main", label="Main", is_main=True)
    reg.set_session("main", "SESS")
    assert reg.sole_shared() and reg.sole_shared().id == "main"
    assert reg.for_manager("anna").id == "main"


def test_multi_account_no_cross_manager_fallback() -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = TgAccountRegistry(tmp / "tg.json")
    reg.accounts.clear()
    reg.upsert(account_id="main", label="Main", is_main=True, manager_id="anna")
    reg.set_session("main", "SESS1")
    reg.upsert(account_id="sim2", label="SIM2", manager_id="ivan")
    reg.set_session("sim2", "SESS2")
    assert reg.sole_shared() is None
    assert reg.for_manager("anna").id == "main"
    assert reg.for_manager("ivan").id == "sim2"
    assert reg.for_manager("maria") is None  # нет своей SIM — не берём чужую
    # один менеджер — один аккаунт
    reg.upsert(account_id="sim2", manager_id="anna")
    assert reg.get("main").manager_id == ""
    assert reg.get("sim2").manager_id == "anna"


def test_paused_account_not_reassigned() -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = TgAccountRegistry(tmp / "tg.json")
    reg.accounts.clear()
    reg.upsert(account_id="main", label="Main", is_main=True, manager_id="anna")
    reg.set_session("main", "SESS1")
    reg.upsert(account_id="sim2", label="SIM2", manager_id="ivan")
    reg.set_session("sim2", "SESS2")
    reg.mark_paused("main", "PeerFlood", status="restricted")
    # for_manager не отдаёт paused
    assert reg.for_manager("anna") is None
    # for_contact сохраняет слот клиента даже paused — без подмены
    stuck = reg.for_contact("main", manager_id="anna")
    assert stuck is not None and stuck.id == "main" and stuck.paused
    assert reg.for_contact("main", manager_id="ivan").id == "main"


def test_weekly_limit() -> None:
    tmp = Path(tempfile.mkdtemp())
    store = Store(str(tmp / "db.sqlite"))
    lim = OutreachLimiter(
        store,
        account_id="main",
        daily_limit=172,
        weekly_limit=5,
        work_start=0,
        work_end=24,
    )
    for _ in range(5):
        lim.record_send()
    assert lim.sent_week() >= 5
    assert lim.remaining_week() == 0
    ok, why = lim.can_send()
    assert not ok and "недельный" in why


def test_contact_telegram_cache() -> None:
    tmp = Path(tempfile.mkdtemp())
    store = Store(str(tmp / "db.sqlite"))
    store.add_contact("[REDACTED]", name="Иван Тест")
    store.set_contact_telegram(
        "[REDACTED]",
        telegram_user_id="12345",
        tg_status="ok",
        tg_account_id="main",
    )
    row = store.contact_by_phone("[REDACTED]")
    assert row["telegram_user_id"] == "12345"
    assert row["tg_status"] == "ok"
    # second assign does not overwrite account
    store.set_contact_telegram(
        "[REDACTED]", telegram_user_id="12345", tg_status="ok", tg_account_id="other"
    )
    assert store.contact_by_phone("[REDACTED]")["tg_account_id"] == "main"


def test_daily_shares_with_registry() -> None:
    tmp = Path(tempfile.mkdtemp())
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    os.environ["DASHBOARD_USERS_PATH"] = str(tmp / "users.json")
    reset_registry_cache()
    from bot.dashboard import auth as dash_auth

    dash_auth.save_store(
        {
            "users": [
                {
                    "username": "admin",
                    "role": "admin",
                    "manager_id": "",
                    "password_hash": dash_auth.hash_password("x"),
                    "enabled": True,
                },
                *[
                    {
                        "username": mid,
                        "role": "manager",
                        "manager_id": mid,
                        "password_hash": dash_auth.hash_password("x"),
                        "enabled": True,
                    }
                    for mid in ("anna", "ivan", "maria", "oleg", "elena")
                ],
            ],
            "distribution": {"mode": "even"},
        },
        tmp / "users.json",
    )
    reg = ManagerRegistry(tmp / "managers.json")
    for mid, name in (
        ("anna", "Анна"),
        ("ivan", "Иван"),
        ("maria", "Мария"),
        ("oleg", "Олег"),
        ("elena", "Елена"),
    ):
        reg.upsert(manager_id=mid, name=name)
    shares = daily_shares_for_account(172)
    assert len(shares) == 5
    assert sum(shares.values()) == 172


if __name__ == "__main__":
    test_split_quota_five_managers()
    test_tg_accounts_max_six()
    test_new_account_defaults_to_30_daily()
    test_sole_shared_account()
    test_multi_account_no_cross_manager_fallback()
    test_paused_account_not_reassigned()
    test_weekly_limit()
    test_contact_telegram_cache()
    test_daily_shares_with_registry()
    print("ok")
