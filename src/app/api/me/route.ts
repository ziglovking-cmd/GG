import { playerFromRequest } from "@/lib/players";
import { listDeposits } from "@/lib/wallet";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const player = await playerFromRequest(request);
  if (!player) {
    return Response.json({ player: null });
  }
  const deposits = await listDeposits(player.id);
  return Response.json({
    player: {
      id: player.id,
      display_name: player.display_name,
      username: player.username,
      brawl_tag: player.brawl_tag,
      balance_rub: player.balance_rub,
    },
    deposits,
  });
}
