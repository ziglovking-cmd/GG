"use client";

import { useState } from "react";

export function CopyField({ label, value }: { label: string; value: string }) {
  const [done, setDone] = useState(false);
  const empty = !value.trim();

  return (
    <button
      type="button"
      disabled={empty}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
        } catch {
          const el = document.createElement("textarea");
          el.value = value;
          document.body.appendChild(el);
          el.select();
          document.execCommand("copy");
          el.remove();
        }
        setDone(true);
        window.setTimeout(() => setDone(false), 1600);
      }}
      className="flex w-full items-end justify-between gap-3 border border-[#1a1612]/10 bg-[#efe8dc] px-4 py-4 text-left disabled:opacity-60"
    >
      <span className="min-w-0">
        <span className="block text-[11px] uppercase tracking-[0.2em] text-[#9a7b4f]">{label}</span>
        <span className="font-display mt-1 block break-all text-[26px] font-semibold leading-none tracking-tight">
          {empty ? "—" : value}
        </span>
      </span>
      <span className="shrink-0 text-[11px] uppercase tracking-[0.16em] text-[#1a1612]/35">
        {empty ? "" : done ? "скопировано" : "копировать"}
      </span>
    </button>
  );
}
