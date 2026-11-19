"use client";

import { useEffect, useRef, useState } from "react";
import { MANAGER_HOURS, PHONE_LABEL, PHONE_TEL } from "@/lib/guest-ui";

type Msg = {
  role: "user" | "assistant";
  text: string;
  sources?: { title: string; section: string; slug: string }[];
  grounded?: boolean;
};

const SUGGESTIONS = ["Где Wi‑Fi?", "Как заселиться?", "Парковка платная?", "Можно с питомцем?"];

export function GuestRagChat({ slug, aptName }: { slug: string; aptName: string }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      role: "assistant",
      text: `Спросите про «${aptName}» — отвечу только по инструкции этой квартиры, без выдумок.`,
      grounded: true,
    },
  ]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, open]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setBusy(true);
    try {
      const res = await fetch("/api/rag/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, slug }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMsgs((m) => [
          ...m,
          {
            role: "assistant",
            text: data.error || `Не удалось ответить. Менеджер: ${PHONE_LABEL}`,
            grounded: false,
          },
        ]);
      } else {
        setMsgs((m) => [
          ...m,
          {
            role: "assistant",
            text: data.answer,
            sources: data.sources,
            grounded: data.grounded,
          },
        ]);
      }
    } catch {
      setMsgs((m) => [
        ...m,
        { role: "assistant", text: `Сбой сети. Напишите менеджеру ${PHONE_LABEL}.`, grounded: false },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-[72px] right-4 z-40 border-0 bg-[#1a1612] px-4 py-3.5 text-[11px] uppercase tracking-[0.16em] text-[#efe8dc] shadow-[0_18px_40px_-24px_rgba(26,22,18,0.9)] lg:bottom-8"
      >
        Спросить гид
      </button>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
          <button
            type="button"
            className="absolute inset-0 bg-[#1a1612]/45 backdrop-blur-[2px]"
            aria-label="закрыть"
            onClick={() => setOpen(false)}
          />
          <div className="relative flex max-h-[min(860px,92dvh)] w-full max-w-[520px] flex-col overflow-hidden border border-[#1a1612]/10 bg-[#efe8dc] shadow-[0_30px_80px_-40px_rgba(26,22,18,0.85)] sm:max-h-[80dvh]">
            <div className="border-b border-[#1a1612]/8 bg-[linear-gradient(135deg,#1a1612_0%,#2f261e_55%,#9a7b4f_100%)] px-5 py-4 text-[#efe8dc]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.22em] text-[#c4a574]">Home24 · RAG</p>
                  <p className="font-display mt-1 text-[24px] font-semibold leading-none">Помощник по квартире</p>
                  <p className="mt-2 text-[13px] text-[#efe8dc]/72">
                    Отвечает только по инструкции «{aptName}»
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="border border-[#efe8dc]/25 bg-transparent px-3 py-2 text-[11px] uppercase tracking-[0.14em] text-[#efe8dc]"
                >
                  Закрыть
                </button>
              </div>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
              {msgs.map((m, i) => (
                <div
                  key={`${m.role}-${i}`}
                  className={`max-w-[92%] px-4 py-3 text-[14px] leading-relaxed ${
                    m.role === "user"
                      ? "ml-auto bg-[#1a1612] text-[#efe8dc]"
                      : "border border-[#1a1612]/10 bg-[#faf6ef] text-[#1a1612]"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{m.text}</p>
                  {m.role === "assistant" && m.sources?.length ? (
                    <div className="mt-3 border-t border-[#1a1612]/8 pt-2">
                      <p className="text-[10px] uppercase tracking-[0.18em] text-[#9a7b4f]">Источники</p>
                      <ul className="mt-1 space-y-1 text-[12px] text-[#1a1612]/60">
                        {m.sources.map((s) => {
                          const href =
                            s.section === "card"
                              ? `/g/${s.slug}`
                              : s.section === "faq"
                                ? `/g/${s.slug}/faq`
                                : `/g/${s.slug}/${s.section}`;
                          return (
                            <li key={`${s.slug}-${s.section}-${s.title}`}>
                              <a className="text-[#1a1612] underline-offset-2 hover:underline" href={href}>
                                {s.title}
                              </a>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null}
                  {m.role === "assistant" && m.grounded === false ? (
                    <p className="mt-2 text-[12px] text-[#8a3b2b]">Без опоры в инструкции — лучше уточнить у менеджера.</p>
                  ) : null}
                </div>
              ))}
              {busy ? (
                <p className="text-[12px] uppercase tracking-[0.16em] text-[#9a7b4f]">Ищу в инструкции…</p>
              ) : null}
              <div ref={endRef} />
            </div>

            <div className="border-t border-[#1a1612]/10 bg-[#faf6ef] px-4 py-3">
              <div className="mb-3 flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    disabled={busy}
                    onClick={() => send(s)}
                    className="border border-[#1a1612]/12 bg-[#efe8dc] px-3 py-2 text-[12px] text-[#1a1612]"
                  >
                    {s}
                  </button>
                ))}
              </div>
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void send(input);
                }}
              >
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Вопрос по этой квартире"
                  className="min-w-0 flex-1 border border-[#1a1612]/12 bg-[#efe8dc] px-3 py-3 text-[15px] text-[#1a1612] outline-none focus:border-[#9a7b4f]"
                />
                <button
                  type="submit"
                  disabled={busy || !input.trim()}
                  className="border-0 bg-[#1a1612] px-4 py-3 text-[11px] uppercase tracking-[0.14em] text-[#efe8dc] disabled:opacity-40"
                >
                  Спросить
                </button>
              </form>
              <p className="mt-2 text-[11px] leading-relaxed text-[#1a1612]/45">
                Менеджер · {MANAGER_HOURS} ·{" "}
                <a href={`tel:${PHONE_TEL}`} className="text-[#1a1612]">
                  {PHONE_LABEL}
                </a>
              </p>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
