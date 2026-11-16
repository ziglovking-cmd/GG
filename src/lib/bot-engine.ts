import { randomUUID } from "crypto";
import {
  clinic,
  findService,
  listServicesBrief,
  pickSlotsForRequest,
  slotLabel,
} from "./clinic";
import { dialogSnippet, saveLead, saveSession } from "./store";
import { notifyAdminTelegram } from "./telegram";
import type {
  BotReply,
  Intent,
  Lead,
  Session,
  Slot,
  Urgency,
} from "./types";

const PHONE_RE = /(?:\+?7|8)?[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}/;
const NAME_RE =
  /(?:меня зовут|зовут|имя[:\s]+)([А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+)?)/i;

function detectIntent(text: string, session: Session): Intent {
  const t = text.toLowerCase().trim();

  if (clinic.aggressionTriggers.some((w) => t.includes(w))) return "aggression";
  if (clinic.escalationTriggers.some((w) => t.includes(w))) return "complaint";

  if (PHONE_RE.test(t.replace(/\s/g, "")) || /^\+?\d[\d\s()-]{8,}$/.test(t))
    return "phone";
  if (NAME_RE.test(t) || (session.awaiting === "name" && /^[А-ЯЁA-Zа-яёa-z]{2,}$/.test(t)))
    return "name";

  if (
    /^(да|ок|хорошо|записывайте|подтверждаю|согласен|давайте|верно)\b/i.test(t) ||
    t === "да"
  )
    return "confirm";
  if (/^(нет|не надо|отмена|передумал)/i.test(t)) return "decline";

  if (
    /болит|острая боль|разболел|ноет|опух|отек|не могу терпеть|скорая/.test(t)
  )
    return "pain";

  if (
    /сколько стоит|цена|прайс|стоимость|поч[её]м|сколько будет/.test(t) ||
    findService(t)
  ) {
    if (/запис|хочу|можно|завтра|сегодня|слот|время|вечером/.test(t))
      return "booking";
    if (findService(t) && /сколько|цена|стоимость|поч[её]м/.test(t))
      return "price";
    if (findService(t) && session.awaiting === "service") return "booking";
  }

  if (
    /запис|хочу на при[её]м|запишите|свободн|слот|завтра|сегодня вечером|можно на/.test(
      t
    )
  )
    return "booking";

  if (/где вы|адрес|как добраться|метро|часы|график|работаете|телефон/.test(t))
    return "faq";

  if (/привет|здравств|добрый|доброе/.test(t)) return "greeting";

  if (clinic.unknownTopics.some((w) => t.includes(w))) return "unknown";

  if (session.awaiting === "slot") return "booking";
  if (session.awaiting === "service") return "booking";
  if (session.awaiting === "confirm") return "confirm";

  return "other";
}

function extractPhone(text: string): string | undefined {
  const m = text.replace(/\s/g, " ").match(PHONE_RE);
  if (!m) return undefined;
  let digits = m[0].replace(/\D/g, "");
  if (digits.length === 11 && (digits.startsWith("8") || digits.startsWith("7"))) {
    digits = "7" + digits.slice(1);
  }
  if (digits.length === 10) digits = "7" + digits;
  if (digits.length < 11) return m[0].trim();
  return `+${digits[0]} (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9, 11)}`;
}

function extractName(text: string, session: Session): string | undefined {
  const m = text.match(NAME_RE);
  if (m?.[1]) return m[1].trim();
  if (session.awaiting === "name") {
    const cleaned = text.replace(/[^\p{L}\s-]/gu, "").trim();
    if (
      cleaned.split(/\s+/).length <= 3 &&
      cleaned.length >= 2 &&
      /\p{L}/u.test(cleaned) &&
      !/^-+$/.test(cleaned)
    ) {
      return cleaned;
    }
  }
  return undefined;
}

function pickSlotFromText(text: string, offered: Slot[]): Slot | undefined {
  const t = text.toLowerCase();
  if (!offered.length) return undefined;

  if (/перв|1\b|один/.test(t)) return offered[0];
  if (/втор|2\b|два/.test(t) && offered[1]) return offered[1];
  if (/трет|3\b/i.test(t) && offered[2]) return offered[2];

  for (const s of offered) {
    if (t.includes(s.time) || t.includes(s.time.replace(":", "."))) return s;
    if (s.day === "tomorrow" && t.includes("завтра")) {
      if (offered.filter((x) => x.day === "tomorrow").length === 1) return s;
    }
    if (s.day === "today" && t.includes("сегодня")) {
      if (offered.filter((x) => x.day === "today").length === 1) return s;
    }
  }

  // "завтра в 19:00" style against offered
  const timeMatch = t.match(/\b([01]?\d|2[0-3])[:.](\d{2})\b/);
  if (timeMatch) {
    const wanted = `${timeMatch[1].padStart(2, "0")}:${timeMatch[2]}`;
    const hit = offered.find((s) => s.time === wanted);
    if (hit) return hit;
  }

  return undefined;
}

