# -*- coding: utf-8 -*-
"""Playbook: ответы на все типы соо + приоритет над кривыми примерами."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def test_playbook_file_covers_core_intents():
    import json

    path = ROOT / "data" / "reply_playbook.jsonl"
    assert path.is_file()
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) >= 80
    intents = {r["intent"] for r in rows}
    for need in (
        "deposit",
        "pets",
        "parking",
        "checkin",
        "docs",
        "tech",
        "think",
        "human",
        "thanks",
        "pick",
        "correction",
        "already_said",
    ):
        assert need in intents, need


def test_examples_prefer_playbook_deposit_and_pets():
    from bot import examples

    examples.clear_examples_cache()
    assert examples.playbook_count() >= 80

    dep = examples.similar_examples("какой залог?")
    assert "2 000" in dep or "2000" in dep
    assert "не везде" not in dep.lower()

    pets = examples.similar_examples("можно с собакой?")
    assert "питомц" in pets.lower()
    assert "скажет менеджер" not in pets.lower()

    park = examples.similar_examples("бесплатная парковка есть?")
    assert "парков" in park.lower()
    assert "бесплатн" not in park.split("→")[-1].lower() or "не обеща" in park.lower()


def test_ideal_style_filters_bad_and_uses_playbook():
    from bot import ideal_manager

    ideal_manager.clear_ideal_cache()
    block = ideal_manager.similar_style("какой залог у вас")
    assert isinstance(block, str)
    if block:
        assert "2 000" in block or "2000" in block or "Залог" in block
        assert "не везде" not in block.lower()

    persona = ideal_manager.persona_for_llm()
    assert "любое соо" in persona.lower() or "Воронка" in persona


def test_smart_prompt_has_matrix():
    text = (ROOT / "bot" / "smart_prompt.txt").read_text(encoding="utf-8")
    assert "Ответ на любое соо (матрица)" in text
    assert "техника во время проживания" in text.lower() or "ТВ, бойлер" in text
