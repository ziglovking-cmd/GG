# -*- coding: utf-8 -*-
"""Персональные настройки менеджера — data/user_prefs.json."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("home24.user_prefs")
_LOCK = threading.RLock()

DEFAULTS: dict[str, Any] = {
    "signature": "",
    "theme": "dark",  # dark | light | system
    "notify_sound": True,
    "notify_browser": False,
    "notify_toast": True,
    "composer_enter": "send",  # send | newline (Ctrl+Enter sends)
    "font_size": "md",  # sm | md | lg
    "compact_chat": False,
    "dialog_filter": "mine",  # mine | all | needs_reply
}


def default_prefs_path() -> Path:
    return Path(os.getenv("USER_PREFS_PATH") or "data/user_prefs.json")


def _normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = dict(raw or {})
    out = dict(DEFAULTS)
    theme = str(src.get("theme") or out["theme"]).strip().lower()
    if theme not in ("dark", "light", "system"):
        theme = "dark"
    out["theme"] = theme
    out["signature"] = str(src.get("signature") or "")[:80]
    out["notify_sound"] = bool(src.get("notify_sound", out["notify_sound"]))
    out["notify_browser"] = bool(src.get("notify_browser", out["notify_browser"]))
    out["notify_toast"] = bool(src.get("notify_toast", out["notify_toast"]))
    enter = str(src.get("composer_enter") or out["composer_enter"]).strip().lower()
    out["composer_enter"] = enter if enter in ("send", "newline") else "send"
    font = str(src.get("font_size") or out["font_size"]).strip().lower()
    out["font_size"] = font if font in ("sm", "md", "lg") else "md"
    out["compact_chat"] = bool(src.get("compact_chat", out["compact_chat"]))
    filt = str(src.get("dialog_filter") or out["dialog_filter"]).strip().lower()
    out["dialog_filter"] = (
        filt if filt in ("mine", "all", "needs_reply") else "mine"
    )
    return out


class UserPrefsStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or default_prefs_path())
        self._data: dict[str, Any] = {"users": {}}
        self.load()

    def load(self) -> None:
        with _LOCK:
            if not self.path.exists():
                self._data = {"users": {}}
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("user_prefs load failed")
                self._data = {"users": {}}
                return
            users = {}
            for k, v in (raw.get("users") or {}).items():
                if isinstance(v, dict) and str(k).strip():
                    users[str(k).strip().lower()] = _normalize(v)
            self._data = {"users": users}

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def get(self, username: str) -> dict[str, Any]:
        [REDACTED] or "").strip().lower()
        with _LOCK:
            return dict(self._data.get("users", {}).get(key) or DEFAULTS)

    def update(self, username: str, patch: dict[str, Any]) -> dict[str, Any]:
        [REDACTED] or "").strip().lower()
        if not [REDACTED] ValueError("нужен username")
        with _LOCK:
            cur = _normalize(self._data.setdefault("users", {}).get(key))
            merged = _normalize({**cur, **(patch or {})})
            self._data["users"][key] = merged
            self._save_unlocked()
            return dict(merged)


_store: UserPrefsStore | None = None


def get_user_prefs_store() -> UserPrefsStore:
    global _store
    with _LOCK:
        if _store is None:
            _store = UserPrefsStore()
        return _store


def reset_user_prefs_cache() -> None:
    global _store
    with _LOCK:
        _store = None


def manager_label(username: str, display_name: str = "") -> str:
    """Текст для плейсхолдера {менеджер}: подпись → display_name → логин."""
    prefs = get_user_prefs_store().get(username)
    sig = (prefs.get("signature") or "").strip()
    if sig:
        return sig
    name = (display_name or "").strip()
    return name or username
