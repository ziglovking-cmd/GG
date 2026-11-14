# -*- coding: utf-8 -*-
from bot.fact_guard import SAFE_DEPOSIT, SAFE_PETS, audit_message, guard_outbound, repair_message


def test_wrong_deposit_caught_and_fixed():
    bad = "Залог у нас 5 000 ₽, возвращаем после выезда."
    issues = audit_message(bad)
    assert any(i.startswith("deposit_amount:") for i in issues)
    fixed = repair_message(bad, issues)
    assert "2 000" in fixed
    assert "5 000" not in fixed


def test_correct_deposit_ok():
    ok = "Залог 2 000 ₽, во всех квартирах."
    assert audit_message(ok) == []


def test_global_pets_deny_fixed():
    bad = "С животными нельзя. Только без питомцев."
    issues = audit_message(bad)
    assert "pets_global_deny" in issues
    fixed = repair_message(bad, issues)
    assert "не во всех" in fixed.lower() or SAFE_PETS[:20] in fixed


def test_unknown_flat_renamed():
    bad = "Могу предложить «Фантазия999» на завтра."
    issues = audit_message(bad)
    assert any(i.startswith("unknown_flat:") for i in issues)
    fixed = repair_message(bad, issues)
    assert "Фантазия999" not in fixed


def test_guard_outbound_list():
    out = guard_outbound(["Залог 10 000 руб. Ок?"])
    assert len(out) == 1
    assert "2 000" in out[0]
    assert SAFE_DEPOSIT.split(",")[0] in out[0] or "2 000" in out[0]
