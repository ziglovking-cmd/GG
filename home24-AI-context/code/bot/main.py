"""Home24 userbot: сидит на аккаунте, пишет гостям по script.md + ИИ.
Управление — /команды с менеджер-акка (Избранное) или с админ-акков (в личку боту).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import random
import re
from pathlib import Path
from typing import Any

from telethon import Button, TelegramClient, events
from telethon.errors import FloodWaitError

from bot.ai import reply as ai_reply
from bot.config import get_settings
from bot.engine import Engine
from bot.human import human_send, was_bot_outbound
from bot.hub import get_hub
from bot.login import EXIT_SESSION_DEAD, ensure_login
from bot.managers import ManagerConfig, get_registry
from bot.rate_limit import OutreachLimiter, chunk_sleep_seconds
from bot.runtime_flags import dashboard_keepalive, is_session_dead_error
from bot.session_io import clear_session
from bot.store import Store, _moscow_today

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.getLogger("aiohttp.server").setLevel(logging.WARNING)
logging.getLogger("telethon.network").setLevel(logging.WARNING)
logging.getLogger("telethon.client.updates").setLevel(logging.WARNING)
logger = logging.getLogger("home24")


def _account_session_dead(account_id: str, manager_id: str, reason: str) -> None:
    """Пометить слот revoked, вычистить legacy-копии, blacklist. Без SystemExit при keepalive."""
    note = (reason or "сессия отозвана")[:500]
    dead_sess = ""
    try:
        from bot.tg_accounts import get_tg_accounts

        tg = get_tg_accounts()
        acc = tg.get(account_id) if account_id else None
        if acc:
            dead_sess = (acc.session or "").strip()
        if not dead_sess and manager_id:
            try:
                from bot.managers import get_registry

                m = get_registry().get(manager_id)
                if m:
                    dead_sess = (m.session or "").strip()
            except Exception:
                pass
        if account_id:
            tg.mark_revoked(account_id, note, clear_session=True)
    except Exception:
        logger.exception("mark_revoked failed account=%s", account_id)
    if dead_sess:
        try:
            from bot.session_io import purge_dead_session

            purge_dead_session(dead_sess)
        except Exception:
            logger.exception("purge_dead_session failed")
    try:
        clear_session(manager_id=manager_id)
    except Exception:
        pass
    try:
        get_hub().notify(
            "Telegram-сессия отозвана",
            f"Аккаунт [{account_id or '?'}]: {note}. Войдите снова в Аккаунтах.",
            manager_id=manager_id,
            level="error",
        )
        get_hub().bus.publish(
            "account_warning",
            account_id=account_id,
            manager_id=manager_id,
            title="Сессия отозвана",
            body=note,
            level="error",
        )
    except Exception:
        logger.exception("notify revoked failed")


HELP = """Команды (Избранное или личка с админ-акка):

/help — справка
/status — ваш аккаунт: sent/осталось, очередь, сессия
/managers — список менеджеров команды
/assign @user id_менеджера — закрепить клиента
/import_csv — импорт CSV из файла в Избранном (ответом на файл)
/ai — статус ИИ
/add +79001234567 Имя — в вашу очередь
/add @username Имя
/list — ваши контакты
/send — превью (лимит дня, перенос)
/send go — старт вашей очереди
/stop — стоп рассылки
/take — бот молчит в этом чате
/free — бот снова отвечает
/script — ветки v2

Клиент всегда у одного менеджера. Стоп-лист и 14 дней — общие на всю команду.
"""

_OUTBOUND_BAD = re.compile(
    r"(traceback|exception|error:|rate.?limit|openai|mistral|api[_ ]?key|"
    r"status.?code|typeerror|valueerror|http/\d|modulenotfound|"
    r"TELEGRAM_|OPENAI_|SESSION=|sk-|mstrl_|⚠️ Сбой|⚠️ Не смог)",
    re.I,
)

_outreach_tasks: dict[str, asyncio.Task[Any]] = {}
_stop_flags: dict[str, bool] = {}
_handled_ids: set[int] = set()
_chat_locks: dict[str, asyncio.Lock] = {}


class QueuedGuestEvent:
    """Минимальный event для обработки после рестарта (без живого Update)."""

    def __init__(
        self,
        chat_id: str | int,
        text: str,
        *,
        message_id: int | None = None,
    ) -> None:
        try:
            self.chat_id = int(chat_id)
        except (TypeError, ValueError):
            self.chat_id = chat_id
        self.raw_text = text or ""
        self.id = int(message_id) if message_id else None
        self.is_private = True
        self.out = False
        self.sender_id = self.chat_id

    async def get_sender(self) -> Any:
        return None


def coalesce_guest_batch(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Несколько сообщений одного чата за паузу — один ответ, без повторов."""
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        cid = str(item.get("chat_id") or "")
        if not cid:
            continue
        if cid not in grouped:
            grouped[cid] = {"chat_id": cid, "texts": [], "parts": [], "event": None}
            order.append(cid)
        bucket = grouped[cid]
        text = str(item.get("text") or "").strip()
        if text and text not in bucket["texts"]:
            bucket["texts"].append(text)
        bucket["parts"].append(item)
        if item.get("event") is not None:
            bucket["event"] = item["event"]
    out: list[dict[str, Any]] = []
    for cid in order:
        bucket = grouped[cid]
        if not bucket["texts"] or bucket["event"] is None:
            continue
        bucket["text"] = "\n".join(bucket["texts"])
        out.append(bucket)
    return out


def _take_speaker(store: Any, chat_id: str, message_id: str, account_id: str) -> bool:
    """Один чат — один аккаунт. Второй бот в этот диалог не пишет."""
    sess = store.get_session(chat_id)
    ctx = dict(sess.get("context") or {})
    owner = str(ctx.get("tg_account") or "").strip()
    if owner and owner != account_id:
        logger.info(
            "skip other bot chat=%s owner=%s this=%s", chat_id, owner, account_id
        )
        return False
    key = str(message_id or "").strip()
    if key and not store.claim_meta(f"speak:{chat_id}:{key}"):
        logger.info(
            "skip duplicate speaker chat=%s id=%s this=%s", chat_id, key, account_id
        )
        return False
    if not owner and account_id:
        ctx["tg_account"] = account_id
        store.save_session(chat_id, context=ctx)
    return True


def _stay_quiet_for_manager(store: Any, chat_id: str, sess: dict[str, Any]) -> bool:
    """True — менеджер ещё в паузе 15 минут. Иначе бот снова отвечает."""
    if not sess.get("handed_off") and (sess.get("step") or "") != "handed_off":
        return False
    if store.is_stopped_chat(chat_id) or (sess.get("context") or {}).get("stopped"):
        return True
    from bot.handoff_hold import handoff_hold_active, resume_step

    recent = store.recent_messages(chat_id, limit=40)
    if handoff_hold_active(recent):
        return True
    step = resume_step(sess)
    store.save_session(chat_id, handed_off=0, step=step)
    sess["handed_off"] = 0
    sess["step"] = step
    logger.info("handoff released chat=%s step=%s", chat_id, step)
    return False


def _queue_item(
    chat_id: str,
    text: str,
    *,
    event: Any = None,
    message_id: str = "",
    logged: bool = True,
) -> dict[str, Any]:
    mid = message_id or str(getattr(event, "id", "") or "")
    ev = event or QueuedGuestEvent(chat_id, text, message_id=int(mid) if mid.isdigit() else None)
    return {
        "chat_id": str(chat_id),
        "event": ev,
        "text": text,
        "logged": logged,
        "message_id": mid,
    }


def _lock_for(chat_id: str) -> asyncio.Lock:
    lock = _chat_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _chat_locks[chat_id] = lock
    return lock


def _norm_phone(raw: str) -> str:
    s = re.sub(r"[^\d+]", "", raw.strip())
    if s and not s.startswith("+"):
        s = "+" + s
    return s


async def _human_send(
    client: TelegramClient,
    entity: Any,
    texts: list[str],
    buttons=None,
    *,
    max_msgs: int = 2,
) -> None:
    await human_send(client, entity, texts, buttons, max_msgs=max_msgs)


def finalize_post_outreach_msgs(
    msgs: list[str],
    *,
    post_opener: bool,
    step: str = "",
    known: dict | None = None,
    path: str = "",
) -> tuple[list[str], int]:
    """Keep greeting dedupe, never drop summary/offers/next question.

    Returns (messages_to_send, max_msgs for human_send).
    """
    safe = list(msgs or [])
    if not safe:
        return safe, 1
    blob_low = "\n".join(safe).lower()
    substantive = bool(
        re.search(
            r"(?m)подобрала несколько|записала всё|^\d\)\s|если зайдёт|"
            r"были у нас|впервые\?",
            blob_low,
        )
    ) or any(len(m) >= 280 for m in safe)
    if post_opener and len(safe) > 1 and not substantive and all(len(m) < 280 for m in safe):
        # без повторного «это Home24», но факты не теряем: короткие пузыри склеиваем
        rest = [m for m in safe if not re.search(r"это home24|рада вас|соскучились", m.lower())]
        safe = [" ".join(x.strip() for x in (rest or safe[-1:]))]
    if substantive and len(safe) >= 3:
        safe = [safe[0] + "\n\n" + safe[1], *safe[2:]]
    from bot.reply_guard import question_keys

    asked = question_keys("\n".join(safe))
    known = known or {}
    extra = ""
    if any("?" in m for m in safe):
        pass  # в ответе уже есть вопрос (в т.ч. «Интересно?») — второй не клеим
    elif path.startswith(
        (
            "smart:rule/offer",
            "smart:rule/perk",
            "smart:rule/life",
            "smart:rule/thanks",
            "smart:rule/wait",
            "smart:rule/thinking",
            "smart:rule/plans-later",
        )
    ):
        pass  # рассказ про предложение / ответ на вопрос — анкету следом не клеим (скрин 45, 10.11)
    elif re.search(
        r"(?i)как\s+(?:только\s+)?определитесь|как\s+появятся|как\s+надумаете|будем\s+ждать|"
        r"напишите,\s+подберу|напишите,\s+когда|^[\s🙂😊👍]+$",
        "\n".join(safe),
    ):
        pass  # бот только что сказал «напишите, когда определитесь» — вопрос следом противоречит
    elif step == "await_returning" and str(known.get("returning") or "").strip():
        pass
    elif step == "await_dates" and str(known.get("dates") or "").strip() not in ("", "ещё не определились"):
        pass
    elif step == "await_guests" and str(known.get("guests") or "").strip():
        pass
    elif step == "await_district" and str(known.get("district") or "").strip():
        pass
    elif step == "await_returning" and "returning" not in asked:
        extra = "Подскажите, пожалуйста — вы у нас уже были или впервые?"
    elif step == "await_guests" and "guests" not in asked:
        extra = "Подскажите, пожалуйста, сколько будет гостей?"
    elif step == "await_dates" and "dates" not in asked:
        extra = "Подскажите, пожалуйста, на какие даты планируете поездку?"
    elif step == "await_district" and "district" not in asked:
        from bot.phrases import district_choice_message

        extra = district_choice_message()
    if extra:
        safe.append(extra)
    send_max = min(2, len(safe) or 1) if substantive else (
        1 if post_opener else min(2, len(safe) or 1)
    )
    return safe, send_max


