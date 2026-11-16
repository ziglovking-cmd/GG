import { sql } from "@/lib/db";
import { buildBracket, parseBracket } from "@/lib/brackets";
import {
  postToChannel,
  tournamentCreatedPost,
  winnerPost,
} from "@/lib/channel";
import { normalizeTag } from "@/lib/tags";
import { chargeEntry } from "@/lib/wallet";
import { enqueueFriend } from "@/lib/friends";
import type { Bracket, Registration, Tournament } from "@/lib/types";

export async function getSetting(key: string, fallback = ""): Promise<string> {
  const rows = await sql<{ value: string }>(
    "select value from settings where key = $1",
    [key],
  );
  return rows[0]?.value ?? fallback;
}

export async function setSetting(key: string, value: string): Promise<void> {
  await sql(
    `insert into settings (key, value) values ($1, $2)
     on conflict (key) do update set value = excluded.value`,
    [key, value],
  );
}

const COUNT_SELECT = `select t.*,
  (select count(*)::int from registrations r where r.tournament_id = t.id) as total_count,
  (select count(*)::int from registrations r where r.tournament_id = t.id and r.payment_status = 'paid') as paid_count,
  (select count(*)::int from registrations r where r.tournament_id = t.id and r.payment_status = 'pending') as pending_count,
  (select count(*)::int from registrations r where r.tournament_id = t.id and r.ready_status = 'ready') as ready_count,
  (select count(*)::int from registrations r where r.tournament_id = t.id and r.ready_status = 'noshow') as noshow_count
 from tournaments t`;

export async function getActiveTournament(): Promise<Tournament | null> {
  const rows = await sql<Tournament>(
    `${COUNT_SELECT}
     where t.status in ('open', 'locked', 'checkin', 'live', 'draft')
     order by
       case t.status
         when 'live' then 0
         when 'checkin' then 1
         when 'open' then 2
         when 'locked' then 3
         else 4
       end,
       t.id desc
     limit 1`,
  );
  return rows[0] ?? null;
}

export async function getTournament(id: number): Promise<Tournament | null> {
  const rows = await sql<Tournament>(`${COUNT_SELECT} where t.id = $1`, [id]);
  return rows[0] ?? null;
}

export async function listTournaments(): Promise<Tournament[]> {
  return sql<Tournament>(
    `${COUNT_SELECT}
     order by t.id desc
     limit 30`,
  );
}

export async function createTournament(input: {
  title: string;
  entryFee?: number;
  prize?: number;
  maxPlayers?: number;
  rules?: string;
  createdByPlayerId?: number | null;
  siteUrl?: string;
}): Promise<Tournament> {
  const rows = await sql<Tournament>(
    `insert into tournaments
      (title, game, entry_fee_rub, prize_rub, status, max_players, rules, starts_at, created_by_player_id, checkin_seconds)
     values ($1, 'Brawl Stars', $2, $3, 'open', $4, $5, now() + interval '1 day', $6, 60)
     returning *`,
    [
      input.title,
      input.entryFee ?? 50,
      input.prize ?? 150,
      input.maxPlayers ?? 8,
      input.rules ??
        "Вход 50₽. Приз 150₽. Brawl Tag обязателен. Чек-ин в комнату 60 сек — кто не зашёл, выбывает, слот BOT.",
      input.createdByPlayerId ?? null,
    ],
  );
  await postToChannel({
    kind: "tournament_created",
    tournamentId: rows[0].id,
    body: tournamentCreatedPost({
      title: rows[0].title,
      entry_fee_rub: rows[0].entry_fee_rub,
      prize_rub: rows[0].prize_rub,
      max_players: rows[0].max_players,
      siteUrl: input.siteUrl,
    }),
  });
  return rows[0];
}

export async function updateTournamentStatus(
  id: number,
  status: Tournament["status"],
): Promise<void> {
  await sql(
    "update tournaments set status = $2, updated_at = now() where id = $1",
    [id, status],
  );
}

export async function setStream(
  id: number,
  streamUrl: string,
): Promise<Tournament | null> {
  const embed = toEmbedUrl(streamUrl);
  const rows = await sql<Tournament>(
    `update tournaments
     set stream_url = $2, stream_embed_url = $3, updated_at = now()
     where id = $1
     returning *`,
    [id, streamUrl, embed],
  );
  return rows[0] ?? null;
}

export function toEmbedUrl(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtube.com") || u.hostname.includes("youtu.be")) {
      let id = u.searchParams.get("v");
      if (!id && u.hostname.includes("youtu.be")) {
        id = u.pathname.replace("/", "");
      }
      if (!id && u.pathname.startsWith("/live/")) {
        id = u.pathname.split("/")[2];
      }
      if (!id && u.pathname.startsWith("/embed/")) return url;
      return id ? `https://www.youtube.com/embed/${id}` : null;
    }
    if (u.hostname.includes("twitch.tv")) {
      const channel = u.pathname.split("/").filter(Boolean)[0];
      if (!channel) return null;
      return `https://player.twitch.tv/?channel=${encodeURIComponent(channel)}&parent=localhost&parent=127.0.0.1`;
    }
    return null;
  } catch {
    return null;
  }
}

