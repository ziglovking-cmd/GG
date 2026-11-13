"""Задания рассылки с панели → процесс бота, у которого есть Telegram.

Панель только кладёт JSON в data/outreach_jobs. Бот забирает файл
и шлёт первым сообщениям своим клиентом.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path


def _jobs_dir() -> Path:
    return Path(os.getenv("OUTREACH_JOBS_DIR") or "data/outreach_jobs")


def _status_path() -> Path:
    override = (os.getenv("OUTREACH_STATUS_PATH") or "").strip()
    if override:
        return Path(override)
    return _jobs_dir().parent / "outreach_status.json"


def parse_outreach_lines(text: str) -> list[dict[str, str]]:
    """Строки вида «[REDACTED], Имя» или «@username»."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = ""
        if "," in line:
            left, right = line.split(",", 1)
            if re.search(r"\d", left) or left.strip().startswith("@"):
                line, name = left.strip(), right.strip()
        username = re.search(r"@([A-Za-z][A-Za-z0-9_]{3,})", line)
        digits = re.sub(r"\D", "", line)
        [REDACTED]
        if username and len(digits) < 10:
            [REDACTED] + username.group(1)
        elif len(digits) == 11 and digits[0] in "78":
            [REDACTED] + digits[1:]
        elif len(digits) == 10 and digits[0] == "9":
            [REDACTED] + digits
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        out.append({"phone": key, "name": name[:80]})
    return out


def enqueue(
    *,
    action: str,
    manager_id: str,
    phones: list[str] | None = None,
    now: bool = False,
) -> Path:
    folder = _jobs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.time_ns()}.json"
    path.write_text(
        json.dumps(
            {
                "action": action,
                "manager_id": manager_id,
                "phones": list(phones or []),
                "now": bool(now),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def pending() -> list[Path]:
    folder = _jobs_dir()
    if not folder.exists():
        return []
    return sorted(p for p in folder.glob("*.json") if p.is_file())


def write_status(manager_id: str, **fields: object) -> None:
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    cur = data.get(manager_id) if isinstance(data.get(manager_id), dict) else {}
    cur.update(fields)
    cur["ts"] = time.time()
    data[manager_id] = cur
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def read_status(manager_id: str = "") -> dict:
    path = _status_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    if manager_id:
        row = data.get(manager_id)
        return row if isinstance(row, dict) else {}
    return data
