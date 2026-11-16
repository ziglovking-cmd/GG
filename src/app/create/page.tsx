"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { AuthPanel } from "@/components/AuthPanel";

export default function CreatePage() {
  const router = useRouter();
  const [title, setTitle] = useState("GG Cup — Brawl Stars");
  const [entryFee, setEntryFee] = useState(50);
  const [prize, setPrize] = useState(150);
  const [maxPlayers, setMaxPlayers] = useState(8);
  const [adminToken, setAdminToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const headers: Record<string, string> = {
      "content-type": "application/json",
    };
    if (adminToken.trim()) {
      headers.authorization = `Bearer ${adminToken.trim()}`;
    }
    const res = await fetch("/api/tournaments", {
      method: "POST",
      headers,
      body: JSON.stringify({ title, entryFee, prize, maxPlayers }),
    });
    const data = await res.json();
    setBusy(false);
    if (!res.ok) {
      setError(data.error || "Не удалось создать");
      return;
    }
    router.push(`/tournaments/${data.tournament.id}`);
  }

  return (
    <main className="mx-auto w-full max-w-xl px-5 py-12">
      <p className="chip">Новый турик</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-6xl tracking-wide">
        Создать
      </h1>
      <p className="mt-3 text-[var(--muted)]">
        Анонс уйдёт в Telegram-канал. По умолчанию вход 50₽, приз 150₽.
      </p>

      <div className="mt-8 space-y-6">
        <AuthPanel />
        <form onSubmit={submit} className="space-y-3">
          <input
            className="field"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Название"
            required
          />
          <div className="grid grid-cols-3 gap-3">
            <input
              className="field"
              type="number"
              value={entryFee}
              onChange={(e) => setEntryFee(Number(e.target.value))}
              placeholder="Вход"
            />
            <input
              className="field"
              type="number"
              value={prize}
              onChange={(e) => setPrize(Number(e.target.value))}
              placeholder="Приз"
            />
            <input
              className="field"
              type="number"
              value={maxPlayers}
              onChange={(e) => setMaxPlayers(Number(e.target.value))}
              placeholder="Слоты"
            />
          </div>
          <input
            className="field"
            value={adminToken}
            onChange={(e) => setAdminToken(e.target.value)}
            placeholder="ADMIN_TOKEN (если без сессии игрока)"
          />
          {error && <p className="text-sm text-[var(--coral)]">{error}</p>}
          <button className="btn btn-primary w-full" disabled={busy}>
            {busy ? "..." : "Создать турик"}
          </button>
        </form>
      </div>
    </main>
  );
}
