# -*- coding: utf-8 -*-
"""Запасной вход: открывает ту же веб-страницу, что и start.bat.

Основной способ — start.bat → run_home24.py.
Пароль 2FA в консоль не печатаем и не подставляем по умолчанию.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ.setdefault("HOME24_WEB_LOGIN", "1")
    os.environ.setdefault("USE_PROXY", "0")
    from bot.web_login import main as web_main

    web_main()


if __name__ == "__main__":
    main()
