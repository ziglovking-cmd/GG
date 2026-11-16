import { sql } from "@/lib/db";
import {
  buildBracket,
  formatBracketText,
  markNoshowInBracket,
  parseBracket,
} from "@/lib/brackets";
import {
  bracketPost,
  livePost,
  postToChannel,
} from "@/lib/channel";
import {
  getTournament,
  listRegistrations,
  saveBracket,
} from "@/lib/tournaments";
import type { Bracket, Registration, Tournament } from "@/lib/types";

/**
 * Tournament lobby orchestration.
 * Real Brawl Stars private rooms are created in the official game client
 * (no public API for rooms/friends). The bot stores room code, runs 60s
 * check-in, replaces no-shows with BOT in the bracket and marks them ВЫБЫЛ.
 */
export async function openLobby(input: {
  tournamentId: number;
  roomCode: string;
  checkinSeconds?: number;
}): Promise<
  | { ok: true; tournament: Tournament; bracket: Bracket; deadline: string }
  | { ok: false; error: string }
> {
  const tournament = await getTournament(input.tournamentId);
  if (!tournament) return { ok: false, error: "Турнир не найден" };
  if (!["open", "locked", "checkin"].includes(tournament.status)) {
    return { ok: false, error: "Лобби можно открыть только для открытого турнира" };
  }

  const regs = (await listRegistrations(input.tournamentId)).filter(
    (r) => r.payment_status === "paid",
  );
  if (regs.length < 2) {
    return { ok: false, error: "Нужно минимум 2 оплативших участника" };
  }

  const seconds = Math.min(
    300,
    Math.max(30, input.checkinSeconds ?? tournament.checkin_seconds ?? 60),
  );
  const roomCode = input.roomCode.trim().slice(0, 32);
  if (!roomCode) return { ok: false, error: "Укажи код комнаты Brawl Stars" };

  await sql(
    `update registrations
     set ready_status = 'waiting', ready_at = null
     where tournament_id = $1 and payment_status = 'paid' and ready_status <> 'bot'`,
    [input.tournamentId],
  );

  const bracket = buildBracket(regs);
  await saveBracket(input.tournamentId, bracket);

  const rows = await sql<Tournament>(
    `update tournaments set
       status = 'checkin',
       room_code = $2,
       checkin_seconds = $3,
       lobby_opened_at = now(),
       lobby_deadline_at = now() + ($5::interval),
       bracket_json = $4,
       updated_at = now()
     where id = $1
     returning *`,
    [
      input.tournamentId,
      roomCode,
      seconds,
      JSON.stringify(bracket),
      `${seconds} seconds`,
    ],
  );

  const deadline = rows[0].lobby_deadline_at!;
  const tags = regs.map((r) => `• ${r.display_name} ${r.brawl_tag}`).join("\n");

  await postToChannel({
    kind: "lobby",
    tournamentId: input.tournamentId,
    body: [
      `🚪 Лобби «${tournament.title}»`,
      `Код комнаты: ${roomCode}`,
      `Чек-ин: ${seconds} сек. Кто не зашёл — ВЫБЫЛ, вместо него BOT.`,
      `Участники:`,
      tags,
    ].join("\n"),
  });

  return { ok: true, tournament: rows[0], bracket, deadline };
}

export async function markReady(input: {
  tournamentId: number;
  playerId: number;
}): Promise<{ ok: true; registration: Registration } | { ok: false; error: string }> {
  await settleLobbyIfNeeded(input.tournamentId);
  const tournament = await getTournament(input.tournamentId);
  if (!tournament) return { ok: false, error: "Турнир не найден" };
  if (tournament.status !== "checkin") {
    return { ok: false, error: "Сейчас нет активного чек-ина" };
  }
  if (
    tournament.lobby_deadline_at &&
    new Date(tournament.lobby_deadline_at).getTime() < Date.now()
  ) {
    await settleLobbyIfNeeded(input.tournamentId);
    return { ok: false, error: "Время чек-ина вышло" };
  }

  const rows = await sql<Registration>(
    `update registrations set ready_status = 'ready', ready_at = now()
     where tournament_id = $1 and player_id = $2 and payment_status = 'paid'
     returning *`,
    [input.tournamentId, input.playerId],
  );
  if (!rows[0]) return { ok: false, error: "Ты не в списке оплативших" };
  return { ok: true, registration: rows[0] };
}

