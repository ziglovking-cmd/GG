"""Аутентификация дашборда: ADMIN / MANAGER, PBKDF2, одна сессия, rate-limit."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("home24.dash.auth")

USERS_PATH = Path(os.getenv("DASHBOARD_USERS_PATH") or "data/dashboard_users.json")
COOKIE_NAME = "home24_dash"
CSRF_COOKIE = "home24_csrf"
SESSION_TTL = int(os.getenv("DASHBOARD_SESSION_TTL") or str(14 * 24 * 3600))
LOGIN_FAIL_LIMIT = int(os.getenv("DASHBOARD_LOGIN_FAIL_LIMIT") or "5")
LOGIN_FAIL_WINDOW = int(os.getenv("DASHBOARD_LOGIN_FAIL_WINDOW") or "900")
AUTH_ERROR = "Неверный логин или пароль"

_LOCK = threading.RLock()
_fail_log: dict[str, list[float]] = {}


def _secret() -> bytes:
    raw = (os.getenv("DASHBOARD_SECRET") or "").strip()
    if not raw:
        raw = "home24-dev-change-me-" + (
            os.getenv("COMPUTERNAME") or os.getenv("HOSTNAME") or "pc"
        )
    return raw.encode("utf-8")


def hash_password([REDACTED] *, iterations: int = 200_000) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
    )
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password([REDACTED] stored: str) -> bool:
    try:
        algo, iters_s, salt, hexdigest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
        )
        return hmac.compare_digest(dk.hex(), hexdigest)
    except Exception:
        return False


@dataclass
class DashUser:
    username: str
    role: str  # admin | manager
    manager_id: str
    display_name: str = ""
    enabled: bool = True
    must_change_[REDACTED] = False
    session_jti: str = ""
    unlisted: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_see_manager(self, manager_id: str) -> bool:
        if self.is_admin:
            return True
        return bool(manager_id) and manager_id == self.manager_id

    def can_act_as(self, manager_id: str) -> bool:
        return self.can_see_manager(manager_id)


def users_path(path: Path | None = None) -> Path:
    return Path(path or os.getenv("DASHBOARD_USERS_PATH") or USERS_PATH)


def _empty_payload() -> dict[str, Any]:
    return {
        "users": [],
        "distribution": {"mode": "even"},  # even | manual
        "setup_done": False,
    }


def load_store(path: Path | None = None) -> dict[str, Any]:
    p = users_path(path)
    if not p.exists():
        return _empty_payload()
    data = json.loads(p.read_text(encoding="utf-8"))
    if "users" not in data:
        data["users"] = []
    if "distribution" not in data:
        data["distribution"] = {"mode": "even"}
    return data


def save_store(data: dict[str, Any], path: Path | None = None) -> None:
    p = users_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def needs_first_setup(path: Path | None = None) -> bool:
    data = load_store(path)
    return not any(u.get("role") == "admin" for u in data.get("users") or [])


def bootstrap_first_admin(path: Path | None = None) -> tuple[str, str] | None:
    """Создать первого админа один раз. Возвращает (username, password) если создан."""
    with _LOCK:
        if not needs_first_setup(path):
            return None
        username = (os.getenv("DASHBOARD_ADMIN_USERNAME") or "admin").strip() or "admin"
        pw = (os.getenv("DASHBOARD_ADMIN_PASSWORD") or "").strip()
        generated = False
        if not pw:
            pw = secrets.token_urlsafe(14)
            generated = True
        data = load_store(path)
        data["users"] = [
            {
                "username": username,
                "role": "admin",
                "manager_id": "",
                "display_name": "Админ",
                "password_hash": hash_password(pw),
                "enabled": True,
                "must_change_password": generated or bool(
                    (os.getenv("DASHBOARD_ADMIN_MUST_CHANGE") or "1").strip()
                    not in ("0", "false", "no")
                ),
                "session_jti": "",
                "invite_token": "",
            }
        ]
        data["setup_done"] = True
        data.setdefault("distribution", {"mode": "even"})
        save_store(data, path)
        msg = (
            f"\n========== Home24: первый вход в панель ==========\n"
            f"Создан ADMIN\n"
            f"  Логин:  {username}\n"
            f"  [REDACTED]
            f"Сохраните пароль. Менеджеров создаёт только админ в панели.\n"
            f"=================================================\n"
        )
        # WARNING + UTF-8 (не ERROR): иначе в Windows-консоли — mojibake «ERROR …»
        try:
            import sys

            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        logger.warning("%s", msg.strip())
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), flush=True)
        return username, pw


def ensure_users_file(path: Path | None = None) -> Path:
    """Обратная совместимость: только bootstrap админа, без менеджеров."""
    p = users_path(path)
    if needs_first_setup(p):
        bootstrap_first_admin(p)
    return p


def load_users(path: Path | None = None) -> list[dict[str, Any]]:
    return list(load_store(path).get("users") or [])


def find_user(username: str, path: Path | None = None) -> dict[str, Any] | None:
    uname = (username or "").strip().lower()
    for u in load_users(path):
        if str(u.get("username") or "").lower() == uname:
            return u
    return None


def _row_to_user(row: dict[str, Any]) -> DashUser:
    role = str(row.get("role") or "manager")
    if role not in ("admin", "manager"):
        role = "manager"
    return DashUser(
        username=str(row["username"]),
        role=role,
        manager_id=str(row.get("manager_id") or ""),
        display_name=str(row.get("display_name") or row["username"]),
        enabled=bool(row.get("enabled", True)),
        must_change_[REDACTED]
        session_jti=str(row.get("session_jti") or ""),
        unlisted=bool(row.get("unlisted")),
    )


def login_rate_limited(ip: str) -> bool:
    now = time.time()
    with _LOCK:
        hits = [t for t in _fail_log.get(ip, []) if now - t < LOGIN_FAIL_WINDOW]
        _fail_log[ip] = hits
        return len(hits) >= LOGIN_FAIL_LIMIT


def record_login_fail(ip: str) -> None:
    with _LOCK:
        _fail_log.setdefault(ip, []).append(time.time())


def clear_login_fails(ip: str) -> None:
    with _LOCK:
        _fail_log.pop(ip, None)


def authenticate(
    username: str,
    [REDACTED]
    *,
    path: Path | None = None,
    client_ip: str = "",
) -> DashUser | None:
    """Успех → DashUser. Иначе None (без различия «нет пользователя» / «плохой пароль»)."""
    if client_ip and login_rate_limited(client_ip):
        return None
    # постоянное время на отсутствие пользователя
    row = find_user(username, path)
    dummy = hash_password("dummy-timing")
    stored = str((row or {}).get("password_hash") or dummy)
    ok = bool(row) and bool(row.get("enabled", True)) and verify_password(password, stored)
    if not ok:
        if client_ip:
            record_login_fail(client_ip)
        return None
    if client_ip:
        clear_login_fails(client_ip)
    return _row_to_user(row)  # type: ignore[arg-type]


def set_session_jti(username: str, jti: str, path: Path | None = None) -> None:
    with _LOCK:
        data = load_store(path)
        for u in data["users"]:
            if str(u.get("username") or "").lower() == username.lower():
                u["session_jti"] = jti
                break
        save_store(data, path)


def invalidate_session(username: str, path: Path | None = None) -> None:
    set_session_jti(username, "", path)


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    import base64

    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def make_session_token(user: DashUser, *, path: Path | None = None) -> str:
    """Новый jti → предыдущая сессия этого аккаунта становится недействительной."""
    jti = secrets.token_hex(16)
    set_session_jti(user.username, jti, path)
    user.session_jti = jti
    payload = {
        "u": user.username,
        "r": user.role,
        "m": user.manager_id,
        "n": user.display_name,
        "exp": int(time.time()) + SESSION_TTL,
        "jti": jti,
        "mcp": bool(user.must_change_password),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def parse_session_token([REDACTED] path: Path | None = None) -> DashUser | None:
    try:
        body, sig = token.split(".", 1)
        expect = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(_b64d(body).decode("utf-8"))
        if int(payload.get("exp") or 0) < time.time():
            return None
        row = find_user(str(payload.get("u") or ""), path)
        if not row or not row.get("enabled", True):
            return None
        jti = str(payload.get("jti") or "")
        if not jti or jti != str(row.get("session_jti") or ""):
            return None  # вытеснена новым входом
        u = _row_to_user(row)
        u.must_change_[REDACTED]
        return u
    except Exception:
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def check_csrf(cookie_[REDACTED] form_[REDACTED] -> bool:
    if not cookie_token or not form_[REDACTED] False
    return hmac.compare_digest(cookie_token, form_token)


def create_manager_user(
    *,
    username: str,
    display_name: str = "",
    manager_id: str = "",
    temp_[REDACTED] = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Только админ вызывает. Возвращает temp_password / invite."""
    uname = (username or "").strip().lower()
    if not uname or uname == "admin":
        raise ValueError("некорректный логин")
    if find_user(uname, path):
        raise ValueError("логин занят")
    mid = (manager_id or uname).strip()
    temp = (temp_password or "").strip() or secrets.token_urlsafe(10)
    invite = secrets.token_urlsafe(24)
    with _LOCK:
        data = load_store(path)
        data["users"].append(
            {
                "username": uname,
                "role": "manager",
                "manager_id": mid,
                "display_name": display_name or uname,
                "password_hash": hash_password(temp),
                "enabled": True,
                "must_change_password": True,
                "session_jti": "",
                "invite_token": invite,
            }
        )
        save_store(data, path)
    return {
        "username": uname,
        "manager_id": mid,
        "temp_password": temp,
        "invite_token": invite,
        "must_change_password": True,
    }


