"""Предварительная проверка кампании без отправки приглашений."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from telethon.errors import FloodWaitError, RPCError, UserNotParticipantError
from telethon.tl.types import User

from . import accounts, db, inviting


JOBS: Dict[int, Dict[str, Any]] = {}
TASKS: Dict[int, asyncio.Task] = {}
ACCOUNT_CHECK_CONCURRENCY = 4
ACCOUNT_CHECK_ATTEMPTS = 2
ACCOUNT_CHECK_RETRY_PAUSE = 2
ACCOUNT_CLEANUP_TIMEOUT = 5
TARGET_CHECK_CONCURRENCY = 12
TARGET_REQUEST_PAUSE = 0.35
REQUEST_TIMEOUT = 30


class PreflightError(Exception):
    """Проверку нельзя запустить в текущем состоянии кампании."""


def _blank_job(campaign_id: int, accounts_total: int, targets_total: int) -> Dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "status": "running",
        "phase": "accounts",
        "message": "Проверяю аккаунты-инвайтеры",
        "started_at": int(time.time()),
        "finished_at": None,
        "accounts": {
            "total": accounts_total,
            "checked": 0,
            "ready": 0,
            "items": [],
        },
        "targets": {
            "total": targets_total,
            "checked": 0,
            "valid": 0,
            "invalid": 0,
            "bots": 0,
            "deleted": 0,
            "duplicates": 0,
            "no_hash": 0,
            "technical": 0,
        },
    }


def _public_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in job.items() if not key.startswith("_")}


def _persist(job: Dict[str, Any]) -> None:
    payload = _public_job(job)
    db.ex(
        "UPDATE campaigns SET preflight_status=?,preflight_summary=?,"
        "preflight_checked_at=? WHERE id=?",
        (
            payload["status"],
            json.dumps(payload, ensure_ascii=False),
            int(payload.get("finished_at") or time.time()),
            int(payload["campaign_id"]),
        ),
    )


def get(campaign_id: int) -> Dict[str, Any]:
    runtime = JOBS.get(campaign_id)
    if runtime:
        return _public_job(runtime)
    row = db.q1(
        "SELECT preflight_status,preflight_summary,preflight_checked_at "
        "FROM campaigns WHERE id=?",
        (campaign_id,),
    )
    if not row:
        raise PreflightError("Кампания не найдена")
    if row["preflight_summary"]:
        try:
            result = json.loads(row["preflight_summary"])
            if result.get("status") == "running":
                result["status"] = "interrupted"
                result["message"] = "Проверка прервалась при перезапуске сайта — запустите её ещё раз"
            return result
        except (TypeError, ValueError):
            pass
    return {
        "campaign_id": campaign_id,
        "status": row["preflight_status"] or "not_run",
        "checked_at": row["preflight_checked_at"],
    }


def is_running(campaign_id: int) -> bool:
    task = TASKS.get(campaign_id)
    return bool(task and not task.done())


def start(campaign_id: int) -> Dict[str, Any]:
    campaign = db.row_to_dict(db.q1("SELECT * FROM campaigns WHERE id=?", (campaign_id,)))
    if not campaign:
        raise PreflightError("Кампания не найдена")
    if campaign["status"] == "running" or campaign_id in inviting.RUNNERS:
        raise PreflightError("Сначала остановите кампанию: проверка не выполняется во время инвайтинга")
    if is_running(campaign_id):
        return get(campaign_id)

    settings = db.settings_of(campaign)
    account_ids = [int(value) for value in settings.get("account_ids", [])]
    targets_total = int(
        db.q1(
            "SELECT COUNT(*) c FROM targets WHERE campaign_id=? AND status='pending'",
            (campaign_id,),
        )["c"]
    )
    job = _blank_job(campaign_id, len(account_ids), targets_total)
    JOBS[campaign_id] = job
    _persist(job)
    task = asyncio.create_task(_run(campaign, account_ids, job))
    TASKS[campaign_id] = task
    task.add_done_callback(lambda _: TASKS.pop(campaign_id, None))
    return _public_job(job)


def _account_result(account_id: int, label: str, status: str, detail: str,
                    ready: bool = False) -> Dict[str, Any]:
    return {
        "account_id": account_id,
        "label": label,
        "status": status,
        "detail": detail,
        "ready": ready,
    }


async def _reset_account_client(account_id: int) -> None:
    """Закрывает зависшее/устаревшее соединение перед чистой проверкой."""
    try:
        await asyncio.wait_for(
            accounts.drop_client(account_id), ACCOUNT_CLEANUP_TIMEOUT
        )
    except Exception:
        # Следующая попытка всё равно ограничена общим тайм-аутом. Ошибка
        # очистки не должна блокировать проверку остальных аккаунтов.
        pass


async def _probe_account(campaign: Dict[str, Any], account_id: int,
                         label: str) -> Dict[str, Any]:
    """Один ограниченный по времени сетевой проход проверки аккаунта."""
    client = await accounts.get_client(account_id)
    if not await client.is_user_authorized():
        return _account_result(account_id, label, "unauthorized", "Telegram-сессия завершена")
    me = await client.get_me()
    entity = await inviting.resolve_target_chat(client, int(campaign["target_chat_id"]))
    try:
        await client.get_permissions(entity, me)
    except UserNotParticipantError:
        return _account_result(
            account_id, label, "not_member", "Аккаунт не состоит в целевом чате"
        )
    if not inviting.can_invite(entity):
        return _account_result(
            account_id, label, "no_rights", "В чате запрещено добавлять участников"
        )
    return _account_result(
        account_id, label, "ready", "Прокси, сессия, членство и права подтверждены", True
    )


async def _check_account(campaign: Dict[str, Any], account_id: int,
                         semaphore: asyncio.Semaphore) -> Dict[str, Any]:
    account = db.row_to_dict(db.q1("SELECT * FROM accounts WHERE id=?", (account_id,)))
    label = str((account or {}).get("label") or "Аккаунт %d" % account_id)
    if not account:
        return _account_result(account_id, label, "missing", "Аккаунт удалён")
    eligible, eligibility_code, eligibility_detail = accounts.invite_eligibility(
        account,
        check_quota=False,
    )
    if not eligible:
        return _account_result(
            account_id,
            label,
            eligibility_code,
            eligibility_detail + "; сетевую проверку не выполняю",
        )
    async with semaphore:
        last_error = ""
        for attempt in range(1, ACCOUNT_CHECK_ATTEMPTS + 1):
            await _reset_account_client(account_id)
            try:
                return await asyncio.wait_for(
                    _probe_account(campaign, account_id, label), REQUEST_TIMEOUT
                )
            except asyncio.TimeoutError:
                last_error = "Тайм-аут соединения с Telegram"
            except Exception as exc:
                last_error = "%s: %s" % (type(exc).__name__, str(exc))
            if attempt < ACCOUNT_CHECK_ATTEMPTS:
                await asyncio.sleep(ACCOUNT_CHECK_RETRY_PAUSE)
        await _reset_account_client(account_id)
        return _account_result(
            account_id,
            label,
            "technical",
            "%s (не удалось после %d попыток)" % (last_error, ACCOUNT_CHECK_ATTEMPTS),
        )


async def _run_account_checks(campaign: Dict[str, Any], account_ids: List[int],
                              job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Проверяет аккаунты и сохраняет видимый прогресс после каждого результата."""
    semaphore = asyncio.Semaphore(ACCOUNT_CHECK_CONCURRENCY)
    order = {account_id: position for position, account_id in enumerate(account_ids)}
    tasks = [
        asyncio.create_task(_check_account(campaign, account_id, semaphore))
        for account_id in account_ids
    ]
    results: List[Dict[str, Any]] = []
    try:
        for completed in asyncio.as_completed(tasks):
            result = await completed
            results.append(result)
            results.sort(key=lambda item: order.get(int(item["account_id"]), len(order)))
            job["accounts"]["items"] = list(results)
            job["accounts"]["checked"] = len(results)
            job["accounts"]["ready"] = sum(1 for item in results if item["ready"])
            job["message"] = "Проверяю аккаунты-инвайтеры: %d/%d" % (
                len(results), len(account_ids)
            )
            _persist(job)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
    return results