export async function settleLobbyIfNeeded(
  tournamentId: number,
): Promise<{ settled: boolean; tournament: Tournament | null; noshows: Registration[] }> {
  const tournament = await getTournament(tournamentId);
  if (!tournament || tournament.status !== "checkin") {
    return { settled: false, tournament, noshows: [] };
  }
  if (
    !tournament.lobby_deadline_at ||
    new Date(tournament.lobby_deadline_at).getTime() > Date.now()
  ) {
    return { settled: false, tournament, noshows: [] };
  }

  const regs = await listRegistrations(tournamentId);
  const paid = regs.filter((r) => r.payment_status === "paid");
  const noshows = paid.filter(
    (r) => r.ready_status === "waiting" || r.ready_status === "noshow",
  );

  for (const r of noshows) {
    await sql(
      `update registrations
       set ready_status = 'noshow', note = coalesce(note, '') || ' | no-show auto'
       where id = $1`,
      [r.id],
    );
  }

  let bracket =
    parseBracket(tournament.bracket_json) ??
    buildBracket(
      paid.map((r) => ({
        ...r,
        ready_status:
          r.ready_status === "ready" ? "ready" : ("noshow" as const),
      })),
    );

  for (const r of noshows) {
    bracket = markNoshowInBracket(bracket, r.player_id, {
      name: r.display_name,
      tag: r.brawl_tag,
    });
  }

  // Rebuild from updated ready statuses for consistency
  const refreshed = await listRegistrations(tournamentId);
  bracket = buildBracket(
    refreshed
      .filter((r) => r.payment_status === "paid")
      .map((r) => ({
        ...r,
        ready_status: noshows.some((n) => n.id === r.id)
          ? "noshow"
          : r.ready_status,
      })),
  );

  await saveBracket(tournamentId, bracket);
  const rows = await sql<Tournament>(
    `update tournaments
     set status = 'live', bracket_json = $2, updated_at = now()
     where id = $1
     returning *`,
    [tournamentId, JSON.stringify(bracket)],
  );

  const noshowLines = noshows
    .map((r) => `• ${r.display_name} (${r.brawl_tag}) — ВЫБЫЛ, слот BOT`)
    .join("\n");

  await postToChannel({
    kind: "noshow",
    tournamentId,
    body: [
      `⏱ Чек-ин закрыт: ${tournament.title}`,
      noshows.length
        ? `Не зашли за ${tournament.checkin_seconds}с:\n${noshowLines}`
        : "Все участники на месте.",
      `Турнир стартовал. Код комнаты: ${tournament.room_code ?? "—"}`,
    ].join("\n"),
  });

  await postToChannel({
    kind: "bracket",
    tournamentId,
    body: bracketPost(tournament.title, formatBracketText(bracket)),
  });

  await postToChannel({
    kind: "live",
    tournamentId,
    body: livePost({
      title: tournament.title,
      stream_url: tournament.stream_url,
    }),
  });

  return { settled: true, tournament: rows[0], noshows };
}

export async function lobbyStatus(tournamentId: number) {
  await settleLobbyIfNeeded(tournamentId);
  const tournament = await getTournament(tournamentId);
  if (!tournament) return null;
  const regs = await listRegistrations(tournamentId);
  const paid = regs.filter((r) => r.payment_status === "paid");
  const remainingMs = tournament.lobby_deadline_at
    ? Math.max(0, new Date(tournament.lobby_deadline_at).getTime() - Date.now())
    : 0;
  return {
    tournament,
    roomCode: tournament.room_code,
    status: tournament.status,
    remainingMs,
    ready: paid.filter((r) => r.ready_status === "ready"),
    waiting: paid.filter((r) => r.ready_status === "waiting"),
    noshow: paid.filter((r) => r.ready_status === "noshow"),
    bracket: parseBracket(tournament.bracket_json),
  };
}
