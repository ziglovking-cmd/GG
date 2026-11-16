import { requireAdmin } from "@/lib/auth";
import { listFriendQueue, markFriendAdded } from "@/lib/friends";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  if (!requireAdmin(request)) {
    return Response.json({ error: "admin only" }, { status: 401 });
  }
  return Response.json({
    queue: await listFriendQueue(),
    note: "Добавляй теги вручную в клиенте Brawl Stars — бот не логинится в игру.",
  });
}

export async function POST(request: Request) {
  if (!requireAdmin(request)) {
    return Response.json({ error: "admin only" }, { status: 401 });
  }
  const body = (await request.json().catch(() => ({}))) as { id?: number };
  if (!body.id) {
    return Response.json({ error: "id required" }, { status: 400 });
  }
  const item = await markFriendAdded(body.id);
  return Response.json({ item });
}
