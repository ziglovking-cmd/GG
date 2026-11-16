"use client";

import { useEffect, useState } from "react";
import { AuthPanel } from "@/components/AuthPanel";

type Player = {
  id: number;
  display_name: string;
  brawl_tag: string;
  balance_rub: number;
};

export default function WalletPage() {
  const [player, setPlayer] = useState<Player | null>(null);
  const [amount, setAmount] = useState(100);
  const [msg, setMsg] = useState("");

  async function refresh() {
    const res = await fetch("/api/me");
    const data = await res.json();
    setPlayer(data.player);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function deposit() {
    setMsg("");
    const res = await fetch("/api/wallet/deposit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ amountRub: amount }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg(data.error || "Ошибка");
      return;
    }
    setMsg(
      data.sample
        ? `Демо: +${amount}₽ зачислено.`
        : "Заявка создана, жди подтверждения.",
    );
    await refresh();
  }

  return (
    <main className="mx-auto w-full max-w-xl px-5 py-12">
      <p className="chip">Кошелёк</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-6xl tracking-wide">
        Баланс
      </h1>
      <p className="mt-3 text-[var(--muted)]">
        Пополни баланс и пишись в турики. Вход 50₽ списывается при записи.
      </p>

      <div className="mt-8 space-y-6">
        <AuthPanel />
        {player && (
          <>
            <p className="text-3xl font-semibold">
              {player.balance_rub}
              <span className="text-lg text-[var(--muted)]"> ₽</span>
            </p>
            <div className="flex gap-3">
              <input
                className="field"
                type="number"
                min={50}
                max={10000}
                value={amount}
                onChange={(e) => setAmount(Number(e.target.value))}
              />
              <button className="btn btn-primary" onClick={deposit}>
                Закинуть
              </button>
            </div>
            {msg && <p className="text-sm text-[var(--muted)]">{msg}</p>}
          </>
        )}
      </div>
    </main>
  );
}
