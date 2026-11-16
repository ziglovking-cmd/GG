import { settleLobbyIfNeeded } from "@/lib/lobby";
import { publicTournamentPayload } from "@/lib/tournaments";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id: raw } = await context.params;
  const id = Number(raw);
  if (!Number.isFinite(id)) {
    return Response.json({ error: "bad id" }, { status: 400 });
  }
  await settleLobbyIfNeeded(id);
  return Response.json(await publicTournamentPayload(id));
}
