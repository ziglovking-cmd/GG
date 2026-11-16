import { readdir, readFile } from "node:fs/promises";
import { PGlite } from "@electric-sql/pglite";
import pg from "pg";

const databaseUrl = process.env.DATABASE_URL?.trim() ?? "";
let pool: pg.Pool | undefined;
let local: Promise<PGlite> | undefined;

export async function sql<T = Record<string, unknown>>(
  text: string,
  params: unknown[] = [],
): Promise<T[]> {
  if (databaseUrl !== "") {
    pool ??= new pg.Pool({ connectionString: databaseUrl, max: 5 });
    return (await pool.query(text, params)).rows as T[];
  }
  local ??= startLocal().catch((error: unknown) => {
    local = undefined;
    throw error;
  });
  return (await (await local).query<T>(text, params)).rows;
}

async function startLocal(): Promise<PGlite> {
  const db = new PGlite();
  const files = (await readdir("migrations").catch(() => []))
    .filter((f) => f.endsWith(".sql"))
    .sort();
  for (const file of files) {
    await db.exec(await readFile(`migrations/${file}`, "utf8"));
  }
  await seedSample(db);
  return db;
}

async function seedSample(db: PGlite) {
  const existing = await db.query<{ c: number }>(
    "select count(*)::int as c from tournaments",
  );
  if ((existing.rows[0]?.c ?? 0) > 0) return;

  await db.query(
    `insert into settings (key, value) values
      ('payment_hint', $1),
      ('bot_username', $2),
      ('channel_username', $3)`,
    [
      "СБП / перевод 50₽+ организатору. На сайте можно пополнить баланс — после подтверждения деньги появятся в кошельке.",
      process.env.NEXT_PUBLIC_BOT_USERNAME?.trim() || "GGCupBot",
      process.env.NEXT_PUBLIC_CHANNEL_USERNAME?.trim() || "ggcup_live",
    ],
  );

  const t = await db.query<{ id: number }>(
    `insert into tournaments
      (title, game, entry_fee_rub, prize_rub, status, stream_url, stream_embed_url, max_players, starts_at, rules)
     values
      ($1, 'Brawl Stars', 50, 150, 'open', $2, $3, 8, now() + interval '3 hours', $4)
     returning id`,
    [
      "GG Cup #1 — Brawl Stars",
      "https://www.youtube.com/watch?v=jNQXAC9IVRw",
      "https://www.youtube.com/embed/jNQXAC9IVRw",
      "Вход 50₽. Победителю 150₽. Обязателен Brawl Tag. Сетка на выбывание.",
    ],
  );

  const names = [
    ["Alpha", "#2PP0"],
    ["Beta", "#8YUQ"],
    ["Gamma", "#9VCL"],
    ["Delta", "#LQR2"],
  ];
  for (const [name, tag] of names) {
    const p = await db.query<{ id: number }>(
      `insert into players (display_name, brawl_tag, balance_rub, username)
       values ($1, $2, 100, $3) returning id`,
      [name, tag, name.toLowerCase()],
    );
    await db.query(
      `insert into registrations (tournament_id, player_id, brawl_tag, payment_status)
       values ($1, $2, $3, 'paid')`,
      [t.rows[0].id, p.rows[0].id, tag],
    );
    await db.query(
      `insert into friend_queue (player_id, brawl_tag, status)
       values ($1, $2, 'pending')
       on conflict (player_id, brawl_tag) do nothing`,
      [p.rows[0].id, tag],
    );
  }
}
