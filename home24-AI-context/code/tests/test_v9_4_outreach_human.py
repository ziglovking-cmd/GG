# -*- coding: utf-8 -*-
"""v9.4 — рассылка звучит как живой менеджер, не как шаблон-спам."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.phrases import (
    GREETINGS,
    greeting_msgs,
    sample_outreach_texts,
    tod_greeting,
)


BANNED = (
    "по-человечески",
    "на связи",
    "решила написать",
    "соскучились",
    "напомнила о себе",
    "напоминаю:",
    "напоминаю,",
    "пересекались",
    "удобно ли коротко",
    "рады бывшим",
    "рада снова",
    "приятно познакомиться",
    "меня зовут",
    "просто смотрите",
    "пока без планов",
    "посуточные апартаменты в москве. вы у нас уже останавливались. планируете поездку",
)


def test_greetings_human_variety() -> None:
    assert len(GREETINGS) >= 4
    bodies: set[str] = set()
    for variant in GREETINGS:
        blob = " ".join(variant)
        low = blob.lower()
        assert "{tod}" in blob
        assert "home24" in low
        assert any(
            m in low
            for m in (
                "останавливал",
                "бывали",
                "жили",
                "гостем",
                "гост",
                "жили раньше",
            )
        ), variant
        for b in BANNED:
            assert b not in low, (b, variant)
        # не буклет: нет длинной цепочки «бренд — определение — вы были — CTA»
        assert not re.search(
            r"посуточн\w+\s+апартамент\w+\s+в\s+москве\.\s*вы\s+у\s+нас",
            low,
        ), variant
        # уникальное «тело» после представления
        tail = re.sub(r"^\{tod\}\{name_part\}!\s*", "", blob.strip())
        bodies.add(tail[:48])
    assert len(bodies) == len(GREETINGS)


def test_sample_texts_filled() -> None:
    samples = sample_outreach_texts(name="Мария", hour=14)
    assert len(samples) == len(GREETINGS)
    for s in samples:
        assert "Мария" in s
        assert "Home24" in s
        assert "{tod}" not in s and "{name_part}" not in s
        assert s.startswith("Добрый день")
    anon = sample_outreach_texts(name="Клиент", hour=9)
    assert all("Клиент" not in s for s in anon)
    assert all(s.startswith("Доброе утро") for s in anon)


def test_outreach_greeting_no_client_placeholder() -> None:
    msgs, upd = greeting_msgs({"name": "Клиент", "context": {}}, outreach=True)
    blob = "\n".join(msgs)
    assert "Клиент" not in blob
    assert upd["context"].get("outreach") is True
    assert tod_greeting(hour=20) == "Добрый вечер"


def test_all() -> None:
    test_greetings_human_variety()
    test_sample_texts_filled()
    test_outreach_greeting_no_client_placeholder()
    print("ok v9.4 outreach human")


if __name__ == "__main__":
    test_all()
