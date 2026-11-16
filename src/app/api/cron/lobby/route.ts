import { sql } from "@/lib/db";
import { settleLobbyIfNeeded } from "@/lib/lobby";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Call periodically (or from site polling) to close expired check-ins. */
export async function POST(request: Request) {
  const secret = process.env.CRON_SECRET?.trim();
  if (secret) {
    const header = request.headers.get("authorization") ?? "";
    if (header !== `Bearer ${secret}`) {
      return Response.json({ error: "unauthorized" }, { status: 401 });
    }
  }

  const rows = await sql<{ id: number }>(
    `select id from tournaments where status = 'checkin'`,
  );
  const results = [];
  for (const row of rows) {
    results.push(await settleLobbyIfNeeded(row.id));
  }
  return Response.json({ ok: true, results });
}

export async function GET(request: Request) {
  return POST(request);
}
