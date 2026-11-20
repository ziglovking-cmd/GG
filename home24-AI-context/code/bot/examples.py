# -*- coding: utf-8 -*-
"""Похожие ситуации из эталонных диалогов + curated reply_playbook — в запрос к ИИ.

Все 1200 диалогов в промпт не влезут (у Groq лимит токенов в минуту), поэтому
на каждое сообщение гостя берём 2–3 самых похожих реплики с эталонным ответом.
Playbook (data/reply_playbook.jsonl) всегда приоритетнее: там правильные ответы
на все типы соо (залог, питомцы, парковка, техника, документы…).
Отключить: EXAMPLES_OFF=1. Свой файл: EXAMPLES_PATH=путь.jsonl
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]

_STOP = {
    "а", "и", "в", "на", "с", "у", "по", "к", "за", "из", "о", "не", "но", "да", "ну", "же", "ли", "то",
    "это", "мы", "вы", "я", "нас", "вас", "мне", "нам", "есть", "можно", "будет", "или", "что", "как",
    "здравствуйте", "добрый", "день", "вечер", "привет", "пожалуйста", "спасибо",
}
_CARDS = "[КАРТОЧКИ"
_CONTEXT_INTENTS = {"consent", "pick", "returning", "correction", "district_any"}
_BAD_REPLY = re.compile(
    r"(?i)("
    r"залог\s+не\s+везде|"
    r"по\s+вашей\s+(квартире\s+)?скажет\s+менеджер|"
    r"бесплатн\w*\s+парков|"
    r"залог\s+(?!2\s*000|2000)\d"
    r")"
)


def _stems(text: str) -> frozenset[str]:
    words = re.findall(r"[a-zа-яё0-9]+", (text or "").lower().replace("ё", "е"))
    return frozenset(w[:5] for w in words if len(w) > 1 and w not in _STOP)


def _playbook_path() -> Path:
    env = os.getenv("PLAYBOOK_PATH", "").strip()
    if env:
        p = Path(env)
        return p if p.is_absolute() else ROOT / p
    return ROOT / "data" / "reply_playbook.jsonl"


@lru_cache(maxsize=2)
def _playbook_index(path_key: str) -> tuple[tuple[frozenset[str], str, str, str], ...]:
    del path_key
    p = _playbook_path()
    rows: list[tuple[frozenset[str], str, str, str]] = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.info("examples: playbook %s not found", p)
        return ()
    seen: set[str] = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        guest = str(row.get("guest") or "").strip()
        bot = str(row.get("bot") or "").strip()
        intent = str(row.get("intent") or "playbook")
        if not guest or not bot:
            continue
        key = guest.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append((_stems(guest), guest, bot, f"pb:{intent}"))
    return tuple(rows)


@lru_cache(maxsize=2)
def _index(path: str) -> tuple[tuple[frozenset[str], str, str, str], ...]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    rows: list[tuple[frozenset[str], str, str, str]] = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.info("examples: %s not found", p)
        return ()
    seen: set[str] = set()
    for line in lines:
        try:
            dlg = json.loads(line)
        except ValueError:
            continue
        turns = dlg.get("turns") or []
        for i, t in enumerate(turns):
            if t.get("role") != "guest":
                continue
            reply: list[str] = []
            for nxt in turns[i + 1 :]:
                if nxt.get("role") != "bot":
                    break
                reply.append(nxt["text"])
            if not reply or any(_CARDS in r for r in reply):
                continue
            joined = " ".join(reply)
            if _BAD_REPLY.search(joined):
                continue
            guest = t["text"].strip()
            key = guest.casefold()
            if key in seen:
                continue
            seen.add(key)
            intent = str((t.get("expect") or {}).get("intent") or "")
            if intent in _CONTEXT_INTENTS:
                continue  # «ок», «второй», «да, были» понятны только с прошлой репликой
            rows.append((_stems(guest), guest, joined, intent))
    return tuple(rows)


@lru_cache(maxsize=2)
def _idf(path: str) -> dict[str, float]:
    import math

    idx = _index(path) + _playbook_index("v1")
    df: dict[str, int] = {}
    for stems, *_ in idx:
        for w in stems:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(idx))
    return {w: math.log(1 + n / c) for w, c in df.items()}


def _score_rows(
    text: str,
    idx: tuple[tuple[frozenset[str], str, str, str], ...],
    idf: dict[str, float],
    *,
    min_inter: int = 1,
    soft: bool = False,
) -> list[tuple[float, str, str, str]]:
    q = _stems(text)
    if not idx or not q:
        return []
    scored: list[tuple[float, str, str, str]] = []
    for stems, guest, reply, intent in idx:
        inter = q & stems
        if len(inter) < min_inter:
            continue
        if not soft and len(inter) < 2 and max(idf.get(w, 1.0) for w in inter) < 4.5:
            continue
        score = sum(idf.get(w, 1.0) for w in inter) / (len(q | stems) ** 0.5)
        # точное/почти точное совпадение playbook — сильный буст
        if soft and guest.casefold() in text.casefold():
            score += 8.0
        elif soft and text.casefold() in guest.casefold():
            score += 5.0
        scored.append((score, guest, reply, intent))
    scored.sort(key=lambda x: -x[0])
    return scored


def similar_examples(text: str, k: int = 3, max_chars: int = 720) -> str:
    """Блок «Похожие ситуации» для системного промпта ('' если ничего не подошло)."""
    if os.getenv("EXAMPLES_OFF", "").strip() in ("1", "true", "yes"):
        return ""
    path = os.getenv("EXAMPLES_PATH") or "training/dialogs_home24.jsonl"
    q = _stems(text)
    if not q:
        return ""
    idf = _idf(path)
    pb = _score_rows(text, _playbook_index("v1"), idf, min_inter=1, soft=True)
    tr = _score_rows(text, _index(path), idf, min_inter=1, soft=False)
    # playbook сверху, потом тренировочные
    scored = pb + [(s, g, r, i) for s, g, r, i in tr]
    if not scored:
        return ""
    best = scored[0][0]
    out: list[str] = []
    used_intents: set[str] = set()
    used_guest: set[str] = set()
    for score, guest, reply, intent in scored:
        # playbook: мягкий порог; training: как раньше
        is_pb = intent.startswith("pb:")
        floor = 0.8 if is_pb else 1.6
        if score < floor or score < 0.45 * best:
            continue
        if intent in used_intents and not is_pb:
            continue
        gkey = guest.casefold()
        if gkey in used_guest:
            continue
        used_intents.add(intent)
        used_guest.add(gkey)
        out.append(f"Гость: «{guest}» → Менеджер: «{reply}»")
        if len(out) >= k:
            break
    if not out:
        return ""
    block = (
        "Похожие ситуации из эталона (тон и длина; факты бери из сессии/RAG/каталога):\n"
        + "\n".join(out)
    )
    return block[:max_chars]


def examples_count() -> int:
    path = os.getenv("EXAMPLES_PATH") or "training/dialogs_home24.jsonl"
    return len(_index(path)) + len(_playbook_index("v1"))


def playbook_count() -> int:
    return len(_playbook_index("v1"))


def clear_examples_cache() -> None:
    _index.cache_clear()
    _idf.cache_clear()
    _playbook_index.cache_clear()
