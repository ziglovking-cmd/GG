"use client";

import { useState } from "react";

export default function AdminPage() {
  const [token, setToken] = useState("");
  const [tournamentId, setTournamentId] = useState(1);
  const [roomCode, setRoomCode] = useState("");
  const [log, setLog] = useState("");
  const [friends, setFriends] = useState<
    Array<{ id: number; display_name?: string; brawl_tag: string; status: string }>
  >([]);

  function headers() {
    return {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    };
  }

  async function openLobby() {
    const res = await fetch(`/api/tournaments/${tournamentId}/lobby`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({
        action: "open",
        roomCode,
        checkinSeconds: 60,
      }),
    });
    const data = await res.json();
    setLog(JSON.stringify(data, null, 2));
  }

  async function settle() {
    const res = await fetch(`/api/tournaments/${tournamentId}/lobby`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ action: "settle" }),
    });
    setLog(JSON.stringify(await res.json(), null, 2));
  }

  async function loadFriends() {
    const res = await fetch("/api/admin/friends", { headers: headers() });
    const data = await res.json();
    setFriends(data.queue || []);
    setLog(data.note || "");
  }

  async function markFriend(id: number) {
    const res = await fetch("/api/admin/friends", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ id }),
    });
    setLog(JSON.stringify(await res.json(), null, 2));
    await loadFriends();
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-12">
      <p className="chip">Организатор</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-6xl tracking-wide">
        Админка
      </h1>
      <p className="mt-3 text-[var(--muted)]">
        Комнату в Brawl создаёшь в игре сам. Сюда вписываешь код — бот гоняет
        чек-ин 60с, no-show → ВЫБЫЛ + BOT в сетке. Очередь тегов — чтобы добавить
        всех в друзья вручную.
      </p>

      <div className="mt-8 space-y-3">
        <input
          className="field"
          type="password"
          placeholder="ADMIN_TOKEN"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <input
          className="field"
          type="number"
          placeholder="ID турнира"
          value={tournamentId}
          onChange={(e) => setTournamentId(Number(e.target.value))}
        />
        <input
          className="field"
          placeholder="Код комнаты Brawl"
          value={roomCode}
          onChange={(e) => setRoomCode(e.target.value)}
        />
        <div className="flex flex-wrap gap-3">
          <button className="btn btn-primary" onClick={openLobby}>
            Открыть лобби 60с
          </button>
          <button className="btn btn-ghost" onClick={settle}>
            Закрыть чек-ин
          </button>
          <button className="btn btn-ghost" onClick={loadFriends}>
            Очередь друзей
          </button>
        </div>
      </div>

      {friends.length > 0 && (
        <ul className="mt-8 divide-y divide-white/10">
          {friends.map((f) => (
            <li
              key={f.id}
              className="flex items-center justify-between gap-3 py-3 text-sm"
            >
              <span>
                #{f.id} {f.display_name}{" "}
                <span className="text-[var(--lime)]">{f.brawl_tag}</span> ·{" "}
                {f.status}
              </span>
              {f.status === "pending" && (
                <button className="btn btn-ghost" onClick={() => markFriend(f.id)}>
                  Добавлен
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {log && (
        <pre className="mt-8 overflow-auto whitespace-pre-wrap text-xs text-[var(--muted)]">
          {log}
        </pre>
      )}
    </main>
  );
}
