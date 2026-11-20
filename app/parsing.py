"""Сбор аудитории: участники, авторы сообщений, реакции.

Ключевой момент: access_hash пользователя действителен только для того аккаунта,
который его получил. Поэтому при парсинге мы пишем хэши в разрезе аккаунта —
иначе другой аккаунт не сможет пригласить юзера без @username.
"""
from __future__ import annotations

import asyncio
import string
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from telethon.errors import ChatAdminRequiredError, FloodWaitError, ServerError
from telethon.tl.functions.messages import GetMessageReactionsListRequest
from telethon.tl.types import Channel, Chat, User

from . import accounts, db

# job_id -> состояние
JOBS: Dict[str, Dict[str, Any]] = {}
# (account_id, chat_id) идущих сейчас парсингов
ACTIVE: Set[Tuple[int, int]] = set()

ALPHABET = string.ascii_lowercase + "абвгдежзийклмнопрстуфхцчшщыэюя" + string.digits


def _job(job_id: str) -> Dict[str, Any]:
    return JOBS.setdefault(job_id, {})


def new_job(kind: str, title: str) -> str:
    job_id = "%s-%d" % (kind, time.time_ns())
    JOBS[job_id] = {
        "id": job_id,
        "kind": kind,
        "title": title,
        "status": "running",
        "found": 0,
        "added": 0,
        "total": 0,
        "processed": 0,
        "stage": "",
        "error": None,
        "started_at": int(time.time()),
    }
    return job_id


def _user_last_seen(user: User) -> str:
    st = getattr(user, "status", None)
    if st is None:
        return ""
    name = type(st).__name__
    return {
        "UserStatusOnline": "online",
        "UserStatusOffline": "recently_offline",
        "UserStatusRecently": "recently",
        "UserStatusLastWeek": "last_week",
        "UserStatusLastMonth": "last_month",
        "UserStatusEmpty": "long_ago",
    }.get(name, name)


def save_users(chat_id: int, account_id: int, users: List[User], source: str,
               msg_counts: Optional[Dict[int, int]] = None) -> int:
    """Записывает пользователей и их access_hash. Возвращает число новых записей."""
    now = int(time.time())
    if not users:
        return 0

    member_rows = []
    hash_rows = []
    for u in users:
        if not isinstance(u, User):
            continue
        member_rows.append((
            chat_id, u.id, u.username, u.first_name, u.last_name, u.phone,
            1 if u.bot else 0, 1 if u.deleted else 0, 1 if getattr(u, "premium", False) else 0,
            _user_last_seen(u), (msg_counts or {}).get(u.id, 0), source, now,
        ))
        if u.access_hash is not None:
            hash_rows.append((account_id, u.id, u.access_hash, now))

    return db.save_parsed_members(chat_id, member_rows, hash_rows)


def _save_for_job(job: Dict[str, Any], chat_id: int, account_id: int,
                  users: List[User], source: str,
                  msg_counts: Optional[Dict[int, int]] = None) -> int:
    """Старые профили и хэши обновляются, но счётчик растёт только от новых ID."""
    added = save_users(chat_id, account_id, users, source, msg_counts)
    job["added"] = job.get("added", 0) + added
    job["found"] = job["added"]
    job["total"] = db.q1("SELECT COUNT(*) c FROM members WHERE chat_id=?", (chat_id,))["c"]
    return added


def upsert_chat(entity) -> Dict[str, Any]:
    kind = "channel"
    is_mega = 0
    if isinstance(entity, Chat):
        kind = "group"
    elif isinstance(entity, Channel):
        is_mega = 1 if entity.megagroup else 0
        kind = "supergroup" if entity.megagroup else "channel"
    db.ex(
        "INSERT INTO chats (id,title,username,kind,is_megagroup) VALUES (?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, username=excluded.username, "
        "kind=excluded.kind, is_megagroup=excluded.is_megagroup",
        (entity.id, getattr(entity, "title", ""), getattr(entity, "username", None), kind, is_mega),
    )
    return db.row_to_dict(db.q1("SELECT * FROM chats WHERE id=?", (entity.id,)))


