"use client";

import { useMemo, useState } from "react";
import { apartments, findApartments } from "@/lib/catalog";
import { CANONICAL_ORIGIN } from "@/lib/site";
import { BrandMark } from "@/components/BrandMark";

function guestLink(slug: string) {
  return `${CANONICAL_ORIGIN}/g/${slug}`;
}

export function ManagerMenu() {
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const items = useMemo(() => findApartments(query), [query]);
  const active = apartments.find((x) => x.slug === copied);

  async function copyLink(slug: string) {
    const url = guestLink(slug);
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      const el = document.createElement("textarea");
      el.value = url;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      el.remove();
    }
    setCopied(slug);
    window.setTimeout(() => setCopied((cur) => (cur === slug ? null : cur)), 2600);
  }

  return (
    <div className="min-h-dvh bg-[#efe8dc] text-[#1a1612]">
      <div className="mx-auto max-w-[760px] px-5 pb-32 pt-8 sm:px-8 sm:pt-14">
        <header className="border-b border-[#1a1612]/10 pb-10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <BrandMark />
              <span className="text-[11px] uppercase tracking-[0.28em] text-[#9a7b4f]">Home24</span>
            </div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-[#1a1612]/40">{apartments.length} домов</p>
          </div>
          <h1 className="font-display mt-10 text-[44px] font-semibold leading-[0.95] tracking-tight sm:text-[64px]">
            Каталог
            <br />
            ссылок
          </h1>
          <p className="mt-5 max-w-[22rem] text-[15px] leading-relaxed text-[#1a1612]/55">
            Нажмите слоган — ссылка для гостя копируется. Отправьте её в любой мессенджер.
          </p>
        </header>

        <div className="sticky top-0 z-10 -mx-5 mt-6 bg-[#efe8dc]/90 px-5 py-3 backdrop-blur-md sm:-mx-8 sm:px-8">
          <label className="flex items-center gap-3 border-b border-[#1a1612]/20 py-3">
            <span className="text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">поиск</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Шир, Лориэн, Трёхполье…"
              className="w-full bg-transparent text-[18px] outline-none placeholder:text-[#1a1612]/30"
              autoFocus
            />
          </label>
        </div>

        {items.length === 0 ? (
          <p className="py-16 text-center text-[15px] text-[#1a1612]/40">Нет такого дома. Другой слоган?</p>
        ) : (
          <ul className="m-0 list-none p-0">
            {items.map((a) => {
              const selected = copied === a.slug;
              return (
                <li key={a.slug} className="flex items-baseline gap-3 border-b border-[#1a1612]/10">
                  <button
                    type="button"
                    onClick={() => copyLink(a.slug)}
                    className="group flex min-w-0 flex-1 items-baseline gap-4 py-5 text-left"
                  >
                    <span className="w-8 shrink-0 text-[11px] tabular-nums tracking-wider text-[#9a7b4f]">
                      {String(a.id).padStart(2, "0")}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="font-display block text-[28px] font-semibold leading-none tracking-tight sm:text-[32px]">
                        {a.name}
                      </span>
                      <span className="mt-2 block text-[11px] leading-snug tracking-wide text-[#1a1612]/40">
                        {a.address}
                      </span>
                    </span>
                    <span
                      className={`shrink-0 text-[11px] uppercase tracking-[0.16em] ${
                        selected ? "text-[#9a7b4f]" : "text-[#1a1612]/30 group-hover:text-[#1a1612]"
                      }`}
                    >
                      {selected ? "скопировано" : "копировать"}
                    </span>
                  </button>
                  {a.mapsOrgUrl ? (
                    <a
                      href={a.mapsOrgUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="shrink-0 py-5 text-[11px] uppercase tracking-[0.16em] text-[#9a7b4f] no-underline hover:underline"
                    >
                      карты
                    </a>
                  ) : (
                    <span className="w-12 shrink-0" />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {copied && active ? (
        <div className="fixed inset-x-0 bottom-5 z-20 flex justify-center px-4">
          <div className="max-w-[760px] border border-[#9a7b4f]/40 bg-[#1a1612] px-5 py-3 text-[12px] tracking-wide text-[#efe8dc] shadow-xl">
            {active.name} · {guestLink(copied)}
          </div>
        </div>
      ) : null}
    </div>
  );
}
