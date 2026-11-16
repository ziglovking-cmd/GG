import { promises as fs } from "fs";
import path from "path";
import { randomUUID } from "crypto";
import type { Lead, Message, Session } from "./types";

const RUNTIME_DIR = path.join(process.cwd(), "data", "runtime");
const SESSIONS_FILE = path.join(RUNTIME_DIR, "sessions.json");
const LEADS_FILE = path.join(RUNTIME_DIR, "leads.json");

async function ensureRuntime() {
  await fs.mkdir(RUNTIME_DIR, { recursive: true });
  for (const file of [SESSIONS_FILE, LEADS_FILE]) {
    try {
      await fs.access(file);
    } catch {
      await fs.writeFile(file, "[]", "utf8");
    }
  }
}

async function readJson<T>(file: string): Promise<T[]> {
  await ensureRuntime();
  const raw = await fs.readFile(file, "utf8");
  try {
    return JSON.parse(raw) as T[];
  } catch {
    return [];
  }
}

async function writeJson<T>(file: string, data: T[]) {
  await ensureRuntime();
  await fs.writeFile(file, JSON.stringify(data, null, 2), "utf8");
}

export function createSession(): Session {
  const now = new Date().toISOString();
  return {
    id: randomUUID(),
    createdAt: now,
    updatedAt: now,
    status: "chatting",
    urgency: "normal",
    draft: { urgency: "normal" },
    messages: [],
    offeredSlots: [],
    awaiting: "none",
  };
}

export async function getSession(id: string): Promise<Session | undefined> {
  const sessions = await readJson<Session>(SESSIONS_FILE);
  return sessions.find((s) => s.id === id);
}

export async function saveSession(session: Session): Promise<Session> {
  const sessions = await readJson<Session>(SESSIONS_FILE);
  session.updatedAt = new Date().toISOString();
  const idx = sessions.findIndex((s) => s.id === session.id);
  if (idx >= 0) sessions[idx] = session;
  else sessions.unshift(session);
  await writeJson(SESSIONS_FILE, sessions.slice(0, 200));
  return session;
}

export async function listSessions(): Promise<Session[]> {
  return readJson<Session>(SESSIONS_FILE);
}

export async function appendMessage(
  session: Session,
  role: Message["role"],
  text: string
): Promise<Session> {
  session.messages.push({
    id: randomUUID(),
    role,
    text,
    at: new Date().toISOString(),
  });
  return saveSession(session);
}

export async function saveLead(lead: Lead): Promise<Lead> {
  const leads = await readJson<Lead>(LEADS_FILE);
  leads.unshift(lead);
  await writeJson(LEADS_FILE, leads.slice(0, 200));
  return lead;
}

export async function listLeads(): Promise<Lead[]> {
  return readJson<Lead>(LEADS_FILE);
}

export async function updateLead(
  id: string,
  patch: Partial<Lead>
): Promise<Lead | undefined> {
  const leads = await readJson<Lead>(LEADS_FILE);
  const idx = leads.findIndex((l) => l.id === id);
  if (idx < 0) return undefined;
  leads[idx] = { ...leads[idx], ...patch };
  await writeJson(LEADS_FILE, leads);
  return leads[idx];
}

export function dialogSnippet(session: Session, max = 6): string {
  return session.messages
    .slice(-max)
    .map((m) => `${m.role === "user" ? "Пациент" : "АйАдмин"}: ${m.text}`)
    .join("\n");
}
