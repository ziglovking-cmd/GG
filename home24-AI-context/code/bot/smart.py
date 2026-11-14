# -*- coding: utf-8 -*-
"""Home24 v9 smart brain — LLM-first понимание + safety-слой на скрипте/каталоге."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from bot.config import Settings
from bot.engine import (
    BUTTONS,
    Engine,
    format_booking_summary,
    format_guests_phrase,
    is_stop_request,
    is_guests_negation,
    normalize_dates_phrase,
    parse_budget,
    parse_dates,
    parse_district,
    parse_guests,
    parse_nights,
    parse_returning,
)
from bot.llm import chat_completion, load_providers
from bot.phrases import (
    ADDON_SERVICES_LIST,
    ADDON_SERVICES_REPLY,
    HANDOFF_LINE,
    MANAGER_CONNECT_LINE,
    already_greeted,
    is_consent,
    is_placeholder_name,
    offer_reply,
)

logger = logging.getLogger("home24.smart")

SMART_BOT = os.getenv("SMART_BOT", "1").strip().lower() not in ("0", "false", "no", "off")


def _normalize_district_label(dist: str | None) -> str | None:
    """LLM иногда пишет center/calm — в слотах только русские ярлыки."""
    if not dist:
        return None
    d = str(dist).strip()
    low = d.lower().replace("ё", "е")
    if re.search(r"(?i)подмосков|suburb", low):
        return "Подмосковье"
    if re.search(r"(?i)близко\s*к\s*цен|ближе\s*к\s*цен|near\s*center", low):
        return "Близко к центру"
    if re.search(r"(?i)зелен|лесопарк|green", low):
        return "Тихий зелёный район"
    if re.search(r"(?i)спальн|sleep", low):
        return "Спальный район"
    if low in ("center", "central", "centre", "downtown") or re.search(
        r"(?i)^в?\s*центре?$", low
    ):
        return "центр"
    if low in ("calm", "quiet", "peaceful") or re.search(
        r"(?i)спокой|тихий|тих\w*\s*район", low
    ):
        return "спокойный район" if "район" not in low else d
    if low in ("suburban",):
        return "Подмосковье"
    return d[:40]


# тест-хук: async (system, messages, **kw) -> (raw_json, via) | None
UnderstandHook = Callable[..., Awaitable[tuple[str, str] | None]]
_UNDERSTAND_HOOK: UnderstandHook | None = None


def set_understand_hook(hook: UnderstandHook | None) -> None:
    global _UNDERSTAND_HOOK
    _UNDERSTAND_HOOK = hook


def smart_enabled() -> bool:
    # хук для моков в тестах — всегда включает smart path
    if _UNDERSTAND_HOOK is not None:
        return True
    if os.getenv("HOME24_FORCE_SCRIPT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return False
    return SMART_BOT


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or str(default)).strip())
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float((os.getenv(name) or str(default)).strip()))
    except Exception:
        return default


def _prompt() -> str:
    path = Path(__file__).with_name("smart_prompt.txt")
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return "Ты менеджер Home24. JSON only."


def faq_facts_for_llm(limit: int = 24) -> str:
    try:
        from bot.faq import FAQ_RULES
    except Exception:
        return ""
    lines: list[str] = []
    for keys, msgs in FAQ_RULES:
        if not msgs:
            continue
        topic = ", ".join(keys[:3])
        ans = " ".join(msgs)[:160]
        lines.append(f"- {topic}: {ans}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def catalog_brief_for_llm(
    *,
    limit: int = 10,
    district: str | None = None,
    guests: str | None = None,
) -> str:
    """Короткий релевантный срез каталога (не весь список)."""
    try:
        from bot.catalog import (
            pick_apartments_with_note,
            format_price_line,
            district_preference,
        )
    except Exception:
        return ""
    objs, note = pick_apartments_with_note(
        district=district or "",
        guests=guests or "2",
        limit=limit,
        hard_district=True,
    )
    pref = district_preference(district)
    lines = [f"Зона запроса: {pref}." + (f" {note}" if note else "")]
    for o in objs:
        zone = o.get("zone") or "?"
        cap = f"до {o['capacity']}" if o.get("capacity") else "?"
        lines.append(
            f"«{o['name']}» · zone={zone} · {cap} · {format_price_line(o)}"
            f" · {(o.get('metro') or o.get('area') or '—')[:48]}"
        )
    return "\n".join(lines)


def _session_slots(sess: dict[str, Any]) -> dict[str, Any]:
    ctx = sess.get("context") if isinstance(sess.get("context"), dict) else {}
    return {
        "dates": sess.get("dates") or "",
        "guests": sess.get("guests") or "",
        "district": sess.get("district") or "",
        "returning": sess.get("returning") or "",
        "favorite": sess.get("favorite") or "",
        "budget": ctx.get("budget") or "",
        "pets": ctx.get("pets") or "",
        "kids": ctx.get("kids") or "",
        "parking": ctx.get("parking") or "",
        "prefs": ctx.get("prefs") or "",
        "offers": list(ctx.get("offers") or []),
        "step": sess.get("step") or "await_intent",
        "greeted": bool(ctx.get("greeted") or ctx.get("outreach")),
        "name": "" if is_placeholder_name(sess.get("name")) else (sess.get("name") or ""),
    }


def _parse_json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _is_exact_guest_count(g: str | None) -> bool:
    return bool(g and re.fullmatch(r"\d{1,2}", str(g).strip()))


def _guest_need(guests: str | None) -> int:
    if not guests:
        return 2
    m = re.search(r"(\d+)", str(guests))
    return int(m.group(1)) if m else 2


def _normalize_slots(
    raw_slots: dict[str, Any] | None,
    guest_text: str,
    sess: dict[str, Any],
) -> dict[str, Any]:
    """Validate LLM slots with parsers; merge corrections over session."""
    raw_slots = raw_slots if isinstance(raw_slots, dict) else {}
    out: dict[str, Any] = {}

    # dates — предпочитаем парсер по тексту гостя (выходные > «на 29» от модели)
    d = parse_dates(guest_text)
    if d:
        out["dates"] = normalize_dates_phrase(d) or d
    elif sess.get("dates"):
        out["dates"] = normalize_dates_phrase(str(sess["dates"])) or sess["dates"]

    # число гостей — только из речи. Точная цифра модели без слов гостя не пишется.
    g = parse_guests(guest_text)
    # не даунгрейдить точное «3» сессии в «1-2» от модели
    if (
        g
        and not _is_exact_guest_count(g)
        and _is_exact_guest_count(str(sess.get("guests") or ""))
        and not re.search(r"1-2|3-4|один-два", guest_text)
    ):
        g = str(sess.get("guests"))
    if g:
        out["guests"] = g
    elif sess.get("guests") and not is_guests_negation(guest_text) and not re.search(
        r"(?i)не\s+\d|\bа\s+\d|исправ|ошиб|вместо", guest_text
    ):
        out["guests"] = sess["guests"]

    from bot.reply_guard import resolve_guest_district

    dist = resolve_guest_district(
        guest_text, raw_slots.get("district"), sess.get("district")
    )
    if dist:
        out["district"] = dist

    ret = parse_returning(guest_text)
    if ret:
        out["returning"] = ret
    elif sess.get("returning"):
        out["returning"] = sess["returning"]

    b = parse_budget(guest_text)
    if b:
        out["budget"] = b
    elif (sess.get("context") or {}).get("budget"):
        out["budget"] = (sess.get("context") or {}).get("budget")

    for key in ("pets", "kids", "parking", "prefs", "favorite"):
        val = raw_slots.get(key)
        guest_said_fact = bool(
            re.search(r"(?i)собак|кошк|питом|животн", guest_text)
            if key == "pets"
            else re.search(r"(?i)ребёнок|ребенок|дети|детск", guest_text)
            if key == "kids"
            else re.search(r"(?i)парков|машин", guest_text)
            if key == "parking"
            else False
        )
        if key == "favorite":
            guest_said_fact = False
        if val and str(val) not in ("null", "None", "") and guest_said_fact:
            out[key] = str(val).strip()[:120]
        elif key == "favorite" and sess.get("favorite"):
            out[key] = sess["favorite"]
        elif key != "favorite":
            cur = (sess.get("context") or {}).get(key)
            if cur:
                out[key] = cur

    # имя квартиры из текста
    if not out.get("favorite"):
        try:
            from bot.catalog import find_by_name_fuzzy

            hit = find_by_name_fuzzy(guest_text)
            if hit:
                out["favorite"] = hit["name"]
        except Exception:
            pass
    return out


_PRICE_RE = re.compile(r"\b(\d{3,6})\s*(?:₽|руб)", re.I)
_BANNED_PHRASES = (
    "просто смотрите",
    "пока без планов",
    "по-человечески",
    "на связи",
    "клиент,",
    "меня зовут",
)


def _msg_text(x: Any) -> str:
    """LLM иногда кладёт в messages dict {'role','content'} — берём content."""
    if isinstance(x, dict):
        return str(x.get("content") or x.get("text") or "").strip()
    t = str(x or "").strip()
    # строковый dump словаря
    if re.match(r"^\s*\{['\"]role['\"]", t):
        m = re.search(r"['\"]content['\"]\s*:\s*['\"](.+?)['\"]\s*\}?\s*$", t, flags=re.S)
        if m:
            return m.group(1).strip()
        return ""
    return t


def _sanitize_messages(
    msgs: list[str],
    *,
    allowed_prices: set[int],
    greeted: bool,
) -> list[str]:
    out: list[str] = []
    for m in msgs:
        t = _msg_text(m)
        if not t:
            continue
        low = t.lower()
        if re.search(r"(?i)^\s*\{['\"]role['\"]|^\s*role\s*:", low):
            continue
        if any(b in low for b in _BANNED_PHRASES):
            for b in _BANNED_PHRASES:
                t = re.sub(re.escape(b), "", t, flags=re.I)
            t = re.sub(r"\s{2,}", " ", t).strip(" ,.—")
        # модель дописывает обещание карточек, хотя их шлёт система
        t = re.sub(
            r"(?i)(?:^|\s)[—\-.]?\s*(?:покажу|вот варианты|карточки ниже|"
            r"сейчас пришлю|сейчас подберу|подобрала)\b[^.!?]*[.!?]?",
            " ",
            t,
        )
        t = re.sub(r"\s{2,}", " ", t).strip(" ,—")
        if t and t[-1] not in ".!?…🙂":
            t += "."
        if greeted and re.match(
            r"^(здравствуйте|добрый день|доброе утро|добрый вечер|привет)\b",
            t.lower(),
        ):
            # срезать re-hello
            t = re.sub(
                r"^(здравствуйте|добрый день|доброе утро|добрый вечер|привет)[^.!?]*[.!?]\s*",
                "",
                t,
                flags=re.I,
            ).strip()
        # выкинуть цены не из каталога
        for m_price in list(_PRICE_RE.finditer(t)):
            n = int(m_price.group(1))
            if n not in allowed_prices:
                t = t.replace(m_price.group(0), "цену уточнит менеджер")
        # ≤1 emoji: оставить первый
        emojis = re.findall(r"[\U0001F300-\U0001FAFF🙂😊🏠✨👍]", t)
        if len(emojis) > 1:
            keep = emojis[0]
            first = True
            def _sub(mm: re.Match[str]) -> str:
                nonlocal first
                if mm.group(0) == keep and first:
                    first = False
                    return mm.group(0)
                return ""
            t = re.sub(r"[\U0001F300-\U0001FAFF🙂😊🏠✨👍]", _sub, t)
        if t:
            out.append(t.strip())
    return out


def _fits_capacity(obj: dict[str, Any], need: int) -> bool:
    cap = obj.get("capacity")
    if isinstance(cap, int) and cap > 0:
        return cap >= need
    return need <= 4  # неизвестная вместимость — не обещаем большую компанию


def _resolve_offers(
    names: list[str] | None,
    slots: dict[str, Any],
    *,
    limit: int = 3,
    exclude_names: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Возвращает (objs, names, district_note)."""
    from bot.catalog import find_by_name_fuzzy, pick_apartments_with_note, fits_district

    need = _guest_need(slots.get("guests"))
    ban = {n.lower() for n in (exclude_names or []) if n}
    district = str(slots.get("district") or "")
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in names or []:
        hit = find_by_name_fuzzy(str(n))
        if not hit or hit["name"].lower() in seen or hit["name"].lower() in ban:
            continue
        if not _fits_capacity(hit, need):
            continue
        if not fits_district(hit, district):
            continue
        picked.append(hit)
        seen.add(hit["name"].lower())
        if len(picked) >= limit:
            break
    note = ""
    if len(picked) < limit:
        extra, note = pick_apartments_with_note(
            district=district,
            guests=str(slots.get("guests") or "2"),
            budget=str(slots.get("budget") or "") or None,
            limit=limit + 4,
            hard_district=True,
        )
        for o in extra:
            name_l = o["name"].lower()
            if name_l in seen or name_l in ban:
                continue
            if not _fits_capacity(o, need):
                continue
            picked.append(o)
            seen.add(name_l)
            if len(picked) >= limit:
                break
    return picked[:limit], [p["name"] for p in picked[:limit]], note


_SUMMARY_LEADS = (
    "Поняла",
    "Хорошо, вижу",
    "Ок, приняла",
    "Ясно",
)


def _slot_summary_line(
    slots: dict[str, Any],
    prev: dict[str, Any] | None = None,
    *,
    only_changed: bool = False,
) -> str | None:
    """Вариативная сводка; при only_changed — только изменившиеся слоты."""
    prev = prev or {}
    parts: list[str] = []
    changed: list[str] = []
    if slots.get("dates") and (
        not only_changed or str(slots.get("dates")) != str(prev.get("dates") or "")
    ):
        parts.append(str(slots["dates"]))
        if str(slots.get("dates")) != str(prev.get("dates") or ""):
            changed.append(f"даты — {slots['dates']}")
    if slots.get("guests") and (
        not only_changed or str(slots.get("guests")) != str(prev.get("guests") or "")
    ):
        gp = format_guests_phrase(slots["guests"])
        parts.append(gp)
        if str(slots.get("guests")) != str(prev.get("guests") or ""):
            changed.append(gp)
    if slots.get("district") and (
        not only_changed or str(slots.get("district")) != str(prev.get("district") or "")
    ):
        from bot.reply_guard import guest_district_phrase

        dist_disp = guest_district_phrase(
            _normalize_district_label(str(slots["district"])) or str(slots["district"])
        )
        parts.append(dist_disp)
        if str(slots.get("district")) != str(prev.get("district") or ""):
            changed.append(dist_disp)
    if only_changed:
        if not changed:
            return None
        # одну правку гостей оформляет caller («Поняла, N человека»)
        if len(changed) == 1 and re.search(r"\d+\s*(гост|человек)", changed[0]):
            return None
        lead = _SUMMARY_LEADS[sum(ord(c) for c in changed[0]) % len(_SUMMARY_LEADS)]
        return f"{lead}: {', '.join(changed)}."
    if not parts:
        return None
    lead = _SUMMARY_LEADS[sum(ord(c) for c in parts[0]) % len(_SUMMARY_LEADS)]
    return f"{lead}: {', '.join(parts)}."


PETS_EARLY_LINE = (
    "С питомцами можно не во всех квартирах. "
    "В карточке будет пометка, где можно и какая доплата. "
    "Напишите даты и район — подберу подходящие."
)

_GUIDE_INTENT_RE = re.compile(
    r"(?i)путеводител|инструкц\w*\s*(проживан|по\s*квартир|для\s*гост)|"
    r"как\s+(включить|пользоваться|настроить|работа\w*\s+с)|"
    r"(не\s+работа|не\s+включа|сломал\w*|не\s+греет|не\s+стира)\w*.{0,40}"
    r"(стиралк|посудомой|микроволн|телевиз|\bтв\b|бойлер|духовк|кофемашин|фен|утюг|кондиционер|плит)|"
    r"(стиралк|посудомой|микроволн|бойлер|телевизор|духовк|кофемашин).{0,30}"
    r"(как|не\s|включ|работа|пользова)|"
    r"парол\w*\s+(от\s+)?(вай|wifi|wi-?fi|интернет)|"
    r"(где|как)\s+парков|парковк\w*\s*(где|как)|"
    r"куда\s+(поставить|припарковать)\s+машин|"
    r"как\s+(добраться|пройти|зайти|найти\s+подъезд|открыть\s+(дверь|домофон))|"
    r"где\s+(подъезд|домофон|лежит\s+ключ|шкаф\s+с\s+ключ)|"
    r"что[- ]то\s+не\s+работа|не\s+работа\w*\s+техник"
)
_GUIDE_PLACE_RE = re.compile(
    r"(?i)\d|улиц|пер\.|переул|просп|шоссе|проезд|набереж|бульвар|магистрал|"
    r"квартир|жк\b|балакирев|магистральн|руставел|севанск|ленинск|профсоюз|"
    r"строкомбинат|лобанов|ощепков|фитарев|каштанов|соснов"
)


def _guide_intent(text: str) -> bool:
    return bool(_GUIDE_INTENT_RE.search(text or ""))