async def _collect_participants(client, entity, job, chat_id: int, account_id: int,
                                deep: bool, limit: Optional[int]) -> int:
    """Обычный обход. При deep=True добирает сверх лимита ~10k перебором префиксов."""
    total_new = 0
    buffer: List[User] = []
    job["stage"] = "участники"
    seen = set()

    async def flush():
        nonlocal total_new, buffer
        if buffer:
            total_new += _save_for_job(job, chat_id, account_id, buffer, "participants")
            buffer = []

    try:
        async for user in client.iter_participants(entity, limit=limit):
            if job.get("stop_requested"):
                await flush()
                raise ParsePaused("Остановлено вручную: участники сохранены в общей базе")
            if user.id in seen:
                continue
            seen.add(user.id)
            buffer.append(user)
            job["processed"] += 1
            if len(buffer) >= 200:
                await flush()
                await asyncio.sleep(0)
    except ChatAdminRequiredError:
        await flush()
        raise
    except FloodWaitError as e:
        await flush()
        job["stage"] = "пауза FloodWait %ds" % e.seconds
        await _wait(job, min(e.seconds + 2, 300))
    except asyncio.CancelledError:
        await flush()
        raise
    await flush()

    if deep:
        job["stage"] = "участники (глубокий обход)"
        for prefix in ALPHABET:
            if job.get("stop_requested"):
                await flush()
                raise ParsePaused("Остановлено вручную: участники сохранены в общей базе")
            try:
                async for user in client.iter_participants(entity, search=prefix):
                    if job.get("stop_requested"):
                        await flush()
                        raise ParsePaused("Остановлено вручную: участники сохранены в общей базе")
                    if user.id in seen:
                        continue
                    seen.add(user.id)
                    buffer.append(user)
                    job["processed"] += 1
                    if len(buffer) >= 200:
                        await flush()
            except FloodWaitError as e:
                await flush()
                job["stage"] = "пауза FloodWait %ds" % e.seconds
                await _wait(job, min(e.seconds + 2, 300))
            except ParsePaused:
                raise
            except asyncio.CancelledError:
                await flush()
                raise
            except Exception:
                continue
            await flush()
            await _wait(job, 0.5)

    return total_new


async def sync_target_members(account_id: int, chat_ref: str) -> Dict[str, Any]:
    """Обновляет локальный список участников целевого чата для исключения дублей."""
    client = await accounts.get_client(account_id)
    if not await client.is_user_authorized():
        raise RuntimeError("Аккаунт не авторизован")

    entity = await resolve_chat(client, chat_ref)
    chat = upsert_chat(entity)
    job = {"stage": "участники", "processed": 0, "found": 0}
    added = await _collect_participants(
        client, entity, job, entity.id, account_id, deep=False, limit=None)
    total = db.q1("SELECT COUNT(*) c FROM members WHERE chat_id=?", (entity.id,))["c"]
    db.ex(
        "UPDATE chats SET last_parsed_at=?, members_count=? WHERE id=?",
        (int(time.time()), total, entity.id),
    )
    db.log(
        "Целевой чат «%s» синхронизирован: участников %d, новых %d"
        % (getattr(entity, "title", str(entity.id)), total, added),
        scope="parse", account_id=account_id,
    )
    return {"chat_id": chat["id"], "title": chat.get("title") or "", "total": total,
            "added": added}


class ParsePaused(Exception):
    """Проход остановлен, место сохранено в parse_cursors — следующий запуск продолжит."""


# Сколько FloodWait пережидаем на месте. Дольше — сохраняем место и останавливаемся.
FLOOD_WAIT_MAX = 15 * 60
# Как часто сохраняем найденных людей и место прохода (в сообщениях).
SAVE_EVERY = 1000
# Паузы перед повторами после обрыва связи; после последней — остановка с сохранением.
RECONNECT_DELAYS = (5, 15, 30, 60, 120)
# Незаконченный проход старше недели начинаем заново с новых сообщений.
CURSOR_MAX_AGE = 7 * 86400
TRANSIENT_ERRORS = (ConnectionError, OSError, EOFError, asyncio.TimeoutError, ServerError)