function formatOffered(slots: Slot[]): string {
  return slots
    .map((s, i) => `${i + 1}) ${slotLabel(s)}`)
    .join("\n");
}

async function createLeadFromSession(
  session: Session,
  status: Lead["status"],
  summary: string
): Promise<Lead> {
  const lead: Lead = {
    id: randomUUID(),
    sessionId: session.id,
    createdAt: new Date().toISOString(),
    status,
    name: session.draft.name || "Не указано",
    phone: session.draft.phone || "Не указан",
    service: session.draft.serviceTitle || "Уточняется",
    slot: session.draft.slotLabel || "Уточняется",
    urgency: session.urgency,
    summary,
    dialogSnippet: dialogSnippet(session),
    telegramSent: false,
  };
  await saveLead(lead);
  session.leadId = lead.id;
  session.status = status === "escalated" ? "escalated" : "created";
  await saveSession(session);
  await notifyAdminTelegram(lead);
  return lead;
}

async function escalate(
  session: Session,
  reason: string,
  askContact = true
): Promise<BotReply> {
  session.draft.notes = reason;
  session.status = "escalated";
  session.awaiting =
    askContact && !session.draft.phone
      ? "phone"
      : askContact && !session.draft.name
        ? "name"
        : "none";

  if (!session.draft.phone && askContact) {
    const text = `${reason}\n\nПередаю диалог живому администратору. Напишите телефон для связи — перезвоним за 5–10 минут в рабочие часы (${clinic.hours}).`;
    return { text, session, actions: ["escalated"] };
  }

  if (!session.draft.name && askContact) {
    const text = `${reason}\n\nАдминистратор подключается. Как к вам обращаться?`;
    return { text, session, actions: ["escalated"] };
  }

  const lead = await createLeadFromSession(session, "escalated", reason);
  const text = `${reason}\n\nАдминистратор уже получил карточку обращения и свяжется с вами${session.draft.phone ? ` по ${session.draft.phone}` : ""}.`;
  return { text, session, lead, actions: ["escalated"] };
}

function setService(session: Session, serviceId: string, title: string) {
  session.draft.serviceId = serviceId;
  session.draft.serviceTitle = title;
}

function offerBooking(
  session: Session,
  userText: string,
  intro: string
): BotReply {
  const slots = pickSlotsForRequest(userText, 2);
  session.offeredSlots = slots;
  session.awaiting = "slot";
  session.status = "collecting";

  // If user already named a precise time that matches, preselect path still asks confirm via slot choice
  const text = `${intro}\n\nСвободные окна:\n${formatOffered(slots)}\n\nКакой слот удобнее — 1 или 2? Или напишите время.`;
  return { text, session, actions: ["offered_slots"] };
}

