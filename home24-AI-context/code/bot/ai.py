"""Скрипт — основной путь. Минимальный LLM — только край (script miss)."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from bot.config import Settings
from bot.engine import (
    BUTTONS,
    Engine,
    extract_notes,
    is_refusal,
    is_stop_request,
    is_waiting_nudge,
    keyword_intent,
    match_button,
    parse_budget,
    parse_dates,
    parse_district,
    parse_guests,
    parse_nights,
    parse_objection,
    parse_returning,
    _step_ask,
)
from bot.llm import chat_completion, load_providers

logger = logging.getLogger("home24.ai")

USE_AI = os.getenv("USE_AI", "1").strip().lower() not in ("0", "false", "no", "off")

_SCRIPT_ONLY_STEPS = {
    "greeting",
    "done",
    "handed_off",
}

_FUNNEL_SOFT_FIRST = {
    "await_dates",
    "await_guests",
    "await_district",
    "await_returning",
    "await_favorite",
}

# LLM вообще не зовём на этих шагах — только скрипт / мягкий переспрос
_NO_LLM_STEPS = _FUNNEL_SOFT_FIRST | {
    "await_intent",
    "greeting",
    "browsing",
    "bonus",
    "looking",
}


def _is_noise(text: str) -> bool:
    """Ссылки, телефоны, токены, мусор — не ответ на шаг воронки."""
    t = (text or "").strip()
    if not t:
        return True
    if re.search(r"(?i)https?://|t\.me/|disk\.yandex|google\.com/|wa\.me/", t):
        return True
    if re.fullmatch(r"\+?\d[\d\s\-()]{8,}", t):
        return True
    if re.fullmatch(r"[0-9a-fA-F]{40,}", t):
        return True
    if len(t) > 220 and not parse_dates(t) and not parse_guests(t):
        return True
    return False


_ASK_VARIANTS: dict[str, tuple[str, ...]] = {
    "await_dates": (
        "Подскажите, пожалуйста, на какие даты планируете поездку?",
        "На какие даты примерно смотрите? Можно ориентировочно 🙂",
        "Когда планируете заезд?",
    ),
    "await_guests": (
        "Подскажите, пожалуйста, сколько будет гостей?",
        "Сколько человек заедет?",
        "Сколько вас будет?",
    ),
    "await_district": (
        "Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?",
        "Где комфортнее жить — ближе к центру или тише у метро?",
        "Район: центр или потише? 🙂",
    ),
    "await_returning": (
        "Вы у нас уже были или впервые?",
        "Вы у нас уже останавливались или это первый раз?",
    ),
    "await_favorite": (
        "Напишите, пожалуйста, название или адрес квартиры 🙂",
        "Какая квартира заинтересовала — название или адрес?",
    ),
    "await_intent": (
        "Подскажите, пожалуйста, на какие даты планируете поездку?",
        "На какие даты смотрите?",
        "Когда планируете заезд?",
    ),
    "browsing": (
        "Могу прислать пару вариантов на будущее — удобно?",
        "Прислать 2–3 квартиры просто посмотреть?",
    ),
}


def _ask_for(step: str, *, salt: str = "") -> str:
    opts = _ASK_VARIANTS.get(step) or ("Чем могу помочь по квартире? 🙂",)
    if len(opts) == 1:
        return opts[0]
    idx = sum(ord(c) for c in (salt or step)) % len(opts)
    return opts[idx]


def _soft_ack(step: str, *, noise: bool = False, apt: str | None = None, salt: str = "") -> list[str]:
    """Один тёплый ответ на «вы» — без канцелярита и без «не поймала»."""
    ask = _ask_for(step, salt=salt or apt or "")
    if apt:
        return [f"Да, «{apt}» есть 🙂 {ask}"]
    if noise:
        return [f"Хорошо, приняла 🙂 {ask}"]
    leads = ("Хорошо 🙂", "Приняла 🙂", "Отлично.")
    lead = leads[sum(ord(c) for c in (salt or step)) % len(leads)]
    return [f"{lead} {ask}"]

_ALLOWED_STEPS = {
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
}

_BAD = re.compile(
    r"(traceback|exception|error:|rate.?limit|openai|mistral|gemini|anthropic|"
    r"api[_ ]?key|status.?code|typeerror|valueerror|"
    r"TELEGRAM_|OPENAI_|SESSION=|sk-|mstrl_|xpl_|AQ\.)",
    re.I,
)

def _resume_questions() -> dict[str, tuple[str, str | None]]:
    from bot.phrases import district_choice_message

    ask_district = district_choice_message()
    return {
        "await_district": (ask_district, "district"),
        "await_dates": ("Подскажите, пожалуйста, на какие даты планируете поездку?", "dates"),
        "await_guests": ("Подскажите, пожалуйста, сколько будет гостей?", "guests"),
        "await_returning": ("Вы у нас уже были или впервые?", "returning"),
        "await_favorite": ("Напишите, пожалуйста, название или адрес квартиры 🙂", None),
        "browsing": ("Могу прислать пару вариантов на будущее — удобно?", "browsing"),
        "await_intent": (ask_district, "greeting"),
        "bonus": ("Могу прислать ссылку на бонусы или коротко рассказать — как удобнее?", "bonus"),
    }


_RESUME_Q = _resume_questions()

_EDGE_PROMPT_PATH = Path(__file__).with_name("edge_prompt.txt")
_EDGE_PROMPT_CACHE: str | None = None


def _edge_prompt() -> str:
    global _EDGE_PROMPT_CACHE
    if _EDGE_PROMPT_CACHE is not None:
        return _EDGE_PROMPT_CACHE
    try:
        _EDGE_PROMPT_CACHE = _EDGE_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        _EDGE_PROMPT_CACHE = (
            "Home24 менеджер, жен. род. Скрипт: район→даты→гости→календарь TravelLine→заявка. "
            "Без галлюцинаций. JSON only."
        )
    return _EDGE_PROMPT_CACHE


def extract_slots(text: str) -> dict[str, Any]:
    """Вытащить всё полезное из любого сообщения гостя (на любом шаге)."""
    if is_stop_request(text):
        return {}
    if is_refusal(text):
        return {}
    out: dict[str, Any] = {}
    d, g, dist, ret = parse_dates(text), parse_guests(text), parse_district(text), parse_returning(text)
    if d:
        out["dates"] = d
    if g:
        out["guests"] = g
    if dist:
        out["district"] = dist
    if ret:
        out["returning"] = ret
    nights = parse_nights(text)
    if nights:
        out["_nights"] = nights
        # если дат нет, но есть ночи — зафиксируем как подсказку в notes
        if not d:
            out.setdefault("_notes", "")
    budget = parse_budget(text)
    if budget:
        out["_budget"] = budget
    objection = parse_objection(text)
    if objection:
        out["_objection"] = objection
    notes = extract_notes(text)
    if notes:
        out["_notes"] = notes
    try:
        from bot.catalog import find_by_name_fuzzy

        hit = find_by_name_fuzzy(text)
        if hit and hit.get("name"):
            out["favorite"] = str(hit["name"])
    except Exception:
        pass
    return out


def _merge_notes(sess: dict[str, Any], notes: str) -> dict[str, Any]:
    if not notes:
        return dict(sess.get("context") or {})
    ctx = dict(sess.get("context") or {})
    prev = str(ctx.get("notes") or "")
    if notes and notes not in prev:
        ctx["notes"] = (prev + "; " + notes).strip("; ")[:400] if prev else notes
    # короткое prefs для отчёта
    tags = []
    low = notes.lower()
    if re.search(r"тих|шум|спокойн", low):
        tags.append("тихо/спокойно")
    if re.search(r"реб[её]н|семь|доч|сын", low):
        tags.append("с ребёнком/семьёй")
    if re.search(r"центр", low):
        tags.append("центр")
    if re.search(r"парк|машин|авто", low):
        tags.append("парковка")
    if tags:
        pref = ", ".join(tags)
        old = str(ctx.get("prefs") or "")
        if pref not in old:
            ctx["prefs"] = (old + "; " + pref).strip("; ")[:300] if old else pref
    return ctx


def _merge_slot_meta(sess: dict[str, Any], slots: dict[str, Any]) -> dict[str, Any]:
    """Бюджет / возражения / заметки → context для отчёта менеджеру."""
    ctx = dict(sess.get("context") or {})
    notes = str(slots.get("_notes") or "")
    if notes:
        ctx = _merge_notes({**sess, "context": ctx}, notes)
    budget = str(slots.get("_budget") or "").strip()
    if budget:
        ctx["budget"] = budget
    objection = str(slots.get("_objection") or "").strip()
    if objection:
        old = str(ctx.get("objection") or "")
        if objection not in old:
            ctx["objection"] = (old + "; " + objection).strip("; ")[:200] if old else objection
    return ctx


def _merge_prefs(sess: dict[str, Any], prefs: str) -> dict[str, Any]:
    ctx = dict(sess.get("context") or {})
    p = (prefs or "").strip()
    if not p:
        return ctx
    old = str(ctx.get("prefs") or "")
    if p not in old:
        ctx["prefs"] = (old + "; " + p).strip("; ")[:300] if old else p[:300]
    return ctx


def _clean(msgs: list[str]) -> list[str]:
    out = []
    for m in msgs:
        t = str(m).strip()
        if not t or _BAD.search(t):
            continue
        if t.startswith("{") or t.startswith("```"):
            continue
        if re.search(
            r"все (объекты|квартиры).{0,40}лифт|оборудованы лифт|гарантирую|"
            r"у нас нет квартир на|в каталоге все",
            t,
            re.I,
        ):
            continue
        if re.match(r"(?i)^(привет|здравствуй|добр(ый|ое|ого)|хорошего дня|пока)[\s,.!]", t):
            if len(t) < 80:
                continue
        t = re.sub(r"\*\*|__", "", t)
        t = re.sub(r"\(([аеиоуыя]|те|ём|ешь|ась)\)", "", t)
        t = re.sub(r"\bАнна\b", "", t)
        t = re.sub(r"\bчел\.", "человек", t)
        t = re.sub(r"  +", " ", t).strip(" ,!")
        if t:
            out.append(t)
    return out[:2]


def _session_blob(sess: dict[str, Any]) -> str:
    notes = ""
    try:
        notes = str((sess.get("context") or {}).get("notes") or "")[:80]
    except Exception:
        pass
    return (
        f"step={sess.get('step')}; "
        f"dates={sess.get('dates') or '—'}; guests={sess.get('guests') or '—'}; "
        f"district={sess.get('district') or '—'}; returning={sess.get('returning') or '—'}; "
        f"favorite={sess.get('favorite') or '—'}; notes={notes or '—'}"
    )


def _confirm_slots_lead(
    *,
    favorite: str = "",
    dates: str = "",
    guests: str = "",
    district: str = "",
    nights: str = "",
) -> str:
    """Короткое подтверждение уже понятых слотов — без повторных вопросов."""
    bits: list[str] = []
    if favorite:
        bits.append(f"«{favorite}»")
    if dates:
        bits.append(str(dates).replace("на ", ""))
    if nights:
        bits.append(f"{nights} ноч.")
    if guests:
        bits.append(f"{guests} гост.")
    if district:
        bits.append(str(district))
    if not bits:
        return "Хорошо 🙂"
    return "Поняла: " + ", ".join(bits) + "."


def _funnel_reply(engine: Engine, sess: dict[str, Any], text: str, slots: dict[str, Any]):
    """Протолкнуть воронку по всем найденным слотам сразу (любой шаг)."""
    step = sess.get("step") or "await_intent"
    merged = dict(sess)
    notes = str(slots.get("_notes") or "")
    nights = str(slots.get("_nights") or "").strip()
    clean_slots = {k: v for k, v in slots.items() if v and not str(k).startswith("_")}
    # бюджет/возражения/заметки — в context для отчёта (даже если шаг не сдвинулся)
    meta_ctx = _merge_slot_meta(sess, slots)
    if nights:
        meta_ctx = {**meta_ctx, "nights": nights}
    if meta_ctx != (sess.get("context") or {}):
        merged["context"] = meta_ctx

    # Квартира + слоты из одного сообщения — подтвердить и спросить только пробел
    fav = str(clean_slots.get("favorite") or merged.get("favorite") or "").strip()
    dates = str(clean_slots.get("dates") or merged.get("dates") or "").strip()
    guests = str(clean_slots.get("guests") or merged.get("guests") or "").strip()
    district = str(clean_slots.get("district") or merged.get("district") or "").strip()
    if fav and (
        clean_slots.get("favorite")
        or clean_slots.get("dates")
        or clean_slots.get("guests")
        or clean_slots.get("district")
    ):
        try:
            from bot.catalog import format_card, find_by_name_fuzzy

            hit = find_by_name_fuzzy(fav) or find_by_name_fuzzy(text)
        except Exception:
            hit = None
        if hit:
            fav = str(hit["name"])
            card = format_card(hit)
            lead = _confirm_slots_lead(
                favorite=fav, dates=dates, guests=guests, district=district, nights=nights
            )
            ctx = {**(merged.get("context") or {}), "offers": [fav]}
            base_upd = {
                "favorite": fav,
                "dates": dates,
                "guests": guests,
                "district": district,
                "context": ctx,
            }
            if dates and guests:
                ret = str(clean_slots.get("returning") or merged.get("returning") or "").strip()
                if ret in ("да", "нет"):
                    return engine.handle(
                        {**merged, **base_upd, "returning": ret, "step": "await_returning"},
                        ret,
                    )
                return (
                    [f"Да, есть 🙂\n{card}", f"{lead} Вы у нас уже были или впервые?"],
                    BUTTONS["returning"],
                    {**base_upd, "step": "await_returning"},
                    False,
                )
            if dates and not guests:
                return (
                    [f"Да, есть 🙂\n{card}", f"{lead} Сколько вас будет?"],
                    BUTTONS["guests"],
                    {**base_upd, "step": "await_guests"},
                    False,
                )
            if guests and not dates:
                return (
                    [f"Да, есть 🙂\n{card}", f"{lead} Подскажите даты — забронируем?"],
                    BUTTONS["dates"],
                    {**base_upd, "step": "await_dates"},
                    False,
                )
            return (
                [f"Да, есть 🙂\n{card}", f"{lead} Подскажите даты — забронируем?"],
                BUTTONS["dates"],
                {**base_upd, "step": "await_dates"},
                False,
            )

    # на шаге гостей голое «2» не должно затирать даты («на 2»)
    if step == "await_guests" and clean_slots.get("dates") and clean_slots.get("guests"):
        if re.fullmatch(r"на\s*[1-3]", str(clean_slots["dates"]).strip()):
            clean_slots.pop("dates", None)
    # на returning — район/даты из «тихий» не крутим воронку и не зовём LLM
    if step == "await_returning":
        from bot.catalog import parse_offer_pick, wants_variants

        if parse_offer_pick(text) is not None or clean_slots.get("returning") or wants_variants(text):
            pass  # ниже обычная логика
        elif clean_slots.get("district") or notes:
            ctx = _merge_notes(merged, notes or text.strip()[:120])
            if clean_slots.get("district"):
                pref = str(clean_slots["district"])
                old = str(ctx.get("prefs") or "")
                if pref not in old:
                    ctx["prefs"] = (old + "; " + pref).strip("; ")[:300] if old else pref
            return (
                [
                    "Хорошо, учла 🙂",
                    "Какой вариант берём (1–3 или название)? И вы у нас уже были или впервые?",
                ],
                BUTTONS["returning"],
                _ctx_upd_safe(merged, {"context": ctx}),
                False,
            )
        else:
            return engine.handle(merged, text)

    for k, v in clean_slots.items():
        merged[k] = v
    if notes:
        merged["context"] = _merge_notes(merged, notes)

    start_steps = ("await_intent", "greeting", "looking", "done", "browsing")
    if step in start_steps and (
        clean_slots.get("dates") or clean_slots.get("guests") or clean_slots.get("district")
    ):
        if clean_slots.get("dates"):
            out = engine.handle({**merged, "step": "await_dates"}, clean_slots["dates"])
            merged2 = {**merged, **out[2]}
            st = str(out[2].get("step") or "")
            if clean_slots.get("guests") and st == "await_guests":
                out = engine.handle({**merged2, "step": "await_guests"}, clean_slots["guests"])
                merged2 = {**merged2, **out[2]}
                st = str(out[2].get("step") or st)
            if clean_slots.get("district") and st == "await_district":
                out = engine.handle(
                    {**merged2, "step": "await_district"}, clean_slots["district"]
                )
            if notes:
                ctx = _merge_notes({**merged2, **out[2]}, notes)
                out = (out[0], out[1], {**out[2], "context": ctx}, out[3])
            return out
        upd: dict[str, Any] = {
            "step": "await_dates",
            "guests": clean_slots.get("guests") or merged.get("guests") or "",
            "district": clean_slots.get("district") or merged.get("district") or "",
            "context": merged.get("context") or {},
        }
        bits = []
        if upd["guests"]:
            bits.append(f"{upd['guests']} гост.")
        if upd["district"]:
            bits.append(str(upd["district"]))
        lead = ("Поняла: " + ", ".join(bits) + ".") if bits else "Хорошо 🙂"
        return (
            [lead, "Подскажите, пожалуйста, на какие даты планируете поездку?"],
            BUTTONS["dates"],
            upd,
            False,
        )

    if step == "await_dates" and clean_slots.get("dates"):
        out = engine.handle({**merged, "step": "await_dates"}, clean_slots["dates"])
        merged2 = {**merged, **out[2]}
        if clean_slots.get("guests") and out[2].get("step") == "await_guests":
            out = engine.handle({**merged2, "step": "await_guests"}, clean_slots["guests"])
            merged2 = {**merged2, **out[2]}
            if clean_slots.get("district") and out[2].get("step") == "await_district":
                out = engine.handle(
                    {**merged2, "step": "await_district"}, clean_slots["district"]
                )
        return out
    if step == "await_guests" and clean_slots.get("guests"):
        # сохранить исходные даты сессии (не дать «на 2» из числа гостей)
        if sess.get("dates"):
            merged["dates"] = sess["dates"]
        out = engine.handle({**merged, "step": "await_guests"}, clean_slots["guests"])
        if clean_slots.get("district") and out[2].get("step") == "await_district":
            out = engine.handle(
                {**merged, **out[2], "step": "await_district"}, clean_slots["district"]
            )
        return out
    if step == "await_district" and clean_slots.get("district"):
        return engine.handle({**merged, "step": "await_district"}, clean_slots["district"])
    if step == "await_returning" and clean_slots.get("returning"):
        # если просят варианты / каталога ещё не было — полный текст в engine
        from bot.catalog import wants_variants

        ctx = dict(merged.get("context") or {})
        if (
            not (ctx.get("offers") or merged.get("favorite"))
            or wants_variants(text)
        ):
            return engine.handle(merged, text)
        phrase = "Нет, впервые" if clean_slots["returning"] == "нет" else "Да, были"
        return engine.handle({**merged, "step": "await_returning"}, phrase)

    if step == "await_dates" and (clean_slots.get("guests") or clean_slots.get("district") or notes):
        upd = {
            "guests": clean_slots.get("guests") or sess.get("guests") or "",
            "district": clean_slots.get("district") or sess.get("district") or "",
            "context": merged.get("context") or sess.get("context") or {},
        }
        return (
            ["Пожелания вижу. Подскажите, пожалуйста, на какие даты планируете поездку?"],
            BUTTONS["dates"],
            upd,
            False,
        )
    return engine.handle(merged, text)


def _ctx_upd_safe(sess: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    from bot.engine import _ctx_upd

    return _ctx_upd(sess, updates)


def _with_resume(
    msgs: list[str], resume_step: str | None
) -> tuple[list[str], list[tuple[str, str]] | None]:
    if not resume_step or resume_step not in _RESUME_Q:
        return msgs, None
    q, bkey = _RESUME_Q[resume_step]
    out = list(msgs)
    blob = " ".join(out).lower()
    # не дублировать тот же вопрос, если скрипт/AI уже спросили
    already = False
    if resume_step == "await_dates" and re.search(r"дат", blob):
        already = True
    elif resume_step == "await_guests" and re.search(r"человек|гост|сколько\s*вас", blob):
        already = True
    elif resume_step == "await_district" and re.search(r"район|центр|спокойн", blob):
        already = True
    elif resume_step == "await_returning" and re.search(r"впервые|были\s*у|раньше", blob):
        already = True
    elif out and out[-1].rstrip().endswith("?"):
        already = True
    if not already:
        if out:
            out.append(q)
        else:
            out = [q]
    buttons = BUTTONS.get(bkey) if bkey else None
    return out[:3], buttons


def _strip_meta(updates: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in updates.items() if not k.startswith("_") and k != "need_ai"}


def _parse_ai_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


async def ai_fallback(
    settings: Settings,
    sess: dict[str, Any],
    text: str,
    history: list[dict[str, str]],
    *,
    resume_step: str | None = None,
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool] | None:
    """Минимальный LLM на край. Промпт = edge_prompt.txt (script.md)."""
    if not USE_AI:
        return None
    providers = load_providers()
    if not providers:
        return None

    try:
        from bot.catalog import catalog_facts_for_llm, catalog_summary

        offers = list((sess.get("context") or {}).get("offers") or [])
        facts = catalog_facts_for_llm(offers or None, limit=6)
        cat = (catalog_summary() + ("\n" + facts if facts else ""))[:900]
    except Exception:
        cat = ""

    try:
        from bot.rag import rag_context_for_llm

        rag_block = rag_context_for_llm(
            text,
            district=str(sess.get("district") or "") or None,
            favorite=str(sess.get("favorite") or "") or None,
            guests=str(sess.get("guests") or "") or None,
            k=4,
        )
    except Exception:
        rag_block = ""

    system = (
        f"{_edge_prompt()}\n\n"
        f"Сессия: {_session_blob(sess)}\n"
        + (f"{rag_block}\n" if rag_block else "")
        + f"Каталог (только факты БД, без выдуманных цен):\n{cat}\n"
        "Не выдумывай цены, метро, адреса и свободные даты — только RAG/каталог."
    )

    hist: list[dict[str, str]] = []
    for h in history[-4:]:
        role = "assistant" if h.get("role") == "bot" else "user"
        hist.append({"role": role, "content": (h.get("text") or "")[:180]})

    result = await chat_completion(
        providers,
        system=system,
        messages=[
            *hist,
            {
                "role": "user",
                "content": (
                    f"Гость: {text[:280]}\n"
                    "Один сырой JSON без markdown. Без привет/пока. Без выдуманных квартир."
                ),
            },
        ],
        max_tokens=140,
        temperature=0.35,
        json_mode=True,
    )
    if not result:
        return None
    raw, via = result
    data = _parse_ai_json(raw)
    msgs = _clean([str(x) for x in (data.get("messages") or []) if x])
    if not msgs:
        return None

    updates: dict[str, Any] = {}
    for key in ("dates", "guests", "district", "returning", "step"):
        val = data.get(key)
        if val in (None, "", "null", "пусто"):
            continue
        val = str(val)
        if key == "step":
            if val in _ALLOWED_STEPS:
                updates[key] = val
            continue
        if key == "dates":
            parsed = parse_dates(val) or parse_dates(text)
            if parsed:
                updates[key] = parsed
            continue
        if key == "guests":
            parsed = parse_guests(val) or parse_guests(text)
            if parsed:
                updates[key] = parsed
            continue
        if key == "district":
            parsed = parse_district(val) or parse_district(text)
            if parsed:
                updates[key] = parsed
            continue
        updates[key] = val

    prefs = data.get("prefs")
    if prefs and str(prefs) not in ("null", "None", ""):
        updates["context"] = _merge_prefs(sess, str(prefs))

    esc = bool(data.get("escalate"))
    low = text.lower()
    hard = any(
        x in low
        for x in (
            "жалоб",
            "плохо было",
            "ужас",
            "кошмар",
            "позовите",
            "менеджер",
            "оператор",
            "живой человек",
        )
    )
    if esc and not hard:
        logger.info("AI escalate suppressed via=%s", via)
        esc = False
    if esc:
        updates["handed_off"] = 1
        updates["step"] = "handed_off"

    buttons = None
    if not esc and resume_step:
        msgs, buttons = _with_resume(msgs, resume_step)

    logger.info("AI edge ok via=%s resume=%s", via, resume_step)
    return msgs, buttons, updates, esc


async def reply(
    settings: Settings,
    engine: Engine,
    sess: dict[str, Any],
    text: str,
    history: list[dict[str, str]],
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool]:
    """v9: LLM-first smart brain → safety; иначе скрипт/FAQ. Всегда непустой ответ."""
    text = (text or "").strip()
    step0 = sess.get("step") or "await_intent"

    # стоп / отказ / takeover — только скрипт (как v8.6)
    if sess.get("handed_off") or step0 == "handed_off":
        msgs, buttons, updates, esc = await _reply_core(
            settings, engine, sess, text, history
        )
        step = str(updates.get("step") or step0)
        return _guarantee(msgs, buttons, updates, esc, step, history=history)
    if is_stop_request(text) or is_refusal(text):
        msgs, buttons, updates, esc = await _reply_core(
            settings, engine, sess, text, history
        )
        step = str(updates.get("step") or step0)
        return _guarantee(msgs, buttons, updates, esc, step, history=history)

    # Smart brain (LLM-first)
    try:
        from bot.smart import smart_enabled, smart_reply

        if smart_enabled() and USE_AI:
            smart = await smart_reply(settings, engine, sess, text, history)
            if smart and (smart[0] or (smart[2].get("context") or {}).get("quiet_turn")):
                msgs, buttons, updates, esc = smart
                ctx = dict(updates.get("context") or {})
                path = ctx.get("reply_path") or "smart"
                ctx["reply_path"] = path
                updates["context"] = ctx
                logger.info("reply_path=%s", path)
                step = str(updates.get("step") or sess.get("step") or "await_intent")
                return _guarantee(msgs, buttons, updates, esc, step, history=history)
    except Exception:
        logger.exception("smart brain failed → script")

    msgs, buttons, updates, esc = await _reply_core(settings, engine, sess, text, history)
    ctx = dict(updates.get("context") or {})
    ctx["reply_path"] = "script"
    updates["context"] = ctx
    logger.info("reply_path=script")
    step = str(updates.get("step") or sess.get("step") or "await_intent")
    return _guarantee(msgs, buttons, updates, esc, step, history=history)


async def _reply_core(
    settings: Settings,
    engine: Engine,
    sess: dict[str, Any],
    text: str,
    history: list[dict[str, str]],
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool]:
    """Внутренний пайплайн ответа."""
    text = (text or "").strip()
    step = sess.get("step") or "await_intent"

    # Менеджер ведёт диалог — бот молчит (пока явно не «Вернуть боту»)
    if sess.get("handed_off") or step == "handed_off":
        logger.info("script silent handed_off step=%s", step)
        return [], None, {"handed_off": 1, "step": "handed_off"}, False

    # стоп-лист раньше всего — без LLM
    if is_stop_request(text):
        logger.info("script stop-list")
        msgs, buttons, updates, esc = engine.handle(sess, text)
        return msgs, buttons, _strip_meta(updates), esc

    if is_refusal(text):
        logger.info("script refusal")
        msgs, buttons, updates, esc = engine.handle(sess, text)
        return msgs, buttons, _strip_meta(updates), esc

    # «ну что там» — сразу напоминание шага
    if is_waiting_nudge(text):
        logger.info("script waiting nudge step=%s", step)
        msgs, buttons, updates, esc = engine.handle(sess, text)
        if msgs:
            return msgs, buttons, _strip_meta(updates), esc

    kw = keyword_intent(text)
    if kw in ("complaint", "escalate"):
        msgs, buttons, updates, esc = engine.handle(sess, text)
        return msgs, buttons, _strip_meta(updates), esc

    btn = match_button(text) if len(text) <= 48 else None
    # «давайте 3 вариант» / «1 впервые» — выбор квартиры, не browse/ret кнопка
    try:
        from bot.catalog import parse_offer_pick

        pick_n = parse_offer_pick(text)
        if btn == "browse_yes" and pick_n is not None:
            btn = None
        if btn == "browse_yes" and parse_dates(text):
            btn = None
        if btn in ("ret_yes", "ret_no") and pick_n is not None:
            btn = None  # составное: номер + впервые → engine
    except Exception:
        pick_n = None
    # pick раньше кнопки/FAQ — иначе «впервые» съедает «давайте 1»
    if pick_n is not None and step in (
        "await_returning",
        "await_favorite",
        "browsing",
        "done",
    ):
        logger.info("script apartment pick early step=%s n=%s", step, pick_n)
        msgs, buttons, updates, esc = engine.handle(sess, text)
        return msgs, buttons, _strip_meta(updates), esc
    if btn:
        logger.info("script button=%s", btn)
        msgs, buttons, updates, esc = engine.handle(sess, text)
        return msgs, buttons, _strip_meta(updates), esc

    try:
        from bot.catalog import (
            budget_from_sess,
            find_by_name_fuzzy,
            format_card,
            offer_bundle,
            parse_offer_pick,
            wants_variants,
        )

        if step in ("await_returning", "await_favorite", "browsing", "done") and (
            parse_offer_pick(text) is not None or find_by_name_fuzzy(text)
        ):
            logger.info("script apartment pick step=%s", step)
            msgs, buttons, updates, esc = engine.handle(sess, text)
            return msgs, buttons, _strip_meta(updates), esc

        slots_probe = extract_slots(text)
        # «предложите варианты» даже если в тексте есть returning-слот
        if wants_variants(text) and not any(
            slots_probe.get(k) for k in ("dates", "guests", "district")
        ):
            if step in (
                "browsing",
                "await_intent",
                "done",
                "await_dates",
                "await_guests",
                "await_district",
                "await_returning",
            ):
                if step in (
                    "await_dates",
                    "await_guests",
                    "await_district",
                    "await_returning",
                    "browsing",
                    "done",
                ) or (sess.get("favorite") and step in ("done", "browsing")):
                    msgs, buttons, updates, esc = engine.handle(sess, text)
                    if msgs:
                        return msgs, buttons, _strip_meta(updates), esc
                cards, offered = offer_bundle(
                    district=str(sess.get("district") or "не принципиально"),
                    guests=str(sess.get("guests") or "2"),
                    budget=budget_from_sess(sess),
                    limit=3,
                )
                if cards:
                    ctx = dict(sess.get("context") or {})
                    if offered:
                        ctx["offers"] = offered
                    return (
                        [cards, "Если подходит, напишите номер или название 🙂"],
                        [("Да, ищу квартиру", "looking")],
                        {
                            "step": "done" if step in ("await_intent", "browsing", "done") else step,
                            "context": ctx,
                        },
                        False,
                    )

        if step in ("browsing", "done", "await_intent"):
            hit = find_by_name_fuzzy(text)
            if hit:
                # слоты из того же сообщения («Феррари на 13… буду я 1… уже был»)
                slots_apt = extract_slots(text)
                dates = str(slots_apt.get("dates") or sess.get("dates") or "").strip()
                guests = str(slots_apt.get("guests") or sess.get("guests") or "").strip()
                returning = str(
                    slots_apt.get("returning") or sess.get("returning") or ""
                ).strip()
                district = str(
                    slots_apt.get("district") or sess.get("district") or ""
                ).strip()
                ctx = {
                    **(sess.get("context") or {}),
                    "offers": [hit["name"]],
                }
                meta_ctx = _merge_slot_meta({**sess, "context": ctx}, slots_apt)
                base = {
                    **sess,
                    "favorite": hit["name"],
                    "dates": dates,
                    "guests": guests,
                    "district": district or sess.get("district") or "",
                    "returning": returning,
                    "context": meta_ctx,
                }
                # всё для заявки — сразу returning/handoff, не спрашивать даты заново
                if dates and guests:
                    phrase = returning if returning in ("да", "нет") else hit["name"]
                    if returning in ("да", "нет"):
                        return engine.handle(
                            {**base, "step": "await_returning"}, phrase
                        )
                    return (
                        [
                            "Да, есть такая 🙂\n" + format_card(hit),
                            f"Поняла: «{hit['name']}», {dates}, {guests} гост.",
                            "Вы у нас уже были или впервые?",
                        ],
                        BUTTONS["returning"],
                        {
                            "favorite": hit["name"],
                            "dates": dates,
                            "guests": guests,
                            "district": base["district"],
                            "step": "await_returning",
                            "context": meta_ctx,
                        },
                        False,
                    )
                if dates and not guests:
                    return (
                        [
                            "Да, есть такая 🙂\n" + format_card(hit),
                            f"На {dates.replace('на ', '')} — отлично. Сколько вас будет?",
                        ],
                        BUTTONS["guests"],
                        {
                            "favorite": hit["name"],
                            "dates": dates,
                            "returning": returning,
                            "step": "await_guests",
                            "context": meta_ctx,
                        },
                        False,
                    )
                if guests and not dates:
                    bits = [f"{guests} гост."]
                    if returning == "да":
                        bits.append("уже были у нас")
                    return (
                        [
                            "Да, есть такая 🙂\n" + format_card(hit),
                            "Хорошо, " + ", ".join(bits) + ". Подскажите даты — забронируем?",
                        ],
                        BUTTONS["dates"],
                        {
                            "favorite": hit["name"],
                            "guests": guests,
                            "returning": returning,
                            "step": "await_dates",
                            "context": meta_ctx,
                        },
                        False,
                    )
                return (
                    [
                        "Да, есть такая 🙂\n" + format_card(hit),
                        "Подскажите даты — забронируем?",
                    ],
                    [
                        ("Ближайшие выходные", "dates_weekend"),
                        ("Ещё варианты", "browsing"),
                    ],
                    {
                        "favorite": hit["name"],
                        "returning": returning,
                        "step": "await_dates",
                        "context": meta_ctx,
                    },
                    False,
                )
    except Exception:
        logger.exception("catalog")

    if kw == "looking" and step.startswith("await_"):
        # сначала слоты из длинного текста, потом looking-handle
        slots_early = extract_slots(text)
        if slots_early.get("dates") or slots_early.get("guests") or slots_early.get("district"):
            logger.info("script looking+slots mid step=%s slots=%s", step, slots_early)
            msgs, buttons, updates, esc = _funnel_reply(engine, sess, text, slots_early)
            if not updates.get("need_ai"):
                return msgs, buttons, _strip_meta(updates), esc
        logger.info("script looking mid-funnel step=%s", step)
        msgs, buttons, updates, esc = engine.handle(sess, text)
        if not updates.get("need_ai") and msgs:
            return msgs, buttons, _strip_meta(updates), esc

    # любое сообщение — вытаскиваем слоты (даты/гости/район/заметки)
    slots = extract_slots(text)
    if slots and (
        step.startswith("await_")
        or step in ("await_intent", "greeting", "looking", "browsing", "done")
    ):
        logger.info("script slots=%s step=%s", {k: v for k, v in slots.items() if k != "_notes"}, step)
        try:
            msgs, buttons, updates, esc = _funnel_reply(engine, sess, text, slots)
            if not updates.get("need_ai") and (msgs or updates):
                return msgs, buttons, _strip_meta(updates), esc
        except Exception:
            logger.exception("funnel")

    if (slots or kw == "looking") and step in ("await_intent", "greeting"):
        logger.info("script compound start slots=%s kw=%s", slots, kw)
        msgs, buttons, updates, esc = engine.handle(sess, text)
        if not updates.get("need_ai") and msgs:
            return msgs, buttons, _strip_meta(updates), esc

    # до engine miss: шум / название квартиры — без «не поймала»-петли
    resume_pre = step
    try:
        from bot.catalog import find_by_name_fuzzy

        hit_pre = find_by_name_fuzzy(text) if len(text) <= 80 else None
    except Exception:
        hit_pre = None
    if hit_pre and resume_pre in _FUNNEL_SOFT_FIRST | {"await_intent", "browsing", "done"}:
        name = str(hit_pre["name"])
        logger.info("script apt early %r step=%s", name, resume_pre)
        if resume_pre in ("await_returning", "await_favorite", "browsing", "done"):
            msgs, buttons, updates, esc = engine.handle(
                {**sess, "favorite": name, "step": "await_returning" if resume_pre != "await_favorite" else resume_pre},
                name,
            )
            if msgs:
                return msgs, buttons, _strip_meta(updates), esc
        soft = _soft_ack(
            resume_pre if resume_pre in _FUNNEL_SOFT_FIRST else "await_dates",
            apt=name,
        )
        bkey = {"await_dates": "dates", "await_guests": "guests", "await_district": "district"}.get(
            resume_pre, "dates"
        )
        return (
            soft,
            BUTTONS.get(bkey),
            {"favorite": name, "step": resume_pre if resume_pre.startswith("await_") else "await_dates"},
            False,
        )
    if _is_noise(text) and resume_pre in _NO_LLM_STEPS:
        logger.info("script noise early step=%s", resume_pre)
        soft = _soft_ack(
            resume_pre if resume_pre in _RESUME_Q or resume_pre in _FUNNEL_SOFT_FIRST else "await_intent",
            noise=True,
        )
        bkey = {
            "await_dates": "dates",
            "await_guests": "guests",
            "await_district": "district",
            "await_returning": "returning",
        }.get(resume_pre)
        return soft, BUTTONS.get(bkey) if bkey else BUTTONS.get("greeting"), {}, False

    logger.info("script handle step=%s", step)
    msgs, buttons, updates, esc = engine.handle(sess, text)
    if not updates.get("need_ai") and msgs:
        return msgs, buttons, _strip_meta(updates), esc

    resume = str(updates.get("_resume") or step)

    # квартира по имени mid-воронки — зафиксировать, не крутить soft-reask
    try:
        from bot.catalog import find_by_name_fuzzy

        hit = find_by_name_fuzzy(text)
    except Exception:
        hit = None
    if hit and resume in _FUNNEL_SOFT_FIRST | {"await_intent", "browsing", "done"}:
        name = str(hit["name"])
        logger.info("script apt mid-funnel %r step=%s", name, resume)
        if resume in ("await_dates", "await_guests", "await_district", "await_intent"):
            soft = _soft_ack(resume if resume != "await_intent" else "await_dates", apt=name)
            btns = BUTTONS.get(
                {"await_dates": "dates", "await_guests": "guests", "await_district": "district"}.get(
                    resume, "dates"
                )
            )
            return soft, btns, {"favorite": name, "step": resume if resume.startswith("await_") else "await_dates"}, False
        msgs, buttons, updates, esc = engine.handle(
            {**sess, "favorite": name, "step": "await_returning" if resume != "await_favorite" else resume},
            name,
        )
        if msgs:
            return msgs, buttons, _strip_meta(updates), esc

    # ссылки / телефоны / токены — короткое «приняла» + один вопрос шага
    if _is_noise(text) and resume in _NO_LLM_STEPS:
        logger.info("script noise ack step=%s", resume)
        soft = _soft_ack(resume if resume in _RESUME_Q or resume in _FUNNEL_SOFT_FIRST else "await_intent", noise=True)
        bkey = {
            "await_dates": "dates",
            "await_guests": "guests",
            "await_district": "district",
            "await_returning": "returning",
        }.get(resume)
        return soft, BUTTONS.get(bkey) if bkey else BUTTONS.get("greeting"), {}, False

    if resume in _SCRIPT_ONLY_STEPS or step in _SCRIPT_ONLY_STEPS:
        soft, soft_btn = _with_resume(
            ["Хорошо 🙂"],
            "await_intent" if resume in _SCRIPT_ONLY_STEPS else resume,
        )
        return soft, soft_btn, {}, False

    # на датах: если похоже на дату — принять сырой текст, не крутить soft reask
    if resume == "await_dates" and re.search(
        r"\d|понедельник|вторник|сред|четверг|пятниц|суббот|воскресен|выходн|недел",
        text.lower(),
    ):
        raw_date = parse_dates(text, allow_day_1_3=True) or text.strip()[:40]
        logger.info("script force-date %r", raw_date)
        msgs, buttons, updates, esc = engine.handle(
            {**sess, "step": "await_dates"}, raw_date
        )
        if not updates.get("need_ai") and msgs:
            return msgs, buttons, _strip_meta(updates), esc

    # воронка: мягкий переспрос БЕЗ LLM и БЕЗ повтора того же вопроса подряд
    if resume in _NO_LLM_STEPS:
        ctx = dict(sess.get("context") or {})
        last_soft = str(ctx.get("last_soft") or "")
        last_ask = str(ctx.get("last_ask") or "")
        soft = _soft_ack(resume, salt=text[:40] + last_soft)
        ask_line = soft[-1] if soft else _ask_for(resume, salt=text)
        if last_soft == resume and last_ask and ask_line.strip().lower() == last_ask.strip().lower():
            ask_line = _ask_for(resume, salt=last_ask + "x")
            soft = [soft[0].split("🙂")[0] + "🙂 " + ask_line] if soft else [ask_line]
        bkey = {
            "await_dates": "dates",
            "await_guests": "guests",
            "await_district": "district",
            "await_returning": "returning",
            "await_intent": "greeting",
            "browsing": "browsing",
            "bonus": "bonus",
        }.get(resume)
        logger.info("script soft ack (no LLM) resume=%s", resume)
        return (
            soft,
            BUTTONS.get(bkey) if bkey else BUTTONS.get("greeting"),
            {"context": {**ctx, "last_soft": resume, "last_ask": ask_line}},
            False,
        )

    # LLM — только вне воронки (редкий оффтоп)
    logger.info("script miss → minimal LLM edge resume=%s", resume)
    ai = await ai_fallback(settings, sess, text, history, resume_step=resume)
    if ai and ai[0]:
        return ai[0], ai[1], _strip_meta(ai[2]), ai[3]

    soft = _soft_ack("await_intent")
    return soft, BUTTONS.get("greeting"), {}, False


def _guarantee(
    msgs: list[str] | None,
    buttons: list[tuple[str, str]] | None,
    updates: dict[str, Any],
    esc: bool,
    step: str,
    *,
    history: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[tuple[str, str]] | None, dict[str, Any], bool]:
    """Непустой ответ гостю — кроме silence, когда менеджер уже ведёт чат."""
    handed = bool(updates.get("handed_off") or step == "handed_off")
    # Путаница и замечание про скорость уже собраны из слышанного и вопроса шага.
    # Повтор того же вопроса здесь — ответ, а не петля анкеты.
    path = str((updates.get("context") or {}).get("reply_path") or "")
    keep_voice = path in (
        "smart:rule/plain",
        "smart:rule/pace",
        "smart:rule/calendar-span",
        "smart:rule/area",
        "smart:rule/yes-to-ask",
        "smart:rule/wait",
    )

    def _out(batch: list[str]) -> list[str]:
        from bot.reply_guard import humanize

        if keep_voice:
            return humanize([m for m in batch if (m or "").strip()], history)
        return humanize(_dedupe_msgs(batch, history=history), history)

    if (updates.get("context") or {}).get("quiet_turn") and not msgs:
        # гость в третий раз «хорошо» после «будем ждать» и 😊 — молчим, не навязываемся
        return [], None, updates, esc
    if handed:
        # первая реплика эскалации/стоп — отправить; дальше тишина
        if msgs:
            return (
                _out(msgs),
                buttons,
                {**updates, "handed_off": 1, "step": "handed_off"},
                esc,
            )
        return [], None, {**updates, "handed_off": 1, "step": "handed_off"}, esc
    if msgs:
        out = _out(msgs)
        if out:
            return out, buttons, updates, esc
    ask, btns = _step_ask(step if step.startswith("await_") or step in ("browsing", "bonus") else "await_intent")
    from bot.reply_guard import humanize

    return humanize(ask, history) or ask, btns or buttons, updates, esc


def _ask_key(text: str) -> str:
    from bot.reply_guard import question_key

    return question_key(text)


def _is_rehello(text: str) -> bool:
    low = (text or "").lower()
    return bool(
        re.search(
            r"^(здравствуйте|добрый день|доброе утро|добрый вечер|привет)\b",
            low,
        )
        and re.search(r"home24|рада вас|это home|посуточн", low)
    )


def _is_substantive_bundle(msgs: list[str]) -> bool:
    """Сводка + карточки / следующий вопрос — нельзя схлопывать в один пузырь-обрывок."""
    if not msgs:
        return False
    blob = "\n".join(msgs)
    low = blob.lower()
    if re.search(
        r"(?m)подобрала несколько|записала всё|^\d\)\s|если зайдёт|были у нас|"
        r"впервые\?",
        low,
    ):
        return True
    if any(len(m) >= 200 for m in msgs):
        return True
    return False


def _dedupe_msgs(msgs: list[str], *, history: list[dict[str, Any]] | None = None) -> list[str]:
    """Без повторного приветствия и дублей вопросов; офферы/сводку не отбрасывать."""
    prev_bot = ""
    if history:
        for h in reversed(history):
            if (h.get("role") or "") == "bot" and (h.get("text") or "").strip():
                prev_bot = str(h.get("text") or "")
                break
    prev_keys = {_ask_key(prev_bot)} if prev_bot else set()
    prev_keys.discard("")
    already_said_hello = _is_rehello(prev_bot) or bool(
        prev_bot and re.search(r"home24|соскучились|давно не брон", prev_bot.lower())
    )

    out: list[str] = []
    dropped_ask = ""
    seen_asks: set[str] = set(prev_keys)
    for m in msgs:
        t = (m or "").strip()
        if not t:
            continue
        if already_said_hello and _is_rehello(t):
            # повторное представление после outreach — оставить только вопрос
            parts = re.split(r"(?<=[.!?…])\s+|(?<=\))\s+(?=[А-ЯЁA-Z])", t)
            ask_parts = [
                p
                for p in parts
                if _ask_key(p)
                and not re.search(r"^(здравствуйте|добрый|привет)\b", p.lower())
            ]
            if ask_parts:
                t = " ".join(ask_parts).strip()
            else:
                continue
        key = _ask_key(t)
        # длинные карточки / сводка — не режем как «повторный ask»
        if key and key in seen_asks and len(t) < 200 and not _is_substantive_bundle([t]):
            parts = re.split(r"(?<=[.!?…])\s+|(?<=\))\s+(?=[А-ЯЁA-Z])", t)
            kept_parts = [
                p.strip()
                for p in parts
                if p.strip() and not (_ask_key(p) and _ask_key(p) in seen_asks)
            ]
            dropped_ask = key
            if not kept_parts:
                continue
            t = " ".join(kept_parts)
            key = _ask_key(t)
            if key and key in seen_asks:
                continue
        if key:
            seen_asks.add(key)
        out.append(t)
    # вопрос сняли как повтор, а другого нет — ответ без продолжения (10.11 «С 3 по 6 декабря.»)
    from bot.reply_guard import is_closing

    if dropped_ask and out and not any("?" in x for x in out) and not is_closing("\n".join(out)):
        from bot.reply_guard import follow_up_ask

        recent = "\n".join(
            str(h.get("text") or "") for h in (history or [])[-6:] if (h.get("role") or "") == "bot"
        )
        follow = follow_up_ask(dropped_ask, recent)
        if follow:
            out[-1] = f"{out[-1].rstrip()} {follow}"

    if already_said_hello and out:
        if _is_substantive_bundle(out):
            # сводка + карточки + вопрос: до 3 кусков, потом consolidate в 1–2 пузыря
            out = out[:3]
        elif len(out) > 1 and all(len(x) < 220 for x in out):
            facts = [x for x in out if not _ask_key(x) and not _is_rehello(x)]
            prefer = [
                x
                for x in out
                if _ask_key(x) and not _is_rehello(x)
            ]
            out = (facts + prefer)[:2]
        else:
            out = out[:1]
    # свежее входящее: приветствие + вопрос ок (до 2 пузырей), без дубля дат
    elif len(out) >= 2:
        keys = [_ask_key(x) for x in out]
        if keys.count("dates") >= 2:
            # оставить первое с датами + приветствие если было
            kept: list[str] = []
            seen_d = False
            for x in out:
                k = _ask_key(x)
                if k == "dates":
                    if seen_d:
                        continue
                    seen_d = True
                kept.append(x)
            out = kept
    if out:
        if _is_substantive_bundle(out):
            return out[:3]
        return out[:2]
    # повтор того же вопроса не возвращаем — иначе диалог крутится по кругу
    return ["Хорошо. Напишите, когда будут даты или район — подберу."]
