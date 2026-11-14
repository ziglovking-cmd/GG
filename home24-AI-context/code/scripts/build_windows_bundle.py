# -*- coding: utf-8 -*-
"""Собрать /opt/cursor/artifacts/home24_bot_windows.zip"""

from __future__ import annotations

import shutil
import sqlite3
import zipfile
from pathlib import Path

import os

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path("/opt/cursor/artifacts")
STAGE = Path("/tmp/home24_bot_windows_stage")
NAME = os.environ.get("HOME24_BUNDLE_NAME", "home24_bot_windows")
ZIP_PATH = OUT_DIR / f"{NAME}.zip"

# файлы корня бандла
ROOT_FILES = [
    "script.md",
    "requirements.txt",
    "run_home24.py",
    "start.bat",
    "install_autostart.bat",
    "uninstall_autostart.bat",
    "README_WINDOWS.md",
    "README.md",
    "THIRD_PARTY.md",
    "managers.example.json",
    # запасные CLI (основной вход — start.bat → веб)
    "login_windows.py",
    "run_windows.bat",
]


def _write_env(dst: Path) -> None:
    src_path = ROOT / ".env"
    if not src_path.exists():
        src_path = ROOT / ".env.example"
    src = src_path.read_text(encoding="utf-8")
    lines: list[str] = []
    for line in src.splitlines():
        if line.startswith("TELEGRAM_SESSION="):
            lines.append("TELEGRAM_SESSION=")
        elif line.startswith("TELEGRAM_2FA="):
            lines.append("TELEGRAM_2FA=")
        elif line.startswith("TELEGRAM_API_ID="):
            # не кладём официальные id (6/4/…) — пользователь ставит свои
            lines.append("TELEGRAM_API_ID=")
        elif line.startswith("TELEGRAM_API_HASH="):
            lines.append("TELEGRAM_API_HASH=")
        elif line.startswith("MANAGER_PHONE="):
            lines.append("MANAGER_PHONE=[REDACTED]")
        else:
            lines.append(line)
    extras = {
        "USE_PROXY": "0",
        "HOME24_NO_QR": "1",
        "HOME24_WEB_LOGIN": "1",
        "HOME24_LOGIN_PORT": "43125",
        "TELEGRAM_PROXY": "",
        "MANAGER_PHONE": "[REDACTED]",
        "TELEGRAM_2FA": "",
        "DAILY_SEND_LIMIT": "172",
        "WEEKLY_SEND_LIMIT": "1200",
        "TG_ACCOUNT_NEW_DAILY_LIMIT": "30",
        "WORK_HOURS_START": "10",
        "WORK_HOURS_END": "20",
        "WORK_TIMEZONE": "Europe/Moscow",
        "OUTREACH_MAX_PER_HOUR": "0",
        "OUTREACH_MIN_GAP_SEC": "45",
        "DASHBOARD_HOST": "[REDACTED]",
        "DASHBOARD_PORT": "43125",
        "DASHBOARD_SECRET": "change-me-home24-dashboard",
        "DASHBOARD_ADMIN_USERNAME": "admin",
        "TG_QUIET_HOURS_AFTER_LOGIN": "24",
        "HOME24_CHECK_WINDOWS": "1",
        "HOME24_CHECK_INTERVAL_MIN": "3",
        "HOME24_CHECK_JITTER": "0.3",
        "HOME24_NIGHT_START": "23",
        "HOME24_NIGHT_END": "8",
        "HOME24_NIGHT_INTERVAL_MIN": "15",
        "HOME24_ACTIVE_IDLE_MIN": "10",
    }
    keys_present = {ln.split("=", 1)[0] for ln in lines if "=" in ln and not ln.startswith("#")}
    for k, v in extras.items():
        if k not in keys_present:
            lines.append(f"{k}={v}")
        else:
            lines = [f"{k}={v}" if ln.startswith(f"{k}=") else ln for ln in lines]
    text = "\n".join(lines).rstrip() + "\n"
    assert "TELEGRAM_SESSION=\n" in text or text.rstrip().endswith("TELEGRAM_SESSION=")
    assert "1AZWar" not in text and "1BVts" not in text
    assert "123443" not in text
    dst.write_text(text, encoding="utf-8")


def _copy_db(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if dst.name == "home24.db":
        con = sqlite3.connect(str(dst))
        con.execute(
            "INSERT INTO meta(key,value) VALUES('telethon_session','') "
            "ON CONFLICT(key) DO UPDATE SET value=''"
        )
        con.commit()
        val = con.execute(
            "SELECT value FROM meta WHERE [REDACTED]
        ).fetchone()
        assert not (val and val[0]), val
        con.close()


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    bundle = STAGE / NAME
    bundle.mkdir(parents=True)

    shutil.copytree(
        ROOT / "bot",
        bundle / "bot",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )

    data = bundle / "data"
    data.mkdir()
    (data / ".gitkeep").write_text("", encoding="utf-8")
    _copy_db(ROOT / "data" / "mailing.sqlite", data / "mailing.sqlite")
    _copy_db(ROOT / "data" / "home24.db", data / "home24.db")
    tpl_src = ROOT / "data" / "templates.json"
    tpl_dst = data / "templates.json"
    if tpl_src.exists():
        shutil.copy2(tpl_src, tpl_dst)
    else:
        # сгенерировать дефолты в бандл
        from bot.reply_templates import TemplateStore

        TemplateStore(tpl_dst)
    brand_src = ROOT / "data" / "brand"
    if brand_src.exists():
        shutil.copytree(brand_src, data / "brand")

    for name in ROOT_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, bundle / name)

    # тесты в бандл (для локальной проверки на Windows)
    # только пользовательские скрипты (не build_windows_bundle — там абсолютные пути CI)
    eval_src = ROOT / "scripts" / "eval_smart_dialogs.py"
    if eval_src.exists():
        (bundle / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(eval_src, bundle / "scripts" / "eval_smart_dialogs.py")

    tests_src = ROOT / "tests"
    if tests_src.exists():
        shutil.copytree(
            tests_src,
            bundle / "tests",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )

    _write_env(bundle / ".env")

    bad = []
    for p in bundle.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".py", ".bat", ".md", ".txt", ".env"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for needle in ("/workspace", "/tmp/home24", "/home/ubuntu"):
            if needle in text:
                bad.append((str(p.relative_to(bundle)), needle))
    if bad:
        raise SystemExit(f"hardcoded paths in bundle: {bad}")

    # сессия не должна утечь
    env_text = (bundle / ".env").read_text(encoding="utf-8")
    if "TELEGRAM_SESSION=" in env_text:
        for ln in env_text.splitlines():
            if ln.startswith("TELEGRAM_SESSION=") and ln.split("=", 1)[1].strip():
                raise SystemExit("session leaked into bundle .env")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in bundle.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=str(Path(NAME) / p.relative_to(bundle)))

    size = ZIP_PATH.stat().st_size
    print("OK", ZIP_PATH, "bytes", size)
    print("files", sum(1 for _ in bundle.rglob("*") if _.is_file()))
    names = sorted(p.name for p in bundle.iterdir())
    print("root", names)


if __name__ == "__main__":
    main()
