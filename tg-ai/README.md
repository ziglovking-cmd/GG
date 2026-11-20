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

Бот читает переписку и отвечает **твоим** голосом. На чат — свой режим (подкат / работа / друг / как_я).

## Бесплатный сервер БЕЗ карты → Hugging Face Spaces

Render / Fly / Railway почти всегда просят карту. **HF Spaces — нет.**

1. Аккаунт на [huggingface.co](https://huggingface.co) (бесплатно).
2. **New Space** → имя любое → SDK: **Docker** → Hardware: **CPU basic** (free) → Create.
3. В Space → **Files** → залей из папки `tg-ai`: `Dockerfile`, `requirements.txt`, `bot.py`, этот `README.md` (с шапкой `---` сверху — не трогай).
4. **Settings → Variables and secrets** (секреты!):

| Ключ | Значение |
|------|----------|
| `BOT_TOKEN` | токен бота |
| `OWNER_ID` | твой числовой ID |
| `AI_API_KEY` | ключ Gemini с [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `AI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `AI_MODEL` | `gemini-2.0-flash` |
| `WEBHOOK_SECRET` | любой пароль латиницей, типа `sekret_93821` |
| `WEBHOOK_URL` | `https://ИМЯ_ЮЗЕРА-ИМЯ_СПЕЙСА.hf.space` (без `/` в конце; точный URL смотри на странице Space) |
| `DATA_DIR` | `/tmp/data` |
| `PORT` | `8080` |

5. Save → дождись билдa (App running).
6. Открой `https://...hf.space/health` → должно быть `ok`.
7. Чтобы не засыпал: [cron-job.org](https://cron-job.org) (без карты) → каждые 5 мин GET на `/health`.

`WEBHOOK_SECRET` — просто пароль в URL вебхука, не ключ ИИ и не токен бота.

### Если лень облако

На своём ПК / ноуте (без карты, без вебхука):

```bash
cd tg-ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполни; WEBHOOK_URL оставь пустым
python bot.py
```

Пока открыт терминал / ПК не спит — бот живой.

### Где просят карту (не надо)

Render, Fly.io, Railway — для этого бота не обязательны.

## Режимы

| Команда | Смысл |
|--------|--------|
| `/chats` | список |
| `/on ID` / `/off ID` | автоответы |
| `/mode ID подкат` | флирт |
| `/mode ID работа` | деловой |
| `/mode ID друг` / `холод` / `как_я` | пресеты |
| `/mode ID свой текст` | свой бриф |
| `/default подкат` | режим для новых чатов |

Старый чат → как ты по истории. Новый + режим → по режиму твоим голосом.

Business Mode в BotFather + подключение бота в Telegram Business. Экспорт JSON/ZIP + ID в подписи — натаскать стиль.
