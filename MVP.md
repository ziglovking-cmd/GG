# MVP — легитимный инвайт-пак

Собрано поверх учёта TZ (presence-only success) и гигиены пула (1 аккаунт = 1 IP).

## Режимы кампании (`invite_mode`)

| Режим | Поведение |
|---|---|
| `force` | Классический `InviteToChannel` / `AddChatUser` + verify membership |
| `link` | Экспорт `ExportChatInvite` → статус `link_ready`, force-воркеры **не** стартуют |
| `hybrid` (default) | Force для целей с username/hash; остальные → статус `need_link` |

Ссылки **не** рассылаются в ЛС — только копирование оператором.

## Ворота старта

Перед force/hybrid:

1. Preflight статус `ready` или `warning`
2. У каждого инвайтера уникальный proxy `host:port`
3. Отмечен `warmup` (кнопка в карточке аккаунта)
4. Аккаунт не в `invite_restricted` / unauthorized / disabled

Гео номера ≠ гео прокси — мягкое предупреждение, не блок.

## Пул аккаунтов

- `pool_role`: `parser` | `inviter` | `trust`
- `warmup_done` / notes / checked_at
- `proxy_country`, inferred phone country
- `is_premium` (из `get_me`)
- `@SpamBot` audit (`POST /api/accounts/{id}/spambot`)
- Fair carousel: `last_attempt_at` + premium/hash ranking

## Темп

- Профили: `cautious` / `normal` / `warmed`
- Тримодальный jitter паузы (чаще середина диапазона)
- Pre-invite reading чата перед Invite RPC
- `SILENT_LOSS_RESTRICT_THRESHOLD = 1`

## Frankenstein (волны × confirmed)

Идея волн/шаблонов из SoCloseSociety, но:
- успех только после presence-confirm;
- 1 аккаунт = 1 proxy;
- паузы в **минутах**, не 30–75 сек;
- нет шаблона «Aggressive 200/день».

| Шаблон | Акков | confirmed/день·акк | Волна | Пауза волн |
|---|---|---|---|---|
| ultra_safe | 1 | 2 | 2 | 8ч |
| safe | 1 | 3 | 3 | 6ч |
| conservative | 3 | 3 | 4 | 5ч |
| standard | 5 | 4 | 5 | 4ч |
| growth | 10 | 5 | 6 | 4ч |

Мягкий потолок чата: ~40 confirmed/сутки (все кампании на этот `target_chat_id`).

## API

- `GET /api/campaign-templates`
- `POST /api/campaigns` — `invite_mode`, `speed_profile`, `template_id`
- `POST /api/campaigns/{id}/start` — gates; link-режим возвращает `invite_link`
- `POST /api/campaigns/{id}/invite-link`
- `POST /api/accounts/{id}/warmup`
- `POST /api/accounts/{id}/spambot`

## Вне скоупа MVP

- Мобильные прокси / авто-ротация fingerprint
- DM рассылка invite-ссылок
- Авто-одобрение join-request (ручной ops)

См. также [ATTRIBUTION.md](ATTRIBUTION.md).
