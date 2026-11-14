# Home24 v9.2 — district model + lean LLM turns

Based on v9.1.

## Fixes

1. **District / area model** — each apartment gets `is_central`, `is_calm`, `zone` (center|calm|other). Centre ≈ Garden Ring / TTK + nearby metros (Бауманская, Ленинский/Гагаринский, Бутырская, Лефортово, Хорошёво, Нижегородская…). Прокшино / Коммунарка / Одинцово / etc. are never centre. Hard filter by requested zone; if empty — honest note + nearest options. «Почему подходит» uses real metro/zone; never claims «центр» for outer flats.
2. **One short summary** — max 1 summary line + cards; 1–2 bubbles total. No duplicate «Отметила…» + «Поняла…», no invented parking/metro-vs-price. Dates normalized to «с 1 по 7 января»; guests «3 человека».
3. **Correction** — if current offers still fit new guest count, confirm and ask pick; full cards only when the set changes.
4. **LLM robustness** — one understand call per message; short relevant catalog subset; retry once with backoff on 429/503; chain `mistral-small → ministral-8b → gemini-3.5-flash-lite / flash-lite-latest`; soft dead TTL for rate limits; `reply_path` logged per turn (`smart:model` or `script`).
5. **Eval** — paced real runs (`--pace 12`) report path % LLM vs script.

## Tests

```bash
python tests/test_v9_2_district_llm.py
python tests/test_v9_1_fixes.py
python tests/test_v9_smart_dialogs.py
EVAL_PACE_SEC=12 python scripts/eval_smart_dialogs.py
```

## Artifacts

- `/opt/cursor/artifacts/home24_bot_windows_v9_2.zip`
- `/opt/cursor/artifacts/HOME24_V9_2_CHANGELOG.md`
- `/opt/cursor/artifacts/home24_v9_2_eval.log`

## Eval result (real LLM, paced)

- Providers: `mistral-small → ministral-8b → gemini-3.5-flash-lite / flash-lite-latest`
- Pace: 14s between guest turns
- **PATH STATS: smart=13 script=0 (100% LLM / rule-smart paths, 0% script fallback)**
- Transcript: `/opt/cursor/artifacts/home24_v9_2_eval.log`
- Note: `gemini-3.8-flash` exists but often 503; working defaults are `gemini-3.5-flash-lite` + `gemini-flash-lite-latest`.