def _target_mark(target_id: int, preflight_status: str, error: Optional[str],
                 resolved_user_id: Optional[int] = None,
                 target_status: Optional[str] = None,
                 username: Optional[str] = None) -> None:
    fields = [
        "preflight_status=?",
        "preflight_error=?",
        "preflight_checked_at=?",
        "resolved_user_id=?",
    ]
    values: List[Any] = [preflight_status, error, int(time.time()), resolved_user_id]
    if target_status is not None:
        fields.extend(["status=?", "error=?"])
        values.extend([target_status, error])
    if username is not None:
        fields.append("username=?")
        values.append(username)
    values.append(target_id)
    db.ex("UPDATE targets SET %s WHERE id=?" % ",".join(fields), values)


def _known_target(target: Dict[str, Any], ready_ids: List[int]) -> Optional[Tuple[str, str, int]]:
    """Проверяет цель без username по уже собранным Telegram-данным."""
    user_id = int(target.get("resolved_user_id") or target.get("user_id") or 0)
    if user_id <= 0:
        return ("no_hash", "Нет username и настоящего Telegram ID", 0)
    member = db.q1(
        "SELECT MAX(is_bot) is_bot,MAX(is_deleted) is_deleted FROM members WHERE user_id=?",
        (user_id,),
    )
    if member and int(member["is_bot"] or 0):
        return ("bot", "Бот исключён предварительной проверкой", user_id)
    if member and int(member["is_deleted"] or 0):
        return ("deleted", "Удалённый аккаунт исключён предварительной проверкой", user_id)
    if not ready_ids:
        return None
    placeholders = ",".join("?" for _ in ready_ids)
    access = db.q1(
        "SELECT 1 FROM hashes WHERE user_id=? AND account_id IN (%s) LIMIT 1" % placeholders,
        [user_id] + ready_ids,
    )
    if not access:
        return ("no_hash", "Нет username и ни один выбранный инвайтер не имеет access_hash", user_id)
    return ("valid", "Настоящий Telegram ID и access_hash найдены", user_id)


