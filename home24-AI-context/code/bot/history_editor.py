# -*- coding: utf-8 -*-
"""Разбор истории перед отправкой: повторы вырезает или не пускает сообщение."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bot.reply_guard import question_key, question_keys, sentence_repeats

_FILLER = {
    "поняла",
    "хорошо",
    "вижу",
    "приняла",
    "ясно",
    "отлично",
    "записала",
    "подскажите",
    "пожалуйста",
    "будет",
    "ближе",
    "район",
    "центр",
    "поспокойнее",
    "даты",
    "дата",
    "дату",
    "это",
    "для",
    "вас",
    "вам",
    "или",
    "уже",
    "нас",
    "дома",
}

_GUEST_WORDS = {
    "один": "1",
    "одна": "1",
    "одного": "1",
    "двое": "2",
    "двоих": "2",
    "вдвоем": "2",
    "трое": "3",
    "троих": "3",
    "втроем": "3",
    "четверо": "4",
    "четверых": "4",
}

_MONTH = re.compile(
    r"январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр"
)


@dataclass
class HistoryEdit:
    messages: list[str]
    action: str  # keep | edit | skip
    note: str = ""


def _norm(text: str) -> str:
    s = (text or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in _norm(text).split() if len(t) > 2]


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text or "")
    return [p.strip() for p in parts if p.strip()]


def _bot_blob(history: list[dict] | None) -> str:
    return "\n".join(
        str(item.get("text") or "")
        for item in history or []
        if (item.get("role") or "") == "bot" and str(item.get("text") or "").strip()
    )


def _returning_known(sess: dict | None, blob: str) -> bool:
    sess = sess or {}
    if str(sess.get("returning") or sess.get("returning_guest") or "").strip():
        return True
    ctx = sess.get("context") or {}
    if ctx.get("outreach"):
        return True
    return bool(re.search(r"останавл|уже бывал|жили у нас|были у нас|впервые", blob, re.I))


def _asked(blob: str, sess: dict | None) -> set[str]:
    keys = set(question_keys(blob))
    if _returning_known(sess, blob):
        keys.add("returning")
    return keys


def _guest_marks(text: str) -> set[str]:
    low = _norm(text)
    marks: set[str] = set()
    for word, num in _GUEST_WORDS.items():
        if re.search(rf"(?<![а-я]){word}(?![а-я])", low):
            marks.add(num)
    count = re.search(r"(\d+)\s*(?:человек|гост|чел\b)", low)
    if count:
        marks.add(count.group(1))
    return marks


def _is_recap(sentence: str, blob: str) -> bool:
    """Сводка дат и гостей, которые бот уже называл, без нового факта."""
    info = [t for t in _tokens(sentence) if t not in _FILLER and t not in _GUEST_WORDS]
    hist = set(_tokens(blob))
    novel = [t for t in info if t not in hist]
    if novel:
        return False
    nums = set(re.findall(r"\d+", sentence))
    hist_nums = set(re.findall(r"\d+", blob))
    if nums and not nums <= hist_nums:
        return False
    months = set(_MONTH.findall(_norm(sentence)))
    hist_months = set(_MONTH.findall(_norm(blob)))
    if months and not months <= hist_months:
        return False
    guests = _guest_marks(sentence)
    if guests and not guests <= _guest_marks(blob):
        return False
    return bool(nums or months or guests or re.search(r"поняла|записала", sentence, re.I))


def _keep_sentence(sentence: str, blob: str, asked: set[str]) -> bool:
    if re.search(r"(?m)^1\)", sentence):
        return True
    [REDACTED]
    if key and key in asked:
        return False
    if sentence_repeats(sentence, blob):
        return False
    if _is_recap(sentence, blob):
        return False
    return True


def _edit_text(text: str, blob: str, asked: set[str]) -> str:
    if re.search(r"(?m)^1\)", text or ""):
        parts = text.split("\n\n")
        if len(parts) >= 2 and not _keep_sentence(parts[-1], blob, asked):
            parts = parts[:-1]
        return "\n\n".join(p for p in parts if p.strip()).strip()
    kept = [bit for bit in _split_sentences(text) if _keep_sentence(bit, blob, asked)]
    return " ".join(kept).strip()


def echoes_bot_history(text: str, history: list[dict] | None) -> bool:
    """Своё исходящее, которое Telegram прислал повторно. Короткое «А» менеджера не оно."""
    t = _norm(text)
    if len(t) < 12:
        return False
    for item in history or []:
        if (item.get("role") or "") != "bot":
            continue
        if _norm(str(item.get("text") or "")) == t:
            return True
    return False


def review_outbound(
    messages: list[str] | None,
    history: list[dict] | None,
    sess: dict | None = None,
) -> HistoryEdit:
    """Сверить черновик со всей историей бота. edit — обрезать, skip — не слать."""
    blob = _bot_blob(history)
    asked = _asked(blob, sess)
    raw = [str(m).strip() for m in (messages or []) if str(m).strip()]
    if not raw:
        return HistoryEdit([], "skip", "пусто")
    if not blob:
        return HistoryEdit(raw, "keep", "")
    edited: list[str] = []
    for text in raw:
        nxt = _edit_text(text, blob, asked)
        if nxt:
            edited.append(nxt)
            asked |= question_keys(nxt)
            blob = (blob + "\n" + nxt).strip()
    if not edited:
        return HistoryEdit([], "skip", "в истории уже есть")
    if edited != raw:
        return HistoryEdit(edited, "edit", "убрала повтор")
    return HistoryEdit(edited, "keep", "")
