# -*- coding: utf-8 -*-
"""Продление проживания — коллега уточнит, свободна ли квартира после гостя."""

from __future__ import annotations

from bot.life import match_life


def test_extend_stay_mentions_colleague_and_checkout() -> None:
    for text in (
        "можно ли продлить проживание?",
        "Хотим продлить на день",
        "Можно остаться ещё на ночь?",
        "продление возможно?",
    ):
        hit = match_life(text)
        assert hit is not None, text
        assert hit.kind == "extend"
        assert hit.escalate is True
        assert "коллега" in hit.line.lower()
        assert "заезда" in hit.line.lower()
        assert "продлить" in hit.line.lower()
