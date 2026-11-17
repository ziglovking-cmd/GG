import type { SectionId } from "@/lib/sections";

/** Contacts from https://home24.msk.ru/contacts — phone kept as live manager line. */
export const PHONE_TEL = "+79777176097";
export const PHONE_LABEL = "+7 977 717-60-97";
export const TELEGRAM_USERNAME = "home24_msk";
export const SITE_URL = "https://home24.msk.ru";
export const MANAGER_LABEL = "Ваш персональный менеджер";
export const MANAGER_HOURS = "09:00–00:00";
export const MANAGER_HOURS_SITE = "с 9:00 до 00:00";

export const SECTION_CARD: Record<
  SectionId,
  { hint: string; emoji: string }
> = {
  "kak-dobratsya": { hint: "Адрес, карта и как дойти до двери", emoji: "🗺️" },
  parkovka: { hint: "Бесплатный двор или платная улица — смотрите карточку", emoji: "🚗" },
  zaselenie: { hint: "Домофон, ключница, первый шаг внутрь", emoji: "🔑" },
  wifi: { hint: "Сеть, пароль и что делать если молчит", emoji: "📶" },
  pravila: { hint: "Чтобы отдых прошёл спокойно", emoji: "✦" },
  video: { hint: "Обзор квартиры и техника — ролики на этой вкладке", emoji: "▶" },
  faq: { hint: "Коротко про депозит, питомцев, продление", emoji: "?" },
  rayon: { hint: "Магазины, метро, чем заняться рядом", emoji: "☕" },
  uslugi: { hint: "Заказ через менеджера — WhatsApp, Telegram или звонок", emoji: "✦" },
  partnery: { hint: "Пицца «Дом24» — только Прокшино", emoji: "🍕" },
  vyselenie: { hint: "Ключи, мусор, до скорой встречи", emoji: "🚪" },
  otzyv: { hint: "Два слова о нас после выезда", emoji: "♡" },
  kontakty: { hint: "Персональный менеджер, 09:00–00:00", emoji: "☎" },
};
