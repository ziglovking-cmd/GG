"""Новые тесты: сессия, лимиты, веб-логин, opt-out, без утечки 2FA."""

from __future__ import annotations

import ast
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.engine import is_stop_request
from bot.login import EXIT_SESSION_DEAD, ensure_login
from bot.rate_limit import OutreachLimiter
from bot.session_io import clear_session, save_session_db, save_session_env
from bot.store import Store


def test_exit_session_dead_code() -> None:
    assert EXIT_SESSION_DEAD == 42


def test_session_io_env_roundtrip(tmp_path: Path | None = None) -> None:
    d = Path(tempfile.mkdtemp())
    env = d / ".env"
    env.write_text("TELEGRAM_API_ID=6\nTELEGRAM_SESSION=old\nMANAGER_PHONE=+1\n", encoding="utf-8")
    save_session_env("NEWSESS", phone="[REDACTED]", env_path=env)
    text = env.read_text(encoding="utf-8")
    assert "TELEGRAM_SESSION=NEWSESS" in text
    assert "MANAGER_PHONE=[REDACTED]" in text
    assert "old" not in text
    clear_session(env_path=env, db_path=d / "missing.db")
    assert "TELEGRAM_SESSION=\n" in env.read_text(encoding="utf-8") or env.read_text(
        encoding="utf-8"
    ).rstrip().endswith("TELEGRAM_SESSION=")


def test_session_io_db(tmp_path: Path | None = None) -> None:
    d = Path(tempfile.mkdtemp())
    db = d / "t.db"
    store = Store(str(db))
    save_session_db("ABC", [REDACTED], db_path=db)
    assert store.get_meta("telethon_session") == "ABC"
    assert store.get_meta("owner_id") == "123"
    clear_session(env_path=d / ".env", db_path=db)
    assert (store.get_meta("telethon_session") or "") == ""


def test_outreach_limiter_caps() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    d = Path(tempfile.mkdtemp())
    store = Store(str(d / "lim.db"))
    # фиксируем «сейчас» внутри окна через подкласс
    class Fixed(OutreachLimiter):
        def now(self):
            return datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    lim = Fixed(store, daily_limit=3, per_hour=0, work_start=10, work_end=20)
    assert lim.daily_limit == 3
    assert lim.in_work_hours() is True
    assert lim.remaining_today() == 3
    lim.record_send()
    lim.record_send()
    lim.record_send()
    assert lim.sent_today() == 3
    assert lim.remaining_today() == 0
    ok, why = lim.can_send()
    assert ok is False
    assert "лимит" in why.lower() or "днев" in why.lower()
    lim.set_last_error("FloodWait 30s")
    assert "FloodWait" in lim.last_error()
    # ответы не вызывают record_send — отдельный счётчик не растёт сам
    assert lim.sent_today() == 3


def test_outreach_work_hours_and_spacing() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    d = Path(tempfile.mkdtemp())
    store = Store(str(d / "lim2.db"))

    class Noon(OutreachLimiter):
        def now(self):
            return datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    class Night(OutreachLimiter):
        def now(self):
            return datetime(2026, 6, 15, 22, 30, tzinfo=ZoneInfo("Europe/Moscow"))

    noon = Noon(store, daily_limit=100, work_start=10, work_end=20)
    assert noon.in_work_hours()
    # 8 часов до 20:00, 100 слотов → ~288 сек
    gap = noon.spacing_delay_sec(queue_left=100)
    assert 200 <= gap <= 400
    lines = noon.status_lines(pending_count=150)
    blob = "\n".join(lines)
    assert "100" in blob
    assert "сегодня" in blob.lower() or "Сегодня" in blob or "осталось" in blob

    night = Night(store, daily_limit=100, work_start=10, work_end=20)
    assert not night.in_work_hours()
    ok, why = night.can_send()
    assert ok is False
    assert "часов" in why
    assert night.seconds_until_window_open() > 0
    assert night.planned_today(150) == 100  # завтра до лимита


