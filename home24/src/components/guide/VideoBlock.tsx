"use client";

import { useState } from "react";
import { PUBLIC_DISKS, type DiskId } from "@/lib/disks";
import { playableSrc } from "@/lib/media-src";

export function VideoBlock({
  title,
  path,
  disk,
  url,
}: {
  title: string;
  path?: string;
  disk?: string;
  url?: string;
}) {
  const [tick, setTick] = useState(0);
  const [failed, setFailed] = useState(false);
  const siteHref = disk === "home24" ? url || "" : "";
  const src = playableSrc({ path, disk, url }, tick);
  const lower = (path || url || "").toLowerCase();
  const mime = lower.endsWith(".mov") ? "video/quicktime" : "video/mp4";
  const diskHref =
    path && disk && disk !== "local" && disk !== "home24" && disk in PUBLIC_DISKS
      ? `${PUBLIC_DISKS[disk as DiskId]}?path=${encodeURIComponent(path)}`
      : "";
  const showBar = Boolean(failed || (diskHref && lower.endsWith(".mov")));

  if (!src) {
    return (
      <figure className="my-6 border border-[#1a1612]/10 bg-[#faf6ef]">
        <figcaption className="px-4 py-3 text-[12px] uppercase tracking-[0.16em] text-[#9a7b4f]">{title}</figcaption>
        <p className="px-4 pb-8 text-center text-sm text-[#1a1612]/40">Видео для этой квартиры ещё не загружено.</p>
      </figure>
    );
  }

  return (
    <figure className="my-6 overflow-hidden border border-[#1a1612] bg-[#1a1612]">
      <figcaption className="px-4 py-3 text-[12px] uppercase tracking-[0.16em] text-[#c4b08a]">{title}</figcaption>
      <video
        key={tick}
        controls
        playsInline
        preload="none"
        controlsList="nodownload"
        className="aspect-video w-full bg-black"
        onError={() => setFailed(true)}
        onLoadedData={() => setFailed(false)}
      >
        <source src={src} type={mime} />
        {mime !== "video/mp4" ? <source src={src} type="video/mp4" /> : null}
      </video>
      {showBar ? (
        <div className="flex items-center justify-between gap-3 px-4 py-3 text-sm text-[#efe8dc]/70">
          {failed ? (
            <span>Не открылось. Ещё раз — часто помогает на телефоне.</span>
          ) : (
            <span>Большой ролик — если крутится долго, откройте на Диске.</span>
          )}
          <span className="flex shrink-0 gap-2">
            {failed ? (
              <button
                type="button"
                className="border border-[#9a7b4f] px-3 py-1 text-[11px] uppercase tracking-[0.14em] text-[#c4b08a]"
                onClick={() => {
                  setFailed(false);
                  setTick((n) => n + 1);
                }}
              >
                Ещё раз
              </button>
            ) : null}
            {diskHref ? (
              <a
                href={diskHref}
                target="_blank"
                rel="noreferrer"
                className="border border-[#9a7b4f] px-3 py-1 text-[11px] uppercase tracking-[0.14em] text-[#c4b08a]"
              >
                Диск
              </a>
            ) : null}
            {siteHref ? (
              <a
                href={siteHref}
                target="_blank"
                rel="noreferrer"
                className="border border-[#9a7b4f] px-3 py-1 text-[11px] uppercase tracking-[0.14em] text-[#c4b08a]"
              >
                Сайт
              </a>
            ) : null}
          </span>
        </div>
      ) : null}
    </figure>
  );
}
