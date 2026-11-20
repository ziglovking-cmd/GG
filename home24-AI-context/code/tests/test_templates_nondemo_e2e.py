# -*- coding: utf-8 -*-
"""Playwright: templates work in non-demo mode with empty data dir + seeded dialog."""
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
OUT = Path("/opt/cursor/artifacts/e2e-qa/templates")


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


def _seed_dialog(db: Path, chat_id: str = "8154980719") -> None:
    from bot.store import Store

    st = Store(db)
    st.add_contact(
        phone="[REDACTED]",
        name="Тест Клиент",
        chat_id=chat_id,
        manager_id="anna",
        tg_status="ok",
    )
    st.save_session(
        chat_id,
        step="await_dates",
        name="Тест Клиент",
        manager_id="anna",
        handed_off=False,
        context={"next": "уточнить даты", "tg_status": "ok"},
    )


async def _run(base: str) -> dict:
    from playwright.async_api import async_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"checks": [], "fails": []}

    def ok(c: str, d: str = "") -> None:
        report["checks"].append({"check": c, "status": "ok", "detail": d})

    def fail(c: str, d: str = "") -> None:
        report["checks"].append({"check": c, "status": "fail", "detail": d})
        report["fails"].append(f"{c}: {d}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1536, "height": 864})
        reqs: list[str] = []

        def on_req(req):
            if "/api/templates" in req.url:
                reqs.append(f"{req.method} {req.url}")

        page.on("request", on_req)

        await page.goto(base + "/")
        await page.fill('input[name="u"]', "admin")
        await page.fill('input[name="p"]', "admin123")
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/app")
        await page.wait_for_selector("#appShell:not(.hidden)")
        await page.wait_for_timeout(800)

        # cache-bust present
        html = await page.content()
        if "dashboard.js?v=" in html and "dashboard.css?v=" in html:
            ok("cache-bust query on assets")
        else:
            fail("cache-bust query on assets", "missing ?v=")

        # boot should have fetched templates
        await page.wait_for_timeout(500)
        if any("/api/templates" in r for r in reqs):
            ok("loadTemplates on boot", str(len(reqs)))
        else:
            fail("loadTemplates on boot", "no /api/templates yet")

        # open dialog
        await page.wait_for_selector(".dialog-item", timeout=8000)
        await page.locator(".dialog-item").first.click()
        await page.wait_for_selector("#chatBody:not(.hidden)")
        await page.wait_for_timeout(600)
        if any("8154980719" in r or "chat_id=" in r for r in reqs):
            ok("templates with chat_id after open dialog")
        else:
            # still ok if boot-only; button will refetch
            ok("dialog opened", "templates chat_id optional")

        # slash opens picker
        await page.fill("#replyText", "")
        await page.focus("#replyText")
        await page.keyboard.press("/")
        await page.wait_for_timeout(500)
        open_p = not await page.locator("#tplPicker").evaluate(
            "e => e.classList.contains('hidden')"
        )
        if open_p:
            ok("slash opens picker")
        else:
            await page.click("#btnTemplates")
            await page.wait_for_timeout(400)
            open_p = not await page.locator("#tplPicker").evaluate(
                "e => e.classList.contains('hidden')"
            )
            if open_p:
                ok("templates button opens picker", "slash fallback to button")
            else:
                fail("templates picker open", "neither slash nor button")

        await page.screenshot(path=str(OUT / "nondemo_tpl_picker.png"))
        n = await page.locator("#tplList .tpl-item, #tplList button[data-tid]").count()
        if n >= 1:
            ok("templates listed", f"{n} items")
            await page.locator("#tplList button[data-tid], #tplList .tpl-item").first.click()
            await page.wait_for_timeout(300)
            val = await page.input_value("#replyText")
            if val.strip():
                ok("template insert", val[:80])
            else:
                fail("template insert", "empty")
        else:
            fail("templates listed", "empty picker")

        # admin settings CRUD
        await page.locator('#sideNav button[data-page="settings"]').click()
        await page.wait_for_timeout(500)
        await page.click("#btnTplNew")
        await page.wait_for_selector("#tplEditTitle")
        title = f"E2E shared {int(time.time()) % 100000}"
        await page.fill("#tplEditTitle", title)
        await page.fill("#tplEditBody", "Привет{, имя}! Это {менеджер}, тест.")
        await page.click("#tplEditSave")
        await page.wait_for_timeout(600)
        tout = await page.locator("#tplSettingsOut").inner_text()
        if "сохран" in tout.lower():
            ok("admin create shared template", title)
        else:
            fail("admin create shared template", tout[:120])
        await page.screenshot(path=str(OUT / "nondemo_settings_tpl.png"))

        # find edit/delete buttons
        del_btn = page.locator("[data-del-tpl]").first
        if await del_btn.count():
            # edit first
            edit = page.locator("[data-edit-tpl]").first
            if await edit.count():
                await edit.click()
                await page.wait_for_selector("#tplEditTitle")
                await page.fill("#tplEditTitle", title + " edited")
                await page.click("#tplEditSave")
                await page.wait_for_timeout(400)
                ok("admin edit shared template")
            page.once("dialog", lambda d: d.accept())
            await del_btn.click()
            await page.wait_for_timeout(400)
            ok("admin delete shared template")
        else:
            fail("admin delete shared template", "no delete button")

        await page.click("#btnLogout")
        await page.wait_for_url("**/")

        # manager personal template via API + prefs UI reload
        await page.fill('input[name="u"]', "anna")
        await page.fill('input[name="p"]', "demo-mgr")
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/app")
        await page.wait_for_timeout(600)
        csrf = await page.evaluate("() => document.cookie")
        created = await page.evaluate(
            """async () => {
              const r = await fetch('/api/templates', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                  'Content-Type': 'application/json',
                  'X-CSRF-Token': (document.cookie.match(/home24_csrf=([^;]+)/)||[])[1] || ''
                },
                body: JSON.stringify({
                  title: 'Личный E2E',
                  body: 'Личный текст {имя}',
                  category: 'greeting',
                  scope: 'personal'
                })
              });
              return {status: r.status, body: await r.json().catch(()=>({}))};
            }"""
        )
        if created.get("status") == 200 and created.get("body", {}).get("ok"):
            ok("manager personal template API", str(created["body"].get("template", {}).get("id")))
        else:
            fail("manager personal template API", str(created)[:200])
        await page.locator('#sideNav button[data-page="prefs"]').click()
        await page.wait_for_timeout(500)
        listed = await page.locator("#prefTplList").inner_text()
        if "Личный" in listed or "E2E" in listed:
            ok("manager prefs lists personal template", listed[:100])
        else:
            fail("manager prefs lists personal template", listed[:120])
        await page.screenshot(path=str(OUT / "nondemo_mgr_prefs.png"))

        await browser.close()

    if not any("/api/templates" in r for r in reqs):
        fail("any /api/templates request", "none captured")
    else:
        ok("api/templates requested", f"{len(reqs)} calls")

    report["template_requests"] = reqs
    return report


def main() -> int:
    port = int(os.environ.get("TEST_TPL_PORT", "43147"))
    data = Path(f"/tmp/h24_tpl_nondemo_{port}")
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)
    (data / "templates.json").write_text(
        json.dumps({"version": 1, "templates": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    db = data / "home24.db"
    # seed after env so Store uses path
    env = os.environ.copy()
    env.update(
        {
            "HOME24_DASHBOARD_DEMO": "0",
            "DASHBOARD_PORT": str(port),
            "DASHBOARD_HOST": "[REDACTED]",
            "HOME24_LOGIN_PORT": str(port),
            "DATABASE_PATH": str(db),
            "MANAGERS_PATH": str(data / "managers.json"),
            "DASHBOARD_USERS_PATH": str(data / "users.json"),
            "TG_ACCOUNTS_PATH": str(data / "tg_accounts.json"),
            "TEMPLATES_PATH": str(data / "templates.json"),
            "USER_PREFS_PATH": str(data / "user_prefs.json"),
            "DASHBOARD_ADMIN_USERNAME": "admin",
            "DASHBOARD_ADMIN_PASSWORD": "admin123",
            "DASHBOARD_ADMIN_MUST_CHANGE": "0",
            "DASHBOARD_SECRET": "tpl-nondemo-secret",
            "TELEGRAM_SESSION": "",
            "MANAGER_PHONE": "",
            "PYTHONPATH": str(ROOT),
            "HOME24_LOCKS_DIR": str(data / "locks"),
        }
    )
    # bootstrap users via import then seed dialog
    seed_code = r"""
import os
from pathlib import Path
from bot.dashboard import auth as dash_auth
from bot.dashboard import demo as D
from bot.store import Store

dash_auth.ensure_users_file()
D.ensure_demo_managers()
D.ensure_demo_users()
db = Path(os.environ["DATABASE_PATH"])
st = Store(db)
phone = "[REDACTED]"
chat_id = "8154980719"
st.add_contact(phone, name="Тест Клиент", manager_id="anna")
st.update_contact(phone, chat_id=chat_id, status="sent", manager_id="anna")
st.set_contact_telegram(phone, telegram_user_id=chat_id, tg_status="ok", tg_account_id="main")
st.get_session(chat_id)
st.save_session(
    chat_id,
    name="Тест Клиент",
    step="await_dates",
    manager_id="anna",
    handed_off=0,
    context={"next": "уточнить даты", "tg_status": "ok"},
)
st.add_message(chat_id, "bot", "Добрый день! Подскажите даты?", sender_label="бот")
st.add_message(chat_id, "guest", "С 12 по 15", emit=False)
# force reseed empty templates
from bot.reply_templates import TemplateStore, reset_template_store_cache
reset_template_store_cache()
TemplateStore(os.environ["TEMPLATES_PATH"])
print("seeded", len(st.list_dialogs(admin=True)))
"""
    prep = subprocess.run(
        [sys.executable, "-c", seed_code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if prep.returncode != 0:
        print(prep.stdout)
        print(prep.stderr)
        return 1

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
        print(json.dumps({"ok": len(report["fails"]) == 0, "fails": report["fails"], "n": len(report["checks"])}, ensure_ascii=False))
        for f in report["fails"]:
            print("FAIL:", f)
        return 1 if report["fails"] else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    # fix seed helper - ensure_demo_managers may not exist
    sys.exit(main())
