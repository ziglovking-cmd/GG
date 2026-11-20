# Автоответчик Telegram Business

Бот быстро читает переписку и отвечает **твоим** голосом. На каждый чат — свой режим (подкат / работа / друг / как_я).

## Бесплатно 24/7 (Render)

GitHub Actions **не** держит бота постоянно (лимиты минут). Для круглосуточной работы — бесплатный веб-сервис с webhook.

### Render (проще всего)

1. Залей код в GitHub (этот репо).
2. Зайди на [render.com](https://render.com) → **New** → **Web Service** → подключи репо.
3. Root Directory: `tg-ai`, Runtime: **Docker**, Instance: **Free**.
4. Environment:
   - `BOT_TOKEN`, `OWNER_ID`, `AI_API_KEY` — как в `.env`
   - `AI_BASE_URL`, `AI_MODEL` — по желанию
   - `WEBHOOK_URL` = URL сервиса **без** слэша, например `https://tg-ai-bot.onrender.com`
   - `WEBHOOK_SECRET` = любой длинный пароль (латиница/цифры)
   - `DATA_DIR=/data`
5. Deploy. Открой `https://твой-сервис.onrender.com/health` — должно быть `ok`.
6. Чтобы бесплатный инстанс не засыпал: [cron-job.org](https://cron-job.org) → ping на `/health` каждые 5 минут.

База на free-диске Render **не вечная** (файлы могут сброситься при редеплое). Для надёжности позже добавь Persistent Disk или переезжай на Fly.

### Fly.io (чуть стабильнее)

```bash
cd tg-ai
fly launch --config fly.toml --no-deploy
fly volumes create tgdata --size 1 --region fra
fly secrets set BOT_TOKEN=... OWNER_ID=... AI_API_KEY=... WEBHOOK_URL=https://<app>.fly.dev WEBHOOK_SECRET=...
fly deploy
```

### Локально / свой VPS

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполни, WEBHOOK_URL оставь пустым
python bot.py          # polling
```

## Режимы

| Команда | Смысл |
|--------|--------|
| `/chats` | список чатов |
| `/on ID` / `/off ID` | автоответы |
| `/mode ID подкат` | флирт для новых |
| `/mode ID работа` | деловой |
| `/mode ID друг` / `холод` / `как_я` | другие пресеты |
| `/mode ID свой текст` | свой бриф |
| `/default подкат` | режим для **новых** чатов |

Старый чат (есть история/импорт) → читает переписку и пишет как ты. Новый + режим → ведёт по режиму твоим голосом.

Экспорт Desktop JSON/ZIP + ID в подписи → натаскать стиль. Подробности по Business Mode — как раньше: BotFather Business Mode + подключение в настройках Telegram Business.
