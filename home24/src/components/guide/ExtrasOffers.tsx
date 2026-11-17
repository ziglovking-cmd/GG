"use client";

import { useEffect, useId, useState } from "react";
import {
  EXTRA_SERVICES,
  EXTRAS_SECTIONS,
  extrasOrderMessage,
  type ExtraService,
} from "@/lib/extras";
import {
  MANAGER_HOURS_SITE,
  PHONE_LABEL,
  PHONE_TEL,
  TELEGRAM_USERNAME,
} from "@/lib/guest-ui";

const ADULT_KEY = "h24_18";

function phoneDigits() {
  return PHONE_TEL.replace(/\D/g, "");
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

function readAdultOk(): boolean {
  try {
    return sessionStorage.getItem(ADULT_KEY) === "1";
  } catch {
    return false;
  }
}

function writeAdultOk() {
  try {
    sessionStorage.setItem(ADULT_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function ExtrasOffers({ aptName }: { aptName: string }) {
  const [active, setActive] = useState<ExtraService | null>(null);
  const [step, setStep] = useState<"age" | "send">("send");
  const titleId = useId();

  function openService(s: ExtraService) {
    setActive(s);
    if (s.adult && !readAdultOk()) {
      setStep("age");
    } else {
      setStep("send");
    }
  }

  function close() {
    setActive(null);
  }

  function confirmAge() {
    writeAdultOk();
    setStep("send");
  }

  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [active]);

  const msg = active ? extrasOrderMessage(aptName, active) : "";
  const wa = `https://wa.me/${phoneDigits()}?text=${encodeURIComponent(msg)}`;
  const tg = `https://t.me/${TELEGRAM_USERNAME}?text=${encodeURIComponent(msg)}`;
  const genericMsg = encodeURIComponent(`Здравствуйте! Квартира «${aptName}». `);

  return (
    <div className="space-y-5">
      <div className="border border-[#1a1612]/10 bg-[linear-gradient(165deg,#faf6ef_0%,#f3ebe0_55%,#efe4d4_100%)] px-5 py-5 sm:px-7">
        <p className="text-[11px] uppercase tracking-[0.22em] text-[#9a7b4f]">Для гостей Home24</p>
        <p className="font-display mt-2 text-[24px] font-semibold leading-tight tracking-tight text-[#1a1612]">
          Сделаем проживание удобнее
        </p>
        <p className="mt-2 max-w-xl text-[14px] leading-relaxed text-[#3a342c]/80">
          Выберите услугу — откроется сообщение менеджеру, останется только отправить. Стоимость и
          время уточнит менеджер.
        </p>
      </div>

      {EXTRAS_SECTIONS.map((sec) => {
        const items = EXTRA_SERVICES.filter((s) => s.section === sec.id);
        return (
          <div key={sec.id}>
            <p className="mb-2.5 text-[11px] uppercase tracking-[0.22em] text-[#9a7b4f]">{sec.title}</p>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {items.map((s) => (
                <ServiceCard key={s.id} service={s} onClick={() => openService(s)} />
              ))}
            </div>
          </div>
        );
      })}

      <p className="text-[13px] leading-relaxed text-[#1a1612]/50">
        Не нашли нужное? Позвоните или напишите менеджеру {MANAGER_HOURS_SITE} — постараемся помочь.
      </p>
      <div className="grid grid-cols-2 gap-2.5">
        <a
          href={`tel:${PHONE_TEL}`}
          className="bg-[#1a1612] px-3 py-3.5 text-center text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] no-underline"
        >
          Позвонить
        </a>
        <a
          href={`https://wa.me/${phoneDigits()}?text=${genericMsg}`}
          target="_blank"
          rel="noreferrer"
          className="border border-[#1a1612] px-3 py-3.5 text-center text-[11px] uppercase tracking-[0.16em] text-[#1a1612] no-underline"
        >
          Написать
        </a>
      </div>

      {active ? (
        <OrderSheet
          titleId={titleId}
          service={active}
          step={step}
          wa={wa}
          tg={tg}
          onClose={close}
          onAgeOk={confirmAge}
        />
      ) : null}
    </div>
  );
}

function ServiceCard({ service, onClick }: { service: ExtraService; onClick: () => void }) {
  const adult = !!service.adult;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative block w-full border px-4 py-4 pr-10 text-left transition hover:border-[#9a7b4f]/55 active:scale-[0.99] ${
        adult
          ? "border-[#1a1612] bg-[#1a1612] text-[#efe8dc]"
          : "border-[#1a1612]/12 bg-[#faf6ef] text-[#1a1612]"
      }`}
    >
      <span className={`text-[11px] uppercase tracking-[0.2em] ${adult ? "text-[#d4b98a]" : "text-[#9a7b4f]"}`}>
        {service.eyebrow}
      </span>
      <span className="mt-1.5 flex flex-wrap items-center gap-2 text-[19px] font-semibold leading-tight tracking-tight">
        {service.name}
        {adult ? (
          <span className="inline-flex bg-[#efe8dc] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-[#1a1612]">
            18+
          </span>
        ) : null}
      </span>
      <span className={`mt-2 block text-[13px] leading-snug ${adult ? "text-[#efe8dc]/65" : "text-[#1a1612]/55"}`}>
        {service.blurb}
      </span>
      <span
        aria-hidden
        className={`absolute right-4 top-4 text-[18px] ${adult ? "text-[#d4b98a]" : "text-[#9a7b4f]"}`}
      >
        →
      </span>
    </button>
  );
}

function OrderSheet({
  titleId,
  service,
  step,
  wa,
  tg,
  onClose,
  onAgeOk,
}: {
  titleId: string;
  service: ExtraService;
  step: "age" | "send";
  wa: string;
  tg: string;
  onClose: () => void;
  onAgeOk: () => void;
}) {
  const [dob, setDob] = useState("");
  const [err, setErr] = useState("");
  const age = ageFromIsoDate(dob);

  function submitAge() {
    if (!dob) {
      setErr("Укажите дату рождения");
      return;
    }
    if (age === null) {
      setErr("Проверьте дату рождения");
      return;
    }
    if (age < 18) {
      setErr("Услуга доступна только с 18 лет");
      return;
    }
    setErr("");
    onAgeOk();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-[#1a1612]/55 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-[440px] border-t-[3px] border-[#9a7b4f] bg-[#faf6ef] px-5 pb-5 pt-[22px] shadow-[0_-12px_40px_rgba(26,22,18,0.25)]">
        <p className="text-[11px] uppercase tracking-[0.24em] text-[#9a7b4f]">Заказ услуги</p>
        <h3 id={titleId} className="mt-1.5 text-[22px] font-semibold tracking-tight text-[#1a1612]">
          {service.name}
        </h3>

        {step === "age" ? (
          <div className="mt-3">
            <p className="text-[14px] leading-relaxed text-[#1a1612]/70">
              Эта услуга только для гостей старше 18 лет. Укажите дату рождения.
            </p>
            <div className="mt-3 flex gap-2">
              <input
                type="date"
                value={dob}
                max={new Date().toISOString().slice(0, 10)}
                onChange={(e) => {
                  setDob(e.target.value);
                  setErr("");
                }}
                className="w-full border border-[#1a1612]/20 bg-white px-3 py-3 text-[16px] text-[#1a1612] outline-none focus:border-[#9a7b4f]"
              />
            </div>
            <p className="mt-2 min-h-[18px] text-[13px] text-[#b3261e]">{err}</p>
            <div className="mt-1 flex flex-col gap-2">
              <button
                type="button"
                onClick={submitAge}
                className="bg-[#1a1612] px-3 py-3.5 text-center text-[14px] font-semibold uppercase tracking-[0.05em] text-[#efe8dc]"
              >
                Подтвердить
              </button>
              <button
                type="button"
                onClick={onClose}
                className="bg-transparent px-3 py-3 text-center text-[14px] font-semibold uppercase tracking-[0.05em] text-[#1a1612]/55"
              >
                Отмена
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-3">
            <p className="mb-3.5 text-[14px] leading-relaxed text-[#1a1612]/70">
              {service.adult
                ? "Всё обсуждается лично с менеджером — деликатно и конфиденциально. Напишите или позвоните, если что-то понадобится."
                : "Выберите, как удобнее связаться — сообщение уже будет готово. Стоимость и время уточнит менеджер."}
            </p>
            <div className="flex flex-col gap-2">
              <a
                href={wa}
                target="_blank"
                rel="noreferrer"
                className="bg-[#1f8f4e] px-3 py-3.5 text-center text-[14px] font-semibold uppercase tracking-[0.05em] text-white no-underline"
              >
                Написать в WhatsApp
              </a>
              <a
                href={tg}
                target="_blank"
                rel="noreferrer"
                className="bg-[#2a8bd0] px-3 py-3.5 text-center text-[14px] font-semibold uppercase tracking-[0.05em] text-white no-underline"
              >
                Написать в Telegram
              </a>
              <a
                href={`tel:${PHONE_TEL}`}
                className="bg-[#1a1612] px-3 py-3.5 text-center text-[14px] font-semibold uppercase tracking-[0.05em] text-[#efe8dc] no-underline"
              >
                Позвонить менеджеру
              </a>
              <button
                type="button"
                onClick={onClose}
                className="bg-transparent px-3 py-3 text-center text-[14px] font-semibold uppercase tracking-[0.05em] text-[#1a1612]/55"
              >
                Закрыть
              </button>
            </div>
            <p className="mt-3 text-[12px] leading-relaxed text-[#1a1612]/45">
              {PHONE_LABEL} · {MANAGER_HOURS_SITE}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
