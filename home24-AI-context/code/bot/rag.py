# -*- coding: utf-8 -*-
"""RAG grounding для Home24 LLM: только проверенные факты из скрипта/FAQ/карты.

Без тяжёлых зависимостей (chromadb / embeddings): TF‑IDF по стемам, как в
``bot.examples``. Цель — не дать модели выдумать цену, метро, залог, животных
или адрес, которого нет в корпусе.

Отключить: ``RAG_OFF=1``. Свой скрипт: ``SCRIPT_PATH``. Топ‑k: ``RAG_TOP_K``
(по умолчанию 6). Макс. символов блока: ``RAG_MAX_CHARS`` (по умолчанию 1600).
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("home24.rag")

ROOT = Path(__file__).resolve().parents[1]

_STOP = {
    "а",
    "и",
    "в",
    "на",
    "с",
    "у",
    "по",
    "к",
    "за",
    "из",
    "о",
    "не",
    "но",
    "да",
    "ну",
    "же",
    "ли",
    "то",
    "это",
    "мы",
    "вы",
    "я",
    "нас",
    "вас",
    "мне",
    "нам",
    "есть",
    "можно",
    "будет",
    "или",
    "что",
    "как",
    "если",
    "для",
    "при",
    "без",
    "ещё",
    "еще",
    "уже",
    "только",
    "здравствуйте",
    "добрый",
    "день",
    "вечер",
    "привет",
    "пожалуйста",
    "спасибо",
}

# Жёсткие политики — всегда доступны retrieval'у (антигаллюцинации).
_POLICY_CHUNKS: tuple[tuple[str, str, str], ...] = (
    (
        "policy:prices",
        "Цены и даты",
        "Цены и свободные даты не выдумывать. Цифры цены — только из каталога/TravelLine. "
        "Если цены нет — сказать, что менеджер уточнит.",
    ),
    (
        "policy:invent",
        "Не выдумывать",
        "Не выдумывать квартиры, адреса, метро, парковку, животных, залог и услуги. "
        "Если факта нет в блоке RAG — uncertain=true или escalate, без догадок.",
    ),
    (
        "policy:cards",
        "Карточки",
        "Карточки квартир, цены на них и следующий вопрос воронки пишет система. "
        "В messages не обещать «покажу / пришлю / подобрала».",
    ),
    (
        "policy:arbat",
        "Арбат",
        "На Новом Арбате и Садовом квартир Home24 нет. Не предлагать Арбат как наличие.",
    ),
)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str  # faq | life | fact | map | address | district | catalog | policy
    title: str
    text: str
    stems: frozenset[str]


def rag_enabled() -> bool:
    return os.getenv("RAG_OFF", "").strip().lower() not in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(float((os.getenv(name) or str(default)).strip()))
    except Exception:
        return default


def _stems(text: str) -> frozenset[str]:
    """Стемы как в ``bot.examples`` (5 символов) + короткий префикс 4 для склонений."""
    words = re.findall(r"[a-zа-яё0-9]+", (text or "").lower().replace("ё", "е"))
    out: set[str] = set()
    for w in words:
        if len(w) <= 1 or w in _STOP:
            continue
        out.add(w[:5])
        if len(w) >= 6:
            out.add(w[:4])
    return frozenset(out)


def _script_path() -> Path:
    raw = (os.getenv("SCRIPT_PATH") or "script.md").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    return p


def _section(md: str, heading: str) -> str:
    """Текст от ``## heading`` до следующего ``## ``."""
    pat = re.compile(
        rf"(?ms)^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s+|\Z)"
    )
    m = pat.search(md)
    return m.group(1).strip() if m else ""


def _bullets(block: str) -> list[str]:
    out: list[str] = []
    for line in (block or "").splitlines():
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s.startswith("* "):
            out.append(s[2:].strip())
    return out


