# Home24 v8.3 — changelog (RU)

Архив: `/opt/cursor/artifacts/home24_bot_windows_v8_3.zip`

## Hotfix: ответ после outreach

По реальному транскрипту после первого сообщения рассылки бот **здоровался снова**, вставлял имя **«Клиент»** и слал **два** почти одинаковых вопроса про даты.

### Исправления

1. **Уже поздоровались** — после outreach (`context.outreach` / `greeted` / `phr_greet`) бот не представляет Home24 и не пишет «Здравствуйте» снова. Интент «снять квартиру» → сразу вопрос про даты и гостей.
2. **Без заглушек имени** — `Клиент` / `Client` / `Гость` / `User` / телефон не подставляются в `{name_part}` / `{имя}`.
3. **Один ответ на одно сообщение гостя** — looking важнее hello; дубли дат/гостей склеиваются; inbound-ход без карточек каталога — один пузырь.
4. **Ожидаемый ответ** на «Здравствуйте! Да, хотели бы снять квартиру» после opener:

> Отлично! Подскажите, пожалуйста, на какие даты планируете поездку и сколько будет гостей? С радостью подберу вариант 😊  
> *(или другой вариант из пула LOOKING_START — без приветствия и без «Клиент»)*

Логика v8 / v8.1 / v8.2 сохранена.

### Было → стало (этот транскрипт)

| | Было | Стало |
|---|---|---|
| Ответ | 1) Здравствуйте, Клиент! … Это Home24. … даты… 2) С радостью подберу 🙂 На какие даты… | **Одно** сообщение: «Отлично! … даты … и сколько будет гостей? … 😊» |
| Имя | «Клиент» | не вставляется |
| Повторный hello | да | нет |

## Обновление

Сохраните свой `data/` и `.env`. Распакуйте zip, скопируйте код поверх.

## Артефакты

- `/opt/cursor/artifacts/home24_bot_windows_v8_3.zip`
- `/opt/cursor/artifacts/HOME24_V8_3_CHANGELOG.md`
- `/opt/cursor/artifacts/home24_bot_windows_v8_2.zip`
- `/opt/cursor/artifacts/HOME24_V8_2_CHANGELOG.md`
- `/opt/cursor/artifacts/home24_bot_windows_v8_1.zip`
- `/opt/cursor/artifacts/HOME24_V8_1_CHANGELOG.md`
- `/opt/cursor/artifacts/home24_bot_windows_v8.zip`
- `/opt/cursor/artifacts/HOME24_V8_CHANGELOG.md`

## Тесты (запускать)

```text
python tests/test_v8_3_outreach_reply.py
python tests/test_v8_slots_takeover.py
python tests/test_pick_flow.py
python tests/test_active_mode.py
python tests/test_presence.py
python tests/test_simulations.py
```
