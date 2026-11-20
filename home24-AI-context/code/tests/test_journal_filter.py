# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.hub import HubLogHandler, LogRing, get_hub, is_technical_logger


def test_technical_logger_detection() -> None:
    assert is_technical_logger("aiohttp.access")
    assert is_technical_logger("aiohttp.server")
    assert is_technical_logger("telethon.network.mtprotosender")
    assert not is_technical_logger("home24.dashboard")
    assert not is_technical_logger("home24")


def test_log_ring_filters_technical() -> None:
    ring = LogRing(n=50)
    ring.add("INFO", "home24.bot", "sent outreach")
    ring.add("INFO", "aiohttp.access", "GET /api/queue")
    ring.add("WARNING", "telethon.network", "timeout")
    plain = ring.list(technical=False)
    assert len(plain) == 1
    assert plain[0]["logger"] == "home24.bot"
    tech = ring.list(technical=True)
    assert len(tech) == 3


def test_hub_handler_skips_access_info() -> None:
    hub = get_hub()
    hub.logs = LogRing(n=50)
    h = HubLogHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    rec = logging.LogRecord(
        "aiohttp.access", logging.INFO, __file__, 1, "GET /api/queue", (), None
    )
    h.emit(rec)
    assert hub.logs.list(technical=True) == []
    rec2 = logging.LogRecord(
        "home24", logging.INFO, __file__, 1, "account online", (), None
    )
    h.emit(rec2)
    rows = hub.logs.list(technical=False)
    assert any("online" in r["message"] for r in rows)


if __name__ == "__main__":
    test_technical_logger_detection()
    test_log_ring_filters_technical()
    test_hub_handler_skips_access_info()
    print("ok")
