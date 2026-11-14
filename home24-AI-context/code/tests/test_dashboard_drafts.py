# -*- coding: utf-8 -*-
"""Per-dialog reply drafts on the dashboard Dialogs tab (Playwright)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _wait_port(host: str, port: int, timeout: float = 20.0) -> None:
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.4)
            try:
                s.connect((host, port))
                return
            except OSError:
                time.sleep(0.2)
    raise RuntimeError(f"dashboard not up on {host}:{port}")


async def _run(base: str) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(base + "/")
        await page.fill('input[name="u"]', "admin")
        await page.fill('input[name="p"]', "admin123")
        await page.click('button[type=submit]')
        await page.wait_for_url("**/app")
        await page.wait_for_selector(".dialog-item")
        items = page.locator(".dialog-item")
        assert await items.count() >= 2
        await page.wait_for_timeout(300)
        await items.nth(0).click()
        await page.wait_for_timeout(400)
        await page.fill("#replyText", "DRAFT_FOR_CLIENT_A")
        await page.dispatch_event("#replyText", "input")
        title_a = (await page.locator("#chatTitle").inner_text()).strip()
        await items.nth(1).click()
        await page.wait_for_timeout(500)
        assert (await page.input_value("#replyText")) == ""
        title_b = (await page.locator("#chatTitle").inner_text()).strip()
        assert title_b != title_a
        await page.fill("#replyText", "DRAFT_FOR_CLIENT_B")
        await page.dispatch_event("#replyText", "input")
        await items.nth(0).click()
        await page.wait_for_timeout(500)
        assert (await page.locator("#chatTitle").inner_text()).strip() == title_a
        assert (await page.input_value("#replyText")) == "DRAFT_FOR_CLIENT_A"
        drafts = await page.evaluate(
            """() => {
              const k = Object.keys(localStorage).find((x) => x.startsWith('home24_drafts_'));
              return k ? JSON.parse(localStorage.getItem(k) || '{}') : {};
            }"""
        )
        assert any(v == "DRAFT_FOR_CLIENT_A" for v in drafts.values())
        assert any(v == "DRAFT_FOR_CLIENT_B" for v in drafts.values())
        await browser.close()


def main() -> int:
    port = int(os.environ.get("TEST_DASH_PORT", "43141"))
    data = Path(f"/tmp/h24_draft_test_{port}")
    if data.exists():
        import shutil

        shutil.rmtree(data)
    data.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME24_DASHBOARD_DEMO": "1",
            "DASHBOARD_PORT": str(port),
            "DASHBOARD_HOST": "[REDACTED]",
            "DATABASE_PATH": str(data / "home24.db"),
            "MANAGERS_PATH": str(data / "managers.json"),
            "DASHBOARD_USERS_PATH": str(data / "users.json"),
            "TG_ACCOUNTS_PATH": str(data / "tg_accounts.json"),
            "DASHBOARD_ADMIN_USERNAME": "admin",
            "DASHBOARD_ADMIN_PASSWORD": "admin123",
            "DASHBOARD_ADMIN_MUST_CHANGE": "0",
            "DASHBOARD_SECRET": "draft-test-secret",
            "TELEGRAM_SESSION": "",
            "MANAGER_PHONE": "",
            "PYTHONPATH": str(ROOT),
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "bot.dashboard.app"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_port("[REDACTED]", port)
        asyncio.run(_run(f"http://[REDACTED]:{port}"))
        print("test_dashboard_drafts OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