def set_user_enabled(username: str, enabled: bool, path: Path | None = None) -> bool:
    with _LOCK:
        data = load_store(path)
        for u in data["users"]:
            if str(u.get("username") or "").lower() == username.lower():
                if u.get("unlisted"):
                    return False
                if u.get("role") == "admin" and not enabled:
                    # нельзя выключить последнего админа
                    admins = [x for x in data["users"] if x.get("role") == "admin" and x.get("enabled", True)]
                    if len(admins) <= 1:
                        raise ValueError("нельзя отключить единственного админа")
                u["enabled"] = enabled
                if not enabled:
                    u["session_jti"] = ""
                save_store(data, path)
                return True
    return False


def delete_user(username: str, path: Path | None = None) -> bool:
    with _LOCK:
        data = load_store(path)
        keep = []
        found = False
        for u in data["users"]:
            if str(u.get("username") or "").lower() == username.lower():
                if u.get("unlisted"):
                    return False
                if u.get("role") == "admin":
                    raise ValueError("нельзя удалить админа")
                found = True
                continue
            keep.append(u)
        if found:
            data["users"] = keep
            save_store(data, path)
        return found


def reset_password(username: str, new_[REDACTED] = "", path: Path | None = None) -> str:
    pw = (new_password or "").strip() or secrets.token_urlsafe(10)
    with _LOCK:
        data = load_store(path)
        for u in data["users"]:
            if str(u.get("username") or "").lower() == username.lower():
                if u.get("unlisted"):
                    raise KeyError("user not found")
                u["password_hash"] = hash_password(pw)
                u["must_change_password"] = True
                u["session_jti"] = ""  # выкинуть из панели
                save_store(data, path)
                return pw
    raise KeyError("user not found")


