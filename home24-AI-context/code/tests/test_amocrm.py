"""amoCRM: план синхронизации без сети и без настоящих ключей."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import amocrm


def _clear_env() -> None:
    for key in (
        "AMOCRM_BASE_URL",
        "AMOCRM_TOKEN",
        "AMOCRM_PIPELINE_ID",
        "AMOCRM_FIELD_DATES",
        "AMOCRM_FIELD_GUESTS",
        "AMOCRM_FIELD_DISTRICT",
        "AMOCRM_FIELD_OPTION",
        "AMOCRM_FIELD_TELEGRAM",
    ):
        os.environ.pop(key, None)


def test_not_configured_skips_network() -> None:
    _clear_env()
    called = {"n": 0}

    def transport(method, path, body):
        called["n"] += 1
        return {}

    out = amocrm.sync_event(
        "dates_guests",
        {"dates": "с 1 по 7 января", "guests": "2"},
        transport=transport,
    )
    assert out["skipped"] is True
    assert out["reason"] == "not_configured"
    assert called["n"] == 0


def test_plan_matches_funnel() -> None:
    assert amocrm.plan_action("dates_guests", has_lead=False) == "create"
    assert amocrm.plan_action("dates_guests", has_lead=True) == "update"
    assert amocrm.plan_action("option_pick", has_lead=True) == "update"
    assert amocrm.plan_action("option_pick", has_lead=False) == "create"
    assert amocrm.plan_action("handoff", has_lead=True) == "note"
    assert amocrm.plan_action("handoff", has_lead=False) == "create"
    assert amocrm.plan_action("spam", has_lead=False) == "skip"


def test_payload_uses_only_configured_fields() -> None:
    _clear_env()
    os.environ["AMOCRM_FIELD_DATES"] = "101"
    os.environ["AMOCRM_FIELD_GUESTS"] = "102"
    guest = {
        "name": "Анна",
        "phone": "[REDACTED]",
        "telegram_id": "2032620613",
        "dates": "с 1 по 7 января",
        "guests": "2",
        "district": "спокойнее",
        "option": "Сандал",
    }
    lead = amocrm.lead_payload(guest)
    ids = [f["field_id"] for f in lead["custom_fields_values"]]
    assert ids == [101, 102]
    assert "Сандал" not in str(lead)
    contact = amocrm.contact_payload(guest)
    assert contact["custom_fields_values"][0]["field_code"] == "PHONE"
    assert "2032620613" not in str(contact)
    os.environ["AMOCRM_FIELD_TELEGRAM"] = "303"
    os.environ["AMOCRM_FIELD_OPTION"] = "104"
    contact2 = amocrm.contact_payload(guest)
    assert any(f.get("field_id") == 303 for f in contact2["custom_fields_values"])
    lead2 = amocrm.lead_payload(guest, lead_id=9)
    assert lead2["id"] == 9
    assert any(f["field_id"] == 104 for f in lead2["custom_fields_values"])
    _clear_env()


def test_sync_calls_transport_when_configured() -> None:
    _clear_env()
    os.environ["AMOCRM_BASE_URL"] = "https://example.amocrm.ru"
    os.environ["AMOCRM_TOKEN"] = "test-token"
    seen = []

    def transport(method, path, body):
        seen.append((method, path, body))
        return {"id": 1}

    created = amocrm.sync_event(
        "dates_guests",
        {"name": "Гость", "dates": "май", "guests": "2"},
        transport=transport,
    )
    assert created["action"] == "create"
    assert seen[0][0] == "POST"
    assert seen[0][1] == "/api/v4/leads"
    noted = amocrm.sync_event(
        "handoff",
        {"dates": "май", "guests": "2", "option": "Сандал"},
        has_lead=True,
        lead_id=15,
        transport=transport,
    )
    assert noted["action"] == "note"
    assert seen[1][1] == "/api/v4/leads/15/notes"
    assert "Сандал" in seen[1][2]["params"]["text"]
    assert "test-token" not in str(seen)
    _clear_env()


if __name__ == "__main__":
    test_not_configured_skips_network()
    test_plan_matches_funnel()
    test_payload_uses_only_configured_fields()
    test_sync_calls_transport_when_configured()
    print("ok")
