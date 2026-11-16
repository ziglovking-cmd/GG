import { randomBytes } from "node:crypto";
import { sql } from "@/lib/db";
import { parseCookie, sessionSecret } from "@/lib/auth";
import { normalizeTag } from "@/lib/tags";
import type { Player } from "@/lib/types";
import { enqueueFriend } from "@/lib/friends";

export async function upsertPlayer(input: {
  telegramId?: number | null;
  username?: string | null;
  displayName: string;
  brawlTag: string;
}): Promise<{ ok: true; player: Player } | { ok: false; error: string }> {
  const tag = normalizeTag(input.brawlTag);
  if (!tag) {
    return {
      ok: false,
      error: "Brawl Tag обязателен, формат вроде #2PP0ABC",
    };
  }
  const name = input.displayName.trim().slice(0, 40);
  if (name.length < 2) {
    return { ok: false, error: "Укажи ник (минимум 2 символа)" };
  }

  const token = randomBytes(24).toString("hex");

  if (input.telegramId) {
    const rows = await sql<Player>(
      `insert into players (telegram_id, username, display_name, brawl_tag, session_token)
       values ($1, $2, $3, $4, $5)
       on conflict (telegram_id) do update set
         username = excluded.username,
         display_name = excluded.display_name,
         brawl_tag = excluded.brawl_tag,
         session_token = coalesce(players.session_token, excluded.session_token)
       returning *`,
      [input.telegramId, input.username ?? null, name, tag, token],
    );
    await enqueueFriend(rows[0].id, tag);
    return { ok: true, player: rows[0] };
  }

  const existing = await sql<Player>(
    `select * from players where lower(username) = lower($1) and telegram_id is null limit 1`,
    [input.username ?? ""],
  );
  if (existing[0] && input.username) {
    const rows = await sql<Player>(
      `update players set display_name = $2, brawl_tag = $3,
         session_token = coalesce(session_token, $4)
       where id = $1 returning *`,
      [existing[0].id, name, tag, token],
    );
    await enqueueFriend(rows[0].id, tag);
    return { ok: true, player: rows[0] };
  }

  const rows = await sql<Player>(
    `insert into players (telegram_id, username, display_name, brawl_tag, session_token, balance_rub)
     values (null, $1, $2, $3, $4, 0) returning *`,
    [input.username ?? null, name, tag, token],
  );
  await enqueueFriend(rows[0].id, tag);
  return { ok: true, player: rows[0] };
}

export async function getPlayerById(id: number): Promise<Player | null> {
  const rows = await sql<Player>(`select * from players where id = $1`, [id]);
  return rows[0] ?? null;
}

export async function getPlayerByTelegram(
  telegramId: number,
): Promise<Player | null> {
  const rows = await sql<Player>(
    `select * from players where telegram_id = $1`,
    [telegramId],
  );
  return rows[0] ?? null;
}

export async function getPlayerBySession(
  token: string,
): Promise<Player | null> {
  if (!token) return null;
  const rows = await sql<Player>(
    `select * from players where session_token = $1`,
    [token],
  );
  return rows[0] ?? null;
}

export async function playerFromRequest(
  request: Request,
): Promise<Player | null> {
  const cookies = parseCookie(request.headers.get("cookie") ?? "");
  const token = cookies.gg_session ?? "";
  return getPlayerBySession(token);
}

export function sessionCookie(token: string): string {
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  return `gg_session=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000${secure}`;
}

export function ensureDevSessionSecret() {
  return sessionSecret();
}
