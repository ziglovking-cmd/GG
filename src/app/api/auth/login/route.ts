import { sessionCookie, upsertPlayer } from "@/lib/players";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    displayName?: string;
    username?: string;
    brawlTag?: string;
  };

  if (!body.brawlTag?.trim()) {
    return Response.json(
      { error: "Brawl Tag обязателен" },
      { status: 400 },
    );
  }

  const result = await upsertPlayer({
    displayName: body.displayName || body.username || "Игрок",
    username: body.username ?? null,
    brawlTag: body.brawlTag,
  });

  if (!result.ok) {
    return Response.json({ error: result.error }, { status: 400 });
  }

  const token = result.player.session_token;
  if (!token) {
    return Response.json({ error: "session error" }, { status: 500 });
  }

  return new Response(JSON.stringify({ player: publicPlayer(result.player) }), {
    status: 200,
    headers: {
      "content-type": "application/json",
      "set-cookie": sessionCookie(token),
    },
  });
}

function publicPlayer(p: {
  id: number;
  display_name: string;
  username: string | null;
  brawl_tag: string;
  balance_rub: number;
}) {
  return {
    id: p.id,
    display_name: p.display_name,
    username: p.username,
    brawl_tag: p.brawl_tag,
    balance_rub: p.balance_rub,
  };
}
