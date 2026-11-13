"use client";

import Image from "next/image";
import { useState } from "react";
import { CopyField } from "@/components/guide/CopyField";
import { MANAGER_HOURS, PHONE_LABEL, PHONE_TEL } from "@/lib/guest-ui";
import { FOR_TWO_KIT, NINJA_DOM24 } from "@/lib/partners";

type OfferId = "pizza" | "for-two";

export function PartnerOffers() {
  const [offer, setOffer] = useState<OfferId | null>(null);
  const [adultOk, setAdultOk] = useState(false);

  return (
    <div className="space-y-5">
      <div className="border border-[#1a1612]/10 bg-[linear-gradient(165deg,#faf6ef_0%,#f3ebe0_55%,#efe4d4_100%)] px-5 py-5 sm:px-7">
        <p className="text-[11px] uppercase tracking-[0.22em] text-[#9a7b4f]">Прокшино</p>
        <p className="font-display mt-2 text-[24px] font-semibold leading-tight tracking-tight text-[#1a1612]">
          Выберите предложение
        </p>
        <p className="mt-2 max-w-xl text-[14px] leading-relaxed text-[#3a342c]/80">
          Два варианта для гостей Home24 в этом районе — еда от партнёра или набор «Для двоих».
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <OfferTab
          active={offer === "pizza"}
          onClick={() => {
            setOffer("pizza");
            setAdultOk(false);
          }}
          eyebrow="Еда"
          title="Пицца «Дом24»"
          blurb="Промокод HOME24 у Ninja Food"
        />
        <OfferTab
          active={offer === "for-two"}
          onClick={() => setOffer("for-two")}
          eyebrow="Вечер"
          title="Для двоих"
          blurb="Доп. услуга · через менеджера"
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
          Нажмите карточку. У «Для двоих» плашка 18+ — нужен ввод даты рождения.
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
  blurb,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  eyebrow: string;
  title: string;
  blurb: string;
  badge?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`relative block w-full overflow-hidden border px-5 py-5 text-left transition ${
        active
          ? "border-[#1a1612] bg-[#1a1612] text-[#efe8dc] shadow-[0_18px_40px_-28px_rgba(26,22,18,0.85)]"
          : "border-[#1a1612]/12 bg-[#faf6ef] text-[#1a1612] hover:border-[#9a7b4f]/55"
      }`}
    >
      <span
        className={`text-[11px] uppercase tracking-[0.2em] ${
          active ? "text-[#c4a574]" : "text-[#9a7b4f]"
        }`}
      >
        {eyebrow}
      </span>
      <span className="font-display mt-2 flex flex-wrap items-center gap-2 text-[22px] font-semibold leading-none tracking-tight">
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
      <span className={`mt-3 block text-[13px] leading-snug ${active ? "text-[#efe8dc]/70" : "text-[#1a1612]/55"}`}>
        {blurb}
      </span>
    </button>
  );
}

function ageFromIsoDate(value: string, today = new Date()): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [y, m, d] = value.split("-").map(Number);
  const born = new Date(y, m - 1, d);
  if (born.getFullYear() !== y || born.getMonth() !== m - 1 || born.getDate() !== d) return null;
  if (born > today) return null;
  let age = today.getFullYear() - y;
  const beforeBirthday =
    today.getMonth() < m - 1 || (today.getMonth() === m - 1 && today.getDate() < d);
  if (beforeBirthday) age -= 1;
  return age;
}

