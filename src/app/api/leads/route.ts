import { NextResponse } from "next/server";
import { listLeads, listSessions } from "@/lib/store";

export const runtime = "nodejs";

export async function GET() {
  const [leads, sessions] = await Promise.all([listLeads(), listSessions()]);
  return NextResponse.json({
    leads,
    sessions: sessions.map((s) => ({
      id: s.id,
      createdAt: s.createdAt,
      updatedAt: s.updatedAt,
      status: s.status,
      urgency: s.urgency,
      draft: s.draft,
      messageCount: s.messages.length,
      messages: s.messages,
      leadId: s.leadId,
    })),
  });
}
