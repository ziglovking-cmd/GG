# Home24 v10.29 · 20.11.2026

## Цель
Обучить бота отвечать на **любое** сообщение гостя «на все 100»: не только воронка бронь, а FAQ, коррекции, техника, документы, «подумаем», выбор квартиры — без галлюцинаций и без кривых исторических примеров.

## Что сделано
1. **`data/reply_playbook.jsonl`** — curated эталон гость→менеджер (~95 пар) на все типы соо: залог, питомцы, парковка, заезд/выезд, вайфай/техника, документы, акции, выбор квартиры, коррекции, «уже писал», thank/think/stop и т.д.
2. **`bot/examples.py`** — playbook всегда приоритетнее `dialogs_home24.jsonl`; отфильтрованы плохие ответы («залог не везде», «скажет менеджер», бесплатная парковка, чужой залог).
3. **`bot/ideal_manager.py`** — playbook первым в стиле; фильтр плохих реплик из guest-dialogs; персона с матрицей «на любое соо».
4. **`smart_prompt.txt` / `edge_prompt.txt`** — явная матрица типов сообщений (слот / FAQ / escalate / уточню).
5. Починен синтаксис `training/generate_dialogs.py` (после санитизации `[REDACTED]`).

## Деплой
Скопировать на `/opt/home24`:
- `bot/examples.py`, `bot/ideal_manager.py`, `bot/smart_prompt.txt`, `bot/edge_prompt.txt`, `bot/version.py`
- `data/reply_playbook.jsonl`
- `tests/test_reply_playbook.py`, `HOME24_V10_29_CHANGELOG.md`

`systemctl restart home24-bot home24-dash`
