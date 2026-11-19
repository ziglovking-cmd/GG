from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import ApiCreds
from app.config import (
    DEFAULT_BATCH_PAUSE,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DAILY_LIMIT,
    DEFAULT_MAX_DELAY,
    DEFAULT_MIN_DELAY,
    get_api_credentials,
    save_api_credentials,
)


router = APIRouter()


@router.get("/api/settings")
def get_settings():
    api_id, api_hash = get_api_credentials()
    return {
        "api_id": api_id,
        "api_hash_set": bool(api_hash),
        "defaults": {
            "daily_limit": DEFAULT_DAILY_LIMIT,
            "min_delay": DEFAULT_MIN_DELAY,
            "max_delay": DEFAULT_MAX_DELAY,
            "batch_size": DEFAULT_BATCH_SIZE,
            "batch_pause": DEFAULT_BATCH_PAUSE,
        },
    }


@router.post("/api/settings")
def post_settings(body: ApiCreds):
    save_api_credentials(body.api_id, body.api_hash)
    return {"ok": True}
