# Home24 v8.4 — changelog (RU)

Архив: `/opt/cursor/artifacts/home24_bot_windows_v8_4.zip`  
Полный список текстов: `/opt/cursor/artifacts/HOME24_V8_4_TEXTS.md`

## Что нового

Полная перепись **всех клиентских** текстов бота в одном тоне: тёплый менеджер посуточной аренды, всегда **«вы»**, коротко, естественно, ≤1 эмодзи на сообщение.

Убраны клише: «по-человечески», «на связи», «решила написать», «соскучились», «без суеты», «подстроюсь».  
Нет «Клиент», нет выдуманных цен/скидок/срочности, нет повторного приветствия mid-dialog после opener (логика v8.3 сохранена).

### Outreach openers

- 12 вариантов, 1 пузырь, 1–3 коротких фразы  
- `{tod}` = Доброе утро / Добрый день / Добрый вечер (МСК)  
- Кто мы → вы у нас жили → мягкий вопрос

### Также переписаны

INBOUND_HELLO, HELLO_MID, HOWAREYOU, THANKS, DATES_OK, GUESTS_OK, LOOKING_START, BROWSING_START, SOFT_CLOSE / STOP / HANDOFF, FAQ, AI ask/resume, panel templates, edge prompt, fallback-фразы.

## Обновление

Сохраните свой `data/` (кроме желаемого обновления `templates.json`) и `.env`. Распакуйте zip, скопируйте код поверх.

## Артефакты

- `/opt/cursor/artifacts/home24_bot_windows_v8_4.zip`
- `/opt/cursor/artifacts/HOME24_V8_4_CHANGELOG.md`
- `/opt/cursor/artifacts/HOME24_V8_4_TEXTS.md`
- `/opt/cursor/artifacts/home24_bot_windows_v8_3.zip`
- `/opt/cursor/artifacts/HOME24_V8_3_CHANGELOG.md`
- `/opt/cursor/artifacts/home24_bot_windows_v8_2.zip`
- `/opt/cursor/artifacts/HOME24_V8_2_CHANGELOG.md`

## Тесты

```text
python tests/test_v8_3_outreach_reply.py
python tests/test_simulations.py
python tests/test_v8_slots_takeover.py
python tests/test_pick_flow.py
python tests/test_active_mode.py
python tests/test_presence.py
python tests/test_reply_templates.py
```