export async function registerPlayer(input: {
  tournamentId: number;
  playerId: number;
  brawlTag: string;
  payFromBalance?: boolean;
}): Promise<{ ok: true; registration: Registration } | { ok: false; error: string }> {
  const tournament = await getTournament(input.tournamentId);
  if (!tournament) return { ok: false, error: "Турнир не найден" };
  if (tournament.status !== "open") {
    return { ok: false, error: "Регистрация закрыта" };
  }
  const tag = normalizeTag(input.brawlTag);
  if (!tag) return { ok: false, error: "Brawl Tag обязателен, пример #2PP0ABC" };

  const paid = tournament.paid_count ?? 0;
  if (paid >= tournament.max_players) {
    return { ok: false, error: "Мест больше нет" };
  }

  const existing = await getRegistrationForPlayer(
    input.tournamentId,
    input.playerId,
  );
  if (existing?.payment_status === "paid") {
    return { ok: false, error: "Ты уже в турнире" };
  }

  let paymentStatus: "pending" | "paid" = "pending";
  if (input.payFromBalance) {
    const charged = await chargeEntry(input.playerId, tournament.entry_fee_rub);
    if (!charged.ok) return { ok: false, error: charged.error };
    paymentStatus = "paid";
  }

  const rows = await sql<Registration>(
    `insert into registrations (tournament_id, player_id, brawl_tag, payment_status)
     values ($1, $2, $3, $4)
     on conflict (tournament_id, player_id) do update set
       brawl_tag = excluded.brawl_tag,
       payment_status = case
         when registrations.payment_status = 'paid' then registrations.payment_status
         else excluded.payment_status
       end
     returning *`,
    [input.tournamentId, input.playerId, tag, paymentStatus],
  );

  await sql(`update players set brawl_tag = $2 where id = $1`, [
    input.playerId,
    tag,
  ]);
  await enqueueFriend(input.playerId, tag);

  return { ok: true, registration: rows[0] };
}

export async function getRegistrationForPlayer(
  tournamentId: number,
  playerId: number,
): Promise<Registration | null> {
  const rows = await sql<Registration>(
    `select * from registrations where tournament_id = $1 and player_id = $2`,
    [tournamentId, playerId],
  );
  return rows[0] ?? null;
}

export async function markPaid(
  registrationId: number,
): Promise<Registration | null> {
  const rows = await sql<Registration>(
    `update registrations set payment_status = 'paid' where id = $1 returning *`,
    [registrationId],
  );
  return rows[0] ?? null;
}

export async function listRegistrations(
  tournamentId: number,
): Promise<Registration[]> {
  return sql<Registration>(
    `select r.*, p.display_name, p.username, p.telegram_id
     from registrations r
     join players p on p.id = r.player_id
     where r.tournament_id = $1
     order by
       case r.payment_status when 'paid' then 0 when 'pending' then 1 else 2 end,
       r.id`,
    [tournamentId],
  );
}

export async function saveBracket(
  tournamentId: number,
  bracket: Bracket,
): Promise<void> {
  await sql(
    `update tournaments set bracket_json = $2, updated_at = now() where id = $1`,
    [tournamentId, JSON.stringify(bracket)],
  );
}

export async function generateAndSaveBracket(
  tournamentId: number,
): Promise<Bracket | null> {
  const regs = (await listRegistrations(tournamentId)).filter(
    (r) => r.payment_status === "paid",
  );
  if (regs.length < 2) return null;
  const bracket = buildBracket(regs);
  await saveBracket(tournamentId, bracket);
  return bracket;
}

export async function setWinner(
  tournamentId: number,
  registrationId: number,
): Promise<void> {
  const regs = await listRegistrations(tournamentId);
  const winner = regs.find((r) => r.id === registrationId);
  const t = await getTournament(tournamentId);
  await sql(
    `update tournaments
     set winner_registration_id = $2, status = 'finished', updated_at = now()
     where id = $1`,
    [tournamentId, registrationId],
  );
  if (t && winner) {
    await postToChannel({
      kind: "winner",
      tournamentId,
      body: winnerPost({
        title: t.title,
        winnerName: winner.display_name ?? "Игрок",
        winnerTag: winner.brawl_tag,
        prize_rub: t.prize_rub,
      }),
    });
  }
}

export async function publicTournamentPayload(id?: number) {
  const tournament = id ? await getTournament(id) : await getActiveTournament();
  const paymentHint = await getSetting(
    "payment_hint",
    "Пополни баланс на сайте или оплати организатору. Вход в турик 50₽.",
  );
  const botUsername = await getSetting(
    "bot_username",
    process.env.NEXT_PUBLIC_BOT_USERNAME?.trim() || "GGCupBot",
  );
  const channelUsername = await getSetting(
    "channel_username",
    process.env.NEXT_PUBLIC_CHANNEL_USERNAME?.trim() || "ggcup_live",
  );

  if (!tournament) {
    return {
      sample: true,
      botUsername,
      channelUsername,
      paymentHint,
      tournament: null,
      players: [] as Registration[],
      bracket: null as Bracket | null,
    };
  }

  const regs = await listRegistrations(tournament.id);
  return {
    sample: !process.env.DATABASE_URL,
    botUsername,
    channelUsername,
    paymentHint,
    tournament,
    players: regs,
    bracket: parseBracket(tournament.bracket_json),
  };
}

export { parseBracket, normalizeTag };