def _chunks_from_faq() -> list[Chunk]:
    try:
        from bot.faq import FAQ_RULES
    except Exception:
        return []
    rows: list[Chunk] = []
    for i, (keys, msgs) in enumerate(FAQ_RULES):
        if not msgs:
            continue
        topic = ", ".join(keys[:4])
        body = " ".join(str(m) for m in msgs if m).strip()
        if not body:
            continue
        text = f"Тема: {topic}. Ответ: {body}"
        rows.append(
            Chunk(
                chunk_id=f"faq:{i}",
                source="faq",
                title=topic[:80],
                text=text,
                stems=_stems(topic + " " + body),
            )
        )
    return rows


def _chunks_from_life() -> list[Chunk]:
    try:
        from bot.life import _RULES
    except Exception:
        return []
    rows: list[Chunk] = []
    for i, (pat, hit) in enumerate(_RULES):
        line = getattr(hit, "line", "") or ""
        if not line:
            continue
        # pattern.pattern даёт ключевые слова ситуации
        keys = re.sub(r"\(\?i\)|\\s\*|\\b|[()|?+*]", " ", getattr(pat, "pattern", ""))
        keys = re.sub(r"\s+", " ", keys).strip()[:120]
        kind = getattr(hit, "kind", "fact") or "fact"
        esc = " Передать менеджеру." if getattr(hit, "escalate", False) else ""
        text = f"Ситуация ({kind}): {keys}. Ответ: {line}{esc}"
        rows.append(
            Chunk(
                chunk_id=f"life:{i}",
                source="life",
                title=f"life/{kind}",
                text=text,
                stems=_stems(keys + " " + line),
            )
        )
    return rows


def _chunks_from_script(md: str) -> list[Chunk]:
    rows: list[Chunk] = []
    facts = _bullets(_section(md, "Короткие факты"))
    for i, f in enumerate(facts):
        if len(f) < 8:
            continue
        rows.append(
            Chunk(
                chunk_id=f"fact:{i}",
                source="fact",
                title="короткий факт",
                text=f,
                stems=_stems(f),
            )
        )

    # Карта + адреса + районы лежат внутри «## Карта квартир» до «## Промпт»
    map_block = _section(md, "Карта квартир")
    if map_block:
        # подблоки без ## — режем по заголовкам «Адреса:» / «Районы»
        parts = re.split(
            r"(?m)^(Адреса:|Районы\s*\([^)]*\):|Локации\s*/\s*метро:|Типы района[^:]*:)\s*$",
            map_block,
        )
        # parts[0] = intro map lines; then label, body, label, body...
        intro = parts[0] if parts else map_block
        for i, line in enumerate(_bullets(intro)):
            if len(line) < 12:
                continue
            rows.append(
                Chunk(
                    chunk_id=f"map:{i}",
                    source="map",
                    title="карта квартир",
                    text=line,
                    stems=_stems(line),
                )
            )
        label = ""
        for piece in parts[1:]:
            if piece.rstrip(":").startswith(
                ("Адреса", "Районы", "Локации", "Типы района")
            ) or piece.startswith("Адреса") or piece.startswith("Районы") or piece.startswith(
                "Локации"
            ) or piece.startswith("Типы"):
                label = piece.strip().rstrip(":")
                continue
            src = (
                "address"
                if label.lower().startswith("адрес")
                else "district"
                if "район" in label.lower() or "локац" in label.lower() or "тип" in label.lower()
                else "map"
            )
            for j, line in enumerate(_bullets(piece)):
                if len(line) < 8:
                    continue
                rows.append(
                    Chunk(
                        chunk_id=f"{src}:{label[:20]}:{j}",
                        source=src,
                        title=label[:60] or src,
                        text=line,
                        stems=_stems(line),
                    )
                )
    return rows


