const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let ACCOUNTS = [], CHATS = [], CURRENT_CHAT = null, CURRENT_CAMPAIGN = null, MEMBERS_OFFSET = 0;
const INVITED_TARGET = "@skyptop_new_delivery";
const INVITED_CHAT_ID = 4396252688;
const INVITED_STORAGE_KEY = "tg-audience:invited-snapshot:4396252688";
const MOSCOW_TIME_ZONE = "Europe/Moscow";
let INVITED_ROWS = [];
let INVITED_CALENDAR_YEAR = null;
let INVITED_CALENDAR_MONTH = null;
let INVITED_SELECTED_DATE = null;

// ─────────────────────────────────────────────────────── утилиты

function toast(msg, isError) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "show" + (isError ? " err" : "");
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = ""), 4000);
}

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString("ru-RU");
const fmtDuration = (seconds) => {
  const s = Math.max(0, Number(seconds) || 0);
  if (s >= 3600) return `${Math.floor(s / 3600)} ч ${Math.ceil((s % 3600) / 60)} мин`;
  if (s >= 60) return `${Math.ceil(s / 60)} мин`;
  return `${s} с`;
};
const plural = (n, a, b, c) => {
  const m = n % 100, k = n % 10;
  return n + " " + (m > 10 && m < 20 ? c : k === 1 ? a : k > 1 && k < 5 ? b : c);
};

// ─────────────────────────────────────────────────────── вкладки

document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".pane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "base") loadChats();
    if (btn.dataset.tab === "invite") loadCampaignForm();
    if (btn.dataset.tab === "invited") loadInvitedTab();
    if (btn.dataset.tab === "notifications") loadNotificationSettings();
    if (btn.dataset.tab === "log") loadLog();
  };
});

// ─────────────────────────────────────────────────────── настройки

async function loadSettings() {
  const s = await api("/settings");
  if (s.api_id) $("set-api-id").value = s.api_id;
  $("set-status").textContent = s.api_hash_set
    ? "api_id и api_hash сохранены."
    : "api_id / api_hash не заданы — авторизация аккаунтов не заработает.";
}

$("set-save").onclick = async () => {
  try {
    await api("/settings", { method: "POST", body: {
      api_id: Number($("set-api-id").value), api_hash: $("set-api-hash").value.trim() } });
    toast("Сохранено");
    loadSettings();
  } catch (e) { toast(e.message, true); }
};

// ─────────────────────────────────────────────────────── уведомления

async function loadNotificationSettings() {
  try {
    const settings = await api("/notifications/settings");
    $("notif-status").textContent = settings.token_set
      ? `Токен сохранён${settings.bot_username ? ` для @${settings.bot_username}` : ""}.`
      : "Токен ещё не сохранён";
    $("notif-token").placeholder = settings.token_set
      ? "Сохранён — вставьте новый только для замены"
      : "1234567890:AA…";
    $("notif-recipient-status").textContent = settings.recipient_set
      ? `Подключён: ${settings.recipient_label || "личный чат"}`
      : "Получатель ещё не подключён";
    $("notif-connect").disabled = !settings.token_set || settings.recipient_set;
    $("notif-connect").textContent = settings.recipient_set
      ? "Получатель подключён"
      : "Найти получателя";
    $("notif-test").disabled = !settings.recipient_set;
    $("notif-report").disabled = !settings.notifications_enabled;
    $("notif-schedule-status").textContent = settings.notifications_enabled
      ? "Включено: уведомление после каждой завершённой попытки приглашения"
      : "Событийные уведомления ещё не активны";
  } catch (e) {
    $("notif-status").textContent = "Не удалось загрузить настройки";
    $("notif-recipient-status").textContent = "Не удалось загрузить получателя";
    $("notif-connect").disabled = true;
    $("notif-test").disabled = true;
    $("notif-report").disabled = true;
    $("notif-schedule-status").textContent = "Не удалось загрузить режим уведомлений";
  }
}