async def _resolve_target(client: Any, account_id: int, target: Dict[str, Any]) -> User:
    username = str(target.get("username") or "").strip().lstrip("@")
    entity = await asyncio.wait_for(client.get_entity("@" + username), REQUEST_TIMEOUT)
    if not isinstance(entity, User):
        raise ValueError("username принадлежит не пользователю")
    if entity.access_hash is not None:
        db.ex(
            "INSERT INTO hashes (account_id,user_id,access_hash,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(account_id,user_id) DO UPDATE SET access_hash=excluded.access_hash,"
            "updated_at=excluded.updated_at",
            (account_id, entity.id, entity.access_hash, int(time.time())),
        )
    return entity


async def _run_targets(job: Dict[str, Any], ready_ids: List[int]) -> None:
    campaign_id = int(job["campaign_id"])
    rows = db.rows_to_dicts(db.q(
        "SELECT * FROM targets WHERE campaign_id=? AND status='pending' ORDER BY id",
        (campaign_id,),
    ))
    target_stats = job["targets"]
    target_stats["total"] = len(rows)
    resolved_seen: Set[int] = {
        int(row["resolved_user_id"])
        for row in db.q(
            "SELECT resolved_user_id FROM targets WHERE campaign_id=? "
            "AND resolved_user_id IS NOT NULL AND status<>'pending'",
            (campaign_id,),
        )
    }
    seen_lock = asyncio.Lock()
    stats_lock = asyncio.Lock()

    network_rows: List[Dict[str, Any]] = []
    for target in rows:
        if str(target.get("username") or "").strip():
            network_rows.append(target)
            continue
        known = _known_target(target, ready_ids)
        if known is None:
            network_rows.append(target)
            continue
        result, detail, resolved_id = known
        if result == "valid":
            if resolved_id in resolved_seen:
                result, detail = "duplicate", "Дубль настоящего Telegram ID в этой кампании"
            else:
                resolved_seen.add(resolved_id)
        status = None if result == "valid" else ("no_hash" if result == "no_hash" else "skipped")
        _target_mark(target["id"], result, None if result == "valid" else detail,
                     resolved_id or None, status)
        target_stats["checked"] += 1
        counter = {
            "bot": "bots",
            "duplicate": "duplicates",
        }.get(result, result if result in target_stats else "invalid")
        target_stats[counter] += 1

    if not network_rows:
        _persist(job)
        return
    if not ready_ids:
        target_stats["technical"] += len(network_rows)
        target_stats["checked"] += len(network_rows)
        for target in network_rows:
            _target_mark(target["id"], "technical", "Нет готового инвайтера для проверки")
        _persist(job)
        return

    queue: asyncio.Queue = asyncio.Queue()
    for target in network_rows:
        queue.put_nowait((target, 0))

    async def finish(category: str) -> None:
        async with stats_lock:
            target_stats["checked"] += 1
            target_stats[category if category in target_stats else "invalid"] += 1
            if target_stats["checked"] % 20 == 0:
                _persist(job)

    async def worker(account_id: int) -> None:
        client = await accounts.get_client(account_id)
        while True:
            try:
                target, retry = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                entity = await _resolve_target(client, account_id, target)
                if entity.bot:
                    _target_mark(target["id"], "bot", "Бот исключён предварительной проверкой",
                                 entity.id, "skipped", entity.username)
                    await finish("bots")
                elif entity.deleted:
                    _target_mark(target["id"], "deleted", "Удалённый аккаунт исключён",
                                 entity.id, "skipped", entity.username)
                    await finish("deleted")
                else:
                    async with seen_lock:
                        duplicate = entity.id in resolved_seen
                        if not duplicate:
                            resolved_seen.add(entity.id)
                    if duplicate:
                        _target_mark(target["id"], "duplicate",
                                     "Дубль настоящего Telegram ID в этой кампании",
                                     entity.id, "skipped", entity.username)
                        await finish("duplicates")
                    else:
                        _target_mark(target["id"], "valid", None, entity.id, None, entity.username)
                        await finish("valid")
            except FloodWaitError as exc:
                if retry == 0 and len(ready_ids) > 1:
                    queue.put_nowait((target, 1))
                else:
                    detail = "Telegram просит подождать %d секунд" % int(exc.seconds)
                    _target_mark(target["id"], "technical", detail)
                    await finish("technical")
            except (ValueError, RPCError) as exc:
                name = type(exc).__name__
                if name in {"UsernameInvalidError", "UsernameNotOccupiedError"} or isinstance(exc, ValueError):
                    detail = "Username больше не существует или указан неверно"
                    _target_mark(target["id"], "invalid", detail, None, "skipped")
                    await finish("invalid")
                elif retry == 0 and len(ready_ids) > 1:
                    queue.put_nowait((target, 1))
                else:
                    detail = "%s: %s" % (name, str(exc))
                    _target_mark(target["id"], "technical", detail)
                    await finish("technical")
            except Exception as exc:
                if retry == 0 and len(ready_ids) > 1:
                    queue.put_nowait((target, 1))
                else:
                    detail = "%s: %s" % (type(exc).__name__, str(exc))
                    _target_mark(target["id"], "technical", detail)
                    await finish("technical")
            finally:
                queue.task_done()
                await asyncio.sleep(TARGET_REQUEST_PAUSE)

    worker_ids = ready_ids[: min(TARGET_CHECK_CONCURRENCY, len(ready_ids))]
    await asyncio.gather(*(worker(account_id) for account_id in worker_ids))
    _persist(job)


