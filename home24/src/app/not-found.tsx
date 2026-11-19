export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-[#efe8dc] px-5 text-center text-[#1a1612]">
      <p className="text-[11px] uppercase tracking-[0.28em] text-[#9a7b4f]">Home24</p>
      <h1 className="font-display mt-4 text-[44px] font-semibold leading-none tracking-tight sm:text-[56px]">
        Этой ссылки уже нет
      </h1>
      <p className="mx-auto mt-4 max-w-sm text-[15px] leading-relaxed text-[#1a1612]/55">
        Откройте каталог и скопируйте ссылку заново — гостевая страница откроется.
      </p>
      <a
        href="/"
        className="mt-8 border border-[#1a1612] px-6 py-3 text-[11px] uppercase tracking-[0.18em] text-[#1a1612] no-underline"
      >
        К каталогу
      </a>
    </div>
  );
}
