import { sql } from "@/lib/db";

export async function postToChannel(input: {
  kind: string;
  body: string;
  tournamentId?: number | null;
}): Promise<{ ok: boolean; messageId?: number; sample?: boolean }> {
  const token = process.env.TELEGRAM_BOT_TOKEN?.trim() ?? "";
  const channel = process.env.TELEGRAM_CHANNEL_ID?.trim() ?? "";

  let messageId: number | undefined;
  let sample = false;

  if (!token || !channel) {
    sample = true;
  } else {
    try {
      const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          chat_id: channel,
          text: input.body,
          disable_web_page_preview: false,
        }),
      });
      const data = (await res.json()) as {
        ok: boolean;
        result?: { message_id: number };
      };
      if (data.ok && data.result?.message_id) {
        messageId = data.result.message_id;
      }
    } catch {
      sample = true;
    }
  }

  await sql(
    `insert into channel_posts (kind, tournament_id, body, telegram_message_id)
     values ($1, $2, $3, $4)`,
    [input.kind, input.tournamentId ?? null, input.body, messageId ?? null],
  );

  return { ok: true, messageId, sample };
}

export function tournamentCreatedPost(t: {
  title: string;
  entry_fee_rub: number;
  prize_rub: number;
  max_players: number;
  siteUrl?: string;
}): string {
  return [
    `🎮 Новый турик: ${t.title}`,
    `Вход: ${t.entry_fee_rub}₽ · Приз: ${t.prize_rub}₽`,
    `Слотов: ${t.max_players}`,
    `Brawl Tag обязателен. Запись в боте и на сайте.`,
    t.siteUrl ? `Сайт: ${t.siteUrl}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

export function winnerPost(t: {
  title: string;
  winnerName: string;
  winnerTag: string;
  prize_rub: number;
}): string {
  return [
    `🏆 Победитель ${t.title}`,
    `${t.winnerName} (${t.winnerTag})`,
    `Приз: ${t.prize_rub}₽`,
  ].join("\n");
}

export function livePost(t: { title: string; stream_url?: string | null }): string {
  return [
    `🔴 LIVE: ${t.title}`,
    t.stream_url ? `Смотреть: ${t.stream_url}` : "Трансляция на сайте GG Cup",
  ].join("\n");
}

export function bracketPost(title: string, text: string): string {
  return `🧩 Сетка «${title}»\n\n${text}`;
}
