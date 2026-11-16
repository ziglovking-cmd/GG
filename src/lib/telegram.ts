import type { Lead } from "./types";
import { clinic } from "./clinic";
import { updateLead } from "./store";

function urgencyLabel(u: Lead["urgency"]): string {
  if (u === "urgent") return "🔥 СРОЧНО";
  if (u === "complaint") return "⚠️ ЖАЛОБА";
  return "обычная";
}

export function formatLeadCard(lead: Lead): string {
  const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
  return [
    `🦷 <b>Новая заявка — ${clinic.brand}</b>`,
    `Клиника: ${clinic.name}`,
    ``,
    `<b>Имя:</b> ${lead.name}`,
    `<b>Телефон:</b> ${lead.phone}`,
    `<b>Услуга:</b> ${lead.service}`,
    `<b>Время:</b> ${lead.slot}`,
    `<b>Срочность:</b> ${urgencyLabel(lead.urgency)}`,
    `<b>Статус:</b> ${lead.status === "escalated" ? "эскалация админу" : "заявка создана"}`,
    ``,
    `<b>Кратко:</b> ${lead.summary}`,
    ``,
    `<b>Диалог:</b>`,
    `<pre>${escapeHtml(lead.dialogSnippet)}</pre>`,
    ``,
    `Админка: ${appUrl}/admin`,
  ].join("\n");
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export async function notifyAdminTelegram(lead: Lead): Promise<boolean> {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_ADMIN_CHAT_ID;

  if (!token || !chatId) {
    console.log("[telegram] skipped — set TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID");
    console.log("[telegram] card preview:\n", formatLeadCard(lead).replace(/<[^>]+>/g, ""));
    return false;
  }

  const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text: formatLeadCard(lead),
      parse_mode: "HTML",
      disable_web_page_preview: true,
    }),
  });

  const ok = res.ok;
  if (!ok) {
    const body = await res.text();
    console.error("[telegram] send failed", res.status, body);
  } else {
    await updateLead(lead.id, { telegramSent: true });
  }
  return ok;
}
