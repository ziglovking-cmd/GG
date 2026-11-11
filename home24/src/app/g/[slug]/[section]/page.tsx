import { notFound } from "next/navigation";
import { getGuestApartment } from "@/lib/shared-videos";
import { sectionBody, sectionsFor, type SectionId } from "@/lib/sections";
import { GuestChrome } from "@/components/guide/GuestChrome";
import { KaitenDoc } from "@/components/guide/KaitenDoc";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string; section: string }>;
}): Promise<Metadata> {
  const { slug, section } = await params;
  const apt = await getGuestApartment(slug);
  const s = apt ? sectionsFor(apt).find((x) => x.id === section) : undefined;
  if (!apt || !s) return { title: "Инструкция" };
  return { title: s.title };
}

export default async function GuestSection({
  params,
}: {
  params: Promise<{ slug: string; section: string }>;
}) {
  const { slug, section } = await params;
  const apt = await getGuestApartment(slug);
  const s = apt ? sectionsFor(apt).find((x) => x.id === section && x.kind !== "faq") : undefined;
  if (!apt || !s) notFound();
  const id = s.id as SectionId;

  return (
    <GuestChrome apt={apt} active={id}>
      <KaitenDoc apt={apt} section={id} title={s.title} text={sectionBody(apt, id)} />
    </GuestChrome>
  );
}
