---
title: tg-ai
emoji: 🤖
colorFrom: slate
colorTo: green
sdk: docker
app_port: 8080
pinned: false
---

# Автоответчик Telegram Business

Бот читает переписку и отвечает **твоим** голосом. Режимы на чат: подкат / работа / друг / как_я.

## 24/7 БЕЗ карты (реально)

Render/Fly = карта. Hugging Face free ≈ час и спать. Для постоянной работы:

### Вариант A — свой ПК / ноут (самый простой)

```bash
cd tg-ai
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

В `.env` заполни `BOT_TOKEN`, `OWNER_ID`, `AI_API_KEY` (Gemini).  
**`WEBHOOK_URL` не трогай — пустой.** Дальше:

```bash
python bot.py
```

Пока комп включён и не спит — бот живой. Чтобы не гас экран: в питании отключи сон, либо запусти на старом телефоне.

### Вариант B — Android (Termux), тоже без карты

1. Поставь **Termux** из F-Droid.  
2. В Termux:
```bash
pkg install python git
git clone https://github.com/ziglovking-cmd/GG.git
cd GG/tg-ai
pip install -r requirements.txt
nano .env   # те же ключи, WEBHOOK_URL пустой
python bot.py
```
3. Чтобы не убило: `pkg install termux-services` + держи зарядку / отключи оптимизацию батареи для Termux.  
   Или `ssh` на телефон и `nohup python bot.py &`.

### Вариант C — Serv00 (без карты) → пошагово

Полная инструкция: **[SERV00.md](./SERV00.md)**  
Коротко: рега → Enable «Run your own applications» → SSH → venv → `.env` → `./start.sh` → cron каждые 5 мин.

### Где НЕ ждать чуда

| Площадка | Почему |
|----------|--------|
| Hugging Face free | Режут по времени / засыпает |
| Render / Fly / Railway | Почти всегда карта |
| GitHub Actions | Минуты, не 24/7 |

ИИ без карты: [Google AI Studio](https://aistudio.google.com/apikey) → в `.env`:
```
AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
AI_MODEL=gemini-2.0-flash
AI_API_KEY=AIza...
```

`WEBHOOK_SECRET` нужен **только** если юзаешь webhook на облаке. На ПК/Termux/Serv00 с polling — не нужен.

## Режимы бота

| Команда | Смысл |
|--------|--------|
| `/chats` | список |
| `/on ID` / `/off ID` | автоответы |
| `/mode ID подкат` | флирт |
| `/mode ID работа` | деловой |
| `/mode ID друг` / `холод` / `как_я` | пресеты |
| `/default подкат` | режим для новых |

Старый чат → как ты по истории. Новый → по режиму.  
Business Mode в BotFather + чат-бот в Telegram Business.
