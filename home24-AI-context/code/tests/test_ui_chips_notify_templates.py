# -*- coding: utf-8 -*-
"""QA: filter chips readable offline + templates fetch at 1536x864 (no CDN)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/opt/cursor/artifacts/e2e-qa/ui_fix")


def _wait_port(host: str, port: int, timeout: float = 25.0) -> None:
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
    raise RuntimeError(f"not up {host}:{port}")


def _luminance(rgb: str) -> float:
    """Rough relative luminance from rgb()/rgba() string."""
    import re

    m = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", rgb or "")
    if not m:
        return 0.0
    r, g, b = (int(m.group(i)) / 255.0 for i in (1, 2, 3))

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    R, G, B = f(r), f(g), f(b)
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


async def _run(base: str) -> dict:
    from playwright.async_api import async_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    fails: list[str] = []
    ok_rows: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1536, "height": 864})

        async def route_handler(route):
            url = route.request.url
            if url.startswith("http") and "[REDACTED]" not in url and "localhost" not in url:
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", route_handler)
        page = await context.new_page()
        external_hits: list[str] = []
        page.on(
            "requestfailed",
            lambda r: external_hits.append(r.url)
            if "[REDACTED]" not in r.url and r.url.startswith("http")
            else None,
        )
        tpl_reqs: list[str] = []
        page.on(
            "request",
            lambda r: tpl_reqs.append(r.url) if "/api/templates" in r.url else None,
        )

        await page.goto(base + "/")
        await page.fill('input[name="u"]', "admin")
        await page.fill('input[name="p"]', "admin123")
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/app")
        await page.wait_for_timeout(700)

        # Force dark theme (user screenshot)
        await page.evaluate(
            """() => {
              document.documentElement.setAttribute('data-theme','dark');
              localStorage.setItem('home24_theme','dark');
            }"""
        )
        await page.wait_for_timeout(100)

        chips = page.locator("#dialogFilterBar .filter-chip, #dialogFilterBar button")
        n = await chips.count()
        if n < 3:
            fails.append(f"filter chips count {n}")
        texts = []
        for i in range(await chips.count()):
            t = (await chips.nth(i).inner_text()).strip()
            texts.append(t)
            st = await chips.nth(i).evaluate(
                """(el) => {
                  const s = getComputedStyle(el);
                  return {color: s.color, bg: s.backgroundColor, text: el.textContent.trim()};
                }"""
            )
            # must have visible label
            if not st["text"]:
                fails.append(f"chip {i} empty text")
            # background must not be near-white while text is near-white
            bg_l = _luminance(st["bg"])
            fg_l = _luminance(st["color"])
            contrast = (max(bg_l, fg_l) + 0.05) / (min(bg_l, fg_l) + 0.05)
            if bg_l > 0.85 and fg_l > 0.7:
                fails.append(f"chip {i} white-on-white bg={st['bg']} fg={st['color']}")
            elif contrast < 2.5:
                fails.append(
                    f"chip {i} low contrast {contrast:.2f} bg={st['bg']} fg={st['color']}"
                )
            else:
                ok_rows.append(f"chip '{st['text']}' contrast={contrast:.2f}")

        if "Мои" not in texts or "Все" not in texts:
            fails.append(f"chip labels missing: {texts}")
        else:
            ok_rows.append(f"labels ok: {texts}")

        await page.screenshot(path=str(OUT / "chips_dark.png"))

        # light theme too
        await page.evaluate(
            """() => document.documentElement.setAttribute('data-theme','light')"""
        )
        await page.wait_for_timeout(100)
        for i in range(await chips.count()):
            st = await chips.nth(i).evaluate(
                """(el) => {
                  const s = getComputedStyle(el);
                  return {color: s.color, bg: s.backgroundColor, text: el.textContent.trim()};
                }"""
            )
            bg_l = _luminance(st["bg"])
            fg_l = _luminance(st["color"])
            contrast = (max(bg_l, fg_l) + 0.05) / (min(bg_l, fg_l) + 0.05)
            if contrast < 2.5:
                fails.append(f"light chip {i} low contrast {contrast:.2f}")
        await page.screenshot(path=str(OUT / "chips_light.png"))
        await page.evaluate(
            """() => document.documentElement.setAttribute('data-theme','dark')"""
        )

        # Templates (notify dropdown is out of scope — user opens it on purpose)
        await page.locator(".dialog-item").first.click()
        await page.wait_for_selector("#chatBody:not(.hidden)")
        await page.wait_for_timeout(300)
        before = len(tpl_reqs)
        await page.click("#btnTemplates")
        await page.wait_for_timeout(700)
        open_tpl = not await page.locator("#tplPicker").evaluate(
            "e => e.classList.contains('hidden')"
        )
        if not open_tpl:
            fails.append("templates picker did not open")
        else:
            ok_rows.append("templates picker opens")
        if len(tpl_reqs) <= before:
            fails.append("no /api/templates after Шаблоны click")
        else:
            ok_rows.append(f"templates fetched: {tpl_reqs[-1]}")
        await page.screenshot(path=str(OUT / "templates_open.png"))
        await page.keyboard.press("Escape")
        await page.fill("#replyText", "")
        await page.focus("#replyText")
        before2 = len(tpl_reqs)
        await page.keyboard.press("/")
        await page.wait_for_timeout(500)
        open_slash = not await page.locator("#tplPicker").evaluate(
            "e => e.classList.contains('hidden')"
        )
        if not open_slash:
            fails.append("slash did not open templates")
        else:
            ok_rows.append("slash opens templates")
        if len(tpl_reqs) <= before2:
            ok_rows.append("slash open (fetch may be cached from prior)")
        await page.screenshot(path=str(OUT / "templates_slash.png"))

        # no external CDN should have been requested successfully
        # (aborted is fine)
        ok_rows.append(f"blocked external attempts: {len(external_hits)}")

        await browser.close()

    return {"ok": not fails, "fails": fails, "ok_rows": ok_rows}


def main() -> int:
    port = int(os.environ.get("TEST_UI_PORT", "43148"))
    data = Path(f"/tmp/h24_ui_fix_{port}")
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME24_DASHBOARD_DEMO": "1",
            "DASHBOARD_PORT": str(port),
            "DASHBOARD_HOST": "[REDACTED]",
            "HOME24_LOGIN_PORT": str(port),
            "DATABASE_PATH": str(data / "home24.db"),
            "MANAGERS_PATH": str(data / "managers.json"),
            "DASHBOARD_USERS_PATH": str(data / "users.json"),
            "TG_ACCOUNTS_PATH": str(data / "tg_accounts.json"),
            "TEMPLATES_PATH": str(data / "templates.json"),
            "USER_PREFS_PATH": str(data / "user_prefs.json"),
            "DASHBOARD_ADMIN_USERNAME": "admin",
            "DASHBOARD_ADMIN_PASSWORD": "admin123",
            "DASHBOARD_ADMIN_MUST_CHANGE": "0",
            "DASHBOARD_SECRET": "ui-fix-secret",
            "PYTHONPATH": str(ROOT),
            "HOME24_LOCKS_DIR": str(data / "locks"),
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
        report = asyncio.run(_run(f"http://[REDACTED]:{port}"))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
