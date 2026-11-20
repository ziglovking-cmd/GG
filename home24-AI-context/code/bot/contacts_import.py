"""Перед первым сообщением: ImportContacts по одному + кэш telegram user id.

Не bulk: вызывается сразу перед отправкой конкретному клиенту (внутри дневного
капа и рабочих часов — это ответственность outreach-цикла).
"""

from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger("home24.contacts_import")

TG_OK = "ok"
TG_MISSING = "нет в Telegram"
TG_RETRY = "повтор проверки"
TG_PENDING = ""
TG_ALREADY_CONTACT = "уже в контактах"
TG_HAS_DIALOG = "есть диалог"
# совместимость со старым значением
TG_SKIP_EXISTING = TG_ALREADY_CONTACT


async def _resolve_phone(client: Any, phone_for_tg: str) -> str:
    """Второй способ найти аккаунт, если ImportContacts вернул пустой users."""
    from telethon.tl.functions.contacts import ResolvePhoneRequest

    try:
        resolved = await client(ResolvePhoneRequest(phone=phone_for_tg))
    except Exception as e:
        name_e = type(e).__name__
        if (
            "FloodWait" in name_e
            or "PeerFlood" in name_e
            or "PhoneNotOccupied" in name_e
            or "PhoneNumberInvalid" in name_e
        ):
            raise
        logger.info("resolvePhone skipped phone=%s err=%s", phone_for_tg, name_e)
        return ""
    users = list(getattr(resolved, "users", None) or [])
    for user in users:
        uid = getattr(user, "id", None)
        if uid:
            return str(uid)
    return ""


def _digits(phone: str) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())


def _split_name(name: str) -> tuple[str, str]:
    raw = (name or "").strip() or "Клиент"
    # убрать DEMO-префикс из отображаемого, если вдруг
    if raw.upper().startswith("DEMO"):
        raw = raw.split("·", 1)[-1].strip() or "Клиент"
    first, _, last = raw.partition(" ")
    return (first or "Клиент")[:64], (last or "")[:64]


async def _find_in_contacts(client: Any, phone_n: str) -> str | None:
    from telethon.tl.functions.contacts import GetContactsRequest

    contacts = await client(GetContactsRequest(hash=0))
    users = getattr(contacts, "users", None) or []
    digits = _digits(phone_n)
    if not digits:
        return None
    for u in users:
        uid = getattr(u, "id", None)
        if uid is None:
            continue
        up = _digits(getattr(u, "phone", None) or "")
        if up and (up.endswith(digits[-10:]) or digits.endswith(up[-10:])):
            return str(uid)
    return None


async def _find_existing_dialog(client: Any, phone_n: str) -> str | None:
    """Уже есть диалог / сущность в сессии — без ImportContacts."""
    try:
        entity = await client.get_entity(phone_n)
        uid = getattr(entity, "id", None)
        if uid is not None:
            return str(uid)
    except Exception:
        pass
    try:
        # иногда Telethon принимает только цифры
        entity = await client.get_entity(int(_digits(phone_n)))
        uid = getattr(entity, "id", None)
        if uid is not None:
            return str(uid)
    except Exception:
        pass
    return None