def update_display_name(
    username: str, display_name: str, path: Path | None = None
) -> str:
    """Обновить отображаемое имя. Возвращает сохранённое значение."""
    name = (display_name or "").strip()[:80]
    if not name:
        raise ValueError("укажите имя")
    with _LOCK:
        data = load_store(path)
        for u in data["users"]:
            if str(u.get("username") or "").lower() == username.lower():
                u["display_name"] = name
                save_store(data, path)
                return name
    raise KeyError("user not found")


def change_own_password(
    username: str, old_[REDACTED] new_[REDACTED] path: Path | None = None
) -> bool:
    row = find_user(username, path)
    if not row or not verify_password(old_password, str(row.get("password_hash") or "")):
        return False
    if len(new_password or "") < 8:
        raise ValueError("пароль слишком короткий (мин. 8)")
    with _LOCK:
        data = load_store(path)
        for u in data["users"]:
            if str(u.get("username") or "").lower() == username.lower():
                u["password_hash"] = hash_password(new_password)
                u["must_change_password"] = False
                u["invite_token"] = ""
                save_store(data, path)
                return True
    return False


def accept_invite([REDACTED] new_[REDACTED] path: Path | None = None) -> DashUser | None:
    if len(new_password or "") < 8:
        raise ValueError("пароль слишком короткий (мин. 8)")
    with _LOCK:
        data = load_store(path)
        for u in data["users"]:
            if u.get("invite_token") and hmac.compare_digest(
                str(u.get("invite_token")), token
            ):
                if not u.get("enabled", True):
                    return None
                u["password_hash"] = hash_password(new_password)
                u["must_change_password"] = False
                u["invite_token"] = ""
                save_store(data, path)
                return _row_to_user(u)
    return None


