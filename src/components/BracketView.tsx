import type { Bracket } from "@/lib/types";

export function BracketView({ bracket }: { bracket: Bracket }) {
  const rounds = Array.from({ length: bracket.rounds }, (_, i) => i + 1);
  return (
    <div className="bracket-grid">
      {rounds.map((round) => (
        <div key={round} className="space-y-3">
          <p className="chip">Раунд {round}</p>
          {bracket.matches
            .filter((m) => m.round === round)
            .map((m) => {
              const out =
                m.playerAStatus === "noshow" ||
                m.playerBStatus === "noshow" ||
                m.playerAStatus === "bot" ||
                m.playerBStatus === "bot";
              return (
                <div
                  key={m.id}
                  className={`match-row ${out ? "out" : ""}`}
                >
                  <Slot
                    name={m.playerAName}
                    tag={m.playerATag}
                    status={m.playerAStatus}
                    win={m.winnerId != null && m.winnerId === m.playerAId}
                  />
                  <Slot
                    name={m.playerBName}
                    tag={m.playerBTag}
                    status={m.playerBStatus}
                    win={m.winnerId != null && m.winnerId === m.playerBId}
                  />
                </div>
              );
            })}
        </div>
      ))}
    </div>
  );
}

function Slot({
  name,
  tag,
  status,
  win,
}: {
  name: string | null;
  tag: string | null;
  status: string;
  win: boolean;
}) {
  const label =
    status === "bot"
      ? "BOT"
      : status === "noshow"
        ? `${name ?? "Игрок"} · ВЫБЫЛ`
        : name ?? "TBD";
  return (
    <div
      className={`flex items-center justify-between gap-3 py-1 text-sm ${
        win ? "text-[var(--lime)]" : "text-[var(--text)]"
      }`}
    >
      <span className="truncate font-semibold">{label}</span>
      <span className="shrink-0 text-xs text-[var(--muted)]">
        {status === "bot" ? "#BOT" : tag ?? ""}
      </span>
    </div>
  );
}
