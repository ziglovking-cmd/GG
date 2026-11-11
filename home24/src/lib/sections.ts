import type { Apartment, Video } from "@/lib/catalog";
import { isProkshino } from "@/lib/partners";
import { isCoffeeVideo } from "@/lib/video-kind";

export type SectionId =
  | "kak-dobratsya"
  | "parkovka"
  | "zaselenie"
  | "wifi"
  | "pravila"
  | "faq"
  | "video"
  | "rayon"
  | "vyselenie"
  | "otzyv"
  | "kontakty"
  | "partnery";

export type Section = {
  id: SectionId;
  title: string;
  kind: "text" | "faq";
};

export type FaqItem = {
  key: string;
  q: string;
  a: string;
  video?: Video;
};

export const SECTIONS: Section[] = [
  { id: "kak-dobratsya", title: "Как добраться?", kind: "text" },
  { id: "parkovka", title: "Парковка", kind: "text" },
  { id: "zaselenie", title: "Как заселиться самостоятельно?", kind: "text" },
  { id: "wifi", title: "Wi-Fi", kind: "text" },
  { id: "pravila", title: "Правила проживания", kind: "text" },
  { id: "video", title: "Видео пользования техникой и не только", kind: "text" },
  { id: "faq", title: "FAQ часто задаваемые вопросы", kind: "faq" },
  { id: "rayon", title: "Справочник района", kind: "text" },
  { id: "partnery", title: "Предложения от партнёров", kind: "text" },
  { id: "vyselenie", title: "Как выселиться самостоятельно?", kind: "text" },
  { id: "otzyv", title: "Оставить отзыв", kind: "text" },
  { id: "kontakty", title: "Контакты", kind: "text" },
];

const PARTNER_SECTION = SECTIONS.find((s) => s.id === "partnery")!;

export function sectionsFor(apt: Pick<Apartment, "metro" | "address" | "area">): Section[] {
  if (isProkshino(apt)) return SECTIONS;
  return SECTIONS.filter((s) => s.id !== "partnery");
}

export { isProkshino, PARTNER_SECTION };

export function guideTitle(apt: Apartment) {
  return `Квартира «${apt.name}» — инструкция по заселению и проживанию`;
}

export function mapsUrl(apt: Apartment) {
  if (apt.mapsOrgUrl) return apt.mapsOrgUrl;
  if (apt.coords) {
    const [lat, lon] = apt.coords.split(",").map((x) => x.trim());
    return `https://yandex.ru/maps/?pt=${lon},${lat}&z=17&l=map`;
  }
  return `https://yandex.ru/maps/?text=${encodeURIComponent(apt.address)}`;
}

export function reviewUrl(apt: Apartment) {
  if (!apt.mapsOrgUrl) return "";
  return `${apt.mapsOrgUrl.replace(/\/+$/, "")}/reviews/`;
}

export function navUrl(apt: Apartment) {
  if (apt.coords) {
    const [lat, lon] = apt.coords.split(",").map((x) => x.trim());
    return `https://yandex.ru/maps/?mode=routes&rtext=~${lat},${lon}&rtt=auto`;
  }
  return `https://yandex.ru/maps/?mode=routes&rtext=~${encodeURIComponent(apt.address)}&rtt=auto`;
}

export function faqItems(apt: Apartment): FaqItem[] {
  const seen = new Set<string>();
  const out: FaqItem[] = [];
  apt.faq.forEach((item, i) => {
    const q = item.q.trim();
    if (seen.has(q.toLowerCase())) return;
    seen.add(q.toLowerCase());
    out.push({
      key: `q${i + 1}`,
      q,
      a: item.a.replace(/https?:\/\/\S+/g, "").trim(),
    });
  });
  return out;
}

export function sectionBody(apt: Apartment, id: SectionId): string {
  switch (id) {
    case "kak-dobratsya":
      return apt.how;
    case "parkovka":
      return apt.parking;
    case "zaselenie":
      return apt.checkin;
    case "wifi":
      return apt.wifi;
    case "pravila":
      return apt.rules;
    case "video":
      return apt.videos.length
        ? "Обзор квартиры и ролики с Яндекс.Диска. Играют здесь, скачивать ничего не нужно."
        : "Для этой квартиры роликов пока нет — текстовая инструкция в остальных разделах.";
    case "rayon":
      return apt.district;
    case "vyselenie":
      return apt.checkout;
    case "otzyv":
      return apt.review;
    case "kontakty":
      return apt.contacts;
    default:
      return "";
  }
}

export function videosForSection(apt: Apartment, id: SectionId): Video[] {
  if (id !== "video") return [];
  const coffee = apt.videos.filter(isCoffeeVideo);
  const rest = apt.videos.filter((v) => !isCoffeeVideo(v));
  return [...rest, ...coffee];
}
