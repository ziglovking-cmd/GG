import Image from "next/image";
import type { Apartment } from "@/lib/catalog";
import { mapsUrl, navUrl, reviewUrl, videosForSection, type SectionId } from "@/lib/sections";
import { PartnerOffers } from "@/components/guide/PartnerOffers";
import { VideoBlock } from "@/components/guide/VideoBlock";
import { CopyField } from "@/components/guide/CopyField";
import { parseWifi } from "@/lib/wifi";

export function KaitenDoc({
  apt,
  section,
  title,
  text,
}: {
  apt: Apartment;
  section: SectionId;
  title: string;
  text: string;
}) {
  const videos = videosForSection(apt, section);
  const wifi = section === "wifi" ? parseWifi(text) : null;
  const wifiNets = wifi?.networks.filter((n) => n.ssid || n.password) ?? [];
  return (
    <article className="k-doc">
      <p className="mb-3 text-[11px] uppercase tracking-[0.24em] text-[#9a7b4f]">«{apt.name}»</p>
      <h1 className="k-h1">{title}</h1>
      {section === "wifi" ? (
        <div className="mb-8 grid gap-px bg-[#1a1612]/10">
          {wifiNets.length ? (
            wifiNets.map((n, i) => (
              <div key={`${n.ssid || ""}-${i}`} className="grid gap-px">
                <CopyField label={wifiNets.length > 1 ? `Сеть ${i + 1}` : "Сеть"} value={n.ssid || ""} />
                <CopyField label={wifiNets.length > 1 ? `Пароль ${i + 1}` : "Пароль"} value={n.password || ""} />
              </div>
            ))
          ) : (
            <>
              <CopyField label="Сеть" value="" />
              <CopyField label="Пароль" value="" />
            </>
          )}
        </div>
      ) : null}
      {section === "partnery" ? <PartnerOffers /> : null}
      {section === "kak-dobratsya" && (
        <div className="mb-8 border border-[#1a1612]/10 bg-[#faf6ef] p-6">
          <p className="text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">Адрес</p>
          <p className="font-display mt-2 text-[26px] font-semibold leading-tight">{apt.address}</p>
          {apt.metro ? <p className="mt-3 text-[14px] text-[#1a1612]/50">{apt.metro}</p> : null}
          {apt.coords ? <p className="mt-1 text-[12px] text-[#1a1612]/35">{apt.coords}</p> : null}
          <div className="mt-6 grid grid-cols-2 gap-px bg-[#1a1612]/10">
            <a
              href={mapsUrl(apt)}
              target="_blank"
              rel="noreferrer"
              className="bg-[#1a1612] px-3 py-3.5 text-center text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] no-underline"
            >
              Карта
            </a>
            <a
              href={navUrl(apt)}
              target="_blank"
              rel="noreferrer"
              className="bg-[#9a7b4f] px-3 py-3.5 text-center text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] no-underline"
            >
              Маршрут
            </a>
          </div>
        </div>
      )}
      {section === "wifi" ? (
        <div className="border border-[#1a1612]/10 bg-[#faf6ef] px-5 py-6 sm:px-7">
          <Rich
            text={
              wifi?.note ||
              "Если интернет пропал: нажмите кнопку перезагрузки на роутере или выньте питание на 10 секунд. Роутер обычно у входной двери или над ней. Если не ожило — напишите персональному менеджеру (с 09:00 до 00:00)."
            }
          />
        </div>
      ) : text ? (
        <div className="border border-[#1a1612]/10 bg-[#faf6ef] px-5 py-6 sm:px-7">
          <Rich text={text} />
          {section === "otzyv" && reviewUrl(apt) ? (
            <p className="mt-6">
              <a
                href={reviewUrl(apt)}
                target="_blank"
                rel="noreferrer"
                className="inline-block bg-[#1a1612] px-4 py-3.5 text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] no-underline"
              >
                Оставить отзыв на Картах
              </a>
            </p>
          ) : null}
          {section === "parkovka" ? (
            <p className="mt-6 text-[15px] leading-relaxed text-[#3a342c]">
              <a href={mapsUrl(apt)} target="_blank" rel="noreferrer">
                Дом на Яндекс.Картах
              </a>
              {" — рядом видны знаки. Карта городских зон и оплата: "}
              <a href="https://parking.mos.ru/" target="_blank" rel="noreferrer">
                parking.mos.ru
              </a>
              .
            </p>
          ) : null}
        </div>
      ) : null}
      {section === "video" && (apt.photos || []).length
        ? (apt.photos || []).map((p) => (
            <figure key={p.src} className="my-6 overflow-hidden border border-[#1a1612]/10 bg-[#faf6ef]">
              <figcaption className="px-4 py-3 text-[12px] uppercase tracking-[0.16em] text-[#9a7b4f]">
                {p.title}
              </figcaption>
              <Image
                src={p.src}
                alt={p.alt || p.title}
                width={1280}
                height={718}
                className="block h-auto w-full"
                sizes="(max-width: 720px) 100vw, 640px"
              />
            </figure>
          ))
        : null}
      {videos.map((v) => (
        <VideoBlock key={v.name} title={v.title} path={v.path} disk={v.disk} url={v.url} />
      ))}
    </article>
  );
}

function linkify(text: string) {
  const parts = text.split(/(https?:\/\/[^\s]+)/g);
  return parts.map((part, i) =>
    part.startsWith("http") ? (
      <a key={i} href={part} target="_blank" rel="noreferrer">
        {part}
      </a>
    ) : (
      part
    ),
  );
}

function Rich({ text }: { text: string }) {
  const blocks = text.split(/\n\n+/);
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split("\n").filter((l) => l.trim());
        if (!lines.length) return null;
        if (lines.every((l) => l.trim().startsWith("•"))) {
          return (
            <ul key={i}>
              {lines.map((l, j) => (
                <li key={j}>{l.replace(/^•\s*/, "")}</li>
              ))}
            </ul>
          );
        }
        if (lines.filter((l) => /^\d+\./.test(l.trim())).length >= 2) {
          return (
            <ol key={i}>
              {lines.map((l, j) => (
                <li key={j}>{l.replace(/^\d+\.\s*/, "")}</li>
              ))}
            </ol>
          );
        }
        if (lines[0].startsWith(">")) {
          return (
            <blockquote key={i} className="k-callout">
              {lines.map((l) => l.replace(/^>\s?/, "")).join(" ")}
            </blockquote>
          );
        }
        return lines.map((line, j) => (
          <p key={`${i}-${j}`} className="k-line">
            {linkify(line)}
          </p>
        ));
      })}
    </>
  );
}