$("notif-save").onclick = async () => {
  const token = $("notif-token").value.trim();
  if (!token) return toast("Вставьте токен, полученный от BotFather", true);
  const button = $("notif-save");
  button.disabled = true;
  button.textContent = "Проверяю…";
  $("notif-status").textContent = "Проверяю токен через Telegram";
  try {
    const result = await api("/notifications/settings", {
      method: "POST", body: { bot_token: token },
    });
    $("notif-token").value = "";
    toast(`Бот @${result.bot_username} подключён`);
    await loadNotificationSettings();
  } catch (e) {
    $("notif-status").textContent = "Токен не сохранён";
    toast(e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Проверить и сохранить";
  }
};

$("notif-connect").onclick = async () => {
  const button = $("notif-connect");
  button.disabled = true;
  button.textContent = "Ищу…";
  $("notif-recipient-status").textContent = "Ищу последнее нажатие Start";
  try {
    const result = await api("/notifications/connect", { method: "POST" });
    toast(`Получатель подключён: ${result.recipient_label}`);
    await loadNotificationSettings();
  } catch (e) {
    $("notif-recipient-status").textContent = "Получатель не найден";
    toast(e.message, true);
  } finally {
    await loadNotificationSettings();
  }
};

$("notif-test").onclick = async () => {
  const button = $("notif-test");
  button.disabled = true;
  button.textContent = "Отправляю…";
  try {
    await api("/notifications/test", { method: "POST" });
    toast("Тестовое сообщение отправлено в Telegram");
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.textContent = "Отправить тест";
    await loadNotificationSettings();
  }
};

$("notif-report").onclick = async () => {
  const button = $("notif-report");
  button.disabled = true;
  button.textContent = "Отправляю…";
  try {
    await api("/notifications/report", { method: "POST" });
    toast("Отчёт о кампаниях отправлен в Telegram");
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.textContent = "Отправить отчёт сейчас";
    await loadNotificationSettings();
  }
};

// ─────────────────────────────────────────────────────── аккаунты

const STATUS_LABEL = {
  new: ["не авторизован", ""],
  needs_code: ["ждёт код", "warn"],
  needs_password: ["ждёт пароль 2FA", "warn"],
  authorized: ["авторизован", "ok"],
  banned: ["заблокирован", "err"],
  error: ["ошибка", "err"],
};

function accountCard(a) {
  const [label, cls] = STATUS_LABEL[a.status] || [a.status, ""];
  const inService = a.status === "authorized" && Boolean(a.can_invite) &&
    !Boolean(a.invite_restricted);
  const serviceLabel = inService ? "В строю" : "Не в строю";
  const serviceClass = inService ? "ok" : "err";
  let inviteLabel = "готов к приглашению", inviteClass = "ok";
  if (a.invite_restricted) {
    inviteLabel = "ограничен Telegram — требуется ручное восстановление";
    inviteClass = "err";
  } else if (!a.can_invite) {
    inviteLabel = "не участвует в инвайтинге";
    inviteClass = "err";
  } else if (a.cooldown_left > 0) {
    inviteLabel = `защитная пауза: ещё ${fmtDuration(a.cooldown_left)}`;
    inviteClass = "warn";
  } else if (a.successful_today >= a.daily_limit) {
    inviteLabel = "суточный лимит исчерпан";
    inviteClass = "warn";
  } else if (a.next_attempt_in > 0) {
    inviteLabel = `ожидает интервал: ${fmtDuration(a.next_attempt_in)}`;
    inviteClass = "warn";
  }
  const inviteState = a.status === "authorized"
    ? `<span class="badge ${inviteClass}">${inviteLabel}</span>` : "";
  let auth = "";
  if (a.status === "new" || a.status === "error")
    auth = `<button onclick="sendCode(${a.id})">Запросить код</button>`;
  if (a.status === "needs_code")
    auth = `<input id="code-${a.id}" placeholder="код из Telegram" style="max-width:170px">
            <button class="primary" onclick="signIn(${a.id})">Войти</button>
            <button onclick="sendCode(${a.id})">Новый код</button>`;
  if (a.status === "needs_password")
    auth = `<input id="pwd-${a.id}" type="password" placeholder="пароль 2FA" style="max-width:170px">
            <button class="primary" onclick="signInPwd(${a.id})">Подтвердить</button>`;

  return `<div class="item">
    <div class="item-head">
      <span class="item-title">${esc(a.label)}</span>
      <span class="badge ${cls}">${label}</span>
      ${inviteState}
      ${a.tg_username ? `<span class="badge">@${esc(a.tg_username)}</span>` : ""}
      <span class="badge ${serviceClass} account-service-status">${serviceLabel}</span>
    </div>
    <div class="item-meta">
      ${esc(a.phone)} · сегодня успешно ${a.successful_today || 0} ·
      попыток ${a.invites_today}/${a.daily_limit} ·
      пауза ${a.min_delay}–${a.max_delay} с · пачка ${a.batch_size} ·
      ${a.next_attempt_in > 0 ? `следующая попытка через ${fmtDuration(a.next_attempt_in)} · ` : ""}
      хэшей в базе: ${a.hashes}
      ${a.proxy ? " · прокси задан" : ' · <span style="color:var(--warn)">без прокси</span>'}
      ${a.shared_proxy_warning
        ? `<br><span style="color:var(--warn)">${esc(a.shared_proxy_warning)}</span>` : ""}
      ${a.last_error ? `<br><span style="color:var(--err)">${esc(a.last_error)}</span>` : ""}
      ${a.invite_restriction_reason
        ? `<br><span style="color:var(--err)">${esc(a.invite_restriction_reason)}</span>` : ""}
    </div>
    <div class="row">
      ${auth}
      <button onclick="checkAccount(${a.id}, this)">Проверить</button>
      <button onclick="testProxy(${a.id}, this)">Проверить прокси</button>
      <button onclick="editAccount(${a.id})">Настроить</button>
      ${a.can_invite
        ? `<button class="danger" onclick="setInviteEnabled(${a.id}, false)">Отключить инвайтинг</button>`
        : `<button class="primary" onclick="setInviteEnabled(${a.id}, true)">Включить инвайтинг</button>`}
      ${a.cooldown_left > 0 && !a.invite_restricted
        ? `<button onclick="resetCooldown(${a.id})">Снять паузу</button>` : ""}
      ${a.invite_restricted && a.cooldown_left <= 0
        ? `<button class="primary" onclick="restoreInvites(${a.id})">Восстановить инвайтинг</button>` : ""}
      <button class="danger" onclick="removeAccount(${a.id})">Удалить</button>
    </div>
  </div>`;
}

// Пока пользователь вводит код или идёт долгая проверка — не перерисовываем
// карточки: иначе автообновление затрёт введённый код прямо под руками.
let REFRESH_PAUSED_UNTIL = 0;

function accountsListBusy() {
  if (Date.now() < REFRESH_PAUSED_UNTIL) return true;
  const active = document.activeElement;
  const list = $("accounts-list");
  if (active && active.tagName === "INPUT" && list.contains(active)) return true;
  return [...list.querySelectorAll("input")].some((i) => i.value.trim() !== "");
}

async function loadAccounts(force) {
  ACCOUNTS = await api("/accounts");
  if (force || !accountsListBusy()) {
    $("accounts-list").innerHTML = ACCOUNTS.length
      ? ACCOUNTS.map(accountCard).join("")
      : '<p class="hint">Пока ни одного аккаунта.</p>';
  }

  const sel = $("parse-account");
  const keep = sel.value;
  sel.innerHTML = ACCOUNTS.filter((a) => a.status === "authorized" && a.can_parse)
    .map((a) => `<option value="${a.id}">${esc(a.label)}</option>`).join("")
    || '<option value="">— нет авторизованных —</option>';
  if (keep) sel.value = keep;
}

$("acc-add").onclick = async () => {
  const phone = $("acc-phone").value.trim();
  if (!phone) return toast("Укажите телефон", true);
  try {
    await api("/accounts", { method: "POST", body: {
      label: $("acc-label").value.trim() || phone,
      phone,
      proxy: $("acc-proxy").value.trim() || null,
      daily_limit: Number($("acc-limit").value) || 2,
    } });
    $("acc-label").value = $("acc-phone").value = $("acc-proxy").value = "";
    toast("Аккаунт добавлен — запросите код");
    loadAccounts(true);
  } catch (e) { toast(e.message, true); }
};

window.sendCode = async (id) => {
  try { await api(`/accounts/${id}/code`, { method: "POST" }); toast("Код отправлен"); }
  catch (e) { toast(e.message, true); }
  loadAccounts(true);
};

window.signIn = async (id) => {
  const code = $(`code-${id}`).value.trim();
  try {
    const r = await api(`/accounts/${id}/signin`, { method: "POST", body: { code } });
    toast(r.status === "needs_password" ? "Введите пароль 2FA" : "Аккаунт авторизован");
  } catch (e) { toast(e.message, true); }
  loadAccounts(true);
};

window.signInPwd = async (id) => {
  try {
    await api(`/accounts/${id}/password`, { method: "POST", body: { password: $(`pwd-${id}`).value } });
    toast("Аккаунт авторизован");
  } catch (e) { toast(e.message, true); }
  loadAccounts(true);
};

window.checkAccount = async (id, btn) => {
  const original = btn?.textContent || "Проверить";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Проверяю…";
  }
  try {
    const r = await api(`/accounts/${id}/check`, { method: "POST" });
    const labels = {
      authorized: "Аккаунт авторизован и готов к работе",
      new: "Аккаунт пока не авторизован — запросите код",
      banned: "Аккаунт заблокирован Telegram",
      error: "Не удалось проверить аккаунт",
    };
    toast(labels[r.status] || `Статус аккаунта: ${r.status}`,
      r.status === "banned" || r.status === "error");
  } catch (e) {
    toast(e.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = original;
    }
    loadAccounts(true);
  }
};

window.testProxy = async (id, btn) => {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Проверяю…";
  REFRESH_PAUSED_UNTIL = Date.now() + 40000;
  try {
    const r = await api(`/accounts/${id}/test_proxy`, { method: "POST" });
    if (r.ok) {
      toast(`Соединение есть: ${r.latency_ms} мс (${r.verdict}), DC ${r.dc}` +
        (r.proxy ? "" : " — но прокси не задан, идём напрямую"));
    } else {
      toast("Прокси не работает: " + r.error, true);
    }
  } catch (e) { toast(e.message, true); }
  REFRESH_PAUSED_UNTIL = 0;
  btn.disabled = false;
  btn.textContent = original;
  loadAccounts(true);
};

window.resetCooldown = async (id) => {
  await api(`/accounts/${id}/reset_cooldown`, { method: "POST" });
  toast("Пауза снята — но если это был PEER_FLOOD, аккаунт лучше не трогать сутки");
  loadAccounts(true);
};

window.restoreInvites = async (id) => {
  const account = ACCOUNTS.find((item) => item.id === id);
  if (!confirm(
    `Вернуть «${account?.label || id}» в инвайтинг после PEER_FLOOD? ` +
    "Делайте это только если ограничение Telegram уже снято."
  )) return;
  try {
    await api(`/accounts/${id}/restore_invites`, { method: "POST" });
    toast("Ограничение снято вручную; аккаунт снова доступен preflight");
    await loadAccounts(true);
  } catch (e) {
    toast(e.message, true);
  }
};

window.setInviteEnabled = async (id, enabled) => {
  const account = ACCOUNTS.find((item) => item.id === id);
  if (!enabled && !confirm(
    `Отключить инвайтинг для «${account?.label || id}»? ` +
    "Активные кампании продолжат работать на остальных аккаунтах."
  )) return;
  try {
    await api(`/accounts/${id}`, {
      method: "PATCH",
      body: { can_invite: enabled },
    });
    toast(enabled
      ? "Инвайтинг включён — аккаунт можно выбирать в новых кампаниях"
      : "Аккаунт отключён; остальные аккаунты продолжают кампании");
    await loadAccounts(true);
  } catch (e) {
    toast(e.message, true);
  }
};

window.removeAccount = async (id) => {
  if (!confirm("Удалить аккаунт из пула? Сессия на диске останется.")) return;
  await api(`/accounts/${id}`, { method: "DELETE" });
  loadAccounts(true);
};

window.editAccount = async (id) => {
  const a = ACCOUNTS.find((x) => x.id === id);
  const proxy = prompt("Прокси (пусто — без прокси):", a.proxy || "");
  if (proxy === null) return;
  const limit = prompt("Суточный защитный лимит попыток:", a.daily_limit);
  if (limit === null) return;
  const delays = prompt(
    "Пауза после засчитанной попытки, «мин-макс» секунд. Приватность пропускается сразу. Например: 90-240 или 14400-14400:",
    `${a.min_delay}-${a.max_delay}`
  );
  if (delays === null) return;
  const [min, max] = delays.split("-").map((v) => parseInt(v.trim(), 10));
  if (!Number.isInteger(min) || !Number.isInteger(max) || min < 1 || max < min) {
    return toast("Введите два целых числа: минимум не меньше 1, максимум не меньше минимума", true);
  }
  try {
    await api(`/accounts/${id}`, { method: "PATCH", body: {
      proxy: proxy.trim(), daily_limit: Number(limit),
      min_delay: min, max_delay: max } });
    toast("Сохранено");
  } catch (e) { toast(e.message, true); }
  loadAccounts(true);
};

// ─────────────────────────────────────────────────────── парсинг