def _guest_safe(msgs: list[str] | None) -> list[str]:
    safe: list[str] = []
    for m in msgs or []:
        t = str(m).strip()
        if not t or _OUTBOUND_BAD.search(t) or (t.startswith("{") and t.endswith("}")):
            logger.warning("drop bad guest text: %r", t[:120])
            continue
        # страховка: заглушка имени не должна уйти гостю
        t = re.sub(
            r"(?i)\b(клиент|client|гость|guest|user)\s*,\s*",
            "",
            t,
        )
        t = re.sub(r"(?i)^(здравствуйте|добрый день|доброе утро),\s+(клиент|client|гость)\b", r"\1", t)
        from bot.reply_guard import smooth_speech

        t = smooth_speech(t)
        if t:
            safe.append(t)
    # два одинаковых вопроса про даты в одном ходе → один пузырь
    if len(safe) > 1:
        date_asks = sum(
            1
            for s in safe
            if re.search(r"на какие даты|даты примерно|сколько будет гост", s.lower())
        )
        if date_asks >= 2:
            prefer = [
                s
                for s in safe
                if re.search(r"на какие даты|даты|гост", s.lower())
                and not re.search(r"это home24|рада вас|соскучились", s.lower())
            ]
            safe = (prefer or safe)[:1]
    from bot.reply_guard import finished_next_line

    return safe or [finished_next_line(None)]


