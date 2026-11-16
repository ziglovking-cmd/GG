import { Bot, InlineKeyboard, type Context } from "grammy";
import { isTelegramAdmin } from "@/lib/auth";
import {
  formatBracketText,
  parseBracket,
} from "@/lib/brackets";
import { friendQueueHelpText, listFriendQueue, markFriendAdded } from "@/lib/friends";
import { lobbyStatus, markReady, openLobby, settleLobbyIfNeeded } from "@/lib/lobby";
import {
  getPlayerByTelegram,
  upsertPlayer,
} from "@/lib/players";
import {
  createTournament,
  generateAndSaveBracket,
  getActiveTournament,
  getRegistrationForPlayer,
  getTournament,
  listRegistrations,
  markPaid,
  registerPlayer,
  setStream,
  setWinner,
} from "@/lib/tournaments";

let botSingleton: Bot | null = null;

export function getBot(): Bot | null {
  const token = process.env.TELEGRAM_BOT_TOKEN?.trim();
  if (!token) return null;
  if (botSingleton) return botSingleton;
  botSingleton = buildBot(token);
  return botSingleton;
}

function buildBot(token: string): Bot {
  const bot = new Bot(token);

  bot.command("start", async (ctx) => {
    const t = await getActiveTournament();
    const site = process.env.NEXT_PUBLIC_SITE_URL?.trim() || "";
    const kb = new InlineKeyboard()
      .text("Записаться", "join")
      .text("Я в комнате", "ready")
      .row()
      .text("Мой статус", "status")
      .text("Сетка", "bracket");
    await ctx.reply(
      [
        "GG Cup — турики Brawl Stars",
        "Вход 50₽ · Приз 150₽ · Brawl Tag обязателен",
        "",
        t
          ? `Сейчас: ${t.title} [${t.status}]`
          : "Активного турнира пока нет — следи за каналом.",
        "",
        "Перед стартом бот открывает лобби на 60 сек.",
        "Кто не нажал «Я в комнате» — ВЫБЫЛ, в сетке BOT.",
        site ? `Сайт: ${site}` : "",
      ]
        .filter(Boolean)
        .join("\n"),
      { reply_markup: kb },
    );
  });

  bot.command("help", async (ctx) => {
    await ctx.reply(
      [
        "Команды игрока:",
        "/join — запись (потом пришли Brawl Tag)",
        "/ready — я зашёл в комнату",
        "/status — статус оплаты/чек-ина",
        "/bracket — сетка",
        "/balance — подсказка по балансу на сайте",
        "",
        "Админ:",
        "/newcup Название",
        "/players",
        "/paid <registration_id>",
        "/room КОД — открыть лобби 60с",
        "/friends — очередь тегов в друзья",
        "/friendok <id>",
        "/stream URL",
        "/winner <registration_id>",
        "/settle — закрыть чек-ин вручную",
      ].join("\n"),
    );
  });

  bot.command("join", async (ctx) => joinFlow(ctx));
  bot.callbackQuery("join", async (ctx) => {
    await ctx.answerCallbackQuery();
    await joinFlow(ctx);
  });

  bot.command("ready", async (ctx) => readyFlow(ctx));
  bot.callbackQuery("ready", async (ctx) => {
    await ctx.answerCallbackQuery();
    await readyFlow(ctx);
  });

  bot.command("status", async (ctx) => statusFlow(ctx));
  bot.callbackQuery("status", async (ctx) => {
    await ctx.answerCallbackQuery();
    await statusFlow(ctx);
  });

  bot.command("bracket", async (ctx) => bracketFlow(ctx));
  bot.callbackQuery("bracket", async (ctx) => {
    await ctx.answerCallbackQuery();
    await bracketFlow(ctx);
  });

  bot.command("balance", async (ctx) => {
    const site = process.env.NEXT_PUBLIC_SITE_URL?.trim() || "сайте GG Cup";
    await ctx.reply(
      `Пополни баланс и создавай/смотри турики здесь: ${site}\nВход в турик списывается с баланса (50₽).`,
    );
  });

  bot.on("message:text", async (ctx, next) => {
    const text = ctx.message.text.trim();
    if (text.startsWith("/")) return next();
    const user = ctx.from;
    if (!user) return;

    // Pending tag after /join
    if (/^#?[0-9A-Za-z]{3,15}$/.test(text)) {
      const t = await getActiveTournament();
      if (!t || t.status !== "open") {
        await ctx.reply("Сейчас запись закрыта.");
        return;
      }
      const saved = await upsertPlayer({
        telegramId: user.id,
        username: user.username ?? null,
        displayName: user.first_name || user.username || "Игрок",
        brawlTag: text,
      });
      if (!saved.ok) {
        await ctx.reply(saved.error);
        return;
      }
      const reg = await registerPlayer({
        tournamentId: t.id,
        playerId: saved.player.id,
        brawlTag: text,
        payFromBalance: saved.player.balance_rub >= t.entry_fee_rub,
      });
      if (!reg.ok) {
        await ctx.reply(reg.error);
        return;
      }
      if (reg.registration.payment_status === "paid") {
        await ctx.reply(
          `Ты в турнире «${t.title}». Оплата с баланса прошла. Жди лобби/код комнаты.`,
        );
      } else {
        await ctx.reply(
          `Заявка принята (${reg.registration.brawl_tag}). Пополни баланс на сайте или оплати 50₽ организатору — после /paid тебя пустят.`,
        );
      }
      return;
    }
    return next();
  });

  // Admin commands
  bot.command("newcup", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const title =
      ctx.message?.text?.replace(/^\/newcup(@\w+)?\s*/i, "").trim() ||
      `GG Cup #${Date.now() % 1000}`;
    const t = await createTournament({
      title,
      siteUrl: process.env.NEXT_PUBLIC_SITE_URL?.trim(),
    });
    await ctx.reply(
      `Создан турик #${t.id}: ${t.title}\nВход ${t.entry_fee_rub}₽ · Приз ${t.prize_rub}₽`,
    );
  });

  bot.command("players", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const t = await getActiveTournament();
    if (!t) return void ctx.reply("Нет активного турнира");
    const regs = await listRegistrations(t.id);
    if (!regs.length) return void ctx.reply("Пока пусто");
    const lines = regs.map(
      (r) =>
        `#${r.id} ${r.display_name} ${r.brawl_tag} · ${r.payment_status} · ${r.ready_status}`,
    );
    await ctx.reply(`Участники «${t.title}»:\n${lines.join("\n")}`);
  });

  bot.command("paid", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const id = Number(ctx.message?.text?.split(/\s+/)[1]);
    if (!Number.isFinite(id)) return void ctx.reply("Формат: /paid 12");
    const reg = await markPaid(id);
    await ctx.reply(reg ? `Оплата #${id} подтверждена` : "Не найдено");
  });

  bot.command("room", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const code =
      ctx.message?.text?.replace(/^\/room(@\w+)?\s*/i, "").trim() || "";
    const t = await getActiveTournament();
    if (!t) return void ctx.reply("Нет турнира");
    const res = await openLobby({ tournamentId: t.id, roomCode: code });
    if (!res.ok) return void ctx.reply(res.error);

    // Notify paid players in DM when possible
    const regs = (await listRegistrations(t.id)).filter(
      (r) => r.payment_status === "paid" && r.telegram_id,
    );
    for (const r of regs) {
      try {
        await ctx.api.sendMessage(
          r.telegram_id!,
          [
            `🚪 Комната «${t.title}»`,
            `Код: ${code}`,
            `У тебя 60 секунд. Жми /ready или «Я в комнате».`,
            `Не успеешь — ВЫБЫЛ, вместо тебя BOT.`,
          ].join("\n"),
          {
            reply_markup: new InlineKeyboard().text("Я в комнате", "ready"),
          },
        );
      } catch {
        /* user may not have started bot */
      }
    }

    await ctx.reply(
      `Лобби открыто до ${res.deadline}. Код ${code}. Чек-ин 60с. Добавь теги из /friends в игре.`,
    );
  });

  bot.command("settle", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const t = await getActiveTournament();
    if (!t) return void ctx.reply("Нет турнира");
    // force deadline to past
    const { sql } = await import("@/lib/db");
    await sql(
      `update tournaments set lobby_deadline_at = now() - interval '1 second' where id = $1`,
      [t.id],
    );
    const res = await settleLobbyIfNeeded(t.id);
    await ctx.reply(
      res.settled
        ? `Чек-ин закрыт. No-show: ${res.noshows.length}. Турнир LIVE.`
        : "Нечего закрывать (не checkin или дедлайн ещё не вышел — принудительно выстави дедлайн).",
    );
  });

  bot.command("friends", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const items = await listFriendQueue("pending");
    await ctx.reply(friendQueueHelpText(items));
  });

  bot.command("friendok", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const id = Number(ctx.message?.text?.split(/\s+/)[1]);
    if (!Number.isFinite(id)) return void ctx.reply("Формат: /friendok 3");
    const item = await markFriendAdded(id);
    await ctx.reply(item ? `Тег ${item.brawl_tag} отмечен добавленным` : "Не найдено");
  });

  bot.command("stream", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const url =
      ctx.message?.text?.replace(/^\/stream(@\w+)?\s*/i, "").trim() || "";
    const t = await getActiveTournament();
    if (!t) return void ctx.reply("Нет турнира");
    if (!url) return void ctx.reply("Формат: /stream https://...");
    await setStream(t.id, url);
    await ctx.reply("Стрим сохранён");
  });

  bot.command("winner", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const id = Number(ctx.message?.text?.split(/\s+/)[1]);
    const t = await getActiveTournament();
    if (!t) return void ctx.reply("Нет турнира");
    if (!Number.isFinite(id)) return void ctx.reply("Формат: /winner 12");
    await setWinner(t.id, id);
    await ctx.reply("Победитель зафиксирован, пост ушёл в канал");
  });

  bot.command("makebracket", async (ctx) => {
    if (!(await ensureAdmin(ctx))) return;
    const t = await getActiveTournament();
    if (!t) return void ctx.reply("Нет турнира");
    const b = await generateAndSaveBracket(t.id);
    await ctx.reply(b ? formatBracketText(b) : "Мало игроков");
  });

  return bot;
}

