# -*- coding: utf-8 -*-
"""Панель Home24 без Telegram: демо-диалоги на локальной машине.

Не открывает сессию Telegram и ничего не отправляет.
Рабочий запуск с аккаунтом компании — python run_home24.py (см. README).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# До импорта bot.*: порт и флаг DEMO читаются при загрузке модуля панели.
os.environ.setdefault("HOME24_DASHBOARD_DEMO", "1")
os.environ.setdefault("HOME24_DASHBOARD_ONLY", "1")
os.environ.setdefault("HOME24_WEB_LOGIN", "1")
os.environ.setdefault("HOME24_NO_QR", "1")
os.environ.setdefault("USE_PROXY", "0")
os.environ.setdefault("USE_AI", "0")
os.environ.setdefault("DASHBOARD_HOST", "[REDACTED]")
os.environ.setdefault("DASHBOARD_PORT", "43125")
os.environ.setdefault("DASHBOARD_ADMIN_USERNAME", "admin")
os.environ.setdefault("DASHBOARD_ADMIN_PASSWORD", "home24-demo")
os.environ.setdefault("DASHBOARD_ADMIN_MUST_CHANGE", "0")


def main() -> None:
    from bot.config import get_settings
    from bot.dashboard.demo import seed_demo
    from bot.store import Store

    info = seed_demo(Store(get_settings().db_path))
    host = os.environ["DASHBOARD_HOST"]
    port = os.environ["DASHBOARD_PORT"]
    user = os.environ["DASHBOARD_ADMIN_USERNAME"]
    print(
        f"Демо-данные: {info.get('dialogs')} диалогов, {info.get('managers')} менеджеров.",
        flush=True,
    )
    print(
        f"Вход администратора: {user} / {os.environ['DASHBOARD_ADMIN_PASSWORD']}",
        flush=True,
    )
    print("Менеджеры anna, ivan, maria, oleg, elena — пароль demo-mgr", flush=True)
    print(f"Панель: http://{host}:{port}/", flush=True)

    from bot.dashboard.app import run_dashboard
    import asyncio

    asyncio.run(run_dashboard(open_browser=False))


if __name__ == "__main__":
    main()