$("parse-load-dialogs").onclick = async () => {
  const id = $("parse-account").value;
  if (!id) return toast("Нет авторизованного аккаунта", true);
  $("parse-load-dialogs").disabled = true;
  $("parse-load-dialogs").textContent = "Загружаю…";
  try {
    const dialogs = await api(`/dialogs/${id}`);
    $("parse-dialog").innerHTML = '<option value="">— выберите чат —</option>' +
      dialogs.map((d) => `<option value="${d.id}">${esc(d.title)} · ${d.kind}` +
        `${d.members_count ? " · " + d.members_count : ""}${d.is_admin ? " · админ" : ""}</option>`).join("");
    toast(`Найдено ${plural(dialogs.length, "чат", "чата", "чатов")}`);
  } catch (e) { toast(e.message, true); }
  $("parse-load-dialogs").disabled = false;
  $("parse-load-dialogs").textContent = "Загрузить список чатов";
};

$("parse-messages-all").onchange = () => {
  $("parse-messages").disabled = $("parse-messages-all").checked;
};

function parsePayload() {
  const chat = $("parse-manual").value.trim() || $("parse-dialog").value;
  if (!chat) { toast("Выберите чат", true); return null; }
  const sources = [];
  if ($("src-participants").checked) sources.push("participants");
  if ($("src-history").checked) sources.push("history");
  if ($("src-reactions").checked) sources.push("reactions");
  if (!sources.length) { toast("Выберите хотя бы один источник", true); return null; }
  return {
    chat, sources,
    deep: $("src-deep").checked,
    messages_limit: $("parse-messages-all").checked
      ? null : Number($("parse-messages").value) || 5000,
    posts_limit: Number($("parse-posts").value) || 100,
  };
}

$("parse-start").onclick = async () => {
  const body = parsePayload();
  if (!body) return;
  try {
    await api("/parse", { method: "POST",
      body: { ...body, account_id: Number($("parse-account").value) } });
    toast("Парсинг запущен");
    loadJobs();
  } catch (e) { toast(e.message, true); }
};

$("parse-start-all").onclick = async () => {
  const body = parsePayload();
  if (!body) return;
  const count = ACCOUNTS.filter((a) => a.status === "authorized" && a.can_parse).length;
  if (!count) return toast("Нет авторизованных аккаунтов", true);
  if (!confirm(`Спарсить этот чат каждым из ${count} аккаунтов по очереди?\n\n` +
    "Все они должны состоять в чате. Это нужно, чтобы у каждого появились свои " +
    "access_hash — иначе инвайтить можно будет только юзеров с @username.")) return;
  try {
    const r = await api("/parse/all", { method: "POST", body });
    toast(`Запущено по очереди на ${r.accounts} аккаунтах`);
    loadJobs();
  } catch (e) { toast(e.message, true); }
};

async function loadJobs() {
  const jobs = await api("/jobs");
  $("jobs-list").innerHTML = jobs.length ? jobs.map((j) => {
    const cls = j.status === "error" ? "err" : j.status === "done" ? "ok" : "warn";
    const label = { running: "идёт", done: "готово", error: "ошибка", paused: "остановлено" }[j.status]
      || j.status;
    const stop = j.status === "running" && !j.stop_requested
      ? `<button onclick="stopJob('${esc(j.id)}', this)">Остановить</button>` : "";
    const progress = j.total_accounts
      ? `<span class="badge">${j.done_accounts || 0} / ${j.total_accounts} аккаунтов</span>` : "";
    return `<div class="item">
      <div class="item-head">
        <span class="item-title">${esc(j.title)}</span>
        <span class="badge ${cls}">${label}</span>
        ${progress}
        ${stop}
      </div>
      <div class="item-meta">${esc(j.stage || "")} · обработано ${j.processed}
        · новых за проход ${j.added ?? j.found ?? 0}
        ${j.total != null ? ` · всего в единой базе ${j.total}` : ""}
        ${j.error ? `<br><span style="color:var(--err)">${esc(j.error)}</span>` : ""}</div>
    </div>`;
  }).join("") : '<p class="hint">Задач пока нет.</p>';
}

window.stopJob = async (id, btn) => {
  btn.disabled = true;
  try {
    await api(`/jobs/${encodeURIComponent(id)}/stop`, { method: "POST" });
    toast("Останавливаю — место прохода сохранится");
    loadJobs();
  } catch (e) { toast(e.message, true); btn.disabled = false; }
};

// ─────────────────────────────────────────────────────── база

$("csv-import-file").onchange = () => {
  const file = $("csv-import-file").files[0];
  $("csv-import-status").textContent = file
    ? `${file.name} · ${(file.size / 1024).toFixed(1)} КБ`
    : "Файл не выбран";
};

$("csv-import-btn").onclick = async () => {
  const file = $("csv-import-file").files[0];
  if (!file) return toast("Выберите CSV-файл", true);
  if (file.size > 10 * 1024 * 1024) return toast("CSV-файл больше 10 МБ", true);

  const btn = $("csv-import-btn");
  btn.disabled = true;
  btn.textContent = "Загружаю…";
  $("csv-import-status").textContent = "Проверяю строки и убираю дубли";
  try {
    const r = await api("/members/import", { method: "POST", body: {
      name: $("csv-import-name").value.trim() || file.name.replace(/\.csv$/i, ""),
      csv_text: await file.text(),
    } });
    $("csv-import-status").textContent =
      `Готово: загружено ${r.imported}, пропущено ${r.skipped}`;
    toast(`CSV загружен: ${r.imported} записей`);
    $("csv-import-file").value = "";
    await loadChats();
  } catch (e) {
    $("csv-import-status").textContent = "Импорт не выполнен";
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Загрузить CSV";
  }
};

async function loadChats() {
  CHATS = await api("/chats");
  $("chats-list").innerHTML = CHATS.length ? CHATS.map((c) => `<div class="item">
    <div class="item-head">
      <span class="item-title">${esc(c.title || c.id)}</span>
      <span class="badge">${c.kind}</span>
      <span class="badge ok">${c.parsed} в базе</span>
    </div>
    <div class="item-meta">id ${c.id}${c.username ? " · @" + esc(c.username) : ""}
      ${c.last_parsed_at ? " · обновлено " + new Date(c.last_parsed_at * 1000).toLocaleString("ru-RU") : ""}</div>
    <div class="row">
      <button onclick="openMembers(${c.id})">Показать</button>
      <button onclick="location.href='/api/members/export?chat_id=${c.id}'">CSV</button>
      <button class="danger" onclick="dropChat(${c.id})">Удалить из базы</button>
    </div>
  </div>`).join("") : '<p class="hint">База пуста — начните с вкладки «Парсинг».</p>';
}

window.dropChat = async (id) => {
  if (!confirm("Удалить чат и всех его участников из базы?")) return;
  await api(`/chats/${id}`, { method: "DELETE" });
  loadChats();
};

window.openMembers = (id) => {
  CURRENT_CHAT = id;
  MEMBERS_OFFSET = 0;
  $("members-card").hidden = false;
  const chat = CHATS.find((c) => c.id === id);
  $("members-title").textContent = "Участники — " + (chat?.title || id);
  $("members-table").innerHTML = "";
  loadMembers(true);
};

async function loadMembers(reset) {
  if (reset) { MEMBERS_OFFSET = 0; $("members-table").innerHTML = ""; }
  const search = encodeURIComponent($("members-search").value.trim());
  const data = await api(`/members?chat_id=${CURRENT_CHAT}&offset=${MEMBERS_OFFSET}&limit=100&search=${search}`);
  const table = $("members-table");
  if (!table.innerHTML) {
    table.innerHTML = `<thead><tr><th>id</th><th>username</th><th>имя</th>
      <th>сообщений</th><th>был в сети</th><th>источник</th></tr></thead><tbody></tbody>`;
  }
  table.querySelector("tbody").insertAdjacentHTML("beforeend", data.items.map((m) => `<tr>
    <td>${m.user_id}</td>
    <td>${m.username ? "@" + esc(m.username) : "—"}</td>
    <td>${esc(((m.first_name || "") + " " + (m.last_name || "")).trim()) || "—"}</td>
    <td>${m.msg_count}</td>
    <td>${esc(m.last_seen || "—")}</td>
    <td>${esc(m.sources)}</td></tr>`).join(""));
  MEMBERS_OFFSET += data.items.length;
  $("members-count").textContent = `Показано ${MEMBERS_OFFSET} из ${data.total}`;
  $("members-more").disabled = MEMBERS_OFFSET >= data.total;
}

$("members-more").onclick = () => loadMembers(false);
$("members-search").oninput = () => { clearTimeout(window._ms);
  window._ms = setTimeout(() => loadMembers(true), 300); };
$("members-export").onclick = () => location.href = `/api/members/export?chat_id=${CURRENT_CHAT}`;

// ─────────────────────────────────────────────────────── кампании

