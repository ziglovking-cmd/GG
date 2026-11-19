import { NextRequest, NextResponse } from "next/server";
import { resolveSlug } from "@/lib/catalog";
import { askRag } from "@/lib/rag/answer";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    question?: string;
    slug?: string;
  };

  const question = String(body.question || "").trim();
  const rawSlug = String(body.slug || "").trim();
  const slug = rawSlug ? resolveSlug(rawSlug) : null;

  if (!question) {
    return NextResponse.json({ error: "Пустой вопрос" }, { status: 400 });
  }

  try {
    const result = await askRag(question, slug);
    return NextResponse.json(result);
  } catch (e) {
    console.error("rag_ask_failed", e);
    return NextResponse.json(
      { error: "Не удалось ответить. Напишите менеджеру." },
      { status: 500 },
    );
  }
}
