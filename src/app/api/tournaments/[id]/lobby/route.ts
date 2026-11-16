import { requireAdmin } from "@/lib/auth";
import { lobbyStatus, markReady, openLobby, settleLobbyIfNeeded } from "@/lib/lobby";
import { playerFromRequest } from "@/lib/players";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id: raw } = await context.params;
  const id = Number(raw);
  const status = await lobbyStatus(id);
  if (!status) return Response.json({ error: "not found" }, { status: 404 });
  return Response.json(status);
}

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id: raw } = await context.params;
  const id = Number(raw);
  const body = (await request.json().catch(() => ({}))) as {
    action?: "open" | "ready" | "settle";
    roomCode?: string;
    checkinSeconds?: number;
  };

  if (body.action === "ready") {
    const player = await playerFromRequest(request);
    if (!player) {
      return Response.json({ error: "Войди на сайте" }, { status: 401 });
    }
    const res = await markReady({ tournamentId: id, playerId: player.id });
    if (!res.ok) return Response.json({ error: res.error }, { status: 400 });
    return Response.json({ ok: true, registration: res.registration });
  }

  if (!requireAdmin(request)) {
    return Response.json({ error: "Нужен ADMIN_TOKEN" }, { status: 401 });
  }

  if (body.action === "settle") {
    const { sql } = await import("@/lib/db");
    await sql(
      `update tournaments set lobby_deadline_at = now() - interval '1 second' where id = $1`,
      [id],
    );
    const res = await settleLobbyIfNeeded(id);
    return Response.json(res);
  }

  const res = await openLobby({
    tournamentId: id,
    roomCode: body.roomCode ?? "",
    checkinSeconds: body.checkinSeconds ?? 60,
  });
  if (!res.ok) return Response.json({ error: res.error }, { status: 400 });
  return Response.json(res);
}
