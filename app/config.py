"""Конфигурация приложения: Telegram API, бот уведомлений и пути к данным."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
DB_PATH = DATA_DIR / "app.db"
CONFIG_PATH = DATA_DIR / "config.json"
EXPORT_DIR = DATA_DIR / "exports"

DATA_DIR.mkdir(exist_ok=True)
SESSIONS_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)

load_dotenv(ROOT / ".env")


def _load_file_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text("utf-8"))
        except Exception:
            return {}
    return {}


def _save_file_config(cfg: dict) -> None:
    """Атомарно сохраняет секреты в файл, доступный только владельцу."""
    temp_path = CONFIG_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)


def get_api_credentials() -> tuple[Optional[int], Optional[str]]:
    """api_id/api_hash: сначала .env, потом сохранённый через веб-интерфейс config.json."""
    api_id = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    if not api_id or not api_hash:
        cfg = _load_file_config()
        api_id = api_id or cfg.get("api_id")
        api_hash = api_hash or cfg.get("api_hash")
    try:
        api_id_int = int(api_id) if api_id else None
    except (TypeError, ValueError):
        api_id_int = None
    return api_id_int, (api_hash or None)


def save_api_credentials(api_id: int, api_hash: str) -> None:
    cfg = _load_file_config()
    cfg["api_id"] = int(api_id)
    cfg["api_hash"] = api_hash
    _save_file_config(cfg)


def get_bot_settings() -> tuple[Optional[str], Optional[str]]:
    """Токен бота и сохранённый username; токен может быть задан через окружение."""
    cfg = _load_file_config()
    token = os.getenv("TG_BOT_TOKEN") or cfg.get("bot_token")
    username = cfg.get("bot_username")
    return (token or None), (username or None)


def save_bot_settings(token: str, username: str) -> None:
    cfg = _load_file_config()
    clean_token = token.strip()
    clean_username = username.strip().lstrip("@")
    if cfg.get("bot_token") != clean_token or cfg.get("bot_username") != clean_username:
        # Получателя нужно подтвердить заново для каждого нового бота.
        cfg.pop("bot_chat_id", None)
        cfg.pop("bot_recipient_label", None)
        cfg.pop("bot_update_offset", None)
    cfg["bot_token"] = clean_token
    cfg["bot_username"] = clean_username
    _save_file_config(cfg)


def get_bot_recipient() -> tuple[Optional[int], Optional[str]]:
    """Возвращает сохранённый личный чат для уведомлений без раскрытия токена."""
    cfg = _load_file_config()
    try:
        chat_id = int(cfg["bot_chat_id"]) if cfg.get("bot_chat_id") is not None else None
    except (TypeError, ValueError):
        chat_id = None
    label = cfg.get("bot_recipient_label")
    return chat_id, (str(label) if label else None)


def save_bot_recipient(chat_id: int, label: str) -> None:
    cfg = _load_file_config()
    cfg["bot_chat_id"] = int(chat_id)
    cfg["bot_recipient_label"] = label.strip() or "Личный чат Telegram"
    _save_file_config(cfg)


def get_bot_update_offset() -> Optional[int]:
    cfg = _load_file_config()
    try:
        return int(cfg["bot_update_offset"]) if cfg.get("bot_update_offset") is not None else None
    except (TypeError, ValueError):
        return None


def save_bot_update_offset(offset: int) -> None:
    cfg = _load_file_config()
    cfg["bot_update_offset"] = int(offset)
    _save_file_config(cfg)


# Дефолты лимитов для нового аккаунта. Специально консервативные:
# превышение приводит к PEER_FLOOD, silent loss и риску для целевого чата.
# Масштаб — числом аккаунтов с отдельным IP, не скоростью одного.
DEFAULT_DAILY_LIMIT = 2
DEFAULT_MIN_DELAY = 15 * 60   # секунд между инвайтами одного аккаунта
DEFAULT_MAX_DELAY = 25 * 60
DEFAULT_BATCH_SIZE = 2        # после стольких confirmed/armed RPC — длинная пауза
DEFAULT_BATCH_PAUSE = 45 * 60
# Тихие потери подряд без confirmed → снять аккаунт с ротации до ручного restore.
SILENT_LOSS_RESTRICT_THRESHOLD = 2
SILENT_LOSS_LOOKBACK_SECONDS = 7 * 24 * 3600
