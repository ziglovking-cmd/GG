import { getPlayerById, playerFromRequest } from "@/lib/players";
import { registerPlayer } from "@/lib/tournaments";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const player = await playerFromRequest(request);
  if (!player) {
    return Response.json(
      { error: "Сначала войди и укажи Brawl Tag" },
      { status: 401 },
    );
  }
  if (!player.brawl_tag) {
    return Response.json({ error: "Brawl Tag обязателен" }, { status: 400 });
  }

  const { id: raw } = await context.params;
  const id = Number(raw);
  const body = (await request.json().catch(() => ({}))) as {
    brawlTag?: string;
    payFromBalance?: boolean;
  };

  const result = await registerPlayer({
    tournamentId: id,
    playerId: player.id,
    brawlTag: body.brawlTag || player.brawl_tag,
    payFromBalance: body.payFromBalance !== false,
  });

  if (!result.ok) {
    return Response.json({ error: result.error }, { status: 400 });
  }
  const refreshed = (await getPlayerById(player.id)) ?? player;
  return Response.json({
    registration: result.registration,
    player: {
      id: refreshed.id,
      display_name: refreshed.display_name,
      username: refreshed.username,
      brawl_tag: refreshed.brawl_tag,
      balance_rub: refreshed.balance_rub,
    },
  });
}