async def run_manager(
    manager: ManagerConfig,
    store: Store | None = None,
    *,
    account_id: str = "",
    session_override: str = "",
) -> None:
    """Один Telegram-аккаунт компании (SIM) в этом процессе; менеджеры — веб."""
    mid = manager.id
    settings = get_settings()
    store = store or Store(settings.db_path)
    engine = Engine(settings)
    reg = get_registry()
    from bot.tg_accounts import get_tg_accounts

    tg = get_tg_accounts()
    acc = tg.get(account_id) if account_id else tg.for_manager(mid)
    aid = (acc.id if acc else "") or (account_id or mid or "main")

    try:
        from bot import phrases as P

        P.sync_greet_rr(store.get_meta("greet_rr"))
    except Exception:
        pass

    from bot.session_blacklist import is_blacklisted

    saved = (session_override or (acc.session if acc else "") or "").strip()
    # legacy fallback только если слот ещё живой и строка не в blacklist
    if not saved and acc and acc.status == "ok":
        saved = (manager.session or "").strip()
    if not saved and acc and acc.status == "ok":
        saved = (store.get_meta(f"telethon_session:{mid}") or "").strip()
    if (
        not saved
        and acc
        and acc.status == "ok"
        and mid == reg.default_manager_id
    ):
        saved = (store.get_meta("telethon_session") or settings.session or "").strip()
    if saved and is_blacklisted(saved):
        logger.error(
            "refusing blacklisted session for account=%s — нужен новый вход",
            aid,
        )
        _account_session_dead(aid, mid, "чёрный список отозванных сессий")
        if dashboard_keepalive():
            return
        raise SystemExit(EXIT_SESSION_DEAD)

    device = None
    if acc:
        try:
            device = tg.freeze_device_fingerprint(aid)
        except Exception:
            device = None
    try:
        client, sess = await ensure_login(
            settings.api_id,
            settings.api_hash,
            saved,
            account_id=aid,
            device=device,
        )
    except RuntimeError as e:
        logger.error("client lock/registry: %s", e)
        get_hub().notify(
            "Аккаунт занят",
            str(e),
            manager_id=mid,
            level="error",
        )
        if dashboard_keepalive():
            return
        raise SystemExit(EXIT_SESSION_DEAD) from e
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else EXIT_SESSION_DEAD
        if code == EXIT_SESSION_DEAD and getattr(e, "wipe", True):
            _account_session_dead(aid, mid, "сессия отозвана при подключении")
            if dashboard_keepalive():
                return
            raise
        if code == EXIT_SESSION_DEAD:
            logger.error(
                "account=%s connect failed, session file kept (%s)",
                aid,
                getattr(e, "args", ("",))[:1],
            )
            if dashboard_keepalive():
                return
            raise
        raise
    from bot.session_io import save_manager_session

    me = await client.get_me()
    phone = ("+" + me.phone) if me.phone and not str(me.phone).startswith("+") else (me.phone or "")
    # дедуп: обновить существующий слот по user_id, не плодить копию
    bound_mid = (acc.manager_id if acc and acc.manager_id else mid)
    try:
        acc = tg.apply_authorized_session(
            session=sess,
            phone=phone or manager.phone or "",
            telegram_user_id=int(me.id),
            manager_id=bound_mid,
            preferred_account_id=aid,
            label=(acc.label if acc and (acc.label or "").strip() else (manager.name or aid)),
        )
        aid = acc.id
        if acc.manager_id:
            mid = acc.manager_id
            manager = reg.get(mid) or manager
    except Exception:
        logger.exception("apply_authorized_session failed aid=%s", aid)
        try:
            tg.set_session(aid, sess, phone=phone or None)
        except KeyError:
            tg.upsert(
                account_id=aid,
                label=(acc.label if acc and (acc.label or "").strip() else (manager.name or aid)),
                manager_id=bound_mid,
                is_main=bool(acc.is_main) if acc else (aid == "main"),
                daily_send_limit=int(acc.daily_send_limit) if acc else None,
            )
            tg.set_session(aid, sess, phone=phone or None)
    save_manager_session(
        mid,
        sess,
        phone=phone or manager.phone or None,
        user_id=int(me.id),
        is_default=(mid == reg.default_manager_id),
    )
    manager.session = sess
    get_hub().register_client(mid, client, account_id=aid)
    from bot.version import BUILD

    logger.info("Home24 build %s, folder %s", BUILD, Path(__file__).resolve().parents[1])
    logger.info(
        "account=%s manager=%s online as %s @%s id=%s",
        aid,
        mid,
        me.first_name,
        me.username,
        me.id,
    )

    owner_ids = set(settings.admin_ids) | set(manager.admin_ids) | {int(me.id)}
    extra = await _resolve_extra_admins(client, store)
    owner_ids |= extra
    report_to = manager.report_chat or "me"
    from bot.service_reports import emit_service_report, report_account_online

    async def notify_admin(text: str) -> None:
        """Сервис: всегда в панель; в Избранное — только если админ включил отчёты."""
        await emit_service_report(
            client,
            text,
            account_id=aid,
            manager_id=mid,
            report_to=report_to,
            title="Сервис",
        )

    def _lim() -> OutreachLimiter:
        return OutreachLimiter.for_manager(store, manager)

    async def handle_command(chat: Any, text: str, msg_id: int | None = None) -> bool:
        text = (text or "").strip()
        if not text.startswith("/"):
            return False
        if msg_id is not None:
            if msg_id in _handled_ids:
                return True
            _handled_ids.add(msg_id)
            if len(_handled_ids) > 500:
                _handled_ids.clear()

        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        args = parts[1:]
        logger.info("CMD mgr=%s %s args=%s", mid, cmd, args)

        async def answer(msg: str) -> None:
            try:
                await client.send_message(chat, msg)
            except Exception:
                logger.exception("command answer failed")
                await notify_admin(f"⚠️ Не смог ответить на команду {cmd}: {msg[:200]}")

        try:
            if cmd in ("/help", "/start"):
                await answer(HELP)
            elif cmd == "/ai":
                from bot.llm import load_providers

                provs = load_providers()
                if provs:
                    lines = [
                        "ИИ-фолбэк: ON",
                        "Скрипт: привет/финал/воронка — без токенов",
                        "ИИ только если скрипт не знает ответ",
                        "Провайдеры (по порядку):",
                    ]
                    for i, p in enumerate(provs, 1):
                        lines.append(f"  {i}. {p.name} · {p.model}")
                    await answer("\n".join(lines))
                else:
                    await answer("ИИ: OFF — нет ключей AI1/AI2/AI3")
            elif cmd == "/managers":
                lines = [
                    "Веб-менеджеры (работают в панели, не в личных Telegram):",
                ]
                for m in reg.list_public():
                    mark = " ← вы" if m["id"] == mid else ""
                    def_m = " · default" if m["id"] == reg.default_manager_id else ""
                    lines.append(
                        f"· {m['id']}: {m['name']} · доля {m.get('share_weight', 1)}"
                        f"{def_m}{mark}"
                    )
                lines.append(
                    "Telegram — аккаунт(ы) компании в панели → Аккаунты. "
                    "Лимиты — на аккаунт бота, не на менеджера."
                )
                await answer("\n".join(lines))
            elif cmd == "/assign":
                if len(args) < 2:
                    await answer("Пример: /assign @user anna\nили /assign +7900… anna")
                else:
                    target = args[0].strip()
                    if target.startswith("@") is False and not target.startswith("+"):
                        if target[0].isdigit():
                            target = _norm_phone(target)
                    elif target.startswith("@"):
                        target = target.lower()
                    else:
                        target = _norm_phone(target)
                    want = reg.resolve_id(args[1])
                    if not want:
                        await answer(f"Не знаю менеджера {args[1]!r}. /managers")
                    else:
                        if not store.contact_by_phone(target):
                            store.add_contact(
                                phone=target,
                                username=target if target.startswith("@") else "",
                                manager_id=want,
                            )
                        ok_a, why = store.assign_manager(target, want)
                        await answer(
                            f"Закрепил за {want}." if ok_a else f"Нельзя: {why}"
                        )
            elif cmd == "/import_csv":
                await answer(
                    "Пришлите CSV-файл в Избранное и ответьте на него командой "
                    "/import_csv (колонки: phone_or_username,name,manager_id)."
                )
            elif cmd == "/status":
                st_all = store.stats()
                st = store.stats_for_manager(
                    mid, default_manager_id=reg.default_manager_id
                )
                lim = _lim()
                last_err = (store.get_meta("last_error") or "").strip()
                task = _outreach_tasks.get(mid)
                team_lines = []
                for m in reg.enabled_list():
                    lm = OutreachLimiter.for_manager(store, m)
                    healthy = "ok" if (m.session or "").strip() else "нет сессии"
                    if m.id == mid:
                        healthy = "живая"
                    team_lines.append(
                        f"· {m.id} ({m.name}): сегодня {lm.sent_today()}/{lm.daily_limit}, "
                        f"сессия {healthy}"
                    )
                await answer(
                    f"Менеджер: {manager.name} [{mid}]\n"
                    f"Акк: {me.first_name} (@{me.username or '—'})\n"
                    f"Сессия: живая · id={me.id}\n"
                    f"Ваша очередь: pending {st['pending']} · sent {st['sent']} · "
                    f"fail {st['failed']} · стоп {st['stopped']}\n"
                    + "\n".join(lim.status_lines(pending_count=int(st["pending"])))
                    + "\n"
                    f"Команда:\n"
                    + "\n".join(team_lines)
                    + "\n"
                    f"Всего контактов (глобально): {st_all['all']} · стоп {st_all['stopped']}\n"
                    f"ИИ: {'ON' if settings.ai_ready else 'OFF'}\n"
                    f"Рассылка: {'идёт' if task and not task.done() else 'стоп'}\n"
                    f"Ответы гостям в дневной лимит не входят.\n"
                    f"Последняя ошибка: {last_err or '—'}"
                )
            elif cmd == "/script":
                from bot.version import BUILD

                await answer(
                    f"Сборка бота: {BUILD}\n"
                    f"Папка: {Path(__file__).resolve().parents[1]}\n"
                    "Скрипт script.md (Home24 v3, 09.11.2026)\n"
                    "рассылка → «да» = рассказать о предложении\n"
                    "looking → район → даты → гости → календарь TravelLine → менеджер\n"
                    "+ browsing / бонусы / ответы по словам / ИИ (Groq первым)"
                )
            elif cmd == "/add":
                if not args:
                    await answer(
                        "Пример: /add +79001234567 Анна\nили /add @username Анна"
                    )
                else:
                    joined = " ".join(args)
                    m = re.match(
                        r"(@)\s*([A-Za-z0-9_]{4,})(.*)$|(\+[0-9\s\-()]{8,})(.*)$|(@[A-Za-z0-9_]{4,})(.*)$",
                        joined.strip(),
                    )
                    target = ""
                    name = ""
                    if m:
                        if m.group(2):
                            target = "@" + m.group(2)
                            name = (m.group(3) or "").strip()
                        elif m.group(4):
                            target = _norm_phone(m.group(4))
                            name = (m.group(5) or "").strip()
                        elif m.group(6):
                            target = m.group(6)
                            name = (m.group(7) or "").strip()
                    if not target or target in ("@", "+"):
                        await answer(
                            "Не понял номер/юзернейм. Пиши без пробела: /add @BDOXA"
                        )
                    elif target.startswith("@"):
                        store.add_contact(
                            phone=target.lower(),
                            name=name,
                            username=target,
                            manager_id=mid,
                        )
                        await answer(
                            f"Добавил в вашу очередь ({mid}): {target.lower()} {name}".strip()
                        )
                    else:
                        store.add_contact(phone=target, name=name, manager_id=mid)
                        await answer(
                            f"Добавил в вашу очередь ({mid}): {target} {name}".strip()
                        )
            elif cmd == "/list":
                rows = [
                    c
                    for c in store.list_contacts(limit=80)
                    if (c.get("manager_id") or "") in ("", mid)
                    or c.get("manager_id") == mid
                ][:30]
                await answer(
                    "\n".join(
                        f"{c['status']}: {c['phone']} [{c.get('manager_id') or '—'}] "
                        f"{c['name']}".strip()
                        for c in rows
                    )
                    if rows
                    else "Пусто. /add …"
                )
            elif cmd == "/stop":
                _stop_flags[mid] = True
                await answer("Останавливаю вашу рассылку.")
            elif cmd == "/take":
                store.save_session(
                    str(getattr(chat, "id", chat)),
                    handed_off=1,
                    step="handed_off",
                    manager_id=mid,
                )
                await answer("Ок, этот чат за тобой — бот молчит.")
            elif cmd == "/free":
                store.save_session(
                    str(getattr(chat, "id", chat)),
                    handed_off=0,
                    step="await_intent",
                    manager_id=mid,
                )
                await answer("Бот снова отвечает в этом чате.")
            elif cmd == "/send":
                task = _outreach_tasks.get(mid)
                if task and not task.done():
                    await answer("Уже идёт. /stop")
                else:
                    from bot.dashboard.distribute import (
                        build_day_queue,
                        daily_shares_for_account,
                    )
                    from bot.tg_accounts import get_tg_accounts

                    lim = _lim()
                    tg = get_tg_accounts()
                    acc = tg.for_manager(mid) or tg.main()
                    daily = int(acc.daily_send_limit) if acc else lim.daily_limit
                    aid = acc.id if acc else "main"
                    shares = daily_shares_for_account(daily)
                    pending = build_day_queue(
                        store,
                        daily_limit=daily,
                        account_id=aid,
                        only_manager_id=mid,
                    )
                    if not pending:
                        await answer(
                            f"Нет pending в вашей доле на сегодня "
                            f"(доля {shares.get(mid, 0)} из {daily}). /add …"
                        )
                    elif not args or (args[0].lower() not in ("go", "start", "да")):
                        lines = [
                            f"Превью /send [{mid}]: доля сегодня {shares.get(mid, 0)}/{daily}, "
                            f"в очереди {len(pending)} (без отправки).",
                            f"Доли команды: {shares}",
                            *lim.status_lines(pending_count=len(pending)),
                        ]
                        ok_cap, why = lim.can_send()
                        if not ok_cap:
                            lines.append(f"Сейчас не шлём: {why}")
                            lines.append(
                                "При /send go бот дождётся окна или продолжит завтра."
                            )
                        lines.append("Кого напишем:")
                        for c in pending[:25]:
                            lines.append(
                                f"· {c['status']}: {c['phone']} {c.get('name') or ''}".strip()
                            )
                        if len(pending) > 25:
                            lines.append(f"… и ещё {len(pending) - 25}")
                        lines.append("Чтобы реально стартовать: /send go")
                        await answer("\n".join(lines))
                    else:
                        _stop_flags[mid] = False
                        plan = lim.planned_today(len(pending))
                        await answer(
                            f"Старт очереди [{mid}]: {len(pending)} шт. "
                            f"(доля {shares.get(mid, 0)}/{daily}). "
                            f"Сегодня аккаунт: {lim.sent_today()}/{lim.daily_limit}, "
                            f"план ~{plan}.\n"
                            f"Часы: {lim.work_start}:00–{lim.work_end}:00 {lim.tz_name}."
                        )
                        _outreach_tasks[mid] = asyncio.create_task(
                            _run_outreach(
                                client,
                                store,
                                engine,
                                settings,
                                pending,
                                notify_admin,
                                owner_ids,
                                manager=manager,
                            )
                        )
            else:
                await answer("Не знаю команду. /help")
        except Exception:
            logger.exception("command crashed")
            await notify_admin(f"⚠️ Ошибка команды {cmd} — смотри логи. Гостю не слал.")
        return True

    # импорт CSV ответом на файл
    @client.on(events.NewMessage(func=lambda e: bool(e.out) and bool(e.is_reply)))
    async def on_import_reply(event: events.NewMessage.Event) -> None:
        text = (event.raw_text or "").strip().lower()
        if text.split()[0].split("@")[0] != "/import_csv":
            return
        try:
            reply = await event.get_reply_message()
            if not reply or not reply.file:
                await client.send_message(event.chat_id, "Нужен ответ на CSV-файл.")
                return
            data = await reply.download_media(bytes)
            if not data:
                await client.send_message(event.chat_id, "Не прочитал файл.")
                return
            text_csv = data.decode("utf-8-sig", errors="replace")
            stats = store.import_contacts_csv(
                text_csv, default_manager_id=reg.default_manager_id
            )
            await client.send_message(
                event.chat_id,
                f"Импорт: ok={stats['ok']} bad={stats['bad']}. "
                f"Незакреплённые → default ({reg.default_manager_id}).",
            )
        except Exception:
            logger.exception("import_csv")
            await notify_admin("Сбой /import_csv")

    pending_guests: list[dict[str, Any]] = []
    _screen_lock = asyncio.Lock()
    from bot.presence import ActiveConversation
    from bot.reply_guard import GuestInbox

    active_conv = ActiveConversation()
    guest_inbox = GuestInbox()
    _inbox_guard = asyncio.Lock()
    _DEBOUNCE_SEC = 0.6

    def _duplicate_live(cid: str, message_id: str, text: str) -> bool:
        mid_s = str(message_id or "")
        if mid_s and guest_inbox.has(cid, mid_s):
            return True
        waiting = list(guest_inbox.buckets.get(cid, []))
        waiting.extend(
            p for p in pending_guests if str(p.get("chat_id") or "") == cid
        )
        for item in waiting:
            if mid_s and str(item.get("message_id") or "") == mid_s:
                return True
            if text and str(item.get("text") or "").strip() == text:
                return True
        return False

    async def _arm_debounce(cid: str) -> None:
        """Короткая пауза: новые пузыри сбрасывают таймер, ответ один."""
        async with _inbox_guard:
            gen = guest_inbox.bump(cid)

        async def _later() -> None:
            try:
                await asyncio.sleep(_DEBOUNCE_SEC)
            except asyncio.CancelledError:
                return
            async with _inbox_guard:
                items = guest_inbox.pop_if_gen(cid, gen)
            if not items:
                return
            await _flush_guest_batch(items)

        asyncio.create_task(_later())

    async def _steal_late(cid: str) -> list[dict[str, Any]]:
        """Сообщения, пришедшие пока генерировался ответ."""
        async with _inbox_guard:
            late = guest_inbox.steal(cid)
            moved: list[dict[str, Any]] = []
            stay: list[dict[str, Any]] = []
            for item in pending_guests:
                if str(item.get("chat_id") or "") == cid:
                    moved.append(item)
                else:
                    stay.append(item)
            pending_guests[:] = stay
        return late + moved

    async def _screen_incoming(event: events.NewMessage.Event) -> None:
        from bot.contacts_import import ensure_telegram_user
        from bot.number_screen import format_report, pairs_from_file, screen_pairs

        async with _screen_lock:
            fname = str(getattr(getattr(event, "file", None), "name", "") or "list.csv")
            try:
                data = await event.download_media(bytes)
            except Exception:
                logger.exception("screen download")
                await client.send_message(event.chat_id, "Не смог прочитать файл.")
                return
            if not data:
                await client.send_message(event.chat_id, "Файл пустой.")
                return
            pairs, dropped = pairs_from_file(data, fname)
            if not pairs:
                await client.send_message(
                    event.chat_id,
                    "В файле не нашёл номеров. Нужен csv, txt или xlsx.",
                )
                return
            await client.send_message(
                event.chat_id,
                f"Смотрю {len(pairs)} номеров: кто есть в Telegram. Сообщения гостям не пишу.",
            )

            async def _checker(phone: str, name: str) -> tuple[str | None, str]:
                uid_s, status = await ensure_telegram_user(
                    client,
                    store,
                    phone=phone,
                    name=name,
                    account_id=aid,
                )
                await asyncio.sleep(1.2)
                return uid_s, status

            async def _beat(done: int, total: int) -> None:
                await client.send_message(event.chat_id, f"Проверено {done} из {total}.")

            try:
                stats = await screen_pairs(
                    pairs,
                    store=store,
                    checker=_checker,
                    daily=int(manager.daily_send_limit or 30),
                    manager_id=mid,
                    account_id=aid,
                    sent_today=_lim().sent_today(),
                    pause=asyncio.sleep,
                    progress=_beat,
                )
            except Exception:
                logger.exception("screen file")
                await client.send_message(event.chat_id, "Проверка файла оборвалась. Хвост не трогал.")
                return
            stats["skipped_own"] = dropped
            await client.send_message(event.chat_id, format_report(stats))
            missing = stats.get("missing_phones") or []
            if missing:
                body = "нет в Telegram\n" + "\n".join(missing)
                bio = io.BytesIO(body.encode("utf-8"))
                bio.name = "net-v-telegram.txt"
                await client.send_file(event.chat_id, bio)

    @client.on(events.NewMessage)
    async def on_any(event: events.NewMessage.Event) -> None:
        text = (event.raw_text or "").strip()
        uid = event.sender_id
        logger.info(
            "msg in=%s out=%s uid=%s private=%s text=%r",
            not event.out,
            event.out,
            uid,
            event.is_private,
            text[:80],
        )

        fname = str(getattr(getattr(event, "file", None), "name", "") or "")
        from bot.number_screen import is_number_file

        chat_ok = int(getattr(event, "chat_id", 0) or 0) == int(me.id)
        from_owner = (uid in owner_ids) and not event.out
        if fname and is_number_file(fname) and event.is_private and (chat_ok or from_owner):
            if _screen_lock.locked():
                await client.send_message(event.chat_id, "Уже проверяю предыдущий файл.")
                return
            asyncio.create_task(_screen_incoming(event))
            return

        is_admin = bool(event.out) or (uid in owner_ids)

        # /команды только от админов / с этого акка
        if text.startswith("/") and is_admin:
            try:
                await handle_command(event.chat_id, text, event.id)
            except Exception:
                logger.exception("command failed")
                await notify_admin(f"Сбой команды {text[:40]}")
            return

        # исходящие: сообщения менеджера с телефона/панели → takeover; свои бот-реплики игнор
        if event.out:
            if not event.is_private or not text or text.startswith("/"):
                return
            chat_id = str(event.chat_id)
            if was_bot_outbound(chat_id, getattr(event, "id", None)) or was_bot_outbound(
                event.chat_id, getattr(event, "id", None)
            ):
                return
            # менеджер написал сам — бот молчит до «Вернуть боту»
            store.save_session(chat_id, handed_off=1, step="handed_off", manager_id=mid)
            try:
                store.add_message(
                    chat_id,
                    "manager",
                    text,
                    sender_label="Telegram",
                    manager_id=mid,
                )
            except Exception:
                pass
            try:
                get_hub().bus.publish(
                    "takeover", chat_id=chat_id, active=True, by="Telegram"
                )
            except Exception:
                pass
            logger.info("manager outbound → handed_off chat=%s", chat_id)
            return
        if not event.is_private:
            return
        if text.startswith("/"):
            return
        if not text:
            return

        # никогда не отвечаем ботам / SpamBot / сервисам Telegram
        sender = await event.get_sender()
        if sender and (
            getattr(sender, "bot", False)
            or getattr(sender, "is_self", False)
            or int(getattr(sender, "id", 0) or 0) in (777000, 178220800, 42777)  # TG / SpamBot
            or str(getattr(sender, "username", "") or "").lower()
            in ("spambot", "spaminfo", "spaminfobot", "botfather", "telegram")
        ):
            logger.info("skip bot/service uid=%s", getattr(sender, "id", None))
            return

        chat_id = str(event.chat_id)
        inbound_id = str(getattr(event, "id", "") or "")
        if not _take_speaker(store, chat_id, inbound_id, aid):
            return
        # клиент другого менеджера — не отвечаем с этого аккаунта
        owner = store.contact_manager_id(chat_id=chat_id) or (
            store.get_session(chat_id).get("manager_id") or ""
        )
        if owner and owner != mid:
            logger.info("skip chat=%s owned by %s (this=%s)", chat_id, owner, mid)
            return

        # окна проверки / active mode
        from bot.presence import get_check_settings

        cw = get_check_settings(store)
        if cw.get("enabled", True):
            sess0 = store.get_session(chat_id)
            # молчим, только пока менеджер писал в последние 15 минут
            if _stay_quiet_for_manager(store, chat_id, sess0):
                if (sess0.get("step") or "") != "handed_off":
                    store.save_session(chat_id, step="handed_off")
                store.add_message(chat_id, "guest", text, manager_id=mid)
                logger.info("silent handed_off (queued path) chat=%s", chat_id)
                return
            if (sess0.get("step") or "") == "handed_off":
                store.save_session(chat_id, step="await_dates")

            inbound_id = str(getattr(event, "id", "") or "")
            if _duplicate_live(chat_id, inbound_id, text):
                logger.info("dup inbound skip chat=%s id=%s", chat_id, inbound_id)
                return
            store.add_message(chat_id, "guest", text, manager_id=mid)
            item = _queue_item(
                chat_id,
                text,
                event=event,
                message_id=inbound_id,
                logged=True,
            )
            # короткая склейка пачки, без окна «проверки» на минуты
            guest_inbox.push(item)
            try:
                store.enqueue_inbound(
                    chat_id,
                    text,
                    message_id=str(item.get("message_id") or ""),
                    manager_id=mid,
                )
            except Exception:
                logger.exception("persist inbound queue chat=%s", chat_id)
            await _arm_debounce(chat_id)
            logger.info("debounce guest chat=%s", chat_id)
            return

        # legacy: сразу прочитал + ответ
        try:
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await client.send_read_acknowledge(event.chat_id, max_id=event.id)
        except Exception:
            logger.debug("read ack failed", exc_info=True)
        async with _lock_for(chat_id):
            await _handle_guest(event, chat_id, already_logged=False)

    async def _handle_guest(
        event: events.NewMessage.Event,
        chat_id: str,
        *,
        already_logged: bool = False,
        text_override: str = "",
        from_hold: bool = False,
    ) -> None:
        text = (text_override or event.raw_text or "").strip()
        sender = await event.get_sender()
        sess = store.get_session(chat_id)
        # закрепить диалог за этим менеджером, если ещё не закреплён
        if not (sess.get("manager_id") or "").strip():
            store.save_session(chat_id, manager_id=mid)
            sess["manager_id"] = mid
        # подтянуть настоящее имя из TG; заглушки (Клиент/Гость/телефон) не считаются именем
        try:
            from bot.phrases import is_placeholder_name, real_first_name
        except Exception:
            is_placeholder_name = lambda _n: not (_n or "").strip()  # type: ignore
            real_first_name = lambda _n: (_n or "").strip()  # type: ignore
        cur_name = sess.get("name") or ""
        if (not cur_name or is_placeholder_name(cur_name)) and sender:
            name = " ".join(
                x
                for x in [
                    getattr(sender, "first_name", ""),
                    getattr(sender, "last_name", ""),
                ]
                if x
            )
            if name and not is_placeholder_name(name):
                store.save_session(chat_id, name=name)
                sess["name"] = name
            elif cur_name and is_placeholder_name(cur_name):
                store.save_session(chat_id, name="")
                sess["name"] = ""
        # глобальный стоп-лист — никогда не пишем и не reopen
        if store.is_stopped_chat(chat_id) or (sess.get("context") or {}).get("stopped"):
            logger.info("ignore stopped chat=%s", chat_id)
            return

        # Менеджер ведёт чат только 15 минут после своей реплики, потом бот отвечает
        if _stay_quiet_for_manager(store, chat_id, sess):
            if (sess.get("step") or "") != "handed_off":
                store.save_session(chat_id, step="handed_off")
            if not already_logged:
                store.add_message(chat_id, "guest", text, manager_id=mid)
            logger.info("silent handed_off chat=%s", chat_id)
            return

        # неизвестный step от старого ИИ — сбрасываем на воронку
        known = {
            "greeting",
            "await_intent",
            "await_dates",
            "await_guests",
            "await_district",
            "await_returning",
            "await_favorite",
            "browsing",
            "bonus",
            "done",
            "handed_off",
            "looking",
        }
        if (sess.get("step") or "") not in known:
            store.save_session(chat_id, step="await_intent")
            sess["step"] = "await_intent"

        if not already_logged:
            store.add_message(chat_id, "guest", text, manager_id=mid)
        history = store.recent_messages(chat_id, limit=24)
        msgs: list[str] = []
        buttons = None
        updates: dict[str, Any] = {}
        escalate = False
        try:
            msgs, buttons, updates, escalate = await asyncio.wait_for(
                ai_reply(settings, engine, sess, text, history),
                timeout=14.0,
            )
        except asyncio.TimeoutError:
            logger.warning("reply timeout chat=%s", chat_id)
            await notify_admin(f"Таймаут ответа · чат {chat_id}")
            from bot.reply_guard import finished_next_line

            msgs = [finished_next_line(sess)]
        except Exception:
            logger.exception("reply pipeline")
            await notify_admin(f"Сбой ответа · чат {chat_id}")
            msgs = ["Уточню у коллеги и сразу вернусь 🙂"]
            escalate = False

        late = await _steal_late(chat_id)
        extra_lines: list[str] = []
        for part in late:
            bit = str(part.get("text") or "").strip()
            if bit and bit not in text and bit not in extra_lines:
                extra_lines.append(bit)
            try:
                store.dequeue_inbound(
                    chat_id,
                    message_id=str(part.get("message_id") or ""),
                    manager_id=mid,
                    text=bit,
                )
            except Exception:
                pass
        if extra_lines:
            text = (text + "\n" + "\n".join(extra_lines)).strip()
            logger.info("fold late chat=%s n=%s", chat_id, len(extra_lines))
            history = store.recent_messages(chat_id, limit=24)
            try:
                msgs, buttons, updates, escalate = await asyncio.wait_for(
                    ai_reply(settings, engine, sess, text, history),
                    timeout=14.0,
                )
            except Exception:
                logger.exception("refold reply chat=%s", chat_id)

        safe = _guest_safe(msgs)
        # сначала сохраняем сессию — до отправки, чтобы гонка не откатывала шаг
        stop_req = bool(updates.pop("stop_requested", False)) if updates else False
        if updates:
            if updates.get("step") and updates["step"] not in known:
                updates.pop("step", None)
            try:
                store.save_session(chat_id, **updates)
                sess.update(updates)
            except Exception:
                logger.exception("session save")
                await notify_admin(f"Не сохранил сессию {chat_id}")

        if stop_req or (sess.get("context") or {}).get("stopped"):
            store.mark_stopped(chat_id=chat_id)
            logger.info("stop-list chat=%s", chat_id)

        # после outreach: без re-hello, но сводку / карточки / следующий вопрос не ронять
        try:
            from bot.phrases import already_greeted as _already_greeted
        except Exception:
            _already_greeted = lambda _s: False  # type: ignore
        hist_bot = [h for h in history if (h.get("role") or "") == "bot"]
        post_opener = bool(hist_bot) or _already_greeted(sess)
        step_now = str((updates or {}).get("step") or sess.get("step") or "")
        safe, send_max = finalize_post_outreach_msgs(
            safe,
            post_opener=post_opener,
            step=step_now,
            known=sess,
            path=str(((updates or {}).get("context") or {}).get("reply_path") or ""),
        )
        from bot.question_dedupe import dedupe_slot_questions
        from bot.reply_guard import collapse_repeat_asks, strip_repeated_outbound

        previous_bot = "\n".join(str(h.get("text") or "") for h in hist_bot[-2:])
        safe = strip_repeated_outbound(safe, previous_bot)
        safe = collapse_repeat_asks(safe, previous_bot)
        safe = dedupe_slot_questions(safe)
        if not safe and from_hold and escalate:
            # гость ждал менеджера 15 минут — не молчим и не повторяем «сейчас подключу»
            from bot.handoff_hold import HOLD_SORRY_LINE

            safe = [HOLD_SORRY_LINE]
        elif safe and from_hold and not escalate and not any("?" in m for m in safe) and not any(
            re.search(r"(?m)^1\)", m) for m in safe
        ):
            # ответили на вопрос, пока менеджер занят: гость должен знать, что бронь не потерялась
            from bot.handoff_hold import HOLD_NOTE

            if HOLD_NOTE.lower() not in safe[-1].lower():
                safe[-1] = f"{safe[-1].rstrip()} {HOLD_NOTE}"
        if not safe:
            # повторный запрос квартир/района — не молчим после антидубля
            guest_ask = (text or "").strip()
            if re.search(
                r"(?i)свободн|квартир|вариант|пришлите|покажите|центр|какие\s+есть",
                guest_ask,
            ):
                if not str(sess.get("guests") or "").strip():
                    safe = ["Напишите, сколько вас будет — сверю свободные под вас."]
                elif ((sess.get("context") or {}).get("offers")):
                    safe = ["Варианты выше. Напишите номер или название."]
                else:
                    safe = ["Напишите даты, район и сколько вас — подберу свободные."]
            else:
                logger.info("skip echo reply chat=%s", chat_id)
                return
        from bot.handoff_hold import already_answered

        if already_answered(store.recent_messages(chat_id, limit=12), safe):
            # этот же ответ уже ушёл (догон после рестарта + проверка паузы, второй процесс) — не дублируем
            logger.info("skip duplicate answer chat=%s", chat_id)
            return
        for m in safe:
            store.add_message(chat_id, "bot", m, sender_label="бот", manager_id=mid)
        try:
            await _human_send(
                client,
                event.chat_id,
                safe,
                buttons,
                max_msgs=send_max,
            )
        except Exception as e:
            err = type(e).__name__
            if "UserBlocked" in err or "YouBlocked" in err or "PeerIdInvalid" in err:
                logger.warning("skip send %s chat=%s", err, chat_id)
                store.mark_stopped(chat_id=chat_id)
            else:
                logger.exception("send to guest failed")
                await notify_admin(f"Не отправил гостю {chat_id}")
            return

        if escalate:
            from bot.phrases import client_report

            report = (sess.get("context") or {}).get("report") if isinstance(
                sess.get("context"), dict
            ) else None
            body = report or client_report(sess, guest_text=text)
            await notify_admin(body)
        # в active mode offline только после тишины (см. check_window_loop);
        # иначе — сразу offline, чтобы не светить зелёный статус
        try:
            from bot.presence import get_check_settings, set_offline

            if not active_conv.is_active(get_check_settings(store)):
                await set_offline(client)
        except Exception:
            pass

    async def _flush_guest_batch(items: list[dict[str, Any]]) -> None:
        """Один чат — один ответ, даже если гость прислал три сообщения подряд."""
        from bot.presence import get_check_settings

        for bucket in coalesce_guest_batch(items):
            cid = bucket["chat_id"]
            ev = bucket["event"]
            if store.last_message_role(cid) in ("bot", "manager"):
                # пока сообщения ждали в очереди, на них уже ответили (бот после паузы или менеджер)
                for part in bucket["parts"]:
                    store.dequeue_inbound(
                        cid,
                        message_id=str(part.get("message_id") or ""),
                        manager_id=mid,
                        text=str(part.get("text") or ""),
                    )
                logger.info("skip answered batch chat=%s", cid)
                continue
            try:
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await client.send_read_acknowledge(
                    ev.chat_id, max_id=getattr(ev, "id", None)
                )
            except Exception:
                logger.debug("read ack batch", exc_info=True)
            try:
                async with _lock_for(cid):
                    await _handle_guest(
                        ev,
                        cid,
                        already_logged=True,
                        text_override=bucket["text"],
                    )
                for part in bucket["parts"]:
                    store.dequeue_inbound(
                        cid,
                        message_id=str(part.get("message_id") or ""),
                        manager_id=mid,
                        text=str(part.get("text") or ""),
                    )
                active_conv.touch(get_check_settings(store))
                logger.info(
                    "batch reply chat=%s parts=%s",
                    cid,
                    len(bucket["texts"]),
                )
            except Exception:
                logger.exception("batch reply chat=%s", cid)

    async def handoff_release_loop() -> None:
        """Гость писал, пока чат у менеджера, а менеджер 15 минут молчит — отвечает бот.

        Раз в минуту смотрим переданные чаты. Если после последней реплики менеджера/бота
        прошло 15 минут и есть неотвеченные сообщения гостя — бот обрабатывает их одним ответом.
        """
        from bot.handoff_hold import take_unanswered

        await asyncio.sleep(30)
        while True:
            try:
                for cid in store.list_held_chats(manager_id=mid):
                    text = take_unanswered(store, cid, mid)
                    if not text:
                        continue
                    logger.info("hold expired → bot answers chat=%s parts=%s", cid, text.count("\n") + 1)
                    async with _lock_for(cid):
                        await _handle_guest(
                            QueuedGuestEvent(cid, text),
                            cid,
                            already_logged=True,
                            text_override=text,
                            from_hold=True,
                        )
                    await notify_admin(
                        f"Менеджер не ответил за 15 минут — бот ответил гостю сам · чат {cid}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if is_session_dead_error(e):
                    logger.error("handoff release loop stopped — session dead")
                    return
                logger.exception("handoff release loop")
            await asyncio.sleep(60)

    async def check_window_loop() -> None:
        """Окна проверки + выход из active mode после тишины гостя."""
        from bot.presence import get_check_settings, next_wait_seconds, set_offline

        await set_offline(client)
        logger.info(
            "check windows on mgr=%s interval≈%s min active_idle≈%s min",
            mid,
            get_check_settings(store).get("interval_min"),
            get_check_settings(store).get("active_idle_min"),
        )
        while True:
            try:
                cw = get_check_settings(store)
                if pending_guests:
                    batch = list(pending_guests)
                    pending_guests.clear()
                    logger.info("flush queued guests now: %s", len(batch))
                    await _flush_guest_batch(batch)
                try:
                    store.purge_finished()
                except Exception:
                    logger.debug("purge finished", exc_info=True)
                # в active mode чаще проверяем idle; окна — только когда не active
                if active_conv.is_active(cw):
                    await asyncio.sleep(20)
                    if active_conv.just_left_active(get_check_settings(store)):
                        await set_offline(client)
                        logger.info("left active mode → offline + check windows")
                    continue

                if active_conv.just_left_active(cw):
                    await set_offline(client)
                    logger.info("left active mode → offline + check windows")

                wait = next_wait_seconds(cw)
                await asyncio.sleep(wait)
                await set_offline(client)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                name = type(e).__name__
                if is_session_dead_error(e) or "SessionRevoked" in name:
                    logger.error("check window stopped — session dead (%s)", name)
                    return
                logger.exception("check window loop")
                await asyncio.sleep(10)

    async def _consume_outreach_jobs() -> None:
        from bot.outreach_jobs import pending as outreach_pending
        from bot.outreach_jobs import write_status

        for job_path in outreach_pending():
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("outreach job unreadable %s", job_path)
                job_path.unlink(missing_ok=True)
                continue
            action = str(job.get("action") or "start")
            job_mid = str(job.get("manager_id") or mid)
            if action == "stop":
                job_path.unlink(missing_ok=True)
                _stop_flags[job_mid] = True
                write_status(job_mid, running=False, note="остановлено с панели")
                get_hub().set_outreach(job_mid, running=False, note="стоп с панели")
                continue
            task = _outreach_tasks.get(job_mid)
            if task and not task.done():
                continue
            job_path.unlink(missing_ok=True)
            phones = [str(p) for p in (job.get("phones") or []) if p]
            now = bool(job.get("now"))

            async def _go(phones=phones, job_mid=job_mid, now=now) -> None:
                rows: list[dict] = []
                if phones:
                    for phone in phones:
                        row = store.contact_by_phone(phone)
                        send_on = str((row or {}).get("send_on") or "")
                        due = (not send_on) or send_on <= _moscow_today()
                        if row and row.get("status") == "pending" and due:
                            rows.append(row)
                    if not rows:
                        write_status(
                            job_mid,
                            running=False,
                            note="номер не в очереди: уже отправлен, стоп или не на сегодня",
                            count=0,
                        )
                        return
                else:
                    rows = store.list_outreach_batch(
                        limit=80,
                        manager_id=job_mid,
                        default_manager_id=reg.default_manager_id,
                    )
                write_status(
                    job_mid,
                    running=True,
                    note=f"отправляю {len(rows)}" + (" сейчас" if now else ""),
                    count=len(rows),
                )

                async def _note(text: str) -> None:
                    write_status(job_mid, running=True, note=text[:240])
                    get_hub().set_outreach(job_mid, running=True, note=text[:200])

                try:
                    await _run_outreach(
                        client,
                        store,
                        engine,
                        settings,
                        rows,
                        _note,
                        set(),
                        manager=reg.get(job_mid) or manager,
                        skip_window=now,
                    )
                    from bot.outreach_jobs import read_status

                    done = read_status(job_mid)
                    write_status(
                        job_mid,
                        running=False,
                        note=str(done.get("note") or "готово")[:240],
                        count=done.get("count", len(rows)),
                    )
                except Exception:
                    logger.exception("panel outreach")
                    write_status(job_mid, running=False, note="ошибка отправки, смотрите журнал")

            _outreach_tasks[job_mid] = asyncio.create_task(_go())
            logger.info("panel outreach start mid=%s phones=%s now=%s", job_mid, len(phones), now)

    async def poll_saved() -> None:
        last = 0
        try:
            async for m in client.iter_messages("me", limit=1):
                last = m.id
        except Exception:
            logger.exception("poll init")
        logger.info("poll Saved Messages from id>%s", last)
        while True:
            try:
                await asyncio.sleep(2)
                cmd_file = Path("data/cmd.txt")
                if cmd_file.exists():
                    raw = cmd_file.read_text().strip()
                    cmd_file.unlink(missing_ok=True)
                    if raw.startswith("/"):
                        logger.info("file CMD %r", raw)
                        await handle_command("me", raw)
                try:
                    from bot.human import begin_bot_send, end_bot_send, mark_bot_outbound
                    from bot.panel_outbox import pending as panel_pending

                    for job_path in panel_pending():
                        job = json.loads(job_path.read_text(encoding="utf-8"))
                        cid = str(job.get("chat_id") or "").strip()
                        body = str(job.get("text") or "").strip()
                        if not cid or not body:
                            job_path.unlink(missing_ok=True)
                            continue
                        target = int(cid) if cid.lstrip("-").isdigit() else cid
                        begin_bot_send(cid)
                        try:
                            sent = await client.send_message(target, body)
                            mark_bot_outbound(
                                cid, int(getattr(sent, "id", 0) or 0), ttl=90.0
                            )
                        finally:
                            end_bot_send(cid)
                        job_path.unlink(missing_ok=True)
                        logger.info("panel outbox sent chat=%s", cid)
                except Exception:
                    logger.exception("panel outbox")
                try:
                    await _consume_outreach_jobs()
                except Exception:
                    logger.exception("outreach jobs")
                async for m in client.iter_messages("me", limit=8):
                    if m.id <= last:
                        break
                    body = (m.message or "").strip()
                    if m.out and body.startswith("/"):
                        logger.info("poll CMD %r id=%s", body, m.id)
                        await handle_command("me", body, m.id)
                async for m in client.iter_messages("me", limit=1):
                    if m.id > last:
                        last = m.id
                    break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                name = type(e).__name__
                if is_session_dead_error(e) or "SessionRevoked" in name or "AuthKeyUnregistered" in name:
                    logger.error(
                        "poll Saved Messages stopped — session dead (%s)", name
                    )
                    _account_session_dead(aid, mid, f"{name}: poll")
                    return
                logger.exception("poll loop")
                await asyncio.sleep(5)

    online_text = (
        f"Home24 online ✅ [{mid}] @{me.username}\n"
        f"Аккаунт: {aid}\n"
        f"Менеджер: {manager.name}\n"
        f"ИИ: {'ON · ' + settings.openai_model if settings.ai_ready else 'OFF'}\n"
        f"Лимит первых: {manager.daily_send_limit}/день · "
        f"{manager.work_hours_start}:00–{manager.work_hours_end}:00 "
        f"{manager.work_timezone}\n"
        f"Ошибки и заявки → панель. Гостям — только живые реплики.\n"
        f"/help"
    )
    await report_account_online(
        client,
        account_id=aid,
        manager_id=mid,
        telegram_user_id=int(me.id),
        text=online_text,
        report_to=report_to,
        username=me.username or "",
    )
    async def _restore_inbound_queue() -> None:
        """После рестарта: БД-очередь + непрочитанные лички за 24ч."""
        seen: set[str] = set()
        try:
            for row in store.list_inbound_queue(manager_id=mid):
                cid = str(row.get("chat_id") or "")
                text = str(row.get("text") or "").strip()
                if not cid or not text:
                    continue
                key = f"{cid}:{row.get('message_id') or text}"
                if key in seen or _duplicate_live(
                    cid, str(row.get("message_id") or ""), text
                ):
                    continue
                seen.add(key)
                sess = store.get_session(cid)
                if sess.get("handed_off") or (sess.get("step") or "") == "handed_off":
                    store.dequeue_inbound(
                        cid,
                        message_id=str(row.get("message_id") or ""),
                        manager_id=mid,
                        text=text,
                    )
                    continue
                pending_guests.append(
                    _queue_item(
                        cid,
                        text,
                        message_id=str(row.get("message_id") or ""),
                        logged=True,
                    )
                )
        except Exception:
            logger.exception("restore inbound_queue from db")

        # гость писал после паузы менеджера — ответить, даже если чат уже прочитан
        try:
            import time as _time

            from bot.handoff_hold import handoff_hold_active

            fresh = _time.time() - 36 * 3600
            async for dialog in client.iter_dialogs(limit=40):
                try:
                    if not getattr(dialog, "is_user", False):
                        continue
                    ent = dialog.entity
                    if getattr(ent, "bot", False) or getattr(ent, "is_self", False):
                        continue
                    cid = str(dialog.id)
                    owner = store.contact_manager_id(chat_id=cid) or (
                        store.get_session(cid).get("manager_id") or ""
                    )
                    if owner and owner != mid:
                        continue
                    sess = store.get_session(cid)
                    if not (
                        sess.get("handed_off") or (sess.get("step") or "") == "handed_off"
                    ):
                        continue
                    if store.is_stopped_chat(cid) or (sess.get("context") or {}).get(
                        "stopped"
                    ):
                        continue
                    if store.last_message_role(cid) not in ("guest", "user"):
                        continue
                    recent = store.recent_messages(cid, limit=40)
                    if handoff_hold_active(recent):
                        continue
                    staff_at = 0.0
                    for item in recent:
                        if (item.get("role") or "") in ("bot", "manager"):
                            staff_at = max(staff_at, float(item.get("created_at") or 0))
                    waiting = [
                        item
                        for item in recent
                        if (item.get("role") or "") in ("guest", "user")
                        and float(item.get("created_at") or 0) > staff_at
                        and float(item.get("created_at") or 0) >= fresh
                    ]
                    if not waiting:
                        continue
                    bound = str((sess.get("context") or {}).get("tg_account") or "").strip()
                    if bound and bound != aid:
                        continue
                    last_id = waiting[-1].get("id") or waiting[-1].get("text")
                    if not store.claim_meta(f"resume:{cid}:{last_id}"):
                        continue
                    if _stay_quiet_for_manager(store, cid, sess):
                        continue
                    ctx = dict(store.get_session(cid).get("context") or {})
                    if not str(ctx.get("tg_account") or "").strip():
                        ctx["tg_account"] = aid
                        store.save_session(cid, context=ctx)
                    logger.info(
                        "resume unanswered chat=%s n=%s", cid, len(waiting)
                    )
                    for item in waiting:
                        body = str(item.get("text") or "").strip()
                        if not body:
                            continue
                        key = f"{cid}:{item.get('id') or body}"
                        seen.add(key)
                        pending_guests.append(
                            _queue_item(
                                cid,
                                body,
                                message_id=str(item.get("id") or ""),
                                logged=True,
                            )
                        )
                except Exception:
                    logger.debug("resume handoff skip", exc_info=True)
        except Exception:
            logger.exception("resume stale handoff")

        # непрочитанные private за сутки — если бот ещё не ответил после последнего гостя
        try:
            import time as _time

            cutoff = _time.time() - 24 * 3600
            async for dialog in client.iter_dialogs(limit=40):
                try:
                    if not getattr(dialog, "is_user", False):
                        continue
                    ent = dialog.entity
                    if getattr(ent, "bot", False) or getattr(ent, "is_self", False):
                        continue
                    unread = int(getattr(dialog, "unread_count", 0) or 0)
                    if unread <= 0:
                        continue
                    cid = str(dialog.id)
                    owner = store.contact_manager_id(chat_id=cid) or (
                        store.get_session(cid).get("manager_id") or ""
                    )
                    if owner and owner != mid:
                        continue
                    sess = store.get_session(cid)
                    if sess.get("handed_off") or (sess.get("step") or "") == "handed_off":
                        continue
                    if store.is_stopped_chat(cid):
                        continue
                    # последнее наше сообщение позже гостя — уже ответили
                    if store.last_message_role(cid) in ("bot", "manager"):
                        continue
                    async for msg in client.iter_messages(dialog, limit=min(unread, 8)):
                        if getattr(msg, "out", False):
                            break
                        body = (getattr(msg, "message", None) or "").strip()
                        if not body or body.startswith("/"):
                            continue
                        ts = getattr(msg, "date", None)
                        if ts is not None:
                            try:
                                if ts.timestamp() < cutoff:
                                    continue
                            except Exception:
                                pass
                        key = f"{cid}:{getattr(msg, 'id', '') or body}"
                        if key in seen or _duplicate_live(
                            cid, str(getattr(msg, "id", "") or ""), body
                        ):
                            continue
                        seen.add(key)
                        store.add_message(cid, "guest", body, manager_id=mid)
                        item = _queue_item(
                            cid,
                            body,
                            message_id=str(getattr(msg, "id", "") or ""),
                            logged=True,
                        )
                        pending_guests.append(item)
                        store.enqueue_inbound(
                            cid,
                            body,
                            message_id=str(item.get("message_id") or ""),
                            manager_id=mid,
                        )
                except Exception:
                    logger.debug("recover dialog skip", exc_info=True)
        except Exception:
            logger.exception("recover unread private")

        if pending_guests:
            logger.info(
                "startup inbound restore mgr=%s pending=%s", mid, len(pending_guests)
            )

    await _restore_inbound_queue()
    if pending_guests:
        startup_batch = list(pending_guests)
        pending_guests.clear()
        logger.info("startup flush mgr=%s n=%s", mid, len(startup_batch))
        await _flush_guest_batch(startup_batch)
    try:
        from bot.smart import log_smart_startup

        log_smart_startup()
    except Exception:
        logger.debug("smart startup log failed", exc_info=True)
    asyncio.create_task(poll_saved())
    asyncio.create_task(check_window_loop())
    asyncio.create_task(handoff_release_loop())
    try:
        from bot.presence import set_offline

        await set_offline(client)
    except Exception:
        pass
    logger.info("listening + poll + check-windows mgr=%s", mid)
    hb_task = asyncio.create_task(_lock_heartbeat(aid), name=f"hb-{aid}")
    try:
        await client.run_until_disconnected()
    except Exception as e:
        name = type(e).__name__
        logger.error("bot disconnected mgr=%s account=%s: %s: %s", mid, aid, name, e)
        if is_session_dead_error(e):
            store.set_meta("last_error", f"{aid}/{mid}: {name}: session revoked")
            _account_session_dead(aid, mid, f"{name}: сессия отозвана")
            if dashboard_keepalive():
                return
            raise SystemExit(EXIT_SESSION_DEAD) from e
        raise
    finally:
        hb_task.cancel()
        get_hub().unregister_client(mid, account_id=aid)
        try:
            from bot.client_registry import release as release_client

            await release_client(aid, disconnect=True)
        except Exception:
            logger.debug("client release failed aid=%s", aid, exc_info=True)
        try:
            acc2 = tg.get(aid)
            if acc2:
                acc2.last_disconnect_at = __import__("time").time()
                tg.save()
        except Exception:
            pass


async def _lock_heartbeat(account_id: str) -> None:
    from bot.instance_guard import note_heartbeat

    name = f"account_{(account_id or '').strip() or 'main'}"
    while True:
        note_heartbeat(name)
        await asyncio.sleep(15)


async def run() -> None:
    """Запуск всех Telegram-аккаунтов компании в одном процессе."""
    await run_all()


async def run_all() -> None:
    from bot.instance_guard import acquire_global
    from bot.telegram_api import TelegramApiError, resolve_api_credentials

    ok_lock, lock_msg = acquire_global()
    if not ok_lock:
        logger.error("%s", lock_msg)
        raise SystemExit(1)

    try:
        resolve_api_credentials()
    except TelegramApiError as e:
        logger.error("%s", e)
        get_hub().notify(
            "Нужны свои Telegram API ключи",
            str(e),
            level="error",
        )
        if dashboard_keepalive():
            # панель остаётся — менеджер может вписать ключи
            logger.warning("Telegram не стартует без своих api_id/api_hash — панель открыта")
            while True:
                await asyncio.sleep(3600)
        raise SystemExit(str(e)) from e

    settings = get_settings()
    store = Store(settings.db_path)
    reg = get_registry()
    from bot.tg_accounts import get_tg_accounts

    tg = get_tg_accounts()
    for n in tg.repair_duplicates():
        logger.warning("startup repair: %s", n)

    from bot.session_blacklist import is_blacklisted

    # подтянуть legacy-сессию в main ТОЛЬКО если живая, не blacklist, не чужой слот
    default = reg.default()
    if not (default.session or "").strip():
        legacy = (store.get_meta("telethon_session") or settings.session or "").strip()
        if legacy and not is_blacklisted(legacy):
            reg.set_session(default.id, legacy)
            default.session = legacy
        elif legacy and is_blacklisted(legacy):
            logger.warning("skip blacklisted legacy session for managers default")
            try:
                from bot.session_io import purge_dead_session

                purge_dead_session(legacy)
            except Exception:
                pass
    main_acc = tg.main()
    if main_acc and not (main_acc.session or "").strip() and main_acc.status == "ok":
        legacy = (
            (default.session or "").strip()
            or (store.get_meta("telethon_session") or settings.session or "").strip()
        )
        if legacy and is_blacklisted(legacy):
            logger.warning("skip copying blacklisted TELEGRAM_SESSION into main")
            try:
                from bot.session_io import purge_dead_session

                purge_dead_session(legacy)
            except Exception:
                pass
        elif legacy and not tg.session_already_used(legacy, except_id=main_acc.id):
            tg.set_session(main_acc.id, legacy, phone=default.phone or None)
        elif legacy and tg.session_already_used(legacy, except_id=main_acc.id):
            logger.warning(
                "skip copying TELEGRAM_SESSION into main — already used by another account slot"
            )

    keepalive = dashboard_keepalive()

    async def _spawn_tasks(*, allow_legacy: bool) -> list[asyncio.Task]:
        # после отзыва / в keepalive — только слоты tg_accounts с новой живой сессией
        ready_accs = tg.unique_ready_ok()
        if ready_accs:
            logger.info(
                "starting %s telegram account(s): %s",
                len(ready_accs),
                ", ".join(f"{a.id}→{a.manager_id or '*'}" for a in ready_accs),
            )
            out: list[asyncio.Task] = []
            for a in ready_accs:
                mid = (a.manager_id or "").strip() or reg.default_manager_id
                m = reg.get(mid) or default
                m.daily_send_limit = int(a.daily_send_limit)
                m.weekly_send_limit = int(a.weekly_send_limit)
                out.append(
                    asyncio.create_task(
                        run_manager(
                            m, store, account_id=a.id, session_override=a.session
                        ),
                        name=f"acc-{a.id}",
                    )
                )
            return out
        if not allow_legacy:
            return []
        ready = [
            m
            for m in reg.enabled_list()
            if (m.session or "").strip()
            and not is_blacklisted(m.session or "")
            and not tg.session_already_used(m.session or "")
        ]
        if not ready:
            return []
        logger.info(
            "starting %s legacy manager session(s): %s",
            len(ready),
            ", ".join(m.id for m in ready),
        )
        return [
            asyncio.create_task(run_manager(m, store), name=f"mgr-{m.id}") for m in ready
        ]

    # первый старт может взять legacy; keepalive-respawn — только новый вход в Аккаунтах
    tasks = await _spawn_tasks(allow_legacy=not keepalive)
    if not tasks:
        logger.error("нет Telegram-аккаунтов с сессией — нужен вход в Аккаунты")
        if keepalive:
            logger.warning("dashboard keepalive: ждём повторный вход в Аккаунтах")
        else:
            raise SystemExit(EXIT_SESSION_DEAD)

    # если один упал — остальные живут; при keepalive панель не гасим
    exit_dead = False
    running_ids = {t.get_name() for t in tasks}
    while True:
        if not tasks:
            if keepalive:
                await asyncio.sleep(5)
                # тихо перечитать реестр; repair логирует только при реальных изменениях
                tg.load()
                notes = tg.repair_duplicates()
                for n in notes:
                    logger.warning("startup repair: %s", n)
                fresh = await _spawn_tasks(allow_legacy=False)
                fresh = [t for t in fresh if t.get_name() not in running_ids]
                if fresh:
                    logger.info("respawn %s account task(s) after re-login", len(fresh))
                    tasks = fresh
                    running_ids |= {t.get_name() for t in tasks}
                    exit_dead = False
                    continue
                continue
            if exit_dead:
                raise SystemExit(EXIT_SESSION_DEAD)
            return
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        tasks = list(pending)
        for t in done:
            running_ids.discard(t.get_name())
            try:
                t.result()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else EXIT_SESSION_DEAD
                if code == EXIT_SESSION_DEAD:
                    exit_dead = True
                    logger.error("manager task session dead: %s", t.get_name())
                else:
                    raise
            except Exception:
                logger.exception("manager task crashed: %s", t.get_name())
                exit_dead = True


async def _resolve_extra_admins(client: TelegramClient, store: Store) -> set[int]:
    ids: set[int] = set()
    raw = (store.get_meta("extra_admin_ids") or "").strip()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    # @BDOXA — управляющий акк
    for uname in ("BDOXA", "bdoxa"):
        try:
            ent = await client.get_entity(uname)
            uid = int(ent.id)
            ids.add(uid)
            store.set_meta("extra_admin_ids", ",".join(str(x) for x in sorted(ids)))
            logger.info("admin @%s id=%s", uname, uid)
            break
        except Exception as e:
            logger.warning("resolve @%s: %s", uname, e)
    return ids


async def _sleep_interruptible(seconds: float, manager_id: str = "") -> bool:
    """Ждать seconds кусками; True если прервали /stop этого менеджера."""
    for step in chunk_sleep_seconds(seconds, chunk=20.0):
        if _stop_flags.get(manager_id):
            return True
        await asyncio.sleep(step)
    return bool(_stop_flags.get(manager_id))


async def _run_outreach(
    client: TelegramClient,
    store: Store,
    engine: Engine,
    settings,
    pending: list[dict],
    notify,
    owner_ids: set[int] | None = None,
    *,
    manager: ManagerConfig | None = None,
    skip_window: bool = False,
) -> None:
    owners = owner_ids or set()
    mid = manager.id if manager else ""
    lim = (
        OutreachLimiter.for_manager(store, manager)
        if manager
        else OutreachLimiter(store)
    )
    ok = fail = skip = 0
    left = list(pending)
    deferred = 0

    can0, why0 = lim.can_send()
    if not can0 and "тишина после входа" in (why0 or ""):
        await notify(
            f"[{mid}] Outreach на паузе — {why0}. "
            f"Входящие ответы работают. В очереди {len(left)}."
        )
        return

    if not skip_window and not lim.in_work_hours():
        wait = lim.seconds_until_window_open()
        await notify(
            f"[{mid}] Вне рабочих часов {lim.work_start}:00–{lim.work_end}:00 {lim.tz_name}. "
            f"Жду ~{int(wait // 3600)}ч {int((wait % 3600) // 60)}м. "
            f"Сегодня лимит {lim.daily_limit}, уже {lim.sent_today()}."
        )
        if await _sleep_interruptible(wait, mid):
            await notify("Рассылка остановлена до старта окна.")
            return

    while left:
        if _stop_flags.get(mid):
            await notify("Рассылка остановлена.")
            break

        if lim.remaining_today() <= 0:
            deferred = len(left)
            await notify(
                f"[{mid}] Дневной лимит {lim.sent_today()}/{lim.daily_limit}. "
                f"Перенос на завтра: {deferred} (pending)."
            )
            break

        if not skip_window and not lim.in_work_hours():
            wait = lim.seconds_until_window_open()
            deferred = len(left)
            await notify(
                f"[{mid}] Окно закрыто. Жду открытие (~{int(wait // 3600)}ч). "
                f"В очереди {deferred}."
            )
            if await _sleep_interruptible(wait, mid):
                await notify("Рассылка остановлена.")
                break
            continue

        can, why = lim.can_send(ignore_window=skip_window)
        if not can:
            if "лимит дня" in why or "дневной" in why:
                deferred = len(left)
                await notify(f"{why}. Перенос: {deferred}.")
                break
            if "вне рабочих" in why:
                continue
            await notify(f"Пауза: {why}")
            if await _sleep_interruptible(
                min(lim.spacing_delay_sec(queue_left=len(left)), 600), mid
            ):
                break
            continue

        c = left.pop(0)
        phone = c["phone"]
        name = c.get("name") or ""
        # менеджер диалога = из очереди (доля); иначе стартовавший
        contact_mid = (c.get("manager_id") or "").strip() or mid
        if phone in ("@", "+", "") or (
            phone.startswith("@")
            and not re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{2,31}", phone)
        ):
            store.update_contact(phone, status="failed", last_error="битый юзернейм")
            fail += 1
            await notify(f"Пропуск битого контакта: {phone!r}")
            continue
        try:
            from bot.contacts_import import TG_MISSING, TG_RETRY, ensure_telegram_user
            from bot.tg_accounts import get_tg_accounts

            tg = get_tg_accounts()
            prev_acc = (c.get("tg_account_id") or "").strip()
            # клиент навсегда на одном аккаунте; paused/revoked — не перекидываем
            acc = tg.for_contact(prev_acc, manager_id=contact_mid)
            if acc is None:
                skip += 1
                await notify(f"Пропуск {phone}: нет Telegram-аккаунта для [{contact_mid}]")
                continue
            if acc.paused or acc.status != "ok":
                skip += 1
                await notify(
                    f"Пропуск {phone}: аккаунт [{acc.id}] {acc.status}"
                    f"{(' — ' + acc.status_note) if acc.status_note else ''}"
                )
                continue
            if prev_acc and prev_acc != acc.id:
                skip += 1
                await notify(f"Пропуск {phone}: уже у аккаунта {prev_acc}")
                continue
            acc_id = acc.id
            send_client = get_hub().get_client(contact_mid, account_id=acc_id) or client

            if phone.startswith("@"):
                entity = await send_client.get_entity(phone)
                chat_id = str(entity.id)
                store.set_contact_telegram(
                    phone,
                    telegram_user_id=chat_id,
                    tg_status="ok",
                    tg_account_id=acc_id,
                )
            else:
                uid, tg_st = await ensure_telegram_user(
                    send_client,
                    store,
                    phone=phone,
                    name=name,
                    account_id=acc_id,
                )
                if tg_st == TG_RETRY or (not uid and tg_st != TG_MISSING):
                    store.update_contact(
                        phone,
                        status="pending",
                        last_error=(tg_st or "не проверилось")[:200],
                    )
                    skip += 1
                    await notify(f"Пропуск {phone}: Telegram не ответил, номер остаётся в очереди")
                    continue
                if not uid or tg_st == TG_MISSING:
                    store.update_contact(
                        phone, status="failed", last_error="нет в Telegram"
                    )
                    skip += 1
                    await notify(f"Пропуск {phone}: нет в Telegram")
                    continue
                entity = await send_client.get_entity(int(uid))
                chat_id = str(entity.id)

            if phone.lower() in ("@bdoxa",) or int(entity.id) == int(
                (await send_client.get_me()).id
            ):
                store.update_contact(
                    phone, status="skipped", last_error="admin — не шлём скрипт"
                )
                skip += 1
                await notify(f"Пропуск {phone}: управляющий акк")
                continue
            # глобальный стоп
            if store.is_stopped_chat(chat_id) or store.is_globally_stopped(
                phone=phone, chat_id=chat_id
            ):
                store.update_contact(
                    phone, status="stopped", chat_id=chat_id, last_error="stop-list"
                )
                skip += 1
                await notify(f"Пропуск {phone}: глобальный стоп-лист")
                continue
            # глобальный 14-дневный лимит / уже писали без ответа
            if store.recently_sent_global(phone=phone, chat_id=chat_id):
                store.update_contact(
                    phone,
                    status="sent",
                    chat_id=chat_id,
                    last_error="глобально: уже писали ≤14 дней",
                )
                skip += 1
                await notify(f"Пропуск {phone}: уже писали (глобально ≤14 дней)")
                continue
            existing = store.contact_by_chat(chat_id)
            if existing:
                em = (existing.get("manager_id") or "").strip()
                # чужой менеджер — не перехватываем; свой / пустой — ок
                if em and contact_mid and em != contact_mid:
                    skip += 1
                    await notify(f"Пропуск {phone}: чат уже у менеджера {em}")
                    continue
                if existing.get("status") == "sent" and not store.guest_replied(chat_id):
                    store.update_contact(
                        phone,
                        status="sent",
                        chat_id=chat_id,
                        last_error="уже писали, нет ответа",
                    )
                    skip += 1
                    await notify(f"Пропуск {phone}: уже писали, ответа нет")
                    continue
            if any(
                (m.get("role") == "guest")
                for m in store.list_messages(chat_id, limit=8)
            ):
                store.update_contact(
                    phone,
                    status="skipped",
                    chat_id=chat_id,
                    last_error="уже есть диалог",
                )
                skip += 1
                await notify(f"Пропуск {phone}: уже переписываемся")
                continue
            sess = store.get_session(chat_id)
            try:
                from bot.phrases import is_placeholder_name
            except Exception:
                is_placeholder_name = lambda _n: False  # type: ignore
            # не класть «Клиент»/телефон в session.name — обращения без имени
            if name and not is_placeholder_name(name):
                store.save_session(chat_id, name=name, manager_id=contact_mid)
                sess["name"] = name
            else:
                store.save_session(chat_id, name="", manager_id=contact_mid)
                sess["name"] = ""
            msgs, buttons, updates = engine.greeting(sess, outreach=True)
            if updates:
                updates["manager_id"] = contact_mid
                store.save_session(chat_id, **updates)
            try:
                from bot import phrases as P

                store.set_meta("greet_rr", str(P.greet_rr_value()))
            except Exception:
                pass
            safe = _guest_safe(msgs)
            for m in safe:
                store.add_message(chat_id, "bot", m)
            await _human_send(send_client, entity, safe, buttons)
            store.update_contact(
                phone, status="sent", chat_id=chat_id, manager_id=contact_mid
            )
            lim.record_send(manager_id=contact_mid)
            ok += 1
            logger.info(
                "acc=%s mgr=%s sent to %s day=%s/%s",
                acc_id,
                contact_mid,
                phone,
                lim.sent_today(),
                lim.daily_limit,
            )
        except FloodWaitError as e:
            wait = int(getattr(e, "seconds", 0) or 0)
            tip = (
                f"FloodWait {wait}s — стоп рассылки на сегодня. "
                f"Telegram просит подождать {wait}с; новые первые сообщения сегодня не шлём."
            )
            lim.pause_for_day(tip)
            try:
                from bot.tg_accounts import get_tg_accounts

                paused_acc = get_tg_accounts().for_contact(
                    (c.get("tg_account_id") or ""), manager_id=contact_mid or mid
                )
                if paused_acc:
                    get_tg_accounts().mark_paused(paused_acc.id, tip, status="paused")
                get_hub().notify(
                    "FloodWait — стоп на сегодня",
                    tip + (f" [{paused_acc.id}]" if paused_acc else ""),
                    manager_id=contact_mid or mid,
                    level="error",
                )
            except Exception:
                pass
            store.update_contact(phone, status="pending", last_error=tip[:200])
            left.insert(0, c)
            await notify(f"⚠ {tip}")
            break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            short = str(e)
            ename = type(e).__name__
            if "PeerFlood" in ename or "peer flood" in short.lower():
                tip = "PeerFlood — аккаунт ограничен, стоп на сегодня"
                lim.pause_for_day(tip)
                try:
                    from bot.tg_accounts import get_tg_accounts

                    paused_acc = get_tg_accounts().for_contact(
                        (c.get("tg_account_id") or ""), manager_id=contact_mid or mid
                    )
                    if paused_acc:
                        get_tg_accounts().mark_paused(
                            paused_acc.id, tip, status="restricted"
                        )
                    get_hub().notify(
                        "PeerFlood — стоп на сегодня",
                        tip + (f" [{paused_acc.id}]" if paused_acc else ""),
                        manager_id=contact_mid or mid,
                        level="error",
                    )
                except Exception:
                    pass
                store.update_contact(phone, status="pending", last_error=tip[:200])
                left.insert(0, c)
                await notify(f"⚠ {tip}")
                break
            store.update_contact(phone, status="failed", last_error=err[:200])
            lim.set_last_error(err)
            fail += 1
            logger.warning("fail %s: %s", phone, err)
            if "Cannot find any entity" in short:
                tip = "нет такого юзернейма / акк скрыт"
            elif "frozen" in short.lower() or "FROZEN" in short:
                tip = "аккаунт ограничен Telegram"
                lim.pause_for_day(tip)
            elif is_session_dead_error(ename) or "AuthKeyUnregistered" in ename:
                lim.set_last_error(err)
                await notify("Сессия отозвана — останавливаю рассылку")
                try:
                    from bot.tg_accounts import get_tg_accounts

                    paused_acc = get_tg_accounts().for_contact(
                        (c.get("tg_account_id") or ""), manager_id=contact_mid or mid
                    )
                    dead_id = paused_acc.id if paused_acc else (c.get("tg_account_id") or "")
                except Exception:
                    dead_id = c.get("tg_account_id") or ""
                _account_session_dead(str(dead_id or ""), contact_mid or mid, f"{ename}: сессия отозвана")
                if dashboard_keepalive():
                    break
                raise SystemExit(EXIT_SESSION_DEAD) from e
            else:
                tip = short[:120]
            await notify(f"Не отправил {phone}: {tip}")
            continue

        gap = lim.spacing_delay_sec(queue_left=max(1, len(left) + 1))
        if settings.outreach_delay and settings.outreach_delay > 0:
            gap = max(gap, float(settings.outreach_delay))
        if left and await _sleep_interruptible(gap, mid):
            await notify("Рассылка остановлена.")
            break

    await notify(
        f"[{mid}] Рассылка: ok={ok} fail={fail} skip={skip}. "
        f"Сегодня {lim.sent_today()}/{lim.daily_limit}. "
        f"В очереди на потом: {len(left) or deferred}."
    )


def main() -> None:
    from bot.instance_guard import install_signal_handlers

    install_signal_handlers()
    asyncio.run(run())


if __name__ == "__main__":
    main()
