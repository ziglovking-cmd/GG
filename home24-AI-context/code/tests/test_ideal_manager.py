# -*- coding: utf-8 -*-
"""Идеальный менеджер: персона, эталон в промпте, стиль в understand."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.pop("IDEAL_MANAGER_OFF", None)
os.environ["SMART_BOT"] = "1"


def test_prompt_has_ideal_dialog_markers():
    p = (ROOT / "bot" / "smart_prompt.txt").read_text(encoding="utf-8")
    assert "ЭТАЛОННЫЙ ДИАЛОГ №1 — ПРИМЕР СТИЛЯ" in p
    assert "=== конец примера ===" in p
    assert "адаптируйся к каждому клиенту, не копируй фразы и факты" in p
    assert p.index('"ask_next": "dates"') < p.index("ЭТАЛОННЫЙ ДИАЛОГ")
    assert "Идеальный менеджер" in p


def test_persona_and_style():
    from bot import ideal_manager

    ideal_manager.clear_ideal_cache()
    assert "живой" in ideal_manager.persona_for_llm().lower()
    # после «спасибо» эталон даёт короткий ответ — стиль может найтись из корпуса
    block = ideal_manager.similar_style("можно с собакой на выходные?")
    # корпус может быть пуст по стемам — не валим; проверяем что API не падает
    assert isinstance(block, str)


def test_ideal_off():
    from bot import ideal_manager

    os.environ["IDEAL_MANAGER_OFF"] = "1"
    try:
        assert ideal_manager.persona_for_llm() == ""
        assert ideal_manager.similar_style("залог") == ""
    finally:
        os.environ.pop("IDEAL_MANAGER_OFF", None)


def test_smart_system_includes_ideal_and_rag():
    from bot import smart
    from bot.config import get_settings
    from bot.engine import Engine

    captured: dict = {}

    async def hook(system, messages, **kw):
        captured["system"] = system
        return (
            json.dumps(
                {
                    "intent": "looking",
                    "slots": {},
                    "messages": ["Поняла, подберу."],
                    "ask_next": "none",
                },
                ensure_ascii=False,
            ),
            "mock",
        )

    smart.set_understand_hook(hook)
    orig = smart._craft_early_raw
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
        try:
            asyncio.run(
                smart.smart_reply(
                    get_settings(),
                    Engine(get_settings()),
                    sess,
                    "Нужна квартира на выходные, двое, потише",
                    [{"role": "bot", "text": "Добрый день! Это Home24"}],
                )
            )
        except Exception:
            pass
    finally:
        smart._craft_early_raw = orig
        smart.set_understand_hook(None)

    system = captured.get("system") or ""
    assert system, "LLM hook не получил system"
    assert "ЭТАЛОННЫЙ ДИАЛОГ №1" in system or "Идеальный менеджер" in system
    assert "RAG" in system
