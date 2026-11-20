from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from pathlib import Path

from dotenv import load_dotenv

# .env рядом с рабочей папкой процесса (run_windows.bat делает cd в бандл)
load_dotenv(Path.cwd() / ".env")
load_dotenv()


def _ids(raw: str) -> set[int]:
    out: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    session: str
    admin_ids: set[int]
    manager_name: str
    brand: str
    site_url: str
    loyalty_url: str
    channel_url: str
    vk_url: str
    openai_key: str
    openai_base: str
    openai_model: str
    outreach_delay: float
    db_path: str
    script_path: str

    @property
    def ai_ready(self) -> bool:
        # любой из ключей dual-AI
        import os

        return bool(
            self.openai_key.strip()
            or (os.getenv("AI1_API_KEY") or "").strip()
            or (os.getenv("AI2_API_KEY") or "").strip()
            or (os.getenv("AI3_API_KEY") or "").strip()
            or (os.getenv("GROQ_API_KEY") or "").strip()
        )


@lru_cache
def get_settings() -> Settings:
    from bot.telegram_api import resolve_api_credentials

    # Без дефолта api_id=6: только свои ключи с my.telegram.org
    try:
        api_id, api_hash = resolve_api_credentials()
    except Exception:
        # Settings могут читаться до проверки (панель); TelegramClient не стартует
        # без повторной проверки в login/main.
        raw = (os.getenv("TELEGRAM_API_ID") or "").strip()
        api_id = int(raw) if raw.isdigit() else 0
        api_hash = (os.getenv("TELEGRAM_API_HASH") or "").strip()
    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        session=(os.getenv("TELEGRAM_SESSION") or "").strip(),
        admin_ids=_ids(os.getenv("ADMIN_USER_IDS") or ""),
        manager_name=os.getenv("MANAGER_DISPLAY_NAME") or "Анна",
        brand=os.getenv("BRAND_NAME") or "Home24",
        site_url=os.getenv("SITE_URL") or "https://home24.msk.ru/",
        loyalty_url=os.getenv("LOYALTY_URL") or "https://home24.msk.ru/loyalty",
        channel_url=os.getenv("CHANNEL_URL") or "https://t.me/home24_msk",
        vk_url=os.getenv("VK_URL") or "https://vk.ru/club172662058",
        openai_key=(os.getenv("OPENAI_API_KEY") or "").strip(),
        openai_base=os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        openai_model=os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
        outreach_delay=float(os.getenv("OUTREACH_DELAY_SEC") or "50"),
        db_path=os.getenv("DATABASE_PATH") or "data/home24.db",
        script_path=os.getenv("SCRIPT_PATH") or "script.md",
    )
