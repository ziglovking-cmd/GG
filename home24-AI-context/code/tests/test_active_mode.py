# -*- coding: utf-8 -*-
"""v8.1/v8.2: active mode — сразу отвечаем в живом диалоге, после тишины снова окна."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.presence import (
    ActiveConversation,
    default_check_settings,
    get_check_settings,
    save_check_settings,
)
from bot.store import Store


def _db_path(base: Path | None = None) -> Path:
    """Windows-safe: always a .db file under an existing directory."""
    if base is None:
        base = Path(tempfile.mkdtemp(prefix="h24_am_"))
    else:
        base = Path(base)
        base.mkdir(parents=True, exist_ok=True)
    return base / "home24_test.db"


def test_active_mode_enter_and_idle_exit():
    ac = ActiveConversation()
    s = {"active_idle_min": 10}
    ac.touch(s)
    assert ac.is_active(s) is True

    # simulate silence longer than idle
    ac._last_guest_ts = time.time() - (10 * 60 + 5)
    assert ac.is_active(s) is False
    assert ac.just_left_active(s) is True
    # second call — already left
    assert ac.just_left_active(s) is False


def test_active_mode_extends_on_touch():
    ac = ActiveConversation()
    s = {"active_idle_min": 10}
    ac.touch(s)
    t1 = ac.last_guest_ts
    time.sleep(0.05)
    ac.touch(s)
    assert ac.last_guest_ts > t1
    assert ac.is_active(s)


def test_cold_not_active_until_touch():
    ac = ActiveConversation()
    s = {"active_idle_min": 10}
    assert ac.is_active(s) is False
    ac.touch(s)
    assert ac.is_active(s) is True


def test_settings_active_idle_roundtrip(tmp_path=None):
    db = _db_path(Path(tmp_path) if tmp_path is not None else None)
    st = Store(str(db))
    out = save_check_settings(st, {"active_idle_min": 12, "interval_min": 3})
    assert out["active_idle_min"] == 12
    got = get_check_settings(st)
    assert got["active_idle_min"] == 12


def test_default_active_idle_10():
    d = default_check_settings()
    assert d["active_idle_min"] == 10.0


if __name__ == "__main__":
    test_active_mode_enter_and_idle_exit()
    test_active_mode_extends_on_touch()
    test_cold_not_active_until_touch()
    test_settings_active_idle_roundtrip()
    test_default_active_idle_10()
    print("ok")
