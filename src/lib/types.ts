export type Urgency = "normal" | "urgent" | "complaint";

export type LeadStatus =
  | "chatting"
  | "collecting"
  | "created"
  | "escalated"
  | "closed";

export type Intent =
  | "price"
  | "pain"
  | "booking"
  | "faq"
  | "complaint"
  | "aggression"
  | "unknown"
  | "confirm"
  | "decline"
  | "phone"
  | "name"
  | "greeting"
  | "other";

export interface Service {
  id: string;
  aliases: string[];
  title: string;
  priceFrom: number;
  priceTo?: number;
  priceNote: string;
  durationMin: number;
}

export interface Slot {
  id: string;
  day: "today" | "tomorrow";
  dayLabel: string;
  time: string;
  doctorRole: string;
  available: boolean;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  at: string;
}

export interface BookingDraft {
  serviceId?: string;
  serviceTitle?: string;
  slotId?: string;
  slotLabel?: string;
  name?: string;
  phone?: string;
  urgency: Urgency;
  notes?: string;
}

export interface Session {
  id: string;
  createdAt: string;
  updatedAt: string;
  status: LeadStatus;
  urgency: Urgency;
  draft: BookingDraft;
  messages: Message[];
  offeredSlots: Slot[];
  awaiting: "none" | "service" | "slot" | "name" | "phone" | "confirm";
  lastIntent?: Intent;
  leadId?: string;
  /** Keeps «завтра вечером» while we ask for service */
  bookingHint?: string;
}

export interface Lead {
  id: string;
  sessionId: string;
  createdAt: string;
  status: "created" | "escalated";
  name: string;
  phone: string;
  service: string;
  slot: string;
  urgency: Urgency;
  summary: string;
  dialogSnippet: string;
  telegramSent: boolean;
}

export interface BotReply {
  text: string;
  session: Session;
  lead?: Lead;
  actions?: Array<"booked" | "escalated" | "offered_slots">;
}
