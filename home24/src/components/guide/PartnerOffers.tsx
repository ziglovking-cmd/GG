"use client";

import Image from "next/image";
import { useState } from "react";
import { CopyField } from "@/components/guide/CopyField";
import { FOR_TWO_KIT, NINJA_DOM24 } from "@/lib/partners";

type OfferId = "pizza" | "for-two";

export function PartnerOffers() {
  const [offer, setOffer] = useState<OfferId | null>(null);
  const [adultOk, setAdultOk] = useState(false);

  return (
    <div className="space-y-4">
      <p className="text-[15px] leading-relaxed text-[#3a342c]">
        Выберите предложение — для гостей Home24 в Прокшино.
      </p>

      <div className="grid grid-cols-1 gap-px bg-[#1a1612]/10 sm:grid-cols-2">
        <OfferTab
          active={offer === "pizza"}
          onClick={() => {
            setOffer("pizza");
            setAdultOk(false);
          }}
          eyebrow="Еда"
          title="Пицца «Дом24»"
        />
        <OfferTab
          active={offer === "for-two"}
          onClick={() => setOffer("for-two")}
          eyebrow="Романтика"
          title="Для двоих"
          badge={FOR_TWO_KIT.badge}
        />
      </div>

      {offer === "pizza" ? <PartnerNinjaDom24 /> : null}
      {offer === "for-two" ? (
        adultOk ? (
          <PartnerForTwo />
        ) : (
          <AgeGate onConfirm={() => setAdultOk(true)} />
        )
      ) : null}

      {!offer ? (
        <p className="text-[13px] leading-relaxed text-[#1a1612]/45">
          Нажмите карточку выше. У «Для двоих» стоит плашка 18+ — откроется после подтверждения возраста.
        </p>
      ) : null}
    </div>
  );
}

function OfferTab({
  active,
  onClick,
  eyebrow,
  title,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  eyebrow: string;
  title: string;
  badge?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`relative block w-full border-0 px-5 py-5 text-left transition ${
        active ? "bg-[#1a1612] text-[#efe8dc]" : "bg-[#faf6ef] text-[#1a1612]"
      }`}
    >
      <span
        className={`text-[11px] uppercase tracking-[0.2em] ${
          active ? "text-[#c4a574]" : "text-[#9a7b4f]"
        }`}
      >
        {eyebrow}
      </span>
      <span className="font-display mt-2 flex items-center gap-2 text-[22px] font-semibold leading-none tracking-tight">
        {title}
        {badge ? (
          <span
            className={`inline-flex items-center px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] ${
              active ? "bg-[#c4a574] text-[#1a1612]" : "bg-[#1a1612] text-[#efe8dc]"
            }`}
          >
            {badge}
          </span>
        ) : null}
      </span>
    </button>
  );
}

function AgeGate({ onConfirm }: { onConfirm: () => void }) {
  return (
    <div className="border border-[#1a1612]/10 bg-[#faf6ef] px-5 py-6 sm:px-7">
      <p className="text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">Ограничение 18+</p>
      <p className="font-display mt-2 text-[26px] font-semibold leading-tight tracking-tight">
        {FOR_TWO_KIT.title}
      </p>
      <p className="mt-3 text-[15px] leading-relaxed text-[#3a342c]">
        Этот блок только для совершеннолетних гостей. Набор уже в квартире — детали откроются после
        подтверждения.
      </p>
      <button
        type="button"
        onClick={onConfirm}
        className="mt-6 w-full border-0 bg-[#1a1612] px-4 py-3.5 text-[11px] uppercase tracking-[0.16em] text-[#efe8dc]"
      >
        {FOR_TWO_KIT.ageGate}
      </button>
    </div>
  );
}

function PartnerForTwo() {
  const o = FOR_TWO_KIT;
  return (
    <div className="border border-[#1a1612]/10 bg-[#faf6ef]">
      <div className="px-5 py-6 sm:px-7">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">{o.partner}</p>
          <span className="inline-flex items-center bg-[#1a1612] px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#efe8dc]">
            {o.badge}
          </span>
        </div>
        <p className="font-display mt-2 text-[28px] font-semibold leading-none tracking-tight">{o.title}</p>
        <p className="mt-3 text-[15px] leading-relaxed text-[#3a342c]">{o.subtitle}</p>
        <p className="mt-6 text-[15px] leading-relaxed text-[#3a342c]">{o.body}</p>
        <ul className="mt-6 grid gap-px bg-[#1a1612]/10">
          {o.contents.map((item) => (
            <li key={item} className="bg-[#faf6ef] px-4 py-3 text-[14px] text-[#1a1612]">
              {item}
            </li>
          ))}
        </ul>
        <p className="mt-6 text-[13px] leading-relaxed text-[#1a1612]/50">
          Ищите набор в квартире. Если не нашли — напишите персональному менеджеру (09:00–00:00).
        </p>
      </div>
    </div>
  );
}

function PartnerNinjaDom24() {
  const o = NINJA_DOM24;
  return (
    <div className="border border-[#1a1612]/10 bg-[#faf6ef]">
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
  );
}
