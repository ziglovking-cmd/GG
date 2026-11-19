from __future__ import annotations

import csv
import io
import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import accounts, db, inviting, parsing, preflight
from app.api.schemas import CampaignIn, TargetSyncIn
from app.infrastructure.bot import client


router = APIRouter()


@router.post("/api/campaigns/sync-target")
async def sync_campaign_target(body: TargetSyncIn):
    try:
        return await parsing.sync_target_members(body.account_id, body.target_chat.strip())
    except Exception as e:
        raise HTTPException(400, "Не удалось получить участников целевого чата: %s" % e)


@router.get("/api/campaigns")
def list_campaigns():
    rows = db.rows_to_dicts(db.q("SELECT * FROM campaigns ORDER BY id DESC"))
    for r in rows:
        r["stats"] = inviting.campaign_stats(r["id"])
        r["settings"] = db.settings_of(r)
        r["running"] = r["id"] in inviting.RUNNERS and not inviting.RUNNERS[r["id"]].done()
    return rows


@router.post("/api/campaigns")
async def create_campaign(body: CampaignIn):
    if not body.account_ids:
        raise HTTPException(400, "Выберите хотя бы один аккаунт-инвайтер")
    if not body.source_chat_ids:
        raise HTTPException(400, "Выберите хотя бы один чат-донор")

    # целевой чат резолвим первым аккаунтом, чтобы записать его id и название
    try:
        client = await accounts.get_client(body.account_ids[0])
        ref = body.target_chat.strip()
        entity = await client.get_entity(int(ref) if ref.lstrip("-").isdigit() else ref)
    except Exception as e:
        raise HTTPException(400, "Не удалось открыть целевой чат: %s" % e)

    parsing.upsert_chat(entity)
    settings = {"account_ids": body.account_ids,
                "source_chat_ids": body.source_chat_ids,
                "filters": body.filters}
    campaign_id = db.ex(
        "INSERT INTO campaigns (name,target_chat_id,target_title,settings,status,created_at) "
        "VALUES (?,?,?,?, 'draft', ?)",
        (body.name, entity.id, getattr(entity, "title", ""),
         inviting.settings_json(settings), int(time.time())),
    )
    count = inviting.build_targets(campaign_id, body.source_chat_ids, body.filters)
    db.log("Кампания «%s» создана, целей: %d" % (body.name, count),
           scope="invite", campaign_id=campaign_id)
    return {"id": campaign_id, "targets": count}


@router.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: int):
    row = db.row_to_dict(db.q1("SELECT * FROM campaigns WHERE id=?", (campaign_id,)))
    if not row:
        raise HTTPException(404, "Кампания не найдена")
    row["settings"] = db.settings_of(row)
    row["stats"] = inviting.campaign_stats(campaign_id)
    row["running"] = campaign_id in inviting.RUNNERS and not inviting.RUNNERS[campaign_id].done()
    state = inviting.STATE.get(campaign_id, {})
    result_counts = {
        int(item["account_id"]): item
        for item in db.rows_to_dicts(db.q(
            """
            SELECT account_id,
                   SUM(CASE WHEN status='invited' THEN 1 ELSE 0 END) AS confirmed,
                   SUM(CASE WHEN status='verifying' THEN 1 ELSE 0 END) AS verifying
            FROM targets
            WHERE campaign_id=? AND account_id IS NOT NULL
            GROUP BY account_id
            """,
            (campaign_id,),
        ))
    }
    now = int(time.time())

    last_attempts = {
        int(item["account_id"]): item
        for item in db.rows_to_dicts(db.q(
            """
            SELECT * FROM (
                SELECT id,account_id,user_id,username,status,error,attempted_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY account_id ORDER BY attempted_at DESC,id DESC
                       ) AS attempt_rank
                FROM targets
                WHERE campaign_id=? AND account_id IS NOT NULL
                  AND attempted_at IS NOT NULL
            ) WHERE attempt_rank=1
            """,
            (campaign_id,),
        ))
    }

    def worker_payload(aid: int, info: Dict[str, Any]) -> Dict[str, Any]:
        account = db.q1(
            "SELECT label,next_attempt_at,cooldown_until FROM accounts WHERE id=?",
            (aid,),
        ) or {"label": aid, "next_attempt_at": 0, "cooldown_until": 0}
        counts = result_counts.get(aid, {})
        worker_info = dict(info)
        if (
            str(worker_info.get("state") or "").startswith("до следующей попытки")
            and int(account["next_attempt_at"] or 0) <= now
            and int(account["cooldown_until"] or 0) <= now
            and int(counts.get("verifying") or 0) == 0
        ):
            worker_info["state"] = "готов к следующей цели"
        return {
            "account_id": aid,
            "label": account["label"],
            **worker_info,
            # В интерфейсе попыткой считается только подтверждённое присутствие.
            "done": int(counts.get("confirmed") or 0),
            "attempted": int(counts.get("confirmed") or 0),
            "awaiting_confirmation": int(counts.get("verifying") or 0),
            "last_attempt": last_attempts.get(aid),
            "campaign_wait_in": max(0, int(row.get("next_invite_at") or 0) - now),
        }

    worker_ids = dict.fromkeys([
        *(row["settings"].get("account_ids") or []),
        *(state.get("workers") or {}).keys(),
        *last_attempts.keys(),
    ])
    row["workers"] = [
        worker_payload(aid, (state.get("workers") or {}).get(aid, {"not_started": True}))
        for aid in worker_ids
    ]
    row["recent"] = db.rows_to_dicts(db.q(
        "SELECT * FROM targets WHERE campaign_id=? AND attempted_at IS NOT NULL "
        "ORDER BY attempted_at DESC LIMIT 30", (campaign_id,)))
    return row


