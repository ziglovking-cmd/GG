import { getBot } from "@/lib/bot";
import { settleLobbyIfNeeded } from "@/lib/lobby";
import { getActiveTournament } from "@/lib/tournaments";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const bot = getBot();
  if (!bot) {
    return Response.json(
      { ok: false, error: "TELEGRAM_BOT_TOKEN не задан" },
      { status: 503 },
    );
  }

  // Opportunistic lobby settle on each update
  try {
    const active = await getActiveTournament();
    if (active) await settleLobbyIfNeeded(active.id);
  } catch {
    /* ignore */
  }

  const secret = process.env.TELEGRAM_WEBHOOK_SECRET?.trim();
  if (secret) {
    const header = request.headers.get("x-telegram-bot-api-secret-token");
    if (header !== secret) {
      return Response.json({ ok: false }, { status: 401 });
    }
  }

  const update = await request.json();
  await bot.handleUpdate(update);
  return Response.json({ ok: true });
}

export async function GET() {
  const configured = Boolean(process.env.TELEGRAM_BOT_TOKEN?.trim());
  return Response.json({
    ok: true,
    botConfigured: configured,
    hint: configured
      ? "Webhook POST /api/telegram"
      : "Добавь TELEGRAM_BOT_TOKEN в секреты приложения",
  });
}
