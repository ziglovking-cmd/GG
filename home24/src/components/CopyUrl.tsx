"use client";

import { useState } from "react";

export function CopyUrl({ url }: { url: string }) {
  const [done, setDone] = useState(false);

  return (
    <button
      type="button"
      className="shrink-0 text-[11px] uppercase tracking-[0.16em] text-[#1a1612]/35 hover:text-[#9a7b4f]"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(url);
        } catch {
          const el = document.createElement("textarea");
          el.value = url;
          document.body.appendChild(el);
          el.select();
          document.execCommand("copy");
          el.remove();
        }
        setDone(true);
        window.setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? "скопировано" : "копировать"}
    </button>
  );
}
