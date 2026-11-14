# -*- coding: utf-8 -*-
"""Рассылка с панели: разбор номеров и постановка в очередь бота."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp.test_utils import TestClient, TestServer

from bot.config import get_settings
from bot.dashboard import auth as dash_auth
from bot.dashboard.app import INDEX_HTML, create_dashboard_app
from bot.managers import ManagerRegistry, reset_registry_cache
from bot.outreach_jobs import parse_outreach_lines
from bot.store import Store


def test_parse_phones() -> None:
    rows = parse_outreach_lines(
        "[REDACTED], Мария\n89651960074\n@home24guest\nмусор\n"
    )
    phones = [r["phone"] for r in rows]
    assert phones == ["[REDACTED]", "[REDACTED]", "@home24guest"]
    assert rows[0]["name"] == "Мария"


def test_compose_queues_job_without_sending() -> None:
    import asyncio

    async def run() -> None:
        tmp = Path(tempfile.mkdtemp())
        users = tmp / "users.json"
        users.write_text(
            json.dumps(
                {
                    "users": [
                        {
                            "username": "admin",
                            "role": "admin",
                            "manager_id": "",
                            "display_name": "Админ",
                            "password_hash": dash_auth.hash_password("admin123"),
                            "enabled": True,
                            "must_change_password": False,
                            "session_jti": "",
                        }
                    ],
                    "distribution": {"mode": "even"},
                    "setup_done": True,
                }
            ),
            encoding="utf-8",
        )
        os.environ["DASHBOARD_USERS_PATH"] = str(users)
        os.environ["DATABASE_PATH"] = str(tmp / "home24.db")
        os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
        os.environ["OUTREACH_JOBS_DIR"] = str(tmp / "jobs")
        os.environ["OUTREACH_STATUS_PATH"] = str(tmp / "status.json")
        os.environ["HOME24_DASHBOARD_DEMO"] = "0"
        get_settings.cache_clear()
        reset_registry_cache()
        ManagerRegistry(tmp / "managers.json").upsert(
            manager_id="anna", name="Анна", make_default=True
        )
        app = create_dashboard_app()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            assert 'data-page="mail"' in INDEX_HTML
            assert 'id="btnMailNow"' in INDEX_HTML
            r = await client.post(
                "/api/login", json={"username": "admin", "password": "admin123"}
            )
            body = await r.json()
            assert r.status == 200
            csrf = body["csrf"]
            r = await client.post(
                "/api/outreach/compose",
                json={"text": "[REDACTED], Мария\nнет номера", "now": True},
                headers={"X-CSRF-Token": csrf},
            )
            data = await r.json()
            assert r.status == 200, data
            assert data["queued"] == ["[REDACTED]"]
            jobs = list((tmp / "jobs").glob("*.json"))
            assert len(jobs) == 1
            job = json.loads(jobs[0].read_text(encoding="utf-8"))
            assert job["now"] is True
            assert job["phones"] == ["[REDACTED]"]
            store = Store(str(tmp / "home24.db"))
            row = store.contact_by_phone("[REDACTED]")
            assert row and row["status"] == "pending"
            assert row["name"] == "Мария"
        finally:
            await client.close()

    asyncio.run(run())


if __name__ == "__main__":
    test_parse_phones()
    test_compose_queues_job_without_sending()
    print("ok outreach desk")
