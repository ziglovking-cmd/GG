from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from app import db


router = APIRouter()


@router.get("/api/events")
def events(limit: int = 100, campaign_id: Optional[int] = None):
    if campaign_id:
        rows = db.q("SELECT * FROM events WHERE campaign_id=? ORDER BY id DESC LIMIT ?",
                    (campaign_id, limit))
    else:
        rows = db.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    return db.rows_to_dicts(rows)