def _num(value: int) -> str:
    return "{:,}".format(value).replace(",", " ")


async def _wait(job: Dict[str, Any], seconds: float) -> None:
    """Ждёт, но сразу выходит по кнопке «Остановить»."""
    end = time.monotonic() + seconds
    while not job.get("stop_requested"):
        left = end - time.monotonic()
        if left <= 0:
            return
        await asyncio.sleep(min(left, 1.0))


def _load_cursor(chat_id: int, account_id: int, source: str,
                 limit: Optional[int]) -> Optional[Dict[str, Any]]:
    row = db.row_to_dict(db.q1(
        "SELECT offset_id, scanned, total, updated_at FROM parse_cursors "
        "WHERE chat_id=? AND account_id=? AND source=?",
        (chat_id, account_id, source),
    ))
    if not row:
        return None
    stale = time.time() - row["updated_at"] > CURSOR_MAX_AGE
    if stale or (limit is not None and row["scanned"] >= limit):
        _drop_cursor(chat_id, account_id, source)
        return None
    return row


def _save_cursor(chat_id: int, account_id: int, source: str, offset_id: int,
                 scanned: int, total: Optional[int]) -> None:
    if not offset_id:
        return
    db.ex(
        """
        INSERT INTO parse_cursors (chat_id, account_id, source, offset_id, scanned, total, updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(chat_id, account_id, source) DO UPDATE SET
            offset_id=excluded.offset_id, scanned=excluded.scanned,
            total=excluded.total, updated_at=excluded.updated_at
        """,
        (chat_id, account_id, source, offset_id, scanned, total, int(time.time())),
    )


def _drop_cursor(chat_id: int, account_id: int, source: str) -> None:
    db.ex("DELETE FROM parse_cursors WHERE chat_id=? AND account_id=? AND source=?",
          (chat_id, account_id, source))


