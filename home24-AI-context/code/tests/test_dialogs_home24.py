# -*- coding: utf-8 -*-
"""Проверочные диалоги Home24 офлайн (правила + скрипт, без ИИ).

Сами диалоги — tests/dialogs_home24.py. Живой прогон с Groq: scripts/eval_home24_dialogs.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("HOME24_FORCE_SCRIPT", None)

from bot import smart as smart_mod  # noqa: E402
from scripts.eval_home24_dialogs import run_dialog  # noqa: E402
from tests.dialogs_home24 import DIALOGS  # noqa: E402


async def _no_llm(system, messages):
    return None


@pytest.mark.parametrize("dialog", DIALOGS, ids=[d["title"] for d in DIALOGS])
def test_dialog(dialog) -> None:
    smart_mod.set_understand_hook(_no_llm)
    try:
        result = asyncio.run(run_dialog(dialog))
    finally:
        smart_mod.set_understand_hook(None)
    problems = [
        f"{t['guest']!r} → {t['bot']!r}: {p}"
        for t in result["turns"]
        for p in t["problems"]
    ]
    assert not problems, "\n".join(problems)