export async function handleUserMessage(
  session: Session,
  userText: string
): Promise<BotReply> {
  const intent = detectIntent(userText, session);
  session.lastIntent = intent;

  // Contact collection — also when escalated and awaiting phone/name
  const phone = extractPhone(userText);
  const nameGuess = extractName(userText, {
    ...session,
    awaiting: session.awaiting === "phone" ? "name" : session.awaiting,
  });

  if (session.status === "escalated" && (session.awaiting === "phone" || session.awaiting === "name")) {
    if (phone) session.draft.phone = phone;
    if (nameGuess) session.draft.name = nameGuess;

    if (!session.draft.phone) {
      session.awaiting = "phone";
      return {
        text: nameGuess
          ? `${nameGuess}, принял. Остался телефон для связи.`
          : "Нужен номер телефона (например +7 999 123-45-67), чтобы администратор до вас дозвониться.",
        session,
        actions: ["escalated"],
      };
    }
    if (!session.draft.name) {
      session.awaiting = "name";
      return {
        text: `Принял ${session.draft.phone}. Как к вам обращаться? Сразу передам администратору.`,
        session,
        actions: ["escalated"],
      };
    }

    const lead = await createLeadFromSession(
      session,
      "escalated",
      session.draft.notes || "Эскалация администратору"
    );
    session.awaiting = "none";
    return {
      text: `Спасибо, ${session.draft.name}! Передал администратору. Перезвоним на ${session.draft.phone}.`,
      session,
      lead,
      actions: ["escalated"],
    };
  }

  if (intent === "phone" || (session.awaiting === "phone" && phone)) {
    if (phone) {
      session.draft.phone = phone;
      if (session.awaiting === "phone" && session.draft.slotId) {
        return finalizeBooking(session);
      }
      if (!session.draft.name) {
        session.awaiting = "name";
        return {
          text: `Принял телефон ${phone}. Как к вам обращаться?`,
          session,
        };
      }
      if (session.draft.slotId) return finalizeBooking(session);
    }
  }

  if (intent === "name" || session.awaiting === "name") {
    const name = extractName(userText, session);
    if (name) {
      session.draft.name = name;
      if (!session.draft.phone) {
        session.awaiting = "phone";
        return {
          text: `Приятно познакомиться, ${name}! Оставьте телефон — подтвердим запись.`,
          session,
        };
      }
      if (session.draft.slotId) return finalizeBooking(session);
      session.awaiting = "none";
    } else if (session.awaiting === "name") {
      return {
        text: session.draft.slotLabel
          ? `Слот ${session.draft.slotLabel} держу. Напишите, пожалуйста, как вас зовут.`
          : "Напишите, пожалуйста, имя — как к вам обращаться.",
        session,
      };
    }
  }

  if (session.awaiting === "phone" && !phone) {
    return {
      text: "Оставьте номер телефона в формате +7 999 123-45-67 — подтвердим запись.",
      session,
    };
  }

  if (intent === "aggression") {
    session.urgency = "complaint";
    return escalate(
      session,
      "Понимаю, что ситуация неприятная. Сразу подключаю живого администратора — он разберётся лично.",
      true
    );
  }

  if (intent === "complaint") {
    session.urgency = "complaint";
    return escalate(
      session,
      "Принял. По жалобе лучше поговорить с администратором лично — передаю обращение.",
      true
    );
  }

  if (intent === "unknown") {
    return escalate(
      session,
      "По этому вопросу точных данных в базе нет — не хочу гадать. Уточню у администратора.",
      true
    );
  }

  if (intent === "greeting") {
    return {
      text: `Здравствуйте! Я АйАдмин клиники «${clinic.name}». Могу подсказать цены, адрес и записать на приём. Что вас интересует?`,
      session,
    };
  }

  if (intent === "faq") {
    const t = userText.toLowerCase();
    if (/адрес|где|метро|добраться/.test(t)) {
      return {
        text: `Мы по адресу: ${clinic.address}. До метро — пара минут. Записать вас на удобное время?`,
        session,
      };
    }
    if (/час|график|работа/.test(t)) {
      return {
        text: `Работаем ${clinic.hours}, ${clinic.hoursNote}. Куда удобнее записаться — сегодня или завтра?`,
        session,
      };
    }
    if (/телефон|номер/.test(t)) {
      return {
        text: `Телефон клиники: ${clinic.phone}. Могу сразу записать вас здесь в чате — это быстрее.`,
        session,
      };
    }
  }

  if (intent === "pain") {
    session.urgency = "urgent";
    session.draft.urgency = "urgent";
    session.draft.notes = "Острая боль / срочность";
    if (!session.draft.serviceId) {
      setService(session, "consult", "Срочный осмотр / консультация");
    }
    return offerBooking(
      session,
      userText + " сегодня срочно",
      "Понимаю, неприятно. Диагноз по чату не ставлю — это делает врач на осмотре. Давайте подберём ближайший слот, чтобы вас быстро посмотрели."
    );
  }

  if (intent === "price") {
    const service = findService(userText);
    if (service) {
      setService(session, service.id, service.title);
      return {
        text: `${service.title} — ${service.priceNote}. Точную сумму скажет врач после осмотра.\n\nЗаписать вас? Могу предложить окна на сегодня/завтра.`,
        session,
      };
    }
    return {
      text: `Вот актуальный прайс «от»:\n${listServicesBrief()}\n\nЧто интересует — подберу слот.`,
      session,
    };
  }

  // Slot selection while awaiting
  if (session.awaiting === "slot" || session.awaiting === "confirm") {
    if (intent === "decline") {
      session.awaiting = "none";
      session.offeredSlots = [];
      return {
        text: "Хорошо, слот не бронирую. Напишите другое время или услугу — подберу варианты.",
        session,
      };
    }

    const chosen =
      pickSlotFromText(userText, session.offeredSlots) ||
      (intent === "confirm" && session.offeredSlots[0]
        ? session.offeredSlots[0]
        : undefined);

    if (chosen) {
      session.draft.slotId = chosen.id;
      session.draft.slotLabel = slotLabel(chosen);
      if (!session.draft.name) {
        session.awaiting = "name";
        return {
          text: `Отлично, держу ${slotLabel(chosen)}. Как вас зовут?`,
          session,
        };
      }
      if (!session.draft.phone) {
        session.awaiting = "phone";
        return {
          text: `Слот ${slotLabel(chosen)} почти ваш. Оставьте телефон для подтверждения.`,
          session,
        };
      }
      return finalizeBooking(session);
    }

    if (session.awaiting === "slot") {
      // maybe new time preference
      const slots = pickSlotsForRequest(userText, 2);
      session.offeredSlots = slots;
      return {
        text: `Смотрю другие окна:\n${formatOffered(slots)}\n\nВыберите 1 или 2.`,
        session,
        actions: ["offered_slots"],
      };
    }
  }

  if (intent === "booking" || session.awaiting === "service") {
    const service = findService(userText);
    if (service) setService(session, service.id, service.title);

    if (/завтра|сегодня|вечер|утром|слот|запис|можно на/.test(userText.toLowerCase())) {
      session.bookingHint = [session.bookingHint, userText].filter(Boolean).join(" ");
    }

    // Combined: price + booking in one message
    const priceHint = service
      ? `${service.title} — ${service.priceNote}. `
      : session.draft.serviceTitle
        ? `${session.draft.serviceTitle}. `
        : "";

    if (!session.draft.serviceId && !service) {
      session.awaiting = "service";
      session.bookingHint = session.bookingHint || userText;
      return {
        text: `Конечно, запишем. На какую услугу?\n${listServicesBrief()}`,
        session,
      };
    }

    const slotQuery = [session.bookingHint, userText].filter(Boolean).join(" ");
    const hasExactTime = /\b([01]?\d|2[0-3])[:.](\d{2})\b/.test(slotQuery);

    // Auto-hold only when the patient named a concrete time (e.g. 19:00)
    if (hasExactTime) {
      const candidateSlots = pickSlotsForRequest(slotQuery, 3);
      const exact = pickSlotFromText(slotQuery, candidateSlots);
      if (exact) {
        session.draft.slotId = exact.id;
        session.draft.slotLabel = slotLabel(exact);
        session.offeredSlots = [exact, ...candidateSlots.filter((s) => s.id !== exact.id)].slice(0, 2);

        if (!session.draft.name) {
          session.awaiting = "name";
          return {
            text: `${priceHint}На ${slotLabel(exact)} есть место. Как вас зовут?`,
            session,
            actions: ["offered_slots"],
          };
        }
        if (!session.draft.phone) {
          session.awaiting = "phone";
          return {
            text: `${priceHint}Слот ${slotLabel(exact)} свободен. Оставьте телефон — подтвержу запись.`,
            session,
            actions: ["offered_slots"],
          };
        }
        return finalizeBooking(session);
      }
    }

    return offerBooking(
      session,
      slotQuery,
      `${priceHint}Могу предложить удобные окна.`
    );
  }

  if (intent === "confirm" && session.draft.slotId) {
    if (!session.draft.name) {
      session.awaiting = "name";
      return { text: "Подтверждаю. Как вас зовут?", session };
    }
    if (!session.draft.phone) {
      session.awaiting = "phone";
      return { text: "Остался только телефон для подтверждения.", session };
    }
    return finalizeBooking(session);
  }

  // Fallback: helpful nudge
  if (!session.draft.serviceId) {
    return {
      text: `Могу подсказать цены или сразу записать. Например: «сколько стоит чистка» или «запишите завтра вечером».\n\nПрайс:\n${listServicesBrief()}`,
      session,
    };
  }

  return offerBooking(
    session,
    userText,
    "Давайте подберём время."
  );
}

async function finalizeBooking(session: Session): Promise<BotReply> {
  session.awaiting = "none";
  const urgency: Urgency = session.urgency;
  const summary = `Запись: ${session.draft.serviceTitle || "услуга"} на ${session.draft.slotLabel || "время"}`;
  const lead = await createLeadFromSession(session, "created", summary);

  const text = [
    `Готово — заявка создана ✅`,
    ``,
    `Имя: ${session.draft.name}`,
    `Телефон: ${session.draft.phone}`,
    `Услуга: ${session.draft.serviceTitle}`,
    `Время: ${session.draft.slotLabel}`,
    urgency === "urgent" ? `Срочность: срочный приём` : null,
    ``,
    `Администратор получил карточку заявки и подтвердит запись. Если планы изменятся — напишите сюда.`,
  ]
    .filter(Boolean)
    .join("\n");

  return { text, session, lead, actions: ["booked"] };
}
