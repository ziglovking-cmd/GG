import type { Apartment } from "@/lib/catalog";
import { faqItems, guideTitle, navUrl, sectionsFor, type SectionId } from "@/lib/sections";
import { GuideShell } from "@/components/guide/GuideShell";

export function GuestChrome({
  apt,
  active,
  faqKey,
  children,
}: {
  apt: Apartment;
  active?: SectionId | "index";
  faqKey?: string;
  children: React.ReactNode;
}) {
  const faqs = faqItems(apt).map((f) => ({ key: f.key, q: f.q }));
  return (
    <GuideShell
      slug={apt.slug}
      aptName={apt.name}
      title={guideTitle(apt)}
      faqs={faqs}
      sections={sectionsFor(apt)}
      active={active}
      faqKey={faqKey}
      routeHref={navUrl(apt)}
    >
      {children}
    </GuideShell>
  );
}
