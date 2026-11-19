import { notFound } from "next/navigation";
import { getGuestApartment } from "@/lib/shared-videos";
import { faqItems } from "@/lib/sections";
import { GuestChrome } from "@/components/guide/GuestChrome";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const dynamicParams = true;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string; item: string }>;
}): Promise<Metadata> {
  const { slug, item } = await params;
  const apt = await getGuestApartment(slug);
  const f = apt ? faqItems(apt).find((x) => x.key === item) : undefined;
  return { title: f?.q ?? "FAQ" };
}

export default async function FaqDoc({
  params,
}: {
  params: Promise<{ slug: string; item: string }>;
}) {
  const { slug, item } = await params;
  const apt = await getGuestApartment(slug);
  if (!apt) notFound();
  const faqs = faqItems(apt);
  const f = faqs.find((x) => x.key === item);
  if (!f) notFound();

  return (
    <GuestChrome apt={apt} active="faq" faqKey={f.key}>
      <article className="k-doc">
        <p className="mb-3 text-[11px] uppercase tracking-[0.24em] text-[#9a7b4f]">FAQ · «{apt.name}»</p>
        <h1 className="k-h1">{f.q}</h1>
        {f.a ? (
          <div className="border border-[#1a1612]/10 bg-[#faf6ef] px-5 py-6 text-[17px] leading-relaxed text-[#3a342c] sm:px-7">
            {f.a}
          </div>
        ) : null}
      </article>
    </GuestChrome>
  );
}