def _guide_reply(
    sess: dict[str, Any],
    raw: str,
    history: list[dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """Путеводитель по проживанию: спросить адрес → прислать ссылку из таблицы."""
    from bot.apartments_map import (
        GUIDE_ASK_LINE,
        GUIDE_MULTI_LINE,
        GUIDE_UNKNOWN_LINE,
        format_guide_message,
        guide_for_name,
        guides_for_address,
    )

    ctx = dict(sess.get("context") or {})
    awaiting = bool(ctx.get("guide_await") or ctx.get("guide_pick"))
    if not awaiting and not _guide_intent(raw):
        return None

    hits = guides_for_address(raw)
    if not hits:
        known = str(sess.get("favorite") or ctx.get("guide_name") or "").strip()
        if known and not awaiting:
            title, url = guide_for_name(known)
            if url:
                hits = [(title or known, url)]

    if len(hits) == 1:
        name, url = hits[0]
        line = format_guide_message(name, url)
        return (
            [line],
            None,
            _craft_state(
                sess,
                step=str(sess.get("step") or "await_intent"),
                path="smart:rule/guide",
                ctx_extra={
                    "guide_await": False,
                    "guide_pick": False,
                    "guide_name": name,
                    "favorite": name,
                },
            ),
            False,
        )
    if len(hits) > 1:
        names = ", ".join(f"«{n}»" for n, _u in hits[:6])
        line = f"{GUIDE_MULTI_LINE} У нас здесь: {names}."
        return (
            [line],
            None,
            _craft_state(
                sess,
                step=str(sess.get("step") or "await_intent"),
                path="smart:rule/guide-pick",
                ctx_extra={"guide_await": False, "guide_pick": True},
            ),
            False,
        )
    if awaiting:
        # ждём адрес/название — чужие реплики (даты, гости) не перехватываем
        if not (_GUIDE_PLACE_RE.search(raw) or len(raw.split()) <= 4):
            return None
        return (
            [GUIDE_UNKNOWN_LINE],
            None,
            _craft_state(
                sess,
                step=str(sess.get("step") or "await_intent"),
                path="smart:rule/guide-unknown",
                ctx_extra={"guide_await": True, "guide_pick": bool(ctx.get("guide_pick"))},
            ),
            False,
        )
    return (
        [GUIDE_ASK_LINE],
        None,
        _craft_state(
            sess,
            step=str(sess.get("step") or "await_intent"),
            path="smart:rule/guide-ask",
            ctx_extra={"guide_await": True, "guide_pick": False},
        ),
        False,
    )


def _pets_answer(text: str, slots: dict[str, Any], *, offers: list[str] | None = None) -> str:
    """Отдельный вопрос про животных: сначала общий ответ, после карточек — по списку."""
    names = [str(x) for x in (offers or slots.get("offers") or []) if x]
    if not names:
        return PETS_EARLY_LINE
    kind = "питомцем"
    if re.search(r"(?i)собак", text) or re.search(r"(?i)собак", str(slots.get("pets") or "")):
        kind = "собакой"
    elif re.search(r"(?i)кошк", text) or re.search(r"(?i)кошк", str(slots.get("pets") or "")):
        kind = "кошкой"
    ok_names: list[str] = []
    no_names: list[str] = []
    try:
        from bot.apartments_map import allows_pets, pets_note

        for name in names:
            if allows_pets(name):
                note = pets_note(name)
                ok_names.append(f"«{name}» {note}".strip() if note else f"«{name}»")
            else:
                no_names.append(f"«{name}»")
    except Exception:
        return PETS_EARLY_LINE
    bits: list[str] = []
    if ok_names:
        bits.append(f"С {kind} можно: {', '.join(ok_names)}.")
    if no_names:
        bits.append(f"Без животных: {', '.join(no_names)}.")
    if not bits:
        return PETS_EARLY_LINE
    return " ".join(bits)


def _cards_with_reasons(
    objs: list[dict[str, Any]],
    reasons: dict[str, str] | None,
    *,
    footer: str | None = None,
    lead: str | None = None,
    district: str | None = None,
    guests: str | None = None,
) -> str:
    from bot.catalog import format_card

    leads = (
        "Подобрала несколько вариантов под вас 🙂",
        "Вот что лучше подходит под ваш запрос 🙂",
        "Смотрите, что нашлось под ваши условия 🙂",
    )
    head = (lead or "").strip() or leads[len(objs) % len(leads)]
    parts = [head]
    for i, obj in enumerate(objs, 1):
        name = str(obj.get("name") or "")
        block = f"{i}) {format_card(obj)}"
        why = ""
        if reasons:
            why = str(reasons.get(name) or reasons.get(name.lower()) or "").strip()
        why = _fresh_reason(why, obj, district=district, guests=guests)
        if why:
            block += f"\nПочему подходит: {why}"
        parts.append(block)
    foot = (footer or "").strip() or "Если подходит, напишите номер (1–3) или название."
    if "не подтвержда" not in foot.lower() and "по календарю" not in foot.lower():
        foot = foot.rstrip()
        if foot[-1:] not in ".!?":
            foot += "."
        foot += " Наличие на эти даты отсюда не подтверждаю."
    parts.append(foot)
    return "\n\n".join(parts)


def _fresh_reason(
    why: str,
    obj: dict[str, Any],
    *,
    district: str | None = None,
    guests: str | None = None,
) -> str:
    """Причина только с тем, чего ещё нет на карточке."""
    from bot.catalog import format_card

    card = format_card(obj).lower()
    metro = (obj.get("metro") or "").lower()

    def keep(text: str) -> str:
        parts = [p.strip() for p in re.split(r",|;", text or "") if p.strip()]
        fresh: list[str] = []
        for part in parts:
            low = part.lower()
            if low in card or (metro and low in metro):
                continue
            if re.search(r"(?i)до\s+\d+\s+гост", low) and re.search(
                r"до\s+\d+\s+гост", card
            ):
                continue
            fresh.append(part)
        return ", ".join(fresh)

    cleaned = keep(_sanitize_reason(why, obj))
    if cleaned:
        return cleaned[:120]
    return keep(_default_reason(obj, district=district, guests=guests))[:120]


def _sanitize_reason(why: str, obj: dict[str, Any]) -> str:
    """Нельзя писать «центр» для нецентральной квартиры."""
    w = (why or "").strip()
    if not w:
        return ""
    if obj.get("is_central") or obj.get("zone") == "center":
        return w[:120]
    # вырезать ложный центр
    if re.search(r"(?i)центр", w):
        w = re.sub(r"(?i)\s*в\s*центре\s*,?", " ", w)
        w = re.sub(r"(?i)центр\w*", "", w)
        w = re.sub(r"\s{2,}", " ", w).strip(" ,.—")
    # отброс бессмысленного «Москва, до N гостей»
    if re.fullmatch(r"(?i)москва(?:,\s*до\s*\d+\s*гост\w*)?", w):
        return ""
    return w[:120]


def _cap_msgs(msgs: list[str], limit: int = 3) -> list[str]:
    """Не больше limit пузырей; карточки и финальный вопрос не выбрасываем."""
    msgs = [m for m in msgs if (m or "").strip()]
    if len(msgs) <= limit:
        return msgs
    card_i = next(
        (
            i
            for i, m in enumerate(msgs)
            if re.search(r"(?m)^1\)", m) or "Почему подходит:" in m
        ),
        None,
    )
    q_i = None
    for i in range(len(msgs) - 1, -1, -1):
        if card_i is not None and i == card_i:
            continue
        if re.search(
            r"\?|подскажите|были у нас|впервые|напишите номер|подключаю",
            msgs[i],
            flags=re.I,
        ):
            q_i = i
            break
    head: list[str] = []
    for i, m in enumerate(msgs):
        if i == card_i or i == q_i:
            continue
        head.append(m)
    reserved = (1 if card_i is not None else 0) + (1 if q_i is not None else 0)
    head = head[: max(0, limit - reserved)]
    if len(head) >= 2 and reserved >= 1 and len(head) + reserved > limit:
        # склеить первые смысловые фразы
        head = ["\n\n".join(head)]
        head = head[: max(0, limit - reserved)]
    out = list(head)
    if card_i is not None:
        out.append(msgs[card_i])
    if q_i is not None:
        if len(out) >= limit:
            out[-1] = out[-1].rstrip() + "\n\n" + msgs[q_i]
        else:
            out.append(msgs[q_i])
    return out[:limit]


def _default_reason(
    obj: dict[str, Any],
    *,
    district: str | None = None,
    guests: str | None = None,
) -> str:
    try:
        from bot.catalog import reason_for_offer

        return reason_for_offer(obj, district=district, guests=guests)
    except Exception:
        metro = (obj.get("metro") or obj.get("area") or "")[:48]
        return metro or "из каталога"


def _next_question(ask_next: str, slots: dict[str, Any]) -> str | None:
    ask = (ask_next or "").strip().lower()
    if ask in ("none", "null", ""):
        if not slots.get("dates"):
            ask = "dates"
        elif not slots.get("guests"):
            ask = "guests"
        elif not slots.get("district"):
            ask = "district"
        elif slots.get("dates") and slots.get("guests") and slots.get("district"):
            if not slots.get("returning"):
                ask = "returning"
            else:
                ask = "pick"
        else:
            return None
    # вопросы с опорой на уже известное — звучит догадливо, не как анкета
    if ask == "district":
        from bot.phrases import district_choice_message

        return district_choice_message()
    if ask == "dates":
        return "Подскажите, пожалуйста, на какие даты планируете поездку?"
    if ask == "guests":
        return "Сколько вас будет?"
    if ask == "returning":
        return "Подскажите, пожалуйста — вы у нас уже были или впервые?"
    if ask == "pick":
        return "Какой вариант ближе — напишите номер или название 🙂"
    if ask == "stay":
        return None
    if ask == "book":
        return HANDOFF_LINE
    return None


def _human_ack(
    text: str,
    slots: dict[str, Any],
    prev: dict[str, Any],
    *,
    asked_pets: bool = False,
) -> str | None:
    """Короткое «услышала вас» без робо-сводки «Записала: a, b, c»."""
    bits: list[str] = []
    if asked_pets:
        return None  # pets_answer отдельно
    # новое в этом ходе
    if slots.get("dates") and str(slots.get("dates")) != str(prev.get("dates") or ""):
        bits.append(str(slots["dates"]))
    if slots.get("guests") and str(slots.get("guests")) != str(prev.get("guests") or ""):
        bits.append(format_guests_phrase(slots["guests"]))
    if slots.get("district") and str(slots.get("district")) != str(
        prev.get("district") or ""
    ):
        from bot.reply_guard import guest_district_phrase

        dist = guest_district_phrase(
            _normalize_district_label(str(slots["district"])) or str(slots["district"])
        )
        bits.append(dist)
    if not bits:
        return None
    # живая склейка без канцелярита
    leads = (
        "Поняла",
        "Хорошо, вижу",
        "Ок, приняла",
        "Ясно",
    )
    lead = leads[sum(ord(c) for c in bits[0]) % len(leads)]
    if len(bits) == 1:
        return f"{lead}: {bits[0]}."
    if len(bits) == 2:
        return f"{lead}: {bits[0]}, {bits[1]}."
    # три слота — чуть естественнее, чем список через запятую
    return f"{lead}: {bits[0]}, {bits[1]}, {bits[2]}."


def _llm_insight_ok(text: str, *, intent: str) -> bool:
    """Пропускать живую реакцию модели, отсекая выдумки и сводки."""
    low = (text or "").lower().strip()
    if len(low) < 4 or len(low) > 220:
        return False
    if re.search(
        r"(?i)^(записала|приняла|отметила|хорошо,? зафиксировала)\b|"
        r"подобрал|на части объектов|важнее:|метро или|"
        r"гост\w*\s+планир|планир\w*\s+поездк|вот что есть|район вам больше|"
        r"\d+\s*°|градус|777|99999|wifi.?парол",
        low,
    ):
        return False
    if intent not in ("faq", "apartment_q") and re.search(
        r"(?i)парковка точно|подберу с парков|парковкой и метро|"
        r"свободно с|скидк\w+\s*\d",
        low,
    ):
        return False
    if re.fullmatch(r"(?i)ок|хорошо|поняла|принято|супер|ясно[.!]?", low):
        return False
    if _BRUSH_OFF_RE.search(low):
        return False
    if re.search(
        r"(?i)\b(эм+|мм+|ээ+|секунду|минутку|одну минуту|сейчас подумаю|"
        r"сейчас гляну|щас вернусь)\b",
        low,
    ):
        return False
    return True


def _pick_llm_insight(
    raw_msgs: list[str],
    *,
    intent: str,
    with_cards: bool,
) -> str:
    """Короткий живой кусок из LLM; при карточках — без вопроса в хвосте."""
    for m in raw_msgs:
        m2 = re.sub(
            r"(?i)^\s*привет(ствую)?[.!]?\s*",
            "Здравствуйте! ",
            (m or "").strip(),
        ).strip()
        if not _llm_insight_ok(m2, intent=intent):
            continue
        if with_cards and "?" in m2:
            head = m2.split("?", 1)[0].strip()
            if head and not re.search(r"[.!?…🙂]$", head):
                head += "."
            if head and _llm_insight_ok(head, intent=intent):
                return head
            continue
        return m2
    return ""


def _infer_step(slots: dict[str, Any], ask_next: str, *, offered: bool, esc: bool) -> str:
    if esc:
        return "handed_off"
    ask = (ask_next or "").lower()
    if ask == "book" or offered and slots.get("returning"):
        return "await_returning" if not slots.get("returning") else "await_returning"
    if offered or ask == "pick" or ask == "returning":
        return "await_returning"
    # воронка: район → даты → гости → календарь
    if not slots.get("district"):
        return "await_district"
    if not slots.get("dates"):
        return "await_dates"
    if not slots.get("guests"):
        return "await_guests"
    return "await_returning"


def _buttons_for(step: str, ask_next: str) -> list[tuple[str, str]] | None:
    ask = (ask_next or "").lower()
    key = {
        "dates": "dates",
        "guests": "guests",
        "district": "district",
        "returning": "returning",
        "pick": "returning",
    }.get(ask)
    if key:
        return BUTTONS.get(key)
    return BUTTONS.get(
        {
            "await_dates": "dates",
            "await_guests": "guests",
            "await_district": "district",
            "await_returning": "returning",
        }.get(step, "")
    )


async def _call_understand(
    system: str,
    messages: list[dict[str, str]],
) -> tuple[str, str] | None:
    if _UNDERSTAND_HOOK is not None:
        return await _UNDERSTAND_HOOK(system, messages)
    timeout = _env_float("SMART_TIMEOUT_SEC", 12.0)
    max_tokens = _env_int("SMART_MAX_TOKENS", 480)
    providers = load_providers(role="understand")
    if not providers:
        providers = load_providers()
    if not providers:
        return None
    return await chat_completion(
        providers,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.35,
        json_mode=True,
        timeout=timeout,
    )


_LAUGH_RE = re.compile(
    r"(?i)^\s*(ору+|ахах[\w]*|хаха[\w]*|хехе+|лол+|кек+|ржу[\w]*|"
    r"(?:ха[\s\-.]*){2,}|аха+|ха+|😂+|🤣+|😆+)[.!…\s🤣😂]*$"
)
_SHRUG_RE = re.compile(
    r"(?i)^\s*(ок|окей|okay|ладно|хз|не\s*знаю|потом|щас|секунду|мм+|эм+|ну+|ага|угу|"
    r"ясно|понятно|спс|спасибо|пасиб)[.!…\s]*$"
)
_AVAIL_RE = re.compile(
    # «почём» ≠ «почему» (скрин: «Почему за день?» → ложный календарь)
    r"(?i)сколько\s*(будет\s*)?(стоит|стоимость)|какая\s*цена|поч[её]м(?![а-яё])|"
    r"свободн|есть\s*места|наличи"
)
_EARLY_CHECKIN_RE = re.compile(
    r"(?i)ранн(ий|ее)\s*заезд|заехать\s*до\s*15|до\s*15:00|до\s*тр[её]х|"
    r"заехать\s*(по)?раньше|пораньше\s*заех|заехать\s*(в|к)\s*([1-9]|1[0-4])\b|"
    r"заезд\s*(в|к)\s*([1-9]|1[0-4])\b|в\s*\d{1,2}\s*утра"
)
_LATE_CHECKOUT_RE = re.compile(
    r"(?i)поздн(ий|ее)\s*выезд|после\s*12|(выехать|уехать)\s*(по)?позже|(по)?позже\s*(выех|уех)"
)
_EARLY_LATE_LINE = (
    "Ранний заезд и поздний выезд иногда можно, если квартира свободна. "
    "Напишите желаемое время — уточню по выбранной квартире."
)

_NAIVE_FACTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)wifi|вайф|wi-fi|парол[ья]\s*от\s*(вай|интернет)|интернет"),
        "Вайфай есть почти везде. Пароль — в путеводителе по квартире. Подскажите, пожалуйста, ваш адрес — пришлю инструкцию по проживанию 🙂",
    ),
    (
        re.compile(r"(?i)вы\s*бот|ты\s*бот|это\s*бот|вы\s*робот|нейросет|chatgpt|чат\s*гпт|\bии\b"),
        "Я виртуальный помощник Home24, могу позвать менеджера.",
    ),
    (
        re.compile(r"(?i)как\s*тебя\s*зовут|сколько\s*тебе\s*лет|ты\s*кто\s*по\s*имени"),
        "Я из команды Home24.",
    ),
    (
        re.compile(r"(?i)анекдот|шутк|расскажи\s*что"),
        "С этим не помогу, а с квартирой с радостью.",
    ),
    (
        re.compile(r"(?i)люблю\s*тебя|выйди\s*замуж|познаком|свидан"),
        "Спасибо) Я тут по квартирам.",
    ),
    (
        re.compile(r"(?i)аквариум|пиран|оркестр|слон|динозавр|вертол|роял|пианино|мебель\s*перевез"),
        "Крупные вещи и шум по правилам дома нельзя.",
    ),
    (
        re.compile(r"(?i)курить|кальян|вейп|сигарет"),
        "В квартирах не курим. На балконе можно, если он есть и дом не против.",
    ),
    (
        re.compile(r"(?i)вечеринк|тусовк|можно\s*компанию|человек\s*\d{2}|\d{2}\s*человек\s*вечер"),
        "Тихо отдохнуть можно, шумные вечеринки нет. Жить можно по числу спальных мест.",
    ),
    (
        re.compile(r"(?i)крипт|bitcoin|\bbtc\b|usdt|dogecoin"),
        "Крипту не принимаем, только карта или перевод. Способ оплаты менеджер пришлёт при брони.",
    ),
    (
        re.compile(r"(?i)ключ|код\s*от\s*двер|как\s*попасть|кто\s*(нас\s*)?встрет"),
        "Код или ключ пришлём перед заездом, заселение без встречи.",
    ),
    (
        _EARLY_CHECKIN_RE,
        "Ранний заезд иногда можно, если квартира свободна. Напишите желаемое время — уточню.",
    ),
    (
        _LATE_CHECKOUT_RE,
        "Поздний выезд иногда можно, если нет заезда следом. Напишите время — уточню по квартире.",
    ),
    (
        re.compile(r"(?i)заезд|заселен|заселиться|со\s*скольки|во\s*сколько\s*въез|чек-ин|check-?in"),
        "Заезд после 15:00, точное время зависит от квартиры.",
    ),
    (
        re.compile(r"(?i)выезд|чек-аут|check-?out|до\s*скольки|во\s*сколько\s*(надо\s*|нужно\s*)?выех"),
        "Выезд до 12:00. Позже иногда можно, зависит от квартиры.",
    ),
    (
        re.compile(r"(?i)(залог|депозит)[^.?!]{0,60}(возвра|верн|отда)|(возвра|верн)[^.?!]{0,30}(залог|депозит)"),
        "Залог возвращаем после выезда, как только пройдёт клининг.",
    ),
    (
        re.compile(r"(?i)залог|депозит"),
        "Залог 2 000 ₽, во всех квартирах. Возвращаем после выезда, как только пройдёт клининг.",
    ),
    (
        re.compile(r"(?i)оплат|наличн|перевод|сбер|тиньк|картой|по\s*карте"),
        "Оплата картой онлайн или переводом. Менеджер всё пришлёт при брони.",
    ),
    (
        re.compile(r"(?i)уборк|полотенц|бель[её]"),
        "Перед каждым заездом уборка, чистое бельё и полотенца.",
    ),
    (
        re.compile(r"(?i)(?:^|[\s,])(?:ало|есть\s*кто|вы\s*тут|вы\s*на\s*связи)\b"),
        "Да, я тут.",
    ),
    (
        re.compile(r"(?i)парков|на\s*машин|(поставить|оставить)\s*машин"),
        "Парковка зависит от дома, где-то двор, где-то городская рядом. По вашей квартире уточнит менеджер.",
    ),
    (
        re.compile(r"(?i)собак|собач|кошк|\bкот(ом|а|ик)?\b|питом|животн|\bп[её]с\b"),
        PETS_EARLY_LINE,
    ),
    (
        re.compile(r"(?i)кофемашин|кофеварк|\bкофе\b"),
        "В каждой квартире есть кофемашина.",
    ),
)
# Тексты выше = script.md → «Короткие факты» (по порядку; «вы бот?» — из «Ответы по словам»).


