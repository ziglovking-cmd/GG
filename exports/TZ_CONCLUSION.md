# Заключение по ТЗ инвайтинга

Документ фиксирует причины наблюдаемых ошибок и конкретные изменения в коде
относительно требований ТЗ (очередь, Telethon, access_hash, SQLite).

## 1. Почему старые аккаунты доставляют, а новые — нет

`access_hash` пользователя действителен **только для того аккаунта**, который его
получил. Чужой хэш даёт `PEER_ID_INVALID`.

- Старый аккаунт (тысячи хэшей) чаще резолвит цель через свой `hashes` →
  `InputPeerUser(user_id, own_hash)`.
- Новый аккаунт (десятки хэшей) без записи в `hashes` идёт через `@username`.
  Если username нет — цель для него недоступна (`no_hash`).
- Даже при корректном peer Telegram может принять `InviteToChannelRequest`
  без исключения и без `missing_invitees`, но не добавить человека в чат
  («тихая потеря»). Это ответ API, а не баг счётчика. У новых/ограниченных
  аккаунтов доля таких ответов выше.

Рекомендация по эксплуатации: парсить доноров **теми же аккаунтами**, которыми
потом инвайтите, чтобы накопить собственные хэши; для целей без `@username`
новый аккаунт объективно бессилен.

## 2. Корректная логика очереди (как реализовано)

| Ситуация | Статус цели | Суточный лимит (`successful_today`) | Пауза |
|---|---|---|---|
| Присутствие подтверждено `get_permissions` | `invited` | +1 | интервал аккаунта / кампании |
| RPC принят, после 5 проверок нет в чате | `failed` (unconfirmed) | **не** растёт | интервал **сохраняется** (реальный запрос ушёл в Telegram) |
| `missing_invitees` | `failed` | нет | интервал **освобождается** |
| Privacy / not mutual | `privacy` | нет | интервал освобождается |
| FloodWait | `failed` | нет | `cooldown_until = seconds+5` |
| PEER_FLOOD | `failed` | нет | 24ч + `invite_restricted` до ручного restore |
| Техсбой до durable-маркера | обратно в `pending` | нет | **без** задержки |
| Техсбой / обрыв после маркера | остаётся `verifying` | нет | без повторной отправки Invite RPC |

Успех засчитывается **только** в одной транзакции с
`invite_confirmations.result='confirmed'`. Ограничения Telegram не обходятся:
после реального Invite RPC защитный интервал сохраняется даже при тихой потере.

Проблема из ТЗ «после неподтверждённого приглашения — суточная пауза» относилась
к учёту попытки как успеха. Сейчас `quota_left = daily_limit - successful_today`,
и unconfirmed/`missing_invitees`/privacy/`database is locked` лимит не жгут.

## 3. SQLite: concurrent write

Ранее основной процесс не выставлял `busy_timeout`, тогда как reporter ждал
30 с — отсюда периодический `database is locked` при параллельной записи.

Сделано:

- `PRAGMA busy_timeout=30000` + `timeout=30` на основном соединении (`app/db.py`)
- `PRAGMA synchronous=NORMAL` вместе с WAL
- claim цели и arm Invite RPC — в `BEGIN IMMEDIATE`
- `database is locked` классифицируется как **технический** сбой, не как лимит Telegram

## 4. Перечень изменений в коде

1. `app/db.py` — busy_timeout / timeout / synchronous; `claim_invite_target`;
   IMMEDIATE в `mark_invite_rpc_started`.
2. `app/infrastructure/invitations/repository.py` — claim через атомарный helper.
3. `app/infrastructure/invitations/telegram.py` — locked SQLite = transient.
4. Тесты: сохранение интервала без квоты на unconfirmed; busy_timeout;
   атомарный claim; locked ≠ PEER_FLOOD.

Ранее уже в проекте (и сохранено): двухфазный invite → verifying → confirm;
отдельные privacy / missing_invitees / PEER_FLOOD; at-most-once маркер;
reporter с IMMEDIATE и защитой от double-count.

## 5. Что сознательно не делаем

- Не обходим FloodWait / PEER_FLOOD / суточные лимиты Telegram.
- Не переиспользуем чужие `access_hash`.
- Не считаем «тихую потерю» успехом и не крутим повторный Invite RPC по той же
  цели без новой постановки в очередь оператором/новой кампанией с политикой
  исключения уже обработанных.
