"use client";

import { useMemo, useState } from "react";
import { SECTIONS, type Section } from "@/lib/sections";

export function GuideSearch({
  slug,
  faqs = [],
  sections = SECTIONS,
}: {
  slug: string;
  faqs?: { key: string; q: string }[];
  sections?: Section[];
}) {
  const [q, setQ] = useState("");
  const hits = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (s.length < 2) return [];
    const docs = sections.filter((x) => x.title.toLowerCase().includes(s)).map((x) => ({
      href: x.kind === "faq" ? `/g/${slug}/faq` : `/g/${slug}/${x.id}`,
      title: x.title,
    }));
    const more = faqs
      .filter((f) => f.q.toLowerCase().includes(s))
      .map((f) => ({ href: `/g/${slug}/faq/${f.key}`, title: f.q }));
    return [...docs, ...more].slice(0, 8);
  }, [q, slug, faqs, sections]);

  return (
    <div className="relative w-full">
      <label className="flex items-center gap-3 border-b border-[#efe8dc]/25 py-2">
        <span className="text-[10px] uppercase tracking-[0.2em] text-[#c4b08a]">поиск</span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Wi‑Fi, парковка, депозит…"
          className="w-full bg-transparent text-[15px] text-[#efe8dc] outline-none placeholder:text-[#efe8dc]/35"
        />
      </label>
      {hits.length > 0 && (
        <div className="absolute z-20 mt-2 w-full border border-[#1a1612]/10 bg-[#efe8dc] shadow-xl">
          {hits.map((h) => (
            <button
              key={h.href}
              type="button"
              className="block w-full border-b border-[#1a1612]/8 px-4 py-3 text-left text-[14px] text-[#1a1612] last:border-0 hover:bg-[#faf6ef]"
              onClick={() => {
                setQ("");
                window.location.href = h.href;
              }}
            >
              {h.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
