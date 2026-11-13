"""Сохранение StringSession в .env / managers.json / data/home24.db (без печати секретов)."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger("home24.session_io")


def project_root() -> Path:
    return Path.cwd()


def save_session_env(sess: str, *, phone: str | None = None, env_path: Path | None = None) -> None:
    """Совместимость: пишем TELEGRAM_SESSION (сессия default-менеджера)."""
    path = env_path or (project_root() / ".env")
    lines: list[str] = []
    found_sess = False
    found_phone = False
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for line in text.splitlines():
        if line.startswith("TELEGRAM_SESSION="):
            lines.append(f"TELEGRAM_SESSION={sess}")
            found_sess = True
        elif phone is not None and line.startswith("MANAGER_PHONE="):
            lines.append(f"MANAGER_PHONE={phone}")
            found_phone = True
        else:
            lines.append(line)
    if not found_sess:
        lines.append(f"TELEGRAM_SESSION={sess}")
    if phone is not None and not found_phone:
        lines.append(f"MANAGER_PHONE={phone}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_session_db(
    sess: str,
    user_id: int | None = None,
    db_path: str | Path | None = None,
    *,
    manager_id: str = "",
) -> None:
    db = Path(db_path or os.getenv("DATABASE_PATH") or "data/home24.db")
    if not db.exists():
        return
    con = sqlite3.connect(str(db))
    try:
        [REDACTED] if manager_id else "telethon_session"
        con.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, sess),
        )
        if not manager_id:
            con.execute(
                "INSERT INTO meta(key,value) VALUES('telethon_session',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (sess,),
            )
        if user_id is not None:
            o[REDACTED] if manager_id else "owner_id"
            con.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (okey, str(user_id)),
            )
        con.commit()
    finally:
        con.close()


def save_manager_session(
    manager_id: str,
    sess: str,
    *,
    phone: str | None = None,
    user_id: int | None = None,
    is_default: bool = False,
) -> None:
    """Сессия менеджера → managers.json (+ .env если default)."""
    from bot.managers import get_registry

    reg = get_registry()
    reg.set_session(manager_id, sess, phone=phone)
    save_session_db(sess, user_id=user_id, manager_id=manager_id)
    if is_default or manager_id == reg.default_manager_id:
        save_session_env(sess, phone=phone)
        save_session_db(sess, user_id=user_id, manager_id="")


def clear_session(
    *,
    env_path: Path | None = None,
    db_path: str | Path | None = None,
    manager_id: str = "",
) -> None:
    if manager_id:
        try:
            from bot.managers import get_registry

            get_registry().clear_session(manager_id)
        except Exception:
            pass
        save_session_db("", manager_id=manager_id, db_path=db_path)
        return
    save_session_env("", env_path=env_path)
    db = Path(db_path or os.getenv("DATABASE_PATH") or "data/home24.db")
    if db.exists():
        con = sqlite3.connect(str(db))
        try:
            con.execute(
                "INSERT INTO meta(key,value) VALUES('telethon_session','') "
                "ON CONFLICT(key) DO UPDATE SET value=''"
            )
            con.commit()
        finally:
            con.close()


def _clear_env_session_if_matches(
    sess: str, *, env_path: Path | None = None
) -> bool:
    path = env_path or (project_root() / ".env")
    if not path.exists():
        return False
    target = (sess or "").strip()
    if not target:
        return False
    text = path.read_text(encoding="utf-8")
    lines: list[str] = []
    changed = False
    for line in text.splitlines():
        if line.startswith("TELEGRAM_SESSION="):
            cur = line.split("=", 1)[1] if "=" in line else ""
            if cur.strip() == target:
                lines.append("TELEGRAM_SESSION=")
                changed = True
                continue
        lines.append(line)
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # process env so get_settings / getenv don't keep the dead value
        if (os.getenv("TELEGRAM_SESSION") or "").strip() == target:
            os.environ["TELEGRAM_SESSION"] = ""
    return changed


def purge_dead_session(
    sess: str,
    *,
    env_path: Path | None = None,
    db_path: str | Path | None = None,
) -> None:
    """Стереть отозванную сессию везде + blacklist sha256. Не трогать другие сессии."""
    target = (sess or "").strip()
    if not target:
        return
    try:
        from bot.session_blacklist import blacklist_session

        blacklist_session(target)
    except Exception:
        logger.exception("blacklist failed")

    # managers.json — все менеджеры с этой строкой
    try:
        from bot.managers import get_registry

        reg = get_registry()
        for m in list(reg.managers.values()):
            if (m.session or "").strip() == target:
                reg.clear_session(m.id)
    except Exception:
        logger.exception("purge managers session failed")

    # tg_accounts.json — все слоты с этой строкой
    try:
        from bot.tg_accounts import get_tg_accounts

        tg = get_tg_accounts()
        for a in list(tg.accounts.values()):
            if (a.session or "").strip() == target:
                a.session = ""
                if a.status == "ok":
                    a.status = "revoked"
                    a.status_note = (a.status_note or "сессия отозвана")[:500]
        tg.save()
    except Exception:
        logger.exception("purge tg_accounts session failed")

    # meta: любые ключи с этой value + session-like keys
    db = Path(db_path or os.getenv("DATABASE_PATH") or "data/home24.db")
    if db.exists():
        try:
            con = sqlite3.connect(str(db))
            try:
                rows = con.execute("SELECT key, value FROM meta").fetchall()
                for key, value in rows:
                    k = str(key or "")
                    v = str(value or "").strip()
                    if v == target or (
                        "session" in k.lower() and v == target
                    ):
                        con.execute(
                            "INSERT INTO meta(key,value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=''",
                            (k, ""),
                        )
                con.commit()
            finally:
                con.close()
        except Exception:
            logger.exception("purge meta session failed")

    try:
        _clear_env_session_if_matches(target, env_path=env_path)
    except Exception:
        logger.exception("purge .env session failed")

    # сбросить кэш Settings.session если был
    try:
        from bot.config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass

    logger.warning("purged dead session from legacy stores (len=%s)", len(target))
