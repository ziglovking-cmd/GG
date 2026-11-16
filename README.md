# GG Cup — Brawl Stars турики

Мини-сайт + Telegram-бот для турниров Brawl Stars.

- Вход **50₽**, приз победителю **150₽**
- Обязательный **Brawl Tag**
- Сетки, стрим, кошелёк на сайте
- Лобби: код комнаты → чек-ин **60 секунд** → кто не зашёл = **ВЫБЫЛ**, в сетке **BOT**
- Анонсы турниров/победителей/сеток в Telegram-канал

## Важно про Brawl Stars

Официального API для создания комнат и добавления в друзья нет. Бот **не логинится в игру**. Организатор создаёт комнату в клиенте Brawl, вставляет код в бота/админку; очередь тегов (`/friends`) помогает добавить всех вручную.

## Секреты

| Имя | Зачем |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram-бот |
| `TELEGRAM_CHANNEL_ID` | Канал для анонсов (`@channel` или `-100…`) |
| `ADMIN_TELEGRAM_IDS` | Telegram ID админов через запятую |
| `ADMIN_TOKEN` | Админка сайта / API |
| `TELEGRAM_WEBHOOK_SECRET` | Опционально, проверка webhook |
| `SESSION_SECRET` | Сессии сайта |
| `PAYMENT_PROVIDER` | `sandbox` (демо) или боевой провайдер позже |

Публичные (не секреты): `NEXT_PUBLIC_BOT_USERNAME`, `NEXT_PUBLIC_CHANNEL_USERNAME`, `NEXT_PUBLIC_SITE_URL`.

После деплоя поставь webhook:

`https://api.telegram.org/bot<TOKEN>/setWebhook?url=<SITE>/api/telegram`

## Локально

```bash
npm install
npm run dev
```

Sample-данные поднимаются в PGlite без `DATABASE_URL`.