async def _scan_messages(client, entity, job, chat_id: int, account_id: int, source: str,
                         label: str, limit: Optional[int], handle, flush) -> None:
    """Проходит сообщения от новых к старым, переживая FloodWait и обрывы связи.

    После FloodWait и переподключения продолжает с того же сообщения, а не
    бросает проход. Каждые SAVE_EVERY сообщений сохраняет людей и место прохода,
    поэтому долгий FloodWait, кнопка «Остановить» или перезапуск сервера теряют
    не больше последней порции: следующий запуск продолжит с сохранённого места.
    """
    cursor = _load_cursor(chat_id, account_id, source, limit)
    offset_id = cursor["offset_id"] if cursor else 0
    scanned = cursor["scanned"] if cursor else 0
    total = cursor["total"] if cursor else None
    if cursor:
        db.log("Продолжаю %s «%s» с сообщения #%d: уже пройдено %s"
               % (label, job.get("title", chat_id), offset_id, _num(scanned)),
               scope="parse", account_id=account_id)
    since_save = 0
    failures = 0

    def show(extra: str = "") -> None:
        goal = limit if not total else (total if limit is None else min(limit, total))
        job["stage"] = "%s · %s / %s%s" % (label, _num(scanned), _num(goal) if goal else "?", extra)

    def checkpoint() -> None:
        flush()
        _save_cursor(chat_id, account_id, source, offset_id, scanned, total)

    def place() -> str:
        return "сообщение #%d, пройдено %s" % (offset_id, _num(scanned))

    show()
    while limit is None or scanned < limit:
        if job.get("stop_requested"):
            checkpoint()
            raise ParsePaused("Остановлено вручную (%s). Запустите этот чат этим же "
                              "аккаунтом ещё раз — продолжу с этого места." % place())
        left = None if limit is None else limit - scanned
        messages = client.iter_messages(entity, limit=left, offset_id=offset_id, wait_time=1)
        try:
            async for msg in messages:
                if not total and getattr(messages, "total", None):
                    total = messages.total
                await handle(msg)
                offset_id = msg.id
                scanned += 1
                failures = 0
                job["processed"] += 1
                since_save += 1
                if since_save >= SAVE_EVERY:
                    checkpoint()
                    since_save = 0
                if scanned % 100 == 0:
                    show()
                if job.get("stop_requested"):
                    break
            else:
                break  # история кончилась или дошли до лимита
        except FloodWaitError as e:
            checkpoint()
            if e.seconds > FLOOD_WAIT_MAX:
                db.log("Парсинг «%s» (%s): Telegram попросил паузу %d с — останавливаюсь, "
                       "место сохранено (%s)" % (job.get("title", chat_id), label, e.seconds, place()),
                       level="warn", scope="parse", account_id=account_id)
                raise ParsePaused("Telegram попросил паузу %d мин (%s). Запустите этот чат "
                                  "этим же аккаунтом позже — продолжу с этого места."
                                  % ((e.seconds + 59) // 60, place()))
            db.log("Парсинг «%s» (%s): FloodWait %d с, жду и продолжаю с сообщения #%d"
                   % (job.get("title", chat_id), label, e.seconds, offset_id),
                   level="warn", scope="parse", account_id=account_id)
            show(" · пауза FloodWait %d с" % e.seconds)
            await _wait(job, e.seconds + 2)
        except TRANSIENT_ERRORS as e:
            checkpoint()
            failures += 1
            if failures > len(RECONNECT_DELAYS):
                db.log("Парсинг «%s» (%s): нет связи с Telegram (%s) — останавливаюсь, "
                       "место сохранено (%s)" % (job.get("title", chat_id), label, e, place()),
                       level="error", scope="parse", account_id=account_id)
                raise ParsePaused("Нет связи с Telegram: %s (%s). Запустите этот чат этим же "
                                  "аккаунтом ещё раз — продолжу с этого места." % (e, place()))
            delay = RECONNECT_DELAYS[failures - 1]
            db.log("Парсинг «%s» (%s): обрыв связи (%s), повтор %d/%d через %d с"
                   % (job.get("title", chat_id), label, e, failures, len(RECONNECT_DELAYS), delay),
                   level="warn", scope="parse", account_id=account_id)
            show(" · нет связи, повтор через %d с" % delay)
            await _wait(job, delay)
            if not client.is_connected():
                try:
                    await asyncio.wait_for(client.connect(), 40)
                except Exception:
                    pass  # следующий заход снова упадёт и посчитается как неудача
        except asyncio.CancelledError:
            checkpoint()
            raise

    flush()
    _drop_cursor(chat_id, account_id, source)
    show()


async def _collect_history(client, entity, job, chat_id: int, account_id: int,
                           messages_limit: Optional[int]) -> None:
    """Авторы сообщений — самая конверсионная выборка. None — вся история."""
    # msg_count в базе обновляется через MAX, поэтому сохраняем накопленные
    # за этот запуск счётчики. После продолжения прохода счёт начинается заново.
    counts: Dict[int, int] = {}
    pending: Dict[int, User] = {}

    async def handle(msg) -> None:
        try:
            sender = msg.sender
        except Exception:
            sender = None
        if isinstance(sender, User) and not sender.bot:
            counts[sender.id] = counts.get(sender.id, 0) + 1
            pending[sender.id] = sender
            if len(pending) >= 200:
                flush()

    def flush() -> None:
        if pending:
            _save_for_job(job, chat_id, account_id, list(pending.values()), "history", counts)
            pending.clear()

    await _scan_messages(client, entity, job, chat_id, account_id, "history",
                         "история сообщений", messages_limit, handle, flush)


async def _collect_reactions(client, entity, job, chat_id: int, account_id: int,
                             posts_limit: Optional[int]) -> None:
    """Кто ставил реакции последним постам — тёплая аудитория канала."""
    users: Dict[int, User] = {}
    pending: Dict[int, User] = {}

    async def handle(msg) -> None:
        if not getattr(msg, "reactions", None):
            return
        try:
            res = await client(GetMessageReactionsListRequest(peer=entity, id=msg.id, limit=100))
        except (FloodWaitError,) + TRANSIENT_ERRORS:
            raise  # проход переждёт и повторит это сообщение
        except Exception:
            return
        for u in getattr(res, "users", []) or []:
            if isinstance(u, User) and not u.bot:
                users[u.id] = u
                pending[u.id] = u
        if len(pending) >= 200:
            flush()
        await _wait(job, 0.4)

    def flush() -> None:
        if pending:
            _save_for_job(job, chat_id, account_id, list(pending.values()), "reactions")
            pending.clear()

    await _scan_messages(client, entity, job, chat_id, account_id, "reactions",
                         "реакции", posts_limit, handle, flush)


async def resolve_chat(client, chat_ref: str):
    """По id чат резолвится только если он есть в кэше сессии аккаунта.
    У свежего аккаунта кэш пуст — подтягиваем список диалогов и пробуем снова."""
    ref = int(chat_ref) if _is_int(chat_ref) else chat_ref
    try:
        return await client.get_entity(ref)
    except (ValueError, TypeError):
        if not _is_int(chat_ref):
            raise
        async for _ in client.iter_dialogs():
            pass
        return await client.get_entity(int(chat_ref))


async def run_parse(job_id: str, account_id: int, chat_ref: str, sources: List[str],
                    deep: bool, participants_limit: Optional[int],
                    messages_limit: Optional[int], posts_limit: Optional[int]) -> None:
    job = _job(job_id)
    job["account_id"] = account_id
    active_key = None
    try:
        client = await accounts.get_client(account_id)
        if not await client.is_user_authorized():
            raise RuntimeError("Аккаунт не авторизован")

        entity = await resolve_chat(client, chat_ref)
        chat = upsert_chat(entity)
        job["chat_id"] = entity.id
        job["title"] = getattr(entity, "title", str(entity.id))
        # Два прохода одного чата одним аккаунтом писали бы одно и то же место прохода.
        if (account_id, entity.id) in ACTIVE:
            raise RuntimeError("Этот чат уже парсится этим аккаунтом — дождитесь окончания")
        active_key = (account_id, entity.id)
        ACTIVE.add(active_key)

        job["added"] = 0
        job["found"] = 0
        job["total"] = db.q1("SELECT COUNT(*) c FROM members WHERE chat_id=?", (entity.id,))["c"]
        paused = None
        try:
            if "participants" in sources:
                try:
                    await _collect_participants(
                        client, entity, job, entity.id, account_id, deep, participants_limit)
                except ChatAdminRequiredError:
                    db.log(
                        "Список участников «%s» скрыт: нужны права администратора. "
                        "Собираю аудиторию по истории сообщений." % job["title"],
                        level="warn", scope="parse", account_id=account_id)
                    if "history" not in sources:
                        sources = sources + ["history"]

            for source, collect, limit in (("history", _collect_history, messages_limit),
                                           ("reactions", _collect_reactions, posts_limit)):
                if source not in sources:
                    continue
                if job.get("stop_requested"):
                    raise ParsePaused("Остановлено вручную")
                await collect(client, entity, job, entity.id, account_id, limit)
        except ParsePaused as e:
            paused = str(e)

        total = db.q1("SELECT COUNT(*) c FROM members WHERE chat_id=?", (entity.id,))["c"]
        added = job.get("added", 0)
        db.ex("UPDATE chats SET last_parsed_at=?, members_count=? WHERE id=?",
              (int(time.time()), total, entity.id))

        job["found"] = added
        job["added"] = added
        job["total"] = total
        if paused:
            job["status"] = "paused"
            job["stage"] = paused
            db.log("Парсинг «%s» остановлен: всего %d, новых %d. %s"
                   % (job["title"], total, added, paused),
                   level="warn", scope="parse", account_id=account_id)
        else:
            job["status"] = "done"
            job["stage"] = "готово"
            db.log("Спарсено «%s»: всего %d, новых %d" % (job["title"], total, added),
                   scope="parse", account_id=account_id)
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        db.log("Ошибка парсинга: %s" % e, level="error", scope="parse", account_id=account_id)
    finally:
        if active_key:
            ACTIVE.discard(active_key)


def request_stop(job_id: str) -> bool:
    """Просит задачу остановиться; проход сохранит место и завершится."""
    job = JOBS.get(job_id)
    if not job:
        return False
    job["stop_requested"] = True
    sub = JOBS.get(job.get("current_sub") or "")
    if sub:
        sub["stop_requested"] = True
    return True


async def run_parse_all(job_id: str, account_ids: List[int], chat_ref: str, sources: List[str],
                        deep: bool, participants_limit: Optional[int],
                        messages_limit: Optional[int], posts_limit: Optional[int],
                        gap: int = 30) -> None:
    """Прогоняет парсинг последовательно каждым аккаунтом, чтобы у всех появились
    свои access_hash. Иначе инвайтить можно будет только юзеров с @username."""
    job = _job(job_id)
    job["total_accounts"] = len(account_ids)
    ok = 0
    done = 0
    for index, account_id in enumerate(account_ids, 1):
        if job.get("stop_requested"):
            break
        account = db.row_to_dict(db.q1("SELECT label FROM accounts WHERE id=?", (account_id,)))
        label = (account or {}).get("label", account_id)
        job["stage"] = "аккаунт %d из %d: %s" % (index, len(account_ids), label)
        job["done_accounts"] = index - 1

        sub_id = new_job("parse", "%s · %s" % (chat_ref, label))
        job["current_sub"] = sub_id
        await run_parse(sub_id, account_id, chat_ref, sources, deep,
                        participants_limit, messages_limit, posts_limit)
        job["current_sub"] = None
        done = index
        sub = JOBS[sub_id]
        job["added"] = job.get("added", 0) + sub.get("added", 0)
        job["found"] = job["added"]
        job["total"] = sub.get("total", job.get("total", 0))
        if sub["status"] in ("done", "paused"):
            ok += 1
        else:
            db.log("Аккаунт «%s» не смог спарсить чат: %s" % (label, sub.get("error")),
                   level="warn", scope="parse", account_id=account_id)

        if index < len(account_ids) and not job.get("stop_requested"):
            job["stage"] = "пауза перед следующим аккаунтом"
            await _wait(job, gap)

    job["current_sub"] = None
    job["done_accounts"] = done
    if job.get("stop_requested"):
        job["status"] = "paused"
        job["stage"] = "остановлено вручную: справились %d из %d" % (ok, len(account_ids))
    else:
        job["status"] = "done" if ok else "error"
        job["stage"] = "готово: справились %d из %d" % (ok, len(account_ids))
        if not ok:
            job["error"] = "ни один аккаунт не смог получить список"
    db.log("Парсинг всеми аккаунтами завершён: %d из %d" % (ok, len(account_ids)), scope="parse")


def _is_int(v: str) -> bool:
    try:
        int(v)
        return True
    except (TypeError, ValueError):
        return False


async def list_dialogs(account_id: int) -> List[Dict[str, Any]]:
    """Группы и каналы, доступные аккаунту."""
    client = await accounts.get_client(account_id)
    if not await client.is_user_authorized():
        raise RuntimeError("Аккаунт не авторизован")
    out: List[Dict[str, Any]] = []
    async for dialog in client.iter_dialogs():
        ent = dialog.entity
        if isinstance(ent, Chat):
            kind = "group"
        elif isinstance(ent, Channel):
            kind = "supergroup" if ent.megagroup else "channel"
        else:
            continue
        out.append({
            "id": ent.id,
            "title": getattr(ent, "title", ""),
            "username": getattr(ent, "username", None),
            "kind": kind,
            "is_admin": bool(getattr(ent, "creator", False) or getattr(ent, "admin_rights", None)),
            "members_count": getattr(ent, "participants_count", None),
        })
    out.sort(key=lambda d: (d["kind"], d["title"] or ""))
    return out
