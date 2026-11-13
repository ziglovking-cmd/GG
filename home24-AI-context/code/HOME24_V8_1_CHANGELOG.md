# Home24 v8.1 — changelog (RU)

Архив: `/opt/cursor/artifacts/home24_bot_windows_v8_1.zip`

## Что нового

**Active mode** для живого диалога: после первого ответа в окне проверки (или пока гость пишет) бот отвечает **сразу** — только пауза «печатает», без ожидания следующего окна. Другие чаты в этот период тоже сразу.  
Выход из active mode — после тишины гостя **N минут** (по умолчанию **10**, панель → Настройки / `HOME24_ACTIVE_IDLE_MIN`). Затем снова offline + окна проверки.

Остальное из v8 без изменений: слоты, takeover, API keys, QR expires, SessionRevoked, UTF-8.

## Настройки

| Ключ | Default | Где |
|---|---|---|
| `HOME24_CHECK_WINDOWS` | 1 | env / панель |
| `HOME24_CHECK_INTERVAL_MIN` | 3 | env / панель |
| `HOME24_CHECK_JITTER` | 0.3 | env / панель |
| `HOME24_NIGHT_*` | 23–8 / 15 мин | env / панель |
| `HOME24_ACTIVE_IDLE_MIN` | **10** | env / панель |

## Обновление

Сохраните свой `data/` и `.env`. Распакуйте zip рядом, скопируйте код поверх. `Ctrl+F5` в панели.

## Артефакты

- `/opt/cursor/artifacts/home24_bot_windows_v8_1.zip`
- `/opt/cursor/artifacts/HOME24_V8_1_CHANGELOG.md`
- `/opt/cursor/artifacts/HOME24_V8_CHANGELOG.md`
- `/opt/cursor/artifacts/HOME24_QA_REPORT.md`
- `/opt/cursor/artifacts/HOME24_TEMPLATES_LOGIN_REPORT.md`
- `/opt/cursor/artifacts/HOME24_UI_CHIPS_NOTIFY_REPORT.md`
- `/opt/cursor/artifacts/e2e-qa/ui_fix/report.json`
- `/opt/cursor/artifacts/e2e-qa/ui_fix/chips_dark.png`
- `/opt/cursor/artifacts/e2e-qa/ui_fix/templates_open.png`
- `/opt/cursor/artifacts/ui_fix_chips_dark.png`
- `/opt/cursor/artifacts/ui_fix_templates_open.png`

## Тесты

```text
python tests/test_active_mode.py   → ok
python tests/test_presence.py      → ok
python tests/test_v8_slots_takeover.py → ok
```
