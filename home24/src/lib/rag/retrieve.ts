import { foldSearch } from "@/lib/search";
import { getCorpus } from "@/lib/rag/corpus";
import type { RagChunk, RagHit } from "@/lib/rag/types";

const STOP = new Set(
  [
    "и",
    "в",
    "во",
    "на",
    "по",
    "к",
    "с",
    "со",
    "у",
    "о",
    "об",
    "от",
    "для",
    "это",
    "эта",
    "этот",
    "как",
    "что",
    "чем",
    "ли",
    "же",
    "а",
    "но",
    "или",
    "то",
    "там",
    "тут",
    "можно",
    "нужно",
    "есть",
    "нет",
    "где",
    "когда",
    "пожалуйста",
    "скажи",
    "подскажи",
    "расскажи",
    "сколько",
    "стоит",
    "какой",
    "какая",
    "какие",
    "какое",
  ].map(foldSearch),
);

function tokens(text: string): string[] {
  return (text || "")
    .split(/[^a-zA-Zа-яА-ЯёЁ0-9]+/u)
    .map(foldSearch)
    .filter((t) => t.length >= 2 && !STOP.has(t));
}

/** Lightweight BM25-ish lexical retrieval over apartment knowledge chunks. */
export function retrieve(question: string, opts?: { slug?: string | null; k?: number }): RagHit[] {
  const q = tokens(question);
  if (!q.length) return [];

  const slug = opts?.slug || null;
  const k = opts?.k ?? 5;
  const corpus = getCorpus(slug);

  const df = new Map<string, number>();
  const docs = corpus.map((c) => {
    const toks = tokens(`${c.title} ${c.section} ${c.name} ${c.text}`);
    const tf = new Map<string, number>();
    for (const t of toks) tf.set(t, (tf.get(t) || 0) + 1);
    for (const t of new Set(toks)) df.set(t, (df.get(t) || 0) + 1);
    return { chunk: c, tf, len: toks.length || 1 };
  });

  const N = docs.length || 1;
  const avgdl = docs.reduce((s, d) => s + d.len, 0) / N;
  const k1 = 1.4;
  const b = 0.75;

  const scored: RagHit[] = [];
  for (const d of docs) {
    let score = 0;
    let covered = 0;
    for (const term of q) {
      const f = d.tf.get(term) || 0;
      if (!f) continue;
      covered += 1;
      const n = df.get(term) || 0;
      const idf = Math.log(1 + (N - n + 0.5) / (n + 0.5));
      const denom = f + k1 * (1 - b + b * (d.len / avgdl));
      score += idf * ((f * (k1 + 1)) / denom);
      if (foldSearch(d.chunk.title).includes(term) || foldSearch(d.chunk.section).includes(term)) {
        score += 0.45 * idf;
      }
    }
    const coverage = covered / q.length;
    // Soft penalty when only a tiny fraction of the question matches.
    score *= 0.55 + 0.45 * coverage;
    if (score > 0 && covered > 0) scored.push({ ...d.chunk, score });
  }

  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, k);
}

export function formatContext(hits: RagHit[]): string {
  return hits.map((h, i) => `[#${i + 1}] ${h.name} · ${h.title}\n${h.text}`).join("\n\n");
}

export function minScoreThreshold(hits: RagHit[], question: string): boolean {
  if (!hits.length) return false;
  const q = tokens(question);
  if (!q.length) return false;
  const top = hits[0];
  const hay = foldSearch(`${top.title} ${top.section} ${top.text}`);
  const covered = q.filter((t) => hay.includes(t)).length;
  const coverage = covered / q.length;
  // Need a real topical overlap, not one generic word.
  if (covered < 1) return false;
  if (q.length >= 2 && covered < 2 && coverage < 0.5) return false;
  return top.score >= 1.6 && coverage >= 0.34;
}

export type { RagChunk };
