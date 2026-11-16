import Link from "next/link";
import { listTournaments } from "@/lib/tournaments";

export const dynamic = "force-dynamic";

export default async function TournamentsPage() {
  const tournaments = await listTournaments();

  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="chip">Турики</p>
          <h1 className="mt-2 font-[family-name:var(--font-display)] text-6xl tracking-wide">
            Расписание
          </h1>
        </div>
        <Link href="/create" className="btn btn-primary">
          Создать турик
        </Link>
      </div>

      <ul className="mt-10 divide-y divide-white/10">
        {tournaments.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center justify-between gap-4 py-5">
            <div>
              <Link
                href={`/tournaments/${t.id}`}
                className="text-xl font-semibold hover:text-[var(--lime)]"
              >
                {t.title}
              </Link>
              <p className="mt-1 text-sm text-[var(--muted)]">
                {t.entry_fee_rub}₽ → {t.prize_rub}₽ · {t.paid_count ?? 0}/
                {t.max_players} · {t.status}
              </p>
            </div>
            <Link href={`/tournaments/${t.id}`} className="btn btn-ghost">
              Сетка
            </Link>
          </li>
        ))}
        {tournaments.length === 0 && (
          <li className="py-10 text-[var(--muted)]">Пока пусто — создай первый турик.</li>
        )}
      </ul>
    </main>
  );
}
