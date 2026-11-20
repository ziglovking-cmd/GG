"""amoCRM: когда создавать и обновлять сделку из воронки бота.

Сеть не вызывается, пока в окружении нет AMOCRM_BASE_URL и AMOCRM_TOKEN.
Ключи сюда не вшиваются. Поле «Telegram уведомление» не используется:
гость ищется по телефону или Telegram id контакта.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

# dates_guests — даты и гости уже есть: создать сделку или обновить поля.
# option_pick — гость выбрал вариант: дописать квартиру.
# handoff — менеджер забирает чат: примечание, сделку не плодим заново если она есть.
EVENTS = ("dates_guests", "option_pick", "handoff")


def base_url() -> str:
    return (os.getenv("AMOCRM_BASE_URL") or "").strip().rstrip("/")


def token() -> str:
    return (os.getenv("AMOCRM_TOKEN") or "").strip()


def configured() -> bool:
    return bool(base_url() and token())


def plan_action(event: str, *, has_lead: bool) -> str:
    """create | update | note | skip."""
    if event not in EVENTS:
        return "skip"
    if event == "handoff":
        return "note" if has_lead else "create"
    return "update" if has_lead else "create"


def _field_id(env_name: str) -> int | None:
    raw = (os.getenv(env_name) or "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


def lead_custom_fields(guest: dict[str, Any]) -> list[dict[str, Any]]:
    """Только поля, для которых задан id в окружении. Пустые значения не шлём."""
    mapping = (
        ("AMOCRM_FIELD_DATES", "dates"),
        ("AMOCRM_FIELD_GUESTS", "guests"),
        ("AMOCRM_FIELD_DISTRICT", "district"),
        ("AMOCRM_FIELD_OPTION", "option"),
    )
    fields: list[dict[str, Any]] = []
    for env_name, key in mapping:
        fid = _field_id(env_name)
        value = str(guest.get(key) or "").strip()
        if fid is None or not value:
            continue
        fields.append({"field_id": fid, "values": [{"value": value[:500]}]})
    return fields


def contact_payload(guest: dict[str, Any]) -> dict[str, Any]:
    name = str(guest.get("name") or "").strip() or "Гость Telegram"
    payload: dict[str, Any] = {"name": name[:255]}
    phone = str(guest.get("phone") or "").strip()
    if phone:
        payload["custom_fields_values"] = [
            {"field_code": "PHONE", "values": [{"value": phone, "enum_code": "WORK"}]}
        ]
    tg = str(guest.get("telegram_id") or "").strip()
    fid = _field_id("AMOCRM_FIELD_TELEGRAM")
    if tg and fid is not None:
        payload.setdefault("custom_fields_values", []).append(
            {"field_id": fid, "values": [{"value": tg}]}
        )
    return payload


def lead_payload(guest: dict[str, Any], *, lead_id: int | None = None) -> dict[str, Any]:
    name = str(guest.get("name") or "").strip() or "Гость Home24"
    body: dict[str, Any] = {"name": f"Home24 · {name}"[:255]}
    if lead_id:
        body["id"] = int(lead_id)
    pipeline = (os.getenv("AMOCRM_PIPELINE_ID") or "").strip()
    if pipeline.isdigit():
        body["pipeline_id"] = int(pipeline)
    fields = lead_custom_fields(guest)
    if fields:
        body["custom_fields_values"] = fields
    return body


def note_text(guest: dict[str, Any]) -> str:
    bits = ["Бот передал диалог менеджеру."]
    for key, label in (
        ("dates", "Даты"),
        ("guests", "Гости"),
        ("district", "Район"),
        ("option", "Вариант"),
    ):
        value = str(guest.get(key) or "").strip()
        if value:
            bits.append(f"{label}: {value}")
    return "\n".join(bits)


Transport = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


def _http_transport(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
    url = base_url() + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return {"ok": False, "status": exc.code, "detail": detail}


def sync_event(
    event: str,
    guest: dict[str, Any],
    *,
    has_lead: bool = False,
    lead_id: int | None = None,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Собрать действие. Без токена сеть не трогаем."""
    if not configured():
        return {"ok": False, "skipped": True, "reason": "not_configured", "event": event}
    action = plan_action(event, has_lead=has_lead or bool(lead_id))
    if action == "skip":
        return {"ok": False, "skipped": True, "reason": "unknown_event", "event": event}
    call = transport or _http_transport
    if action == "note":
        body = {"note_type": "common", "params": {"text": note_text(guest)}}
        path = f"/api/v4/leads/{int(lead_id)}/notes" if lead_id else "/api/v4/leads/notes"
        result = call("POST", path, body)
        return {"ok": True, "action": action, "event": event, "result": result}
    payload = lead_payload(guest, lead_id=lead_id if action == "update" else None)
    if action == "create":
        result = call("POST", "/api/v4/leads", payload)
    else:
        result = call("PATCH", "/api/v4/leads", payload)
    return {"ok": True, "action": action, "event": event, "result": result}


def maybe_sync(event: str, guest: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Безопасная обёртка: ошибка amo не должна ронять ответ гостю."""
    try:
        return sync_event(event, guest, **kwargs)
    except Exception:
        return {"ok": False, "skipped": True, "reason": "error", "event": event}