async def _run(campaign: Dict[str, Any], account_ids: List[int],
               job: Dict[str, Any]) -> None:
    try:
        results = await _run_account_checks(campaign, account_ids, job)
        ready_ids = [int(item["account_id"]) for item in results if item["ready"]]
        job["phase"] = "targets"
        job["message"] = "Проверяю пользователей из очереди"
        _persist(job)

        await _run_targets(job, ready_ids)
        account_warnings = len(results) - len(ready_ids)
        technical = int(job["targets"].get("technical") or 0)
        if not ready_ids:
            job["status"] = "error"
            job["message"] = "Ни один аккаунт-инвайтер не готов к запуску"
        elif account_warnings or technical:
            job["status"] = "warning"
            job["message"] = "Проверка завершена: есть пункты, требующие внимания"
        else:
            job["status"] = "ready"
            job["message"] = "Проверка завершена — кампания готова к запуску"
        job["phase"] = "done"
        job["finished_at"] = int(time.time())
        _persist(job)
        db.log(
            "Предварительная проверка: готово аккаунтов %d/%d, пригодных целей %d/%d"
            % (
                len(ready_ids), len(results), int(job["targets"]["valid"]),
                int(job["targets"]["total"]),
            ),
            scope="invite",
            campaign_id=int(campaign["id"]),
        )
    except Exception as exc:
        job["status"] = "error"
        job["phase"] = "done"
        job["message"] = "Проверка остановлена: %s: %s" % (type(exc).__name__, str(exc))
        job["finished_at"] = int(time.time())
        _persist(job)