def _chunks_from_catalog() -> list[Chunk]:
    try:
        from bot.catalog import DEFAULT_PATH, _connect, _row_public
    except Exception:
        return []
    con = None
    try:
        con = _connect(DEFAULT_PATH)
        if not con:
            return []
        rows_db = [_row_public(r) for r in con.execute("SELECT * FROM objects")]
    except Exception:
        return []
    finally:
        try:
            if con is not None:
                con.close()
        except Exception:
            pass
    out: list[Chunk] = []
    for i, o in enumerate(rows_db[:120]):
        name = (o.get("name") or "").strip()
        if not name:
            continue
        bits = [
            f"Квартира «{name}»",
            o.get("area") or "",
            o.get("metro") or "",
            f"до {o['capacity']} гостей" if o.get("capacity") else "",
        ]
        try:
            from bot.catalog import format_price_line

            bits.append(format_price_line(o))
        except Exception:
            pass
        text = " · ".join(b for b in bits if b)
        out.append(
            Chunk(
                chunk_id=f"catalog:{i}:{name}",
                source="catalog",
                title=name,
                text=text,
                stems=_stems(text),
            )
        )
    return out


def _policy_chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id=cid,
            source="policy",
            title=title,
            text=text,
            stems=_stems(title + " " + text),
        )
        for cid, title, text in _POLICY_CHUNKS
    ]


@lru_cache(maxsize=4)
def build_index(script_mtime: float = 0.0) -> tuple[Chunk, ...]:
    """Индекс корпуса. ``script_mtime`` в ключе — автообновление после правки script.md."""
    del script_mtime  # только для ключа кэша
    chunks: list[Chunk] = []
    chunks.extend(_policy_chunks())
    chunks.extend(_chunks_from_faq())
    chunks.extend(_chunks_from_life())
    try:
        md = _script_path().read_text(encoding="utf-8")
        chunks.extend(_chunks_from_script(md))
    except OSError as e:
        logger.info("rag: script not read: %s", e)
    chunks.extend(_chunks_from_catalog())
    # дедуп по тексту
    seen: set[str] = set()
    uniq: list[Chunk] = []
    for c in chunks:
        key = c.text.strip().lower()
        if key in seen or len(key) < 8:
            continue
        seen.add(key)
        uniq.append(c)
    logger.info("rag: indexed %s chunks", len(uniq))
    return tuple(uniq)


def clear_rag_cache() -> None:
    build_index.cache_clear()
    _idf.cache_clear()


@lru_cache(maxsize=4)
def _idf(script_mtime: float = 0.0) -> dict[str, float]:
    idx = build_index(script_mtime)
    df: dict[str, int] = {}
    for c in idx:
        for w in c.stems:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(idx))
    return {w: math.log(1 + n / c) for w, c in df.items()}


def _mtime_key() -> float:
    try:
        return float(_script_path().stat().st_mtime)
    except OSError:
        return 0.0


def _boost(chunk: Chunk, query: str, *, district: str | None, favorite: str | None) -> float:
    q = (query or "").lower().replace("ё", "е")
    b = 0.0
    if chunk.source == "policy":
        # политики поднимаем при вопросах про цену/выдумки/арбат
        if re.search(r"(?i)цен|стоит|руб|₽|свободн|дат", q) and "цен" in chunk.chunk_id:
            b += 2.5
        if re.search(r"(?i)арбат|садов", q) and "arbat" in chunk.chunk_id:
            b += 3.0
        if re.search(r"(?i)выдум|не знаю|а вдруг", q):
            b += 1.0
    title_l = chunk.title.lower().replace("ё", "е")
    text_l = chunk.text.lower().replace("ё", "е")
    if favorite:
        fav = favorite.lower().replace("ё", "е")
        if fav and (fav in text_l or fav in title_l):
            b += 4.0
    if district:
        dist = district.lower().replace("ё", "е")
        if dist and (dist in text_l or dist[:5] in text_l):
            b += 1.8
    # прямое вхождение редких маркеров
    for marker, extra in (
        (r"залог|депозит", 2.2),
        (r"животн|собак|кошк|питом", 2.2),
        (r"заезд|выезд|чек.?ин|чек.?аут", 1.8),
        (r"парков", 1.8),
        (r"крипт|bitcoin|usdt", 2.5),
        (r"метро|адрес|где\s+наход", 1.5),
        (r"вайфай|wifi|wi-fi", 2.0),
        (r"курить|кури", 2.0),
        (r"документа|отчёт|отчет|чек", 1.6),
    ):
        if re.search(marker, q, flags=re.I) and re.search(marker, text_l, flags=re.I):
            b += extra
    return b


