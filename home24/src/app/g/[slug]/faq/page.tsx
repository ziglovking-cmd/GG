import { notFound } from "next/navigation";
import { getGuestApartment } from "@/lib/shared-videos";
import { faqItems } from "@/lib/sections";
import { GuestChrome } from "@/components/guide/GuestChrome";
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
  return { title: apt ? `FAQ часто задаваемые вопросы · ${apt.name}` : "FAQ" };
}

export default async function FaqFolder({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const apt = await getGuestApartment(slug);
  if (!apt) notFound();
  const faqs = faqItems(apt);

  return (
    <GuestChrome apt={apt} active="faq">
      <article>
        <p className="mb-3 text-[11px] uppercase tracking-[0.24em] text-[#9a7b4f]">«{apt.name}»</p>
        <h1 className="k-h1">FAQ</h1>
        <div>
          {faqs.map((f, i) => (
            <a
              key={f.key}
              href={`/g/${apt.slug}/faq/${f.key}`}
              className="group flex items-start gap-4 border-b border-[#1a1612]/10 py-5 no-underline"
            >
              <span className="w-8 shrink-0 pt-1 text-[11px] tabular-nums text-[#9a7b4f]">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="font-display min-w-0 flex-1 text-[22px] font-semibold leading-tight tracking-tight text-[#1a1612] sm:text-[26px]">
                {f.q}
              </span>
              <span className="pt-2 text-[13px] text-[#1a1612]/25 group-hover:text-[#9a7b4f]">→</span>
            </a>
          ))}
        </div>
      </article>
    </GuestChrome>
  );
}
