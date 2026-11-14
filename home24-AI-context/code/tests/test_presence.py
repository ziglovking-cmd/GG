# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.presence import (
    default_check_settings,
    get_check_settings,
    is_night,
    next_wait_seconds,
    save_check_settings,
)
from bot.store import Store


def _db_path(base: Path | None = None) -> Path:
    """Windows-safe temp sqlite path (file under a real directory)."""
    if base is None:
        base = Path(tempfile.mkdtemp(prefix="h24_pr_"))
    else:
        base = Path(base)
        base.mkdir(parents=True, exist_ok=True)
    return base / "home24_test.db"


def test_night_span():
    s = {"night_start_hour": 23, "night_end_hour": 8}
    assert is_night(s, hour=23)
    assert is_night(s, hour=2)
    assert not is_night(s, hour=12)


def test_wait_jitter_bounds():
    # hour=12 явно: не зависит от wall-clock / night mode после 23:00
    # night_start=night_end=0 → is_night всегда False (и 0 больше не схлопывается в 23)
    s = {
        "interval_min": 3,
        "jitter": 0.3,
        "night_start_hour": 0,
        "night_end_hour": 0,
        "night_interval_min": 15,
    }
    for _ in range(40):
        w = next_wait_seconds(s, hour=12)
        assert 20 <= w <= 3 * 60 * 1.35
    # даже «ночью» по часам — при a==b ночи нет
    for _ in range(10):
        w = next_wait_seconds(s, hour=23)
        assert 20 <= w <= 3 * 60 * 1.35
    # 0 час валиден как night_start (раньше `or 23` ломал тест)
    s_night = {
        "interval_min": 3,
        "jitter": 0.0,
        "night_start_hour": 0,
        "night_end_hour": 8,
        "night_interval_min": 15,
    }
    assert is_night(s_night, hour=0)
    assert is_night(s_night, hour=3)
    assert not is_night(s_night, hour=12)
    w_night = next_wait_seconds(s_night, hour=1)
    assert abs(w_night - 15 * 60) < 1.0


def test_store_roundtrip(tmp_path=None):
    db = _db_path(Path(tmp_path) if tmp_path is not None else None)
    st = Store(str(db))
    out = save_check_settings(
        st,
        {
            "interval_min": 5,
            "jitter": 0.2,
            "night_interval_min": 20,
            "enabled": True,
        },
    )
    assert out["interval_min"] == 5
    got = get_check_settings(st)
    assert got["interval_min"] == 5
    assert got["night_interval_min"] == 20


def test_defaults():
    d = default_check_settings()
    assert d["interval_min"] == 3.0
    assert d["enabled"] is True


if __name__ == "__main__":
    test_night_span()
    test_wait_jitter_bounds()
    test_store_roundtrip()
    test_defaults()
    print("ok")
