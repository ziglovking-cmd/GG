# Home24 v9.1 — smart bot fixes (changelog)

Based on v9.0. Same LLM-first brain + script safety; eight concrete reply/slot bugs fixed before ship.

## Fixes

1. **Kids count as guests** — «нас двое и ребёнок» → exact `3`, never downgraded to `1–2`. Date fragments like «на 12» no longer become guest counts when «N гостя» is present.
2. **Correction** — «не 3 а 4 человека» → explicit «Поняла, 4 человека» + capacity re-pick (drop offers that don’t fit).
3. **Pets** — multi-intent «можно с собакой?» answers from FAQ facts (согласование / не на всех) + manager confirms for the chosen apartment. No «отметила ваш запрос».
4. **Summaries** — varied leads (`Записала` / `Приняла` / `Отметила` / …); delta-only when one slot changed; no full summary + same cards when nothing changed. Dropped robotic «Записала всё».
5. **Weather** — brief «не проверяю» + polite steer back; no invented °C / small talk facts.
6. **Rude guest** — short apology + concrete next step; no pointless escalate on «тупите».
7. **Pick «давайте 1»** — confirm apartment **by name**, then returning question or booking handoff; no card resend.
8. **Production smart** — `SMART_BOT=1` default in `.env.example` and `bot/smart.py`; startup logs active understand model (`log_smart_startup`). Gemini defaults: `gemini-3.8-flash` (2.0/2.5 retired for new keys).

## Tests

```bash
python tests/test_v9_1_fixes.py          # 8 items (+ crib FAQ, date-vs-guests)
python tests/test_v9_smart_dialogs.py    # 27 mocked scenarios
python scripts/eval_smart_dialogs.py    # live AI1/AI2 keys
```

## Eval mode (this ship)

The five dialogs in the agent report were re-run with **real LLM calls** (`scripts/eval_smart_dialogs.py`, understand providers from `.env`: Mistral small → Gemini 3.8 → ministral fallback). Unit/scenario suites use **mocks**. Transcript: `/opt/cursor/artifacts/home24_v9_1_eval.log`.

Startup log example: `smart brain ON · understand=mini-smart/mistral-small-latest · fallback=flash-smart/gemini-3.8-flash, …`

## Artifacts

- `/opt/cursor/artifacts/home24_bot_windows_v9_1.zip`
- `/opt/cursor/artifacts/HOME24_V9_1_CHANGELOG.md`
- `/opt/cursor/artifacts/home24_v9_1_eval.log`
