import { requireAdmin } from "@/lib/auth";
import { settleLobbyIfNeeded } from "@/lib/lobby";
import { playerFromRequest } from "@/lib/players";
import {
  createTournament,
  getActiveTournament,
  listTournaments,
  publicTournamentPayload,
} from "@/lib/tournaments";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  if (url.searchParams.get("active") === "1") {
    const active = await getActiveTournament();
    if (active) await settleLobbyIfNeeded(active.id);
    return Response.json(await publicTournamentPayload(active?.id));
  }
  const list = await listTournaments();
  return Response.json({ tournaments: list, sample: !process.env.DATABASE_URL });
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    title?: string;
    entryFee?: number;
    prize?: number;
    maxPlayers?: number;
    rules?: string;
  };

  const admin = requireAdmin(request);
  const player = await playerFromRequest(request);
  if (!admin && !player) {
    return Response.json(
      { error: "Войди на сайте (ник + Brawl Tag) или укажи ADMIN_TOKEN" },
      { status: 401 },
    );
  }

  const title = (body.title ?? "").trim();
  if (title.length < 3) {
    return Response.json({ error: "Название слишком короткое" }, { status: 400 });
  }

  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL?.trim() ||
    new URL(request.url).origin;

  const t = await createTournament({
    title,
    entryFee: body.entryFee ?? 50,
    prize: body.prize ?? 150,
    maxPlayers: body.maxPlayers ?? 8,
    rules: body.rules,
    createdByPlayerId: player?.id ?? null,
    siteUrl,
  });

  return Response.json({ tournament: t });
}
