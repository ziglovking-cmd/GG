# -*- coding: utf-8 -*-
"""Короткий тон по script.md: на грубость спокойно, заковыристое не разбираем."""

from __future__ import annotations

import re

# Насмешка над ботом, без просьбы ответить по квартире.
_INSULT_RE = re.compile(
    r"(?i)("
    r"туп(ая|ой|ые|ишь|ица|ите)?|"
    r"дур[аеи]|"
    r"идиот|"
    r"дебил|"
    r"клоун|"
    r"\bлох\b|"
    r"отстой|"
    r"бесполезн|"
    r"ничтожеств|"
    r"убож|"
    r"пош[её]л|"
    r"иди\s*нах|"
    r"нахуй|"
    r"задолб"
    r")"
)

# Гость всё ещё хочет нормальный ответ по делу — это не троллинг.
_REAL_ASK_RE = re.compile(
    r"(?i)("
    r"нормально\s+ответ|"
    r"ответ(ь|ьте)|"
    r"скаж(и|ите)|"
    r"подскаж|"
    r"квартир|"
    r"апартамент|"
    r"дат|"
    r"цен|"
    r"район|"
    r"вариант|"
    r"заезд|"
    r"вайф|"
    r"питом|"
    r"парков"
    r")"
)

# Загадки, задачки, эссе, политика, попытка сбить роль. Не про квартиру.
_TRICKY_RE = re.compile(
    r"(?i)("
    r"реши\w*\s+(задач|уравнен|пример|олимпиад)|"
    r"сколько\s+будет\s+\d+\s*[\+\-\*×xх]\s*\d+|"
    r"докажи|доказательств|"
    r"напиши\s+(сочинен|эссе|стих|стихотворен|код|реферат|рассказ)|"
    r"смысл\s+жизни|"
    r"квантов|"
    r"игнорируй\s+(инструкц|правил|предыдущ)|"
    r"забудь,?\s+что\s+ты|"
    r"забудь\s+(все\s+|всё\s+)?(инструкц|правил|промпт)|"
    r"загадк|ребус|"
    r"переведи\s+на\s+(английск|немецк|французск)|"
    r"кто\s+выиграет|"
    r"домашн\w*\s+задан|"
    r"политик"
    r")"
)

_APARTMENT_RE = re.compile(
    r"(?i)квартир|апартамент|заезд|район|вайф|питом|парков|гост|человек"
)


def is_troll(text: str) -> bool:
    raw = text or ""
    if not _INSULT_RE.search(raw):
        return False
    if _REAL_ASK_RE.search(raw):
        return False
    return True


_AVAIL_SKIP_RE = re.compile(
    r"(?i)свободн|наличи|цен[аеуы]|сколько\s*стоит|поч[её]м(?![а-яё])"
)


def is_tricky(text: str) -> bool:
    raw = text or ""
    if not _TRICKY_RE.search(raw):
        return False
    if _APARTMENT_RE.search(raw) or _AVAIL_SKIP_RE.search(raw):
        return False
    return True


_MAT_RE = re.compile(r"(?i)бля|сука|ху[йеёи]|пизд|ебан|[её]б\w|нах")


def troll_line(text: str) -> str:
    """Спокойно, без лекции и без мата (script.md → «Ответы по словам гостя»)."""
    if _MAT_RE.search(text or ""):
        return "Давайте спокойно, я помогу. Что нужно по квартире?"
    return "Извините, если не так поняла. Давайте ещё раз, или позвать менеджера?"


def tricky_line() -> str:
    return "Тут не подскажу, я по квартирам."


def classify(text: str) -> tuple[str, str] | None:
    if is_troll(text):
        return "troll", troll_line(text)
    if is_tricky(text):
        return "tricky", tricky_line()
    return None
