from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.config import (
    DEFAULT_BATCH_PAUSE,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DAILY_LIMIT,
    DEFAULT_MAX_DELAY,
    DEFAULT_MIN_DELAY,
)


class ApiCreds(BaseModel):
    api_id: int
    api_hash: str


class BotTokenIn(BaseModel):
    bot_token: str


class AccountIn(BaseModel):
    label: str
    phone: str
    proxy: Optional[str] = None
    can_parse: bool = True
    can_invite: bool = True
    daily_limit: int = DEFAULT_DAILY_LIMIT
    min_delay: int = DEFAULT_MIN_DELAY
    max_delay: int = DEFAULT_MAX_DELAY
    batch_size: int = DEFAULT_BATCH_SIZE
    batch_pause: int = DEFAULT_BATCH_PAUSE


class AccountPatch(BaseModel):
    label: Optional[str] = None
    proxy: Optional[str] = None
    can_parse: Optional[bool] = None
    can_invite: Optional[bool] = None
    daily_limit: Optional[int] = None
    min_delay: Optional[int] = None
    max_delay: Optional[int] = None
    batch_size: Optional[int] = None
    batch_pause: Optional[int] = None


class CodeIn(BaseModel):
    code: str


class PasswordIn(BaseModel):
    password: str


class ParseIn(BaseModel):
    account_id: int
    chat: str
    sources: List[str] = ["participants", "history"]
    deep: bool = False
    participants_limit: Optional[int] = None
    messages_limit: Optional[int] = 5000   # None — вся история
    posts_limit: Optional[int] = 100


class ParseAllIn(BaseModel):
    chat: str
    account_ids: List[int] = []       # пусто — все авторизованные парсеры
    sources: List[str] = ["participants", "history"]
    deep: bool = False
    participants_limit: Optional[int] = None
    messages_limit: Optional[int] = 5000   # None — вся история
    posts_limit: Optional[int] = 100
    gap: int = 30                     # пауза между аккаунтами, секунд


class CampaignIn(BaseModel):
    name: str
    target_chat: str
    account_ids: List[int]
    source_chat_ids: List[int]
    filters: Dict[str, Any] = {}


class TargetSyncIn(BaseModel):
    account_id: int
    target_chat: str


class CsvImportIn(BaseModel):
    name: str = "Импорт CSV"
    csv_text: str
