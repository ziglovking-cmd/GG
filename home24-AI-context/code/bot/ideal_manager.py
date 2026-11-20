# -*- coding: utf-8 -*-
"""Идеальный менеджер Home24 — персона + стиль эталонного диалога.

Владелец: «начальница сказала вот этот диалог был идеальным — настраивайся под него»
и «сделай его пиздец умным». Этот модуль держит правила тона и подмешивает
похожие живые реплики из guest-dialogs / ideal_dialog / reply_playbook в промпт.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_STOP = {
    "а", "и", "в", "на", "с", "у", "по", "к", "за", "из", "о", "не", "но", "да", "ну",
    "же", "ли", "то", "это", "мы", "вы", "я", "нас", "вас", "мне", "нам", "есть",
    "можно", "будет", "или", "что", "как", "здравствуйте", "добрый", "день", "вечер",
}

_BAD_STYLE = re.compile(
    r"(?i)("
    r"залог\s+не\s+везде|"
    r"по\s+вашей\s+(квартире\s+)?скажет\s+менеджер|"
    r"бесплатн\w*\s+парков|"
    r"залог\s+(?!2\s*000|2000)\d|"
    r"точно\s+свободн|всегда\s+свободн"
    r")"
)

PERSONA_BLOCK = """Идеальный менеджер Home24 (тон + факты + как отвечать на любое соо):
- Пиши как живой человек в Telegram: коротко, тепло, на «вы», женский род.
- Одна законченная фраза за ход; без канцелярита и без повторного приветствия.
- Принял факты гостя сразу; не переспрашивай уже сказанное.
- Воронка: даты → условия (гости/район/что важно) → карточки → выбор → бронь/менеджер.
- Жёстко: цена, метро, адрес, залог, животные, «свободно», бесплатная парковка —
  только из RAG/каталога/календаря. Нет строки в базе → не додумывай, скажи «уточню»
  или uncertain=true. Лучше короткий честный ответ, чем красивая выдумка.
- Залог всегда 2 000 ₽, возврат после клининга. Чужую сумму не называй.
- Парковку бесплатной не обещай. Питомцы — не во всех, метка в карточке + доплата.
- «Спасибо» → «Пожалуйста)» без нового вопроса. «Подумаем» → «Хорошо, будете готовы, напишите.»
- Техника/вайфай/ТВ во время проживания → спроси адрес, пришли путеводитель.
- Документы/оплата/отмена/жалоба/выбор квартиры → по факту FAQ или escalate менеджеру.
- Эталон стиля — ЭТАЛОННЫЙ ДИАЛОГ №1 и reply_playbook (не копируй даты, имена и факты)."""


def ideal_enabled() -> bool:
    return os.getenv("IDEAL_MANAGER_OFF", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    )


def _stems(text: str) -> frozenset[str]:
    words = re.findall(r"[a-zа-яё0-9]+", (text or "").lower().replace("ё", "е"))
    return frozenset(w[:5] for w in words if len(w) > 1 and w not in _STOP)


def _load_playbook_pairs() -> list[tuple[frozenset[str], str, str]]:
    path = ROOT / "data" / "reply_playbook.jsonl"
    rows: list[tuple[frozenset[str], str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
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
        if 3 <= len(guest) <= 220 and 4 <= len(bot) <= 320:
            rows.append((_stems(guest), guest, bot))
    return rows


@lru_cache(maxsize=2)
def _style_pairs(path_key: str) -> tuple[tuple[frozenset[str], str, str], ...]:
    """Пары гость→бот из playbook + guest-dialogs + ideal_dialog (для тона)."""
    del path_key
    rows: list[tuple[frozenset[str], str, str]] = []
    # curated playbook — первым (правильные ответы на все типы соо)
    rows.extend(_load_playbook_pairs())
    sources = [
        ROOT / "data" / "ideal_dialog_1.md",
        ROOT / "data" / "style_dialogs.md",
        ROOT / "data" / "style_external_tone.md",
        ROOT.parents[0] / "guest-dialogs" / "dialogs.md",
        ROOT / "training" / "dialogs_home24_sample.md",
    ]
    for path in sources:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        guest = ""
        for line in text.splitlines():
            s = line.strip()
            m_g = re.match(
                r"(?:\*\*)?Гость(?:\*\*)?:\s*(.+)$|"
                r"^-\s*[\d.]+\s*·\s*guest:\s*(.+)$",
                s,
                flags=re.I,
            )
            m_b = re.match(
                r"(?:\*\*)?Бот(?:\*\*)?:\s*(.+)$|"
                r"^-\s*[\d.]+\s*·\s*bot:\s*(.+)$",
                s,
                flags=re.I,
            )
            if m_g:
                guest = (m_g.group(1) or m_g.group(2) or "").strip()
                continue
            if m_b and guest:
                bot = (m_b.group(1) or m_b.group(2) or "").strip()
                guest = guest.strip().strip("*").strip()
                bot = bot.strip().strip("*").strip()
                if 4 <= len(guest) <= 220 and 4 <= len(bot) <= 280:
                    if "[КАРТОЧКИ" in bot or "1)" in bot[:8]:
                        guest = ""
                        continue
                    if _BAD_STYLE.search(bot):
                        guest = ""
                        continue
                    rows.append((_stems(guest), guest, bot))
                guest = ""
    # дедуп: первое вхождение выигрывает (playbook раньше)
    seen: set[str] = set()
    out: list[tuple[frozenset[str], str, str]] = []
    for stems, g, b in rows:
        k = g.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append((stems, g, b))
    return tuple(out)


def similar_style(text: str, k: int = 3, max_chars: int = 640) -> str:
    """Блок «Как отвечал живой менеджер» для system prompt."""
    if not ideal_enabled():
        return ""
    if os.getenv("IDEAL_STYLE_OFF", "").strip().lower() in ("1", "true", "yes"):
        return ""
    idx = _style_pairs("v2")
    q = _stems(text)
    if not idx or not q:
        return ""
    scored: list[tuple[float, str, str]] = []
    min_inter = 1 if len(q) <= 2 else 2
    for stems, guest, reply in idx:
        inter = q & stems
        if len(inter) < min_inter:
            continue
        score = len(inter) / (len(q | stems) ** 0.5)
        if guest.casefold() in (text or "").casefold():
            score += 2.0
        scored.append((score, guest, reply))
    scored.sort(key=lambda x: -x[0])
    lines: list[str] = []
    min_score = 0.28 if len(q) <= 2 else 0.45
    for score, guest, reply in scored[:k]:
        if score < min_score:
            continue
        lines.append(f"Гость: «{guest}» → Менеджер: «{reply}»")
    if not lines:
        return ""
    block = (
        "Как отвечал живой менеджер (тон и длина; факты бери из RAG/каталога):\n"
        + "\n".join(lines)
    )
    return block[:max_chars]


def persona_for_llm() -> str:
    if not ideal_enabled():
        return ""
    return PERSONA_BLOCK


def clear_ideal_cache() -> None:
    _style_pairs.cache_clear()
