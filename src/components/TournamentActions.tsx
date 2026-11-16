"use client";

import { useState } from "react";
import { AuthPanel } from "@/components/AuthPanel";

export function TournamentActions({
  tournamentId,
  status,
  entryFee,
}: {
  tournamentId: number;
  status: string;
  entryFee: number;
}) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function join() {
    setBusy(true);
    setMsg("");
    const res = await fetch(`/api/tournaments/${tournamentId}/join`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ payFromBalance: true }),
    });
    const data = await res.json();
    setBusy(false);
    setMsg(
      res.ok
        ? data.registration.payment_status === "paid"
          ? `Ты в турнире. Списано ${entryFee}₽.`
          : "Заявка есть, но на балансе не хватило — пополни кошелёк."
        : data.error || "Ошибка",
    );
  }

  async function ready() {
    setBusy(true);
    setMsg("");
    const res = await fetch(`/api/tournaments/${tournamentId}/lobby`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "ready" }),
    });
    const data = await res.json();
    setBusy(false);
    setMsg(res.ok ? "Ты в комнате ✅" : data.error || "Ошибка");
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_280px]">
      <div className="flex flex-wrap gap-3">
        {status === "open" && (
          <button className="btn btn-primary" disabled={busy} onClick={join}>
            Записаться за {entryFee}₽
          </button>
        )}
        {status === "checkin" && (
          <button className="btn btn-primary" disabled={busy} onClick={ready}>
            Я в комнате
          </button>
        )}
        {msg && <p className="w-full text-sm text-[var(--muted)]">{msg}</p>}
      </div>
      <AuthPanel compact />
    </div>
  );
}
