"use client";

import { useEffect, useRef, useState, useTransition } from "react";

type ChatMessage = { role: "user" | "assistant"; text: string };

const PROMPTS = [
  "Сколько стоит чистка и можно завтра в 19:00?",
  "Болит зуб, что делать?",
  "Хочу записаться завтра вечером",
  "Есть ли рассрочка на имплант?",
  "Вы меня обманули, хочу жалобу!",
];

export default function ChatWidget() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("chatting");
  const [toast, setToast] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [booting, setBooting] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await fetch("/api/session", { method: "POST" });
      const data = await res.json();
      if (cancelled) return;
      setSessionId(data.sessionId);
      setMessages([{ role: "assistant", text: data.welcome }]);
      setBooting(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toast]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !sessionId || pending) return;

    setInput("");
    setMessages((m) => [...m, { role: "user", text: trimmed }]);
    setToast(null);

    startTransition(async () => {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, message: trimmed }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessages((m) => [
          ...m,
          { role: "assistant", text: "Секунду, сбой связи. Попробуйте ещё раз." },
        ]);
        return;
      }
      setMessages((m) => [...m, { role: "assistant", text: data.reply }]);
      setStatus(data.status);
      if (data.actions?.includes("booked")) {
        setToast("Заявка создана — карточка ушла админу (Telegram / лог на /admin)");
      } else if (data.actions?.includes("escalated") && data.lead) {
        setToast("Эскалация: живой админ получил карточку обращения");
      }
    });
  }

  const statusClass =
    status === "created" ? "ok" : status === "escalated" ? "warn" : "";

  const statusLabel: Record<string, string> = {
    chatting: "в диалоге",
    collecting: "собираем данные",
    created: "заявка создана",
    escalated: "эскалация админу",
    closed: "закрыто",
  };

  return (
    <div className="chat-card">
      <div className="chat-header">
        <div>
          <h3>Чат пациента</h3>
          <span>виджет для сайта клиники</span>
        </div>
        <div className={`status-pill ${statusClass}`}>
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: 99,
              background: status === "created" ? "var(--ok)" : "var(--accent)",
              display: "inline-block",
            }}
          />
          {statusLabel[status] || status}
        </div>
      </div>

      <div className="messages">
        {booting && <div className="muted">Подключаю АйАдмин…</div>}
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.text}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {toast && <div className="toast">{toast}</div>}

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Напишите сообщение…"
          disabled={booting || !sessionId}
          aria-label="Сообщение"
        />
        <button type="submit" disabled={booting || pending || !input.trim()}>
          {pending ? "…" : "Отправить"}
        </button>
      </form>

      <div style={{ padding: "0 0.9rem 0.9rem" }}>
        <div className="muted" style={{ marginBottom: 8 }}>
          Быстрые демо-фразы:
        </div>
        <div className="demo-prompts">
          {PROMPTS.map((p) => (
            <button key={p} type="button" onClick={() => void send(p)}>
              {p}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
