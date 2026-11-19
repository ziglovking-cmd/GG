"use client";

import Image from "next/image";
import { CopyField } from "@/components/guide/CopyField";
import { NINJA_DOM24 } from "@/lib/partners";

/** Prokshino-only partner promo (pizza). Intimate kit lives in «Дополнительные услуги». */
export function PartnerOffers() {
  const o = NINJA_DOM24;
  return (
    <div className="space-y-5">
      <div className="border border-[#1a1612]/10 bg-[linear-gradient(165deg,#faf6ef_0%,#f3ebe0_55%,#efe4d4_100%)] px-5 py-5 sm:px-7">
        <p className="text-[11px] uppercase tracking-[0.22em] text-[#9a7b4f]">Прокшино</p>
        <p className="font-display mt-2 text-[24px] font-semibold leading-tight tracking-tight text-[#1a1612]">
          Предложение партнёра
        </p>
        <p className="mt-2 max-w-xl text-[14px] leading-relaxed text-[#3a342c]/80">
          Пицца «Дом24» со скидкой для гостей Home24 в этом районе. Набор «Для двоих» и остальные
          доп. услуги — в разделе «Дополнительные услуги».
        </p>
      </div>

      <div className="overflow-hidden border border-[#1a1612]/10 bg-[#faf6ef]">
        <Image
          src={o.image}
          alt="Пицца Дом24 от Ninja Food, промокод HOME24"
          width={1280}
          height={1280}
          className="block h-auto w-full"
          sizes="(max-width: 720px) 100vw, 640px"
          priority
        />
        <div className="px-5 py-6 sm:px-7">
          <p className="text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">{o.partner}</p>
          <p className="font-display mt-2 text-[28px] font-semibold leading-none tracking-tight">{o.title}</p>
          <p className="mt-3 text-[15px] leading-relaxed text-[#3a342c]">{o.subtitle}</p>
          <div className="mt-6">
            <CopyField label="Промокод" value={o.promo} />
          </div>
          <ul className="mt-6 list-disc space-y-2 pl-5 text-[14px] leading-relaxed text-[#3a342c]">
            {o.terms.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          <div className="mt-6 grid grid-cols-2 gap-px bg-[#1a1612]/10">
            <a
              href={o.orderUrl}
              target="_blank"
              rel="noreferrer"
              className="bg-[#1a1612] px-3 py-3.5 text-center text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] no-underline"
            >
              Заказать
            </a>
            <a
              href={o.phoneHref}
              className="bg-[#9a7b4f] px-3 py-3.5 text-center text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] no-underline"
            >
              {o.phone}
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
