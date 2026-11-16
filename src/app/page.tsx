import Link from "next/link";
import { publicTournamentPayload } from "@/lib/tournaments";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const data = await publicTournamentPayload();
  const t = data.tournament;
  const bot = data.botUsername;
  const channel = data.channelUsername;

  return (
    <main>
      <section className="relative min-h-[calc(100vh-5rem)] overflow-hidden">
        <div className="hero-visual" aria-hidden />
        <div className="relative z-10 mx-auto flex min-h-[calc(100vh-5rem)] w-full max-w-6xl flex-col justify-center px-5 py-16">
          <p className="chip anim-rise">Brawl Stars · вход 50₽ · приз 150₽</p>
          <h1 className="anim-rise-delay mt-4 max-w-3xl font-[family-name:var(--font-display)] text-7xl leading-[0.9] tracking-[0.04em] text-white sm:text-8xl md:text-9xl">
            GG CUP
          </h1>
          <p className="anim-rise-delay-2 mt-5 max-w-xl text-lg text-[var(--muted)] sm:text-xl">
            Турики, сетки и стрим в одном месте. Чек-ин в комнату — 60 секунд:
            не зашёл, выбыл, в сетке сразу BOT.
          </p>
          <div className="anim-rise-delay-2 mt-8 flex flex-wrap gap-3">
            <Link href="/tournaments" className="btn btn-primary">
              Смотреть турики
            </Link>
            <a
              href={`https://t.me/${bot}`}
              className="btn btn-ghost"
              target="_blank"
              rel="noreferrer"
            >
              Открыть бота
            </a>
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-6xl px-5 py-20">
        <div className="flex flex-col gap-10 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-xl">
            <p className="chip">Сейчас</p>
            <h2 className="mt-3 font-[family-name:var(--font-display)] text-5xl tracking-wide">
              {t ? t.title : "Ждём анонс"}
            </h2>
            <p className="mt-3 text-[var(--muted)]">
              {t
                ? `Статус: ${statusLabel(t.status)}. Оплатили ${t.paid_count ?? 0}/${t.max_players}.`
                : "Создай турик на сайте или через бота — анонс улетит в канал."}
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            {t && (
              <Link href={`/tournaments/${t.id}`} className="btn btn-primary">
                Сетка и лобби
              </Link>
            )}
            <Link href="/stream" className="btn btn-ghost">
              {t?.status === "live" || t?.status === "checkin" ? (
                <span className="inline-flex items-center gap-2">
                  <span className="live-dot" /> Трансляция
                </span>
              ) : (
                "Трансляция"
              )}
            </Link>
            <a
              href={`https://t.me/${channel}`}
              className="btn btn-ghost"
              target="_blank"
              rel="noreferrer"
            >
              ТГК
            </a>
          </div>
        </div>

        <div className="mt-14 grid gap-10 md:grid-cols-3">
          <Feature
            title="Сетки"
            text="Бот собирает сетку из оплативших. No-show за минуту — сразу ВЫБЫЛ и слот BOT."
          />
          <Feature
            title="Деньги"
            text="Пополни баланс на сайте, вход 50₽ списывается при записи. Победителю 150₽."
          />
          <Feature
            title="Лобби"
            text="Админ даёт код комнаты Brawl. Игроки жмут «Я в комнате» за 60 сек — иначе вылет."
          />
        </div>
        {data.sample && (
          <p className="mt-10 text-sm text-[var(--muted)]">
            Сейчас на sample-данных. Подключи TELEGRAM_BOT_TOKEN, канал и ADMIN_TOKEN в секретах.
          </p>
        )}
      </section>
    </main>
  );
}

function Feature({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <h3 className="font-[family-name:var(--font-display)] text-3xl tracking-wide text-[var(--lime)]">
        {title}
      </h3>
      <p className="mt-2 text-[var(--muted)]">{text}</p>
    </div>
  );
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    open: "запись",
    locked: "закрыт",
    checkin: "чек-ин 60с",
    live: "LIVE",
    finished: "завершён",
    draft: "черновик",
  };
  return map[status] ?? status;
}
