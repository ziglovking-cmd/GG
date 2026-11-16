"use client";

import { useEffect, useState, type FormEvent } from "react";

type Player = {
  id: number;
  display_name: string;
  username: string | null;
  brawl_tag: string;
  balance_rub: number;
};

export function AuthPanel({ compact = false }: { compact?: boolean }) {
  const [player, setPlayer] = useState<Player | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [brawlTag, setBrawlTag] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch("/api/me")
      .then((r) => r.json())
      .then((d) => setPlayer(d.player ?? null))
      .catch(() => setPlayer(null));
  }, []);

  async function login(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ displayName, brawlTag }),
    });
    const data = await res.json();
    setLoading(false);
    if (!res.ok) {
      setError(data.error || "Ошибка");
      return;
    }
    setPlayer(data.player);
  }

  if (player) {
    return (
      <div className={compact ? "text-sm" : "space-y-1"}>
        <p className="font-semibold">
          {player.display_name}{" "}
          <span className="text-[var(--lime)]">{player.brawl_tag}</span>
        </p>
        <p className="text-[var(--muted)]">Баланс: {player.balance_rub}₽</p>
      </div>
    );
  }

  return (
    <form onSubmit={login} className="space-y-3">
      {!compact && (
        <p className="text-sm text-[var(--muted)]">
          Brawl Tag обязателен — без него в турик не пустим.
        </p>
      )}
      <input
        className="field"
        placeholder="Ник"
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
        required
      />
      <input
        className="field"
        placeholder="Brawl Tag, например #2PP0ABC"
        value={brawlTag}
        onChange={(e) => setBrawlTag(e.target.value)}
        required
      />
      {error && <p className="text-sm text-[var(--coral)]">{error}</p>}
      <button className="btn btn-primary w-full" disabled={loading}>
        {loading ? "..." : "Войти"}
      </button>
    </form>
  );
}
