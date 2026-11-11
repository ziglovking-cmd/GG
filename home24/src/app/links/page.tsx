import { apartments } from "@/lib/catalog";
import { CANONICAL_ORIGIN, guestUrl } from "@/lib/site";
import { CopyUrl } from "@/components/CopyUrl";
import { BrandMark } from "@/components/BrandMark";

export default function LinksPage() {
  return (
    <div className="min-h-dvh bg-[#efe8dc] text-[#1a1612]">
      <header className="border-b border-[#1a1612]/10 px-5 py-5 sm:px-8">
        <div className="mx-auto flex max-w-[760px] items-center justify-between gap-4">
          <a href="/" className="flex items-center gap-3 no-underline">
            <BrandMark small />
            <span className="text-[11px] uppercase tracking-[0.28em] text-[#9a7b4f]">Home24</span>
          </a>
          <a href="/guest-links.txt" className="text-[11px] uppercase tracking-[0.16em] text-[#1a1612]/50 no-underline">
            Скачать .txt
          </a>
        </div>
      </header>
      <main className="mx-auto max-w-[760px] px-5 py-10 sm:px-8">
        <h1 className="font-display text-[44px] font-semibold leading-none tracking-tight sm:text-[56px]">
          Ссылки
          <br />
          для гостей
        </h1>
        <p className="mt-5 max-w-md text-[15px] leading-relaxed text-[#1a1612]/55">
          Рабочие адреса на сервере. Копируйте и отправляйте гостю — открывается в браузере по HTTPS, без VPN.
          База: {CANONICAL_ORIGIN}
        </p>
        <ul className="mt-10 m-0 list-none p-0">
          {apartments.map((a) => {
            const url = guestUrl(a.slug);
            return (
              <li key={a.slug} className="border-b border-[#1a1612]/10 py-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <a href={`/g/${a.slug}`} className="font-display text-[26px] font-semibold leading-none no-underline">
                      {a.name}
                    </a>
                    <p className="mt-2 break-all text-[12px] text-[#9a7b4f]">{url}</p>
                    <p className="mt-1 truncate text-[12px] text-[#1a1612]/40">{a.address}</p>
                  </div>
                  <CopyUrl url={url} />
                </div>
              </li>
            );
          })}
        </ul>
      </main>
    </div>
  );
}
