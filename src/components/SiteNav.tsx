import Link from "next/link";

const links = [
  { href: "/tournaments", label: "Турики" },
  { href: "/stream", label: "Стрим" },
  { href: "/wallet", label: "Баланс" },
  { href: "/create", label: "Создать" },
  { href: "/admin", label: "Админ" },
];

export function SiteNav() {
  return (
    <header className="relative z-20 mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-5">
      <Link href="/" className="group flex items-baseline gap-2">
        <span className="font-[family-name:var(--font-display)] text-3xl tracking-[0.06em] text-[var(--lime)]">
          GG CUP
        </span>
        <span className="hidden text-xs uppercase tracking-[0.18em] text-[var(--muted)] sm:inline">
          Brawl Stars
        </span>
      </Link>
      <nav className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2 text-sm text-[var(--muted)]">
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className="transition-colors hover:text-[var(--lime)]"
          >
            {l.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
