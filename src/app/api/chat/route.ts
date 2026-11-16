import { NextRequest, NextResponse } from "next/server";
import { handleUserMessage } from "@/lib/bot-engine";
import {
  appendMessage,
  createSession,
  getSession,
  saveSession,
} from "@/lib/store";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const message = String(body.message || "").trim();
    let sessionId = body.sessionId as string | undefined;

    if (!message) {
      return NextResponse.json({ error: "empty message" }, { status: 400 });
    }

    let session = sessionId ? await getSession(sessionId) : undefined;
    if (!session) {
      session = createSession();
      await saveSession(session);
      sessionId = session.id;
    }

    await appendMessage(session, "user", message);
    const result = await handleUserMessage(session, message);
    await appendMessage(result.session, "assistant", result.text);

    return NextResponse.json({
      sessionId: result.session.id,
      reply: result.text,
      status: result.session.status,
      awaiting: result.session.awaiting,
      draft: result.session.draft,
      lead: result.lead
        ? {
            id: result.lead.id,
            status: result.lead.status,
            telegramSent: result.lead.telegramSent,
          }
        : null,
      actions: result.actions || [],
    });
  } catch (e) {
    console.error(e);
    return NextResponse.json({ error: "chat failed" }, { status: 500 });
  }
}
