import Link from "next/link";
import { notFound } from "next/navigation";
import { BracketView } from "@/components/BracketView";
import { LobbyTicker } from "@/components/LobbyTicker";
import { TournamentActions } from "@/components/TournamentActions";
import { settleLobbyIfNeeded } from "@/lib/lobby";
import { parseBracket } from "@/lib/brackets";
import { publicTournamentPayload } from "@/lib/tournaments";

export const dynamic = "force-dynamic";

export default async function TournamentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: raw } = await params;
  const id = Number(raw);
  if (!Number.isFinite(id)) notFound();

  await settleLobbyIfNeeded(id);
  const data = await publicTournamentPayload(id);
  const t = data.tournament;
  if (!t) notFound();
  const bracket = data.bracket ?? parseBracket(t.bracket_json);

  const paid = data.players.filter((p) => p.payment_status === "paid");
  const waiting = paid.filter((p) => p.ready_status === "waiting");
  const ready = paid.filter((p) => p.ready_status === "ready");
  const noshow = paid.filter((p) => p.ready_status === "noshow");

  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-12">
      <p className="chip">{t.game}</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-6xl tracking-wide">
        {t.title}
      </h1>
      <p className="mt-3 max-w-2xl text-[var(--muted)]">
        Вход {t.entry_fee_rub}₽ · Приз {t.prize_rub}₽ · Статус{" "}
        <span className="text-[var(--lime)]">{t.status}</span>
        {t.room_code ? ` · Комната ${t.room_code}` : ""}
      </p>

      <div className="mt-8">
        <TournamentActions
          tournamentId={t.id}
          status={t.status}
          entryFee={t.entry_fee_rub}
        />
      </div>

      {(t.status === "checkin" || t.status === "live") && (
        <section className="mt-12">
          <h2 className="font-[family-name:var(--font-display)] text-4xl tracking-wide">
            Лобби
          </h2>
          <p className="mt-2 text-[var(--muted)]">
            60 секунд на «Я в комнате». Иначе — ВЫБЫЛ и BOT в сетке.
          </p>
          <LobbyTicker
            tournamentId={t.id}
            active={t.status === "checkin"}
          />
          <div className="mt-4 grid gap-6 sm:grid-cols-3">
            <Stat label="Готовы" value={String(ready.length)} />
            <Stat label="Ждут" value={String(waiting.length)} />
            <Stat label="Выбыли" value={String(noshow.length)} />
          </div>
        </section>
      )}

      <section className="mt-12">
        <div className="flex items-end justify-between gap-4">
          <h2 className="font-[family-name:var(--font-display)] text-4xl tracking-wide">
            Сетка
          </h2>
          <Link href="/stream" className="text-sm text-[var(--lime)]">
            Смотреть стрим →
          </Link>
        </div>
        <div className="mt-6">
          {bracket ? (
            <BracketView bracket={bracket} />
          ) : (
            <p className="text-[var(--muted)]">
              Сетка появится после открытия лобби (/room в боте или в админке).
            </p>
          )}
        </div>
      </section>

      <section className="mt-14">
        <h2 className="font-[family-name:var(--font-display)] text-4xl tracking-wide">
          Участники
        </h2>
        <ul className="mt-4 divide-y divide-white/10">
          {data.players.map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"
            >
              <span>
                {p.display_name}{" "}
                <span className="text-[var(--lime)]">{p.brawl_tag}</span>
              </span>
              <span className="text-[var(--muted)]">
                {p.payment_status} · {p.ready_status}
              </span>
            </li>
          ))}
          {data.players.length === 0 && (
            <li className="py-6 text-[var(--muted)]">Пока никто не записался</li>
          )}
        </ul>
      </section>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.14em] text-[var(--muted)]">
        {label}
      </p>
      <p className="mt-1 font-[family-name:var(--font-display)] text-5xl text-[var(--lime)]">
        {value}
      </p>
    </div>
  );
}
