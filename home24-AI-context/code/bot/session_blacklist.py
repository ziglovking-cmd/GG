# -*- coding: utf-8 -*-
"""Стойкий чёрный список отозванных StringSession (sha256) — никогда не поднимать снова."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("home24.session_blacklist")
_LOCK = threading.RLock()
_cache: set[str] | None = None


def default_blacklist_path() -> Path:
    return Path(os.getenv("SESSION_BLACKLIST_PATH") or "data/session_blacklist.json")


def session_hash(session: str) -> str:
    s = (session or "").strip().encode("utf-8")
    if not s:
        return ""
    return hashlib.sha256(s).hexdigest()


def _load_unlocked(path: Path | None = None) -> set[str]:
    global _cache
    if _cache is not None:
        return _cache
    p = path or default_blacklist_path()
    hashes: set[str] = set()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for h in data.get("sha256") or []:
                if isinstance(h, str) and len(h) == 64:
                    hashes.add(h.lower())
        except Exception:
            logger.exception("session blacklist load failed")
    _cache = hashes
    return _cache


def _save_unlocked(path: Path | None = None) -> None:
    p = path or default_blacklist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sha256": sorted(_load_unlocked(p))}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def is_blacklisted(session: str, *, path: Path | None = None) -> bool:
    h = session_hash(session)
    if not h:
        return False
    with _LOCK:
        return h in _load_unlocked(path)


def blacklist_session(session: str, *, path: Path | None = None) -> bool:
    """Добавить sha256 сессии. True если список изменился."""
    h = session_hash(session)
    if not h:
        return False
    with _LOCK:
        s = _load_unlocked(path)
        if h in s:
            return False
        s.add(h)
        _save_unlocked(path)
        logger.warning("blacklisted dead session hash=%s…", h[:12])
        return True


def unblacklist_session(session: str, *, path: Path | None = None) -> bool:
    """Убрать hash после успешного нового входа (если вдруг совпал)."""
    h = session_hash(session)
    if not h:
        return False
    with _LOCK:
        s = _load_unlocked(path)
        if h not in s:
            return False
        s.discard(h)
        _save_unlocked(path)
        return True


def reset_blacklist_cache() -> None:
    global _cache
    with _LOCK:
        _cache = None
