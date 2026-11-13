"""Shared admin store used by the Telegram admin menu. Same JSON as the website."""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def admin_dir() -> Path:
    p = Path(os.environ.get("ADMIN_DATA_DIR") or "/opt/home24/admin")
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except OSError:
        fallback = ROOT / "data" / "admin"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def shared_dir() -> Path:
    p = Path(os.environ.get("SHARED_DIR") or "/opt/home24/shared")
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except OSError:
        fallback = ROOT / "public" / "shared"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def store_path() -> Path:
    return admin_dir() / "store.json"


def read_store() -> dict:
    path = store_path()
    if not path.exists():
        return {"overlays": {}, "videos": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"overlays": {}, "videos": []}
    if not isinstance(data, dict):
        return {"overlays": {}, "videos": []}
    overlays = data.get("overlays") if isinstance(data.get("overlays"), dict) else {}
    videos = data.get("videos") if isinstance(data.get("videos"), list) else []
    return {"overlays": overlays, "videos": videos}


def write_store(store: dict) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def support_path() -> Path:
    return admin_dir() / "support.json"


def read_support() -> dict:
    path = support_path()
    if not path.exists():
        return {"threads": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"threads": []}
    threads = data.get("threads") if isinstance(data.get("threads"), list) else []
    return {"threads": threads}


def write_support(data: dict) -> None:
    support_path().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_support_agent_reply(thread_id: str, text: str) -> bool:
    data = read_support()
    now = datetime.now(timezone.utc).isoformat()
    thread = next((t for t in data["threads"] if t.get("id") == thread_id), None)
    if not thread:
        return False
    thread.setdefault("messages", []).append({"role": "agent", "text": text, "at": now})
    thread["updatedAt"] = now
    thread["waitingHuman"] = False
    write_support(data)
    return True


def save_library_video(*, title: str, src: Path, slugs: list[str] | str, skip_if_has: bool = True) -> dict:
    ext = src.suffix.lower() if src.suffix else ".mp4"
    if ext not in {".mp4", ".mov", ".m4v", ".webm"}:
        ext = ".mp4"
    vid = secrets.token_hex(6)
    filename = f"{vid}{ext}"
    dest = shared_dir() / filename
    dest.write_bytes(src.read_bytes())
    if ext in {".mp4", ".m4v", ".mov"}:
        from mp4_faststart import faststart_file

        faststart_file(dest)
    public = ROOT / "public" / "shared"
    public.mkdir(parents=True, exist_ok=True)
    (public / filename).write_bytes(dest.read_bytes())
    item = {
        "id": vid,
        "title": title,
        "filename": filename,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "slugs": slugs if slugs != "all" else "all",
        "skipIfHas": skip_if_has,
    }
    store = read_store()
    store["videos"] = [item, *store["videos"]]
    write_store(store)
    return item


def delete_library_video(vid: str) -> bool:
    store = read_store()
    item = next((v for v in store["videos"] if v.get("id") == vid), None)
    if not item:
        return False
    store["videos"] = [v for v in store["videos"] if v.get("id") != vid]
    write_store(store)
    try:
        (shared_dir() / item["filename"]).unlink(missing_ok=True)
    except OSError:
        pass
    return True


def patch_overlay(slug: str, field: str, value: str) -> None:
    store = read_store()
    cur = store["overlays"].get(slug) or {}
    cur[field] = value
    store["overlays"][slug] = cur
    write_store(store)
