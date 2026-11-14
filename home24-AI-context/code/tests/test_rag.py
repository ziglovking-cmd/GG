# -*- coding: utf-8 -*-
"""RAG grounding: индекс, retrieval, антигаллюцинации в промпте."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.pop("RAG_OFF", None)
os.environ["SMART_BOT"] = "1"

from bot import rag  # noqa: E402


def setup_function() -> None:
    rag.clear_rag_cache()
    os.environ.pop("RAG_OFF", None)


def test_index_has_core_sources():
    stats = rag.index_stats()
    assert stats["enabled"] is True
    assert stats["total"] >= 40
    by = stats["by_source"]
    assert by.get("faq", 0) >= 10
    assert by.get("fact", 0) >= 5
    assert by.get("policy", 0) >= 3
    # карта/адреса из script.md
    assert by.get("map", 0) + by.get("address", 0) + by.get("district", 0) >= 10


def test_retrieve_deposit():
    hits = rag.retrieve("какой у вас залог?")
    blob = " ".join(h.text.lower() for h in hits)
    assert hits, "ожидали чанки про залог"
    assert "2 000" in blob or "2000" in blob or "залог" in blob


def test_retrieve_pets():
    hits = rag.retrieve("можно с собакой?")
    blob = " ".join(h.text.lower() for h in hits)
    assert hits
    assert any(w in blob for w in ("животн", "собак", "питом", "кошк"))


def test_retrieve_checkin():
    hits = rag.retrieve("во сколько заезд?")
    blob = " ".join(h.text.lower() for h in hits)
    assert "15" in blob or "заезд" in blob


def test_retrieve_arbat_policy():
    hits = rag.retrieve("есть что-то на Арбате?")
    blob = " ".join(h.text.lower() for h in hits)
    assert "арбат" in blob
    assert any(h.source == "policy" or "нет" in h.text.lower() for h in hits)


def test_retrieve_metro_for_apartment():
    hits = rag.retrieve("Чехов где находится, какое метро?", favorite="Чехов")
    blob = " ".join(h.text for h in hits)
    assert "Чехов" in blob or "чехов" in blob.lower()
    assert "Бауман" in blob or "Балакирев" in blob or "бауман" in blob.lower()


def test_rag_block_anti_hallucination_header():
    block = rag.rag_context_for_llm("сколько залог и можно ли курить?")
    assert "RAG" in block
    assert "ТОЛЬКО" in block or "только" in block.lower()
    assert "залог" in block.lower() or "курить" in block.lower() or "курим" in block.lower()


def test_rag_off_returns_empty():
    os.environ["RAG_OFF"] = "1"
    try:
        assert rag.rag_context_for_llm("залог") == ""
        assert rag.retrieve("залог") == []
    finally:
        os.environ.pop("RAG_OFF", None)


def test_smart_prompt_includes_rag():
    """smart_reply прокидывает RAG-блок в system для understand."""
    from bot import smart
    from bot.engine import Engine
    from bot.config import get_settings

    captured: dict = {}

    async def hook(system, messages, **kw):
        captured["system"] = system
        return (
            json.dumps(
                {
                    "intent": "faq",
                    "slots": {},
                    "messages": ["Поняла, отвечу по фактам."],
                    "ask_next": "none",
                    "escalate": False,
                },
                ensure_ascii=False,
            ),
            "mock",
        )

    smart.set_understand_hook(hook)
    # обходим script-rules, чтобы дойти до LLM+RAG
    orig_early = smart._craft_early_raw
    smart._craft_early_raw = lambda *a, **k: None  # type: ignore
    try:
        sess = {
            "name": "Мария",
            "step": "await_intent",
            "dates": "",
            "guests": "",
            "district": "",
            "returning": "",
            "favorite": "",
            "handed_off": 0,
            "context": {"outreach": True, "greeted": True},
        }
        s = get_settings()
        try:
            asyncio.run(
                smart.smart_reply(
                    s,
                    Engine(s),
                    sess,
                    "Подскажите нюанс: балллы лояльности суммируются с романтическим пакетом?",
                    [{"role": "bot", "text": "Добрый день! Это Home24"}],
                )
            )
        except Exception:
            # пост-LLM путь в архиве мог быть бит санитизацией — RAG уже в system
            pass
    finally:
        smart._craft_early_raw = orig_early
        smart.set_understand_hook(None)

    system = captured.get("system") or ""
    assert system, "understand hook не получил system — ход не дошёл до LLM"
    assert "RAG" in system
    assert "uncertain" in system.lower() or "не выдумывай" in system.lower()