def retrieve(
    query: str,
    *,
    k: int | None = None,
    district: str | None = None,
    favorite: str | None = None,
    sources: Iterable[str] | None = None,
    min_score: float = 1.4,
) -> list[Chunk]:
    """Топ‑k релевантных чанков под реплику гостя."""
    if not rag_enabled():
        return []
    q = (query or "").strip()
    if not q:
        return []
    top_k = k if k is not None else _env_int("RAG_TOP_K", 6)
    top_k = max(1, min(top_k, 16))
    mtime = _mtime_key()
    idx = build_index(mtime)
    idf = _idf(mtime)
    q_stems = _stems(q)
    if not idx or not q_stems:
        return []
    allow = set(sources) if sources else None
    scored: list[tuple[float, Chunk]] = []
    for c in idx:
        if allow is not None and c.source not in allow:
            continue
        inter = q_stems & c.stems
        if not inter and not _boost(c, q, district=district, favorite=favorite):
            continue
        base = sum(idf.get(w, 1.0) for w in inter) / (len(q_stems | c.stems) ** 0.5)
        score = base + _boost(c, q, district=district, favorite=favorite)
        # одно частое слово без буста — шум; сильный topical boost пропускаем
        if len(inter) < 2 and score < 3.0 and not favorite and _boost(
            c, q, district=district, favorite=favorite
        ) < 2.0:
            continue
        scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return []
    best = scored[0][0]
    out: list[Chunk] = []
    seen_src_title: set[str] = set()
    for score, c in scored:
        if score < min_score and score < 0.55 * best:
            continue
        dedupe = f"{c.source}:{c.title[:40]}:{c.text[:60]}"
        if dedupe in seen_src_title:
            continue
        seen_src_title.add(dedupe)
        out.append(c)
        if len(out) >= top_k:
            break
    return out


def format_rag_block(
    chunks: list[Chunk],
    *,
    max_chars: int | None = None,
) -> str:
    if not chunks:
        return ""
    limit = max_chars if max_chars is not None else _env_int("RAG_MAX_CHARS", 1600)
    lines = [
        "RAG — проверенные факты (единственный источник правды для ответа гостю):",
        "Используй ТОЛЬКО эти факты + слоты сессии + каталог ниже. Нет факта → uncertain=true, не додумывай.",
    ]
    for i, c in enumerate(chunks, 1):
        lines.append(f"{i}. [{c.source}] {c.text}")
    block = "\n".join(lines)
    if len(block) > limit:
        block = block[: limit - 1].rstrip() + "…"
    return block


def rag_context_for_llm(
    guest_text: str,
    *,
    district: str | None = None,
    favorite: str | None = None,
    guests: str | None = None,
    k: int | None = None,
) -> str:
    """Готовый блок для system prompt. Пустая строка, если RAG выключен/пусто."""
    del guests  # зарезервировано под будущий фильтр вместимости
    if not rag_enabled():
        return ""
    chunks = retrieve(
        guest_text,
        k=k,
        district=district,
        favorite=favorite,
    )
    # если вопрос «фактовый», а retrieval слабый — всё равно подтянуть policy
    if not chunks:
        chunks = [c for c in build_index(_mtime_key()) if c.source == "policy"][:2]
    return format_rag_block(chunks)


def index_stats() -> dict[str, Any]:
    idx = build_index(_mtime_key())
    by: dict[str, int] = {}
    for c in idx:
        by[c.source] = by.get(c.source, 0) + 1
    return {"total": len(idx), "by_source": by, "enabled": rag_enabled()}
