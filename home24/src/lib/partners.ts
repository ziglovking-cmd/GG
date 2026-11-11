import type { Apartment } from "@/lib/catalog";

/** Metro / address marker for the Prokshino cluster only. */
export function isProkshino(apt: Pick<Apartment, "metro" | "address" | "area">): boolean {
  const blob = `${apt.metro} ${apt.address} ${apt.area}`.toLowerCase();
  return blob.includes("прокшин");
}

export const NINJA_DOM24 = {
  partner: "Ninja Food",
  title: "Пицца «Дом24»",
  subtitle: "Только для гостей Home24 Apartments в Прокшино",
  promo: "HOME24",
  image: "/partners/ninja-dom24.jpg",
  orderUrl: "https://ninjafood.su",
  phone: "8 (800) 555-03-23",
  phoneHref: "tel:+78005550323",
  terms: [
    "Минимальная сумма заказа от 1199 ₽ (в минимальную сумму не входят ланчи, наборы и блюда недели).",
    "Скидка распространяется на доставку и самовывоз.",
    "Скидка не суммируется с другими акциями компании.",
  ],
};

/** Intimate kit for couples — Prokshino apartments only, 18+. Ordered via manager. */
export const FOR_TWO_KIT = {
  id: "for-two" as const,
  partner: "Home24",
  title: "Для двоих",
  badge: "18+",
  subtitle: "Доп. услуга: напишите менеджеру — оплата и получение набора через него",
  body:
    "Мы позаботились о том, чтобы ваш вечер прошел гладко и без лишней суеты. В этот набор входит всё самое необходимое для безопасного удовольствия: презервативы, лубрикант и кубики для поз — чтобы разнообразить досуг и добавить немного игры. Всё новое и качественное. Отдыхайте, расслабляйтесь и наслаждайтесь друг другом — детали мы уже продумали за вас.",
  contents: ["Презервативы", "Лубрикант", "Кубики для поз"],
  how: [
    "Напишите персональному менеджеру, что нужен набор «Для двоих».",
    "Это доп. услуга — оплата через менеджера.",
    "После оплаты менеджер передаст набор.",
  ],
  cta: "Написать менеджеру",
  ageGate: "Подтвердить и открыть",
  ageHint: "Введите дату рождения — раздел откроется только с 18 лет",
};
