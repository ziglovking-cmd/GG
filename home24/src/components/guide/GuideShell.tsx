"use client";

import { useState } from "react";
import { SECTIONS, type Section, type SectionId } from "@/lib/sections";
import { GuideSearch } from "@/components/guide/GuideSearch";
import { BrandMark } from "@/components/BrandMark";
import { TEL_HREF } from "@/components/CallLink";

export type NavFaq = { key: string; q: string };

export function GuideShell({
  slug,
  title,
  faqs,
  sections = SECTIONS,
  active,
  faqKey,
  routeHref,
  children,
}: {
  slug: string;
  title: string;
  faqs: NavFaq[];
  sections?: Section[];
  active?: SectionId | "index";
  faqKey?: string;
  routeHref?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const short = title.replace(/^Квартира «/, "").replace(/».*/, "") || title;

  const nav = (
    <nav className="flex flex-col py-2">
      <SideLink href={`/g/${slug}`} active={active === "index" || !active}>
        Гид
      </SideLink>
      {sections.map((s) => (
        <div key={s.id}>
          <SideLink
            href={s.kind === "faq" ? `/g/${slug}/faq` : `/g/${slug}/${s.id}`}
            active={active === s.id && !faqKey}
          >
            {s.title}
          </SideLink>
          {s.kind === "faq" && (active === "faq" || faqKey) &&
            faqs.map((f) => (
              <SideLink key={f.key} href={`/g/${slug}/faq/${f.key}`} active={faqKey === f.key} nested>
                {f.q}
              </SideLink>
            ))}
        </div>
      ))}
    </nav>
  );

  return (
    <div className="guest-app min-h-dvh bg-[#efe8dc] text-[#1a1612]">
      <header className="sticky top-0 z-30 border-b border-[#efe8dc]/10 bg-[#1a1612]/95 px-4 py-3 text-[#efe8dc] backdrop-blur-md">
        <div className="mx-auto flex max-w-[1080px] items-center gap-3">
          <button
            type="button"
            className="grid h-11 w-11 place-items-center border border-[#efe8dc]/20 lg:hidden"
            aria-label="меню"
            onClick={() => setOpen(true)}
          >
            <MenuIcon />
          </button>
          <a href={`/g/${slug}`} className="flex min-w-0 items-center gap-3 no-underline">
            <BrandMark small onDark />
            <span className="truncate">
              <span className="block text-[10px] uppercase tracking-[0.28em] text-[#c4b08a]">Home24</span>
              <span className="font-display block truncate text-[20px] font-semibold leading-none">{short}</span>
            </span>
          </a>
          <div className="ml-auto hidden min-w-[260px] lg:block">
            <GuideSearch slug={slug} faqs={faqs} sections={sections} />
          </div>
        </div>
      </header>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button className="absolute inset-0 bg-black/50" aria-label="close" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-0 h-full w-[min(340px,92vw)] overflow-y-auto bg-[#efe8dc] p-5">
            <div className="mb-6 flex items-center gap-3">
              <BrandMark />
              <span className="text-[11px] uppercase tracking-[0.24em] text-[#9a7b4f]">Home24</span>
            </div>
            <div onClick={() => setOpen(false)}>{nav}</div>
          </div>
        </div>
      )}

      <div className="mx-auto flex max-w-[1080px] lg:gap-10">
        <aside className="sticky top-[61px] hidden h-[calc(100dvh-61px)] w-[260px] shrink-0 overflow-y-auto border-r border-[#1a1612]/10 px-4 py-8 lg:block">
          {nav}
        </aside>
        <main className="min-w-0 flex-1 px-5 pb-28 pt-6 sm:px-8 sm:pt-10 lg:pb-16">{children}</main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-[#1a1612]/10 bg-[#efe8dc]/95 px-2 pb-[max(8px,env(safe-area-inset-bottom))] pt-2 backdrop-blur-md lg:hidden">
        <div className="mx-auto grid max-w-[560px] grid-cols-5">
          <Tab href={`/g/${slug}`} label="Гид" active={active === "index" || !active} />
          <Tab href={routeHref || `/g/${slug}/kak-dobratsya`} label="Путь" active={active === "kak-dobratsya"} ext={Boolean(routeHref)} />
          <Tab href={`/g/${slug}/wifi`} label="Wi‑Fi" active={active === "wifi"} />
          <Tab href={`/g/${slug}/video`} label="Видео" active={active === "video"} />
          <Tab href={TEL_HREF} label="Звонок" call />
        </div>
      </nav>
    </div>
  );
}

function Tab({
  href,
  label,
  active,
  ext,
  call,
}: {
  href: string;
  label: string;
  active?: boolean;
  ext?: boolean;
  call?: boolean;
}) {
  return (
    <a
      href={href}
      target={ext ? "_blank" : undefined}
      rel={ext ? "noreferrer" : undefined}
      className={`py-2.5 text-center text-[10px] uppercase tracking-[0.14em] no-underline ${
        active ? "text-[#1a1612]" : "text-[#1a1612]/35"
      }`}
      onClick={
        call
          ? (e) => {
              e.preventDefault();
              window.location.href = TEL_HREF;
            }
          : undefined
      }
    >
      {label}
      {active ? <span className="mx-auto mt-1 block h-px w-5 bg-[#9a7b4f]" /> : null}
    </a>
  );
}

function SideLink({
  href,
  active,
  children,
  nested,
}: {
  href: string;
  active?: boolean;
  children: React.ReactNode;
  nested?: boolean;
}) {
  return (
    <a
      href={href}
      className={`block border-b border-[#1a1612]/8 py-2.5 text-[14px] leading-snug no-underline ${
        nested ? "pl-3 text-[12px] text-[#1a1612]/50" : ""
      } ${active ? "text-[#9a7b4f]" : "text-[#1a1612]/80"}`}
    >
      {children}
    </a>
  );
}

function MenuIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M4 7h16v1.2H4zm0 4.4h16v1.2H4zM4 16h16v1.2H4z" />
    </svg>
  );
}

export function KaitenMark({ small }: { small?: boolean }) {
  return <BrandMark small={small} />;
}
