"use client";

import { useCallback, useEffect, useState } from "react";

type Lead = {
  id: string;
  createdAt: string;
  status: string;
  name: string;
  phone: string;
  service: string;
  slot: string;
  urgency: string;
  summary: string;
  dialogSnippet: string;
  telegramSent: boolean;
};

type SessionRow = {
  id: string;
  createdAt: string;
  updatedAt: string;
  status: string;
  urgency: string;
  draft: {
    name?: string;
    phone?: string;
    serviceTitle?: string;
    slotLabel?: string;
  };
  messageCount: number;
  messages: Array<{ role: string; text: string; at: string }>;
};

export default function AdminDashboard() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/leads", { cache: "no-store" });
      const data = await res.json();
      setLeads(data.leads || []);
      setSessions(data.sessions || []);
      setError(null);
    } catch {
      setError("Не удалось загрузить лог");
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 4000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div>
      <div className="topbar">
        <div className="brand">
          <div className="brand-mark">А</div>
          <div>
            <h1>АйАдмин · админка</h1>
            <p>Заявки и лог диалогов · автообновление</p>
          </div>
        </div>
        <div className="nav">
          <a href="/">← К демо-чату</a>
          <button className="chip" type="button" onClick={() => void load()}>
            Обновить
          </button>
        </div>
      </div>

      {error && <p className="muted">{error}</p>}

      <div className="admin-layout">
        <section className="panel">
          <h2>Заявки ({leads.length})</h2>
          <div className="list">
            {leads.length === 0 && (
              <div className="item muted">Пока пусто — проведите запись в чате.</div>
            )}
            {leads.map((l) => (
              <article key={l.id} className="item">
                <div className="title">
                  <strong>
                    {l.name} · {l.phone}
                  </strong>
                  <span className={`badge ${l.status}`}>{l.status}</span>
                </div>
                <div className="muted">
                  {l.service} · {l.slot}
                  {l.urgency !== "normal" ? ` · ${l.urgency}` : ""}
                  {l.telegramSent ? " · TG ✓" : " · TG offline/log"}
                </div>
                <div className="muted">{new Date(l.createdAt).toLocaleString("ru-RU")}</div>
                <div className="pre">{l.dialogSnippet}</div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <h2>Диалоги ({sessions.length})</h2>
          <div className="list">
            {sessions.map((s) => (
              <article key={s.id} className="item">
                <div className="title">
                  <strong>
                    {s.draft.name || "Гость"} · {s.messageCount} сообщ.
                  </strong>
                  <span className={`badge ${s.status}`}>{s.status}</span>
                </div>
                <div className="muted">
                  {s.draft.serviceTitle || "услуга не выбрана"}
                  {s.draft.slotLabel ? ` · ${s.draft.slotLabel}` : ""}
                </div>
                <div className="pre">
                  {s.messages
                    .slice(-4)
                    .map((m) => `${m.role === "user" ? "Пациент" : "Бот"}: ${m.text}`)
                    .join("\n")}
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
