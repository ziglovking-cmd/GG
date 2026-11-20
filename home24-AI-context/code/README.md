# Home24 userbot

Telethon-диалог для **старых клиентов** Home24 (**v10.21 · 14.11.2026**).  
Каждое сообщение гостя идёт через LLM (история + слоты + **RAG-факты** + каталог) → JSON → safety-слой на скрипте/каталоге.  
RAG (`bot/rag.py`) подтягивает только релевантные куски script.md / FAQ / карты / policy — модель не должна выдумывать цены, метро, залог.  
При сбое LLM — fallback на скрипт. Рассылка, стоп-лист, presence/очередь — без изменений.

## Как файлы связаны

```
script.md  ── единственный источник текстов гостю (шапка файла = карта «раздел → файл кода»)
  ├─ bot/phrases.py      рассылка, приветствия, спасибо, даты/гости, закрытие, стоп, передача,
  │                      «да» на предложение из рассылки (OUTREACH_OFFER / OFFER_FACTS / offer_reply)
  ├─ bot/engine.py       кнопки, воронка скрипта (без ИИ)
  ├─ bot/faq.py          «Ответы по словам гостя»
  ├─ bot/tone.py         грубость, мат, «забудь инструкции»
  ├─ bot/life.py         «Ситуации проживания»
  ├─ bot/smart.py        «Короткие факты», правила до ИИ, сборка запроса к ИИ
  ├─ bot/smart_prompt.txt  «Промпт» + «Карта квартир» + дополнение про «да» на услуги
  └─ bot/edge_prompt.txt   «Если обычная реплика не собралась»
bot/llm.py   Groq → Mistral → Gemini → AI3 (ключи в .env, шаблон .env.example)
bot/reply_guard.py   последний фильтр текста: без длинных тире, «)» считается концом фразы
tests/test_script_sync.py   падает, если script.md и код разъехались
training/                   1200 эталонных диалогов (jsonl + выборка + формат дообучения), см. training/README.md
bot/examples.py             1–2 похожих эталонных примера в каждый запрос к ИИ
bot/rag.py                  RAG grounding: релевантные факты из script/FAQ/карты в промпт (антигаллюцинации)
scripts/rag_probe.py        офлайн-проверка, что RAG подтянет под реплику гостя
scripts/eval_golden.py      бот против 1200 эталонных диалогов (--offline за ~10 с)
tests/dialogs_home24.py     48 проверочных диалогов «гость → что бот обязан ответить»
  ├─ tests/test_dialogs_home24.py      офлайн (правила, без ИИ)
  └─ scripts/eval_home24_dialogs.py    живой прогон с Groq → data/dialog_report.md
bot/apartments_map.py      адреса квартир читаются из script.md («Адреса»)
scripts/export_dialogs.py  выгрузка настоящих переписок → data/real_dialogs.md
scripts/reset_contact.py   стереть историю с гостем и вернуть его в рассылку
new-materials/   откуда пришли скрипт, аудит Groq и дополнение (история, не править)
```

## Принципы

- Квартиры и факты — только из `data/mailing.sqlite`, без выдумок
- Цена в карточке = `objects.price_night` (если NULL — «менеджер уточнит», без ориентиров 3500–7000)
- Фильтр подбора: район (`area`/адрес), гости (`capacity` или текст в `how`), бюджет по реальной цене
- Скрипт и LLM не дублируют вопросы; на шагах воронки LLM не зовётся
- Рассылка — с **одного** рабочего аккаунта компании, с паузами
- «Не пишите / стоп / отпишите» → стоп-лист в БД, больше никогда не пишем
- Тем, кому уже писали и нет ответа, повтор не раньше ~14 дней
- Техошибки — только админу в Избранное, гостю никогда

## Запуск

