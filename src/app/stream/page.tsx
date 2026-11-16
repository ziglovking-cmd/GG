import { publicTournamentPayload } from "@/lib/tournaments";

export const dynamic = "force-dynamic";

export default async function StreamPage() {
  const data = await publicTournamentPayload();
  const t = data.tournament;
  const embed = t?.stream_embed_url;

  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-12">
      <div className="flex items-center gap-3">
        {(t?.status === "live" || t?.status === "checkin") && (
          <span className="live-dot" />
        )}
        <p className="chip">Трансляция</p>
      </div>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-6xl tracking-wide">
        {t?.title ?? "GG Cup Live"}
      </h1>
      <p className="mt-3 text-[var(--muted)]">
        Стрим турнира. Анонсы победителей и сеток дублируются в Telegram-канал.
      </p>

      <div className="mt-8 aspect-video w-full overflow-hidden bg-black/50">
        {embed ? (
          <iframe
            title="GG Cup stream"
            src={embed}
            className="h-full w-full"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[var(--muted)]">
            Стрим ещё не подключен. Админ: /stream URL
          </div>
        )}
      </div>
    </main>
  );
}