async function ensureAdmin(ctx: Context): Promise<boolean> {
  const id = ctx.from?.id;
  if (!id || !isTelegramAdmin(id)) {
    await ctx.reply("Только для админов турнира");
    return false;
  }
  return true;
}

async function joinFlow(ctx: Context) {
  const t = await getActiveTournament();
  if (!t || t.status !== "open") {
    await ctx.reply("Запись сейчас закрыта");
    return;
  }
  await ctx.reply(
    `Турик «${t.title}»\nВход ${t.entry_fee_rub}₽ · Приз ${t.prize_rub}₽\n\nПришли свой Brawl Tag (обязательно), например #2PP0ABC`,
  );
}

async function readyFlow(ctx: Context) {
  const user = ctx.from;
  if (!user) return;
  const player = await getPlayerByTelegram(user.id);
  if (!player) {
    await ctx.reply("Сначала /join и укажи Brawl Tag");
    return;
  }
  const t = await getActiveTournament();
  if (!t) {
    await ctx.reply("Нет активного турнира");
    return;
  }
  await settleLobbyIfNeeded(t.id);
  const res = await markReady({ tournamentId: t.id, playerId: player.id });
  if (!res.ok) {
    await ctx.reply(res.error);
    return;
  }
  const lobby = await lobbyStatus(t.id);
  await ctx.reply(
    `Ок, ты в комнате ✅\nКод: ${lobby?.roomCode ?? "—"}\nГотовы: ${lobby?.ready.length ?? 0} · Ждут: ${lobby?.waiting.length ?? 0}`,
  );
}

