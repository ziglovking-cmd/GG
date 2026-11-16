"use client";

import { useEffect, useState } from "react";

/** Polls lobby settle endpoint while check-in is active. */
export function LobbyTicker({
  tournamentId,
  active,
}: {
  tournamentId: number;
  active: boolean;
}) {
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    if (!active) return;
    let alive = true;

    async function tick() {
      try {
        const res = await fetch(`/api/tournaments/${tournamentId}/lobby`);
        const data = await res.json();
        if (!alive) return;
        setRemaining(data.remainingMs ?? 0);
        if (data.status === "checkin" && (data.remainingMs ?? 0) === 0) {
          await fetch(`/api/cron/lobby`);
          window.location.reload();
        }
      } catch {
        /* ignore */
      }
    }

    tick();
    const id = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [tournamentId, active]);

  if (!active || remaining == null) return null;
  const sec = Math.ceil(remaining / 1000);
  return (
    <p className="mt-2 text-sm text-[var(--coral)]">
      Чек-ин: {sec > 0 ? `${sec}с` : "закрывается…"}
    </p>
  );
}