async function loadCampaignForm() {
  await loadAccounts();
  CHATS = await api("/chats");
  $("camp-accounts").innerHTML = ACCOUNTS.filter((a) =>
    a.status === "authorized" && a.can_invite && !a.invite_restricted)
    .map((a) => `<label><input type="checkbox" class="camp-acc" value="${a.id}" checked>
      ${esc(a.label)} <span class="hint-inline">(${a.quota_left} сегодня, ${a.hashes} хэшей)</span></label>`)
    .join("") || '<p class="hint">Нет авторизованных аккаунтов с правом инвайта.</p>';
  $("camp-sources").innerHTML = CHATS.filter((c) => c.parsed > 0)
    .map((c) => `<label><input type="checkbox" class="camp-src" value="${c.id}">
      ${esc(c.title || c.id)} <span class="hint-inline">(${c.parsed})</span></label>`)
    .join("") || '<p class="hint">Сначала спарсите хотя бы один чат.</p>';
  loadCampaigns();
}

$("camp-sync-target").onclick = async () => {
  const target = $("camp-target").value.trim();
  if (!target) return toast("Сначала укажите целевой чат", true);
  const account = document.querySelector(".camp-acc:checked");
  if (!account) return toast("Выберите аккаунт-инвайтер", true);

  const btn = $("camp-sync-target");
  btn.disabled = true;
  btn.textContent = "Проверяю участников…";
  $("camp-sync-status").textContent = "Загружаю актуальный состав целевого чата";
  try {
    const r = await api("/campaigns/sync-target", { method: "POST", body: {
      account_id: Number(account.value), target_chat: target,
    } });
    $("camp-sync-status").textContent =
      `Готово: ${r.total} участников будут исключены, новых найдено ${r.added}`;
    toast(`Дубли исключены: в целевом чате ${r.total} участников`);
  } catch (e) {
    $("camp-sync-status").textContent = "Не удалось обновить список участников";
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Исключить дубли";
  }
};

$("camp-create").onclick = async () => {
  const account_ids = [...document.querySelectorAll(".camp-acc:checked")].map((e) => Number(e.value));
  const source_chat_ids = [...document.querySelectorAll(".camp-src:checked")].map((e) => Number(e.value));
  const target = $("camp-target").value.trim();
  if (!target) return toast("Укажите целевой чат", true);
  try {
    const r = await api("/campaigns", { method: "POST", body: {
      name: $("camp-name").value.trim() || "Кампания",
      target_chat: target, account_ids, source_chat_ids,
      filters: {
        skip_bots: $("f-bots").checked,
        skip_deleted: $("f-deleted").checked,
        only_username: $("f-username").checked,
        only_active: $("f-active").checked,
        skip_dormant: $("f-dormant").checked,
        only_premium: $("f-premium").checked,
        active_first: $("f-order").checked,
        min_messages: Number($("f-min-msg").value) || 1,
        limit: Number($("f-limit").value) || 5000,
      } } });
    toast(`Кампания создана, целей: ${r.targets}`);
    openCampaign(r.id);
    loadCampaigns();
  } catch (e) { toast(e.message, true); }
};

const CAMP_STATUS = { draft: ["черновик", ""], running: ["идёт", "ok"],
  paused: ["на паузе", "warn"], done: ["завершена", "ok"], error: ["ошибка", "err"] };

async function loadCampaigns() {
  const list = await api("/campaigns");
  const healthByCampaign = await loadRunningCampaignHealth(list);
  $("campaigns-list").innerHTML = list.length ? list.map((c) => {
    const [label, cls] = CAMP_STATUS[c.status] || [c.status, ""];
    const s = c.stats;
    const health = healthByCampaign.get(Number(c.id));
    let runtimeBadge = "";
    if (c.running && !health) {
      runtimeBadge = '<span class="badge warn">проверяю аккаунты…</span>';
    } else if (c.running && health.total === 0) {
      runtimeBadge = '<span class="badge warn">аккаунты запускаются…</span>';
    } else if (c.running && health.active === 0) {
      runtimeBadge = `<span class="badge err">нет работающих аккаунтов: 0/${health.total}</span>`;
    } else if (c.running && health.active < health.total) {
      runtimeBadge = `<span class="badge warn">работают не все: ${health.active}/${health.total}</span>`;
    } else if (c.running) {
      runtimeBadge = `<span class="badge ok">работают все: ${health.active}/${health.total}</span>`;
    }
    return `<div class="item">
      <div class="item-head">
        <span class="item-title">${esc(c.name)}</span>
        <span class="badge ${cls}">${label}</span>
        ${runtimeBadge}
      </div>
      <div class="item-meta">→ ${esc(c.target_title || c.target_chat_id)} ·
        целей ${s.total || 0} · приглашено ${s.invited || 0} · осталось ${s.pending || 0}` +
        `${health?.removed ? ` · снято аккаунтов: ${health.removed}` : ""}</div>
      <div class="row"><button onclick="openCampaign(${c.id})">Открыть</button>
        <button class="danger" onclick="dropCampaign(${c.id})">Удалить</button></div>
    </div>`;
  }).join("") : '<p class="hint">Кампаний пока нет.</p>';
}

window.dropCampaign = async (id) => {
  if (!confirm("Удалить кампанию вместе со списком целей?")) return;
  await api(`/campaigns/${id}`, { method: "DELETE" });
  if (CURRENT_CAMPAIGN === id) { CURRENT_CAMPAIGN = null; $("campaign-detail").hidden = true; }
  loadCampaigns();
};

const TARGET_STATUS = { pending: "в очереди", in_progress: "подготовка до отправки",
  verifying: "результат проверяется", invited: "добавление подтверждено",
  privacy: "пропущен: приватность", already: "уже в чате", deleted: "удалён",
  failed: "ошибка", no_hash: "нет access_hash", skipped: "пропущен" };

function invitationResult(target) {
  const error = String(target.error || "");
  if (target.status === "invited") {
    return { label: "Пользователь добавлен в чат", detail: "Членство подтверждено, счётчик увеличен.", cls: "ok" };
  }
  if (target.status === "failed" && error.includes("missing_invitees")) {
    return { label: "Telegram отклонил приглашение", detail: "Пользователь не добавлен. Счётчик приглашённых не увеличивается.", cls: "err" };
  }
  if (target.status === "verifying") {
    return error.includes("invite_rpc=returned")
      ? { label: "Запрос отправлен и принят Telegram", detail: "Добавление в чат ещё не подтверждено. Счётчик пока не увеличивается.", cls: "warn" }
      : { label: "Результат отправки пока неизвестен", detail: "Проверяем членство пользователя, чтобы избежать повторного приглашения.", cls: "warn" };
  }
  const detail = error.startsWith("invite_claim_pre_rpc:") ? "Приглашение ещё не отправлено." : error;
  return { label: TARGET_STATUS[target.status] || target.status, detail, cls: target.status === "failed" ? "err" : "warn" };
}

function latestWorkerStopEvent(events, accountId, runStartedAt) {
  return events.find((event) => Number(event.account_id) === Number(accountId) &&
    Number(event.ts || 0) >= Number(runStartedAt || 0) && (
    String(event.message || "").includes("PEER_FLOOD") ||
    String(event.message || "").includes("ограничен Telegram в приглашениях") ||
    String(event.message || "").includes("Нет прав добавлять участников")
  ));
}

