# -*- coding: utf-8 -*-
"""Unit tests: process locks + in-process client registry."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_lock_acquire_release_and_stale(monkeypatch=None) -> None:
    from bot import instance_guard as ig

    td = tempfile.mkdtemp(prefix="h24_locks_")
    os.environ["HOME24_LOCKS_DIR"] = td
    # reset held map
    ig._HELD.clear()

    ok, msg = ig.try_acquire("unit_a", account_id="main", role="bot")
    assert ok, msg
    st = ig.lock_status("unit_a")
    assert st["held"] is True
    assert st["pid"] == os.getpid()

    # second acquire same process — ok
    ok2, _ = ig.try_acquire("unit_a", role="bot")
    assert ok2

    # simulate foreign live PID by writing another pid that is alive (self) under other name
    other = Path(td) / "unit_b.lock"
    other.write_text(
        '{"pid": %d, "started_at": 1, "account_id": "x", "role": "bot"}' % os.getpid(),
        encoding="utf-8",
    )
    # same PID is "alive" — refuse
    ok3, msg3 = ig.try_acquire("unit_b", role="bot")
    # unit_b was written with our pid but not in _HELD — try_acquire sees alive pid == self
    # Our code treats pid == getpid() as re-entrant only if path exists and pid matches
    # Actually: `if pid == os.getpid(): _HELD[name]=path; return True`
    assert ok3, msg3

    # stale: dead pid
    ig.release("unit_a")
    stale = Path(td) / "stale.lock"
    stale.write_text(
        '{"pid": 1, "started_at": 1, "account_id": "", "role": "bot"}',
        encoding="utf-8",
    )
    # pid 1 may or may not be alive; force _pid_alive False
    real_alive = ig._pid_alive

    def fake_alive(pid: int) -> bool:
        if pid == 1:
            return False
        return real_alive(pid)

    ig._pid_alive = fake_alive  # type: ignore
    try:
        ok4, msg4 = ig.try_acquire("stale", role="bot")
        assert ok4, msg4
        ig.release("stale")
    finally:
        ig._pid_alive = real_alive  # type: ignore

    ig.release_all()
    print("test_lock_acquire_release_and_stale OK")


def test_reconnect_gap_after_crash() -> None:
    import time

    from bot import instance_guard as ig

    td = tempfile.mkdtemp(prefix="h24_gap_")
    os.environ["HOME24_LOCKS_DIR"] = td
    ig._HELD.clear()
    ig._write_stamp("account_main", at=time.time(), clean=False)
    crashed = ig.reconnect_wait_seconds("account_main")
    assert 15 <= crashed <= 20, crashed
    ig._write_stamp("account_main", at=time.time() - 120, clean=False)
    assert ig.reconnect_wait_seconds("account_main") == 0
    ig._write_stamp("account_main", at=time.time(), clean=True)
    clean = ig.reconnect_wait_seconds("account_main")
    assert 0 < clean <= 4, clean
    print("test_reconnect_gap_after_crash OK")


def test_second_client_refused() -> None:
    import asyncio

    from bot import client_registry as cr
    from bot import instance_guard as ig

    td = tempfile.mkdtemp(prefix="h24_locks2_")
    os.environ["HOME24_LOCKS_DIR"] = td
    ig._HELD.clear()
    cr._LIVE.clear()

    class FakeClient:
        async def disconnect(self):
            return None

    c1, c2 = FakeClient(), FakeClient()
    ok, msg = cr.claim("main", c1, role="bot", session="sessA")
    assert ok, msg
    ok2, msg2 = cr.claim("main", c2, role="login", session="sessA")
    assert not ok2
    assert "TelegramClient" in msg2 or "запрещены" in msg2

    asyncio.run(cr.release("main", disconnect=True))
    ig.release_all()
    print("test_second_client_refused OK")


def test_duplicate_phone_rejected() -> None:
    from bot.tg_accounts import TgAccountRegistry

    td = tempfile.mkdtemp(prefix="h24_tg_")
    path = Path(td) / "tg_accounts.json"
    path.write_text(
        '{"accounts":[{"id":"main","phone":"[REDACTED]","session":"AAAA","status":"ok","enabled":true,"is_main":true}]}',
        encoding="utf-8",
    )
    reg = TgAccountRegistry(path)
    err = reg.reject_duplicate_phone("[REDACTED]", except_id="acc2")
    assert err and "уже привязан" in err
    # тот же телефон + другой preferred слот без match по user_id/session —
    # find_by_identity найдёт main по телефону и обновит его (не создаст второй)
    acc = reg.apply_authorized_session(
        session="AAAA",
        phone="[REDACTED]",
        telegram_user_id="42",
        preferred_account_id="acc2",
    )
    assert acc.id == "main"
    print("test_duplicate_phone_rejected OK")


def test_revoked_no_retry() -> None:
    from bot.tg_accounts import TgAccountRegistry

    td = tempfile.mkdtemp(prefix="h24_rev_")
    path = Path(td) / "tg_accounts.json"
    path.write_text(
        '{"accounts":[{"id":"main","phone":"+7900","session":"DEADSESS","status":"ok","enabled":true,"is_main":true}]}',
        encoding="utf-8",
    )
    reg = TgAccountRegistry(path)
    reg.mark_revoked("main", "SessionRevoked", clear_session=True)
    a = reg.get("main")
    assert a is not None
    assert a.status == "revoked"
    assert not (a.session or "").strip()
    ready = reg.unique_ready_ok()
    assert ready == []
    print("test_revoked_no_retry OK")


if __name__ == "__main__":
    test_lock_acquire_release_and_stale()
    test_reconnect_gap_after_crash()
    test_second_client_refused()
    test_duplicate_phone_rejected()
    test_revoked_no_retry()
    print("ok")
