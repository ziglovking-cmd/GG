"""SQL translation of the domain target selection criteria."""
from typing import Any

from app import db
from app.domain.invitations import TargetSelection


def select_candidates(target_chat_id: int, source_chat_ids: list[int], selection: TargetSelection):
    placeholders = ",".join("?" for _ in source_chat_ids)
    where = ["m.chat_id IN (%s)" % placeholders]
    params: list[Any] = list(source_chat_ids)

    if selection.skip_bots:
        where.append("m.is_bot = 0")
    if selection.skip_deleted:
        where.append("m.is_deleted = 0")
    if selection.only_username:
        where.append("m.username IS NOT NULL AND m.username != ''")
    if selection.only_active:
        where.append("m.msg_count >= ?")
        params.append(selection.min_messages)
    if selection.only_premium:
        where.append("m.is_premium = 1")
    if selection.skip_dormant:
        where.append("(m.last_seen IS NULL OR m.last_seen NOT IN ('last_month','long_ago'))")

    # не трогаем тех, кто уже в целевом чате (если он спарсен)
    where.append("m.user_id NOT IN (SELECT user_id FROM members WHERE chat_id = ?)")
    params.append(target_chat_id)

    # не трогаем тех, кого уже приглашали в этот же чат в прошлых кампаниях
    where.append("""m.user_id NOT IN (
        SELECT t.user_id FROM targets t
        JOIN campaigns c ON c.id = t.campaign_id
        WHERE c.target_chat_id = ?
          AND t.status IN ('verifying','invited','already','privacy','deleted')
    )""")
    params.append(target_chat_id)

    # Не повторяем тихо отклонённые Telegram запросы в следующих кампаниях.
    # Повтор по такой цели другим аккаунтом резко повышает риск PEER_FLOOD.
    where.append("""NOT EXISTS (
        SELECT 1 FROM targets t
        JOIN campaigns c ON c.id = t.campaign_id
        JOIN invite_confirmations v ON v.target_id = t.id
        WHERE c.target_chat_id = ? AND v.result = 'not_present'
          AND (
              COALESCE(t.resolved_user_id, t.user_id) = m.user_id
              OR (
                  NULLIF(TRIM(t.username), '') IS NOT NULL
                  AND NULLIF(TRIM(m.username), '') IS NOT NULL
                  AND LOWER(TRIM(t.username)) = LOWER(TRIM(m.username))
              )
          )
    )""")
    params.append(target_chat_id)

    # исключаем сами аккаунты пула
    where.append("m.user_id NOT IN (SELECT tg_user_id FROM accounts WHERE tg_user_id IS NOT NULL)")

    order = "m.msg_count DESC, m.is_premium DESC" if selection.active_first else "RANDOM()"
    limit = selection.limit

    sql = """
        SELECT m.user_id,
               MAX(m.username) username,
               MAX(COALESCE(m.first_name,'') || ' ' || COALESCE(m.last_name,'')) display,
               MAX(m.msg_count) msg_count,
               MAX(m.is_premium) is_premium
        FROM members m
        WHERE %s
        GROUP BY m.user_id
        ORDER BY %s
        LIMIT ?
    """ % (" AND ".join(where), order.replace("m.", ""))
    params.append(limit)

    return db.q(sql, params)
