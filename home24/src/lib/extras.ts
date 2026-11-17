/** Extra services ordered via manager (WhatsApp / Telegram / phone). */

export type ExtraService = {
  id: string;
  section: string;
  eyebrow: string;
  name: string;
  blurb: string;
  /** Prefill label in manager message (defaults to name). */
  orderAs?: string;
  adult?: boolean;
};

export const EXTRAS_SECTIONS: { id: string; title: string }[] = [
  { id: "checkin", title: "Заезд и выезд" },
  { id: "comfort", title: "Уборка и комфорт" },
  { id: "work", title: "Для работы" },
  { id: "food", title: "Еда" },
  { id: "party", title: "Праздник и досуг" },
  { id: "kids", title: "С детьми и питомцами" },
];

export const EXTRA_SERVICES: ExtraService[] = [
  {
    id: "early-late",
    section: "checkin",
    eyebrow: "Заезд и выезд",
    name: "Ранний заезд / поздний выезд",
    blurb: "Заселиться раньше или задержаться после 12:00",
  },
  {
    id: "transfer",
    section: "checkin",
    eyebrow: "Дорога",
    name: "Трансфер",
    blurb: "Из аэропорта и вокзала или обратно",
  },
  {
    id: "parking",
    section: "checkin",
    eyebrow: "Авто",
    name: "Парковка",
    blurb: "Место для машины на время проживания",
  },
  {
    id: "cleaning",
    section: "comfort",
    eyebrow: "Уборка",
    name: "Доп. уборка / смена белья",
    blurb: "Приберём и поменяем бельё во время проживания",
  },
  {
    id: "extra-bed",
    section: "comfort",
    eyebrow: "Комфорт",
    name: "Доп. спальное место",
    blurb: "Подготовим к вашему приезду",
  },
  {
    id: "robes",
    section: "comfort",
    eyebrow: "Комфорт",
    name: "Халаты в аренду",
    blurb: "Мягкие халаты на время проживания",
  },
  {
    id: "kit-slippers",
    section: "comfort",
    eyebrow: "Комфорт",
    name: "Набор: тапочки, маска для сна, бритва",
    blurb: "Всё нужное в одном наборе",
  },
  {
    id: "pillows",
    section: "comfort",
    eyebrow: "Сон",
    name: "Ортопедические подушки в аренду",
    blurb: "Для крепкого сна",
  },
  {
    id: "umbrellas",
    section: "comfort",
    eyebrow: "Погода",
    name: "Зонты",
    blurb: "Возьмите зонт, если в Москве дождь",
  },
  {
    id: "business",
    section: "work",
    eyebrow: "Командировка",
    name: "Для командировочных",
    blurb: "Документы для отчёта, рабочее место",
  },
  {
    id: "docs",
    section: "work",
    eyebrow: "Документы",
    name: "Доставка документов",
    blurb: "Привезём закрывающие документы",
  },
  {
    id: "powerbank",
    section: "work",
    eyebrow: "Прокат",
    name: "Повербанк",
    blurb: "10 000 мА·ч — зарядка в дороге",
  },
  {
    id: "chargers",
    section: "work",
    eyebrow: "Прокат",
    name: "Зарядные устройства",
    blurb: "Если забыли свою зарядку",
  },
  {
    id: "extension",
    section: "work",
    eyebrow: "Прокат",
    name: "Удлинитель",
    blurb: "Чтобы хватило розеток",
  },
  {
    id: "groceries",
    section: "food",
    eyebrow: "Доставка",
    name: "Продукты и готовая еда к заезду",
    blurb: "Плюс снеки",
  },
  {
    id: "coffee",
    section: "food",
    eyebrow: "Утро",
    name: "Кофе зерновой",
    blurb: "Настоящий кофе к завтраку",
  },
  {
    id: "kitchen",
    section: "food",
    eyebrow: "Прокат",
    name: "Кухонная техника",
    blurb: "Аэрогриль, мультиварка, фритюрница",
  },
  {
    id: "romance",
    section: "party",
    eyebrow: "Вечер",
    name: "Романтическое оформление вечера",
    blurb: "Лепестки, свечи, шарики, сервировка",
  },
  {
    id: "decor",
    section: "party",
    eyebrow: "Праздник",
    name: "Праздничный декор",
    blurb: "День рождения, годовщина, сюрприз",
  },
  {
    id: "bouquet",
    section: "party",
    eyebrow: "Сюрприз",
    name: "Букет для близкого человека",
    blurb: "Цветы к вашему приезду",
  },
  {
    id: "games",
    section: "party",
    eyebrow: "Досуг",
    name: "Настольные игры",
    blurb: "Для вечера с друзьями или семьёй",
  },
  {
    id: "for-two",
    section: "party",
    eyebrow: "Для взрослых",
    name: "Для двоих",
    orderAs: "Набор «Для двоих» (18+)",
    blurb: "Деликатно, через менеджера",
    adult: true,
  },
  {
    id: "kids",
    section: "kids",
    eyebrow: "Дети",
    name: "Детские принадлежности",
    blurb: "Кроватка-манеж, ванночка, горшок, игрушки",
  },
  {
    id: "pets",
    section: "kids",
    eyebrow: "Питомцы",
    name: "Для животных",
    blurb: "Лежанка, лоток, когтеточка",
  },
];

export function extrasOrderMessage(aptName: string, service: ExtraService): string {
  const label = service.orderAs || service.name;
  return `Здравствуйте! Квартира «${aptName}». Хочу заказать: ${label}. Подскажите, пожалуйста, условия.`;
}

export function extrasCorpusText(): string {
  const lines = [
    "Дополнительные услуги заказываются через персонального менеджера.",
    "Стоимость и время уточняет менеджер. В квартире наборы не ищите.",
    "Связь: WhatsApp, Telegram или звонок.",
    "",
  ];
  for (const sec of EXTRAS_SECTIONS) {
    const items = EXTRA_SERVICES.filter((s) => s.section === sec.id);
    lines.push(`${sec.title}:`);
    for (const s of items) {
      lines.push(`• ${s.orderAs || s.name}${s.adult ? " (18+)" : ""} — ${s.blurb}`);
    }
    lines.push("");
  }
  lines.push("Не нашли нужное — позвоните или напишите менеджеру с 09:00 до 00:00.");
  return lines.join("\n");
}