function campaignWorkerView(worker, account, events, runStartedAt, campaign) {
  const state = String(worker.state || "");
  if (worker.not_started) {
    if (!campaign.running && campaign.status === "draft") {
      return { kind: "pending", badge: "ожидает запуска", badgeClass: "warn",
        detail: "Кампания ещё не запускалась. Проверка допуска начнётся после запуска." };
    }
    if (!campaign.running && campaign.status === "paused") {
      return { kind: "pending", badge: "кампания на паузе", badgeClass: "warn",
        detail: "Аккаунт будет проверен при следующем запуске кампании." };
    }
    let detail = "Аккаунт не был допущен к запуску этой кампании.";
    if (!account || account.status !== "authorized") {
      detail += " Сессия не авторизована или соединение с Telegram не работает.";
    } else if (!account.can_invite) {
      detail += " Инвайтинг для аккаунта отключён.";
    } else {
      detail += " Проверьте, что он состоит в целевом чате и имеет право приглашать участников.";
    }
    return { kind: "removed", badge: "не запущен", badgeClass: "err", detail };
  }
  const technicalFailure = state.includes("сбой подключения") ||
    state.includes("тайм-аут подключения") || state.includes("проверьте прокси");
  if (technicalFailure) {
    return {
      kind: "removed",
      badge: "снят: нет соединения",
      badgeClass: "err",
      canRecover: Boolean(campaign.running),
      detail: "Воркер остановлен после технического сбоя. Проверка подтвердит прокси, " +
        "Telegram-сессию и доступ к целевому чату; сохранённый интервал не сбросится.",
    };
  }
  if (state.includes("перепроверка доступа")) {
    return {
      kind: "waiting",
      badge: "в ротации · перепроверяет доступ",
      badgeClass: "warn",
      detail: `${state}. Программа заново получит данные чата и вернёт аккаунт ` +
        "к приглашениям автоматически, как только Telegram подтвердит право.",
    };
  }
  const stopEvent = latestWorkerStopEvent(events, worker.account_id, runStartedAt);
  const eventMessage = String(stopEvent?.message || "");
  let stopReason = "";

  if (state.includes("нет прав приглашать") || eventMessage.includes("Нет прав добавлять")) {
    stopReason = "нет права добавлять участников в целевой чат";
  } else if (state.includes("PEER_FLOOD") || eventMessage.includes("PEER_FLOOD")) {
    stopReason = "PEER_FLOOD — Telegram ограничил приглашения";
  } else if (eventMessage.includes("ограничен Telegram в приглашениях")) {
    stopReason = "спамблок Telegram на приглашения";
  } else if (state === "аккаунт недоступен") {
    stopReason = "аккаунт стал недоступен или инвайтинг был отключён";
  }

  // После PEER_FLOOD и спамблока текущий воркер завершается. Его старая
  // надпись остаётся в памяти кампании, поэтому явно показываем, что он снят.
  if (stopReason && (state.includes("PEER_FLOOD") || state.includes("нет прав") ||
      state === "аккаунт недоступен" || state.startsWith("приглашаю"))) {
    const pauseText = Number(account?.cooldown_left || 0) > 0
      ? `Защитная пауза закончится через ${fmtDuration(account.cooldown_left)}.`
      : "Защитная пауза уже закончилась.";
    const returnText = stopReason.includes("прав")
      ? "Верните аккаунту право приглашать и затем перезапустите кампанию."
      : `${pauseText} Чтобы вернуть аккаунт в эту кампанию, её потребуется перезапустить.`;
    return {
      kind: "removed", badge: "снят с кампании", badgeClass: "err",
      detail: `${stopReason}. ${returnText}`,
      stoppedAt: stopEvent?.ts || 0,
    };
  }

  if (!account || account.status !== "authorized") {
    return { kind: "removed", badge: "недоступен", badgeClass: "err",
      detail: "Сессия не авторизована или соединение с Telegram не работает." };
  }
  if (account.invite_restricted) {
    return { kind: "removed", badge: "ограничен Telegram", badgeClass: "err",
      detail: "Аккаунт не вернётся в ротацию автоматически. После защитной паузы " +
        "восстановите его явно в карточке аккаунта." };
  }
  if (!account.can_invite) {
    return { kind: "removed", badge: "инвайтинг отключён", badgeClass: "err",
      detail: "Аккаунт исключён из инвайтинга в настройках." };
  }
  if (Number(account.cooldown_left || 0) > 0) {
    return { kind: "waiting", badge: "в ротации · защитная пауза", badgeClass: "warn",
      detail: `Автоматически продолжит через ${fmtDuration(account.cooldown_left)}.` };
  }
  if (Number(account.quota_left || 0) <= 0) {
    return { kind: "waiting", badge: "в ротации · лимит исчерпан", badgeClass: "warn",
      detail: "Продолжит автоматически после сброса суточного лимита." };
  }
  if (state.startsWith("подготовка приглашения")) {
    return { kind: "active", badge: "подготовка · запрос не отправлен", badgeClass: "warn",
      detail: state };
  }
  if (state.startsWith("отправляю запрос приглашения") || state.startsWith("приглашаю")) {
    return { kind: "active", badge: "отправка запроса", badgeClass: "warn", detail: state };
  }
  if (state.includes("проверяю фактическое присутствие")) {
    return { kind: "active", badge: "проверка результата", badgeClass: "warn", detail: state };
  }
  if (state.startsWith("очередь кампании")) {
    return { kind: "waiting", badge: "очередь · запрос не отправлен", badgeClass: "warn", detail: state };
  }
  const accountWait = Number(account.next_attempt_in || 0);
  const campaignWait = Number(worker.campaign_wait_in || 0);
  if (Math.max(accountWait, campaignWait) > 0 || state.includes("до следующей попытки")) {
    const remaining = Math.max(accountWait, campaignWait);
    return { kind: "waiting", badge: "в ротации · ожидает интервал", badgeClass: "warn",
      detail: remaining > 0 ? `Следующая отправка не раньше чем через ${fmtDuration(remaining)}.` +
        (campaignWait > accountWait ? " Действует общий интервал кампании." : "") : state };
  }
  return { kind: "active", badge: "в ротации · готов", badgeClass: "ok",
    detail: state || "Готов к следующей цели." };
}

function campaignWorkerRows(campaign, accountRows, campaignEvents) {
  const accountsById = new Map(accountRows.map((account) => [Number(account.id), account]));
  const workersById = new Map((campaign.workers || [])
    .map((worker) => [Number(worker.account_id), worker]));
  const configuredIds = (campaign.settings?.account_ids || [...workersById.keys()]).map(Number);
  const runStartedAt = Number(campaignEvents.find((event) =>
    String(event.message || "").includes("запущена"))?.ts || campaign.created_at || 0);

  return configuredIds.map((accountId) => {
    const account = accountsById.get(accountId);
    const worker = workersById.get(accountId) || {
      account_id: accountId,
      label: account?.label || `Аккаунт ${accountId}`,
      not_started: true,
    };
    return {
      worker,
      view: campaignWorkerView(worker, account, campaignEvents, runStartedAt, campaign),
    };
  });
}

function workerServiceView(view, campaign) {
  if (!campaign.running) {
    return campaign.status === "draft"
      ? { label: "Ожидает запуска", badgeClass: "warn" }
      : { label: "Кампания на паузе", badgeClass: "warn" };
  }
  return view.kind === "removed"
    ? { label: "Не в строю", badgeClass: "err" }
    : { label: "В строю", badgeClass: "ok" };
}

async function loadRunningCampaignHealth(campaigns) {
  const running = campaigns.filter((campaign) => campaign.running);
  const result = new Map();
  if (!running.length) return result;

  let accountRows;
  try { accountRows = await api("/accounts"); }
  catch (e) { return result; }

  const entries = await Promise.all(running.map(async (campaign) => {
    try {
      const [detail, events] = await Promise.all([
        api(`/campaigns/${campaign.id}`),
        api(`/events?campaign_id=${campaign.id}&limit=200`),
      ]);
      const rows = campaignWorkerRows(detail, accountRows, events);
      const removed = rows.filter(({ view }) => view.kind === "removed").length;
      return [Number(campaign.id), {
        total: rows.length,
        active: rows.length - removed,
        removed,
      }];
    } catch (e) {
      return [Number(campaign.id), null];
    }
  }));
  entries.forEach(([id, health]) => { if (health) result.set(id, health); });
  return result;
}

window.openCampaign = async (id) => {
  CURRENT_CAMPAIGN = id;
  $("campaign-detail").hidden = false;
  await refreshCampaign();
  $("campaign-detail").scrollIntoView({ behavior: "smooth" });
};

const PREFLIGHT_LABELS = {
  not_run: ["ещё не запускалась", ""],
  running: ["идёт проверка", "warn"],
  ready: ["готово к запуску", "ok"],
  warning: ["есть предупреждения", "warn"],
  error: ["нужна проверка", "err"],
  interrupted: ["проверка прервана", "err"],
};