function AgeGate({ onConfirm }: { onConfirm: () => void }) {
  const [dob, setDob] = useState("");
  const [touched, setTouched] = useState(false);
  const age = ageFromIsoDate(dob);
  const ok = age !== null && age >= 18;
  const tooYoung = age !== null && age < 18;
  const badDate = touched && dob && age === null;

  return (
    <div className="overflow-hidden border border-[#1a1612]/10 bg-[#faf6ef]">
      <div className="border-b border-[#1a1612]/8 bg-[linear-gradient(120deg,#1a1612_0%,#2c241c_48%,#9a7b4f_100%)] px-5 py-5 sm:px-7">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[11px] uppercase tracking-[0.22em] text-[#c4a574]">Ограничение</p>
          <span className="inline-flex items-center bg-[#efe8dc] px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#1a1612]">
            18+
          </span>
        </div>
        <p className="font-display mt-2 text-[28px] font-semibold leading-none tracking-tight text-[#efe8dc]">
          {FOR_TWO_KIT.title}
        </p>
      </div>
      <div className="px-5 py-6 sm:px-7">
        <p className="text-[15px] leading-relaxed text-[#3a342c]">
          Этот блок только для совершеннолетних гостей. Чтобы открыть описание набора, укажите дату
          рождения.
        </p>

        <label className="mt-6 block">
          <span className="text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">Дата рождения</span>
          <input
            type="date"
            value={dob}
            max={new Date().toISOString().slice(0, 10)}
            onChange={(e) => {
              setDob(e.target.value);
              setTouched(true);
            }}
            className="mt-2 w-full border border-[#1a1612]/12 bg-[#efe8dc] px-4 py-3.5 text-[16px] text-[#1a1612] outline-none focus:border-[#9a7b4f]"
          />
        </label>

        <p className="mt-3 text-[13px] leading-relaxed text-[#1a1612]/50">{FOR_TWO_KIT.ageHint}</p>
        {badDate ? (
          <p className="mt-2 text-[13px] leading-relaxed text-[#8a3b2b]">Проверьте дату рождения.</p>
        ) : null}
        {tooYoung ? (
          <p className="mt-2 text-[13px] leading-relaxed text-[#8a3b2b]">
            Раздел доступен только с 18 лет.
          </p>
        ) : null}

        <button
          type="button"
          disabled={!ok}
          onClick={onConfirm}
          className={`mt-6 w-full border-0 px-4 py-3.5 text-[11px] uppercase tracking-[0.16em] transition ${
            ok ? "bg-[#1a1612] text-[#efe8dc]" : "cursor-not-allowed bg-[#1a1612]/20 text-[#efe8dc]/65"
          }`}
        >
          {FOR_TWO_KIT.ageGate}
        </button>
      </div>
    </div>
  );
}

function PartnerForTwo() {
  const o = FOR_TWO_KIT;
  return (
    <div className="overflow-hidden border border-[#1a1612]/10 bg-[#faf6ef]">
      <div className="relative overflow-hidden border-b border-[#1a1612]/8 bg-[linear-gradient(145deg,#1a1612_0%,#3a2c22_42%,#9a7b4f_100%)] px-5 py-7 sm:px-7">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-[#efe8dc]/10 blur-2xl"
        />
        <div className="relative flex flex-wrap items-center gap-2">
          <p className="text-[11px] uppercase tracking-[0.22em] text-[#c4a574]">{o.partner}</p>
          <span className="inline-flex items-center bg-[#efe8dc] px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#1a1612]">
            {o.badge}
          </span>
        </div>
        <p className="font-display relative mt-3 text-[34px] font-semibold leading-none tracking-tight text-[#efe8dc]">
          {o.title}
        </p>
        <p className="relative mt-4 max-w-xl text-[15px] leading-relaxed text-[#efe8dc]/78">{o.subtitle}</p>
      </div>

      <div className="px-5 py-6 sm:px-7">
        <p className="text-[15px] leading-relaxed text-[#3a342c]">{o.body}</p>

        <p className="mt-7 text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">В наборе</p>
        <ul className="mt-3 grid gap-2 sm:grid-cols-3">
          {o.contents.map((item) => (
            <li
              key={item}
              className="border border-[#1a1612]/10 bg-[linear-gradient(180deg,#fffaf3_0%,#f7efe4_100%)] px-4 py-4 text-center text-[14px] text-[#1a1612]"
            >
              {item}
            </li>
          ))}
        </ul>

        <div className="mt-7 border border-[#1a1612]/10 bg-[#efe8dc]/70 px-4 py-5 sm:px-5">
          <p className="text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">Как получить</p>
          <ol className="mt-3 space-y-3">
            {o.how.map((step, i) => (
              <li key={step} className="flex gap-3 text-[14px] leading-relaxed text-[#3a342c]">
                <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center bg-[#1a1612] text-[11px] text-[#efe8dc]">
                  {i + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-px bg-[#1a1612]/10 sm:grid-cols-2">
          <a
            href={`https://wa.me/${PHONE_TEL.replace(/\D/g, "")}?text=${encodeURIComponent(
              "Здравствуйте! Нужен набор «Для двоих» (доп. услуга).",
            )}`}
            target="_blank"
            rel="noreferrer"
            className="bg-[#1a1612] px-3 py-3.5 text-center text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] no-underline"
          >
            {o.ctaWrite}
          </a>
          <a
            href={`tel:${PHONE_TEL}`}
            className="bg-[#9a7b4f] px-3 py-3.5 text-center text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] no-underline"
          >
            {o.ctaCall} · {PHONE_LABEL}
          </a>
        </div>
        <p className="mt-3 text-[12px] leading-relaxed text-[#1a1612]/45">
          Персональный менеджер · {MANAGER_HOURS}. Набор в квартире не ищите — это доп. услуга, оплата и
          получение только через менеджера.
        </p>
      </div>
    </div>
  );
}

function PartnerNinjaDom24() {
  const o = NINJA_DOM24;
  return (
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
  );
}
