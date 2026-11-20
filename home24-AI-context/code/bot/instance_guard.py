# -*- coding: utf-8 -*-
"""Single-instance + per-account session locks (PID files under data/locks/).

Prevents a second run_home24 / start.bat from starting the same Telegram
session (Telegram revokes auth keys when two clients share one).
No anti-detect — just process exclusivity.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("home24.instance_guard")

_LOCK = threading.RLock()
_HELD: dict[str, Path] = {}  # name → path
_ATEXIT_REGISTERED = False
# После чистого disconnect достаточно короткой паузы.
# После убитого процесса Telegram ещё держит сокет — входить сразу значит
# AuthKeyDuplicated и навсегда потерянный аккаунт.
_GAP_CLEAN = 4.0
_GAP_UNCLEAN = float(os.getenv("HOME24_RECONNECT_GAP") or "20")


def locks_dir() -> Path:
    root = Path(os.getenv("HOME24_LOCKS_DIR") or "data/locks")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # exists but not ours — treat as alive
        return True
    except OSError:
        return False
    # Windows: os.kill(pid, 0) works on Python 3; extra check via /proc when present
    if sys.platform.startswith("linux"):
        return Path(f"/proc/{pid}").exists()
    return True


def _read_lock(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def _write_lock(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def lock_status(name: str) -> dict[str, Any]:
    """Public status for panel: held?, pid, stale?"""
    path = locks_dir() / f"{name}.lock"
    if not path.exists():
        return {"name": name, "held": False, "path": str(path)}
    data = _read_lock(path) or {}
    pid = int(data.get("pid") or 0)
    alive = _pid_alive(pid)
    return {
        "name": name,
        "held": alive,
        "stale": not alive,
        "pid": pid,
        "started_at": data.get("started_at"),
        "account_id": data.get("account_id") or "",
        "role": data.get("role") or "",
        "path": str(path),
        "message": data.get("message") or "",
    }


def _stamp_path(name: str) -> Path:
    return locks_dir() / f"{name}.last"


def _write_stamp(name: str, *, at: float, clean: bool) -> None:
    payload = {"at": float(at), "clean": bool(clean)}
    try:
        _write_lock(_stamp_path(name), payload)
    except Exception:
        logger.debug("stamp write failed name=%s", name, exc_info=True)


def reconnect_wait_seconds(name: str, now: float | None = None) -> float:
    """Сколько секунд нельзя открывать этот auth key.

    clean=True — мы сами закрыли сокет. clean=False — процесс умер,
    и Telegram мог ещё не отпустить соединение.
    """
    data = _read_lock(_stamp_path(name)) or {}
    at = float(data.get("at") or 0)
    if at <= 0:
        return 0.0
    gap = _GAP_CLEAN if data.get("clean") else _GAP_UNCLEAN
    return max(0.0, gap - ((time.time() if now is None else float(now)) - at))


async def pause_before_telegram(account_id: str) -> None:
    aid = (account_id or "").strip() or "main"
    name = f"account_{aid}"
    wait = reconnect_wait_seconds(name)
    if wait <= 0:
        return
    logger.warning(
        "pause %.0fs before Telegram connect account=%s — предыдущий сокет ещё может быть жив",
        wait,
        aid,
    )
    await asyncio.sleep(wait)


def note_heartbeat(name: str) -> None:
    """Пока клиент онлайн, пишем время. По нему следующий старт поймёт, что процесс только что умер."""
    path = locks_dir() / f"{name}.lock"
    with _LOCK:
        if name not in _HELD or not path.exists():
            return
        data = _read_lock(path) or {}
        if int(data.get("pid") or 0) != os.getpid():
            return
        data["heartbeat_at"] = time.time()
        try:
            _write_lock(path, data)
        except Exception:
            logger.debug("heartbeat failed name=%s", name, exc_info=True)


def try_acquire(
    name: str,
    *,
    account_id: str = "",
    role: str = "",
    message: str = "",
) -> tuple[bool, str]:
    """Acquire named lock for this PID. Returns (ok, human message)."""
    global _ATEXIT_REGISTERED
    path = locks_dir() / f"{name}.lock"
    with _LOCK:
        if name in _HELD:
            return True, "already held by this process"
        if path.exists():
            data = _read_lock(path) or {}
            pid = int(data.get("pid") or 0)
            if pid == os.getpid():
                _HELD[name] = path
                return True, "re-entrant"
            if _pid_alive(pid):
                msg = (
                    f"Уже запущен другой процесс Home24 (PID {pid})"
                    + (f" для аккаунта [{account_id}]" if account_id else "")
                    + ". Закройте его или дождитесь завершения — "
                    "два клиента с одной сессией Telegram отзывают вход."
                )
                logger.error("lock busy name=%s pid=%s", name, pid)
                return False, msg
            logger.warning("clearing stale lock name=%s dead_pid=%s", name, pid)
            at = float(data.get("heartbeat_at") or data.get("started_at") or time.time())
            _write_stamp(name, at=at, clean=False)
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        payload = {
            "pid": os.getpid(),
            "started_at": time.time(),
            "heartbeat_at": time.time(),
            "account_id": account_id,
            "role": role,
            "message": message,
        }
        try:
            _write_lock(path, payload)
        except Exception as e:
            return False, f"не удалось создать lock: {e}"
        # verify we won (no race)
        data = _read_lock(path) or {}
        if int(data.get("pid") or 0) != os.getpid():
            return False, "lock race — другой процесс успел первым"
        _HELD[name] = path
        if not _ATEXIT_REGISTERED:
            atexit.register(release_all)
            _ATEXIT_REGISTERED = True
        logger.info("lock acquired name=%s pid=%s", name, os.getpid())
        return True, "ok"


def release(name: str) -> None:
    with _LOCK:
        path = _HELD.pop(name, None) or (locks_dir() / f"{name}.lock")
        data = _read_lock(path) if path.exists() else None
        if data and int(data.get("pid") or 0) not in (0, os.getpid()):
            return
        # Сокет закрыт этим процессом — следующему старту хватит короткой паузы.
        _write_stamp(name, at=time.time(), clean=True)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.debug("lock release failed name=%s", name, exc_info=True)
        else:
            logger.info("lock released name=%s", name)


def release_all() -> None:
    with _LOCK:
        names = list(_HELD.keys())
    for n in names:
        release(n)


def acquire_global() -> tuple[bool, str]:
    return try_acquire("home24", role="bot", message="global Home24 instance")


def acquire_account(account_id: str, *, role: str = "client") -> tuple[bool, str]:
    aid = (account_id or "").strip() or "main"
    return try_acquire(
        f"account_{aid}",
        account_id=aid,
        role=role,
        message=f"TelegramClient for [{aid}]",
    )


def release_account(account_id: str) -> None:
    aid = (account_id or "").strip() or "main"
    release(f"account_{aid}")


def global_status() -> dict[str, Any]:
    st = lock_status("home24")
    accounts = []
    d = locks_dir()
    for p in sorted(d.glob("account_*.lock")):
        name = p.stem  # account_main
        accounts.append(lock_status(name))
    return {"global": st, "accounts": accounts, "pid": os.getpid()}


_SHUTDOWN_STARTED = False


def install_signal_handlers() -> None:
    """SIGTERM сначала рвёт сокет Telegram, и только потом отпускает lock.

    Если снять lock и сразу умереть, systemd поднимет второй процесс,
    пока сервер Telegram ещё видит первый. Это и есть «аккаунт вылетел».
    """

    def _handler(signum, _frame):
        global _SHUTDOWN_STARTED
        if _SHUTDOWN_STARTED:
            return
        _SHUTDOWN_STARTED = True
        logger.info("signal %s — disconnect Telegram before exit", signum)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(_schedule_disconnect_and_exit)
            return
        release_all()
        raise SystemExit(0)

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _handler)
        except Exception:
            pass


def _schedule_disconnect_and_exit() -> None:
    try:
        asyncio.get_running_loop().create_task(_disconnect_and_exit())
    except RuntimeError:
        release_all()
        os._exit(0)


async def _disconnect_and_exit() -> None:
    try:
        from bot.client_registry import disconnect_all

        await asyncio.wait_for(disconnect_all(), timeout=12)
    except Exception:
        logger.exception("shutdown disconnect failed")
    release_all()
    os._exit(0)