function renderCampaignPreflight(result) {
  const panel = $("cd-preflight-panel");
  const button = $("cd-preflight");
  const status = result?.status || "not_run";
  const [label, badgeClass] = PREFLIGHT_LABELS[status] || [status, ""];
  button.disabled = status === "running";
  button.textContent = status === "running" ? "Проверка выполняется…" :
    (status === "not_run" ? "Проверить перед запуском" : "Проверить ещё раз");

  if (status === "not_run") {
    panel.hidden = false;
    panel.className = "preflight-panel";
    panel.innerHTML = `<div class="preflight-title"><strong>Проверка перед запуском</strong>
      <span class="badge">${label}</span></div>
      <p class="preflight-note">Без приглашений проверит выбранные аккаунты и пользователей из очереди.
      Настройки приватности пользователя становятся известны только при реальном приглашении.</p>`;
    return;
  }

  const accounts = result.accounts || { total: 0, checked: 0, ready: 0, items: [] };
  const targets = result.targets || { total: 0, checked: 0 };
  const done = Number(accounts.checked || 0) + Number(targets.checked || 0);
  const total = Number(accounts.total || 0) + Number(targets.total || 0);
  const progress = total ? Math.min(100, Math.round(done * 100 / total)) : 0;
  const accountRows = (accounts.items || []).map((item) => {
    const cls = item.ready ? "ok" : (item.status === "cooldown" ? "warn" : "err");
    return `<div class="preflight-account"><span>${esc(item.label)}</span>
      <small>${esc(item.detail)}</small><span class="badge ${cls}">${item.ready ? "готов" : "не готов"}</span></div>`;
  }).join("");
  panel.hidden = false;
  panel.className = `preflight-panel ${status}`;
  panel.innerHTML = `<div class="preflight-title"><strong>Проверка перед запуском</strong>
      <span class="badge ${badgeClass}">${esc(label)}</span>
      <span class="hint-inline">${esc(result.message || "")}</span></div>
    <div class="progress"><i style="width:${progress}%"></i></div>
    <div class="preflight-metrics">
      <span class="badge ${accounts.ready === accounts.total ? "ok" : "warn"}">инвайтеры ${accounts.ready || 0}/${accounts.total || 0}</span>
      <span class="badge ok">пригодные цели ${targets.valid || 0}</span>
      <span class="badge warn">невалидные ${targets.invalid || 0}</span>
      <span class="badge warn">боты ${targets.bots || 0}</span>
      <span class="badge warn">удалённые ${targets.deleted || 0}</span>
      <span class="badge">дубли ${targets.duplicates || 0}</span>
      <span class="badge warn">нет хэша ${targets.no_hash || 0}</span>
      <span class="badge err">не проверены технически ${targets.technical || 0}</span>
    </div>
    <p class="preflight-note">Проверено целей: ${targets.checked || 0} из ${targets.total || 0}.
      Реальные Telegram ID сохраняются для приглашения и последующего подтверждения.</p>
    ${accountRows ? `<details class="preflight-accounts" ${status === "error" ? "open" : ""}>
      <summary>Показать результат по каждому аккаунту</summary>
      <div class="preflight-account-list">${accountRows}</div></details>` : ""}`;
}

async function refreshCampaign() {
  if (!CURRENT_CAMPAIGN) return;
  let c, accountRows, campaignEvents, campaignPreflight;
  try {
    [c, accountRows, campaignEvents, campaignPreflight] = await Promise.all([
      api(`/campaigns/${CURRENT_CAMPAIGN}`),
      api("/accounts"),
      api(`/events?campaign_id=${CURRENT_CAMPAIGN}&limit=200`),
      api(`/campaigns/${CURRENT_CAMPAIGN}/preflight`),
    ]);
  }
  catch (e) { CURRENT_CAMPAIGN = null; $("campaign-detail").hidden = true; return; }

  $("cd-title").textContent = `${c.name} → ${c.target_title || c.target_chat_id}`;
  const s = c.stats;
  const cells = [["total", "целей"], ["invited", "добавлено в чат"],
    ["verifying", "ожидают подтверждения"], ["privacy", "приватность"],
    ["already", "уже в чате"], ["no_hash", "нет хэша"], ["failed", "ошибки"], ["pending", "осталось"]];
  $("cd-stats").innerHTML = cells.map(([k, label]) =>
    `<div class="stat"><b>${s[k] || 0}</b><span>${label}</span></div>`).join("");
  $("cd-stats").title = "Счётчик добавленных увеличивается после подтверждения членства. Результаты запросов показаны ниже у аккаунтов и в последних попытках.";

  renderCampaignPreflight(campaignPreflight);
  $("cd-start").disabled = c.running || campaignPreflight?.status === "running";
  $("cd-stop").disabled = !c.running;
  $("cd-preflight").disabled = c.running || campaignPreflight?.status === "running";

  const workerViews = campaignWorkerRows(c, accountRows, campaignEvents);
  const removedCount = workerViews.filter(({ view }) => view.kind === "removed").length;
  const waitingCount = workerViews.filter(({ view }) => view.kind === "waiting").length;
  const activeCount = workerViews.length - removedCount;
  if (!workerViews.length) {
    $("cd-worker-summary").textContent = "";
  } else if (!c.running && c.status === "draft") {
    $("cd-worker-summary").innerHTML =
      `<b>Кампания ещё не запускалась.</b> Выбрано аккаунтов: ${workerViews.length}. ` +
      "Проверка доступа к целевому чату начнётся после запуска.";
  } else if (!c.running) {
    $("cd-worker-summary").innerHTML =
      `<b>Кампания на паузе.</b> Выбрано аккаунтов: ${workerViews.length}.`;
  } else {
    $("cd-worker-summary").innerHTML =
      `<b>В ротации: ${activeCount} из ${workerViews.length}</b> · ` +
      `ожидают: ${waitingCount} · сняты: ${removedCount}. ` +
      "Технически снятый аккаунт можно проверить и вернуть кнопкой в его карточке.";
  }
  $("cd-workers").innerHTML = workerViews.length ? workerViews.map(({ worker: w, view }) => {
    const service = workerServiceView(view, c);
    const last = w.last_attempt;
    const result = last ? invitationResult(last) : null;
    return `<div class="item">
    <div class="item-head"><span class="item-title">${esc(w.label)}</span>
      <span class="badge ${view.badgeClass}">${esc(view.badge)}</span>
      <span class="badge ok">${w.done || 0} приглашено</span>
      ${w.awaiting_confirmation ? `<span class="badge warn">${w.awaiting_confirmation} ожидает подтверждения</span>` : ""}
      ${w.privacy ? `<span class="badge warn">${w.privacy} приватность</span>` : ""}
      <span class="badge ${service.badgeClass} worker-service-status">${service.label}</span></div>
    <div class="item-meta">${esc(view.detail)}${view.stoppedAt
      ? ` · снят ${fmtDateTime(view.stoppedAt)}` : ""}</div>
    ${last ? `<div class="item-meta"><b>Последняя попытка:</b>
      ${esc(last.username ? "@" + last.username : last.user_id)} · ${fmtTime(last.attempted_at)}
      <span class="badge ${result.cls}">${esc(result.label)}</span>
      <div>${esc(result.detail)}</div></div>` : '<div class="item-meta">Завершённых попыток пока нет.</div>'}
    ${view.canRecover ? `<div class="row worker-recovery-row">
      <button class="recover" onclick="recoverCampaignAccount(${Number(w.account_id)}, this)">
        Проверить и вернуть в строй
      </button>
      <span class="hint-inline">Прокси → сессия → права в чате. Интервал сохраняется.</span>
    </div>` : ""}</div>`;
  }).join("")
    : '<p class="hint">Аккаунты не запущены.</p>';

  $("cd-recent").innerHTML = `<thead><tr><th>пользователь</th><th>статус</th>
    <th>аккаунт</th><th>время</th><th>детали</th></tr></thead><tbody>` +
    c.recent.map((t) => { const result = invitationResult(t); return `<tr>
      <td>${t.username ? "@" + esc(t.username) : t.user_id}</td>
      <td><span class="badge ${result.cls}">${esc(result.label)}</span></td>
      <td>${t.account_id || "—"}</td>
      <td>${t.attempted_at ? fmtTime(t.attempted_at) : "—"}</td>
      <td>${esc(result.detail)}</td></tr>`; }).join("") + "</tbody>";
}

window.recoverCampaignAccount = async (accountId, button) => {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Проверяю прокси…";
  try {
    const result = await api(
      `/campaigns/${CURRENT_CAMPAIGN}/accounts/${accountId}/recover`,
      { method: "POST" },
    );
    const latency = result.latency_ms ? ` · ${result.latency_ms} мс` : "";
    toast(result.already_active
      ? "Аккаунт уже находится в ротации"
      : `Аккаунт возвращён в строй${latency}`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.textContent = original;
    await refreshCampaign();
    await loadCampaigns();
  }
};

$("cd-start").onclick = async () => {
  try {
    await api(`/campaigns/${CURRENT_CAMPAIGN}/start`, { method: "POST" });
    toast("Кампания запущена");
  } catch (e) { toast(e.message, true); }
  refreshCampaign();
};

$("cd-preflight").onclick = async () => {
  const button = $("cd-preflight");
  button.disabled = true;
  button.textContent = "Запускаю проверку…";
  try {
    const result = await api(`/campaigns/${CURRENT_CAMPAIGN}/preflight`, { method: "POST" });
    renderCampaignPreflight(result);
    toast("Проверка запущена — приглашения не отправляются");
  } catch (e) {
    toast(e.message, true);
    button.disabled = false;
    button.textContent = "Проверить перед запуском";
  }
  refreshCampaign();
};

$("cd-stop").onclick = async () => {
  await api(`/campaigns/${CURRENT_CAMPAIGN}/stop`, { method: "POST" });
  toast("Останавливаю — воркеры завершат текущую паузу");
  refreshCampaign();
};

$("cd-export").onclick = () => location.href = `/api/campaigns/${CURRENT_CAMPAIGN}/export`;

// ─────────────────────────────────────────────────────── приглашённые

const MOSCOW_DATE_TIME_FORMATTER = new Intl.DateTimeFormat("ru-RU", {
  timeZone: MOSCOW_TIME_ZONE,
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
});
const MOSCOW_DATE_PARTS_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: MOSCOW_TIME_ZONE,
  year: "numeric", month: "2-digit", day: "2-digit",
});
const MOSCOW_MONTH_FORMATTER = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "UTC", month: "long", year: "numeric",
});
const MOSCOW_DAY_FORMATTER = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "UTC", day: "numeric", month: "long", year: "numeric",
});

