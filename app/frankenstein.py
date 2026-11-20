"""Frankenstein pack: SoClose-style waves/templates × our confirmed-delivery hygiene.

Throughput scales by **number of warmed accounts with unique IPs**, never by
shrinking delays below the speed profile. Success remains presence-confirmed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.domain.invitations import DEFAULT_INVITE_MODE, SPEED_PROFILES, speed_profile_bounds

# Мягкий потолок confirmed/сутки на один целевой чат (все кампании суммарно).
CHAT_DAILY_CONFIRMED_SOFT_CAP = 40
DEFAULT_TEMPLATE_ID = "safe"

# Шаблоны: идея волн/лимитов из SoCloseSociety, паузы — наши минутные профили.
# Нет «Aggressive 200/день»: это маркетинг и путь к PEER_FLOOD / silent loss.
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "ultra_safe": {
        "id": "ultra_safe",
        "name": "Ultra Safe — 1 аккаунт",
        "description": "Новый номер: 2 confirmed/день, длинные паузы, волны через 8ч.",
        "accounts_needed": 1,
        "per_wave": 2,
        "hours_between_waves": 8,
        "daily_limit_per_account": 2,
        "speed_profile": "cautious",
        "invite_mode": "hybrid",
        "require_warmup": True,
        "risk_level": "minimal",
        "result_per_day_hint": "~2 confirmed/день на аккаунт",
    },
    "safe": {
        "id": "safe",
        "name": "Safe — 1 аккаунт",
        "description": "Базовый легитимный режим после прогрева.",
        "accounts_needed": 1,
        "per_wave": 3,
        "hours_between_waves": 6,
        "daily_limit_per_account": 3,
        "speed_profile": "cautious",
        "invite_mode": "hybrid",
        "require_warmup": True,
        "risk_level": "low",
        "result_per_day_hint": "~3 confirmed/день на аккаунт",
    },
    "conservative": {
        "id": "conservative",
        "name": "Conservative — 3 аккаунта",
        "description": "Масштаб числом IP: ~9 confirmed/день суммарно.",
        "accounts_needed": 3,
        "per_wave": 4,
        "hours_between_waves": 5,
        "daily_limit_per_account": 3,
        "speed_profile": "normal",
        "invite_mode": "hybrid",
        "require_warmup": True,
        "risk_level": "moderate",
        "result_per_day_hint": "~9 confirmed/день (3×3)",
    },
    "standard": {
        "id": "standard",
        "name": "Standard — 5 аккаунтов",
        "description": "Рабочий пул: ~20 confirmed/день при 1 IP на аккаунт.",
        "accounts_needed": 5,
        "per_wave": 5,
        "hours_between_waves": 4,
        "daily_limit_per_account": 4,
        "speed_profile": "normal",
        "invite_mode": "hybrid",
        "require_warmup": True,
        "risk_level": "moderate",
        "result_per_day_hint": "~20 confirmed/день (5×4)",
    },
    "growth": {
        "id": "growth",
        "name": "Growth — 10 аккаунтов",
        "description": "Только после warmup на всех; профиль warmed; без агрессии SoClose.",
        "accounts_needed": 10,
        "per_wave": 6,
        "hours_between_waves": 4,
        "daily_limit_per_account": 5,
        "speed_profile": "warmed",
        "invite_mode": "hybrid",
        "require_warmup": True,
        "risk_level": "moderate-high",
        "result_per_day_hint": "~50 confirmed/день (10×5), chat soft-cap ~40",
    },
}


def list_templates() -> List[Dict[str, Any]]:
    rows = []
    for item in TEMPLATES.values():
        gap_min, gap_max = speed_profile_bounds(str(item["speed_profile"]))
        row = dict(item)
        row["invite_gap_min"] = gap_min
        row["invite_gap_max"] = gap_max
        row["accounts_x_daily"] = int(item["accounts_needed"]) * int(
            item["daily_limit_per_account"]
        )
        rows.append(row)
    return rows


def get_template(template_id: Optional[str]) -> Dict[str, Any]:
    key = str(template_id or DEFAULT_TEMPLATE_ID).strip().lower()
    if key not in TEMPLATES:
        key = DEFAULT_TEMPLATE_ID
    return dict(TEMPLATES[key])


def apply_template_to_settings(
    settings: Dict[str, Any],
    template_id: Optional[str],
) -> Dict[str, Any]:
    """Накладывает шаблон на settings кампании (не трогает account_ids/filters)."""
    template = get_template(template_id)
    gap_min, gap_max = speed_profile_bounds(str(template["speed_profile"]))
    out = dict(settings or {})
    out["template_id"] = template["id"]
    out["per_wave"] = int(template["per_wave"])
    out["hours_between_waves"] = int(template["hours_between_waves"])
    out["daily_limit_per_account"] = int(template["daily_limit_per_account"])
    out["speed_profile"] = str(template["speed_profile"])
    out["invite_mode"] = str(template.get("invite_mode") or DEFAULT_INVITE_MODE)
    out["invite_gap_min"] = gap_min
    out["invite_gap_max"] = gap_max
    out["require_warmup"] = bool(template.get("require_warmup", True))
    out["chat_daily_confirmed_soft_cap"] = int(
        out.get("chat_daily_confirmed_soft_cap") or CHAT_DAILY_CONFIRMED_SOFT_CAP
    )
    return out


def template_warnings(account_count: int, template_id: Optional[str]) -> List[str]:
    template = get_template(template_id)
    needed = int(template["accounts_needed"])
    warnings: List[str] = []
    if account_count < needed:
        warnings.append(
            "Шаблон «%s» рассчитан на %d аккаунтов, выбрано %d — суточный confirmed будет ниже"
            % (template["name"], needed, account_count)
        )
    profile = str(template["speed_profile"])
    if profile not in SPEED_PROFILES:
        warnings.append("Неизвестный speed_profile в шаблоне")
    if profile == "warmed":
        warnings.append("Профиль warmed: только для аккаунтов с отмеченным warmup")
    return warnings