async function statusFlow(ctx: Context) {
  const user = ctx.from;
  if (!user) return;
  const player = await getPlayerByTelegram(user.id);
  const t = await getActiveTournament();
  if (!t) return void ctx.reply("Нет турнира");
  if (!player) return void ctx.reply(`Баланс сайта: зайди на сайт. Турнир: ${t.title} [${t.status}]`);
  const reg = await getRegistrationForPlayer(t.id, player.id);
  await ctx.reply(
    [
      `Игрок: ${player.display_name} ${player.brawl_tag}`,
      `Баланс: ${player.balance_rub}₽`,
      `Турик: ${t.title} [${t.status}]`,
      reg
        ? `Запись: ${reg.payment_status} · чек-ин: ${reg.ready_status}`
        : "Ты ещё не записан — /join",
      t.room_code ? `Код комнаты: ${t.room_code}` : "",
    ]
      .filter(Boolean)
      .join("\n"),
  );
}

async function bracketFlow(ctx: Context) {
  const t = await getActiveTournament();
  if (!t) return void ctx.reply("Нет турнира");
  await settleLobbyIfNeeded(t.id);
  const fresh = await getTournament(t.id);
  const bracket = parseBracket(fresh?.bracket_json ?? null);
  if (!bracket) {
    await ctx.reply("Сетка ещё не собрана. Админ: /room КОД или /makebracket");
    return;
  }
  await ctx.reply(formatBracketText(bracket));
}
