"use client";

import { useEffect, useMemo, useState } from "react";
import { matchesSearch } from "@/lib/search";

type AptRow = {
  slug: string;
  id: number;
  name: string;
  address: string;
  metro: string;
  ready: boolean;
  videos: number;
  wifi: string;
};

type LibVideo = {
  id: string;
  title: string;
  filename: string;
  createdAt: string;
  slugs: string[] | "all";
  skipIfHas: boolean;
};

type AptFull = {
  slug: string;
  name: string;
  address: string;
  metro: string;
  coords: string;
  wifi: string;
  how: string;
  parking: string;
  checkin: string;
  checkout: string;
  rules: string;
  district: string;
  contacts: string;
  ready: boolean;
};

export function AdminApp() {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [ok, setOk] = useState<boolean | null>(null);
  const [tab, setTab] = useState<"video" | "flats" | "library">("video");
  const [rows, setRows] = useState<AptRow[]>([]);
  const [videos, setVideos] = useState<LibVideo[]>([]);
  const [q, setQ] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [scope, setScope] = useState<"all" | "selected">("all");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [skip, setSkip] = useState(true);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [editSlug, setEditSlug] = useState<string | null>(null);
  const [draft, setDraft] = useState<AptFull | null>(null);

  const filtered = useMemo(() => {
    if (!q.trim()) return rows;
    return rows.filter((r) => matchesSearch([r.name, r.slug, r.address, r.metro, String(r.id)].join(" "), q));
  }, [q, rows]);

  async function refresh() {
    const me = await fetch("/api/admin/me", { cache: "no-store" });
    if (!me.ok) {
      setOk(false);
      return;
    }
    setOk(true);
    const a = await fetch("/api/admin/apartments", { cache: "no-store" }).then((r) => r.json());
    const v = await fetch("/api/admin/videos", { cache: "no-store" }).then((r) => r.json());
    setRows(a.apartments || []);
    setVideos(v.videos || []);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !title.trim()) {
      setNote("Нужны файл и название ролика.");
      return;
    }
    const slugs = Object.entries(picked)
      .filter(([, on]) => on)
      .map(([slug]) => slug);
    if (scope === "selected" && !slugs.length) {
      setNote("Отметьте квартиры или выберите «на все».");
      return;
    }
    setBusy("upload");
    setNote("");
    const form = new FormData();
    form.set("file", file);
    form.set("title", title.trim());
    form.set("scope", scope);
    form.set("slugs", slugs.join(","));
    form.set("skipIfHas", skip ? "1" : "0");
    const res = await fetch("/api/admin/videos", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    setBusy("");
    if (!res.ok) {
      setNote(data.error || "Не загрузилось");
      return;
    }
    setFile(null);
    setTitle("");
    setNote(
      scope === "all"
        ? "Ролик стоит на всех квартирах, где такой инструкции ещё не было."
        : `Ролик стоит на ${slugs.length} квартирах.`
    );
    refresh();
  }

  async function removeVideo(id: string) {
    if (!confirm("Убрать этот ролик из инструкций?")) return;
    setBusy(id);
    await fetch(`/api/admin/videos/${id}`, { method: "DELETE" });
    setBusy("");
    refresh();
  }

  async function openEdit(slug: string) {
    setEditSlug(slug);
    const apt = await fetch(`/api/admin/apartments/${slug}`).then((r) => r.json());
    setDraft(apt);
    setTab("flats");
  }

  async function saveDraft(e: React.FormEvent) {
    e.preventDefault();
    if (!editSlug || !draft) return;
    setBusy("save");
    const res = await fetch(`/api/admin/apartments/${editSlug}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
    setBusy("");
    if (!res.ok) {
      setNote("Не сохранилось");
      return;
    }
    setNote("Карточка обновлена — гость увидит сразу.");
    refresh();
  }

  async function loginSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy("login");
    setNote("");
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login, password }),
    });
    setBusy("");
    if (!res.ok) {
      setNote("Неверный логин или пароль.");
      return;
    }
    setPassword("");
    await refresh();
  }

  async function logout() {
    await fetch("/api/admin/login", { method: "DELETE" });
    setOk(false);
  }

  if (ok === null) {
    return <p className="p-10 text-sm text-[#1a1612]/50">Проверяю доступ…</p>;
  }

  if (!ok) {
    return (
      <div className="mx-auto max-w-[520px] px-6 py-20">
        <p className="text-[11px] uppercase tracking-[0.28em] text-[#9a7b4f]">Home24 · админка</p>
        <h1 className="font-display mt-4 text-[42px] font-semibold leading-none">Вход</h1>
        <p className="mt-4 text-[15px] leading-relaxed text-[#1a1612]/60">
          Логин и пароль — или команда <b>/admin</b> в боте с вашего Telegram.
        </p>
        <form onSubmit={loginSubmit} className="mt-8 space-y-5">
          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.18em] text-[#9a7b4f]">Логин</span>
            <input
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              autoComplete="username"
              className="mt-2 w-full border-b border-[#1a1612]/20 bg-transparent py-2 text-lg outline-none"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.18em] text-[#9a7b4f]">Пароль</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="mt-2 w-full border-b border-[#1a1612]/20 bg-transparent py-2 text-lg outline-none"
            />
          </label>
          {note ? <p className="text-sm text-[#9a7b4f]">{note}</p> : null}
          <button type="submit" className="bg-[#1a1612] px-5 py-3 text-[11px] uppercase tracking-[0.18em] text-[#efe8dc]">
            {busy === "login" ? "Вхожу…" : "Войти"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[860px] px-5 pb-24 pt-8 sm:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[#1a1612]/10 pb-8">
        <div>
          <p className="text-[11px] uppercase tracking-[0.28em] text-[#9a7b4f]">Home24 · только вы</p>
          <h1 className="font-display mt-3 text-[40px] font-semibold leading-none sm:text-[52px]">Админка</h1>
        </div>
        <button type="button" onClick={logout} className="text-[11px] uppercase tracking-[0.16em] text-[#1a1612]/40">
          Выйти
        </button>
      </header>

      <nav className="mt-6 flex gap-2 text-[11px] uppercase tracking-[0.16em]">
        {(
          [
            ["video", "Залить видео"],
            ["flats", "Править квартиры"],
            ["library", "Библиотека"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`border px-3 py-2 ${tab === id ? "border-[#1a1612] bg-[#1a1612] text-[#efe8dc]" : "border-[#1a1612]/20"}`}
          >
            {label}
          </button>
        ))}
      </nav>

      {note ? <p className="mt-5 border border-[#9a7b4f]/40 bg-[#faf6ef] px-4 py-3 text-sm">{note}</p> : null}

      {tab === "video" ? (
        <form onSubmit={upload} className="mt-8 space-y-6">
          <p className="text-[15px] leading-relaxed text-[#1a1612]/60">
            Telegram и этот чат режут ролики тяжелее ~20 МБ. Сюда можно залить до 500 МБ, по одному файлу. Для Эвереста
            нажмите кнопку ниже — ролик попадёт только на эту квартиру.
          </p>
          <button
            type="button"
            onClick={() => {
              setScope("selected");
              setPicked({ everest: true });
              setSkip(false);
              setQ("эверест");
            }}
            className="border border-[#1a1612] px-3 py-2 text-[11px] uppercase tracking-[0.14em]"
          >
            Только «Эверест»
          </button>
          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.18em] text-[#9a7b4f]">Название для гостя</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Как пользоваться кофемашиной"
              className="mt-2 w-full border-b border-[#1a1612]/20 bg-transparent py-2 text-lg outline-none"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.18em] text-[#9a7b4f]">Файл</span>
            <input
              type="file"
              accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v"
              className="mt-2 block w-full text-sm"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {file ? (
              <p className="mt-1 text-xs text-[#1a1612]/40">
                {file.name} · {(file.size / (1024 * 1024)).toFixed(0)} МБ
                {file.size > 500 * 1024 * 1024
                  ? " — слишком тяжёлый для сайта. Закиньте в папку «эверест» на Яндекс.Диске."
                  : ""}
              </p>
            ) : null}
          </label>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => setScope("all")}
              className={`border px-3 py-2 text-[11px] uppercase tracking-[0.14em] ${scope === "all" ? "border-[#1a1612] bg-[#1a1612] text-[#efe8dc]" : "border-[#1a1612]/20"}`}
            >
              На все квартиры
            </button>
            <button
              type="button"
              onClick={() => setScope("selected")}
              className={`border px-3 py-2 text-[11px] uppercase tracking-[0.14em] ${scope === "selected" ? "border-[#1a1612] bg-[#1a1612] text-[#efe8dc]" : "border-[#1a1612]/20"}`}
            >
              Выборочно
            </button>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={skip} onChange={(e) => setSkip(e.target.checked)} />
            Не дублировать, если у квартиры уже есть такой ролик
          </label>
          {scope === "selected" ? (
            <div>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Поиск слогана…"
                className="mb-3 w-full border-b border-[#1a1612]/20 bg-transparent py-2 outline-none"
              />
              <div className="max-h-[320px] overflow-auto border border-[#1a1612]/10">
                {filtered.map((r) => (
                  <label key={r.slug} className="flex items-center gap-3 border-b border-[#1a1612]/10 px-3 py-2 text-sm">
                    <input
                      type="checkbox"
                      checked={Boolean(picked[r.slug])}
                      onChange={(e) => setPicked((p) => ({ ...p, [r.slug]: e.target.checked }))}
                    />
                    <span className="w-8 tabular-nums text-[#9a7b4f]">{String(r.id).padStart(2, "0")}</span>
                    <span className="font-display text-lg">{r.name}</span>
                  </label>
                ))}
              </div>
            </div>
          ) : null}
          <button
            type="submit"
            disabled={Boolean(busy)}
            className="bg-[#1a1612] px-5 py-3 text-[11px] uppercase tracking-[0.18em] text-[#efe8dc]"
          >
            {busy === "upload" ? "Загружаю…" : "Залить и расставить"}
          </button>
        </form>
      ) : null}

      {tab === "flats" ? (
        <div className="mt-8 grid gap-8 lg:grid-cols-2">
          <div>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Найти квартиру…"
              className="mb-3 w-full border-b border-[#1a1612]/20 bg-transparent py-2 outline-none"
            />
            <ul className="max-h-[70vh] overflow-auto">
              {filtered.map((r) => (
                <li key={r.slug}>
                  <button
                    type="button"
                    onClick={() => openEdit(r.slug)}
                    className={`flex w-full items-baseline gap-3 border-b border-[#1a1612]/10 py-3 text-left ${editSlug === r.slug ? "text-[#9a7b4f]" : ""}`}
                  >
                    <span className="w-8 text-[11px] text-[#9a7b4f]">{String(r.id).padStart(2, "0")}</span>
                    <span>
                      <span className="font-display block text-[22px] leading-none">{r.name}</span>
                      <span className="text-[11px] text-[#1a1612]/40">{r.videos} видео</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          {draft ? (
            <form onSubmit={saveDraft} className="space-y-3">
              {(
                [
                  ["name", "Слоган"],
                  ["address", "Адрес"],
                  ["metro", "Метро"],
                  ["coords", "Координаты"],
                  ["wifi", "Wi‑Fi"],
                  ["how", "Как добраться"],
                  ["checkin", "Заселение"],
                  ["checkout", "Выезд"],
                  ["parking", "Парковка"],
                  ["rules", "Правила"],
                  ["district", "Район"],
                  ["contacts", "Контакты"],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="block">
                  <span className="text-[11px] uppercase tracking-[0.16em] text-[#9a7b4f]">{label}</span>
                  {["wifi", "how", "checkin", "checkout", "parking", "rules", "district", "contacts"].includes(key) ? (
                    <textarea
                      value={String(draft[key] || "")}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                      rows={key === "name" ? 2 : 5}
                      className="mt-1 w-full border border-[#1a1612]/10 bg-[#faf6ef] p-2 text-sm outline-none"
                    />
                  ) : (
                    <input
                      value={String(draft[key] || "")}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                      className="mt-1 w-full border-b border-[#1a1612]/20 bg-transparent py-1 outline-none"
                    />
                  )}
                </label>
              ))}
              <button
                type="submit"
                className="bg-[#1a1612] px-5 py-3 text-[11px] uppercase tracking-[0.18em] text-[#efe8dc]"
              >
                {busy === "save" ? "Сохраняю…" : "Сохранить карточку"}
              </button>
            </form>
          ) : (
            <p className="text-sm text-[#1a1612]/40">Выберите квартиру слева.</p>
          )}
        </div>
      ) : null}

      {tab === "library" ? (
        <ul className="mt-8 space-y-4">
          {videos.length === 0 ? <p className="text-sm text-[#1a1612]/40">Пока пусто — залейте первый ролик.</p> : null}
          {videos.map((v) => (
            <li key={v.id} className="border border-[#1a1612]/10 bg-[#faf6ef] p-4">
              <p className="font-display text-2xl leading-none">{v.title}</p>
              <p className="mt-2 text-[12px] text-[#1a1612]/45">
                {v.slugs === "all" ? "Все квартиры" : `${v.slugs.length} квартир`}
                {v.skipIfHas ? " · без дублей" : ""}
              </p>
              <video
                controls
                playsInline
                preload="metadata"
                className="mt-3 aspect-video w-full bg-black"
                src={`/api/media?path=${encodeURIComponent(`/shared/${v.filename}`)}&disk=local`}
              />
              <button
                type="button"
                onClick={() => removeVideo(v.id)}
                className="mt-3 text-[11px] uppercase tracking-[0.16em] text-[#9a7b4f]"
              >
                {busy === v.id ? "Убираю…" : "Удалить"}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
