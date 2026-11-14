# Home24 v9.3 — small polish on v9.2

## Changes

1. **Greeting** — bare «привет» → one bubble: «Здравствуйте! Подскажите… на какие даты…». No second duplicate dates question; no informal «Привет».
2. **Weekday ranges** — «на пятницу-воскресенье» / «пятницу-воскресенье» / «с пятницы по воскресенье» → `с пятницы по воскресенье` (not bare «пятница»). «на выходные» and «с 1 по 7…» unchanged. Tests in `tests/test_v9_3_small_fixes.py`.
3. **Area labels** — apartments with catalog `area=Москва` show metro/district (`Хорошёво`, `Бутырская`, `Лефортово`, `Коммунарка`, …) on the card title and in «Почему подходит», via `area_label`.
4. **mistral-small 429** — on rate-limit, skip that provider for **10 minutes** (no retry delay) and go straight to `ministral-8b` (then Gemini lite).

## Tests

```bash
python tests/test_v9_3_small_fixes.py
python tests/test_v9_2_district_llm.py
python tests/test_v9_1_fixes.py
python tests/test_v9_smart_dialogs.py
```

## Artifacts

- `/opt/cursor/artifacts/home24_bot_windows_v9_3.zip`
- `/opt/cursor/artifacts/HOME24_V9_3_CHANGELOG.md`
