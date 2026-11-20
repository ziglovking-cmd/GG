# -*- coding: utf-8 -*-
"""v9.6: один вопрос на слот (гости / даты / район / бюджет / «были у нас»).

LLM-ответ + вопрос воронки иногда спрашивают одно и то же дважды:
«Отлично! Назовите, пожалуйста, количество гостей — 2, 3 или 4 человека?
Подскажите, пожалуйста, сколько будет гостей?» → оставляем один вопрос.
"""
from __future__ import annotations

import re

GUESTS_Q = "Подскажите, пожалуйста, сколько будет гостей?"

_SLOT_RES: dict[str, re.Pattern[str]] = {
    "guests": re.compile(
        r"(?i)гост(ей|я|и|ям)\b|сколько\s+(вас|человек)|на\s+сколько\s+человек|"
        r"(число|количеств\w*|кол-?во)\s+(гост|человек|персон)|сколько\s+будет\s+(вас|человек)|"
        r"\bперсон"
    ),
    "dates": re.compile(
        r"(?i)\bдат[уыа]?\b|какие\s+числа|когда\s+.{0,25}(планир|приед|заезд|нужн)|"
        r"даты\s+(заезда|поездки)|на\s+какой\s+срок|сколько\s+(ночей|суток)"
    ),
    "district": re.compile(
        r"(?i)район|центр\s+или|какое\s+метро|ближе\s+к\s+метро|локаци|где\s+удобнее"
    ),
    "budget": re.compile(r"(?i)бюджет|по\s+цене\s+ориентир|ценов\w+\s+(диапазон|рамк)|сколько\s+готовы"),
    "returning": re.compile(r"(?i)были\s+у\s+нас|впервые|уже\s+останавлив"),
}

_ASK_HINT = re.compile(r"(?i)^\s*(подскажите|назовите|уточните|напишите|скажите|сообщите)\b")
_CARD_RE = re.compile(r"(?m)^\s*\d\)\s")
_NAME_GUESTS_RE = re.compile(
    r"(?i)назовите[^.!?\n]*(количеств|числ|кол-?во)[^.!?\n]*гост|"
    r"(количеств|числ)\w*\s+гостей\s*[—–-]\s*\d"
)
_CHOICE_LIST_RE = re.compile(r"\d\s*,\s*\d\s*(,\s*\d\s*)?или\s*\d")


def _is_question(sentence: str) -> bool:
    s = sentence.strip()
    return bool(s) and ("?" in s or bool(_ASK_HINT.search(s)))


def question_slots(sentence: str) -> set[str]:
    """Слоты, о которых спрашивает предложение (пусто — это не вопрос воронки)."""
    if not _is_question(sentence):
        return set()
    return {k for k, rx in _SLOT_RES.items() if rx.search(sentence)}


def asked_slots(text: str) -> set[str]:
    out: set[str] = set()
    for s in _split(text):
        out |= question_slots(s)
    return out


def _split(text: str) -> list[str]:
    return [p for p in re.split(r"(?<=[.!?…])\s+", (text or "").strip()) if p.strip()]


def normalize_guest_question(sentence: str) -> str:
    """«Назовите … количество гостей — 2, 3 или 4 человека?» → канон."""
    if question_slots(sentence) == {"guests"} and (
        _NAME_GUESTS_RE.search(sentence) or _CHOICE_LIST_RE.search(sentence)
    ):
        return GUESTS_Q
    return sentence


def normalize_questions(text: str) -> str:
    if not _NAME_GUESTS_RE.search(text or "") and not _CHOICE_LIST_RE.search(text or ""):
        return text
    parts = re.split(r"((?<=[.!?…])\s+)", text)
    return "".join(p if p.isspace() else normalize_guest_question(p) for p in parts)


def dedupe_slot_questions(msgs: list[str]) -> list[str]:
    """Убрать второй (и далее) вопрос про тот же слот — внутри пузыря и между пузырями.

    Карточки вариантов не режем, но их вопрос учитываем как «уже спросили».
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in msgs or []:
        t = (m or "").strip()
        if not t:
            continue
        if _CARD_RE.search(t):
            seen |= asked_slots(t)
            out.append(t)
            continue
        t = normalize_questions(t)
        parts = re.split(r"((?<=[.!?…])\s+)", t)
        kept: list[str] = []
        for p in parts:
            if p.isspace() or not p:
                kept.append(p)
                continue
            slots = question_slots(p)
            if slots and slots <= seen:
                # дубль: срезать и висящий разделитель перед ним
                if kept and kept[-1].isspace():
                    kept.pop()
                continue
            seen |= slots
            kept.append(p)
        t2 = "".join(kept).strip()
        # «Отлично! 🙂» без вопроса после среза — ок; пустой пузырь — выкинуть
        if t2:
            out.append(t2)
    return out
