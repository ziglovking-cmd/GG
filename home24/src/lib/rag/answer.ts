import { MANAGER_HOURS, PHONE_LABEL } from "@/lib/guest-ui";
import { formatContext, minScoreThreshold, retrieve } from "@/lib/rag/retrieve";
import type { RagAskResult, RagHit } from "@/lib/rag/types";

const REFUSE =
  `В инструкции по этой теме точного ответа нет. Напишите персональному менеджеру ${PHONE_LABEL} (${MANAGER_HOURS}).`;

const SYSTEM = `Ты помощник гостя Home24. Отвечай только по CONTEXT.
Правила:
- Пиши коротко по-русски, спокойно и по делу.
- Используй только факты из CONTEXT. Ничего не выдумывай.
- Не придумывай коды домофона, ключницы, пароли Wi‑Fi, цены и адреса, если их нет в CONTEXT.
- Если в CONTEXT нет ответа — скажи об этом прямо и предложи написать менеджеру ${PHONE_LABEL}.
- Не упоминай горничных и внутренние коды уборки.
- Не говори, что ты ИИ, если не спрашивают.
- Можно кратко сослаться на раздел инструкции (Wi‑Fi, парковка, FAQ и т.п.).`;

function extractive(hits: RagHit[]): string {
  const top = hits[0];
  if (!top) return REFUSE;
  // Prefer FAQ-shaped chunks
  const faq = hits.find((h) => h.section === "faq");
  const pick = faq && faq.score >= top.score * 0.85 ? faq : top;
  const text = pick.text.replace(/^Вопрос:.*\nОтвет:\s*/m, "").trim();
  const lead = pick.section === "faq" ? "" : `Из раздела «${pick.title}»: `;
  const clipped = text.length > 700 ? `${text.slice(0, 680).trim()}…` : text;
  return `${lead}${clipped}`;
}

async function groqAnswer(question: string, hits: RagHit[]): Promise<string | null> {
  const key = process.env.GROQ_API_KEY;
  if (!key) return null;

  const context = formatContext(hits);
  const body = {
    model: process.env.GROQ_MODEL || "openai/gpt-oss-20b",
    temperature: 0.1,
    max_tokens: 450,
    messages: [
      { role: "system", content: SYSTEM },
      {
        role: "user",
        content: `CONTEXT:\n${context}\n\nQUESTION:\n${question}\n\nОтветь только по CONTEXT.`,
      },
    ],
  };

  const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.text().catch(() => "");
    console.error("groq_error", res.status, err.slice(0, 300));
    return null;
  }

  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  const text = data.choices?.[0]?.message?.content?.trim();
  return text || null;
}

export async function askRag(question: string, slug?: string | null): Promise<RagAskResult> {
  const q = (question || "").trim().slice(0, 500);
  if (q.length < 2) {
    return { answer: "Напишите вопрос — например про Wi‑Fi, парковку или заезд.", grounded: false, sources: [], model: "none" };
  }

  const hits = retrieve(q, { slug, k: 5 });
  if (!minScoreThreshold(hits, q)) {
    return { answer: REFUSE, grounded: false, sources: [], model: "none" };
  }

  const sources = hits.slice(0, 3).map((h) => ({
    title: h.title,
    section: h.section,
    slug: h.slug,
  }));

  const groq = await groqAnswer(q, hits);
  if (groq) {
    return { answer: groq, grounded: true, sources, model: "groq" };
  }

  return {
    answer: extractive(hits),
    grounded: true,
    sources,
    model: "extractive",
  };
}