const fmtDateTime = (ts) => ts
  ? MOSCOW_DATE_TIME_FORMATTER.format(new Date(Number(ts) * 1000))
  : "—";

function moscowDateKey(ts = Date.now() / 1000) {
  const parts = Object.fromEntries(MOSCOW_DATE_PARTS_FORMATTER
    .formatToParts(new Date(Number(ts) * 1000))
    .filter((part) => part.type !== "literal")
    .map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function ensureInvitedCalendarMonth() {
  if (INVITED_CALENDAR_YEAR !== null && INVITED_CALENDAR_MONTH !== null) return;
  const [year, month] = moscowDateKey().split("-").map(Number);
  INVITED_CALENDAR_YEAR = year;
  INVITED_CALENDAR_MONTH = month - 1;
}

function formatCalendarDate(dateKey) {
  const [year, month, day] = dateKey.split("-").map(Number);
  return MOSCOW_DAY_FORMATTER.format(new Date(Date.UTC(year, month - 1, day)));
}

function renderInvitedCalendar() {
  ensureInvitedCalendarMonth();
  const year = INVITED_CALENDAR_YEAR;
  const month = INVITED_CALENDAR_MONTH;
  const counts = new Map();
  INVITED_ROWS.forEach((row) => {
    if (!row.invited_by_app || !Number(row.invited_at)) return;
    const key = moscowDateKey(row.invited_at);
    counts.set(key, (counts.get(key) || 0) + 1);
  });

  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const firstWeekday = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7;
  const monthPrefix = `${year}-${String(month + 1).padStart(2, "0")}-`;
  let monthTotal = 0;
  for (const [key, count] of counts) {
    if (key.startsWith(monthPrefix)) monthTotal += count;
  }

  $("invited-cal-title").textContent = MOSCOW_MONTH_FORMATTER
    .format(new Date(Date.UTC(year, month, 1)));
  const selectedCount = INVITED_SELECTED_DATE ? (counts.get(INVITED_SELECTED_DATE) || 0) : null;
  $("invited-cal-summary").textContent = INVITED_SELECTED_DATE
    ? `${formatCalendarDate(INVITED_SELECTED_DATE)}: приглашено ${selectedCount}. Нажмите на дату ещё раз, чтобы убрать фильтр.`
    : `За этот месяц приглашено: ${monthTotal}`;

  const weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    .map((day) => `<div class="calendar-weekday">${day}</div>`).join("");
  const blanks = Array.from({ length: firstWeekday }, () => '<div class="calendar-empty"></div>').join("");
  const todayKey = moscowDateKey();
  const days = Array.from({ length: daysInMonth }, (_, index) => {
    const day = index + 1;
    const key = `${monthPrefix}${String(day).padStart(2, "0")}`;
    const count = counts.get(key) || 0;
    const classes = ["calendar-day"];
    if (key === todayKey) classes.push("today");
    if (key === INVITED_SELECTED_DATE) classes.push("selected");
    return `<button class="${classes.join(" ")}" data-invited-date="${key}" ` +
      `aria-label="${formatCalendarDate(key)}: приглашено ${count}">` +
      `<span class="calendar-day-number">${day}</span>` +
      `<span class="calendar-day-count${count ? " has-invites" : ""}">${count ? `+${count}` : "—"}</span>` +
      `</button>`;
  }).join("");
  $("invited-calendar").innerHTML = weekdays + blanks + days;
  $("invited-calendar").querySelectorAll("[data-invited-date]").forEach((button) => {
    button.onclick = () => {
      const key = button.dataset.invitedDate;
      INVITED_SELECTED_DATE = INVITED_SELECTED_DATE === key ? null : key;
      renderInvitedCalendar();
      renderInvitedRows();
    };
  });
}

function changeInvitedCalendarMonth(delta) {
  ensureInvitedCalendarMonth();
  const next = new Date(Date.UTC(INVITED_CALENDAR_YEAR, INVITED_CALENDAR_MONTH + delta, 1));
  INVITED_CALENDAR_YEAR = next.getUTCFullYear();
  INVITED_CALENDAR_MONTH = next.getUTCMonth();
  INVITED_SELECTED_DATE = null;
  renderInvitedCalendar();
  renderInvitedRows();
}

function parseCsv(text, delimiter = ";") {
  const rows = [];
  let row = [], field = "", quoted = false;
  const source = String(text || "").replace(/^\uFEFF/, "");
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    if (quoted) {
      if (ch === '"' && source[i + 1] === '"') { field += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === delimiter) { row.push(field); field = ""; }
    else if (ch === "\n") { row.push(field.replace(/\r$/, "")); rows.push(row); row = []; field = ""; }
    else field += ch;
  }
  if (field || row.length) { row.push(field.replace(/\r$/, "")); rows.push(row); }
  if (!rows.length) return [];
  const headers = rows.shift();
  return rows.filter((values) => values.some(Boolean)).map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, values[index] || ""])));
}

function loadSavedInvitedSnapshot() {
  try {
    const snapshot = JSON.parse(localStorage.getItem(INVITED_STORAGE_KEY) || "null");
    return snapshot?.chat_id === INVITED_CHAT_ID ? snapshot : null;
  } catch (e) {
    return null;
  }
}

async function loadAllTargetMembers(chatId) {
  const items = [];
  const limit = 1000;
  for (let offset = 0; ; offset += limit) {
    const page = await api(`/members?chat_id=${chatId}&limit=${limit}&offset=${offset}`);
    items.push(...page.items);
    if (items.length >= page.total || !page.items.length) break;
  }
  return items;
}

async function loadInvitationHistory() {
  const campaigns = (await api("/campaigns"))
    .filter((campaign) => Number(campaign.target_chat_id) === INVITED_CHAT_ID);
  const accountLabels = new Map(ACCOUNTS.map((account) => [Number(account.id), account.label]));
  const invited = new Map();

  await Promise.all(campaigns.map(async (campaign) => {
    const [exportResponse, events] = await Promise.all([
      fetch(`/api/campaigns/${campaign.id}/export`),
      api(`/events?campaign_id=${campaign.id}&limit=100000`),
    ]);
    if (!exportResponse.ok) throw new Error("Не удалось загрузить историю кампании");
    const targets = parseCsv(await exportResponse.text()).filter((target) => target.status === "invited");
    const eventTimes = new Map();
    events.forEach((event) => {
      if (!String(event.message || "").startsWith("Приглашён ")) return;
      const key = String(event.message).slice("Приглашён ".length).replace(/^@/, "").toLowerCase();
      if (!eventTimes.has(key) || Number(event.ts) > Number(eventTimes.get(key).ts)) {
        eventTimes.set(key, event);
      }
    });
    targets.forEach((target) => {
      const userId = String(target.user_id || "");
      const username = String(target.username || "").replace(/^@/, "");
      const event = eventTimes.get((username || userId).toLowerCase());
      const record = {
        user_id: userId,
        username,
        display: target.display || "",
        invited_at: Number(event?.ts || 0),
        account_id: Number(target.account_id || event?.account_id || 0),
        account_label: accountLabels.get(Number(target.account_id || event?.account_id || 0)) || "—",
        campaign_id: campaign.id,
        campaign_name: campaign.name,
      };
      const previous = invited.get(userId);
      if (!previous || record.invited_at >= previous.invited_at) invited.set(userId, record);
    });
  }));
  return invited;
}