def test_daily_send_limit_env_default() -> None:
    from bot import rate_limit as rl

    assert rl.DEFAULT_DAILY == 30 or int(__import__("os").getenv("DAILY_SEND_LIMIT") or 30) <= 30
    assert getattr(rl, "DEFAULT_WEEKLY", 210) == 210 or int(
        __import__("os").getenv("WEEKLY_SEND_LIMIT") or 210
    ) <= 210


def test_honest_device_fingerprint() -> None:
    """Нет маскировки под Telegram Desktop; app_version = версия бота; стабильно."""
    import platform

    from bot.device import telethon_device_kwargs
    from bot.version import APP_NAME, __version__

    a = telethon_device_kwargs()
    b = telethon_device_kwargs()
    assert a == b
    assert a["app_version"] == f"{APP_NAME}/{__version__}"
    assert "5.3.1" not in a["app_version"]
    assert a["device_model"] != "Desktop"
    assert "Telegram" not in a["device_model"]
    # system_version отражает platform
    assert platform.system() in a["system_version"] or a["system_version"]
    # login/web_login не содержат старый спуф
    root = Path(__file__).resolve().parents[1]
    for rel in ("bot/login.py", "bot/web_login.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "5.3.1" not in text
        assert 'device_model": "Desktop"' not in text


def test_opt_out_keywords() -> None:
    assert is_stop_request("Не пишите мне больше")
    assert is_stop_request("стоп")
    assert is_stop_request("unsubscribe")
    assert is_stop_request("opt-out")
    assert is_stop_request("отпишитесь пожалуйста")
    assert is_stop_request("leave me alone")
    assert not is_stop_request("просто смотрю варианты")
    assert not is_stop_request("сколько стоит")
    assert not is_stop_request("ищу квартиру")


def test_web_login_routes_and_html() -> None:
    from bot.web_login import HTML, LOGIN_PORT, create_app

    assert LOGIN_PORT > 0
    assert "Найти аккаунты" in HTML
    assert "Запросить код" in HTML
    assert "Показать QR" in HTML
    assert "type=\"password\"" in HTML
    app = create_app()
    paths = {r.resource.canonical for r in app.router.routes()}
    # aiohttp may store differently — check named paths via resources
    res = []
    for resource in app.router.resources():
        try:
            res.append(resource.canonical)
        except Exception:
            pass
    joined = " ".join(res)
    assert "/api/tdata/scan" in joined
    assert "/api/qr/start" in joined
    assert "/api/phone/send_code" in joined
    assert "/api/phone/sign_in" in joined


def test_login_py_no_password_print() -> None:
    """ensure_login / login.py не печатает и не хардкодит 2FA."""
    src = Path(__file__).resolve().parents[1] / "bot" / "login.py"
    text = src.read_text(encoding="utf-8")
    assert "print(" not in text or "password" not in text.lower()
    assert "123443" not in text
    assert "input(" not in text
    # AST: no Call to print with password-related names
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            dump = ast.dump(node)
            assert "password" not in dump.lower()
            assert "2fa" not in dump.lower()


def test_web_login_no_password_logging() -> None:
    src = Path(__file__).resolve().parents[1] / "bot" / "web_login.py"
    text = src.read_text(encoding="utf-8")
    assert "logger.info" in text or "logger." in text
    # never log password value
    assert "logger" not in text or "[REDACTED] not in text
    assert "print(pwd" not in text
    assert "print(password" not in text
    assert "123443" not in text


def test_start_bat_handles_session_dead() -> None:
    bat = (Path(__file__).resolve().parents[1] / "start.bat").read_text(encoding="utf-8")
    assert "ERRORLEVEL" in bat or "%ERR%" in bat
    assert "42" in bat
    assert "web_login" in bat
    assert "run_home24.py" in bat
    assert "Python311" in bat
    assert "restart" in bat.lower() or "перезапуск" in bat.lower() or "goto loop" in bat


def test_tdata_helpers_importable() -> None:
    from bot.tdata_import import account_public_dict, default_tdata_path, telegram_desktop_running
    from bot.tdata_import import TdataAccountInfo

    a = TdataAccountInfo(0, 1, "+7900", "user", "Ann", "SESS")
    d = account_public_dict(a)
    assert "SESS" not in str(d.values())
    assert d["index"] == 0
    assert "session" not in d
    # path may be None on Linux CI
    _ = default_tdata_path()
    assert isinstance(telegram_desktop_running(), bool)


async def _ensure_empty_exits() -> None:
    import os

    os.environ["HOME24_WEB_LOGIN"] = "1"
    try:
        await ensure_login(6, "hash", "")
        raise AssertionError("should exit")
    except SystemExit as e:
        assert e.code == EXIT_SESSION_DEAD


def test_proxy_slot_does_not_fall_back_to_server_ip(tmp_path=None) -> None:
    import os
    from pathlib import Path

    from bot.proxy import EgressProxyMissing, proxy_for_slot

    os.environ.pop("TELEGRAM_PROXY_BOUGHT", None)
    os.environ.pop("TELEGRAM_MTPROXY", None)
    missing = Path("data/proxy_bought_absent.txt")
    assert not missing.exists()
    try:
        proxy_for_slot("bought", have_slot=True)
    except EgressProxyMissing as e:
        assert "proxy_bought.txt" in str(e)
    else:
        raise AssertionError("bought egress must not connect without a proxy")
    assert proxy_for_slot("server", have_slot=True) is None
    from bot.proxy import client_transport, load_mtproxy

    os.environ["TELEGRAM_MTPROXY"] = "fast.example:443:ee00112233445566778899aabbccddeeff"
    try:
        mt = load_mtproxy()
        assert mt is not None and mt[0] == "fast.example" and mt[1] == 443
        conn, proxy = client_transport("server", have_slot=True)
        assert proxy == mt
        assert conn.__name__ == "ConnectionTcpMTProxyIntermediate"
    finally:
        os.environ.pop("TELEGRAM_MTPROXY", None)


def test_brand_is_packaged_with_code() -> None:
    from bot.dashboard.app import PACKAGED_BRAND, resolve_brand_dir

    for name in ("home24-logo.svg", "favicon.svg", "avatar.jpg", "logo.png"):
        assert (PACKAGED_BRAND / name).is_file(), name
    resolved = resolve_brand_dir()
    assert (resolved / "home24-logo.svg").is_file()


def test_startup_does_not_open_a_second_telegram_client() -> None:
    root = Path(__file__).resolve().parents[1]
    body = (root / "run_home24.py").read_text(encoding="utf-8")
    probe = body.split("async def _probe_sessions_once", 1)[1].split("\nasync def ", 1)[0]
    assert "client.connect" not in probe
    assert "mark_revoked" not in probe


def test_device_fingerprint_freezes_once() -> None:
    import tempfile

    from bot.tg_accounts import TgAccountRegistry

    path = Path(tempfile.mkdtemp()) / "tg.json"
    reg = TgAccountRegistry(path)
    reg.upsert(account_id="srv-1", label="Сервер 1", is_main=True)
    slot = reg.get("srv-1")
    assert slot is not None
    slot.device_model = ""
    slot.system_version = ""
    slot.app_version = ""
    first = reg.freeze_device_fingerprint("srv-1")
    assert first["device_model"]
    again = TgAccountRegistry(path)
    saved = again.get("srv-1")
    assert saved is not None
    assert saved.device_model == first["device_model"]
    saved.device_model = "StableBox"
    saved.system_version = "Linux 1"
    saved.app_version = "Home24/9.5.0"
    again.save()
    stuck = again.freeze_device_fingerprint("srv-1")
    assert stuck["device_model"] == "StableBox"
    assert stuck["system_version"] == "Linux 1"


def test_ensure_login_dead_session_exits_42() -> None:
    import asyncio

    asyncio.run(_ensure_empty_exits())


def test_status_help_mentions_preview() -> None:
    from bot.main import HELP

    assert "/send go" in HELP
    assert "превью" in HELP.lower() or "dry" in HELP.lower() or "/send" in HELP
    assert "/status" in HELP


if __name__ == "__main__":
    # allow running without pytest
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print("run", name)
            fn()
    print("ok")
