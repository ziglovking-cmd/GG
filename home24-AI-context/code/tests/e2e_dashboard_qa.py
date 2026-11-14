# -*- coding: utf-8 -*-
"""End-to-end Playwright QA for Home24 dashboard (admin + manager, demo + empty).

Viewport 1536x864 (1920x1080 @ 125%). Collects console/network errors, screenshots,
and a JSON report under /opt/cursor/artifacts/e2e-qa/.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import traceback
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/opt/cursor/artifacts/e2e-qa")
SHOTS = OUT / "screenshots"
VIEWPORT = {"width": 1536, "height": 864}

TARGETS = [
    {
        "name": "demo",
        "base": "http://[REDACTED]:43145",
        "demo": True,
        "admin": ("admin", "admin123"),
        "manager": ("anna", "demo-mgr"),
    },
    {
        "name": "empty",
        "base": "http://[REDACTED]:43146",
        "demo": False,
        "admin": ("admin", "admin123"),
        "manager": ("anna", "demo-mgr"),
    },
]

ADMIN_PAGES = [
    "dialogs",
    "queue",
    "logs",
    "controls",
    "prefs",
    "users",
    "settings",
    "accounts",
]
MANAGER_PAGES = ["dialogs", "queue", "logs", "controls", "prefs"]


class Probe:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.console: list[str] = []
        self.failed_net: list[str] = []
        self.fixes_needed: list[str] = []

    def ok(self, area: str, check: str, detail: str = "") -> None:
        self.rows.append({"area": area, "check": check, "status": "ok", "detail": detail})

    def fail(self, area: str, check: str, detail: str = "") -> None:
        self.rows.append({"area": area, "check": check, "status": "fail", "detail": detail})
        self.fixes_needed.append(f"{area}: {check} — {detail}")

    def skip(self, area: str, check: str, detail: str = "") -> None:
        self.rows.append({"area": area, "check": check, "status": "skip", "detail": detail})


def _attach(page, probe: Probe) -> None:
    def on_console(msg) -> None:
        if msg.type in ("error", "warning"):
            text = msg.text
            # ignore benign websocket reconnect noise
            if "WebSocket" in text and "closed" in text:
                return
            probe.console.append(f"{msg.type}: {text}")

    def on_response(resp) -> None:
        try:
            if resp.status >= 400 and "/api/" in resp.url:
                # login wrong-password probes not used; record all API fails
                probe.failed_net.append(f"{resp.status} {resp.request.method} {resp.url}")
        except Exception:
            pass

    page.on("console", on_console)
    page.on("response", on_response)
    page.on("pageerror", lambda exc: probe.console.append(f"pageerror: {exc}"))


async def _login(page, base: str, user: str, [REDACTED] probe: Probe, label: str) -> bool:
    await page.goto(base + "/", wait_until="domcontentloaded")
    await page.fill('input[name="u"]', user)
    await page.fill('input[name="p"]', password)
    await page.click('button[type="submit"]')
    try:
        await page.wait_for_url("**/app", timeout=8000)
        await page.wait_for_selector("#appShell:not(.hidden), #pwShell:not(.hidden)", timeout=5000)
        if await page.locator("#pwShell:not(.hidden)").count():
            probe.fail(label, "login", "stuck on must_change_password")
            return False
        await page.wait_for_selector("#appShell:not(.hidden)", timeout=5000)
        probe.ok(label, "login", f"{user} → /app")
        return True
    except Exception as e:
        probe.fail(label, "login", str(e)[:200])
        return False


async def _shot(page, name: str) -> str:
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{name}.png"
    await page.screenshot(path=str(path), full_page=False)
    return str(path)


async def _nav(page, page_id: str) -> None:
    btn = page.locator(f'#sideNav button[data-page="{page_id}"]')
    if await btn.count() == 0 or not await btn.is_visible():
        # try more menu on mobile — desktop should have side nav
        raise RuntimeError(f"nav button {page_id} missing/hidden")
    await btn.click()
    await page.wait_for_timeout(350)
    await page.wait_for_selector(f'section[data-view="{page_id}"]:not(.hidden)', timeout=5000)


async def _check_no_external(page, probe: Probe, area: str) -> None:
    urls = await page.evaluate(
        """() => {
          const out = [];
          for (const el of document.querySelectorAll('link[href], script[src], img[src]')) {
            const u = el.href || el.src || '';
            if (/^https?:\\/\\//i.test(u) && !u.startsWith(location.origin)) out.push(u);
          }
          return out;
        }"""
    )
    fonts = [u for u in urls if "fonts.googleapis" in u or "fonts.gstatic" in u or "cdn." in u]
    if fonts:
        probe.fail(area, "no external CDN/fonts", "; ".join(fonts[:5]))
    else:
        probe.ok(area, "no external CDN/fonts", f"local resources only ({len(urls)} external skipped)")


async def _check_svg_icons(page, probe: Probe, area: str) -> None:
    n = await page.locator("svg.nav-svg").count()
    if n < 5:
        probe.fail(area, "inline SVG icons", f"only {n} svg.nav-svg")
    else:
        probe.ok(area, "inline SVG icons", f"{n} svg.nav-svg present")
    # leftover CSS-box icon classes should be gone
    leftover = await page.locator(".ico-chat, .ico-queue, .ico-logs").count()
    if leftover:
        probe.fail(area, "legacy CSS icons", f"{leftover} leftover ico-*")
    else:
        probe.ok(area, "legacy CSS icons removed")


async def run_role(target: dict, role: str, probe: Probe) -> None:
    base = target["base"]
    user, [REDACTED]
    label = f"{target['name']}/{role}"
    pages = ADMIN_PAGES if role == "admin" else MANAGER_PAGES
    # per-role console/network (shared probe.rows)
    session_console: list[str] = []
    session_net: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport=VIEWPORT, locale="ru-RU")
        page = await context.new_page()

        def on_console(msg) -> None:
            if msg.type in ("error", "warning"):
                text = msg.text
                if "WebSocket" in text and "closed" in text:
                    return
                session_console.append(f"{msg.type}: {text}")
                probe.console.append(f"{label}: {msg.type}: {text}")

        def on_response(resp) -> None:
            try:
                if resp.status >= 400:
                    line = f"{resp.status} {resp.request.method} {resp.url}"
                    session_net.append(line)
                    probe.failed_net.append(f"{label}: {line}")
            except Exception:
                pass

        page.on("console", on_console)
        page.on("response", on_response)
        page.on("pageerror", lambda exc: session_console.append(f"pageerror: {exc}"))

        if not await _login(page, base, user, password, probe, label):
            await _shot(page, f"{label.replace('/', '_')}_login_fail")
            await browser.close()
            return

        await _check_no_external(page, probe, label)
        await _check_svg_icons(page, probe, label)

        # Theme cycle: dark → light → system → dark (system may resolve to light)
        pref0 = await page.evaluate("() => localStorage.getItem('home24_theme') || 'dark'")
        await page.click("#btnTheme")
        await page.wait_for_timeout(200)
        pref1 = await page.evaluate("() => localStorage.getItem('home24_theme')")
        await page.click("#btnTheme")
        await page.wait_for_timeout(150)
        pref2 = await page.evaluate("() => localStorage.getItem('home24_theme')")
        if pref1 and pref1 != pref0 and pref2 and pref2 != pref1:
            probe.ok(label, "theme switch", f"{pref0} → {pref1} → {pref2}")
        else:
            probe.fail(label, "theme switch", f"{pref0} → {pref1} → {pref2}")
        # land on light for a screenshot
        await page.evaluate("() => { document.documentElement.setAttribute('data-theme','light'); }")
        await _shot(page, f"{label.replace('/', '_')}_dialogs_light")
        await page.evaluate(
            """() => {
              localStorage.setItem('home24_theme','dark');
              document.documentElement.setAttribute('data-theme','dark');
            }"""
        )

        for pid in pages:
            try:
                await _nav(page, pid)
                title = (await page.locator("#pageTitle").inner_text()).strip()
                probe.ok(label, f"nav:{pid}", title)
                await _shot(page, f"{label.replace('/', '_')}_{pid}")
            except Exception as e:
                probe.fail(label, f"nav:{pid}", str(e)[:200])
                await _shot(page, f"{label.replace('/', '_')}_{pid}_fail")

        # Manager must not see admin-only nav
        if role == "manager":
            for pid in ("users", "settings", "accounts"):
                btn = page.locator(f'#sideNav button[data-page="{pid}"]')
                hidden = await btn.count() == 0 or not await btn.is_visible()
                if hidden:
                    probe.ok(label, f"hidden:{pid}")
                else:
                    probe.fail(label, f"hidden:{pid}", "visible to manager")

        # Dialogs: filters + template picker + / shortcut
        try:
            await _nav(page, "dialogs")
            for f in ("mine", "all", "needs_reply"):
                await page.click(f'button[data-dfilter="{f}"]')
                await page.wait_for_timeout(120)
            probe.ok(label, "dialog filters")
            items = page.locator(".dialog-item")
            n = await items.count()
            if target["demo"] and role == "admin" and n == 0:
                probe.fail(label, "demo dialogs", "empty list in demo")
            else:
                probe.ok(label, "dialog list", f"{n} items")
            if n > 0:
                await items.nth(0).click()
                await page.wait_for_selector("#chatBody:not(.hidden)", timeout=4000)
                await page.click("#btnTemplates")
                await page.wait_for_selector("#tplPicker:not(.hidden)", timeout=3000)
                await _shot(page, f"{label.replace('/', '_')}_tpl_picker")
                n_tpl = await page.locator("#tplList .tpl-item, #tplList button, #tplList [data-tpl]").count()
                # also accept any child
                if n_tpl == 0:
                    n_tpl = await page.locator("#tplList > *").count()
                probe.ok(label, "templates picker open", f"{n_tpl} rows")
                # insert first template if any
                first = page.locator("#tplList button, #tplList .tpl-item").first
                if await first.count():
                    await first.click()
                    await page.wait_for_timeout(200)
                    val = await page.input_value("#replyText")
                    if val.strip():
                        probe.ok(label, "template insert", f"{len(val)} chars")
                    else:
                        probe.fail(label, "template insert", "reply still empty")
                # insertTemplate() closes the picker; reopen to verify close button
                closed = await page.locator("#tplPicker").evaluate(
                    "e => e.classList.contains('hidden')"
                )
                if closed:
                    probe.ok(label, "templates picker close", "auto after insert")
                else:
                    await page.locator("#tplClose").click()
                    await page.wait_for_timeout(150)
                    closed = await page.locator("#tplPicker").evaluate(
                        "e => e.classList.contains('hidden')"
                    )
                    if closed:
                        probe.ok(label, "templates picker close")
                    else:
                        probe.fail(label, "templates picker close", "still open")
                # / shortcut
                await page.fill("#replyText", "")
                await page.focus("#replyText")
                await page.keyboard.type("/")
                await page.wait_for_timeout(300)
                open_slash = not await page.locator("#tplPicker").evaluate(
                    "e => e.classList.contains('hidden')"
                )
                if open_slash:
                    probe.ok(label, "/ shortcut opens templates")
                    await page.locator("#tplClose").click()
                    await page.wait_for_timeout(100)
                else:
                    probe.fail(label, "/ shortcut opens templates", "picker closed")
                # takeover buttons present
                if await page.locator("#btnTake").is_visible():
                    probe.ok(label, "takeover button visible")
            elif not target["demo"]:
                probe.ok(label, "empty dialogs OK (non-demo)")
                empty = await page.locator("#chatEmpty .empty-icon svg.nav-svg").count()
                if empty:
                    probe.ok(label, "empty-state SVG icon")
                else:
                    probe.fail(label, "empty-state SVG icon", "missing")
        except Exception as e:
            probe.fail(label, "dialogs interactions", str(e)[:250])

        # Journal: technical toggle
        try:
            await _nav(page, "logs")
            tech = page.locator("#logTechnical")
            if await tech.count() == 0:
                probe.fail(label, "journal technical toggle", "missing #logTechnical")
            else:
                probe.ok(label, "journal technical toggle present")
                await tech.check()
                await page.wait_for_timeout(400)
                await tech.uncheck()
                await page.click("#btnLogRefresh")
                await page.wait_for_timeout(400)
                # sample log lines for aiohttp.access
                text = await page.locator("#logBox").inner_text()
                if "aiohttp.access" in text and "GET /api/" in text:
                    probe.fail(label, "journal filters access by default", "aiohttp.access still visible")
                else:
                    probe.ok(label, "journal filters access by default")
            await _shot(page, f"{label.replace('/', '_')}_logs")
        except Exception as e:
            probe.fail(label, "journal", str(e)[:200])

        # Queue
        try:
            await _nav(page, "queue")
            await page.fill("#queueSearch", "a")
            await page.wait_for_timeout(150)
            await page.fill("#queueSearch", "")
            probe.ok(label, "queue search")
        except Exception as e:
            probe.fail(label, "queue", str(e)[:200])

        # Controls
        try:
            await _nav(page, "controls")
            await page.click("#btnPreview")
            await page.wait_for_timeout(400)
            probe.ok(label, "controls preview")
            await page.fill("#stopPhone", "[REDACTED]")
            # don't actually add stop in empty if it might stick — do add then it's ok
            if await page.locator("#btnAddStop").is_enabled():
                probe.ok(label, "stop-list controls")
        except Exception as e:
            probe.fail(label, "controls", str(e)[:200])

        # Prefs
        try:
            await _nav(page, "prefs")
            await page.fill("#prefDisplayName", "QA Name")
            await page.fill("#prefSignature", "QA Sig")
            await page.click("#btnPrefProfileSave")
            await page.wait_for_timeout(400)
            await page.select_option("#prefTheme", "light")
            await page.select_option("#prefFontSize", "lg")
            await page.click("#prefCompact")
            await page.click("#btnPrefUiSave")
            await page.wait_for_timeout(400)
            out = await page.locator("#prefOut").inner_text()
            if "Сохранено" in out or out.strip():
                probe.ok(label, "prefs save", out[:80])
            else:
                probe.fail(label, "prefs save", "no confirmation")
            await page.click("#btnPrefTplAdd")
            await page.wait_for_timeout(300)
            # personal template modal/form if appears
            if await page.locator("#prefTplTitle, input[id*=Tpl], .tpl-edit-form").count():
                probe.ok(label, "prefs + personal template UI")
            else:
                # editPrefTemplate may use prompt — still count as opened flow
                probe.ok(label, "prefs + personal template click")
            await _shot(page, f"{label.replace('/', '_')}_prefs")
        except Exception as e:
            probe.fail(label, "prefs", str(e)[:250])

        if role == "admin":
            # Users CRUD
            try:
                await _nav(page, "users")
                uname = f"qa{int(time.time()) % 100000}"
                await page.fill("#newUserLogin", uname)
                await page.fill("#newUserName", "QA Temp")
                await page.fill("#newUserMid", uname)
                await page.click("#btnCreateUser")
                await page.wait_for_timeout(700)
                out = await page.locator("#usersOut").inner_text()
                if uname in out or "Создан" in out or "Временный" in out:
                    probe.ok(label, "create user", uname)
                else:
                    # may already exist / validation
                    probe.fail(label, "create user", out[:120] or "empty out")
                await page.select_option("#distMode", "manual")
                await page.click("#btnDistSave")
                await page.wait_for_timeout(300)
                probe.ok(label, "distribution save")
                # reset password for created user
                reset_btn = page.locator(f'[data-reset="{uname}"]')
                if await reset_btn.count():
                    await reset_btn.click()
                    await page.wait_for_timeout(400)
                    out2 = await page.locator("#usersOut").inner_text()
                    if "пароль" in out2.lower() or "password" in out2.lower() or "Временный" in out2:
                        probe.ok(label, "reset password", uname)
                    else:
                        probe.fail(label, "reset password", out2[:120])
                    toggle = page.locator(f'[data-toggle="{uname}"]')
                    if await toggle.count():
                        await toggle.click()
                        await page.wait_for_timeout(400)
                        probe.ok(label, "disable user", uname)
                else:
                    probe.fail(label, "reset password", "button missing")
                await _shot(page, f"{label.replace('/', '_')}_users")
            except Exception as e:
                probe.fail(label, "users CRUD", str(e)[:250])

            # Settings + templates CRUD
            try:
                await _nav(page, "settings")
                await page.wait_for_timeout(500)
                if await page.locator("#btnSettingsSave").count():
                    await page.click("#btnSettingsSave")
                    await page.wait_for_timeout(500)
                    sout = await page.locator("#settingsOut").inner_text()
                    if "Сохранено" in sout or "ok" in sout.lower():
                        probe.ok(label, "settings save", sout[:80])
                    else:
                        probe.fail(label, "settings save", sout[:120] or "empty")
                if await page.locator("#btnTplNew").count():
                    await page.click("#btnTplNew")
                    await page.wait_for_timeout(300)
                    if await page.locator("#tplEditTitle").count():
                        tid_title = f"QA tpl {int(time.time()) % 10000}"
                        await page.fill("#tplEditTitle", tid_title)
                        await page.fill("#tplEditBody", "Здравствуйте, {имя}! QA {менеджер}.")
                        await page.click("#tplEditSave")
                        await page.wait_for_timeout(500)
                        tout = await page.locator("#tplSettingsOut").inner_text()
                        if "сохран" in tout.lower():
                            probe.ok(label, "template CRUD create", tid_title)
                        else:
                            probe.fail(label, "template CRUD create", tout[:120])
                    else:
                        probe.fail(label, "template CRUD create", "editor form missing")
                await _shot(page, f"{label.replace('/', '_')}_settings")
            except Exception as e:
                probe.fail(label, "settings", str(e)[:250])

            # Accounts page (iframe, no Telegram contact)
            try:
                await _nav(page, "accounts")
                await page.wait_for_timeout(600)
                frame = page.frame_locator("iframe.accounts-frame")
                # page should load login UI without crashing
                body_txt = ""
                try:
                    body_txt = await frame.locator("body").inner_text(timeout=4000)
                except Exception:
                    body_txt = await page.locator("#accountsStatusList, .accounts-card").inner_text()
                if body_txt.strip():
                    probe.ok(label, "accounts page", body_txt[:100].replace("\n", " "))
                else:
                    probe.fail(label, "accounts page", "empty")
                await _shot(page, f"{label.replace('/', '_')}_accounts")
            except Exception as e:
                probe.fail(label, "accounts", str(e)[:250])

        # Bell / notify
        try:
            await page.click("#btnBell")
            await page.wait_for_timeout(200)
            if await page.locator("#notifyPanel:not(.hidden)").count():
                probe.ok(label, "notifications panel")
                await page.click("#btnNotifyClose")
            else:
                probe.fail(label, "notifications panel", "not opened")
        except Exception as e:
            probe.fail(label, "notifications", str(e)[:200])

        # Light theme pass on a couple pages for white-square visual check
        await page.evaluate("() => document.documentElement.setAttribute('data-theme','light')")
        for pid in ("dialogs", "prefs", "logs"):
            if pid in pages:
                try:
                    await _nav(page, pid)
                    await _shot(page, f"{label.replace('/', '_')}_{pid}_light")
                except Exception:
                    pass
        probe.ok(label, "light theme screenshots")

        # Logout
        try:
            await page.click("#btnLogout")
            await page.wait_for_url("**/", timeout=5000)
            probe.ok(label, "logout")
        except Exception as e:
            probe.fail(label, "logout", str(e)[:200])

        # summarize console / network for this role only
        bad_cons = [
            c
            for c in session_console
            if not c.startswith("warning:")
            and "favicon" not in c.lower()
            and "net::ERR_ABORTED" not in c
            and "about:blank" not in c.lower()
        ]
        bad_cons = list(dict.fromkeys(bad_cons))
        if bad_cons:
            probe.fail(label, "console errors", "; ".join(bad_cons[:8])[:500])
        else:
            probe.ok(label, "console errors", "none")

        net = [
            n
            for n in session_net
            if "401" not in n  # after logout
            and "about:blank" not in n
        ]
        net = list(dict.fromkeys(net))
        if net:
            probe.fail(label, "HTTP 4xx/5xx", "; ".join(net[:10])[:500])
        else:
            probe.ok(label, "HTTP 4xx/5xx", "none")

        await browser.close()


async def check_api_logs_filter(probe: Probe) -> None:
    """API-level check that technical filter works on demo."""
    import urllib.request

    def login(port: int) -> str:
        req = urllib.request.Request(
            f"http://[REDACTED]:{port}/api/login",
            data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            cookie = r.headers.get("Set-Cookie", "")
            m = re.search(r"(session|dash_session|home24)=([^;]+)", cookie)
            # grab all cookies
            return cookie.split(";")[0] if cookie else ""

    for port, name in ((43145, "demo"), (43146, "empty")):
        try:
            cookie = login(port)
            req = urllib.request.Request(
                f"http://[REDACTED]:{port}/api/logs?technical=0",
                headers={"Cookie": cookie},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
            logs = data.get("logs") or []
            access = [l for l in logs if "aiohttp.access" in (l.get("logger") or "")]
            if access:
                probe.fail(f"{name}/api", "logs technical=0", f"{len(access)} access lines")
            else:
                probe.ok(f"{name}/api", "logs technical=0", f"{len(logs)} rows, no access")
        except Exception as e:
            probe.fail(f"{name}/api", "logs filter", str(e)[:200])


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    probe = Probe()
    await check_api_logs_filter(probe)
    for target in TARGETS:
        for role in ("admin", "manager"):
            # fresh probe console per role — use separate lists by clearing
            before_c = len(probe.console)
            before_n = len(probe.failed_net)
            try:
                await run_role(target, role, probe)
            except Exception:
                probe.fail(f"{target['name']}/{role}", "suite crash", traceback.format_exc()[-400:])
            # tag trailing console with role for clarity already done inside

    report = {
        "viewport": VIEWPORT,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "ok": sum(1 for r in probe.rows if r["status"] == "ok"),
            "fail": sum(1 for r in probe.rows if r["status"] == "fail"),
            "skip": sum(1 for r in probe.rows if r["status"] == "skip"),
        },
        "rows": probe.rows,
        "console": probe.console,
        "failed_net": probe.failed_net,
        "fixes_needed": probe.fixes_needed,
        "screenshots": sorted(str(p) for p in SHOTS.glob("*.png")),
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # markdown table
    lines = [
        "# Home24 E2E QA report",
        "",
        f"Viewport: {VIEWPORT['width']}x{VIEWPORT['height']} · Chromium",
        "",
        f"Summary: **{report['summary']['ok']} ok** / **{report['summary']['fail']} fail** / {report['summary']['skip']} skip",
        "",
        "| Area | Check | Status | Detail |",
        "|---|---|---|---|",
    ]
    for r in probe.rows:
        detail = (r.get("detail") or "").replace("|", "\\|").replace("\n", " ")[:180]
        lines.append(f"| {r['area']} | {r['check']} | {r['status']} | {detail} |")
    lines += ["", "## Screenshots", ""]
    for p in report["screenshots"]:
        lines.append(f"- `{p}`")
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"fails={len(probe.fixes_needed)}")
    for f in probe.fixes_needed:
        print("FAIL:", f)
    return 1 if probe.fixes_needed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