function renderInvitedRows() {
  const query = $("invited-search").value.trim().toLowerCase().replace(/^@/, "");
  const filter = $("invited-filter").value;
  const rows = INVITED_ROWS.filter((row) => {
    if (INVITED_SELECTED_DATE && moscowDateKey(row.invited_at) !== INVITED_SELECTED_DATE) return false;
    if (filter === "current" && !row.is_member) return false;
    if (filter === "invited" && !row.invited_by_app) return false;
    if (filter === "left" && row.member_status !== "left") return false;
    if (!query) return true;
    return [row.user_id, row.username, row.display, row.account_label, row.campaign_name]
      .some((value) => String(value || "").toLowerCase().includes(query));
  });

  $("invited-table").innerHTML = `<thead><tr><th>Пользователь</th><th>Статус</th>
    <th>Приглашён</th><th>Аккаунт</th><th>Кампания</th></tr></thead><tbody>` +
    rows.map((row) => `<tr>
      <td>${row.username ? "@" + esc(row.username) : esc(row.user_id)}
        ${row.display ? `<br><span class="hint-inline">${esc(row.display)}</span>` : ""}</td>
      <td>${row.member_status === "left"
        ? `<span class="badge err">вышел</span>${row.left_at
          ? `<br><span class="hint-inline">обнаружено ${fmtDateTime(row.left_at)}</span>` : ""}`
        : row.is_member
          ? '<span class="badge ok">в чате</span>'
          : '<span class="badge warn">не проверен</span>'}</td>
      <td>${row.invited_by_app ? fmtDateTime(row.invited_at) : "был в чате ранее"}</td>
      <td>${row.invited_by_app ? esc(row.account_label) : "—"}</td>
      <td>${row.invited_by_app ? esc(row.campaign_name) : "—"}</td>
    </tr>`).join("") + "</tbody>";
  $("invited-count").textContent = INVITED_SELECTED_DATE
    ? `${formatCalendarDate(INVITED_SELECTED_DATE)}: показано ${rows.length} из ${INVITED_ROWS.length}`
    : `Показано ${rows.length} из ${INVITED_ROWS.length}`;
}

async function loadInvitedTab() {
  try {
    await loadAccounts();
    const select = $("invited-account");
    const keep = select.value;
    select.innerHTML = ACCOUNTS.filter((account) => account.status === "authorized" && account.can_parse)
      .map((account) => `<option value="${account.id}">${esc(account.label)}</option>`).join("")
      || '<option value="">Нет доступных аккаунтов</option>';
    if (keep && [...select.options].some((option) => option.value === keep)) select.value = keep;

    const [invited, snapshot] = await Promise.all([
      loadInvitationHistory(),
      Promise.resolve(loadSavedInvitedSnapshot()),
    ]);
    const trackedMembers = snapshot?.members || [];
    const currentMembers = trackedMembers.filter((member) => member.is_member !== false);
    const trackedById = new Map(trackedMembers.map((member) => [String(member.user_id), member]));
    const trackedByUsername = new Map(trackedMembers
      .filter((member) => member.username)
      .map((member) => [String(member.username).toLowerCase(), member]));
    const combined = new Map();

    trackedMembers.forEach((member) => combined.set(String(member.user_id), {
      ...member,
      is_member: member.is_member !== false,
      member_status: member.is_member === false ? "left" : "current",
      invited_by_app: false,
    }));
    invited.forEach((record, userId) => {
      const member = trackedById.get(String(userId))
        || trackedByUsername.get(String(record.username || "").toLowerCase());
      const mergedUserId = String(member?.user_id || userId);
      combined.set(mergedUserId, {
        ...(member || {}),
        ...record,
        user_id: mergedUserId,
        username: member?.username || record.username,
        display: member?.display || record.display,
        is_member: Boolean(member && member.is_member !== false),
        member_status: snapshot
          ? (member && member.is_member !== false ? "current" : "left")
          : "unknown",
        invited_by_app: true,
      });
    });
    INVITED_ROWS = [...combined.values()].sort((a, b) => {
      if (a.member_status !== b.member_status) return a.member_status === "left" ? 1 : -1;
      return Number(b.invited_at || 0) - Number(a.invited_at || 0);
    });

    const invitedCount = [...invited.values()].length;
    const currentInvited = INVITED_ROWS.filter((row) => row.invited_by_app && row.is_member).length;
    const leftCount = INVITED_ROWS.filter((row) => row.member_status === "left").length;
    $("invited-stats").innerHTML = [
      [currentMembers.length, "сейчас в чате"],
      [invitedCount, "приглашено программой"],
      [currentInvited, "приглашённые остались"],
      [snapshot ? leftCount : "—", "вышли"],
    ].map(([value, label]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`).join("");
    $("invited-sync-status").textContent = snapshot
      ? `Последняя проверка: ${fmtDateTime(snapshot.synced_at)}`
      : "Нажмите «Обновить состав» для первого снимка";
    renderInvitedCalendar();
    renderInvitedRows();
  } catch (e) {
    toast(e.message, true);
    $("invited-sync-status").textContent = "Не удалось загрузить данные";
  }
}

$("invited-sync").onclick = async () => {
  const accountId = Number($("invited-account").value);
  if (!accountId) return toast("Выберите авторизованный аккаунт", true);
  const button = $("invited-sync");
  const startedAt = Math.floor(Date.now() / 1000) - 2;
  button.disabled = true;
  button.textContent = "Проверяю состав…";
  $("invited-sync-status").textContent = "Telegram загружает полный список участников";
  try {
    const result = await api("/campaigns/sync-target", {
      method: "POST",
      body: { account_id: accountId, target_chat: INVITED_TARGET },
    });
    const stored = await loadAllTargetMembers(result.chat_id);
    const current = stored.filter((member) => Number(member.updated_at || 0) >= startedAt)
      .map((member) => ({
        user_id: String(member.user_id), username: member.username || "",
        display: [member.first_name, member.last_name].filter(Boolean).join(" "),
      }));
    if (!current.length && Number(result.total) > 0) {
      throw new Error("Telegram не вернул полный состав; предыдущий снимок сохранён");
    }
    const previousSnapshot = loadSavedInvitedSnapshot();
    const previousCurrent = (previousSnapshot?.members || [])
      .filter((member) => member.is_member !== false).length;
    const referenceCount = Math.max(previousCurrent, Number(result.total) || 0);
    if (referenceCount >= 10 && current.length < Math.floor(referenceCount * 0.7)) {
      throw new Error("Telegram вернул подозрительно неполный список; предыдущий снимок сохранён");
    }
    const syncedAt = Math.floor(Date.now() / 1000);
    const history = new Map((previousSnapshot?.members || [])
      .map((member) => [String(member.user_id), { ...member }]));
    const currentIds = new Set();
    current.forEach((member) => {
      const userId = String(member.user_id);
      currentIds.add(userId);
      const previous = history.get(userId) || {};
      history.set(userId, {
        ...previous, ...member, is_member: true,
        first_seen_at: previous.first_seen_at || syncedAt,
        last_seen_at: syncedAt,
        left_at: null,
      });
    });
    history.forEach((member, userId) => {
      if (!currentIds.has(userId) && member.is_member !== false) {
        history.set(userId, { ...member, is_member: false, left_at: syncedAt });
      }
    });
    localStorage.setItem(INVITED_STORAGE_KEY, JSON.stringify({
      chat_id: Number(result.chat_id), synced_at: syncedAt, members: [...history.values()],
    }));
    toast(`Состав обновлён: ${current.length} участников`);
    await loadInvitedTab();
  } catch (e) {
    toast(e.message, true);
    $("invited-sync-status").textContent = "Проверка не выполнена; предыдущие данные сохранены";
  } finally {
    button.disabled = false;
    button.textContent = "Обновить состав";
  }
};

$("invited-search").oninput = renderInvitedRows;
$("invited-filter").onchange = renderInvitedRows;
$("invited-cal-prev").onclick = () => changeInvitedCalendarMonth(-1);
$("invited-cal-next").onclick = () => changeInvitedCalendarMonth(1);
$("invited-cal-today").onclick = () => {
  const [year, month] = moscowDateKey().split("-").map(Number);
  INVITED_CALENDAR_YEAR = year;
  INVITED_CALENDAR_MONTH = month - 1;
  INVITED_SELECTED_DATE = null;
  renderInvitedCalendar();
  renderInvitedRows();
};

$("invited-export").onclick = () => {
  const quote = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const lines = [["user_id", "username", "display", "status", "left_detected_at",
    "invited_at", "account", "campaign"],
    ...INVITED_ROWS.map((row) => [row.user_id, row.username || "", row.display || "",
      row.member_status, row.left_at ? fmtDateTime(row.left_at) : "",
      row.invited_at ? fmtDateTime(row.invited_at) : "",
      row.account_label || "", row.campaign_name || ""])];
  const blob = new Blob(["\uFEFF" + lines.map((line) => line.map(quote).join(";")).join("\n")],
    { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "skyptop_invited.csv";
  link.click();
  URL.revokeObjectURL(link.href);
};

// ─────────────────────────────────────────────────────── лог

async function loadLog() {
  const events = await api("/events?limit=200");
  $("log-list").innerHTML = events.map((e) =>
    `<div class="${e.level}"><span class="t">${fmtTime(e.ts)}</span>${esc(e.message)}</div>`).join("");
}

// ─────────────────────────────────────────────────────── старт

loadSettings();
loadAccounts();
loadJobs();

setInterval(() => {
  const active = document.querySelector(".tab.active").dataset.tab;
  if (active === "accounts") loadAccounts();
  if (active === "parse") loadJobs();
  if (active === "invite") { refreshCampaign(); loadCampaigns(); }
  if (active === "log") loadLog();
}, 4000);
