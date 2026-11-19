"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="min-h-dvh bg-[#efe8dc] px-5 py-24 text-center text-[#1a1612]">
      <p className="text-[11px] uppercase tracking-[0.28em] text-[#9a7b4f]">Home24</p>
      <h1 className="font-display mt-4 text-[40px] font-semibold leading-none">Страница не открылась</h1>
      <p className="mx-auto mt-4 max-w-sm text-[15px] leading-relaxed text-[#1a1612]/55">
        Обновите страницу. Если ошибка повторится, откройте инструкцию с главной или напишите менеджеру.
      </p>
      <button
        type="button"
        onClick={() => reset()}
        className="mt-8 border border-[#1a1612] px-6 py-3 text-[11px] uppercase tracking-[0.18em]"
      >
        Обновить
      </button>
    </div>
  );
}
