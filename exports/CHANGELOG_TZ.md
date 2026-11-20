# Что изменено по ТЗ инвайтинга

Дата: 2026-11-19  
Ветка: `cursor/assemble-tg-audience-d1ea`

## Сборка проекта

Из загруженных архивов собран рабочий TG Audience: `app/`, `web/`, `tests/`, `deploy/`, `exports/`, Docker, `run.sh`.  
macOS-venv (`bin`/`pip`/`cryptg`) не коммитился — окружение через `./run.sh`.

## Исправления очереди и учёта успеха

Уже в архитектуре проекта (сохранено и закреплено тестами):

| Было (проблема из ТЗ) | Стало |
|---|---|
| Успех мог ассоциироваться с принятым RPC | Успех только при `invite_confirmations.result='confirmed'` и статусе `invited` |
| Unconfirmed «съедал» ощущение суточного лимита | `successful_today` / квота не растут на unconfirmed, privacy, missing, tech |
| Privacy и отказы в одной куче | Отдельные статусы/ветки: `privacy`, `failed`+missing, `unconfirmed`, PEER_FLOOD, FloodWait |
| Tech мог выглядеть как длинная пауза | До durable-маркера — requeue без delay; после — verifying без второго Invite |

Защитный `next_attempt_at` после реального Invite RPC **сохраняется** (в т.ч. на silent loss) — это не обход лимитов Telegram.

## SQLite concurrency

Файлы: `app/db.py`, `app/infrastructure/invitations/repository.py`, `app/infrastructure/invitations/telegram.py`

1. `sqlite3.connect(..., timeout=30)` + `PRAGMA busy_timeout=30000` + `synchronous=NORMAL`
2. Новая `claim_invite_target()` — SELECT+claim в одном `BEGIN IMMEDIATE`
3. `mark_invite_rpc_started()` — тоже `BEGIN IMMEDIATE`
4. Текст `database is locked` / `database table is locked` → transient technical, не Telegram-лимит

## Тесты

- Unconfirmed: квота 0, `cooldown_until=0`, `next_attempt_at` сохранён
- `PRAGMA busy_timeout >= 30000`
- Повторный claim той же цели → `None`
- Locked SQLite ≠ PEER_FLOOD для transient-классификации

Итог прогона: **136 passed**.

## Документы для заказчика

| Файл | Назначение |
|---|---|
| `TZ_CONCLUSION.md` | Письменное заключение |
| `CHANGELOG_TZ.md` | Этот список изменений |
| `ACCEPTANCE.md` | Критерии приёмки |
| `CLIENT_LETTER.md` | Шаблон письма |
| `CONSULTATION_AND_COST.md` | Сценарий созвона + смета |
| `delivery_presentation.html` | Слайды для видео/созвона |
| `ТЗ Инвайтинг.docx` | Исходное ТЗ |
| `expert_2026-10-28/` | Обезличенная диагностика |

## Сознательно не делалось

- Обход FloodWait / PEER_FLOOD / суточных лимитов
- Переиспользование чужих access_hash
- Автоматический повтор Invite RPC по verifying-цели без новой постановки
