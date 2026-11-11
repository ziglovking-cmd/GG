import { CallLink } from "@/components/CallLink";
import { PHONE_LABEL } from "@/lib/guest-ui";

export function SiteFooter() {
  return (
    <footer className="border-t border-[#1a1612]/10 bg-[#efe8dc] px-5 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-8 lg:pb-10">
      <div className="mx-auto flex max-w-[1080px] flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <p className="text-[11px] uppercase tracking-[0.22em] text-[#9a7b4f]">Home24</p>
        <p className="text-[15px] leading-relaxed text-[#1a1612]/70">
          Персональный менеджер{" "}
          <CallLink className="text-[#1a1612]">{PHONE_LABEL}</CallLink>
          <span className="text-[#1a1612]/30"> · </span>
          набрать · 09:00–00:00
        </p>
      </div>
    </footer>
  );
}
