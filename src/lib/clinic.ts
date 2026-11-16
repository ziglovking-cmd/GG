import clinicData from "../../data/clinic.json";
import type { Service, Slot } from "./types";

export const clinic = clinicData;

export function formatRub(n: number): string {
  return new Intl.NumberFormat("ru-RU").format(n) + " ₽";
}

/** Rough RU stem so «чистку/чистки» match «чистка». */
function fuzzyIncludes(haystack: string, needle: string): boolean {
  const h = haystack.toLowerCase();
  const n = needle.toLowerCase();
  if (h.includes(n)) return true;
  const stem = n.length > 4 ? n.slice(0, -1) : n;
  return stem.length >= 4 && h.includes(stem);
}

export function findService(text: string): Service | undefined {
  const lower = text.toLowerCase();
  return (clinic.services as Service[]).find((s) =>
    s.aliases.some((a) => fuzzyIncludes(lower, a))
  );
}

export function listServicesBrief(): string {
  return (clinic.services as Service[])
    .map((s) => `• ${s.title} — ${s.priceNote}`)
    .join("\n");
}

function dayLabel(day: "today" | "tomorrow"): string {
  const d = new Date();
  if (day === "tomorrow") d.setDate(d.getDate() + 1);
  return d.toLocaleDateString("ru-RU", {
    weekday: "short",
    day: "numeric",
    month: "long",
  });
}

/** Demo slots regenerated relative to "now" so demos always feel current. */
export function getAvailableSlots(preferEvening = false): Slot[] {
  const todayLabel = dayLabel("today");
  const tomorrowLabel = dayLabel("tomorrow");

  const base: Slot[] = [
    {
      id: "today-11",
      day: "today",
      dayLabel: todayLabel,
      time: "11:00",
      doctorRole: "терапевт",
      available: true,
    },
    {
      id: "today-16",
      day: "today",
      dayLabel: todayLabel,
      time: "16:30",
      doctorRole: "хирург",
      available: true,
    },
    {
      id: "today-19",
      day: "today",
      dayLabel: todayLabel,
      time: "19:00",
      doctorRole: "терапевт",
      available: true,
    },
    {
      id: "tomorrow-10",
      day: "tomorrow",
      dayLabel: tomorrowLabel,
      time: "10:00",
      doctorRole: "ортодонт",
      available: true,
    },
    {
      id: "tomorrow-15",
      day: "tomorrow",
      dayLabel: tomorrowLabel,
      time: "15:00",
      doctorRole: "терапевт",
      available: true,
    },
    {
      id: "tomorrow-19",
      day: "tomorrow",
      dayLabel: tomorrowLabel,
      time: "19:00",
      doctorRole: "терапевт",
      available: true,
    },
  ];

  if (preferEvening) {
    return base.filter((s) => Number(s.time.split(":")[0]) >= 17);
  }
  return base;
}

export function pickSlotsForRequest(
  text: string,
  count = 2
): Slot[] {
  const lower = text.toLowerCase();
  const wantTomorrow =
    lower.includes("завтра") || lower.includes("tomorrow");
  const wantToday =
    lower.includes("сегодня") || lower.includes("сейчас");
  const evening =
    lower.includes("вечер") ||
    lower.includes("после работ") ||
    /1[789]:|20:/.test(lower);

  let slots = getAvailableSlots(evening);

  if (wantTomorrow) slots = slots.filter((s) => s.day === "tomorrow");
  if (wantToday && !wantTomorrow) slots = slots.filter((s) => s.day === "today");

  // Prefer exact time if mentioned (require : or . to avoid matching "2" from "слот 2")
  const timeMatch = lower.match(/\b([01]?\d|2[0-3])[:.](\d{2})\b/);
  if (timeMatch) {
    const hh = timeMatch[1].padStart(2, "0");
    const mm = timeMatch[2];
    const wanted = `${hh}:${mm}`;
    const pool = getAvailableSlots(false).filter((s) => {
      if (wantTomorrow) return s.day === "tomorrow";
      if (wantToday) return s.day === "today";
      return true;
    });
    const exact = pool.filter((s) => s.time === wanted);
    if (exact.length) return exact.slice(0, count);
    const near = pool
      .map((s) => ({
        s,
        diff: Math.abs(
          Number(s.time.replace(":", "")) - Number(wanted.replace(":", ""))
        ),
      }))
      .sort((a, b) => a.diff - b.diff)
      .map((x) => x.s);
    if (near.length) return near.slice(0, count);
  }

  // If evening filter left < count, top up with same-day later slots
  if (slots.length < count) {
    const extra = getAvailableSlots(false).filter((s) => {
      if (wantTomorrow) return s.day === "tomorrow";
      if (wantToday && !wantTomorrow) return s.day === "today";
      return true;
    });
    for (const s of extra) {
      if (!slots.find((x) => x.id === s.id)) slots.push(s);
      if (slots.length >= count) break;
    }
  }

  if (!slots.length) slots = getAvailableSlots(false);
  // Keep preference order from filters (evening-first), don't re-sort away from intent
  return slots.slice(0, count);
}

export function slotLabel(slot: Slot): string {
  return `${slot.dayLabel}, ${slot.time} (${slot.doctorRole})`;
}

export const SYSTEM_PROMPT = `Вы — АйАдмин, ИИ-администратор стоматологии «${clinic.name}».

Цель: отвечать 24/7 и доводить диалог до записи или передачи живому администратору.

Данные клиники:
- Адрес: ${clinic.address}
- Часы: ${clinic.hours} (${clinic.hoursNote})
- Телефон: ${clinic.phone}
- Прайс: ${(clinic.services as Service[]).map((s) => `${s.title} ${s.priceNote}`).join("; ")}
- Врачи: ${clinic.doctors.map((d) => `${d.role} ${d.name}`).join("; ")}

Жёсткие правила:
1) Не ставьте диагнозы и не назначайте лечение. При боли — срочность + ближайший слот / эскалация.
2) Не выдумывайте цены. Только из прайса («от X ₽»). Если цены нет — «уточню у администратора» и эскалация.
3) Коротко, по-человечески, на «вы». 1–2 вопроса за раз.
4) Всегда ведите к действию: запись или эскалация человеку.
5) Жалоба / агрессия → сразу человек.
6) Неизвестная тема → «уточню у администратора» + эскалация.

Стиль ответа: 2–5 коротких предложений, без канцелярита.`;
