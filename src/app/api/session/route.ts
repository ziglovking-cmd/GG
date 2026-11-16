import { NextResponse } from "next/server";
import { createSession, saveSession } from "@/lib/store";
import { clinic } from "@/lib/clinic";

export const runtime = "nodejs";

export async function POST() {
  const session = createSession();
  const welcome = `Здравствуйте! Я АйАдмин клиники «${clinic.name}». Подскажу цены, адрес и запишу на приём за пару сообщений. Что вас беспокоит?`;
  session.messages.push({
    id: crypto.randomUUID(),
    role: "assistant",
    text: welcome,
    at: new Date().toISOString(),
  });
  await saveSession(session);
  return NextResponse.json({
    sessionId: session.id,
    welcome,
    clinic: {
      name: clinic.name,
      brand: clinic.brand,
      address: clinic.address,
      hours: clinic.hours,
    },
  });
}
