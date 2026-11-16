import { sql } from "@/lib/db";
import type { FriendQueueItem } from "@/lib/types";

/**
 * Friend adds happen in the official Brawl Stars client by the organizer.
 * We keep a queue of tags — no game-account login / automation.
 */
export async function enqueueFriend(
  playerId: number,
  brawlTag: string,
): Promise<void> {
  await sql(
    `insert into friend_queue (player_id, brawl_tag, status)
     values ($1, $2, 'pending')
     on conflict (player_id, brawl_tag) do update set
       status = case when friend_queue.status = 'added' then friend_queue.status else 'pending' end,
       updated_at = now()`,
    [playerId, brawlTag],
  );
}

export async function listFriendQueue(
  status?: "pending" | "added" | "failed",
): Promise<FriendQueueItem[]> {
  if (status) {
    return sql<FriendQueueItem>(
      `select f.*, p.display_name
       from friend_queue f
       join players p on p.id = f.player_id
       where f.status = $1
       order by f.id asc`,
      [status],
    );
  }
  return sql<FriendQueueItem>(
    `select f.*, p.display_name
     from friend_queue f
     join players p on p.id = f.player_id
     order by
       case f.status when 'pending' then 0 when 'failed' then 1 else 2 end,
       f.id asc`,
  );
}

export async function markFriendAdded(id: number): Promise<FriendQueueItem | null> {
  const rows = await sql<FriendQueueItem>(
    `update friend_queue set status = 'added', updated_at = now()
     where id = $1 returning *`,
    [id],
  );
  return rows[0] ?? null;
}

export function friendQueueHelpText(items: FriendQueueItem[]): string {
  if (items.length === 0) return "Очередь друзей пуста.";
  const lines = [
    "Добавь в друзья в Brawl Stars вручную (бот не логинится в игру):",
    ...items.slice(0, 30).map(
      (i) => `• ${i.display_name ?? "Игрок"} — ${i.brawl_tag} [#${i.id}]`,
    ),
  ];
  return lines.join("\n");
}
