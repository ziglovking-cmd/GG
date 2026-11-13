# -*- coding: utf-8 -*-
"""Похожие ситуации из эталонных диалогов (training/dialogs_home24.jsonl) — в запрос к ИИ.

Все 1200 диалогов в промпт не влезут (у Groq лимит токенов в минуту), поэтому
на каждое сообщение гостя берём 2 самых похожих реплики с эталонным ответом.
Так ИИ видит, как живой менеджер отвечает именно на такое, а запрос остаётся коротким.
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


def _stems(text: str) -> frozenset[str]:
    words = re.findall(r"[a-zа-яё0-9]+", (text or "").lower().replace("ё", "е"))
    return frozenset(w[:5] for w in words if len(w) > 1 and w not in _STOP)


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
            guest = t["text"].strip()
            key = guest.casefold()
            if key in seen:
                continue
            seen.add(key)
            intent = str((t.get("expect") or {}).get("intent") or "")
            if intent in _CONTEXT_INTENTS:
                continue  # «ок», «второй», «да, были» понятны только с прошлой репликой
            rows.append((_stems(guest), guest, " ".join(reply), intent))
    return tuple(rows)


@lru_cache(maxsize=2)
def _idf(path: str) -> dict[str, float]:
    import math

    idx = _index(path)
    df: dict[str, int] = {}
    for stems, *_ in idx:
        for w in stems:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(idx))
    return {w: math.log(1 + n / c) for w, c in df.items()}


def similar_examples(text: str, k: int = 2, max_chars: int = 520) -> str:
    """Блок «Похожие ситуации» для системного промпта ('' если ничего не подошло)."""
    if os.getenv("EXAMPLES_OFF", "").strip() in ("1", "true", "yes"):
        return ""
    idx = _index(os.getenv("EXAMPLES_PATH") or "training/dialogs_home24.jsonl")
    q = _stems(text)
    if not idx or not q:
        return ""
    idf = _idf(os.getenv("EXAMPLES_PATH") or "training/dialogs_home24.jsonl")
    scored: list[tuple[float, str, str, str]] = []
    for stems, guest, reply, intent in idx:
        inter = q & stems
        if not inter:
            continue
        if len(inter) < 2 and max(idf.get(w, 1.0) for w in inter) < 4.5:
            continue  # одно частое слово («уже», «хочу») — не похожая ситуация
        # редкие слова («собак», «сломал», «годовщ») весят больше частых («хочу», «уже»)
        score = sum(idf.get(w, 1.0) for w in inter) / (len(q | stems) ** 0.5)
        scored.append((score, guest, reply, intent))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0] if scored else 0.0
    out: list[str] = []
    used_intents: set[str] = set()
    for score, guest, reply, intent in scored:
        if score < 1.6 or score < 0.6 * best or intent in used_intents:
            continue
        used_intents.add(intent)
        out.append(f"Гость: «{guest}» → Менеджер: «{reply}»")
        if len(out) >= k:
            break
    if not out:
        return ""
    block = "Похожие ситуации из эталона (тон и длина ответа; факты бери из сессии и каталога):\n" + "\n".join(out)
    return block[:max_chars]


def examples_count() -> int:
    return len(_index(os.getenv("EXAMPLES_PATH") or "training/dialogs_home24.jsonl"))