def _last_bot_text(history: list[dict[str, Any]] | None) -> str:
    for h in reversed(history or []):
        if (h.get("role") or "") == "bot" and str(h.get("text") or "").strip():
            return str(h.get("text") or "")
    return ""


_PACE_RE = re.compile(
    r"(?i)\b(быстро|бистро|медленно|долг[оа]|чётко|четко|сразу)\b.{0,24}"
    r"\b(ответил\w*|отвечаешь|ответ\w*|пишешь|написал\w*|реагир\w*)\b"
)
_BRUSH_OFF_RE = re.compile(
    r"(?i)заковырист|по делу|не значит хорошо|напишите нормально"
)
_DATE_FILLER = {
    "ну",
    "на",
    "в",
    "к",
    "с",
    "го",
    "числа",
    "число",
    "ориентировочно",
    "примерно",
    "где",
    "то",
    "пожалуйста",
    "да",
    "ок",
    "это",
    "будет",
}


_VAGUE_AREA_RE = re.compile(
    r"(?i)^\s*(?:ну[, ]*)?(?:"
    r"район\s+крут\w+|крут\w+(?:\s+район)?|"
    r"классн\w+(?:\s+район)?|норм(?:альный)?(?:\s+район)?"
    r")[.!?…\s]*$"
)
_CONFUSED_RE = re.compile(
    r"(?i)^\s*(?:"
    r"чего|чё|че|где|что|а|"
    r"не\s*понял[аи]?|я\s*не\s*понимаю|ничего\s*не\s*понял[аи]?|"
    r"поясни(?:те)?|в\s*смысле"
    r")[.!?…\s]*$"
)


def _dates_ready(dates: str) -> bool:
    """«на 10» без месяца — ещё не даты поездки."""
    d = (dates or "").strip().lower()
    if not d or d == "ещё не определились":
        return False
    if re.fullmatch(r"на \d{1,2}", d):
        return False
    return True


def _open_ask(slots: dict[str, Any]) -> str:
    if not _dates_ready(str(slots.get("dates") or "")):
        return "dates"
    if not str(slots.get("guests") or "").strip():
        return "guests"
    if not str(slots.get("district") or "").strip():
        return "district"
    if not str(slots.get("returning") or "").strip():
        return "returning"
    return "pick"


def _ask_step(ask: str, fallback: str) -> str:
    return {
        "dates": "await_dates",
        "guests": "await_guests",
        "district": "await_district",
        "returning": "await_returning",
    }.get(ask, fallback or "await_returning")


def _status_line(heard: dict[str, Any], *, ask: str | None = None) -> tuple[str, str, str]:
    """Что уже слышали и существующий вопрос следующего пустого шага."""
    dates = str(heard.get("dates") or "")
    pet = str((heard.get("context") or {}).get("pets") or "")
    bits: list[str] = []
    if dates and dates != "ещё не определились":
        bits.append(dates[:1].upper() + dates[1:])
    if "собак" in pet:
        bits.append("с собакой — зависит от квартиры")
    elif pet:
        bits.append("с животными — зависит от квартиры")
    ask = ask or _open_ask(heard)
    q = _next_question(ask, heard) or ""
    step = _ask_step(ask, str(heard.get("step") or "await_returning"))
    key = "" if ask == "pick" else ask
    head = ", ".join(bits)
    if head:
        head = head[:1].upper() + head[1:]
    if head and q:
        line = f"{head}. {q}"
    else:
        line = q or head
    return line, step, key


_PING_LINE_RE = re.compile(
    r"(?i)^(?:ну[, ]*)?(?:"
    r"привет|здарова|здравствуй\w*|добрый\s+(?:день|вечер|утро)|"
    r"ку-?ку(?:\s+епта)?|куку|ку|дядь|дядя|ау+|алло|ты\s+тут"
    r")(?:\s+епта)?$"
)


def _only_pings(text: str) -> bool:
    parts = [p.strip(" .!…") for p in re.split(r"[\n]+", text or "") if p.strip()]
    if not parts or len(parts) > 8:
        return False
    return all(_PING_LINE_RE.match(p) for p in parts)


def _day_is_noisy(raw: str) -> bool:
    words = re.findall(r"[а-яё]{2,}", (raw or "").lower().replace("ё", "е"))
    return any(w not in _DATE_FILLER for w in words)


def _nudge_line(sess: dict[str, Any]) -> tuple[str, str]:
    """Существующий вопрос пустого слота, без комментария к реплике гостя."""
    slots = _session_slots(sess)
    ask = _open_ask(slots)
    return _next_question(ask, slots) or "", ask


def _forward_question(
    sess: dict[str, Any], history: list[dict[str, Any]] | None
) -> tuple[str, str]:
    """Следующий пробел, кроме вопроса, который бот только что задал."""
    from bot.ai import _ask_key

    slots = _session_slots(sess)
    last_key = _ask_key(_last_bot_text(history))
    order: list[str] = []
    if not slots.get("district"):
        order.append("district")
    if not slots.get("dates"):
        order.append("dates")
    if not slots.get("guests"):
        order.append("guests")
    if (
        slots.get("dates")
        and slots.get("guests")
        and slots.get("district")
        and not slots.get("returning")
    ):
        order.append("returning")
    for ask in order:
        if ask == last_key:
            continue
        q = _next_question(ask, slots)
        if q:
            return q, ask
    # только что спросили то же самое — переспрашиваем другими словами, без тупика
    if order:
        from bot.reply_guard import follow_up_ask

        recent = "\n".join(
            str(h.get("text") or "") for h in (history or [])[-6:] if (h.get("role") or "") == "bot"
        )
        follow = follow_up_ask(order[0], recent)
        if follow:
            return follow, order[0]
    if not slots.get("dates"):
        return "Как будете готовы, напишите даты)", ""
    return "Напишите, что ещё уточнить, подберу)", ""


def _guest_place_phrase(text: str, sess: dict[str, Any]) -> str:
    """Район и адрес словами гостя. Чужой адрес квартире не приписываем."""
    from bot.catalog import match_catalog_place
    from bot.reply_guard import is_open_district

    named = match_catalog_place(text) or ""
    if not named:
        stored = str(sess.get("district") or "").strip()
        if is_open_district(stored):
            # «без разницы» — не передаём как place, иначе календарь ищет «не принципиально»
            named = ""
        else:
            named = match_catalog_place(stored) or ""
            if not named and stored and stored.lower() not in (
                "центр",
                "спокойный",
                "спокойный район",
            ):
                named = stored
    street = ""
    m = re.search(
        r"(?i)([а-яё]{4,}(?:ский|ская|ское|ий|ая|ое)?\s+"
        r"(?:проезд|улиц\w*|переул\w*|бульвар\w*|шоссе|набережн\w*))",
        text or "",
    )
    if m:
        street = " ".join(m.group(1).split())
        street = street[0].upper() + street[1:]
    if street and named:
        return f"{street}, {named}"
    return street or named


def _craft_state(
    sess: dict[str, Any],
    *,
    step: str,
    path: str,
    esc: bool = False,
    district: str | None = None,
    ctx_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = dict(sess.get("context") or {})
    ctx.pop("quiet_turn", None)  # тишина — только на один ход
    if not path.endswith("/wait"):
        ctx.pop("wait_stage", None)
    if ctx_extra:
        ctx.update(ctx_extra)
    ctx["smart"] = True
    ctx["reply_path"] = path
    upd: dict[str, Any] = {"step": "handed_off" if esc else step, "context": ctx}
    for key in ("dates", "guests", "district", "returning", "favorite"):
        if sess.get(key):
            upd[key] = sess[key]
    if ctx_extra and ctx_extra.get("favorite"):
        upd["favorite"] = str(ctx_extra["favorite"])
    if district:
        upd["district"] = district
    if esc:
        upd["handed_off"] = 1
    return upd


def _with_one_forward(
    fact: str,
    sess: dict[str, Any],
    history: list[dict[str, Any]] | None,
) -> tuple[str, str]:
    q, ask = _forward_question(sess, history)
    fact = (fact or "").strip()
    if not fact:
        return q, ask
    if not ask:  # после факта мягкий «напишите, когда…» не нужен
        return fact, ""
    if fact.rstrip().endswith("?"):
        return fact, ""
    # факт уже закрывает тот же пробел — не клеим второй вопрос
    blob = fact.lower()
    if ask == "dates" and re.search(r"дат", blob):
        return fact, ""
    if ask == "guests" and re.search(r"гост|человек", blob):
        return fact, ""
    if ask == "district" and re.search(r"район|центр", blob):
        return fact, ""
    return f"{fact} {q}".strip(), ask


# Ответы, после которых вопрос воронки звучит как анкета
_META_FACT_RE = re.compile(
    r"(?i)виртуальный помощник|^я из команды|с этим не помогу|я тут по квартирам|^да, я тут|^спасибо\)"
)

# Кто пишет и откуда номер — частые ответы на рассылку (не в «Коротких фактах»)
_WHO_RULES: tuple[tuple[re.Pattern[str], str, bool], ...] = (
    (
        re.compile(r"(?i)откуда\s+(у\s+вас\s+)?(мой\s+)?(номер|контакт|телефон)|где\s+взял\w*\s+(мой\s+)?номер"),
        "Вы бронировали у нас квартиру, номер остался с той брони. "
        "Если не хотите сообщений, напишите, больше не побеспокою.",
        False,
    ),
    (
        re.compile(r"(?i)^\s*(а\s+)?(вы|ты)\s+кто\??\s*$|^\s*кто\s+(вы|это|пишет)\??\s*$|что\s+за\s+home\s*24"),
        "Это Home24, квартиры посуточно в Москве) Вы у нас останавливались, поэтому пишу.",
        False,
    ),
    (
        re.compile(r"(?i)(уже|мы)\s+(сняли|нашли|забронировали)|(сняли|нашли)\s+(другую|уже)|не\s+актуальн"),
        "Хорошо) Понадобится квартира в следующий раз, пишите.",
        True,
    ),
)

# Праздник / романтика рядом с датами — ответить и на это, а не только по слотам
_SIDE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)с\s*(реб[её]нк|детьми|малыш)\w*\s*(можно|пустите|разрешено)|кроватк|детск\w*\s*(кроват|стул)"),
        "С детьми можно) Кроватку или стульчик уточню по квартире.",
    ),
    (
        re.compile(r"(?i)день\s*рожд|отметить|праздн|юбиле|девичник|годовщин"),
        "Тихо отметить можно, и квартиру можем украсить.",
    ),
    (
        re.compile(r"(?i)романт|сюрприз|свидани|кино|проектор"),
        "Можем подготовить романтический вечер с кино на проекторе.",
    ),
)


def _side_fact(raw: str) -> str:
    """Попутный вопрос рядом со слотами: «нас четверо, приедем ночью, можно?» — ответить и на него."""
    for rx, line in _SIDE_RULES:
        if rx.search(raw or ""):
            return line
    try:
        from bot.apartments_map import address_answer

        where = address_answer(raw or "")
        if where:
            return where
    except Exception:
        pass
    for rx, fact in _NAIVE_FACTS:
        if rx.search(raw or "") and not _META_FACT_RE.search(fact):
            # питомцы — отдельный путь (_bundle_reply / holiday / naive FAQ),
            # иначе длинный ответ про животных клеится к «на Новый год, с собакой…»
            low = fact.lower()
            if "животн" in low or "питом" in low:
                continue
            return fact
    try:
        from bot.life import match_life

        hit = match_life(raw or "")
    except Exception:
        hit = None
    if hit and not hit.escalate and not hit.stop and hit.kind not in ("route", "later", "wrong", "long"):
        return hit.line
    return ""


def _mentions_known_apartment(text: str, sess: dict[str, Any]) -> bool:
    """Вопрос про уже названную квартиру не перехватывать общим FAQ."""
    low = (text or "").lower()
    offers = ((sess.get("context") or {}).get("offers") or []) if isinstance(sess.get("context"), dict) else []
    if any(str(n).lower() in low for n in offers if n):
        return True
    try:
        from bot.catalog import find_by_name_fuzzy

        return bool(find_by_name_fuzzy(text))
    except Exception:
        return False


def _overlay_heard(sess: dict[str, Any], raw: str) -> dict[str, Any]:
    """Слоты из этой реплики важнее пустой анкеты: не переспрашивать сказанное."""
    merged = dict(sess)
    dates = parse_dates(raw)
    if dates and dates != "ещё не определились":
        merged["dates"] = dates
    guests = parse_guests(raw)
    if guests:
        merged["guests"] = guests
    district = parse_district(raw)
    if district:
        merged["district"] = district
    return merged


def _apartment_count() -> int:
    try:
        from bot.travelline import _read_rooms_file

        n = len(_read_rooms_file())
        if n:
            return n
    except Exception:
        pass
    return 71