async def ensure_telegram_user(
    client: Any,
    store: Any,
    *,
    phone: str,
    name: str = "",
    account_id: str = "",
) -> tuple[str | None, str]:
    """Вернуть (telegram_user_id | None, tg_status).

    None + «нет в Telegram» — пропустить клиента (не слать).
    При успехе user id кэшируется — повторный ImportContacts не вызывается.
    FloodWait / PeerFlood пробрасываются наверх.
    """
    phone_n = (phone or "").strip()
    if not phone_n:
        return None, TG_MISSING

    # имя из БД, если не передали
    row = store.contact_by_phone(phone_n)
    if row and not (name or "").strip():
        name = str(row.get("name") or "")

    if row:
        cached = (row.get("telegram_user_id") or "").strip()
        status = (row.get("tg_status") or "").strip()
        if status == TG_MISSING:
            logger.info("cached miss phone=%s", phone_n)
            return None, TG_MISSING
        if cached:
            return cached, status or TG_OK
        # уже есть диалог у нас в БД — не импортируем
        chat_id = (row.get("chat_id") or "").strip()
        if chat_id and not chat_id.startswith("demo-"):
            store.set_contact_telegram(
                phone_n,
                telegram_user_id=chat_id,
                tg_status=TG_HAS_DIALOG,
                tg_account_id=account_id,
            )
            return chat_id, TG_HAS_DIALOG

    # уже в контактах Telegram-аккаунта
    try:
        uid = await _find_in_contacts(client, phone_n)
        if uid:
            store.set_contact_telegram(
                phone_n,
                telegram_user_id=uid,
                tg_status=TG_ALREADY_CONTACT,
                tg_account_id=account_id,
            )
            return uid, TG_ALREADY_CONTACT
    except Exception as e:
        if "FloodWait" in type(e).__name__ or "PeerFlood" in type(e).__name__:
            raise
        logger.exception("GetContacts failed phone=%s", phone_n)

    # уже есть диалог / сущность в сессии Telethon
    try:
        uid = await _find_existing_dialog(client, phone_n)
        if uid:
            store.set_contact_telegram(
                phone_n,
                telegram_user_id=uid,
                tg_status=TG_HAS_DIALOG,
                tg_account_id=account_id,
            )
            return uid, TG_HAS_DIALOG
    except Exception as e:
        if "FloodWait" in type(e).__name__ or "PeerFlood" in type(e).__name__:
            raise

    # ImportContacts — ровно один контакт, прямо перед отправкой
    try:
        from telethon.tl.functions.contacts import ImportContactsRequest
        from telethon.tl.types import InputPhoneContact

        first, last = _split_name(name)
        phone_for_tg = phone_n if phone_n.startswith("+") else f"+{phone_n.lstrip('+')}"
        result = await client(
            ImportContactsRequest(
                contacts=[
                    InputPhoneContact(
                        client_id=random.randint(1, 2**31 - 1),
                        phone=phone_for_tg,
                        first_name=first,
                        last_name=last,
                    )
                ]
            )
        )
        users = list(getattr(result, "users", None) or [])
        imported_rows = list(getattr(result, "imported", None) or [])
        retry_ids = list(getattr(result, "retry_contacts", None) or [])
        logger.info(
            "import phone=%s users=%s imported=%s retry=%s",
            phone_n,
            len(users),
            len(imported_rows),
            len(retry_ids),
        )
        uid = ""
        if users and getattr(users[0], "id", None):
            uid = str(users[0].id)
        elif imported_rows and getattr(imported_rows[0], "user_id", None):
            uid = str(imported_rows[0].user_id)
        if uid:
            store.set_contact_telegram(
                phone_n,
                telegram_user_id=uid,
                tg_status=TG_OK,
                tg_account_id=account_id,
            )
            logger.info(
                "imported contact phone=%s uid=%s name=%s %s",
                phone_n,
                uid,
                first,
                last,
            )
            return uid, TG_OK
        if retry_ids:
            logger.info("import asked to retry phone=%s", phone_n)
            return None, TG_RETRY
        resolved = await _resolve_phone(client, phone_for_tg)
        if resolved:
            store.set_contact_telegram(
                phone_n,
                telegram_user_id=resolved,
                tg_status=TG_OK,
                tg_account_id=account_id,
            )
            logger.info("resolvePhone phone=%s uid=%s", phone_n, resolved)
            return resolved, TG_OK
        store.set_contact_telegram(
            phone_n,
            telegram_user_id="",
            tg_status=TG_MISSING,
            tg_account_id=account_id,
        )
        logger.info("phone not on telegram: %s", phone_n)
        return None, TG_MISSING
    except Exception as e:
        name_e = type(e).__name__
        if "FloodWait" in name_e or "PeerFlood" in name_e:
            raise
        if "PhoneNotOccupied" in name_e or "PhoneNumberInvalid" in name_e:
            store.set_contact_telegram(
                phone_n,
                telegram_user_id="",
                tg_status=TG_MISSING,
                tg_account_id=account_id,
            )
            logger.info("phone not on telegram: %s (%s)", phone_n, name_e)
            return None, TG_MISSING
        logger.exception("ImportContacts failed phone=%s", phone_n)
        return None, TG_RETRY
