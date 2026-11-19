import type { Apartment } from "@/lib/catalog";
import { mapsUrl, navUrl, sectionsFor } from "@/lib/sections";
import { MANAGER_HOURS, MANAGER_LABEL, PHONE_LABEL, SECTION_CARD } from "@/lib/guest-ui";
import { CallLink, TEL_HREF } from "@/components/CallLink";

export function GuestHome({ apt }: { apt: Apartment }) {
  return (
    <div className="pb-6">
      <section className="relative overflow-hidden border border-[#1a1612]/10 bg-[#1a1612] px-6 py-10 text-[#efe8dc] sm:px-10 sm:py-14">
        <p className="font-display pointer-events-none absolute -right-2 -top-6 text-[120px] leading-none text-[#efe8dc]/[0.07] sm:text-[160px]">
          {String(apt.id).padStart(2, "0")}
        </p>
        <p className="text-[11px] uppercase tracking-[0.32em] text-[#c4b08a]">Home24 · ключи выданы</p>
        <h1 className="font-display relative mt-6 text-[52px] font-semibold leading-[0.9] tracking-tight sm:text-[76px]">
          {apt.name}
        </h1>
        <div className="mt-8 h-px w-16 bg-[#9a7b4f]" />
        <p className="mt-6 max-w-[26rem] text-[15px] leading-relaxed text-[#efe8dc]/70">
          {apt.address}
          {apt.metro ? `. ${apt.metro}` : ""}
        </p>
        <div className="mt-8 grid grid-cols-2 gap-px bg-[#efe8dc]/10 sm:grid-cols-4">
          {[
            { href: mapsUrl(apt), label: "Карта", ext: true },
            { href: navUrl(apt), label: "Маршрут", ext: true },
            { href: `/g/${apt.slug}/wifi`, label: "Wi‑Fi", ext: false },
            { href: TEL_HREF, label: "Звонок", ext: false },
          ].map((b) => (
            <a
              key={b.label}
              href={b.href}
              target={b.ext ? "_blank" : undefined}
              rel={b.ext ? "noreferrer" : undefined}
              className="bg-[#1a1612] px-3 py-4 text-center text-[11px] uppercase tracking-[0.18em] text-[#efe8dc] no-underline hover:bg-[#efe8dc] hover:text-[#1a1612]"
            >
              {b.label}
            </a>
          ))}
        </div>
      </section>

      <p className="mt-12 text-[11px] uppercase tracking-[0.22em] text-[#9a7b4f]">Гид по дому</p>
      <div className="mt-4">
        {sectionsFor(apt).map((s, i) => {
          const href = s.kind === "faq" ? `/g/${apt.slug}/faq` : `/g/${apt.slug}/${s.id}`;
          const extra = s.id === "video" && apt.videos.length ? String(apt.videos.length).padStart(2, "0") : "";
          return (
            <a
              key={s.id}
              href={href}
              className="group flex items-start gap-4 border-b border-[#1a1612]/10 py-5 no-underline"
            >
              <span className="w-8 shrink-0 pt-1 text-[11px] tabular-nums text-[#9a7b4f]">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="min-w-0 flex-1">
                <span className="font-display block text-[26px] font-semibold leading-none tracking-tight text-[#1a1612] sm:text-[30px]">
                  {s.title}
                  {extra ? <span className="ml-2 text-[14px] text-[#9a7b4f]">{extra}</span> : null}
                </span>
                <span className="mt-2 block text-[13px] leading-snug text-[#1a1612]/45">{SECTION_CARD[s.id].hint}</span>
              </span>
              <span className="pt-2 text-[13px] text-[#1a1612]/25 transition group-hover:text-[#9a7b4f]">→</span>
            </a>
          );
        })}
      </div>

      <CallLink className="mt-10 flex items-end justify-between border border-[#1a1612] px-5 py-5 text-[#1a1612] no-underline">
        <span>
          <span className="block text-[11px] uppercase tracking-[0.22em] text-[#9a7b4f]">{MANAGER_LABEL}</span>
          <span className="font-display mt-1 block text-[28px] font-semibold leading-none">{PHONE_LABEL}</span>
        </span>
        <span className="text-[11px] uppercase tracking-[0.18em] text-[#1a1612]/40">{MANAGER_HOURS}</span>
      </CallLink>
    </div>
  );
}
