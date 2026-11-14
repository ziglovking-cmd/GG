# -*- coding: utf-8 -*-
"""Shared Telegram account bind: manager_id='' = общий, must persist."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp.test_utils import TestClient, TestServer

from bot.managers import reset_registry_cache
from bot.tg_accounts import reset_tg_accounts_cache


def _reset_web_login_state() -> None:
    import bot.web_login as wl

    wl._state.update(
        {
            "status": "idle",
            "message": "Выберите менеджера и способ входа",
            "qr_b64": "",
            "need_2fa": False,
            "phone_hash": "",
            "phone": "",
            "done": False,
            "me": None,
            "manager_id": None,
            "account_id": "main",
            "tdata_accounts": [],
            "_tdata_sessions": {},
            "_client": None,
            "_qr": None,
            "_qr_task": None,
        }
    )


async def _run_shared_bind_flow(tmp: Path) -> None:
    os.environ["TG_ACCOUNTS_PATH"] = str(tmp / "tg_accounts.json")
    os.environ["MANAGERS_PATH"] = str(tmp / "managers.json")
    (tmp / "managers.json").write_text(
        json.dumps(
            {
                "default_manager_id": "anna",
                "managers": [
                    {"id": "anna", "name": "Анна", "enabled": True},
                    {"id": "ivan", "name": "Иван", "enabled": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    reset_registry_cache()
    reset_tg_accounts_cache()

    from bot.tg_accounts import get_tg_accounts

    # seed main bound to anna — classic snap-back source
    tg = get_tg_accounts()
    tg.upsert(account_id="main", is_main=True, manager_id="anna", label="Основной")
    assert tg.get("main").manager_id == "anna"

    _reset_web_login_state()
    from bot.web_login import HTML, _state, create_app

    assert "dataset.dirty" in HTML
    assert "showToast" in HTML
    assert "— общий (все менеджеры)" in HTML

    app = create_app()
    # hydrate from tg_accounts → anna (not forced forever as write-only default)
    assert _state["manager_id"] == "anna"

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        st = await (await client.get("/api/status")).json()
        assert st["manager_id"] == "anna"

        # explicit shared
        r = await (
            await client.post(
                "/api/manager/select",
                json={"manager_id": "", "account_id": "main"},
            )
        ).json()
        assert r.get("ok") is not False
        assert r["manager_id"] == ""
        assert r["account_id"] == "main"
        assert "общий" in (r.get("message") or "").lower()

        # in-memory + disk
        assert _state["manager_id"] == ""
        reset_tg_accounts_cache()
        tg2 = get_tg_accounts()
        assert tg2.get("main").manager_id == ""

        # poll must keep shared
        st2 = await (await client.get("/api/status")).json()
        assert st2["manager_id"] == ""

        # aliases → общий
        for alias in ("shared", "__shared__", "-", "*", "default"):
            await (
                await client.post(
                    "/api/manager/select",
                    json={"manager_id": "anna", "account_id": "main"},
                )
            ).json()
            r_alias = await (
                await client.post(
                    "/api/manager/select",
                    json={"manager_id": alias, "account_id": "main"},
                )
            ).json()
            assert r_alias["manager_id"] == "", alias

        # re-hydrate after process-like reset
        _reset_web_login_state()
        from bot.web_login import _hydrate_bind_from_accounts, _public_status

        _hydrate_bind_from_accounts()
        assert _state["manager_id"] == ""
        pub = _public_status()
        assert pub["manager_id"] == ""
    finally:
        await client.close()


def test_shared_manager_select_persists() -> None:
    with tempfile.TemporaryDirectory() as td:
        asyncio.run(_run_shared_bind_flow(Path(td)))


def test_html_poll_respects_dirty() -> None:
    from bot.web_login import HTML

    assert "sel.dataset.dirty" in HTML
    assert "forceSelect" in HTML
    assert "setInterval(refresh, 2000)" in HTML


if __name__ == "__main__":
    test_html_poll_respects_dirty()
    test_shared_manager_select_persists()
    print("ok")
