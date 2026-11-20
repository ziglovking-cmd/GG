# -*- coding: utf-8 -*-
"""Точка входа Windows: панель + менеджеры → логин при необходимости → бот.

Коды выхода:
  0  — штатно
  42 — сессия отозвана / нет сессии (start.bat открывает логин, без рестарт-шторма)
  иное — ошибка, start.bat перезапустит через паузу
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXIT_SESSION_DEAD = 42


def _setup_logging() -> None:
    # Windows console: без UTF-8 кириллица в ERROR выглядит как mojibake
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        if hasattr(sys.stdout, "buffer"):
            import io

            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
    except Exception:
        pass
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        fh = RotatingFileHandler(
            log_dir / "bot.log",
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in root.handlers
    ):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.server").setLevel(logging.WARNING)
    logging.getLogger("telethon.network").setLevel(logging.WARNING)
    logging.getLogger("telethon.client.updates").setLevel(logging.WARNING)


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


def _sessions_present_no_connect() -> bool:
    """Есть ли живые слоты в tg_accounts без TCP-подключения (безопасно при логине)."""
    from bot.session_blacklist import is_blacklisted
    from bot.tg_accounts import get_tg_accounts

    tg = get_tg_accounts()
    tg.load()
    for a in tg.unique_ready_ok():
        sess = (a.session or "").strip()
        if sess and not is_blacklisted(sess) and a.status == "ok":
            return True
    return False


async def _probe_sessions_once() -> bool:
    """Проверка без TCP.

    Раньше здесь открывался клиент, сразу закрывался, и следом бот
    подключался тем же ключом. Telegram видел два входа и отзывал
    аккаунт (AuthKeyDuplicated) — снаружи это выглядело как «вылетает
    каждую неделю», особенно после перезагрузки сервера.
    Живость сессии проверяет единственный клиент в bot.main.
    """
    from bot.tg_accounts import get_tg_accounts

    log = logging.getLogger("home24")
    tg = get_tg_accounts()
    for account in tg.ready_with_session():
        try:
            tg.freeze_device_fingerprint(account.id)
        except Exception:
            log.debug("freeze device %s", account.id, exc_info=True)
    return _sessions_present_no_connect()


async def _open_dashboard_until_ready() -> bool:
    """Показать панель (Accounts) пока не появится сессия в tg_accounts.

    Не подключаемся к Telegram в цикле ожидания — иначе гонка с login-клиентом.
    """
    from aiohttp import web

    from bot.dashboard.app import HOST, PORT, create_dashboard_app

    app = create_dashboard_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    url = f"http://{'[REDACTED]' if HOST == '0.0.0.0' else HOST}:{PORT}/"
    print(f"Панель Home24: {url}  (Аккаунты → вход Telegram)", flush=True)
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass
    for _ in range(600):  # ~10 мин
        await asyncio.sleep(1)
        # только чтение файла — без второго TCP к Telegram
        if _sessions_present_no_connect():
            await runner.cleanup()
            return True
    await runner.cleanup()
    return False


async def _run_bot_with_dashboard() -> None:
    """Дашборд и боты менеджеров в одном event loop."""
    from aiohttp import web

    from bot.dashboard.app import HOST, PORT, create_dashboard_app
    from bot.main import run_all
    from bot.runtime_flags import set_dashboard_keepalive

    set_dashboard_keepalive(True)
    app = create_dashboard_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    url = f"http://{'[REDACTED]' if HOST == '0.0.0.0' else HOST}:{PORT}/"
    logging.getLogger("home24").info("dashboard %s", url)
    print(f"Панель Home24: {url}", flush=True)
    try:
        await run_all()
    finally:
        try:
            from bot.client_registry import snapshot
            from bot.instance_guard import release_all

            for row in snapshot():
                logging.getLogger("home24").info(
                    "shutdown client account=%s role=%s",
                    row.get("account_id"),
                    row.get("role"),
                )
            release_all()
        except Exception:
            logging.getLogger("home24").debug("shutdown locks", exc_info=True)
        await runner.cleanup()


def main() -> None:
    _setup_logging()
    _load_env()
    os.environ.setdefault("HOME24_WEB_LOGIN", "1")
    os.environ.setdefault("HOME24_NO_QR", "1")
    os.environ.setdefault("USE_PROXY", "0")

    log = logging.getLogger("home24")

    from bot.instance_guard import acquire_global, install_signal_handlers, release_all

    install_signal_handlers()
    ok_lock, lock_msg = acquire_global()
    if not ok_lock:
        log.error("%s", lock_msg)
        print(lock_msg, flush=True)
        sys.exit(1)

    if "--login" in sys.argv or os.getenv("HOME24_FORCE_LOGIN") == "1":
        from bot.dashboard.app import main as dash_main

        try:
            dash_main()
        finally:
            release_all()
        return

    if "--dashboard-only" in sys.argv or os.getenv("HOME24_DASHBOARD_ONLY") == "1":
        from bot.dashboard.app import main as dash_main

        try:
            dash_main()
        finally:
            release_all()
        return

    try:
        # сначала без connect — если сессий нет, сразу панель
        if _sessions_present_no_connect():
            ok = asyncio.run(_probe_sessions_once())
        else:
            ok = False
    except Exception:
        log.exception("session probe failed")
        ok = False

    if not ok:
        # информационное: ждём вход в панели, не авария
        log.warning("Нет живой сессии — открываю панель для входа")
        try:
            ok = asyncio.run(_open_dashboard_until_ready())
        except Exception:
            log.exception("dashboard login failed")
            release_all()
            sys.exit(EXIT_SESSION_DEAD)
        if not ok:
            release_all()
            sys.exit(EXIT_SESSION_DEAD)

    try:
        asyncio.run(_run_bot_with_dashboard())
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else EXIT_SESSION_DEAD
        release_all()
        sys.exit(code)
    except Exception as e:
        name = type(e).__name__
        log.exception("bot crashed: %s", name)
        release_all()
        if "AuthKeyUnregistered" in name or "SessionRevoked" in name or "AuthKey" in name:
            sys.exit(EXIT_SESSION_DEAD)
        sys.exit(1)
    finally:
        release_all()


if __name__ == "__main__":
    main()
