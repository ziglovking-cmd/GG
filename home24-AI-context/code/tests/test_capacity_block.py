# -*- coding: utf-8 -*-
"""Блок «Сейчас / Потенциал» на главной панели: /api/capacity + рендер /app для admin и менеджера."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_dashboard_auth import _client  # noqa: E402


def test_capacity_api_and_page_admin_and_manager() -> None:
    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        client, store, _users = await _client(tmp)
        try:
            from bot.managers import get_registry
            from bot.rate_limit import OutreachLimiter

            for m in get_registry().enabled_list():
                get_registry().upsert(manager_id=m.id, name=m.name, weekly_send_limit=210)
            lim = OutreachLimiter(store)
            now = lim.now()
            store.set_meta(f"outreach_cnt_d:acc:main:{now:%Y-%m-%d}", "5")
            store.set_meta(f"outreach_cnt_d:acc:x:{(now - timedelta(days=1)):%Y-%m-%d}", "4")
            store.set_meta(f"outreach_cnt_d:acc:main:{(now - timedelta(days=8)):%Y-%m-%d}", "100")  # вне окна
            for user, pw in (("admin", "admin123"), ("anna", "anna123")):
                r = await client.post("/api/login", json={"username": user, "password": pw})
                assert r.status == 200, user
                r = await client.get("/app")
                assert r.status == 200 and 'id="statsStrip"' in await r.text()
                r = await client.get("/api/capacity")
                assert r.status == 200, user
                c = await r.json()
                assert c["sent_week"] == 9, c
                assert c["weekly_limit"] == 210, c
                assert c["extra_accounts"] == 5
                assert c["potential_week"] == 210 * (c["accounts_now"] + 5)
                await client.post("/api/logout")
            js = (ROOT / "bot" / "dashboard" / "static" / "dashboard.js").read_text(encoding="utf-8")
            assert "Потенциал: ${cap.potential_week} в неделю" in js
            assert "при подключении ещё ${cap.extra_accounts}" in js
            assert "/api/capacity" in js
        finally:
            await client.close()

    asyncio.run(run())
