# Home24 v8 — changelog (RU)

Архив: `/opt/cursor/artifacts/home24_bot_windows_v8.zip`  
Отчёт: `/opt/cursor/artifacts/HOME24_V8_CHANGELOG.md`

## Что исправлено

1. **Слоты из любого сообщения** — даты (завтра/сегодня/послезавтра/будни/`5-7 октября`/`с 12 по 15`), гости (`я буду 1`, `нас двое`, `на 3 человек`), ночи, квартира (fuzzy по каталогу, напр. «феррари»), район. Бот подтверждает понятое и спрашивает только пробел; шаг воронки двигается.
2. **Takeover менеджера** — любой ответ из панели или исходящее с Telegram-аккаунта (не от бота) → `handed_off=1`, `step=handed_off`. Бот молчит, пока не нажать «Вернуть боту» / `/free`. Без авто-reopen по слову «квартира».
3. **Без повторов** — варианты формулировок вопросов; не клеим один и тот же вопрос подряд.
4. **Цена / наличие** — FAQ эскалирует к менеджеру, без выдуманных цифр и статусов.
5. **Тесты** — `tests/test_v8_slots_takeover.py` на живой диалог (Здравствуйте → менеджер «прив» → «Давайте на завтра квартира феррари я буду 1»).
6. **QR-логин** — ожидание до `qr.expires`, а не фиксированные 90 с.
7. **API keys** — отказ стартовать Telegram при пустом/`6`/`4`/`2040`/… официальных id; сообщение в лог и панель; в `.env` бандла ключи пустые.
8. **SessionRevoked** — poll Saved Messages останавливается, без ERROR каждые ~7 с.
9. **Mojibake** — stdout UTF-8; информативный старт «нет сессии» → WARNING, не ERROR.
10. **Офлайн-присутствие + окна проверки** — одна постоянная сессия (без reconnect-churn); после действий `account.UpdateStatusRequest(offline=True)`. Входящие копятся и обрабатываются окнами: чтение → typing → ответ → снова offline.  
    Настройки (панель → **Настройки** / env):  
    - интервал мин (default **3**, `HOME24_CHECK_INTERVAL_MIN`)  
    - jitter ±30% (`HOME24_CHECK_JITTER=0.3`)  
    - ночь 23–8, интервал **15** мин (`HOME24_NIGHT_START` / `HOME24_NIGHT_END` / `HOME24_NIGHT_INTERVAL_MIN`)  
    - вкл/выкл окон (`HOME24_CHECK_WINDOWS=1`)  
    Ответ менеджера из панели уходит **сразу**, затем offline.

## Обновление на Windows

1. Остановите бота.
2. Распакуйте `home24_bot_windows_v8.zip` **рядом**, затем скопируйте новые файлы поверх установки, **сохранив** свой `data/` и `.env`.
3. В `.env` укажите **свои** `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` с https://my.telegram.org (не 6).
4. `Ctrl+F5` в панели после обновления.

## Артефакты

| Путь | Описание |
|---|---|
| `/opt/cursor/artifacts/home24_bot_windows_v8.zip` | Windows-бандл v8 |
| `/opt/cursor/artifacts/HOME24_V8_CHANGELOG.md` | этот отчёт |
| `/opt/cursor/artifacts/HOME24_UI_CHIPS_NOTIFY_REPORT.md` | предыдущий UI-отчёт |
| `/opt/cursor/artifacts/HOME24_TEMPLATES_LOGIN_REPORT.md` | templates/login |
| `/opt/cursor/artifacts/HOME24_QA_REPORT.md` | полный QA |
| `/opt/cursor/artifacts/e2e-qa/ui_fix/report.json` | offline chips/templates QA |
| `/opt/cursor/artifacts/e2e-qa/ui_fix/chips_dark.png` | чипы тёмная тема |
| `/opt/cursor/artifacts/e2e-qa/ui_fix/templates_open.png` | шаблоны |
| `/opt/cursor/artifacts/ui_fix_chips_dark.png` | копия для walkthrough |
| `/opt/cursor/artifacts/ui_fix_templates_open.png` | копия для walkthrough |

## Тесты (локально)

```text
python tests/test_v8_slots_takeover.py   → ok
python tests/test_presence.py            → ok
python tests/test_pick_flow.py           → ALL OK
python tests/test_simulations.py         → ALL OK
python tests/test_conflict.py            → ALL OK
```
