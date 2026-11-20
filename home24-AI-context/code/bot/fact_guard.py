# -*- coding: utf-8 -*-
"""Верификатор исходящих реплик: ловит галлюцинации до отправки гостю.

Детерминированные проверки против карты/политики (не второй LLM).
FACT_GUARD=1 по умолчанию. Выключить: FACT_GUARD=0.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger("home24.fact_guard")

DEPOSIT_RUB = 2000
SAFE_PETS = (
    "С питомцами можно не во всех квартирах. "
    "В карточке будет пометка, где можно и какая доплата."
)
SAFE_DEPOSIT = (
    "Залог 2 000 ₽, во всех квартирах. "
    "Возвращаем после выезда, как только пройдёт клининг."
)
SAFE_PARKING = (
    "Парковка зависит от дома: где-то двор, где-то городская рядом — "
    "уточню по выбранной квартире."
)
SAFE_PRICE = "Цена зависит от дат и квартиры, без них точную сумму не скажу."
SAFE_METRO = "Метро уточню по конкретной квартире из карты."
SAFE_FREE = "Свободные смотрю по календарю под ваши даты и район."


def enabled() -> bool:
    return os.getenv("FACT_GUARD", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


_MONEY_RE = re.compile(
    r"(?i)(\d[\d\s\u00a0]{0,8})\s*(₽|руб|rub)"
)
_DEPOSIT_CTX = re.compile(r"(?i)залог|депозит")
_PET_CLAIM = re.compile(
    r"(?i)(можно\s+с\s+животн|с\s+питомц\w*\s+можно|животн\w*\s+можно|"
    r"можно\s+с\s+собак|можно\s+с\s+кошк|питомц\w*\s+разреш)"
)
_PET_DENY_ALL = re.compile(
    r"(?i)(с\s+животн\w*\s+нельзя|питомц\w*\s+нельзя|животн\w*\s+запрещ)"
)
_FLAT_QUOTE = re.compile(r"«([^»]{2,40})»")
_FREE_PARKING = re.compile(
    r"(?i)(бесплатн\w*\s+парков|парковк\w*\s+бесплатн|парковка\s+есть\s+бесплатн|"
    r"гарантир\w*\s+бесплатн\w*\s+парков)"
)
_INVENTED_PRICE = re.compile(
    r"(?i)(стоит\s+(?:примерно\s+)?\d|около\s+\d[\d\s]{0,6}\s*(?:₽|руб)|"
    r"цена\s+(?:от\s+)?\d[\d\s]{0,6}\s*(?:₽|руб)|"
    r"\d[\d\s]{0,6}\s*(?:₽|руб)\s*(?:за\s+)?(?:ночь|сутки|сутки))"
)
_GUARANTEED_FREE = re.compile(
    r"(?i)(точно\s+свободн|гарантир\w*\s+свободн|всегда\s+свободн|"
    r"все\s+квартиры\s+свободн|свободно\s+на\s+любые\s+даты)"
)
_METRO_CLAIM = re.compile(
    r"(?i)(?:м\.|метро)\s*[«\"]?([А-ЯЁA-Z][А-Яа-яёA-Za-z\-]+)"
)
_SKIP_FLAT = re.compile(
    r"(?i)^(покажите|покажи|вариант|варианты|да|нет|хорошо|ок|окей|спасибо|"
    r"центр|даты|гости|район|можно|нужен|нужна)$"
)


def _parse_money(raw: str) -> int | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _known_titles() -> set[str]:
    try:
        from bot.apartments_map import known_apartment_titles

        return {t.strip().lower() for t in known_apartment_titles() if t}
    except Exception:
        return set()


def _known_metros() -> set[str]:
    """Станции из адресов карты (грубо: слова после «м.» в адресах)."""
    out: set[str] = set()
    try:
        from bot.apartments_map import load_addresses

        for _title, addr in (load_addresses() or {}).items():
            for m in re.finditer(r"(?i)м\.\s*([А-ЯЁA-Za-zа-яё\-]+)", str(addr or "")):
                out.add(m.group(1).strip().lower().replace("ё", "е"))
    except Exception:
        pass
    # частые из эталона / карты Home24
    out.update(
        {
            "бауманская",
            "прокшино",
            "коммунарка",
            "очаково",
            "юго-западная",
            "слобода",
        }
    )
    return out


def _allows_pets(name: str) -> bool | None:
    try:
        from bot.apartments_map import allows_pets

        return bool(allows_pets(name))
    except Exception:
        return None


def _is_card_block(text: str) -> bool:
    return bool(re.search(r"(?m)^1\)", text or ""))


def audit_message(
    text: str,
    *,
    offers: list[str] | None = None,
) -> list[str]:
    """Список найденных проблем (пустой = ок)."""
    issues: list[str] = []
    raw = text or ""
    if not raw.strip():
        return issues

    # залог с чужой суммой
    if _DEPOSIT_CTX.search(raw):
        for m in _MONEY_RE.finditer(raw):
            window = raw[max(0, m.start() - 40) : m.end() + 40]
            if not _DEPOSIT_CTX.search(window):
                continue
            val = _parse_money(m.group(1))
            if val is None:
                continue
            if val != DEPOSIT_RUB:
                issues.append(f"deposit_amount:{val}")

    # глобальный запрет животных — у нас не так
    if _PET_DENY_ALL.search(raw) and not re.search(
        r"(?i)не\s+во\s+всех|не\s+везде|зависит", raw
    ):
        issues.append("pets_global_deny")

    # обещание бесплатной парковки
    if _FREE_PARKING.search(raw):
        issues.append("free_parking")

    # выдуманная цена вне карточек календаря
    if _INVENTED_PRICE.search(raw) and not _is_card_block(raw):
        # «1 балл = 1 ₽» / залог 2000 — не трогаем
        if not re.search(r"(?i)балл|залог|депозит|доплат", raw):
            issues.append("invented_price")

    # «точно свободно» без календаря
    if _GUARANTEED_FREE.search(raw) and not _is_card_block(raw):
        issues.append("guaranteed_free")

    # метро не из карты (только вне карточек — в карточках метро из TL)
    if not _is_card_block(raw):
        known_m = _known_metros()
        for m in _METRO_CLAIM.finditer(raw):
            st = m.group(1).strip().lower().replace("ё", "е")
            if st and known_m and st not in known_m:
                # «м. Бауманская» ок; выдуманное «м. Арбатская» — нет
                issues.append(f"unknown_metro:{st}")

    # неизвестное имя квартиры в «ёлочках»
    offer_set = {o.strip().lower() for o in (offers or []) if o}
    known = _known_titles()
    for name in _FLAT_QUOTE.findall(raw):
        low = name.strip().lower()
        if not low or _SKIP_FLAT.match(low):
            continue
        if re.search(rf"(?i)по\s*«{re.escape(name)}»", raw):
            continue
        if offer_set and low not in offer_set and (not known or low not in known):
            issues.append(f"unknown_flat:{name}")
        elif known and low not in known:
            issues.append(f"unknown_flat:{name}")

    if _PET_CLAIM.search(raw):
        for name in _FLAT_QUOTE.findall(raw):
            ok = _allows_pets(name)
            if ok is False and re.search(
                rf"(?i)«{re.escape(name)}»[^\n]{{0,80}}можно\s+с\s+животн",
                raw,
            ):
                issues.append(f"pets_false_ok:{name}")

    return issues


def repair_message(text: str, issues: list[str]) -> str:
    """Заменить опасные куски на безопасные факты."""
    out = text or ""
    if not issues:
        return out

    if any(i.startswith("deposit_amount:") for i in issues):
        out = re.sub(
            r"(?i)[^.?!]*\b(залог|депозит)\b[^.?!]*[.?!]?",
            " ",
            out,
        )
        out = (out.strip() + " " + SAFE_DEPOSIT).strip()

    if "pets_global_deny" in issues or any(
        i.startswith("pets_false_ok:") for i in issues
    ):
        out = re.sub(
            r"(?i)[^.?!]*\b(животн|питомц|собак|кошк)\b[^.?!]*[.?!]?",
            " ",
            out,
        )
        out = (out.strip() + " " + SAFE_PETS).strip()

    if "free_parking" in issues:
        out = re.sub(
            r"(?i)[^.?!]*\bпарковк\w*\b[^.?!]*[.?!]?",
            " ",
            out,
        )
        out = (out.strip() + " " + SAFE_PARKING).strip()

    if "invented_price" in issues:
        out = re.sub(
            r"(?i)[^.?!]*(стоит|цена|около)\s+[^.?!]*\d[^.?!]*[.?!]?",
            " ",
            out,
        )
        out = re.sub(
            r"(?i)\d[\d\s\u00a0]{0,8}\s*(₽|руб)[^.?!]*[.?!]?",
            " ",
            out,
        )
        if len(out.strip()) < 12:
            out = SAFE_PRICE
        elif "цена зависит" not in out.lower():
            out = (out.strip() + " " + SAFE_PRICE).strip()

    if "guaranteed_free" in issues:
        out = re.sub(
            r"(?i)[^.?!]*(точно\s+свободн|гарантир\w*\s+свободн|всегда\s+свободн|"
            r"все\s+квартиры\s+свободн|свободно\s+на\s+любые)[^.?!]*[.?!]?",
            " ",
            out,
        )
        out = (out.strip() + " " + SAFE_FREE).strip()

    if any(i.startswith("unknown_metro:") for i in issues):
        out = re.sub(
            r"(?i)[^.?!]*(?:м\.|метро)\s*[«\"]?[А-ЯЁA-Za-zа-яё\-]+[^.?!]*[.?!]?",
            " ",
            out,
        )
        out = (out.strip() + " " + SAFE_METRO).strip()

    if any(i.startswith("unknown_flat:") for i in issues):
        known = _known_titles()

        def _keep(m: re.Match[str]) -> str:
            name = m.group(1)
            if known and name.strip().lower() not in known:
                return "«вариант»"
            return m.group(0)

        out = _FLAT_QUOTE.sub(_keep, out)

    out = re.sub(r"\s{2,}", " ", out).strip()
    return out or SAFE_DEPOSIT


def guard_outbound(
    msgs: list[str],
    *,
    sess: dict[str, Any] | None = None,
) -> list[str]:
    """Проверить и поправить список исходящих пузырей."""
    if not enabled():
        return list(msgs or [])
    offers: list[str] = []
    if sess:
        ctx = sess.get("context") or {}
        offers = [
            str(x)
            for x in (ctx.get("offers") or ctx.get("tl_offers") or [])
            if x
        ]
    out: list[str] = []
    for raw in msgs or []:
        text = (raw or "").strip()
        if not text:
            continue
        issues = audit_message(text, offers=offers)
        if issues:
            fixed = repair_message(text, issues)
            logger.warning(
                "fact_guard hit issues=%s before=%r after=%r",
                issues,
                text[:160],
                fixed[:160],
            )
            if fixed:
                out.append(fixed)
        else:
            out.append(text)
    return out