**Windows (рекомендуется):** см. [README_WINDOWS.md](README_WINDOWS.md) — дважды щёлкните `start.bat`.  
Несколько менеджеров: `data/managers.json` (пример — `managers.example.json`), вход с выбором менеджера.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # GROQ_API_KEY (+ резерв AI1 / AI2)
python run_home24.py   # или: python -m bot (если сессия уже есть)
```

Тесты (офлайн, без Telegram):

```bash
HOME24_FORCE_SCRIPT=1 python tests/test_v8_6_bugfix.py   # скриптовый safety
python tests/test_v9_1_fixes.py                           # 8 точечных фиксов v9.1
python tests/test_v9_smart_dialogs.py                     # 27 сценариев, mock LLM
python tests/test_script_sync.py                          # script.md ↔ код
python scripts/eval_home24_dialogs.py --offline          # 48 диалогов без ИИ
python scripts/eval_home24_dialogs.py                    # те же диалоги с Groq (≈8 с пауза между ходами)
python scripts/export_dialogs.py --days 14               # настоящие переписки для разбора
python scripts/eval_smart_dialogs.py                     # живые ключи (Groq / AI1 / AI2)
```

## Цены квартир

Цены и вместимость подтягиваются с официального сайта [home24.msk.ru](https://home24.msk.ru/)
(API TravelLine sync-state), не выдумываются:

```bash
python scripts/update_prices.py
# или офлайн из кэша:
python scripts/update_prices.py --sync-file data/travelline_sync_state.json --no-yandex
```

Пишет в `data/mailing.sqlite` поля `price_night`, `capacity`, `photo_url`,
`price_source`, `price_updated_at`. Неуверенные матчи — в `reports/price_manual_review.txt`.
Яндекс.Карты при капче/403 не обходим.

## Рассылка

- `/add` контакты → `/send` (превью) → `/send go` (реальная отправка, только `pending`)
- Дневной лимит первых сообщений: `DAILY_SEND_LIMIT=30`, неделя `WEEKLY_SEND_LIMIT=210`
- Только в рабочие часы `10:00–20:00 Europe/Moscow` (`WORK_HOURS_*` / `WORK_TIMEZONE`)
- Очередь дня размазывается равномерно по окну; неотправленное остаётся `pending` на завтра
- Ответы гостям в дневной кап **не** входят; FloodWait — ждём сколько сказал Telegram
- Статусы: `pending` → `sent` / `failed` / `stopped` / `skipped`
- Приветствия явно напоминают, что человек **уже был гостем** Home24
- `/status` и превью `/send` показывают сегодня sent/осталось

### Сколько реально слать с одного аккаунта

Честная оценка без ротации купленных акков и антидетекта:

| Темп | Пауза | В день (≈14 ч окна) | Риск |
|---|---|---|---|
| Осторожный (сейчас) | 240 сек, не больше 4/час | **30** | низкий |
| Выше 30/день | — | не используем | высокий (flood / ограничение) |

Рабочий режим Home24: **`DAILY_SEND_LIMIT=30`**, **`WEEKLY_SEND_LIMIT=210`**, пауза **240 с**, не больше **4** первых сообщений в час, окно **10:00–20:00 МСК**. Ответы в диалоге лимит не тратят.  
Ответы гостям в этот лимит почти не входят; узкое место — лимиты Telegram, не CPU.

## ИИ

`USE_AI=1`, промпты `bot/smart_prompt.txt` (основной) и `bot/edge_prompt.txt` (крайний), оба собраны из `script.md`.  
Порядок провайдеров: **Groq** (`GROQ_API_KEY`, модель `GROQ_MODEL`, по умолчанию `qwen/qwen3.8-27b`) → Mistral (`AI1_*`) → Gemini (`AI2_*`) → `AI3_*`.  
`GROQ_FIRST=0` ставит Groq в конец. Бесплатный Groq ~8000 токенов/мин: на 429 он пропускается 60 с, отвечает следующий.  
Ответ `<think>…</think>` у Qwen вырезается до разбора JSON. На `await_dates/guests/district/returning` — только скрипт.

### «Да» на рассылку

Каждое письмо рассылки заканчивается «Рассказать? / Интересно?». На «да / ага / ок / расскажите / ?»
бот рассказывает именно то, что предлагал (услуги, прямая бронь, баллы, романтика/праздник), **без вопроса про даты**.
На «нет» мягко закрывает. Вариант 6 («Может, скоро понадобится?») на «да» сразу спрашивает даты.
То же для «…Рассказать?» в середине разговора (скидки, праздник).

## Команды (Избранное)

`/help` `/status` `/ai` `/add` `/list` `/send` `/stop` `/take` `/free`

## Отчёт менеджеру

При передаче заявки в Избранное: даты, гости, район, любимая кв., бюджет, предпочтения, возражения, что показывали, последнее сообщение.
