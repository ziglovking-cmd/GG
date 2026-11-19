"use client";

import { useState } from "react";

type Done = { original: string; title: string };

export default function EverestDropPage() {
  const [busy, setBusy] = useState(false);
  const [pct, setPct] = useState(0);
  const [current, setCurrent] = useState("");
  const [note, setNote] = useState("");
  const [done, setDone] = useState<Done[]>([]);

  function putFile(file: File) {
    return new Promise<Done>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/drop/everest?name=${encodeURIComponent(file.name)}`);
      xhr.timeout = 30 * 60 * 1000;
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) setPct(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        let data: { error?: string; title?: string } = {};
        try {
          data = JSON.parse(xhr.responseText || "{}");
        } catch {
          /* empty */
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve({ original: file.name, title: data.title || file.name });
          return;
        }
        reject(new Error(data.error || `Сервер ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error("Сеть оборвалась. Попробуй ещё раз, по одному файлу."));
      xhr.ontimeout = () => reject(new Error("Слишком долго. Залей по одному, не все сразу."));
      xhr.send(file);
    });
  }

  async function send(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(true);
    setNote("");
    const ok: Done[] = [];
    for (const file of list) {
      setCurrent(file.name);
      setPct(0);
      try {
        ok.push(await putFile(file));
      } catch (err) {
        setNote(err instanceof Error ? err.message : `Не ушёл файл ${file.name}`);
        setBusy(false);
        setCurrent("");
        if (ok.length) setDone((prev) => [...ok, ...prev]);
        return;
      }
    }
    setDone((prev) => [...ok, ...prev]);
    setNote(`Готово: ${ok.length} файл(ов) на карточке Эвереста.`);
    setBusy(false);
    setCurrent("");
    setPct(0);
  }

  return (
    <div className="mx-auto min-h-dvh max-w-[560px] px-5 py-12">
      <p className="text-[11px] uppercase tracking-[0.28em] text-[#9a7b4f]">Home24 · Эверест</p>
      <h1 className="font-display mt-4 text-[42px] font-semibold leading-none">Кидай ролики сюда</h1>
      <p className="mt-5 text-[16px] leading-relaxed text-[#1a1612]/65">
        Без логина. Лучше по одному файлу, не все сразу. Если имена как с iPhone (IMG_4720 и дальше) — сам подпишу.
      </p>
      <label className="mt-10 block cursor-pointer border border-dashed border-[#1a1612]/25 bg-[#faf6ef] px-5 py-12 text-center">
        <span className="font-display text-[26px] font-semibold">
          {busy ? "Загружаю…" : "Нажми и выбери файлы"}
        </span>
        <span className="mt-3 block text-[13px] text-[#1a1612]/45">mp4, mov — лучше по одному</span>
        <input
          type="file"
          accept="video/mp4,video/quicktime,video/webm,image/jpeg,image/png,.mp4,.mov,.m4v,.jpg,.jpeg,.png"
          multiple
          disabled={busy}
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) send(e.target.files);
            e.target.value = "";
          }}
        />
      </label>
      {busy ? (
        <p className="mt-5 text-sm text-[#1a1612]/70">
          {current} — {pct}%
        </p>
      ) : null}
      {note ? <p className="mt-5 text-sm text-[#9a7b4f]">{note}</p> : null}
      {done.length ? (
        <ul className="mt-8 space-y-2 text-sm">
          {done.map((d) => (
            <li key={d.original + d.title} className="border-b border-[#1a1612]/10 py-2">
              <span className="text-[#1a1612]/40">{d.original}</span>
              <span className="mt-0.5 block font-medium">{d.title}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-10 text-[13px] text-[#1a1612]/40">
        Гостевая карточка:{" "}
        <a href="/g/everest/video" className="underline">
          /g/everest/video
        </a>
      </p>
    </div>
  );
}
