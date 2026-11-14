# -*- coding: utf-8 -*-
"""script.md ↔ код: каждая реплика скрипта есть в боте, промпты собраны из скрипта.

Если поменяли текст в script.md — поменяйте его в файле из шапки script.md (и наоборот).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot import phrases as P  # noqa: E402
from bot.engine import BUTTONS  # noqa: E402
from bot.faq import FAQ_RULES, match_faq  # noqa: E402

SCRIPT = (ROOT / "script.md").read_text(encoding="utf-8")


def _section(title: str) -> str:
    start = SCRIPT.index(f"## {title}")
    nxt = SCRIPT.find("\n## ", start + 3)
    return SCRIPT[start: nxt if nxt != -1 else len(SCRIPT)]


def _numbered(title: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"(?m)^\d+\.\s+(.+)$", _section(title))]


def _variants(title: str) -> list[list[str]]:
    body = _section(title)
    out: list[list[str]] = []
    for chunk in re.split(r"(?m)^Вариант \d+\.\s*$", body)[1:]:
        paras = [p.strip() for p in re.split(r"\n\s*\n", chunk) if p.strip()]
        out.append(paras)
    return out


def _bullets(title: str) -> list[str]:
    return [l[2:].strip() for l in _section(title).splitlines() if l.startswith("- ")]


def test_outreach_matches_script() -> None:
    want = [" ".join(v) for v in _variants("Рассылка, первое письмо")]
    got = [" ".join(v) for v in P.GREETINGS]
    assert got == want
    assert len(P.OUTREACH_OFFER) == len(P.GREETINGS)


def test_inbound_hello_matches_script() -> None:
    assert [list(v) for v in P.INBOUND_HELLO] == _variants("Гость написал первым")


def test_numbered_pools_match_script() -> None:
    pairs = {
        "Середина разговора, без повторного представления": [v[0] for v in P.HELLO_MID],
        "Как дела": [v[0] for v in P.HOWAREYOU],
        "Спасибо": list(P.THANKS),
        "Даты приняты": [v[0] for v in P.DATES_OK],
        "Гости приняты": [v[0] for v in P.GUESTS_OK],
        "Спросить даты": list(P.LOOKING_START),
        "Пока просто смотрит": [v[0] for v in P.BROWSING_START],
        "Мягко закрыть, без заявки": list(P.SOFT_CLOSE_LEAD),
        "Просит больше не писать": list(P.STOP_ACK),
    }
    for title, got in pairs.items():
        assert got == _numbered(title), title


def test_handoff_line_matches_script() -> None:
    assert P.HANDOFF_LINE in _section("Передача коллеге")
    assert P.HANDOFF == [P.HANDOFF_LINE]


def test_buttons_match_script() -> None:
    for line in _bullets("Кнопки"):
        key, _, labels = line.partition(":")
        # в подписях бывают запятые («Да, ищу квартиру») — сверяем строку целиком
        assert ", ".join(b[0] for b in BUTTONS[key.strip()]) == labels.strip(), key


def test_keyword_answers_match_script() -> None:
    body = _section("Ответы по словам гостя")
    blocks = re.split(r"\n(?=Если в сообщении есть: )", body)[1:]
    assert len(blocks) == len(FAQ_RULES)
    for block, (keys, msgs) in zip(blocks, FAQ_RULES):
        first, _, rest = block.partition("\n")
        want_keys = [k.strip() for k in first.split(":", 1)[1].split(",") if k.strip()]
        assert [k.strip() for k in keys] == want_keys
        want_msgs = [p.strip() for p in re.split(r"\n\s*\n", rest.strip()) if p.strip()]
        assert msgs == want_msgs, keys[0]


def test_life_situations_match_script() -> None:
    from bot.life import _RULES

    assert [hit.line for _rx, hit in _RULES] == _bullets("Ситуации проживания")


def test_short_facts_match_script() -> None:
    from bot.smart import _NAIVE_FACTS

    want = _bullets("Короткие факты")
    got = [line for _rx, line in _NAIVE_FACTS]
    assert len(got) == len(want)
    for i, (g, w) in enumerate(zip(got, want)):
        if i == 1:  # «вы бот?» — честный ответ из «Ответы по словам» и промпта
            assert "виртуальный помощник" in g
            continue
        assert g == w


def test_prompts_built_from_script() -> None:
    smart = (ROOT / "bot" / "smart_prompt.txt").read_text(encoding="utf-8")
    edge = (ROOT / "bot" / "edge_prompt.txt").read_text(encoding="utf-8")
    prompt = SCRIPT[SCRIPT.index("# Home24 — менеджер, которая пишет"): SCRIPT.index("## Если обычная реплика не собралась")]
    for line in prompt.splitlines():
        line = line.strip()
        if not line or line.startswith("Не спрашивай даты/гостей/район"):
            continue
        assert line in smart, line
    assert "## Согласие и отказ на предложение услуг" in smart
    assert "Балакиревский пер, 23" in smart and "Карта квартир" in smart
    fallback = SCRIPT[SCRIPT.index("# Home24 — крайний ответ."):].strip()
    assert edge.strip() == fallback


def test_polite_manager_is_not_handoff() -> None:
    msgs, special = match_faq("Уважаемый менеджер, ответьте мне")
    assert special is None and "я тут" in msgs[0].lower()
    assert match_faq("позовите менеджера")[1] == "escalate"
    assert match_faq("нужна квартира на 3 человека") is None


def test_yes_after_offer_tells_facts_not_dates() -> None:
    for idx, topic in enumerate(P.OUTREACH_OFFER):
        sess = {"name": "Мария", "context": {}}
        P._GREET_RR, P._GREET_RECENT = idx - 1, []
        _msgs, upd = P.greeting_msgs(sess, outreach=True)
        sess.update(upd)
        msgs, ctx, step = P.offer_reply(dict(sess), "Да")
        line = msgs[0].lower()
        if topic == "need":
            assert "дат" in line or "заезд" in line or "район" in line
            assert step == "await_district"
        else:
            assert "дат" not in line
            assert "хотите, подберу" in line
            assert re.search(r"балл|проектор|украс", line)
            assert step == "await_dates"
        assert ctx["offer_open"] is False
        refused = P.offer_reply(dict(sess), "нет")
        assert refused and refused[2] == "done"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