@router.get("/api/campaigns/{campaign_id}/preflight")
def get_campaign_preflight(campaign_id: int):
    try:
        return preflight.get(campaign_id)
    except preflight.PreflightError as e:
        raise HTTPException(404, str(e))


@router.post("/api/campaigns/{campaign_id}/preflight")
async def start_campaign_preflight(campaign_id: int):
    try:
        return preflight.start(campaign_id)
    except preflight.PreflightError as e:
        raise HTTPException(400, str(e))


@router.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: int):
    if not db.q1("SELECT id FROM campaigns WHERE id=?", (campaign_id,)):
        raise HTTPException(404, "Кампания не найдена")
    if preflight.is_running(campaign_id):
        raise HTTPException(400, "Дождитесь завершения предварительной проверки")
    inviting.start(campaign_id)
    return {"ok": True}


@router.post("/api/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: int):
    inviting.stop(campaign_id)
    return {"ok": True}


@router.post("/api/campaigns/{campaign_id}/accounts/{account_id}/recover")
async def recover_campaign_account(campaign_id: int, account_id: int):
    try:
        return await inviting.recover_campaign_account(campaign_id, account_id)
    except inviting.WorkerRecoveryError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int):
    runner = inviting.RUNNERS.get(campaign_id)
    if runner is not None and not runner.done():
        raise HTTPException(
            409,
            "Сначала остановите кампанию и дождитесь завершения её воркеров",
        )
    ambiguous = db.q1(
        "SELECT COUNT(*) c FROM targets WHERE campaign_id=? "
        "AND status IN ('in_progress','verifying')",
        (campaign_id,),
    )
    if ambiguous and int(ambiguous["c"] or 0):
        raise HTTPException(
            409,
            "Кампанию нельзя удалить, пока сохраняется незавершённый или "
            "неоднозначный Invite RPC",
        )
    inviting.stop(campaign_id)
    if not db.delete_campaign(campaign_id):
        raise HTTPException(404, "Кампания не найдена")
    return {"ok": True}


@router.get("/api/campaigns/{campaign_id}/export")
def export_campaign(campaign_id: int):
    rows = db.q("SELECT * FROM targets WHERE campaign_id=? ORDER BY id", (campaign_id,))
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["user_id", "username", "display", "status", "account_id", "error"])
    for r in rows:
        writer.writerow([r["user_id"], r["username"] or "", r["display"] or "", r["status"],
                         r["account_id"] or "", r["error"] or ""])
    return StreamingResponse(
        iter([("﻿" + buf.getvalue()).encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="campaign_%d.csv"' % campaign_id},
    )
