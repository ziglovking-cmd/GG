from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from app import accounts, db, parsing
from app.api.schemas import AccountIn, AccountPatch, CodeIn, PasswordIn


router = APIRouter()


@router.get("/api/accounts")
def list_accounts():
    rows = db.rows_to_dicts(db.q("SELECT * FROM accounts ORDER BY id"))
    now = int(time.time())
    for r in rows:
        r["cooldown_left"] = max(0, int(r["cooldown_until"] or 0) - now)
        r["next_attempt_in"] = max(0, int(r.get("next_attempt_at") or 0) - now)
        r["quota_left"] = accounts.quota_left(r)
        eligible, eligibility_code, eligibility_detail = accounts.invite_eligibility(r)
        r["invite_eligible"] = eligible
        r["invite_eligibility_code"] = eligibility_code
        r["invite_eligibility_detail"] = eligibility_detail
        r["hashes"] = db.q1("SELECT COUNT(*) c FROM hashes WHERE account_id=?", (r["id"],))["c"]
    return rows


@router.post("/api/accounts")
def create_account(body: AccountIn):
    phone = body.phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")
    session_name = "acc_" + "".join(ch for ch in phone if ch.isdigit())
    if db.q1("SELECT id FROM accounts WHERE session_name=?", (session_name,)):
        raise HTTPException(400, "Аккаунт с таким номером уже добавлен")
    account_id = db.ex(
        """INSERT INTO accounts (label,phone,session_name,proxy,can_parse,can_invite,
                                 daily_limit,min_delay,max_delay,batch_size,batch_pause,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (body.label or phone, phone, session_name, body.proxy,
         int(body.can_parse), int(body.can_invite), body.daily_limit, body.min_delay,
         body.max_delay, body.batch_size, body.batch_pause, int(time.time())),
    )
    return {"id": account_id}


@router.patch("/api/accounts/{account_id}")
async def patch_account(account_id: int, body: AccountPatch):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return {"ok": True}
    if "can_parse" in fields:
        fields["can_parse"] = int(fields["can_parse"])
    if "can_invite" in fields:
        fields["can_invite"] = int(fields["can_invite"])
    sql = "UPDATE accounts SET " + ",".join("%s=?" % k for k in fields) + " WHERE id=?"
    db.ex(sql, list(fields.values()) + [account_id])
    if "proxy" in fields:
        await accounts.drop_client(account_id)  # переподключение через новый прокси
    return {"ok": True}


@router.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int):
    await accounts.drop_client(account_id)
    db.ex("DELETE FROM hashes WHERE account_id=?", (account_id,))
    db.ex("DELETE FROM accounts WHERE id=?", (account_id,))
    return {"ok": True}


@router.post("/api/accounts/{account_id}/code")
async def account_send_code(account_id: int):
    try:
        return {"status": await accounts.send_code(account_id)}
    except accounts.AuthError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/api/accounts/{account_id}/signin")
async def account_sign_in(account_id: int, body: CodeIn):
    try:
        return {"status": await accounts.sign_in(account_id, body.code)}
    except accounts.AuthError as e:
        raise HTTPException(400, str(e))


@router.post("/api/accounts/{account_id}/password")
async def account_password(account_id: int, body: PasswordIn):
    try:
        return {"status": await accounts.sign_in_password(account_id, body.password)}
    except accounts.AuthError as e:
        raise HTTPException(400, str(e))


@router.post("/api/accounts/{account_id}/check")
async def account_check(account_id: int):
    return {"status": await accounts.refresh_status(account_id)}


@router.post("/api/accounts/{account_id}/logout")
async def account_logout(account_id: int):
    await accounts.logout(account_id)
    return {"ok": True}


@router.post("/api/accounts/{account_id}/test_proxy")
async def account_test_proxy(account_id: int):
    try:
        return await accounts.test_proxy(account_id)
    except accounts.AuthError as e:
        raise HTTPException(400, str(e))


@router.post("/api/accounts/{account_id}/reset_cooldown")
def account_reset_cooldown(account_id: int):
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
    if not account:
        raise HTTPException(404, "Аккаунт не найден")
    if account.get("invite_restricted"):
        raise HTTPException(
            400,
            "PEER_FLOOD нельзя снять как обычную паузу. Дождитесь её окончания "
            "и используйте явное восстановление инвайтинга.",
        )
    db.ex("UPDATE accounts SET cooldown_until=0 WHERE id=?", (account_id,))
    return {"ok": True}


@router.post("/api/accounts/{account_id}/restore_invites")
def account_restore_invites(account_id: int):
    try:
        accounts.restore_invites(account_id)
    except accounts.AuthError as error:
        raise HTTPException(400, str(error))
    db.log(
        "Постоянное ограничение инвайтинга снято вручную оператором",
        level="warn",
        scope="limits",
        account_id=account_id,
    )
    return {"ok": True}


@router.get("/api/dialogs/{account_id}")
async def dialogs(account_id: int):
    try:
        return await parsing.list_dialogs(account_id)
    except Exception as e:
        raise HTTPException(400, str(e))
