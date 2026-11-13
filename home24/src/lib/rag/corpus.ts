import { apartments, type Apartment } from "@/lib/catalog";
import { FOR_TWO_KIT, NINJA_DOM24, isProkshino } from "@/lib/partners";
import type { RagChunk } from "@/lib/rag/types";

function push(
  out: RagChunk[],
  apt: Apartment,
  section: string,
  title: string,
  text: string | undefined | null,
) {
  const body = (text || "").trim();
  if (!body) return;
  out.push({
    id: `${apt.slug}:${section}:${out.length}`,
    slug: apt.slug,
    name: apt.name,
    section,
    title,
    text: body,
  });
}

export function buildCorpus(filterSlug?: string | null): RagChunk[] {
  const out: RagChunk[] = [];
  const list = filterSlug ? apartments.filter((a) => a.slug === filterSlug) : apartments;

  for (const apt of list) {
    push(out, apt, "card", "Карточка квартиры", [
      `Квартира «${apt.name}»`,
      `Адрес: ${apt.address}`,
      apt.metro ? `Метро/ориентир: ${apt.metro}` : "",
      apt.area ? `Район: ${apt.area}` : "",
      apt.coords ? `Координаты: ${apt.coords}` : "",
      `Ссылка на инструкцию: https://89-111-184-212.sslip.io/g/${apt.slug}`,
    ].filter(Boolean).join("\n"));

    push(out, apt, "kak-dobratsya", "Как добраться", apt.how);
    push(out, apt, "parkovka", "Парковка", apt.parking || apt.parkingHint);
    push(out, apt, "zaselenie", "Заселение", apt.checkin);
    push(out, apt, "wifi", "Wi‑Fi", apt.wifi);
    push(out, apt, "pravila", "Правила проживания", apt.rules);
    push(out, apt, "vyselenie", "Выселение", apt.checkout);
    push(out, apt, "rayon", "Справочник района", apt.district);
    push(out, apt, "otzyv", "Отзыв", apt.review);
    push(out, apt, "kontakty", "Контакты", apt.contacts);

    apt.faq.forEach((f) => {
      push(out, apt, "faq", `FAQ: ${f.q}`, `Вопрос: ${f.q}\nОтвет: ${f.a}`);
    });

    if (apt.videos.length) {
      push(
        out,
        apt,
        "video",
        "Видео",
        `Доступные ролики:\n${apt.videos.map((v) => `• ${v.title}`).join("\n")}\nСмотреть во вкладке «Видео» инструкции.`,
      );
    }

    if (isProkshino(apt)) {
      push(
        out,
        apt,
        "partnery",
        "Партнёры: пицца Дом24",
        [
          `${NINJA_DOM24.partner}: ${NINJA_DOM24.title}`,
          NINJA_DOM24.subtitle,
          `Промокод: ${NINJA_DOM24.promo}`,
          ...NINJA_DOM24.terms,
          `Заказ: ${NINJA_DOM24.orderUrl}`,
          `Телефон: ${NINJA_DOM24.phone}`,
        ].join("\n"),
      );
      push(
        out,
        apt,
        "partnery",
        "Партнёры: набор Для двоих (18+)",
        [
          `${FOR_TWO_KIT.title} — ${FOR_TWO_KIT.badge}`,
          FOR_TWO_KIT.subtitle,
          FOR_TWO_KIT.body,
          `В наборе: ${FOR_TWO_KIT.contents.join(", ")}`,
          "Как получить:",
          ...FOR_TWO_KIT.how.map((s, i) => `${i + 1}. ${s}`),
          "Набор в квартире не искать — доп. услуга через менеджера.",
        ].join("\n"),
      );
    }
  }

  return out;
}

let cachedAll: RagChunk[] | null = null;

export function getCorpus(filterSlug?: string | null): RagChunk[] {
  if (filterSlug) return buildCorpus(filterSlug);
  if (!cachedAll) cachedAll = buildCorpus();
  return cachedAll;
}
