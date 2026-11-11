import { notFound } from "next/navigation";
import { getGuestApartment } from "@/lib/shared-videos";
import { guideTitle } from "@/lib/sections";
import { GuestChrome } from "@/components/guide/GuestChrome";
import { GuestHome } from "@/components/guide/GuestHome";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const apt = await getGuestApartment(slug);
  if (!apt) return { title: "Инструкция" };
  return { title: guideTitle(apt) };
}

export default async function GuestIndex({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const apt = await getGuestApartment(slug);
  if (!apt) notFound();

  return (
    <GuestChrome apt={apt} active="index">
      <GuestHome apt={apt} />
    </GuestChrome>
  );
}
