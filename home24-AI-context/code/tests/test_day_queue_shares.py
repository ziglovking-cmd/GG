"""Дневная очередь: кап 172 делится по активным менеджерам, disable → перерасчёт."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.dashboard import auth as dash_auth
from bot.dashboard.distribute import (
    active_manager_ids,
    build_day_queue,
    daily_shares_for_account,
    on_manager_disabled,
    split_quota,
)
from bot.managers import ManagerRegistry, reset_registry_cache
from bot.store import Store


def _setup(n_managers: int = 4) -> tuple[Path, Store, list[str]]:
    tmp = Path(tempfile.mkdtemp())
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    os.environ["DASHBOARD_USERS_PATH"] = str(tmp / "users.json")
    os.environ["DATABASE_PATH"] = str(tmp / "db.sqlite")
    reset_registry_cache()
    names = [("anna", "Анна"), ("ivan", "Иван"), ("maria", "Мария"), ("oleg", "Олег"), ("elena", "Елена")]
    names = names[:n_managers]
    users = [
        {
            "username": "admin",
            "role": "admin",
            "manager_id": "",
            "password_hash": dash_auth.hash_password("x"),
            "enabled": True,
        }
    ]
    reg = ManagerRegistry(tmp / "managers.json")
    mids = []
    for mid, name in names:
        reg.upsert(manager_id=mid, name=name, share_weight=1)
        mids.append(mid)
        users.append(
            {
                "username": mid,
                "role": "manager",
                "manager_id": mid,
                "password_hash": dash_auth.hash_password("x"),
                "enabled": True,
            }
        )
    dash_auth.save_store(
        {"users": users, "distribution": {"mode": "even"}, "setup_done": True},
        tmp / "users.json",
    )
    store = Store(str(tmp / "db.sqlite"))
    return tmp, store, mids


def test_four_managers_43_each() -> None:
    q = split_quota(172, {f"m{i}": 1 for i in range(4)})
    assert sum(q.values()) == 172
    assert all(v == 43 for v in q.values())


def test_five_managers_34_plus_remainder() -> None:
    q = split_quota(172, {f"m{i}": 1 for i in range(5)})
    assert sum(q.values()) == 172
    assert min(q.values()) == 34
    assert max(q.values()) == 35


def test_custom_shares() -> None:
    q = split_quota(100, {"a": 1, "b": 3})
    assert q["a"] == 25 and q["b"] == 75


def test_disabled_manager_redistributes() -> None:
    tmp, store, mids = _setup(4)
    assert len(active_manager_ids()) == 4
    shares = daily_shares_for_account(172)
    assert all(v == 43 for v in shares.values())
    # отключить одного
    dash_auth.set_user_enabled(mids[0], False, path=tmp / "users.json")
    on_manager_disabled(store, mids[0])
    active = active_manager_ids()
    assert mids[0] not in active
    assert len(active) == 3
    shares2 = daily_shares_for_account(172)
    assert mids[0] not in shares2
    assert sum(shares2.values()) == 172
    # 172/3 = 57 + remainder
    assert min(shares2.values()) >= 57
    assert max(shares2.values()) <= 58


def test_build_day_queue_assigns_managers() -> None:
    tmp, store, mids = _setup(4)
    for i in range(80):
        store.add_contact(phone=f"+7900111{i:04d}", name=f"C{i}")
    queue = build_day_queue(store, daily_limit=172, account_id="main")
    assert len(queue) == 80  # меньше капа — все pending
    by_m: dict[str, int] = {}
    for c in queue:
        mid = c["manager_id"]
        by_m[mid] = by_m.get(mid, 0) + 1
        row = store.contact_by_phone(c["phone"])
        assert row["manager_id"] == mid
    # равномерно примерно
    assert set(by_m) == set(mids)
    assert max(by_m.values()) - min(by_m.values()) <= 1


def test_build_day_queue_respects_share_cap() -> None:
    tmp, store, mids = _setup(4)
    for i in range(200):
        store.add_contact(phone=f"+7900222{i:04d}", name=f"D{i}")
    queue = build_day_queue(store, daily_limit=172, account_id="main")
    assert len(queue) == 172
    by_m: dict[str, int] = {}
    for c in queue:
        by_m[c["manager_id"]] = by_m.get(c["manager_id"], 0) + 1
    assert all(v == 43 for v in by_m.values())


def test_only_manager_slice() -> None:
    tmp, store, mids = _setup(4)
    for i in range(100):
        store.add_contact(phone=f"+7900333{i:04d}", name=f"E{i}")
    q = build_day_queue(
        store, daily_limit=172, account_id="main", only_manager_id=mids[0]
    )
    assert len(q) == 43
    assert all(c["manager_id"] == mids[0] for c in q)


if __name__ == "__main__":
    test_four_managers_43_each()
    test_five_managers_34_plus_remainder()
    test_custom_shares()
    test_disabled_manager_redistributes()
    test_build_day_queue_assigns_managers()
    test_build_day_queue_respects_share_cap()
    test_only_manager_slice()
    print("ok")