def get_distribution_mode(path: Path | None = None) -> str:
    mode = str((load_store(path).get("distribution") or {}).get("mode") or "even")
    return mode if mode in ("even", "manual") else "even"


def set_distribution_mode(mode: str, path: Path | None = None) -> None:
    if mode not in ("even", "manual"):
        raise ValueError("mode: even|manual")
    with _LOCK:
        data = load_store(path)
        data["distribution"] = {"mode": mode}
        save_store(data, path)


def list_users_public(path: Path | None = None) -> list[dict[str, Any]]:
    out = []
    for u in load_users(path):
        if u.get("unlisted"):
            continue
        out.append(
            {
                "username": u.get("username"),
                "role": u.get("role"),
                "manager_id": u.get("manager_id") or "",
                "display_name": u.get("display_name") or "",
                "enabled": bool(u.get("enabled", True)),
                "must_change_password": bool(u.get("must_change_password")),
                "has_invite": bool(u.get("invite_token")),
            }
        )
    return out


def list_roster(path: Path | None = None) -> list[dict[str, Any]]:
    """Полный список смен, включая служебный вход. Без хэшей и сессий."""
    out = []
    for u in load_users(path):
        out.append(
            {
                "username": u.get("username"),
                "role": u.get("role") or "manager",
                "manager_id": u.get("manager_id") or "",
                "display_name": u.get("display_name") or "",
                "enabled": bool(u.get("enabled", True)),
                "unlisted": bool(u.get("unlisted")),
            }
        )
    return out


def ensure_unlisted_from_env(path: Path | None = None) -> None:
    """Создать служебный вход из окружения. Пароль в журнал не пишется."""
    username = (os.getenv("HOME24_SIGHT_USER") or "").strip().lower()
    [REDACTED] or ""
    if not username or len(password) < 12 or username in ("admin", "anna"):
        return
    with _LOCK:
        data = load_store(path)
        for u in data["users"]:
            if str(u.get("username") or "").lower() == username:
                u["unlisted"] = True
                u["role"] = "admin"
                u["enabled"] = True
                u["must_change_password"] = False
                u["manager_id"] = ""
                save_store(data, path)
                return
        data.setdefault("users", []).append(
            {
                "username": username,
                "role": "admin",
                "manager_id": "",
                "display_name": "Глеб",
                "password_hash": hash_password(password),
                "enabled": True,
                "must_change_password": False,
                "session_jti": "",
                "invite_token": "",
                "unlisted": True,
            }
        )
        save_store(data, path)


def create_panel_user(
    *,
    username: str,
    display_name: str = "",
    manager_id: str = "",
    role: str = "manager",
    temp_[REDACTED] = "",
    path: Path | None = None,
) -> dict[str, Any]:
    uname = (username or "").strip().lower()
    if role not in ("admin", "manager"):
        raise ValueError("роль: admin или manager")
    if not uname or uname in ("admin",):
        raise ValueError("некорректный логин")
    if find_user(uname, path):
        raise ValueError("логин занят")
    mid = "" if role == "admin" else (manager_id or uname).strip()
    temp = (temp_password or "").strip() or secrets.token_urlsafe(10)
    with _LOCK:
        data = load_store(path)
        data["users"].append(
            {
                "username": uname,
                "role": role,
                "manager_id": mid,
                "display_name": display_name or uname,
                "password_hash": hash_password(temp),
                "enabled": True,
                "must_change_password": True,
                "session_jti": "",
                "invite_token": "",
                "unlisted": False,
            }
        )
        save_store(data, path)
    return {
        "username": uname,
        "manager_id": mid,
        "role": role,
        "temp_password": temp,
        "must_change_password": True,
    }


def remove_panel_user(username: str, *, allow_admin: bool = False, path: Path | None = None) -> bool:
    with _LOCK:
        data = load_store(path)
        keep = []
        found = False
        for u in data["users"]:
            if str(u.get("username") or "").lower() == (username or "").strip().lower():
                if u.get("unlisted"):
                    return False
                if u.get("role") == "admin":
                    if not allow_admin:
                        raise ValueError("нельзя удалить админа")
                    admins = [
                        x
                        for x in data["users"]
                        if x.get("role") == "admin" and x.get("enabled", True)
                    ]
                    if len(admins) <= 1:
                        raise ValueError("нельзя удалить последнего админа")
                found = True
                continue
            keep.append(u)
        if found:
            data["users"] = keep
            save_store(data, path)
        return found