def _script_reply(
    sess: dict[str, Any],
    raw: str,
    history: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """Сценарий Марии: услуги бывшему гостю и «что у вас есть»."""
    ctx = dict(sess.get("context") or {})
    perk = str(ctx.get("perk") or "")
    services = bool(re.search(r"(?i)услуг", raw))
    what_have = bool(
        re.search(r"(?i)что у вас есть|что есть у вас|чем вы занима|какие квартир", raw)
    )
    if what_have and not services:
        n = _apartment_count()
        line = (
            f"У нас {n} квартир, в каждой свежий современный ремонт. "
            "Часть стилизована под эпоху известных людей. "
            "Какую сможем подобрать — зависит от ваших дат или района."
        )
        return (
            [line],
            None,
            _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/catalog"),
            False,
        )
    # «С услугами определимся на месте» — не вопрос про услуги, факты не нужны
    services_q = services and bool(
        re.search(r"(?i)\?|как(?:ие|ая|ой)|что\s+за|расскаж|подробн|список|есть\s+ли", raw)
    )
    if services and not services_q and re.search(r"(?i)определимся|на\s+месте|потом|решим|позже|не\s+нужн", raw):
        fact = "Хорошо, так и сделаем)"
        line, _ask = _with_one_forward(fact, sess, history)
        state = _craft_state(
            sess,
            step=_ask_step(_ask, str(sess.get("step") or "await_dates")) if _ask else str(sess.get("step") or "await_dates"),
            path="smart:rule/perk-later",
            ctx_extra={"perk": "wait", "offer_open": False},
        )
        return [line], None, state, False
    # «Да» на предложение из рассылки → рассказать, а не спрашивать даты
    # (new-materials/home24_prompt_addon_services_da.md, аудит S7/R1#1/R1#13)
    if not parse_dates(raw) and not parse_guests(raw) and not parse_district(raw):
        offered = offer_reply(
            dict(sess), raw, services_question=services_q, last_bot=_last_bot_text(history)
        )
        if offered:
            o_msgs, o_ctx, o_step = offered
            state = _craft_state(sess, step=o_step, path="smart:rule/offer-reply")
            state["context"] = {**(state.get("context") or {}), **o_ctx, "reply_path": "smart:rule/offer-reply"}
            if o_step == "done":
                state["step"] = "done"
            buttons = None
            if o_msgs and str(o_msgs[0]).rstrip().endswith("?"):
                if o_step == "await_dates":
                    buttons = BUTTONS.get("dates")
                elif o_step == "await_district":
                    buttons = BUTTONS.get("district")
            return o_msgs, buttons, state, False
    known_dates = str(sess.get("dates") or "").strip()
    dates_ready = bool(known_dates and known_dates != "ещё не определились")
    # Вопрос про доп. услуги — сразу список, без «откроется за день до заезда» и без анкеты
    if services_q or (services and perk in {"wait", "offered", "told"}):
        next_perk = "told" if dates_ready or perk in {"wait", "offered", "told"} else "orient"
        return (
            [ADDON_SERVICES_REPLY],
            None,
            _craft_state(
                sess,
                step=str(sess.get("step") or "await_dates"),
                path="smart:rule/perk-services",
                ctx_extra={
                    "perk": next_perk,
                    "offer_open": False,
                    "services_colleague_open": True,
                },
            ),
            False,
        )
    if services and dates_ready:
        return (
            [ADDON_SERVICES_REPLY],
            None,
            _craft_state(
                sess,
                step=str(sess.get("step") or "await_dates"),
                path="smart:rule/perk-services",
                ctx_extra={
                    "perk": "told",
                    "offer_open": False,
                    "services_colleague_open": True,
                },
            ),
            False,
        )
    in_perk = perk in {"visit", "orient", "offered", "wait"} or (
        bool(ctx.get("outreach")) and services
    )
    if not in_perk and not services:
        return None
    heard = _overlay_heard(sess, raw)
    # собака, гости или район в этой же фразе — обычный подбор, не сценарий услуг
    if _pet_bits(raw) or parse_guests(raw) or parse_district(raw):
        return None
    dates = parse_dates(raw)
    real_dates = bool(dates and dates != "ещё не определились")
    if perk in {"visit", "orient", ""} and real_dates and not services and not (
        "?" in raw or _side_fact(raw) or re.search(r"(?i)можно|ранн|поздн|парков|скидк|адрес|метро", raw)
        # «Хотела бы забронировать…» — обычный подбор, без рекламы «одна услуга бесплатно»
        or re.search(r"(?i)заброниров|бронир|бронь|снять|сниму|нужна\s+квартир", raw)
    ):
        # даты в сценарии Марии — просто подтверждаем и идём дальше по воронке
        shown = normalize_dates_phrase(dates) or dates
        heard["dates"] = dates
        ask = _open_ask(heard)
        q = (_next_question(ask, heard) or "").strip()
        line = f"Поняла, {shown})" + (f" {q}" if q else "")
        state = _craft_state(
            heard,
            step=_ask_step(ask, "await_district"),
            path="smart:rule/perk-dates",
            ctx_extra={"perk": "told", "offer_open": False},
        )
        state["dates"] = dates
        return [line], BUTTONS.get(ask) if ask else None, state, False
    if perk == "offered" and (
        services
        or re.search(r"(?i)напишу|как буду знать|точно знать|класс|интересно", raw)
        or is_consent(raw)
    ):
        # старый шаг «интересно?» про бесплатную услугу — только список услуг, без «бесплатно»
        if real_dates or _dates_ready(str(sess.get("dates") or "")):
            line, _ask = _with_one_forward(ADDON_SERVICES_REPLY, heard, history)
        else:
            line = ADDON_SERVICES_REPLY + "\nКак будут точные дни — напишите, подберём."
        return (
            [line],
            None,
            _craft_state(
                sess,
                step=str(sess.get("step") or "await_dates"),
                path="smart:rule/perk-services",
                ctx_extra={"perk": "told", "offer_open": False},
            ),
            False,
        )
    if services and not real_dates:
        # спросили «что за услуги» — рассказываем сразу, даты не требуем (аудит S7)
        return (
            [ADDON_SERVICES_REPLY],
            None,
            _craft_state(
                sess,
                step="await_dates",
                path="smart:rule/perk-services",
                ctx_extra={
                    "perk": "orient",
                    "offer_open": False,
                    "services_colleague_open": True,
                },
            ),
            False,
        )
    if perk in ("visit", "orient") and not real_dates and re.search(
        r"(?i)планир|поездк|собира\w*\s+(в|к)|не знаю,?\s+когда", raw
    ):
        line = (
            "Рада, что вам интересно) Будете планировать поездку, "
            "у вас уже есть ориентир по датам или смотрите на ближайшее будущее?"
        )
        return (
            [line],
            None,
            _craft_state(
                sess,
                step="await_dates",
                path="smart:rule/perk-orient",
                ctx_extra={"perk": "orient"},
            ),
            False,
        )
    return None


def _booking_payload(text: str) -> bool:
    return bool(parse_dates(text) and (parse_guests(text) or parse_district(text)))


def _pet_bits(raw: str) -> tuple[str, str] | None:
    if re.search(r"(?i)собак", raw):
        return "собакой", "собака"
    if re.search(r"(?i)кошк", raw):
        return "кошкой", "кошка"
    if re.search(r"(?i)питом", raw):
        return "питомцем", "питомец"
    return None


def _guest_phrase(guests: str, raw: str = "") -> str:
    if str(guests).strip() == "1" and re.search(r"(?i)одна|сама", raw or ""):
        return "одна"
    word = {"1": "один", "2": "двое", "3": "трое", "4": "четверо"}.get(str(guests).strip())
    if word:
        return word
    return f"{guests} гостей"


def _bundle_reply(
    sess: dict[str, Any],
    raw: str,
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """Дата вместе с гостями, районом или питомцем: один следующий вопрос."""
    dates = parse_dates(raw)
    if not dates or dates == "ещё не определились":
        return None
    said_guests = parse_guests(raw)
    # «человек 6» — это гости, а не «на 6-е число»
    bare_day = re.fullmatch(r"на (\d{1,2})", dates)
    if bare_day and said_guests and bare_day.group(1) == str(said_guests).strip():
        return None
    said_district = parse_district(raw)
    pet = _pet_bits(raw)
    if not pet and not said_guests and not said_district:
        return None
    if _mentions_known_apartment(raw, sess):
        return None
    guests = said_guests or str(sess.get("guests") or "")
    district = said_district or str(sess.get("district") or "")
    # полный набор без питомца оставляем подбору квартир
    if not pet and guests and district:
        return None
    shown = dates[:1].upper() + dates[1:]
    line = shown
    if guests:
        line = f"{line}, {_guest_phrase(guests, raw)}"
    if pet:
        line = (
            f"{line}, с {pet[0]} можно, но зависит от квартиры — "
            f"отмечу в списке свободных."
        )
    else:
        line = f"{line}."
    buttons = None
    if not district:
        line = line.rstrip(".") + ". Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?"
        step = "await_district"
        buttons = None
    elif not guests:
        line = line.rstrip(".") + ". Сколько вас будет?"
        step = "await_guests"
        buttons = BUTTONS.get("guests")
    elif not (sess.get("returning") or sess.get("returning_guest")):
        line = line.rstrip(".") + ". Вы у нас уже были или впервые?"
        step = "await_returning"
        buttons = BUTTONS.get("returning")
    else:
        step = str(sess.get("step") or "await_returning")
    state = _craft_state(
        sess,
        step=step,
        path="smart:rule/bundle",
        ctx_extra={"pets": pet[1]} if pet else None,
        district=district or None,
    )
    state["dates"] = dates
    if guests:
        state["guests"] = guests
    return [line], buttons, state, False


# «отдать ход скрипту без ИИ»: smart_reply вернёт None, ai.reply позовёт engine
_DELEGATE: Any = object()


def _craft_early(
    sess: dict[str, Any],
    raw: str,
    history: list[dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    got = _craft_early_raw(sess, raw, history)
    if got is _DELEGATE:
        return None
    if got and (
        _dates_ready(str(parse_dates(raw) or "")) or parse_guests(raw) or parse_district(raw)
    ):
        # гость назвал даты / гостей / район — больше не «думает», дальше обычная воронка
        ctx = dict((got[2] or {}).get("context") or {})
        if ctx.pop("thinking", None):
            got[2]["context"] = ctx
    return got


_ACK_RE = re.compile(
    r"(?i)^\s*(?:ну\s+|да,?\s+|ага,?\s+)?(?:хорошо|хорош|ок|окей|ok|okay|ладно|понятно|ясно|договорились|"
    r"угу|ага|понял|поняла|принято|отлично|супер|спасибо,?\s*хорошо|хорошо,?\s*спасибо|ок,?\s*спасибо|"
    r"буду\s+иметь\s+в\s+виду|учту|напишу|хорошо,?\s*напишу|ок,?\s*напишу)[\s.!)(🙂😊👍]*$"
)
_INVITE_RE = re.compile(
    r"(?i)если\s+что-то\s+планируете|напишите,\s+подбер|как\s+надумаете|будете\s+готовы|"
    r"как\s+(?:только\s+)?определитесь|как\s+появятся|не\s+спешите|будем\s+ждать|пишите\)?\s*$"
)
WAIT_LINE = "Будем ждать!"
WAIT_EMOJI = "😊"


def _waiting_reply(
    sess: dict[str, Any], raw: str, history: list[dict[str, Any]] | None
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """«Хорошо» на приглашение «напишите, подберу» — без анкеты: ждём гостя."""
    if not _ACK_RE.match(raw or ""):
        return None
    ctx = dict(sess.get("context") or {})
    last = _last_bot_text(history).strip().rstrip(".")
    stage = int(ctx.get("wait_stage") or 0)
    if last == WAIT_EMOJI or (stage >= 2 and last in (WAIT_EMOJI, "")):
        state = _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/wait",
                             ctx_extra={"wait_stage": 3, "quiet_turn": True})
        return [], None, state, False
    if last.startswith(WAIT_LINE) or stage == 1 and WAIT_LINE.lower() in last.lower():
        state = _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/wait",
                             ctx_extra={"wait_stage": 2, "quiet_turn": False})
        return [WAIT_EMOJI], None, state, False
    if _INVITE_RE.search(last) and not last.rstrip().endswith("?"):
        state = _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/wait",
                             ctx_extra={"wait_stage": 1, "thinking": True, "quiet_turn": False})
        return [WAIT_LINE], None, state, False
    # «Хорошо» на «Хотите, подберу квартиру?» — не закрывать «Будем ждать!», мягко оставить дверь
    if re.search(r"(?i)хотите,?\s*подбер|подберу\s+квартир\w*\s*\?", last) and last.rstrip().endswith("?"):
        from bot.phrases import LATER_LINE

        state = _craft_state(
            sess,
            step=str(sess.get("step") or "await_dates"),
            path="smart:rule/wait",
            ctx_extra={"wait_stage": 1, "thinking": True, "quiet_turn": False, "offer_pick_ask": False},
        )
        return [LATER_LINE], None, state, False
    if last and "?" not in last and not re.search(r"(?m)^1\)", last):
        # «Хорошо» на ответ-факт («С питомцами можно не везде…») — улыбка, без анкеты и без поиска «района Хорошо»
        state = _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/wait",
                             ctx_extra={"wait_stage": 2, "quiet_turn": False})
        return [WAIT_EMOJI], None, state, False
    return None


_PROMO_Q_RE = re.compile(r"(?i)акци|бонус|спецпредлож|спец\.?\s*предлож|что\s+выгодн|какие\s+выгод|програм\w*\s+лояльн|кешб[эе]к|кэшб[эе]к")
_SERVICES_Q_RE = re.compile(
    r"(?i)(?:доп\w*|какие|что\s+за|есть\s+ли|какие\s+есть)\s+(?:\w+\s+){0,2}услуг|услуг\w*\s+(?:\w+\s+){0,2}(?:какие|есть)|что\s+(?:вы\s+)?(?:ещё\s+)?предлагаете"
)
_SERVICES_WHY_RE = re.compile(
    r"(?i)почему\s+за\s+день|зачем\s+за\s+день|почему\s+(?:только\s+)?перед\s+заезд|"
    r"почему\s+не\s+(?:сейчас|сразу)|а\s+сейчас\s+нельзя"
)
_CALL_COLLEAGUE_RE = re.compile(
    r"(?i)^\s*(?:"
    r"да+|ага|угу|ок|окей|давай(?:те)?|можно|конечно|"
    r"(?:да[,!\s]+)?(?:пожалуйста[,!\s]+)?"
    r"(?:позовите|позови|зовите|свяжите|свяжи|подключите|подключи)"
    r"(?:\s+(?:с\s+)?(?:коллег\w*|менеджер\w*|пожалуйста)){0,3}|"
    r"нужен\s+менеджер|нужна\s+коллег\w*"
    r")[\s!.)\]🙂]*$"
)
SERVICES_LINE = ADDON_SERVICES_REPLY


def _colleague_call_reply(
    sess: dict[str, Any], raw: str, history: list[dict[str, Any]] | None
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """После списка услуг: «да / позовите / свяжите» → менеджер через 10–15 минут."""
    ctx = dict(sess.get("context") or {})
    last = _last_bot_text(history).lower()
    open_offer = bool(ctx.get("services_colleague_open")) or (
        "позову коллег" in last or "другие дополнительн" in last or "фотосесс" in last
    )
    if not open_offer or not _CALL_COLLEAGUE_RE.match((raw or "").strip()):
        return None
    if parse_dates(raw) or parse_guests(raw) or parse_district(raw):
        return None
    return (
        [MANAGER_CONNECT_LINE],
        None,
        _craft_state(
            sess,
            step="handed_off",
            path="smart:rule/services-colleague",
            esc=True,
            ctx_extra={"services_colleague_open": False, "perk": "told", "offer_open": False},
        ),
        True,
    )


def _perks_reply(
    sess: dict[str, Any], raw: str, history: list[dict[str, Any]] | None
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """«Какие акции?» / «Какие доп. услуги?» — сразу список, без «бесплатно» и без «за день до заезда»."""
    if not raw:
        return None
    called = _colleague_call_reply(sess, raw, history)
    if called:
        return called
    # «Почему за день?» после старого ответа — снова список, без календаря квартир
    if _SERVICES_WHY_RE.search(raw) and not parse_dates(raw) and not parse_guests(raw):
        recent_bot = " ".join(
            str(h.get("text") or "") for h in (history or [])[-6:] if (h.get("role") or "") == "bot"
        ).lower()
        if "услуг" in recent_bot or "за день до заезда" in recent_bot or "дополнительн" in recent_bot:
            fact = "Можно выбрать сразу:\n" + ADDON_SERVICES_LIST
            return (
                [fact],
                None,
                _craft_state(
                    sess,
                    step=str(sess.get("step") or "await_dates"),
                    path="smart:rule/perks-why",
                    ctx_extra={
                        "offer_open": False,
                        "perk": "told",
                        "services_colleague_open": True,
                    },
                ),
                False,
            )
    if not raw.strip().endswith("?") and len(raw) > 80:
        return None
    if str((sess.get("context") or {}).get("perk") or "") in ("offered", "wait"):
        return None  # старый шаг «интересно?» — ответ в _script_reply
    promo = bool(_PROMO_Q_RE.search(raw))
    services = bool(_SERVICES_Q_RE.search(raw))
    if not (promo or services) or parse_dates(raw) or parse_guests(raw):
        return None
    said = " ".join(
        str(h.get("text") or "") for h in (history or [])[-10:] if (h.get("role") or "") == "bot"
    ).lower()
    bits: list[str] = []
    if services:
        bits.append(SERVICES_LINE)
    if promo:
        if "балл" in said:
            bits.append("Сейчас действует прямая бронь: без комиссии агрегаторов и с баллами за каждое проживание.")
        else:
            bits.append(
                "При прямой брони выгоднее: без комиссии агрегаторов, плюс баллы — 500 за регистрацию "
                "и потом с каждого проживания, 1 балл = 1 ₽."
            )
    fact = "\n".join(bits) if services and not promo else " ".join(bits)
    if services and promo:
        fact = bits[0] + "\n" + " ".join(bits[1:])
    ctx = dict(sess.get("context") or {})
    # список услуг / гость думает — без анкеты (скрины 56–58 и 11.11 доп. услуги)
    if ctx.get("thinking") or (services and not promo):
        line, ask = fact, ""
    else:
        line, ask = _with_one_forward(fact, sess, history)
    state = _craft_state(
        sess,
        step=_ask_step(ask, str(sess.get("step") or "await_dates")) if ask else str(sess.get("step") or "await_dates"),
        path="smart:rule/perks",
        ctx_extra={
            "offer_open": False,
            "perk": "told" if services else ctx.get("perk", ""),
            "services_colleague_open": True if services else ctx.get("services_colleague_open"),
        },
    )
    return [line], BUTTONS.get(ask) if ask else None, state, False


_MORE_RE = re.compile(r"(?i)^\s*(?:а\s+|и\s+|давайте\s+|покажите\s+)?ещ[её]\s*[.!?)]*\s*$|ещ[её]\s*(вариант|квартир|есть|что|покаж)|други[ех]|другой\s+район|други[ем]\s+район|что\s+ещ[её]|покажите\s+ещ[её]|больше\s+вариант")
_TL_YES_RE = re.compile(
    r"(?i)^\s*(да|давайте|давай|бронируем|бронирую|беру|берём|берем|выбираем|выберем|"
    r"подходит|отлично|хочу|оформляйте|передавайте)\b"
)
_COMFORT_NO_RE = re.compile(
    r"(?i)^\s*(нет|не\s*надо|не\s*нужно|ничего|без\s*доп|вс[её]\s*есть|пока\s*нет|"
    r"не\s*требуется|достаточно)[.!)\s]*$"
)
_CHOSE_FLAT_RE = re.compile(
    r"(?i)(выбрал[аи]?|выбираем|выберем|берём|берем|остановил\w*\s*на|"
    r"хотим\s*(эту|эта)|берём\s*эту|эту\s*квартир|написала?\s*.{0,40}выбрал)"
)


def _comfort_after_pick(
    sess: dict[str, Any],
    chosen: str,
    *,
    when: str = "",
    offers: list[str] | None = None,
) -> tuple[list[str], None, dict[str, Any], bool]:
    """Подтвердить выбор: добрать даты/гостей или сразу доп. для комфорта."""
    from bot.phrases import COMFORT_EXTRAS_ASK, district_choice_message

    head = f"Отлично, «{chosen}»" + (f" на {when}" if when else "") + " 🙂"
    ctx_extra = {
        "comfort_asked": False,
        "offers": list(
            dict.fromkeys(
                list(offers or [])
                + [str(x) for x in ((sess.get("context") or {}).get("offers") or []) if x]
                + [chosen]
            )
        ),
    }
    # район из карты, если ещё не назван
    if not str(sess.get("district") or "").strip():
        try:
            from bot.apartments_map import place_short

            place = place_short(chosen)
            if place:
                # «Коммунарка, м. Коммунарка» → Коммунарка
                sess = {**sess, "district": place.split(",")[0].strip()}
        except Exception:
            pass
    if not _dates_ready(str(sess.get("dates") or "")):
        state = _craft_state(
            sess, step="await_dates", path="smart:rule/pick-need-dates", ctx_extra=ctx_extra
        )
        state["favorite"] = chosen
        return (
            [head, "На какие даты смотрите?"],
            BUTTONS.get("dates"),
            state,
            False,
        )
    if not str(sess.get("guests") or "").strip():
        state = _craft_state(
            sess, step="await_guests", path="smart:rule/pick-need-guests", ctx_extra=ctx_extra
        )
        state["favorite"] = chosen
        return (
            [head, "Сколько вас будет?"],
            BUTTONS.get("guests"),
            state,
            False,
        )
    if not str(sess.get("district") or "").strip():
        state = _craft_state(
            sess, step="await_district", path="smart:rule/pick-need-district", ctx_extra=ctx_extra
        )
        state["favorite"] = chosen
        return [head, district_choice_message()], None, state, False
    ctx_extra["comfort_asked"] = True
    state = _craft_state(
        sess,
        step="await_comfort",
        path="smart:rule/comfort-ask",
        ctx_extra=ctx_extra,
    )
    state["favorite"] = chosen
    return [head, COMFORT_EXTRAS_ASK], None, state, False


def _apartment_pick_reply(
    sess: dict[str, Any],
    raw: str,
    history: list[dict[str, Any]] | None,
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """Гость назвал квартиру / подтвердил выбор — не переспрашивать «какой вариант?»."""
    step = str(sess.get("step") or "")
    if step in ("await_comfort", "await_docs", "await_booking_confirm", "handed_off", "done"):
        return None
    from bot.apartments_map import resolve_apartment_title
    from bot.phrases import is_consent

    ctx = dict(sess.get("context") or {})
    offers = [
        str(x)
        for x in list(ctx.get("tl_offers") or []) + list(ctx.get("offers") or [])
        if x
    ]
    last = _last_bot_text(history).lower()
    fav = str(sess.get("favorite") or "").strip()
    # «Подойдёт?» / «хороший выбор… напишите номер» + «да» при уже выбранной
    if fav and (
        is_consent(raw)
        or _TL_YES_RE.match((raw or "").strip())
        or re.match(r"(?i)^\s*(да|верно|подходит|берём|берем|выбираем)\b", raw or "")
    ):
        if re.search(r"подойд|хороший выбор|вариант ближе|номер или название|напишите номер", last):
            return _comfort_after_pick(sess, fav, offers=offers)

    chosen = resolve_apartment_title(raw, offers=offers)
    if not chosen:
        return None
    low = (raw or "").lower()
    bare = bool(re.fullmatch(r"\s*[«»\"']?[\w\- ]{2,40}[»\"']?\s*", raw or ""))
    chose = bool(_CHOSE_FLAT_RE.search(raw or ""))
    pick_ask = bool(
        re.search(r"вариант ближе|номер или название|напишите номер|какой вариант|подойд", last)
    )
    # голое имя / «выбрали Скандинавию» / ответ на просьбу выбрать
    if not (bare or chose or pick_ask or chosen.lower() in {o.lower() for o in offers}):
        # имя в тексте вопроса («где Скандинавия?») — не выбор
        if re.search(r"\?|где|адрес|метро|сколько|свободн|можно ли", low):
            return None
        if not chose and not bare:
            return None
    return _comfort_after_pick(sess, chosen, offers=offers or [chosen])


def _booking_summary_state(
    sess: dict[str, Any],
    *,
    ack: str = "",
    ctx_extra: dict[str, Any] | None = None,
) -> tuple[list[str], None, dict[str, Any], bool]:
    """Итог для сверки: даты, район, квартира, залог, животные, доп. услуги."""
    from bot.phrases import booking_summary_message

    ctx = dict(sess.get("context") or {})
    if ctx_extra:
        ctx.update(ctx_extra)
    merged = {**sess, "context": ctx}
    summary = booking_summary_message(merged)
    msgs = [f"{ack} {summary}".strip() if ack else summary]
    state = _craft_state(
        sess,
        step="await_booking_confirm",
        path="smart:rule/booking-summary",
        ctx_extra=ctx,
    )
    if sess.get("favorite"):
        state["favorite"] = sess["favorite"]
    return msgs, None, state, False


def _comfort_extras_reply(
    sess: dict[str, Any], raw: str
) -> tuple[list[str], None, dict[str, Any], bool] | None:
    """Ответ на вопрос про доп. удобства → спросить про отчётные документы."""
    if str(sess.get("step") or "") != "await_comfort":
        return None
    from bot.engine import is_refusal
    from bot.phrases import REPORT_DOCS_ASK

    fav = str(sess.get("favorite") or "").strip()
    low = (raw or "").strip()
    ctx = dict(sess.get("context") or {})
    if _COMFORT_NO_RE.match(low) or is_refusal(low):
        note = "доп. удобства не нужны"
        ack = "Хорошо)"
    else:
        note = f"доп. для комфорта: {low[:220]}"
        ack = "Записала)"
    prev = str(ctx.get("prefs") or "")
    ctx["prefs"] = (prev + "; " + note).strip("; ")[:400] if prev else note[:400]
    ctx["comfort_asked"] = True
    state = _craft_state(
        sess,
        step="await_docs",
        path="smart:rule/docs-ask",
        ctx_extra=ctx,
    )
    if fav:
        state["favorite"] = fav
    return [f"{ack} {REPORT_DOCS_ASK}"], None, state, False


def _docs_reply(
    sess: dict[str, Any], raw: str
) -> tuple[list[str], None, dict[str, Any], bool] | None:
    """Нужны ли отчётные документы → итог для сверки."""
    if str(sess.get("step") or "") != "await_docs":
        return None
    from bot.engine import is_refusal
    from bot.phrases import is_consent

    low = (raw or "").strip()
    ctx = dict(sess.get("context") or {})
    if is_consent(low) or re.match(
        r"(?i)^\s*(да|нужны|нужен|нужно|пожалуйста|сделайте|давайте)\b", low
    ):
        ctx["report_docs"] = "да"
        ack = "Хорошо)"
    elif is_refusal(low) or _COMFORT_NO_RE.match(low) or re.match(
        r"(?i)^\s*(нет|не\s*нужн|без\s*документ|не\s*надо)\b", low
    ):
        ctx["report_docs"] = "нет"
        ack = "Поняла)"
    else:
        # свободный ответ — считаем, что нужны, и сохраняем формулировку
        ctx["report_docs"] = "да"
        prev = str(ctx.get("prefs") or "")
        note = f"отчётные документы: {low[:160]}"
        ctx["prefs"] = (prev + "; " + note).strip("; ")[:400] if prev else note[:400]
        ack = "Записала)"
    base = {**sess, "context": ctx}
    return _booking_summary_state(base, ack=ack, ctx_extra=ctx)


def _booking_confirm_reply(
    sess: dict[str, Any], raw: str
) -> tuple[list[str], None, dict[str, Any], bool] | None:
    """Гость подтвердил итог → менеджеру; иначе тоже передаём с пометкой поправить."""
    if str(sess.get("step") or "") != "await_booking_confirm":
        return None
    from bot.phrases import HANDOFF_LINE, is_consent
    from bot.engine import is_refusal

    low = (raw or "").strip()
    ctx = dict(sess.get("context") or {})
    if is_consent(low) or re.match(r"(?i)^\s*(да|верно|вс[её]\s*верно|ок|окей|подтверждаю)\b", low):
        ack = "Отлично)"
    elif is_refusal(low) or re.match(r"(?i)^\s*(нет|не\s*верно|ошибк)", low):
        note = f"сверка: гость поправил — {low[:180]}"
        prev = str(ctx.get("prefs") or "")
        ctx["prefs"] = (prev + "; " + note).strip("; ")[:400] if prev else note[:400]
        ack = "Поняла, передам менеджеру уточнить)"
    else:
        note = f"сверка / комментарий: {low[:180]}"
        prev = str(ctx.get("prefs") or "")
        ctx["prefs"] = (prev + "; " + note).strip("; ")[:400] if prev else note[:400]
        ack = "Записала)"
    state = _craft_state(
        sess,
        step="handed_off",
        path="smart:rule/booking-confirm",
        esc=True,
        ctx_extra=ctx,
    )
    if sess.get("favorite"):
        state["favorite"] = sess["favorite"]
    return [f"{ack} {HANDOFF_LINE}"], None, state, True


def _tl_pick_reply(
    sess: dict[str, Any], raw: str, history: list[dict[str, Any]] | None
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """Гость отвечает на свободные квартиры из календаря: выбор → доп. комфорт → менеджеру."""
    ctx = dict(sess.get("context") or {})
    names = [str(x) for x in (ctx.get("tl_offers") or []) if x]
    last = _last_bot_text(history)
    last_l = last.lower()
    calendar_offer = ("по календарю" in last_l and "свобод" in last_l) or bool(
        re.search(r"(?i)проверю цену", last)
    )
    if not names or not calendar_offer:
        return None
    said_guests = parse_guests(raw)
    if said_guests and re.search(r"(?i)сколько вас|проверю цену", last):
        from bot.travelline import availability_offer

        g = re.search(r"\d+", str(said_guests))
        place = str(sess.get("district") or "")
        line, new_names = availability_offer(str(ctx.get("tl_dates") or sess.get("dates") or ""),
                                             int(g.group(0)) if g else 2, place)
        if line and new_names:
            n = int(g.group(0)) if g else 0
            lead = {1: "Один гость.", 2: "Двое.", 3: "Трое.", 4: "Четверо.", 5: "Пятеро.", 6: "Шестеро."}.get(
                n, format_guests_phrase(said_guests).capitalize() + "."
            )
            state = _craft_state(sess, step="await_returning", path="smart:rule/tl-guests",
                                 ctx_extra={"tl_offers": new_names, "offers": new_names})
            state["guests"] = said_guests
            return [f"{lead} {line}"], None, state, False
        return None
    dates = str(ctx.get("tl_dates") or sess.get("dates") or "")
    try:
        from bot.travelline import span_label, stay_span

        span = stay_span(dates)
        when = span_label(span[0], span[1]) if span else dates
    except Exception:
        when = dates
    low = (raw or "").lower().strip()
    chosen = ""
    m = re.fullmatch(r"\s*(?:№\s*)?(\d)\s*[.)!]*\s*(?:вариант\w*)?\s*", low)
    if m and 1 <= int(m.group(1)) <= len(names):
        chosen = names[int(m.group(1)) - 1]
    if not chosen:
        # по названию — и из прошлых списков («ещё» показывало новые, а гость выбрал из первых)
        for n in list(dict.fromkeys(names + [str(x) for x in (ctx.get("tl_shown") or [])])):
            stem = n.lower()[: max(4, len(n) - 2)]
            if re.search(rf"(?<![а-яёa-z]){re.escape(stem)}", low):
                chosen = n
                break
    if not chosen and len(names) == 1 and (_TL_YES_RE.match(low) or is_consent(raw)) and not _MORE_RE.search(low):
        chosen = names[0]
    if chosen:
        return _comfort_after_pick(sess, chosen, when=when, offers=names)
    if _MORE_RE.search(low):
        from bot.travelline import free_offer_cards

        g = re.search(r"\d+", str(sess.get("guests") or "2"))
        shown_all = list(dict.fromkeys(names + [str(x) for x in (ctx.get("tl_shown") or [])]))
        area = str(sess.get("district") or "")
        cards, more_names = ("", [])
        from bot.reply_guard import is_open_district

        want_other = bool(re.search(r"(?i)други\w*\s+район|в\s+другом|без\s*разницы|любой\s*район", low))
        if area and not is_open_district(area) and not want_other:
            # только тот же район — чужие не подмешиваем
            cards, more_names = free_offer_cards(
                dates, int(g.group(0)) if g else 2, exclude=shown_all, district=area,
                lead=f"Ещё по календарю свободные на {when}:", only_area=True,
            )
        elif is_open_district(area) or not area or want_other:
            cards, more_names = free_offer_cards(
                dates, int(g.group(0)) if g else 2, exclude=shown_all,
                district="" if (is_open_district(area) or want_other or not area) else area,
                lead=(
                    f"Вот ещё по календарю свободные на {when}:"
                    if is_open_district(area) or not area
                    else f"Вот ещё свободные на {when} в других районах:"
                ),
            )
        names = shown_all
        if cards:
            state = _craft_state(sess, step="await_returning", path="smart:rule/tl-more",
                                 ctx_extra={"tl_offers": more_names, "offers": more_names, "tl_dates": dates,
                                            "tl_shown": shown_all + more_names})
            # «по календарю свобод…» — чтобы выбор номером из этого списка тоже сработал
            return [cards.replace("Вот ещё свободные", "Вот ещё по календарю свободные", 1)], None, state, False
        state = _craft_state(sess, step="handed_off", path="smart:rule/tl-more", esc=True)
        return ["Других свободных на эти даты в календаре нет. Передам менеджеру, он поищет варианты 🙂"], None, state, True
    return None


_ALREADY_SAID_RE = re.compile(
    r"(?i)(?:я\s+)?(?:уже|же)\s+(?:вам\s+)?(?:на)?писал\w*|писал\w*\s+(?:уже\s+)?выше|выше\s+(?:уже\s+)?писал|"
    r"я\s+же\s+говорил\w*|уже\s+говорил\w*|уже\s+отвечал\w*"
)


def _craft_early_raw(
    sess: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """Смех, уклонение, наличие и наивные вопросы — без LLM и без петли."""
    raw = (text or "").strip()
    if not raw:
        return None

    # Гость думает: на «как надумаете, пишите» ответил «хорошо» → «Будем ждать!», ещё раз → 😊, дальше тишина.
    # Никаких повторных вопросов про даты, гостей и ночи (скрин 46, 10.11).
    waited = _waiting_reply(sess, raw, history)
    if waited:
        return waited

    # «да / позовите» после списка доп. услуг — раньше выбора квартиры по календарю
    colleague = _colleague_call_reply(sess, raw, history)
    if colleague:
        return colleague

    comfort = _comfort_extras_reply(sess, raw)
    if comfort:
        return comfort

    docs = _docs_reply(sess, raw)
    if docs:
        return docs

    confirmed = _booking_confirm_reply(sess, raw)
    if confirmed:
        return confirmed

    picked = _tl_pick_reply(sess, raw, history)
    if picked:
        return picked

    named = _apartment_pick_reply(sess, raw, history)
    if named:
        return named

    perks = _perks_reply(sess, raw, history)
    if perks:
        return perks

    # «Нет, не двое» — поправка без нового числа: не повторять старое, спросить заново
    if is_guests_negation(raw):
        state = _craft_state(sess, step="await_guests", path="smart:rule/guests-fix")
        state["guests"] = ""
        return (["Поняла, поправлю) Сколько вас будет?"], BUTTONS.get("guests"), state, False)

    # «Я уже написала даты выше» — показать, что услышали, и идти дальше
    if _ALREADY_SAID_RE.search(raw) and not parse_dates(raw) and not parse_guests(raw):
        slots = _session_slots(sess)
        bits = [str(slots[k]) for k in ("dates",) if _dates_ready(str(slots.get(k) or ""))]
        g = str(slots.get("guests") or "").strip()
        if g:
            bits.append(format_guests_phrase(g))
        if slots.get("district") and slots.get("district") != "любой":
            bits.append(str(slots["district"]))
        state = _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/already-said")
        if bits:
            ask = _open_ask(slots)
            if ask in ("pick", "returning") and slots.get("guests") and slots.get("district"):
                return None  # всё есть — пусть подбор покажет варианты
            fact = "Да, вижу: " + ", ".join(bits) + "."
            q = _next_question(ask, slots) or ""
            state["step"] = _ask_step(ask, state["step"])
            return ([f"{fact} {q}".strip()], BUTTONS.get(ask), state, False)
        return (["Извините, не увидела) Продублируйте, пожалуйста, даты?"], None, state, False)

    scripted = _script_reply(sess, raw, history)
    if scripted:
        return scripted

    # путеводитель по проживанию (техника, парковка, как пройти) — до общего FAQ
    guided = _guide_reply(sess, raw, history)
    if guided:
        return guided

    from bot.apartments_map import address_answer

    where = address_answer(raw)
    if where:
        heard_addr = _overlay_heard(sess, raw)  # «с 25 по 28 ноября, где Чехов» — даты тоже запомнить
        if heard_addr.get("district") and re.search(r"(?i)где|адрес|метро|находит", raw) and not parse_district(
            re.sub(r"(?i)«[^»]+»|чехов\w*|дюма|твен\w*|диккенс\w*|скандинави\w*|феррари|россо", "", raw)
        ):
            heard_addr["district"] = sess.get("district") or ""  # спросили адрес квартиры — это не выбор района
        line, ask = _with_one_forward(where, heard_addr, history)
        return (
            [line],
            BUTTONS.get(ask) if ask else None,
            _craft_state(
                heard_addr,
                step=_ask_step(ask, str(sess.get("step") or "await_intent")) if ask else str(sess.get("step") or "await_intent"),
                path="smart:rule/address",
            ),
            False,
        )

    for rx, line, closes in _WHO_RULES:
        if rx.search(raw):
            st = _craft_state(
                sess,
                step="done" if closes else str(sess.get("step") or "await_intent"),
                path="smart:rule/who",
                ctx_extra={"offer_open": False},
            )
            return [line], None, st, False

    if _only_pings(raw):
        heard = dict(sess)
        for item in history or []:
            if (item.get("role") or "") in ("guest", "user"):
                heard = _overlay_heard(heard, str(item.get("text") or ""))
        heard = _overlay_heard(heard, raw)
        dates = str(heard.get("dates") or "")
        if not _dates_ready(dates):
            heard["dates"] = ""
            dates = ""
        if dates:
            shown = dates[:1].upper() + dates[1:]
            pet = str((heard.get("context") or {}).get("pets") or "")
            if "собак" in pet:
                pet_bit = (
                    " С собакой можно, но зависит от квартиры — отмечу в списке свободных."
                )
            elif "кошк" in pet:
                pet_bit = (
                    " С кошкой можно, но зависит от квартиры — отмечу в списке свободных."
                )
            elif pet:
                pet_bit = (
                    " С животными можно, но зависит от квартиры — отмечу в списке свободных."
                )
            else:
                pet_bit = ""
            if not heard.get("district"):
                line, ask, step = (
                    f"{shown}.{pet_bit} Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?",
                    "district",
                    "await_district",
                )
            elif not heard.get("guests"):
                line, ask, step = (
                    f"{shown}.{pet_bit} Сколько вас будет?",
                    "guests",
                    "await_guests",
                )
            else:
                line, ask, step = f"{shown}.{pet_bit}".strip(), "", str(
                    heard.get("step") or "await_returning"
                )
            buttons = BUTTONS.get(ask) if ask else None
        else:
            from bot.phrases import district_choice_message

            line = "Здравствуйте! " + district_choice_message()
            step, buttons = "await_district", None
        return (
            [line],
            buttons,
            _craft_state(heard, step=step, path="smart:rule/resume"),
            False,
        )

    if _VAGUE_AREA_RE.match(raw) and not parse_district(raw):
        heard = dict(sess)
        said = parse_guests(raw)
        if said:
            heard["guests"] = said
        if not _dates_ready(str(heard.get("dates") or "")):
            heard["dates"] = ""
        line = "Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?"
        state = _craft_state(heard, step="await_district", path="smart:rule/area")
        if said:
            state["guests"] = said
        return [line], None, state, False

    if _CONFUSED_RE.match(raw):
        heard = dict(sess)
        for item in history or []:
            if (item.get("role") or "") in ("guest", "user"):
                heard = _overlay_heard(heard, str(item.get("text") or ""))
        line, step, ask = _status_line(heard)
        return (
            [line],
            BUTTONS.get(ask) if ask else None,
            _craft_state(heard, step=step, path="smart:rule/plain"),
            False,
        )

    from bot.tone import is_troll, is_tricky, tricky_line, troll_line

    dates_hint = parse_dates(raw)
    from bot.phrases import LATER_LINE, is_later_think

    if (
        (
            is_later_think(raw)
            or re.search(
                r"(?i)(позже\s*напиш|напишу\s*позже|"
                r"пока\s*не\s*думал|дат\w*.{0,24}(позже|потом)|(позже|потом).{0,24}дат)",
                raw,
            )
        )
        and dates_hint in (None, "ещё не определились")
        and not parse_guests(raw)
        and not parse_district(raw)
    ):
        return (
            [LATER_LINE],
            None,
            _craft_state(sess, step="done", path="smart:rule/life/later"),
            False,
        )

    if is_troll(raw):
        return (
            [troll_line(raw)],
            None,
            _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/troll"),
            False,
        )

    if _PACE_RE.search(raw) and not re.search(
        r"(?i)квартир|апартамент|дат\w*|цен|район|заезд|брон", raw
    ):
        line, ask = _nudge_line(sess)
        step = {
            "dates": "await_dates",
            "guests": "await_guests",
            "district": "await_district",
            "returning": "await_returning",
            "pick": str(sess.get("step") or "await_returning"),
        }.get(ask, str(sess.get("step") or "await_dates"))
        return (
            [line],
            BUTTONS.get(ask),
            _craft_state(sess, step=step, path="smart:rule/pace"),
            False,
        )

    if re.match(r"(?i)^\s*(спасибо|спс|пасиб\w*|благодар\w*)(\s*(большое|огромное|вам))*[.!)\s🙏🙂]*$", raw):
        from bot import phrases as _P

        return (
            [_P.pick(_P.THANKS, dict(sess), "thanks")],
            None,
            _craft_state(sess, step=str(sess.get("step") or "await_intent"), path="smart:rule/thanks"),
            False,
        )

    if re.match(r"(?i)^\s*(да+|ага|угу|ок|окей|ладно|хорошо|давайте)[.!)\s]*$", raw):
        from bot.ai import _ask_key

        last_key = _ask_key(_last_bot_text(history))
        nudge = {
            "dates": "Тогда напишите даты, можно примерно)",
            "guests": "Сколько вас будет?",
            "district": "Какой район вам удобнее?",
            "returning": "Вы у нас уже были или впервые?",
        }.get(last_key)
        if nudge:
            step = {
                "dates": "await_dates",
                "guests": "await_guests",
                "district": "await_district",
                "returning": "await_returning",
            }[last_key]
            return (
                [nudge],
                BUTTONS.get(last_key),
                _craft_state(sess, step=step, path="smart:rule/yes-to-ask"),
                False,
            )

    if (_LAUGH_RE.match(raw) or _SHRUG_RE.match(raw)) and parse_dates(raw) != "ещё не определились":
        # «хз» / «не знаю» — гость думает: это ветка «ещё не определились» ниже, без анкеты
        line, ask = _forward_question(sess, history)
        step = {
            "dates": "await_dates",
            "guests": "await_guests",
            "district": "await_district",
            "returning": "await_returning",
        }.get(ask, str(sess.get("step") or "await_dates"))
        lead = "Поняла 🙂" if _LAUGH_RE.match(raw) else "Хорошо."
        return (
            [f"{lead} {line}"],
            BUTTONS.get(ask) if ask else None,
            _craft_state(sess, step=step, path="smart:rule/listen"),
            False,
        )

    if _AVAIL_RE.search(raw) and not re.search(r"(?i)вариант[ыа]?\s*ещё|другие", raw):
        place = _guest_place_phrase(raw, sess)
        said_district_now = parse_district(raw) or ""
        if not place:
            # «квартиры в Прокшино» — район из текста, даже если в календаре ни у кого нет такого адреса
            named = said_district_now
            if named and named not in ("центр", "спокойный район", "не принципиально"):
                place = named
        dates = str(sess.get("dates") or "").strip()
        from bot.travelline import availability_reply, stay_span

        phrase = normalize_dates_phrase(parse_dates(raw) or dates) or (parse_dates(raw) or dates)
        span = stay_span(phrase)
        from bot.travelline import availability_offer, free_offer_cards

        adults_need = _guest_need(parse_guests(raw) or sess.get("guests"))
        have_guests = bool(parse_guests(raw) or sess.get("guests"))
        # «центр» / зона из сессии — через free_offer_cards (фильтр + ссылки), не простыня
        district_cards = (
            said_district_now
            or str(sess.get("district") or "").strip()
            or place
        )
        calendar_line: str | None = None
        avail_names: list[str] = []
        if span and district_cards:
            calendar_line, avail_names = free_offer_cards(
                phrase,
                adults_need,
                district=district_cards,
                lead="",
            )
            if calendar_line and not calendar_line.lower().startswith("свободны"):
                pass
            elif calendar_line:
                # нормализуем заголовок под даты
                pass
        if span and not calendar_line:
            calendar_line, avail_names = availability_offer(
                phrase,
                adults_need,
                place,
                text=raw,
                next_step=have_guests,
            )
        if not span:
            merged = dict(sess)
            if phrase:
                merged["dates"] = phrase
            said_guests = parse_guests(raw)
            if said_guests:
                merged["guests"] = said_guests
            pet = _pet_bits(raw)
            if pet:
                ctx = dict(merged.get("context") or {})
                ctx["pets"] = pet[1]
                merged["context"] = ctx
            line, step, key = _status_line(merged, ask="dates")
            if re.search(r"(?i)сколько\s*стоит|цен[аыу]|стоимост|почём|почем|прайс", raw):
                # на вопрос про цену — сначала ответ, потом даты
                line = f"Цена зависит от дат и квартиры. {line}"
            state = _craft_state(merged, step=step, path="smart:rule/calendar-span")
            if phrase:
                state["dates"] = phrase
            if said_guests:
                state["guests"] = said_guests
            return (
                [line],
                BUTTONS.get(key) if key else None,
                state,
                False,
            )
        if calendar_line:
            merged = dict(sess)
            if phrase:
                merged["dates"] = phrase
            said_guests = parse_guests(raw)
            if said_guests:
                merged["guests"] = said_guests
            said_place = parse_district(raw) or (place if place and not any(
                n.lower() in place.lower() for n in avail_names) else "")
            if said_place and not str(merged.get("district") or "").strip():
                merged["district"] = said_place  # «квартиры в Прокшино» — район уже назван (скрин 57)
            line, ask = _with_one_forward(calendar_line.rstrip(), merged, history)
            if ask == "guests":
                sep = "\n" if "\n" in calendar_line.rstrip() else " "
                line = f"{calendar_line.rstrip()}{sep}Сколько вас будет? Проверю цену на ваше количество."
            step = {
                "dates": "await_dates",
                "guests": "await_guests",
                "district": "await_district",
                "returning": "await_returning",
            }.get(ask, str(sess.get("step") or "await_returning"))
            state = _craft_state(
                merged,
                step=step,
                path="smart:rule/calendar",
                ctx_extra={"tl_offers": avail_names, "offers": avail_names, "tl_dates": phrase} if avail_names else None,
            )
            if phrase:
                state["dates"] = phrase
            if said_guests:
                state["guests"] = said_guests
            if merged.get("district"):
                state["district"] = merged["district"]
            pet = _pet_bits(raw)
            if pet:
                ctx = dict(state.get("context") or {})
                ctx["pets"] = pet[1]
                state["context"] = ctx
            return (
                [line],
                BUTTONS.get(ask) if ask else None,
                state,
                False,
            )
        when = f" на {dates}" if dates else ""
        if place:
            line = (
                f"По «{place}»{when} цена зависит от дат и квартиры. "
                f"Сейчас подключу менеджера, он скажет точно."
            )
        else:
            line = (
                "Цена зависит от дат и квартиры. "
                "Сейчас подключу менеджера, он скажет точно."
            )
        named = ""
        try:
            from bot.catalog import match_catalog_place

            named = match_catalog_place(raw) or ""
        except Exception:
            named = ""
        state = _craft_state(
            sess,
            step="handed_off",
            path="smart:rule/price",
            esc=True,
            district=named or None,
        )
        if phrase:
            state["dates"] = phrase
        pet = _pet_bits(raw)
        if pet:
            ctx = dict(state.get("context") or {})
            ctx["pets"] = pet[1]
            state["context"] = ctx
            if "животн" not in line.lower() and "питом" not in line.lower() and "собак" not in line.lower():
                line = line.rstrip(".") + ". С животными можно, но зависит от квартиры — отмечу в списке."
        return (
            [line],
            None,
            state,
            True,
        )

    plain_dates = parse_dates(raw)
    if (
        plain_dates
        and not parse_guests(raw)
        and not parse_district(raw)
        and not re.search(r"(?i)собак|кошк|питом|кроват|wifi|вайф|\d+\s*час|утра\b", raw)
        and len(raw) <= 80
    ):
        state = _craft_state(sess, step="await_guests", path="smart:rule/dates")
        state["dates"] = plain_dates
        nights = parse_nights(raw)
        if nights == "1":
            stay = ", одна ночь"
        elif nights == "2":
            stay = ", две ночи"
        elif nights:
            n = int(nights)
            if n % 10 == 1 and n % 100 != 11:
                word = "ночь"
            elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
                word = "ночи"
            else:
                word = "ночей"
            stay = f", {n} {word}"
        else:
            stay = ""
        if plain_dates == "ещё не определились":
            from bot.ai import _ask_key

            last_key = _ask_key(_last_bot_text(history))
            if last_key == "district":
                # «пока не знаем» на вопрос про район — район не важен, идём дальше
                need_returning = not str(sess.get("returning") or "").strip()
                state = _craft_state(
                    sess,
                    step="await_returning" if need_returning else str(sess.get("step") or "await_district"),
                    path="smart:rule/district-any",
                )
                state["district"] = "любой"
                line = "Хорошо, подберу в разных районах)"
                if need_returning:
                    line += " Вы у нас уже были или впервые?"
                elif not str(sess.get("dates") or "").strip() or sess.get("dates") == "ещё не определились":
                    line += " Как появятся даты, напишите, сразу пришлю варианты."
                return ([line], BUTTONS.get("returning") if need_returning else None, state, False)
            # Гость ещё думает (скрин 46, 10.11): не допрашиваем про даты, гостей и ночи.
            # 1-й раз — «не спешите» + предложить пару квартир на примете; дальше — просто ждём.
            ctx_now = dict(sess.get("context") or {})
            thinking_before = bool(ctx_now.get("thinking")) or sess.get("dates") == "ещё не определились"
            dates_known = _dates_ready(str(sess.get("dates") or ""))
            if dates_known and last_key == "guests":
                # даты есть, число гостей пока не знают — не переспрашиваем, идём дальше
                fake = {**sess, "guests": "уточнят"}
                line, ask = _with_one_forward("Хорошо, уточним потом)", fake, history)
                state = _craft_state(
                    sess, step=_ask_step(ask, "await_district") if ask else "await_district", path="smart:rule/guests-later"
                )
                return [line], BUTTONS.get(ask) if ask else None, state, False
            if thinking_before:
                state = _craft_state(
                    sess, step="await_dates", path="smart:rule/thinking", ctx_extra={"thinking": True}
                )
                state["dates"] = "ещё не определились"
                return (["Хорошо, как надумаете, пишите) Подберу квартиру."], None, state, False)
            state = _craft_state(
                sess, step="browsing", path="smart:rule/plans-later", ctx_extra={"thinking": True}
            )  # «давайте» → карточки без дат (engine)
            state["dates"] = "ещё не определились"
            return (["Хорошо, не спешите) Могу пока скинуть пару квартир, чтобы были на примете?"], None, state, False)
        shown = plain_dates[:1].upper() + plain_dates[1:]
        if str(sess.get("dates") or "").strip().lower() == plain_dates.strip().lower():
            shown = "Да, всё верно: " + plain_dates  # гость повторил те же даты
        span_word = re.search(r"(?i)на\s+(неделю|две\s+недели|пару\s+дней|выходные|месяц)", raw)
        if (
            span_word
            and not stay
            and re.match(r"\d", plain_dates)
            and not re.search(r"\bпо\b|[–-]", plain_dates)
        ):
            # «с 20 ноября на неделю» — не терять срок
            shown = f"С {plain_dates} {span_word.group(0).lower()}"
        if re.fullmatch(r"на \d{1,2}", plain_dates) and _day_is_noisy(raw):
            day = plain_dates.split()[-1]
            state["step"] = "await_dates"
            return (
                [f"{day}-е число. Какой месяц и до какого?"],
                BUTTONS.get("dates"),
                state,
                False,
            )
        guests_known = str(sess.get("guests") or "")
        district_known = str(sess.get("district") or "")
        if guests_known:
            state["guests"] = guests_known
        # «с 12 по 15 декабря, а с котом можно?» — ответ на вопрос между датами и следующим шагом
        side_fact = _side_fact(raw)
        if side_fact:
            stay = f"{stay}. {side_fact.rstrip('.')}"
        if not district_known:
            line, step, buttons = (
                f"{shown}{stay}. Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?",
                "await_district",
                None,
            )
        elif not guests_known:
            line, step, buttons = f"{shown}{stay}. Сколько вас будет?", "await_guests", BUTTONS.get("guests")
        elif not (sess.get("returning") or sess.get("returning_guest")):
            line, step, buttons = (
                f"{shown}{stay}. Вы у нас уже были или впервые?",
                "await_returning",
                BUTTONS.get("returning"),
            )
        else:
            line, step, buttons = f"{shown}{stay}.", str(sess.get("step") or "await_returning"), None
        state["step"] = step
        return (
            [line],
            buttons,
            state,
            False,
        )

    bare = re.fullmatch(r"\s*(\d{1,2})\s*[.!]?\s*", raw or "")
    if bare and sess.get("dates") and not sess.get("guests"):
        n = int(bare.group(1))
        if 1 <= n <= 12:
            word = {1: "Один", 2: "Двое", 3: "Трое", 4: "Четверо"}.get(n, f"{n} человек")
            state = _craft_state(sess, step="await_guests", path="smart:rule/guests")
            state["guests"] = str(n)
            if not sess.get("district"):
                state["step"] = "await_district"
                return (
                    [f"{word}. Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?"],
                    None,
                    state,
                    False,
                )
            # район и даты уже есть — карточки из календаря через engine
            return _DELEGATE

    if (
        sess.get("dates")
        and sess.get("guests")
        and not parse_returning(raw)
        and not parse_guests(raw)
        and parse_district(raw)
        not in (
            "центр",
            "спокойный район",
            "не принципиально",
            "Близко к центру",
            "Спальный район",
            "Тихий зелёный район",
            "Подмосковье",
        )
        and 3 <= len((raw or "").strip()) <= 32
        and not re.search(r"\d", raw or "")
        # «Хорошо» / «да» / «спасибо» — не название района (скрин 33: «По «Хорошо» на 5–7 декабря…»)
        and not _ACK_RE.match(raw)
        and not is_consent(raw)
        and not _SHRUG_RE.match(raw)
        and not _LAUGH_RE.match(raw)
        and not re.search(r"(?i)^\s*(нет|не\s|спасибо|благодар|понял|поняла|ладно|ок|окей|ага|угу|да)\b", raw)
        and not raw.strip().endswith("?")
        and not _MORE_RE.search(raw)
    ):
        # свободный текст или названный район («Прокшино») — сверяем с календарём
        from bot.engine import _dates_with_nights

        phrase = ""
        blobs = [str(sess.get("dates") or "")]
        blobs.extend(
            str(h.get("text") or "")
            for h in (history or [])
            if (h.get("role") or "") in ("guest", "user")
        )
        for blob in blobs:
            phrase = _dates_with_nights(blob) or ""
            if phrase:
                break
        phrase = phrase or str(sess.get("dates") or "")
        from bot.travelline import availability_offer

        line, tl_names = availability_offer(
            phrase,
            _guest_need(sess.get("guests")),
            raw.strip(),
            text=raw,
        )
        if line and "календар" in line.lower() and "не подписан" not in line.lower():
            # предложенные квартиры запоминаем: «да», «1», «Карма», «ещё варианты» — дальше по ним
            # «Карма» → район не «Карма»: если гость назвал квартиру, район не перетираем
            named_flat = any(n.lower() in raw.lower() for n in tl_names)
            state = _craft_state(
                sess,
                step="await_returning",
                path="smart:rule/calendar",
                ctx_extra={"tl_offers": tl_names, "offers": tl_names, "tl_dates": phrase},
            )
            if not named_flat:
                state["district"] = raw.strip()
            state["dates"] = phrase
            return [line], None, state, False

    if is_tricky(raw):
        return (
            [tricky_line()],
            None,
            _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/tricky"),
            False,
        )

    from bot.life import match_life

    life = match_life(raw)
    if life and life.kind == "route":
        from bot.ai import _ask_key

        # «у метро, остальное неважно» на вопрос про район — это ответ про район, не про дорогу
        if parse_district(raw) or _ask_key(_last_bot_text(history)) == "district":
            life = None
    if life and life.escalate:
        return (
            [life.line],
            None,
            _craft_state(sess, step="handed_off", path=f"smart:rule/life/{life.kind}", esc=True),
            True,
        )

    bundled = _bundle_reply(sess, raw)
    if bundled:
        side = _side_fact(raw)
        if side and bundled[0] and side.lower()[:20] not in bundled[0][0].lower():
            bundled = ([f"{side} {bundled[0][0]}", *bundled[0][1:]], *bundled[1:])
        return bundled

    if _booking_payload(raw):
        return None
    if _mentions_known_apartment(raw, sess):
        return None

    if life and not life.escalate:
        if life.stop:
            state = _craft_state(sess, step="done", path=f"smart:rule/life/{life.kind}")
            state["handed_off"] = 1
            ctx = dict(state.get("context") or {})
            ctx["stopped"] = True
            state["context"] = ctx
            return [life.line], None, state, False
        life_line = life.line
        if life.kind == "discount":
            life_line += " Плюс баллы при прямой брони, 500 за регистрацию."
        if life.kind == "long" and re.search(r"(?i)месяц|полгода", raw):
            # срок гость уже назвал — не переспрашиваем «на сколько»
            life_line = "Да, можно и на месяц, условия скажет менеджер."
            if not sess.get("dates"):
                life_line += " С какого числа?"
        heard_life = _overlay_heard(sess, raw)  # «день рождения, человек 6» — гостей запомнить
        if life.ask and not life_line.endswith("?"):
            line, ask = _with_one_forward(life_line, heard_life, history)
        else:
            line, ask = life_line, ("dates" if life_line.endswith("?") else "")
        step = {
            "dates": "await_dates",
            "guests": "await_guests",
            "district": "await_district",
            "returning": "await_returning",
        }.get(ask, str(sess.get("step") or "await_dates"))
        return (
            [line],
            BUTTONS.get(ask) if ask else None,
            _craft_state(heard_life, step=step, path=f"smart:rule/life/{life.kind}"),
            False,
        )

    holiday = parse_dates(raw)
    if holiday and re.search(r"(?i)собак|кошк|питом", raw):
        if re.search(r"(?i)собак", raw):
            pet_word, pet_slot = "собакой", "собака"
        elif re.search(r"(?i)кошк", raw):
            pet_word, pet_slot = "кошкой", "кошка"
        else:
            pet_word, pet_slot = "питомцем", "питомец"
        shown = holiday[:1].upper() + holiday[1:]
        if holiday == "ещё не определились":
            # «пока не знаем, с собакой можно?» — эхо «Ещё не определились» звучит как анкета
            line = (
                f"С {pet_word} можно, но зависит от квартиры — "
                f"после выбора района отмечу в списке свободных."
            )
        else:
            line = (
                f"{shown}, с {pet_word} можно, но зависит от квартиры — "
                f"отмечу в списке свободных."
            )
        guests_now = parse_guests(raw) or str(sess.get("guests") or "")
        buttons = None
        if not (sess.get("district") or parse_district(raw)):
            line = f"{line} Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?"
            step = "await_district"
            buttons = None
        elif not guests_now:
            line = f"{line} Сколько вас будет?"
            step = "await_guests"
            buttons = BUTTONS.get("guests")
        else:
            step = str(sess.get("step") or "await_returning")
        state = _craft_state(
            sess,
            step=step,
            path="smart:rule/pet-dates",
            ctx_extra={"pets": pet_slot},
        )
        state["dates"] = holiday
        if guests_now:
            state["guests"] = guests_now
        return [line], buttons, state, False

    if not parse_dates(raw) and not parse_guests(raw):
        for rx, line in _SIDE_RULES:
            if rx.search(raw) and re.search(r"(?i)\?|есть|можно|правда|хоч|сделать|устро", raw):
                fact_line, ask = _with_one_forward(line, _overlay_heard(sess, raw), history)
                return (
                    [fact_line],
                    BUTTONS.get(ask) if ask else None,
                    _craft_state(sess, step=str(sess.get("step") or "await_dates"), path="smart:rule/side"),
                    False,
                )
    # ранний заезд + поздний выезд в одном вопросе — один ответ, без склейки двух фраз
    if _EARLY_CHECKIN_RE.search(raw) and _LATE_CHECKOUT_RE.search(raw):
        hits = [_EARLY_LATE_LINE]
    else:
        hits = [fact for rx, fact in _NAIVE_FACTS if rx.search(raw)]
    for fact in hits[:1]:
        heard = _overlay_heard(sess, raw)
        # «а есть парковка? и во сколько заезд?» — ответить на оба вопроса
        if len(hits) > 1 and hits[0].split()[0] != hits[1].split()[0]:  # «Залог…» + «Залог…» не склеиваем
            fact = f"{hits[0]} {hits[1]}"
        thinking = bool((sess.get("context") or {}).get("thinking"))
        if _META_FACT_RE.search(fact) or thinking:
            # гость ещё думает (скрин 56: залог → «Подскажите даты?») — отвечаем на вопрос, без анкеты
            line, ask = fact, ""
        else:
            line, ask = _with_one_forward(fact, heard, history)
        step = {
            "dates": "await_dates",
            "guests": "await_guests",
            "district": "await_district",
            "returning": "await_returning",
        }.get(ask, str(heard.get("step") or sess.get("step") or "await_dates"))
        extra: dict[str, Any] = {}
        low_fact = fact.lower()
        ctx_now = dict(sess.get("context") or {})
        recent_bot = [str(h.get("text") or "") for h in (history or [])[-16:] if (h.get("role") or "") == "bot"]
        has_cards = bool(ctx_now.get("offers")) and any(re.search(r"(?m)^1\)", t) for t in recent_bot)
        pet_fact = "питом" in low_fact or "животн" in low_fact
        if has_cards and pet_fact:
            pet_word = "собакой" if re.search(r"(?i)собак", raw) else "кошкой" if re.search(r"(?i)кошк", raw) else "питомцем"
            offers = [str(x) for x in (ctx_now.get("offers") or []) if x]
            line = _pets_answer(raw, {"pets": pet_word}, offers=offers)
            notes = str(ctx_now.get("notes") or "").strip()
            if pet_word not in notes:
                extra["notes"] = (notes + "; " if notes else "") + f"с {pet_word}"
        if has_cards and ask in ("", "pick", "returning") and not sess.get("favorite") and not ctx_now.get("pick_nudged") and "?" not in line:
            line = f"{line.rstrip()} Что-то из вариантов приглянулось?"
            extra["pick_nudged"] = True
        if "парков" in low_fact:
            extra["parking"] = "уточнить"
        if pet_fact:
            if re.search(r"(?i)собак", raw):
                extra["pets"] = "собака"
            elif re.search(r"(?i)кошк", raw):
                extra["pets"] = "кошка"
            else:
                extra["pets"] = "питомец"
        return (
            [line],
            BUTTONS.get(ask) if ask else None,
            _craft_state(heard, step=step, path="smart:rule/naive", ctx_extra=extra),
            False,
        )

    # «3» после карточек «1) … 2) … 3) …» — это номер варианта, не число гостей
    # (и через пару вопросов про залог/собаку, если гостей уже знаем — скрин 24)
    recent_cards = any(
        re.search(r"(?m)^1\)", str(h.get("text") or ""))
        for h in (history or [])[-16:]
        if (h.get("role") or "") == "bot"
    )
    if re.fullmatch(r"\s*\d\s*[.!)]?\s*", raw) and (sess.get("context") or {}).get("offers") and (
        re.search(r"(?m)^1\)", _last_bot_text(history)) or (recent_cards and sess.get("guests"))
    ):
        return None
    said_guests = parse_guests(raw)
    said_district = parse_district(raw)
    said_dates = parse_dates(raw)
    bare_day = re.fullmatch(r"на (\d{1,2})", said_dates or "")
    if bare_day and said_guests and bare_day.group(1) == str(said_guests).strip():
        said_dates = None  # «человек 6» — гости, не дата
    if (said_guests or said_district) and not _pet_bits(raw) and (
        not said_dates or said_dates == "ещё не определились"
    ):
        heard = _overlay_heard(sess, raw)
        bits = []
        if said_guests:
            bits.append(_guest_phrase(said_guests, raw).capitalize())
        if said_district:
            bits.append(said_district)
        line = ", ".join(bits) + "."
        side = _side_fact(raw)
        if side:
            line = f"{side} {line}"
        if not heard.get("district"):
            line += " Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?"
            step = "await_district"
        elif not heard.get("dates"):
            line += " На какие даты смотрите?"
            step = "await_dates"
        elif not heard.get("guests"):
            # не оставляем голое «Центр.» — ведём к вместимости (и не копируем старый хвост 1:1)
            if heard.get("dates"):
                line = "Напишите, сколько вас будет — сверю свободные под вас."
            else:
                line += " Сколько вас будет?"
            step = "await_guests"
        else:
            if said_district and not side:
                # район уже есть + слоты заполнены — показать свободные, а не echo «Центр.»
                dates_now = str(heard.get("dates") or "").strip()
                if dates_now:
                    from bot.travelline import free_offer_cards

                    cards, names = free_offer_cards(
                        dates_now,
                        _guest_need(heard.get("guests")),
                        district=str(heard.get("district") or said_district),
                    )
                    if cards:
                        return (
                            [cards],
                            None,
                            _craft_state(
                                heard,
                                step="await_returning",
                                path="smart:rule/heard-cards",
                                ctx_extra={
                                    "tl_offers": names,
                                    "offers": names,
                                    "tl_dates": dates_now,
                                },
                            ),
                            False,
                        )
                return _DELEGATE
            step = str(sess.get("step") or "await_returning")
        return (
            [line],
            BUTTONS.get({"await_dates": "dates", "await_guests": "guests", "await_district": "district"}.get(step) or ""),
            _craft_state(heard, step=step, path="smart:rule/heard"),
            False,
        )
    return None


def _collapse_voice(msgs: list[str], history: list[dict[str, Any]] | None) -> list[str]:
    from bot.reply_guard import collapse_repeat_asks

    bots = [
        str(h.get("text") or "")
        for h in (history or [])
        if (h.get("role") or "") == "bot" and str(h.get("text") or "").strip()
    ]
    return collapse_repeat_asks(msgs, "\n".join(bots[-2:]))


async def smart_reply(
    settings: Settings,
    engine: Engine,
    sess: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """LLM-first ход. None → caller falls back to script engine."""
    if not smart_enabled():
        return None
    text = (text or "").strip()
    if not text:
        return None
    if is_stop_request(text):
        return None  # engine/stop-list

    crafted = _craft_early_raw(sess, text, history)
    if crafted is _DELEGATE:
        return None
    if crafted:
        return crafted

    # чистое приветствие — без сразу вопроса про даты
    if re.fullmatch(
        r"(?i)\s*(привет|здравствуйте|добрый\s+день|доброе\s+утро|добрый\s+вечер|"
        r"хай|здарова|hello|hi)[.!…]?\s*",
        text,
    ):
        return (
            ["Здравствуйте! Чем могу вам помочь?"],
            BUTTONS.get("greeting"),
            {
                "step": "await_intent",
                "context": {
                    **(sess.get("context") or {}),
                    "smart": True,
                    "greeted": True,
                    "reply_path": "smart:rule/hello",
                },
            },
            False,
        )

    # погода — не выдумываем факты; один пузырь (чтобы dedupe не срезал «к делу»)
    if re.search(r"(?i)\bпогод|\bградус|\bдожд|\bснег\b", text) and not re.search(
        r"(?i)квартир|апартамент|заезд|дат", text
    ):
        step = str(sess.get("step") or "await_dates")
        slots0 = _session_slots(sess)
        if slots0.get("dates"):
            steer = "Если по проживанию ещё что-то уточнить — напишите, продолжим."
            ask_for = ""
        else:
            steer = "Если смотрите квартиру — напишите удобные даты, продолжим."
            ask_for = "dates"
            step = "await_dates"
        return (
            [
                "Погоду здесь не проверяю — лучше глянуть в приложении 🙂 " + steer,
            ],
            _buttons_for(step, ask_for),
            {
                "step": step,
                "context": {**(sess.get("context") or {}), "smart": True, "reply_path": "smart:rule/weather"},
            },
            False,
        )

    # детская кроватка / стульчик — короткий факт, без сброса слотов
    if re.search(r"(?i)кроватк|стульчик", text) and not re.search(
        r"(?i)позовите|менеджер", text
    ):
        slots0 = _session_slots(sess)
        offers0 = [str(x) for x in ((sess.get("context") or {}).get("offers") or []) if x]
        if offers0:
            q = (
                f"Кроватку/стульчик уточню по выбранной квартире — в большинстве есть, "
                f"точнее подтвердит менеджер. Какой вариант ближе — номер или название "
                f"(например, 1 — «{offers0[0]}»)?"
            )
            ask = "pick"
        else:
            q = (
                "Кроватку/стульчик уточню по выбранной квартире — в большинстве есть, "
                "точнее подтвердит менеджер. " + (
                    _next_question("", slots0)
                    or "Подскажите, пожалуйста, на какие даты планируете поездку?"
                )
            )
            ask = ""
        step = _infer_step(slots0, ask, offered=bool(offers0), esc=False)
        return (
            [q],
            _buttons_for(step, ask),
            {
                "step": step,
                "context": {**(sess.get("context") or {}), "smart": True, "kids": "кроватка"},
                **{k: slots0[k] for k in ("dates", "guests", "district") if slots0.get(k)},
            },
            False,
        )

    # грубость — короткое извинение + конкретный следующий шаг
    if re.search(r"(?i)\bтуп|\bидиот|\bдур[ае]|\bхер|\bблин\b.*ответ", text) and not re.search(
        r"(?i)позовите|менеджер|жалоб", text
    ):
        q, ask = _forward_question(sess, history)
        from bot.ai import _ask_key

        if not sess.get("dates") and _ask_key(_last_bot_text(history)) == "dates":
            q, ask = "Жду от вас даты.", "dates"
        step = {
            "dates": "await_dates",
            "guests": "await_guests",
            "district": "await_district",
            "returning": "await_returning",
        }.get(ask, str(sess.get("step") or "await_dates"))
        return (
            [f"Извините, если не так поняла. {q}"],
            BUTTONS.get(ask) if ask else None,
            _craft_state(sess, step=step, path="smart:rule/rude"),
            False,
        )

    # выбор «давайте 1» / номер из списка — без повторной рассылки карточек
    try:
        from bot.catalog import parse_offer_pick, find_by_name_fuzzy
    except Exception:
        parse_offer_pick = None  # type: ignore
        find_by_name_fuzzy = None  # type: ignore
    prev_offers = [str(x) for x in ((sess.get("context") or {}).get("offers") or []) if x]
    pick_n = parse_offer_pick(text) if parse_offer_pick else None
    if pick_n and prev_offers and 1 <= pick_n <= len(prev_offers):
        name = prev_offers[pick_n - 1]
        return _comfort_after_pick(sess, name, offers=prev_offers)
    # имя квартиры текстом — тоже выбор, не LLM «подойдёт?»
    try:
        from bot.apartments_map import resolve_apartment_title

        named = resolve_apartment_title(text, offers=prev_offers)
    except Exception:
        named = ""
    if named and (
        re.fullmatch(r"\s*[«»\"']?[\w\- ]{2,40}[»\"']?\s*", text or "")
        or _CHOSE_FLAT_RE.search(text or "")
    ):
        return _comfort_after_pick(sess, named, offers=prev_offers or [named])

    slots_now = _session_slots(sess)
    # короткий релевантный каталог (зона + вместимость), не весь список
    catalog = catalog_brief_for_llm(
        limit=8,
        district=str(slots_now.get("district") or "") or None,
        guests=str(slots_now.get("guests") or "") or None,
    )
    # RAG: только релевантные факты (FAQ/карта/life/policy), не слепой dump FAQ
    try:
        from bot.rag import rag_context_for_llm

        rag_block = rag_context_for_llm(
            text,
            district=str(slots_now.get("district") or "") or None,
            favorite=str(slots_now.get("favorite") or "") or None,
            guests=str(slots_now.get("guests") or "") or None,
        )
    except Exception:
        logger.exception("rag context failed")
        rag_block = ""
    if not rag_block:
        # fallback на старый краткий FAQ, если RAG выключен/пуст
        rag_block = "FAQ (кратко):\n" + faq_facts_for_llm(limit=12)
    try:
        from bot.examples import similar_examples

        examples = similar_examples(text)
    except Exception:
        examples = ""
    try:
        from bot.ideal_manager import persona_for_llm, similar_style

        persona = persona_for_llm()
        style = similar_style(text)
    except Exception:
        logger.exception("ideal manager context failed")
        persona = ""
        style = ""
    system = (
        f"{_prompt()}\n\n"
        + (f"{persona}\n\n" if persona else "")
        + f"Сессия (слоты): {json.dumps(slots_now, ensure_ascii=False)}\n\n"
        + f"{rag_block}\n\n"
        + f"Каталог (релевантный срез, zone=center|calm|other):\n{catalog}\n\n"
        + (f"{examples}\n\n" if examples else "")
        + (f"{style}\n\n" if style else "")
        + "Правила ответа: messages — ровно одна фраза без вопроса, если вопрос уже в ask_next. "
        "Без сводки слотов, без «записала», без хвоста «если что пишите». "
        "Карточки и следующий вопрос система добавит сама. "
        "Факты (цены, метро, адрес, залог, животные, парковка) — только из RAG и каталога. "
        "Нет факта — uncertain=true, не выдумывай. "
        "Не пиши «центр» для zone!=center. "
        "Пиши как идеальный живой менеджер: тепло, на «вы», без повторов."
    )
    hist: list[dict[str, str]] = []
    for h in history[-6:]:
        role = "assistant" if h.get("role") == "bot" else "user"
        hist.append({"role": role, "content": (h.get("text") or "")[:280]})
    user_payload = (
        f"Сообщение гостя: {text[:500]}\n"
        "Верни один JSON по схеме."
    )
    try:
        result = await _call_understand(
            system, [*hist, {"role": "user", "content": user_payload}]
        )
    except Exception:
        logger.exception("smart understand failed")
        return None
    if not result:
        logger.info("smart LLM empty → script fallback")
        return None
    raw, via = result
    data = _parse_json(raw)
    if not data:
        logger.warning("smart bad json via=%s", via)
        return None

    intent = str(data.get("intent") or "looking").lower()
    if intent == "stop" or is_stop_request(text):
        return None

    slots = _normalize_slots(data.get("slots"), text, sess)
    esc = bool(data.get("escalate") or data.get("uncertain") or intent in ("escalate", "book"))
    from bot.faq import _POLITE_ANSWER_RE, _REAL_HANDOFF_RE

    polite_manager = bool(_POLITE_ANSWER_RE.search(text) and not _REAL_HANDOFF_RE.search(text))
    if re.search(
        r"(?i)позовите|менеджер|оператор|жалоб|ужас|кошмар|готов[аы]?\s*брон",
        text,
    ) and not polite_manager:
        esc = True
    if polite_manager:
        # «Уважаемый менеджер, ответьте мне» — ответить самой (аудит S1/S10)
        esc = False
    if esc and intent in ("looking", "multi", "correction", "faq", "chitchat") and not re.search(
        r"(?i)позовите|менеджер|оператор|жалоб|ужас|кошмар|готов[аы]?\s*брон",
        text,
    ):
        if data.get("uncertain") and not data.get("escalate"):
            esc = False
        if intent in ("looking", "multi", "correction") and not re.search(
            r"(?i)брон|позовите|менеджер", text
        ):
            esc = False
    if esc and not re.search(
        r"(?i)позовите|менеджер|оператор|жалоб|ужас|кошмар|брон",
        text,
    ):
        if data.get("escalate") and re.search(r"(?i)туп|идиот|дур|блин|хер", text):
            esc = False

    ask_next = str(data.get("ask_next") or "")
    ask_l_pre = ask_next.strip().lower()
    if ask_l_pre == "dates" and slots.get("dates"):
        ask_next = ""
    elif ask_l_pre == "guests" and slots.get("guests"):
        ask_next = ""
    elif ask_l_pre == "district" and slots.get("district"):
        ask_next = ""
    attach = bool(data.get("attach_offers"))
    offer_names = [str(x) for x in (data.get("offer_names") or []) if x]
    reasons_raw = data.get("offer_reasons") if isinstance(data.get("offer_reasons"), dict) else {}
    reasons: dict[str, str] = {}
    for k, v in reasons_raw.items():
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v if x)
        reasons[str(k)] = str(v)[:120]

    prev_sess = {
        "dates": sess.get("dates") or "",
        "guests": sess.get("guests") or "",
        "district": sess.get("district") or "",
    }
    guests_changed = bool(
        slots.get("guests")
        and str(slots.get("guests")) != str(prev_sess.get("guests") or "")
    )
    is_correction = intent == "correction" or bool(
        re.search(r"(?i)не\s+\d|\bа\s+\d+\s*человек|исправ|вместо\s+\d", text)
        and guests_changed
    )
    asked_pets = bool(re.search(r"(?i)собак|кошк|питом|животн|можно с ", text))
    if asked_pets and not slots.get("pets"):
        slots["pets"] = "собака" if re.search(r"(?i)собак", text) else "питомец"

    have_core = bool(slots.get("dates") and slots.get("guests") and slots.get("district"))
    had_offers = bool(prev_offers)
    need = _guest_need(slots.get("guests"))

    # правка гостей: если текущий набор всё ещё вмещает — не слать карточки снова
    keep_offers_no_resend = False
    if is_correction and guests_changed and had_offers:
        from bot.catalog import find_by_name_fuzzy, fits_district

        still_ok: list[dict[str, Any]] = []
        for n in prev_offers:
            hit = find_by_name_fuzzy(str(n))
            if (
                hit
                and _fits_capacity(hit, need)
                and fits_district(hit, str(slots.get("district") or ""))
            ):
                still_ok.append(hit)
        if len(still_ok) == len(prev_offers) and still_ok:
            keep_offers_no_resend = True
            offered_objs = still_ok
            offered_names = [o["name"] for o in still_ok]
            district_note = ""
            wants = False
            attach = False
        else:
            wants = True
            offered_objs, offered_names, district_note = [], list(prev_offers), ""
    else:
        wants = attach or (
            intent in ("looking", "multi", "recommend") and have_core and not had_offers
        )
        if re.search(r"(?i)вариант|подбер|покаж|пришли|скин", text) and slots.get("guests"):
            wants = True
        # гости ещё не названы — один вопрос, без простыни карточек
        if wants and not slots.get("guests") and not re.search(
            r"(?i)вариант|подбер|покаж|пришли|скин", text
        ):
            wants = False
        if intent in ("apartment_q", "faq", "chitchat") and not attach:
            wants = False
        if intent == "apartment_q" and slots.get("favorite"):
            wants = False
        if had_offers and re.search(
            r"(?i)кроват|wifi|вайф|парков|заезд|рядом|метро\b", text
        ):
            wants = False
        offered_objs, offered_names, district_note = [], list(prev_offers), ""

    from bot.reply_guard import guest_defers_district, is_open_district

    open_district = is_open_district(str(slots.get("district") or "")) or guest_defers_district(
        text
    )

    if wants and not esc and not keep_offers_no_resend:
        # «сами выберите» — не брать квартиры, которые модель привязала к чужому району
        names_for_pick = [] if open_district else offer_names
        if is_correction and guests_changed and prev_offers and not open_district:
            offered_objs, offered_names, district_note = _resolve_offers(
                prev_offers + names_for_pick, slots, limit=3
            )
        else:
            offered_objs, offered_names, district_note = _resolve_offers(
                names_for_pick, slots, limit=3
            )
        if open_district and offered_objs and not district_note:
            district_note = "Район на ваш выбор — свободные по календарю на ваши даты:"
        attach = bool(offered_objs)

    calendar_note = ""
    calendar_checked = False
    tl_card_names: list[str] = []
    from bot.engine import _dates_with_nights

    phrase = ""
    for blob in [text, str(slots.get("dates") or ""), str(sess.get("dates") or "")]:
        phrase = _dates_with_nights(blob) or ""
        if phrase:
            break
    if not phrase:
        for h in history or []:
            if (h.get("role") or "") in ("guest", "user"):
                phrase = _dates_with_nights(str(h.get("text") or "")) or ""
                if phrase:
                    break
    phrase = phrase or normalize_dates_phrase(str(slots.get("dates") or "")) or str(slots.get("dates") or "")
    if phrase:
        slots["dates"] = phrase
    from bot.travelline import (
        availability_reply,
        free_offer_cards,
        same_title,
        search_stays,
        stay_span,
    )

    span = stay_span(phrase)
    # даты + гости + район (или «без разницы») → сначала календарь TravelLine, не каталог
    if (
        span
        and not esc
        and slots.get("guests")
        and (slots.get("district") or open_district)
        and (wants or (have_core and not had_offers))
        and not keep_offers_no_resend
    ):
        dist_for_tl = "" if open_district else str(slots.get("district") or "")
        cards, tl_card_names = free_offer_cards(
            phrase,
            _guest_need(slots.get("guests")),
            district=dist_for_tl,
        )
        if cards and tl_card_names:
            calendar_note = cards
            calendar_checked = True
            offered_objs, offered_names, district_note = [], tl_card_names, ""
            attach = False  # карточки уже в calendar_note
            wants = False
        elif not open_district and not cards:
            # именованный район без свободных — не подмешивать чужие из каталога
            label = str(slots.get("district") or "").strip() or "этом районе"
            calendar_note = (
                f"В районе «{label}» на эти даты по календарю свободных квартир нет. "
                "Могу посмотреть другой район или подключить менеджера."
            )
            calendar_checked = True
            offered_objs, offered_names, district_note = [], [], ""
            attach = False
            wants = False

    if span and not esc and not calendar_note:
        stays = search_stays(span[0], span[1], _guest_need(slots.get("guests")))
        if stays is not None:
            calendar_checked = True
            if offered_objs:
                kept = [o for o in offered_objs if any(same_title(str(o.get("name") or ""), s) for s in stays)]
                prices = {}
                for stay in stays:
                    for obj in kept:
                        if same_title(str(obj.get("name") or ""), stay) and stay.price_night:
                            prices[str(obj.get("name") or "")] = stay.price_night
                for obj in kept:
                    price = prices.get(str(obj.get("name") or ""))
                    if price:
                        obj["price_night"] = price
                offered_objs = kept
                offered_names = [str(o.get("name") or "") for o in kept]
                attach = bool(kept)
                if kept and district_note and (
                    "не подтвержда" in district_note.lower() or "на ваш выбор" in district_note.lower()
                ):
                    district_note = "Свободны по календарю на эти даты:"
            if not offered_objs:
                place_sess = dict(sess)
                if slots.get("district"):
                    place_sess["district"] = slots["district"]
                place = "" if open_district else _guest_place_phrase(text, place_sess)
                calendar_note = availability_reply(
                    phrase,
                    _guest_need(slots.get("guests")),
                    place,
                    text=text,
                    next_step=False,
                ) or ""

    allowed_prices: set[int] = set()
    for o in offered_objs:
        p = o.get("price_night")
        if isinstance(p, int) and p > 0:
            allowed_prices.add(p)
    try:
        from bot.catalog import DEFAULT_PATH, _connect, _row_public

        con = _connect(DEFAULT_PATH)
        if con:
            try:
                for r in con.execute("SELECT price_night FROM objects WHERE price_night IS NOT NULL"):
                    try:
                        allowed_prices.add(int(r[0]))
                    except Exception:
                        pass
            finally:
                con.close()
    except Exception:
        pass

    greeted = already_greeted(sess) or bool(history)
    raw_msgs = [_msg_text(x) for x in (data.get("messages") or [])]
    raw_msgs = [x for x in raw_msgs if x]
    raw_msgs = _sanitize_messages(raw_msgs, allowed_prices=allowed_prices, greeted=greeted)

    # v9.4: живой LLM insight / human-ack вместо робо-сводки «Записала: a, b, c»
    lead = ""
    with_cards = False  # уточним после wants
    if keep_offers_no_resend and slots.get("guests"):
        lead = (
            f"Поняла, {format_guests_phrase(slots['guests'])}. "
            f"Все текущие варианты вмещают {need} — какой ближе, номер или название?"
        )
        ask_next = "pick"
    elif is_correction and guests_changed and slots.get("guests"):
        lead = f"Поняла, {format_guests_phrase(slots['guests'])}."
    else:
        if asked_pets:
            lead = _pets_answer(
                text,
                slots,
                offers=[str(x) for x in ((sess.get("context") or {}).get("offers") or []) if x],
            )
        elif calendar_note:
            lead = calendar_note
        with_cards = bool(attach and offered_objs)
        if not lead:
            insight = _pick_llm_insight(
                raw_msgs, intent=intent, with_cards=with_cards
            )
            if insight:
                lead = insight
            elif intent not in ("faq", "apartment_q"):
                ack = _human_ack(text, slots, prev_sess, asked_pets=False)
                if ack:
                    lead = ack

    hist_blob = " ".join(
        str(h.get("text") or "") for h in history[-10:] if (h.get("role") or "") == "bot"
    ).lower()
    if (
        re.search(r"(?i)реб[её]н|дет(и|ей)|младен", text)
        and not asked_pets
        and not re.search(r"(?i)с детьми можно|кроватку/стульчик", hist_blob)
        and "с детьми можно" not in (lead or "").lower()
    ):
        kids_note = "С детьми можно — кроватку уточню по квартире."
        lead = f"{kids_note} {lead}".strip() if lead else kids_note

    # FAQ / chitchat / добор смысла — если lead ещё пуст и нет карточек
    if not lead and not (attach and offered_objs) and not keep_offers_no_resend:
        lead = _pick_llm_insight(raw_msgs, intent=intent, with_cards=False)
    if not lead and not (attach and offered_objs) and not keep_offers_no_resend:
        raw_blob = " ".join(raw_msgs)
        if _BRUSH_OFF_RE.search(raw_blob) or intent == "chitchat":
            lead = _nudge_line(sess)[0]
        else:
            lead = ""
    if lead and _BRUSH_OFF_RE.search(lead):
        lead = _nudge_line(sess)[0]

    msgs: list[str] = []
    if lead:
        from bot.reply_guard import smooth_speech

        lead = smooth_speech(lead)
    if lead:
        msgs.append(lead)

    q_folded = False
    if attach and offered_objs and not esc and not keep_offers_no_resend:
        set_changed = set(offered_names) != set(prev_offers) if had_offers else True
        # та же подборка уже ушла в прошлом пузыре — не слать карточки второй раз
        if offered_names and hist_blob and all(
            n.lower() in hist_blob for n in offered_names
        ):
            set_changed = False
        if set_changed:
            ask_next = ask_next or "returning"
            foot = None
            ask_l0 = (ask_next or "").strip().lower()
            if ask_l0 == "returning" and not slots.get("returning"):
                foot = _next_question("returning", slots)
                q_folded = bool(foot)
            elif ask_l0 == "pick":
                foot = "Если подходит, напишите номер (1–3) или название."
            if calendar_checked:
                foot = (
                    f"{foot} Свободны по календарю на эти даты."
                    if foot
                    else "Свободны по календарю на эти даты."
                )
            card_lead = district_note or None
            card_blob = _cards_with_reasons(
                offered_objs,
                reasons,
                footer=foot,
                lead=card_lead,
                district=str(slots.get("district") or ""),
                guests=str(slots.get("guests") or ""),
            )
            # 1–2 пузыря: если уже есть lead — карточки вторым; иначе один блок
            if msgs:
                msgs.append(card_blob)
            else:
                msgs = [card_blob]
        else:
            ask_next = ask_next or "pick"

    if intent == "apartment_q" and slots.get("favorite"):
        try:
            from bot.catalog import find_by_name_fuzzy, format_card

            hit = find_by_name_fuzzy(str(slots["favorite"]))
            if hit:
                msgs = [f"По «{hit['name']}»:\n{format_card(hit)}"]
                q_folded = False
                ask_next = ask_next or "pick"
        except Exception:
            pass

    no_cards = not offered_objs and not prev_offers
    if (ask_next or "").strip().lower() == "pick" and no_cards:
        ask_next = "returning" if not slots.get("returning") else "stay"
    q = None if q_folded or keep_offers_no_resend else _next_question(ask_next, slots)
    if q and no_cards:
        from bot.reply_guard import question_key as _qk

        if _qk(q) == "pick":
            if not slots.get("returning"):
                ask_next = "returning"
                q = _next_question("returning", slots)
            else:
                ask_next = "stay"
                q = None
    blob = " ".join(msgs).lower()
    ask_l = (ask_next or "").strip().lower()
    already_next = q_folded or keep_offers_no_resend
    # не дублировать тот же вопрос, если lead уже спрашивает даты/гостей/…
    same_ask = bool(
        re.search(
            r"(?i)на какие даты|когда.{0,20}планир|даты планир|даты смотр|"
            r"сколько (будет )?гост|сколько человек|на сколько человек|"
            r"были у нас|впервые|напишите номер|какой ближе|какой вариант",
            blob,
        )
    )
    if ask_l in ("returning", "") and re.search(r"были у нас|впервые", blob):
        already_next = True
    elif ask_l == "dates" and re.search(
        r"(?i)на какие даты|когда.{0,20}планир|даты смотр|даты планир", blob
    ):
        already_next = True
    elif ask_l == "guests" and re.search(
        r"(?i)сколько будет гост|сколько вас|сколько человек|на сколько человек", blob
    ):
        already_next = True
    elif ask_l == "district" and re.search(r"район|центр или", blob):
        already_next = True
    elif ask_l == "pick" and re.search(r"номер \(1|напишите номер|название|какой ближе", blob):
        already_next = True
    elif ask_l == "book" and re.search(r"подключаю|менеджер", blob):
        already_next = True
    elif same_ask:
        already_next = True
    if q and not already_next and len(msgs) < 2:
        if msgs and attach and offered_objs:
            msgs[-1] = msgs[-1].rstrip() + "\n\n" + q
        else:
            msgs.append(q)
    elif not already_next and msgs and len(msgs) < 2 and not re.search(
        r"\?|подскажите|были у|впервые|подключаю|напишите номер|какой ближе",
        msgs[-1],
        flags=re.I,
    ):
        fallback_q = _next_question("", slots) or (
            "Подскажите, пожалуйста, чем ещё помочь по квартире?"
        )
        from bot.reply_guard import question_key

        if fallback_q and no_cards and question_key(fallback_q) == "pick":
            fallback_q = None
        if fallback_q and not esc:
            msgs.append(fallback_q)

    if len(msgs) >= 2 and re.fullmatch(
        r"(?i)\s*хорошо,?\s*поняла[.!?🙂\s]*", msgs[0] or ""
    ):
        msgs = [m for m in msgs[1:] if (m or "").strip()] or msgs[-1:]
    msgs = _cap_msgs(msgs, 2)
    msgs = _collapse_voice(msgs, history)

    # LLM выбрал квартиру / escalate на бронь — не «подойдёт?» и не сразу менеджер без сверки
    fav_now = str(slots.get("favorite") or sess.get("favorite") or "").strip()
    if fav_now and not esc:
        ask_l0 = (ask_next or "").strip().lower()
        if ask_l0 in ("pick", "book", "stay", "none", "") or re.search(
            r"(?i)подойд|хороший выбор|уточнит детали|документы для брони|вариант ближе",
            " ".join(msgs),
        ):
            return _comfort_after_pick(
                {**sess, **{k: slots.get(k) or sess.get(k) for k in ("dates", "guests", "district", "returning")}},
                fav_now,
                offers=offered_names or prev_offers,
            )
    if esc and fav_now:
        return _comfort_after_pick(
            {**sess, **{k: slots.get(k) or sess.get(k) for k in ("dates", "guests", "district", "returning")}},
            fav_now,
            offers=offered_names or prev_offers,
        )

    if esc:
        if not any("менеджер" in m.lower() or "коллег" in m.lower() for m in msgs):
            msgs.append(
                HANDOFF_LINE
            )
            msgs = _cap_msgs(msgs, 2)
            msgs = _collapse_voice(msgs, history)
        updates = _build_updates(
            sess, slots, offered_names, step="handed_off", esc=True, via=via
        )
        logger.info("smart escalate via=%s intent=%s path=smart:%s", via, intent, via)
        return msgs, None, updates, True

    step = _infer_step(slots, ask_next, offered=bool(offered_names), esc=False)
    updates = _build_updates(sess, slots, offered_names, step=step, esc=False, via=via)
    if tl_card_names:
        ctx = dict(updates.get("context") or {})
        ctx["tl_offers"] = list(tl_card_names)
        ctx["offers"] = list(tl_card_names)
        if phrase:
            ctx["tl_dates"] = phrase
        shown = list(dict.fromkeys([str(x) for x in (ctx.get("tl_shown") or [])] + list(tl_card_names)))
        ctx["tl_shown"] = shown
        updates["context"] = ctx
    buttons = _buttons_for(step, ask_next)
    logger.info(
        "smart ok via=%s intent=%s step=%s offers=%s path=smart:%s",
        via,
        intent,
        step,
        offered_names,
        via,
    )
    return msgs, buttons, updates, False



def _build_updates(
    sess: dict[str, Any],
    slots: dict[str, Any],
    offered_names: list[str],
    *,
    step: str,
    esc: bool,
    via: str | None = None,
) -> dict[str, Any]:
    ctx = dict(sess.get("context") or {})
    for key in ("budget", "pets", "kids", "parking", "prefs"):
        if slots.get(key):
            ctx[key] = slots[key]
    if offered_names:
        ctx["offers"] = offered_names
    ctx["smart"] = True
    if via:
        ctx["reply_path"] = f"smart:{via}"
    else:
        ctx.setdefault("reply_path", "smart")
    upd: dict[str, Any] = {"step": step, "context": ctx}
    for key in ("dates", "guests", "district", "returning", "favorite"):
        if slots.get(key):
            upd[key] = slots[key]
    if esc:
        upd["handed_off"] = 1
        upd["step"] = "handed_off"
    return upd


async def script_fallback(
    settings: Settings,
    engine: Engine,
    sess: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool]:
    """Явный fallback на текущий script/FAQ пайплайн."""
    from bot.ai import _reply_core

    return await _reply_core(settings, engine, sess, text, history)


def log_smart_startup() -> None:
    """При старте бота — видно, что smart включён и какая модель первая."""
    enabled = smart_enabled()
    if not enabled:
        logger.info("smart brain OFF (SMART_BOT=%s FORCE_SCRIPT=%s)", SMART_BOT, os.getenv("HOME24_FORCE_SCRIPT"))
        return
    try:
        provs = load_providers(role="understand")
    except Exception:
        provs = []
    if not provs:
        logger.warning(
            "smart brain ON but no LLM providers — will fall back to script"
        )
        return
    logger.info(
        "smart brain ON · understand=%s/%s · fallback=%s",
        provs[0].name,
        provs[0].model,
        ", ".join(f"{p.name}/{p.model}" for p in provs[1:4]) or "—",
    )
