(() => {
  const PAGE_META = {
    dialogs: { title: "Диалоги", sub: "Живая смена. Архив и булавки рядом" },
    desk: { title: "Стол", sub: "Кто ждёт, поиск по переписке, тихие чаты" },
    mail: { title: "Рассылка", sub: "Первое сообщение бывшим гостям" },
    queue: { title: "Очередь", sub: "Лимиты и первые сообщения" },
    logs: { title: "Журнал", sub: "События системы в реальном времени" },
    controls: { title: "Управление", sub: "Рассылка, стоп-лист, закрепление" },
    prefs: { title: "Мои настройки", sub: "Профиль, шаблоны, тема и уведомления" },
    users: { title: "Пользователи", sub: "Доступ в панель и распределение" },
    settings: { title: "Настройки", sub: "Лимиты, доли и шаблоны ответов" },
    accounts: { title: "Аккаунты", sub: "SIM компании для Telegram-бота" },
  };

  const LANE_LABELS = {
    hot: "Срочно",
    work: "В работе",
    later: "Позже",
    deal: "Сделка",
    lost: "Не вышло",
    issue: "Проблема",
  };

  const STAGE_LABELS = {
    greeting: "приветствие",
    await_intent: "уточняем задачу",
    await_dates: "ждём даты",
    await_guests: "ждём гостей",
    await_district: "ждём район",
    await_returning: "повторный гость",
    await_favorite: "любимый вариант",
    handed_off: "у менеджера",
  };

  function stageLabel(step) {
    const raw = String(step || "").trim();
    if (!raw) return { label: "—", title: "" };
    return { label: STAGE_LABELS[raw] || raw, title: raw };
  }

  function fmtQuiet(sec) {
    const n = Math.max(0, Math.floor(Number(sec) || 0));
    if (!n) return "—";
    const h = Math.floor(n / 3600);
    const m = Math.floor((n % 3600) / 60);
    const s = n % 60;
    if (h > 0) return `${h}ч ${String(m).padStart(2, "0")}м`;
    if (m > 0) return `${m}м ${String(s).padStart(2, "0")}с`;
    return `${s}с`;
  }

  function toLocalDatetimeValue(ts) {
    const t = Number(ts) || 0;
    if (!t) return "";
    const d = new Date(t * 1000);
    if (Number.isNaN(d.getTime())) return "";
    const pad = (x) => String(x).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  const POLL_MS = 10000;
  const state = {
    user: null,
    csrf: "",
    page: "dialogs",
    dialogs: [],
    chatId: "",
    dialog: null,
    messages: [],
    ws: null,
    theme: localStorage.getItem("home24_theme") || "dark",
    demo: false,
    unread: 0,
    settings: null,
    dialogFilter: "",
    dialogScope: localStorage.getItem("home24_dialog_scope") || "mine",
    lane: localStorage.getItem("home24_dialog_lane") || "",
    outcome: {},
    queueFilter: "",
    usersFilter: "",
    usersCache: [],
    queueCache: [],
    openSeq: 0,
    dialogUnread: {},
    _inflight: {},
    _pollTimer: null,
    logTechnical: localStorage.getItem("home24_log_technical") === "1",
    logFollow: true,
    templates: [],
    tplCategories: [],
    tplCatFilter: "",
    tplQuery: "",
    tplOpen: false,
    prefs: {
      signature: "",
      theme: "dark",
      notify_sound: true,
      notify_browser: false,
      notify_toast: true,
      composer_enter: "send",
      font_size: "md",
      compact_chat: false,
      dialog_filter: "mine",
    },
  };

  let audioCtx = null;
  function beep() {
    if (state.prefs && state.prefs.notify_sound === false) return;
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.type = "sine";
      o.frequency.value = 880;
      g.gain.value = 0.04;
      o.connect(g); g.connect(audioCtx.destination);
      o.start();
      g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.25);
      o.stop(audioCtx.currentTime + 0.26);
    } catch {}
  }

  function toast(title, body, level) {
    if (state.prefs && state.prefs.notify_toast === false) return;
    const host = $("#toastHost");
    if (!host) return;
    const el = document.createElement("div");
    el.className = `toast ${level === "warn" || level === "error" ? (level === "error" ? "bad" : "warn") : ""}`;
    el.innerHTML = `<div class="t">${escapeHtml(title)}</div><div class="muted">${escapeHtml(body || "")}</div>`;
    host.appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  function notifyBrowser(title, body) {
    if (!(state.prefs && state.prefs.notify_browser)) return;
    try {
      if (!("Notification" in window)) return;
      if (Notification.permission === "granted") {
        new Notification(title || "Home24", { body: body || "", silent: true });
      } else if (Notification.permission === "default") {
        Notification.requestPermission();
      }
    } catch {}
  }

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];
  /** Safe bind — never throw if element missing (would abort the rest of the script). */
  function on(sel, event, fn) {
    const el = typeof sel === "string" ? $(sel) : sel;
    if (!el) return null;
    el.addEventListener(event, fn);
    return el;
  }
  function setClick(sel, fn) {
    const el = typeof sel === "string" ? $(sel) : sel;
    if (!el) return null;
    el.onclick = fn;
    return el;
  }

  function draftKey() {
    const u = (state.user && state.user.username) || "anon";
    return `home24_drafts_${u}`;
  }
  function loadDraftMap() {
    try {
      return JSON.parse(localStorage.getItem(draftKey()) || "{}") || {};
    } catch {
      return {};
    }
  }
  function saveDraftMap(map) {
    try {
      localStorage.setItem(draftKey(), JSON.stringify(map));
    } catch {}
  }
  function getDraft(chatId) {
    if (!chatId) return "";
    return String(loadDraftMap()[chatId] || "");
  }
  function setDraft(chatId, text) {
    if (!chatId) return;
    const map = loadDraftMap();
    const t = String(text || "");
    if (t) map[chatId] = t;
    else delete map[chatId];
    saveDraftMap(map);
  }
  function clearDraft(chatId) {
    setDraft(chatId, "");
  }
  function persistCurrentDraft() {
    const ta = $("#replyText");
    if (!ta || !state.chatId) return;
    setDraft(state.chatId, ta.value);
  }
  function applyDraftToComposer(chatId) {
    const ta = $("#replyText");
    if (!ta) return;
    ta.value = getDraft(chatId);
    resizeComposer();
    updateCharCount();
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (opts.method && opts.method !== "GET") {
      headers["X-CSRF-Token"] = state.csrf;
    }
    const r = await fetch(path, { ...opts, headers, credentials: "same-origin" });
    if (r.status === 401) {
      location.href = "/";
      throw new Error("auth");
    }
    const data = await r.json().catch(() => ({}));
    if (r.status === 403 && data.must_change_password) {
      showPwChange();
      throw new Error("must_change_password");
    }
    if (!r.ok) throw new Error(data.error || r.statusText);
    return data;
  }

  function showPwChange() {
    $("#appShell").classList.add("hidden");
    $("#pwShell").classList.remove("hidden");
  }
  function showApp() {
    $("#pwShell").classList.add("hidden");
    $("#appShell").classList.remove("hidden");
  }

  function resolveTheme(t) {
    const mode = t || "dark";
    if (mode === "system") {
      try {
        return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
      } catch {
        return "dark";
      }
    }
    return mode === "light" ? "light" : "dark";
  }

  function setTheme(t) {
    state.theme = t || "dark";
    document.documentElement.setAttribute("data-theme", resolveTheme(state.theme));
    localStorage.setItem("home24_theme", state.theme);
  }

  function applyPrefs(prefs) {
    state.prefs = Object.assign({}, state.prefs, prefs || {});
    setTheme(state.prefs.theme || state.theme);
    document.documentElement.setAttribute("data-font", state.prefs.font_size || "md");
    document.documentElement.setAttribute("data-compact", state.prefs.compact_chat ? "1" : "0");
    if (state.prefs.dialog_filter) {
      state.dialogScope = state.prefs.dialog_filter;
      localStorage.setItem("home24_dialog_scope", state.dialogScope);
    }
    syncDialogFilterBar();
    const hint = $(".composer-hint");
    if (hint) {
      hint.textContent = state.prefs.composer_enter === "newline"
        ? "Ctrl+Enter — отправить · Enter — новая строка · / — шаблоны"
        : "Enter — отправить · Shift+Enter — новая строка · / — шаблоны";
    }
  }

  function syncDialogFilterBar() {
    const bar = $("#dialogFilterBar");
    if (!bar) return;
    bar.querySelectorAll("[data-dfilter]").forEach((b) => {
      b.classList.toggle("active", b.dataset.dfilter === state.dialogScope);
    });
  }

  function setSideCollapsed(on) {
    const app = $("#appShell");
    if (!app) return;
    app.classList.toggle("side-collapsed", !!on);
    localStorage.setItem("home24_side_collapsed", on ? "1" : "0");
  }

  function setDrawer(open) {
    const app = $("#appShell");
    const bd = $("#sideBackdrop");
    if (!app) return;
    app.classList.toggle("drawer-open", !!open);
    if (bd) {
      if (open) bd.removeAttribute("hidden");
      else bd.setAttribute("hidden", "");
    }
  }

  function syncNavActive(page) {
    $$(".nav button[data-page], .bottom-nav button[data-page], .shell-nav button[data-page]").forEach((b) => {
      const p = b.dataset.page;
      if (p === "more") return;
      b.classList.toggle("active", p === page);
    });
  }

  function navTo(page) {
    if (!PAGE_META[page]) return;
    if (state.page === "dialogs") persistCurrentDraft();
    state.page = page;
    syncNavActive(page);
    $$("[data-view]").forEach((el) => el.classList.toggle("hidden", el.dataset.view !== page));
    const meta = PAGE_META[page];
    $("#pageTitle").textContent = meta.title;
    const sub = $("#pageSub");
    if (sub) sub.textContent = meta.sub;
    setDrawer(false);
    if (page === "dialogs") loadDialogs();
    if (page === "desk") loadDesk();
    if (page === "mail") loadMail();
    if (page === "queue") loadQueue();
    if (page === "logs") loadLogs();
    if (page === "controls") loadControls();
    if (page === "users") loadUsers();
    if (page === "settings") loadSettings();
    if (page === "prefs") loadPrefsPage();
    if (page === "accounts") {
      refreshStats();
      loadAccountsStatus();
      const frame = $("#accountsFrame");
      if (frame && state.user && state.user.is_admin) {
        const want = frame.dataset.src || "/accounts/";
        if (!frame.src || frame.src === "about:blank" || frame.getAttribute("src") === "about:blank") {
          frame.src = want;
        }
      }
    }
  }

  async function loadAccountsStatus() {
    const banner = $("#accountsBanner");
    const list = $("#accountsStatusList");
    if (!banner && !list) return;
    try {
      const data = await api("/api/tg-accounts");
      const accounts = data.accounts || [];
      const revoked = accounts.filter((a) => a.status === "revoked" || a.revoked);
      const paused = accounts.filter((a) => a.status === "restricted" || a.status === "paused");
      if (banner) {
        if (revoked.length) {
          banner.classList.remove("hidden");
          banner.innerHTML = `<strong>Сессия отозвана</strong> — ${revoked.map((a) =>
            `[${escapeHtml(a.id)}] ${escapeHtml(a.status_note || "нужен повторный вход")}`
          ).join(" · ")}. Войдите снова ниже. Панель продолжает работать.`;
        } else {
          banner.classList.add("hidden");
          banner.textContent = "";
        }
      }
      if (list) {
        list.innerHTML = accounts.map((a) => {
          const st = a.status === "revoked" ? "bad"
            : (a.status === "restricted" || a.status === "paused") ? "warn"
            : a.quiet_active ? "warn"
            : a.has_session ? "ok" : "muted";
          const label = a.status === "revoked" ? "отозвана"
            : a.status === "restricted" ? "ограничен"
            : a.status === "paused" ? "пауза"
            : a.has_session ? "ok" : "нет сессии";
          const quiet = a.quiet_active
            ? `<span class="status warn">${escapeHtml(a.quiet_label || "тишина outreach")}</span>`
            : "";
          return `<div class="acc-row ${a.status === "revoked" ? "paused" : ""}">
            <strong>${escapeHtml(a.label || a.id)}</strong>
            <span class="pill">${escapeHtml(a.id)}${a.is_main ? " · main" : ""}</span>
            <span class="status ${st}">${label}</span>
            ${quiet}
            <span class="muted">${escapeHtml(a.phone || "—")} · менеджер ${escapeHtml(a.manager_id || "общий")}</span>
            ${a.status_note ? `<span class="muted">${escapeHtml(a.status_note)}</span>` : ""}
          </div>`;
        }).join("") || `<div class="muted">Нет слотов</div>`;
      }
      if (revoked.length || paused.length) {
        /* keep toast sparse — banner is enough on the page */
      }
    } catch (err) {
      if (banner) {
        banner.classList.remove("hidden");
        banner.textContent = err.message || "Не удалось загрузить аккаунты";
      }
    }
  }

  async function boot() {
    setTheme(state.theme);
    setDrawer(false);
    const layout = document.querySelector(".dialogs-layout");
    if (layout && localStorage.getItem("home24_list_hidden") === "1") {
      layout.classList.add("list-hidden");
    }
    try {
      const me = await api("/api/me");
      state.user = me.user;
      state.csrf = me.csrf;
      state.demo = !!me.demo;
      $("#userPill").textContent = `${me.user.display_name} · ${me.user.role}`;
      $("#demoPill").classList.add("hidden");
      if (me.user.is_admin) {
        $("#navUsers").classList.remove("hidden");
        $("#navSettings").classList.remove("hidden");
        $("#navAccounts").classList.remove("hidden");
        const deskNav = $("#navDesk");
        if (deskNav) deskNav.classList.remove("hidden");
        const shellDesk = $("#shellDesk");
        if (shellDesk) shellDesk.classList.remove("hidden");
      }
      // Мои настройки — всем (менеджерам и админу для личных prefs)
      $("#navPrefs") && $("#navPrefs").classList.remove("hidden");
      if (me.user.must_change_password) {
        showPwChange();
        return;
      }
      try {
        const prefRes = await api("/api/prefs");
        applyPrefs(prefRes.prefs || {});
      } catch {}
      showApp();
      connectWs();
      startFallbackPoll();
      navTo("dialogs");
      refreshStats();
      pollNotify();
      // шаблоны сразу при старте (не ждать кнопку) — иначе на Windows Edge
      // после открытия диалога /api/templates мог никогда не вызываться
      loadTemplates().catch(() => {});
    } catch {
      location.href = "/";
    }
  }

  function startFallbackPoll() {
    if (state._pollTimer) clearInterval(state._pollTimer);
    state._pollTimer = setInterval(() => {
      if (document.hidden) return;
      // WS — основной канал; опрос раз в 10с как запасной
      pollNotify();
      if (state.page === "dialogs") loadDialogs(true);
      else if (state.page === "queue") loadQueue();
      else if (state.page === "logs") loadLogs();
      else if (state.page === "accounts") loadAccountsStatus();
      else refreshStats();
    }, POLL_MS);
  }

  function connectWs() {
    if (state.ws) try { state.ws.close(); } catch {}
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    state.ws = ws;
    ws.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      if (data.kind === "message") {
        const cid = data.chat_id;
        if (cid && cid === state.chatId) {
          state.messages.push(data);
          renderMessages();
        } else if (data.role === "guest" && cid) {
          state.dialogUnread[cid] = (state.dialogUnread[cid] || 0) + 1;
          state.unread = (state.unread || 0) + 1;
          updateBell();
          beep();
          toast("Новое сообщение", data.text || "", "info");
          notifyBrowser("Новое сообщение", data.text || "");
        }
        loadDialogs(true);
        refreshStats();
      }
      if (data.kind === "notify" || data.kind === "account_warning") {
        state.unread = (state.unread || 0) + 1;
        updateBell();
        beep();
        toast(data.title || data.message || "Уведомление", data.body || data.message || "", data.level || "warn");
        if (state.page === "accounts" || data.kind === "account_warning") loadAccountsStatus();
      }
      if (data.kind === "log" && state.page === "logs") appendLog(data);
      if (data.kind === "queue") {
        if (state.page === "queue") loadQueue();
        else refreshStats();
      }
      if (data.kind === "session") {
        refreshStats();
        if (state.page === "queue") renderQueue();
      }
      if (data.kind === "takeover" && data.chat_id === state.chatId) {
        openChat(state.chatId, { soft: true });
      }
    };
    ws.onclose = () => {
      if (state.user && !state.user.must_change_password) setTimeout(connectWs, 2000);
    };
  }

  function initials(name) {
    const parts = String(name || "?").replace(/DEMO\s*[·•]\s*/i, "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  function avatarHue(id) {
    let h = 0;
    const s = String(id || "");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return h;
  }

  function filteredDialogs() {
    const q = (state.dialogFilter || "").trim().toLowerCase();
    const mid = (state.user && state.user.manager_id) || "";
    let list = state.dialogs || [];
    const scope = state.dialogScope || "mine";
    if (scope === "mine" && mid) {
      list = list.filter((d) => (d.manager_id || "") === mid);
    } else if (scope === "needs_reply") {
      list = list.filter((d) => {
        const last = d.last_message;
        if (last && last.role === "guest") return true;
        if (state.dialogUnread[d.chat_id]) return true;
        return false;
      });
    } else if (scope === "bot") {
      list = list.filter((d) => !d.handed_off);
    } else if (scope === "manager") {
      list = list.filter((d) => !!d.handed_off);
    } else if (scope === "pinned") {
      list = list.filter((d) => !!d.pinned);
    }
    if (state.lane) {
      list = list.filter((d) => (d.lane || "work") === state.lane);
    }
    if (!q) return list;
    return list.filter((d) => {
      const blob = [
        d.name, d.contact_name, d.chat_id, d.manager_id, d.phone, d.step, d.tg_status,
        d.dates, d.guests, d.district, d.favorite, d.brief, d.tone, d.lane,
        d.last_message && d.last_message.text,
      ].filter(Boolean).join(" ").toLowerCase();
      return blob.includes(q);
    });
  }

  function guestFacts(d) {
    if (!d) return [];
    const bits = [];
    if (d.dates) bits.push(String(d.dates));
    if (d.guests) bits.push(`${d.guests} гост.`);
    if (d.district) bits.push(String(d.district));
    if (d.favorite) bits.push(String(d.favorite));
    return bits;
  }

  function relTime(ts) {
    const t = Number(ts) || 0;
    if (!t) return "";
    const sec = Math.max(0, Date.now() / 1000 - t);
    if (sec < 60) return "сейчас";
    if (sec < 3600) return `${Math.floor(sec / 60)} мин`;
    if (sec < 86400) return `${Math.floor(sec / 3600)} ч`;
    return new Date(t * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
  }

  function guestCardText(d) {
    const name = (d && (d.name || d.contact_name)) || "Гость";
    const phone = prettyPhone(d && d.phone);
    const lines = [name];
    if (phone) lines.push(phone);
    guestFacts(d).forEach((x) => lines.push(x));
    const stage = stageLabel(d && d.step);
    if (stage.label && stage.label !== "—") lines.push(stage.label);
    lines.push(d && d.handed_off ? "на менеджере" : "ведёт бот");
    return lines.join("\n");
  }

  async function copyText(text, title) {
    const value = String(text || "").trim();
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      toast(title || "Скопировано", value.split("\n")[0], "info");
    } catch {
      toast(title || "Карточка", value.split("\n").slice(0, 3).join(" · "), "info");
    }
  }

  function toneOf(d) {
    const t = d && d.tone;
    if (t === "ready" || t === "work" || t === "done") return t;
    return "work";
  }

  function renderLaneStats() {
    const box = $("#laneStats");
    if (!box) return;
    const stats = state.outcome || {};
    const order = ["deal", "lost", "later", "issue", "hot", "work"];
    box.innerHTML = order.map((key) => {
      const n = Number(stats[key] || 0);
      const on = state.lane === key ? " active" : "";
      return `<button type="button" class="lane-stat lane-${key}${on}" data-lane="${key}">
        <span class="n">${n}</span>
        <span class="k">${escapeHtml(LANE_LABELS[key] || key)}</span>
      </button>`;
    }).join("");
    box.querySelectorAll("[data-lane]").forEach((el) => {
      el.onclick = () => setLane(el.dataset.lane === state.lane ? "" : el.dataset.lane);
    });
  }

  function setLane(lane) {
    state.lane = lane || "";
    localStorage.setItem("home24_dialog_lane", state.lane);
    const bar = $("#laneBar");
    if (bar) {
      bar.querySelectorAll("[data-lane]").forEach((b) => {
        b.classList.toggle("active", (b.dataset.lane || "") === state.lane);
      });
    }
    renderDialogList();
  }

  function renderReadyStrip() {
    const box = $("#readyStrip");
    if (!box) return;
    const ready = (state.dialogs || []).filter((d) => toneOf(d) === "ready");
    if (!ready.length || state.dialogScope === "archive") {
      box.innerHTML = "";
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");
    box.innerHTML = `<div class="ready-strip-label">Договорились</div>` + ready.map((d) => {
      const name = d.name || d.contact_name || d.chat_id;
      const brief = d.brief || guestFacts(d).join(" · ");
      return `<button type="button" class="ready-chip" data-id="${escapeHtml(d.chat_id)}">
        <span class="ready-name">${escapeHtml(name)}</span>
        ${brief ? `<span class="ready-brief">${escapeHtml(brief)}</span>` : ""}
      </button>`;
    }).join("");
    box.querySelectorAll(".ready-chip").forEach((el) => {
      el.onclick = () => openChat(el.dataset.id);
    });
  }

  function renderDialogList() {
    const box = $("#dialogList");
    renderReadyStrip();
    renderLaneStats();
    if (!box) return;
    const items = filteredDialogs();
    if (!items.length) {
      box.innerHTML = `<div class="empty-state">
        <div class="empty-icon"></div>
        <div class="empty-title">${state.dialogs.length ? "Ничего не найдено" : "Пока нет диалогов"}</div>
        <div class="empty-sub">${state.dialogs.length ? "Сбросьте поиск или выберите другой фильтр" : "Клиенты появятся после первых сообщений"}</div>
      </div>`;
      return;
    }
    box.innerHTML = items.map((d) => {
      const last = d.last_message ? d.last_message.text : "нет сообщений";
      const stage = stageLabel(d.step);
      const take = d.handed_off ? "менеджер" : "бот";
      const tg = d.tg_status || (d.context && d.context.tg_status) || "";
      const missing = tg === "нет в Telegram";
      const name = d.name || d.contact_name || d.chat_id;
      const phone = prettyPhone(d.phone);
      const unread = state.dialogUnread[d.chat_id] || 0;
      const hue = avatarHue(d.chat_id || name);
      const facts = d.brief || guestFacts(d).join(" · ");
      const when = relTime((d.last_message && d.last_message.created_at) || d.updated_at);
      const tone = toneOf(d);
      const toneLabel = tone === "ready" ? "срочно" : tone === "done" ? "закрыт" : "в работе";
      const lane = d.lane || "work";
      const laneLabel = LANE_LABELS[lane] || lane;
      return `<div class="dialog-item tone-${tone} ${d.chat_id === state.chatId ? "active" : ""} ${unread ? "has-unread" : ""}" data-id="${escapeHtml(d.chat_id)}" role="button" tabindex="0">
        <div class="av" style="--av-h:${hue}">${escapeHtml(initials(name))}</div>
        <div class="dialog-body">
          <div class="dialog-top">
            <div class="t">${escapeHtml(name)}</div>
            ${when ? `<span class="when">${escapeHtml(when)}</span>` : ""}
            ${unread ? `<span class="unread-badge">${unread > 99 ? "99+" : unread}</span>` : ""}
          </div>
          ${phone && phone !== name ? `<div class="sub">${escapeHtml(phone)}</div>` : ""}
          ${facts ? `<div class="sub facts">${escapeHtml(facts)}</div>` : ""}
          <div class="m">${escapeHtml(last)}</div>
          <div class="dialog-tags">
            <span class="tag tag-${tone}">${toneLabel}</span>
            <span class="tag tag-lane tag-lane-${escapeHtml(lane)}">${escapeHtml(laneLabel)}</span>
            <span class="tag" title="${escapeHtml(stage.title)}">${escapeHtml(stage.label)}</span>
            <span class="tag ${d.handed_off ? "tag-mgr" : "tag-bot"}">${take}</span>
            ${(d.context && d.context.tg_account) ? `<span class="tag">${escapeHtml(d.context.tg_account)}</span>` : ""}
            ${d.pinned ? `<span class="tag tag-pin">булавка</span>` : ""}
            ${d.note ? `<span class="tag">заметка</span>` : ""}
            ${missing ? `<span class="tag tag-bad">нет в TG</span>` : ""}
            <span class="tag muted-tag">${escapeHtml(d.manager_id || "—")}</span>
          </div>
        </div>
      </div>`;
    }).join("");
    box.querySelectorAll(".dialog-item").forEach((el) => {
      el.onclick = () => openChat(el.dataset.id);
      el.onkeydown = (e) => {
        if (e.[REDACTED] "Enter" || e.[REDACTED] " ") {
          e.preventDefault();
          openChat(el.dataset.id);
        }
      };
    });
  }

  async function loadDialogs(soft) {
    const view = state.dialogScope === "archive" ? "archive" : "live";
    const data = await api("/api/dialogs?view=" + view);
    state.dialogs = data.dialogs || [];
    state.outcome = data.stats || {};
    renderDialogList();
    refreshStats();
    if (!soft && !state.chatId && state.dialogs[0]) openChat(state.dialogs[0].chat_id);
  }

  function applyChatHeader(d, chatId) {
    const name = d.name || d.contact_name || chatId;
    $("#chatTitle").textContent = name;
    const av = $("#chatAvatar");
    if (av) {
      av.textContent = initials(name);
      av.style.setProperty("--av-h", String(avatarHue(chatId || name)));
    }
    const stage = stageLabel(d.step);
    $("#chatStage").textContent = stage.label;
    $("#chatStage").title = stage.title || "";
    $("#chatStage").dataset.kind = "stage";
    $("#chatNext").textContent = (d.context && d.context.next) || "по скрипту";
    $("#chatMgr").textContent = d.manager_id || "—";
    const tgRaw = (d.context && d.context.tg_status) || d.tg_status || "";
    const tgLabel = {
      "ok": "в Telegram",
      "уже в контактах": "уже в контактах",
      "есть диалог": "есть диалог",
      "нет в Telegram": "нет в Telegram",
    }[tgRaw] || (tgRaw || "не проверен");
    const tgEl = $("#chatTg");
    tgEl.textContent = tgLabel;
    tgEl.classList.toggle("warn", tgRaw === "нет в Telegram");
    tgEl.classList.toggle("ok", tgRaw === "ok" || tgRaw === "уже в контактах" || tgRaw === "есть диалог");
    tgEl.title = tgRaw || "";
    const taken = !!d.handed_off;
    $("#btnTake").classList.toggle("hidden", taken);
    $("#btnReturn").classList.toggle("hidden", !taken);
    const pinBtn = $("#btnPin");
    if (pinBtn) pinBtn.textContent = d.pinned ? "Снять булавку" : "Булавка";
    const archBtn = $("#btnArchive");
    if (archBtn) archBtn.textContent = d.archived ? "Вернуть в смену" : "В архив";
    const note = $("#chatNote");
    if (note && document.activeElement !== note) note.value = d.note || "";
    const takeEl = $("#takeState");
    takeEl.textContent = taken ? "На менеджере" : "Ведёт бот";
    takeEl.classList.toggle("pill-mgr", taken);
    takeEl.classList.toggle("pill-bot", !taken);
    const brief = $("#chatBrief");
    if (brief) {
      const phone = prettyPhone(d.phone);
      const facts = d.brief ? [d.brief] : guestFacts(d);
      const tone = toneOf(d);
      const phoneBtn = phone
        ? `<button type="button" class="brief-chip" data-copy="${escapeHtml(phone)}">${escapeHtml(phone)}</button>`
        : "";
      const factHtml = facts.map((f) => `<span class="brief-chip">${escapeHtml(f)}</span>`).join("");
      const agreed = tone === "ready"
        ? `<span class="brief-flag brief-flag-ready">Договорились</span>`
        : "";
      const laneName = LANE_LABELS[d.lane] || "";
      const laneFlag = laneName
        ? `<span class="brief-flag brief-flag-${escapeHtml(d.lane || "work")}">${escapeHtml(laneName)}</span>`
        : "";
      const empty = !phone && !facts.length
        ? `<span class="muted">Даты, гости и район появятся, как только бот их услышит</span>`
        : "";
      brief.classList.toggle("brief-ready", tone === "ready");
      brief.classList.toggle("brief-work", tone === "work");
      brief.classList.toggle("brief-done", tone === "done");
      brief.innerHTML = agreed + laneFlag + phoneBtn + factHtml + empty;
      brief.querySelectorAll("[data-copy]").forEach((el) => {
        el.onclick = () => copyText(el.dataset.copy, "Номер");
      });
    }
    $("#chatEmpty").classList.add("hidden");
    $("#chatBody").classList.remove("hidden");
  }

  async function openChat(chatId, opts = {}) {
    if (!chatId) return;
    const prevId = state.chatId;
    const switching = prevId && prevId !== chatId;
    if (switching) persistCurrentDraft();
    const seq = ++state.openSeq;
    state.chatId = chatId;
    delete state.dialogUnread[chatId];
    renderDialogList();
    applyDraftToComposer(chatId);
    if (switching || !state.dialog || (state.dialog.chat_id || prevId) !== chatId) {
      const cached = state.dialogs.find((d) => d.chat_id === chatId);
      if (cached) {
        applyChatHeader(cached, chatId);
      } else {
        $("#chatEmpty").classList.add("hidden");
        $("#chatBody").classList.remove("hidden");
        $("#chatTitle").textContent = "…";
        const av = $("#chatAvatar");
        if (av) {
          av.textContent = initials(chatId);
          av.style.setProperty("--av-h", String(avatarHue(chatId)));
        }
      }
      if (switching) {
        state.messages = [];
        state.dialog = cached || { chat_id: chatId };
        const box = $("#msgs");
        if (box) {
          box.innerHTML = `<div class="msgs-empty"><div class="empty-sub">Загрузка…</div></div>`;
        }
      }
    }
    try {
      const data = await api(`/api/dialogs/${encodeURIComponent(chatId)}`);
      if (seq !== state.openSeq || state.chatId !== chatId) return;
      state.dialog = data.dialog || {};
      state.messages = data.messages || [];
      applyChatHeader(state.dialog, chatId);
      renderMessages();
      if (!opts.soft) loadDialogs(true);
      // подгрузить шаблоны с подстановкой плейсхолдеров для этого чата
      loadTemplates().catch(() => {});
    } catch (err) {
      if (seq !== state.openSeq || state.chatId !== chatId) return;
      toast("Диалог", err.message || "Не удалось открыть", "error");
    }
  }

  function fmtMsgTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    if (sameDay) return time;
    return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" }) + " " + time;
  }

  function renderMessages() {
    const box = $("#msgs");
    if (!box) return;
    if (!state.messages.length) {
      box.innerHTML = `<div class="msgs-empty">
        <div class="empty-icon"></div>
        <div class="empty-title">Нет сообщений</div>
        <div class="empty-sub">Напишите первое сообщение клиенту</div>
      </div>`;
      return;
    }
    box.innerHTML = state.messages.map((m, i) => {
      const side = m.role === "guest" ? "left" : "right";
      const tone = m.role === "guest" ? "guest" : m.role === "manager" ? "manager" : "bot";
      const who = m.role === "guest" ? "Клиент"
        : m.role === "manager" ? (m.sender_label || "Менеджер")
        : (m.sender_label || "Бот");
      const prev = state.messages[i - 1];
      const senderChanged = !prev || prev.role !== m.role
        || (m.role === "manager" && (prev.sender_label || "") !== (m.sender_label || ""));
      const senderGap = senderChanged && i > 0 ? "sender-gap" : "";
      const label = senderChanged
        ? `<div class="bubble-sender ${tone}">${escapeHtml(who)}</div>`
        : "";
      return `<div class="bubble-row ${side} ${senderGap}">${label}<div class="bubble ${tone}"><span class="ts">${escapeHtml(fmtMsgTime(m.created_at))}</span><span class="body">${escapeHtml(m.text || "")}</span></div></div>`;
    }).join("");
    requestAnimationFrame(() => {
      box.scrollTop = box.scrollHeight;
    });
  }

  function resizeComposer() {
    const ta = $("#replyText");
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(140, Math.max(40, ta.scrollHeight)) + "px";
  }
  function updateCharCount() {
    const ta = $("#replyText");
    const el = $("#charCount");
    if (!el) return;
    const n = (ta && ta.value || "").length;
    el.textContent = String(n);
  }

  async function sendReply() {
    const ta = $("#replyText");
    const text = (ta && ta.value || "").trim();
    const chatId = state.chatId;
    if (!text || !chatId) return;
    const btn = $("#btnSend");
    if (btn) btn.disabled = true;
    try {
      const sent = await api(`/api/dialogs/${encodeURIComponent(chatId)}/reply`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      if (state.chatId === chatId) {
        clearDraft(chatId);
        if (ta) ta.value = "";
        resizeComposer();
        updateCharCount();
        await openChat(chatId, { soft: true });
      } else {
        clearDraft(chatId);
      }
      toast(
        sent && sent.queued ? "В очереди бота" : "Отправлено",
        sent && sent.queued
          ? "Бот отправит это в Telegram в ближайшие секунды"
          : "Сообщение ушло клиенту",
        "info",
      );
    } catch (err) {
      toast("Отправка", err.message || "Ошибка", "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function takeover(on) {
    const chatId = state.chatId;
    if (!chatId) return;
    await api(`/api/dialogs/${encodeURIComponent(chatId)}/takeover`, {
      method: "POST",
      body: JSON.stringify({ active: on }),
    });
    if (state.chatId === chatId) openChat(chatId, { soft: true });
    toast(on ? "Перехват" : "Возврат боту", on ? "Диалог на менеджере" : "Бот снова ведёт чат", "info");
  }

  function once(key, fn) {
    if (!state._inflight) state._inflight = {};
    if (state._inflight[key]) return state._inflight[key];
    const p = Promise.resolve()
      .then(fn)
      .finally(() => { delete state._inflight[key]; });
    state._inflight[key] = p;
    return p;
  }

  async function fetchQueue() {
    return once("queue", async () => {
      const q = await api("/api/queue");
      state.queueCache = q.managers || [];
      return state.queueCache;
    });
  }

  function prettyPhone(raw) {
    const d = String(raw || "").replace(/\D/g, "");
    if (d.length === 11 && d[0] === "7") {
      return `+7 ${d.slice(1, 4)} ${d.slice(4, 7)} ${d.slice(7, 9)} ${d.slice(9)}`;
    }
    return String(raw || "");
  }

  function paintFloor(host, dialogs) {
    const waiting = dialogs.filter((d) => d.last_message && d.last_message.role === "guest");
    const onManager = dialogs.filter((d) => d.handed_off);
    const pinned = dialogs.filter((d) => {
      const blob = `${d.name || ""} ${d.phone || ""}`.replace(/\D/g, "");
      return blob.includes("9250841133") || blob.includes("9651960074");
    });
    const picked = [];
    const seen = new Set();
    [...pinned, ...waiting, ...onManager].forEach((d) => {
      if (!d || seen.has(d.chat_id) || picked.length >= 4) return;
      seen.add(d.chat_id);
      picked.push(d);
    });
    const cards = picked.map((d) => {
      const last = (d.last_message && d.last_message.text) || "первое сообщение ушло";
      const who = (d.last_message && d.last_message.role === "guest")
        ? "ждёт ответа"
        : (d.handed_off ? "у менеджера" : "ведёт бот");
      const facts = guestFacts(d).join(" · ");
      return `<button type="button" class="lead-card" data-open="${escapeHtml(d.chat_id)}">
        <div class="who">${escapeHtml(d.name || prettyPhone(d.phone) || "Гость")}</div>
        ${facts ? `<div class="facts">${escapeHtml(facts)}</div>` : ""}
        <div class="line">${escapeHtml(last)}</div>
        <div class="meta">${who} · открыть</div>
      </button>`;
    }).join("");
    host.className = "stats-strip floor";
    host.innerHTML = `
      <div class="floor-intro">
        <div class="floor-live"><i></i> бот на линии</div>
        <h3>Смена Анны</h3>
        <p>${dialogs.length} диалогов · ${waiting.length} ждут ответа · ${onManager.length} на менеджере. Бот ведёт чат, пока вы его не перехватили.</p>
      </div>
      <div class="floor-leads">${cards || `<div class="lead-card"><div class="who">Рассылка</div><div class="line">Новые номера появятся здесь сразу после отправки.</div></div>`}</div>`;
    host.querySelectorAll("[data-open]").forEach((el) => {
      el.onclick = () => openChat(el.dataset.open);
    });
  }

  function paintStatsStrip() {
    const host = $("#statsStrip");
    if (!host) return;
    const managers = state.queueCache || [];
    const dialogs = state.dialogs || [];
    if ((state.page || "dialogs") === "dialogs") {
      paintFloor(host, dialogs);
      const sub = $("#pageSub");
      if (sub) sub.textContent = "Смена Анны · бот отвечает, пока чат не у вас";
      return;
    }
    host.className = "stats-strip";
    const sentToday = managers.reduce((a, m) => a + (m.sent_today || 0), 0);
    const limits = managers.map((m) => Number(m.daily_limit) || 0).filter((n) => n > 0);
    const dayCap = limits.length ? Math.max(...limits) : 30;
    const pending = managers.reduce((a, m) => a + (m.pending || 0), 0);
    const active = dialogs.length;
    const replies = dialogs.filter((x) => x.handed_off).length;
    const quietMax = managers.reduce((a, m) => Math.max(a, m.quiet_remaining_sec || 0), 0);
    const quietExtra = quietMax > 0
      ? `<div class="stat-card warn"><div class="k">Тишина outreach</div><div class="v">${fmtQuiet(quietMax)}</div><div class="s">после входа · ответы гостям ок</div></div>`
      : "";
    host.innerHTML = `
      <div class="stat-card"><div class="k">Отправлено сегодня</div><div class="v">${sentToday} / ${dayCap}</div><div class="s">лимит аккаунта за день</div></div>
      <div class="stat-card"><div class="k">В очереди</div><div class="v">${pending}</div><div class="s">ждут первого сообщения</div></div>
      <div class="stat-card"><div class="k">Активные диалоги</div><div class="v">${active}</div><div class="s">в списке клиентов</div></div>
      <div class="stat-card"><div class="k">На менеджере</div><div class="v">${replies}</div><div class="s">перехваченные чаты</div></div>
      ${quietExtra}`;
  }

  async function refreshStats() {
    try {
      await fetchQueue();
      paintStatsStrip();
    } catch {
      /* keep previous strip */
    }
  }

  function renderQueue() {
    const q = (state.queueFilter || "").trim().toLowerCase();
    const managers = (state.queueCache || []).filter((m) => {
      if (!q) return true;
      return `${m.name} ${m.id} ${m.outreach_note || ""}`.toLowerCase().includes(q);
    });
    const prog = $("#queueProgress");
    if (prog) {
      prog.innerHTML = (state.queueCache || []).map((m) => {
        const lim = m.daily_limit || 1;
        const pct = Math.min(100, Math.round(((m.sent_today || 0) / lim) * 100));
        const warn = m.paused_today || pct >= 90;
        return `<div class="prog-card ${warn ? "warn" : ""}">
          <div class="top"><span>${escapeHtml(m.name)}</span><span class="muted">${m.sent_today || 0}/${lim}</span></div>
          <div class="bar"><i style="width:${pct}%"></i></div>
          <div class="meta">неделя ${m.sent_week || 0}/${m.weekly_limit || 210} · в очереди ${m.pending || 0}</div>
        </div>`;
      }).join("") || `<div class="muted">Нет менеджеров</div>`;
    }
    const rows = managers.map((m) => {
      const sess = m.session_online
        ? `<span class="status ok">в сети</span>`
        : `<span class="status muted">не в сети</span>`;
      const win = m.in_work_hours
        ? `<span class="status ok">окно · ${escapeHtml(m.moscow_time || "")}</span>`
        : `<span class="status warn">вне часов · ${escapeHtml(m.moscow_time || "")}</span>`;
      const note = m.quiet_active
        ? `<span class="status warn">${escapeHtml(m.quiet_reason || ("тишина " + fmtQuiet(m.quiet_remaining_sec)))}</span>`
        : m.paused_today
        ? `<span class="status bad">${escapeHtml(m.outreach_note || "стоп")}</span>`
        : `<span class="status muted">${escapeHtml(m.outreach_note || "—")}</span>`;
      return `<tr>
        <td><strong>${escapeHtml(m.name)}</strong> <span class="muted">[${escapeHtml(m.id)}]</span></td>
        <td>${m.sent_today}/${m.daily_limit}</td>
        <td>${m.sent_week || 0}/${m.weekly_limit || 210}</td>
        <td>${m.remaining_today}</td>
        <td>${m.pending}</td>
        <td>${win}</td>
        <td>${sess}</td>
        <td>${note}</td>
      </tr>`;
    }).join("");
    $("#queueBody").innerHTML = rows || `<tr><td colspan="8" class="muted">Нет менеджеров</td></tr>`;
  }

  async function loadQueue() {
    await fetchQueue();
    renderQueue();
    paintStatsStrip();
  }

  function isTechnicalLog(l) {
    if (l && l.technical) return true;
    const n = String((l && l.logger) || "").toLowerCase();
    return n.startsWith("aiohttp.") || n.startsWith("telethon.network")
      || n.startsWith("telethon.client.updates") || n.startsWith("asyncio");
  }

  async function loadLogs() {
    const level = $("#logLevel") ? $("#logLevel").value : "";
    const mgr = $("#logMgr") ? $("#logMgr").value : "";
    const tech = !!state.logTechnical;
    const q = new URLSearchParams({
      level, manager_id: mgr, limit: "250", technical: tech ? "1" : "0",
    });
    const data = await once("logs", () => api(`/api/logs?${q}`));
    const box = $("#logBox");
    if (!box) return;
    let rows = data.logs || [];
    if (!tech) rows = rows.filter((l) => !isTechnicalLog(l));
    box.innerHTML = rows.map(formatLog).join("")
      || `<div class="muted" style="padding:.8rem">Пока пусто — события бота появятся здесь</div>`;
    if (state.logFollow) box.scrollTop = box.scrollHeight;
  }
  function appendLog(item) {
    if (!state.logTechnical && isTechnicalLog(item)) return;
    const box = $("#logBox");
    if (!box) return;
    box.insertAdjacentHTML("beforeend", formatLog(item));
    if (state.logFollow) box.scrollTop = box.scrollHeight;
  }
  function formatLog(l) {
    const lv = escapeHtml(l.level || "");
    const tech = isTechnicalLog(l) ? " tech" : "";
    return `<div class="log-line ${lv}${tech}"><span class="muted">[${fmtTime(l.ts)}]</span> <span class="lv">${lv}</span> <span class="muted">${escapeHtml(l.logger || "")}</span> <span class="muted">${escapeHtml(l.manager_id || "")}</span> — ${escapeHtml(l.message || "")}</div>`;
  }

  async function loadControls() {
    const mgrs = await api("/api/managers");
    const opts = (mgrs.managers || []).map((m) => `<option value="${m.id}">${m.name} [${m.id}]</option>`).join("");
    $("#ctrlMgr").innerHTML = opts;
    $("#assignMgr").innerHTML = opts;
    const stops = await api("/api/stops");
    $("#stopList").innerHTML = (stops.stops || []).map((s) =>
      `<tr><td>${escapeHtml(s.key)}</td><td><span class="status muted">${escapeHtml(s.kind)}</span></td>
       <td><button class="btn secondary btn-sm" data-unstop="${escapeHtml(s.key)}">Снять</button></td></tr>`
    ).join("") || `<tr><td colspan="3" class="muted">Пусто</td></tr>`;
    $$("[data-unstop]").forEach((b) => b.onclick = async () => {
      await api("/api/stops/remove", { method: "POST", body: JSON.stringify({ [REDACTED] }) });
      toast("Стоп-лист", "Запись снята", "info");
      loadControls();
    });
  }

  function renderUsers() {
    const q = (state.usersFilter || "").trim().toLowerCase();
    const users = (state.usersCache || []).filter((u) => {
      if (!q) return true;
      return `${u.username} ${u.display_name || ""} ${u.manager_id || ""} ${u.role}`.toLowerCase().includes(q);
    });
    const roster = $("#teamRoster");
    if (roster) {
      const roleName = (role) => role === "admin" ? "администратор" : "менеджер";
      roster.innerHTML = users.map((u) => {
        const name = (u.display_name || u.username || "?").trim();
        const letter = name.slice(0, 1).toUpperCase();
        const st = !u.enabled ? "отключён" : u.must_change_password ? "ждёт пароль" : "на смене";
        return `<article class="team-card">
          <div class="team-avatar" aria-hidden="true">${escapeHtml(letter)}</div>
          <div>
            <strong>${escapeHtml(name)}</strong>
            <div class="muted">${escapeHtml(roleName(u.role))} · ${escapeHtml(u.username)}</div>
            <div class="muted">${escapeHtml(st)}</div>
          </div>
        </article>`;
      }).join("") || `<div class="muted">Команда пока пустая</div>`;
    }
    $("#usersBody").innerHTML = users.map((u) => {
      const st = !u.enabled
        ? `<span class="status bad">отключён</span>`
        : u.must_change_password
          ? `<span class="status warn">ждёт смены пароля</span>`
          : `<span class="status ok">активен</span>`;
      const actions = u.role === "admin"
        ? `<span class="muted">админ</span>`
        : `<button class="btn secondary btn-sm" data-reset="${escapeHtml(u.username)}">Сброс пароля</button>
           <button class="btn secondary btn-sm" data-toggle="${escapeHtml(u.username)}" data-en="${u.enabled ? 0 : 1}">${u.enabled ? "Отключить" : "Включить"}</button>
           <button class="btn danger btn-sm" data-del="${escapeHtml(u.username)}">Удалить</button>`;
      return `<tr>
        <td><strong>${escapeHtml(u.username)}</strong> <span class="muted">${escapeHtml(u.display_name || "")}</span></td>
        <td><span class="status muted">${escapeHtml(u.role)}</span></td>
        <td>${escapeHtml(u.manager_id || "—")}</td>
        <td>${st}</td>
        <td class="row">${actions}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="5" class="muted">Нет пользователей</td></tr>`;
    $$("[data-reset]").forEach((b) => b.onclick = async () => {
      const r = await api("/api/users/reset-password", {
        method: "POST", body: JSON.stringify({ username: b.dataset.reset }),
      });
      $("#usersOut").textContent = `Временный пароль для ${b.dataset.reset}: ${r.temp_password}`;
      toast("Пароль сброшен", b.dataset.reset, "info");
      loadUsers();
    });
    $$("[data-toggle]").forEach((b) => b.onclick = async () => {
      await api("/api/users/enable", {
        method: "POST",
        body: JSON.stringify({ username: b.dataset.toggle, enabled: b.dataset.en === "1" }),
      });
      toast("Пользователь", b.dataset.en === "1" ? "Включён" : "Отключён", "info");
      loadUsers();
    });
    $$("[data-del]").forEach((b) => b.onclick = async () => {
      if (!confirm(`Удалить ${b.dataset.del}?`)) return;
      await api("/api/users/delete", {
        method: "POST", body: JSON.stringify({ username: b.dataset.del }),
      });
      toast("Удалено", b.dataset.del, "warn");
      loadUsers();
    });
  }

  async function loadUsers() {
    const data = await api("/api/users");
    $("#distMode").value = data.distribution || "even";
    state.usersCache = data.users || [];
    renderUsers();
  }

  const MAIL_STATUS = {
    pending: "в очереди",
    sent: "отправлено",
    failed: "не ушло",
    stopped: "стоп",
  };

  async function loadMail() {
    const mid = ($("#ctrlMgr") && $("#ctrlMgr").value) || "";
    const q = mid ? `?manager_id=${encodeURIComponent(mid)}` : "";
    const data = await api(`/api/outreach/board${q}`);
    const win = $("#mailWindow");
    if (win) {
      const note = (data.status && data.status.note) || "";
      const live = data.status && data.status.running ? "Сейчас отправляет. " : "";
      win.textContent = `${live}${data.window_open ? "Окно открыто" : "Сейчас вне окна"} · ${data.window_label || ""}. Сегодня ${data.sent_today || 0}/${data.daily_limit || 0}. ${note}`.trim();
    }
    const samples = $("#mailSamples");
    if (samples) {
      samples.innerHTML = (data.samples || []).map((t) =>
        `<div class="mail-sample">${escapeHtml(t)}</div>`
      ).join("") || `<div class="muted">Нет текстов</div>`;
    }
    const body = $("#mailBody");
    if (body) {
      body.innerHTML = (data.contacts || []).map((c) => {
        const st = MAIL_STATUS[c.status] || c.status || "—";
        const tone = c.status === "sent" ? "ok" : c.status === "failed" || c.status === "stopped" ? "bad" : "muted";
        return `<tr>
          <td>${escapeHtml(prettyPhone(c.phone) || c.phone)}</td>
          <td>${escapeHtml(c.name || "—")}</td>
          <td><span class="status ${tone}">${escapeHtml(st)}</span></td>
          <td class="muted">${escapeHtml(c.last_error || "")}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="4" class="muted">Пока пусто — вставьте номера слева</td></tr>`;
    }
  }

  async function sendMail(now) {
    const text = ($("#mailPhones") && $("#mailPhones").value) || "";
    const mid = ($("#ctrlMgr") && $("#ctrlMgr").value) || "";
    const out = $("#mailOut");
    try {
      const data = await api("/api/outreach/compose", {
        method: "POST",
        body: JSON.stringify({ text, now, manager_id: mid }),
      });
      if (out) out.textContent = data.message || "ок";
      const skipped = (data.skipped || []).map((s) => `${s.phone}: ${s.status}`).join("\n");
      if (out && skipped) out.textContent += `\nНе взяла:\n${skipped}`;
      toast("Рассылка", data.message || "В очереди бота", "info");
      if ($("#mailPhones") && (data.queued || []).length) $("#mailPhones").value = "";
      loadMail();
    } catch (err) {
      if (out) out.textContent = err.message || "Ошибка";
      toast("Рассылка", err.message || "Ошибка", "error");
    }
  }

  async function sendPreview() {
    const mid = $("#ctrlMgr").value;
    const data = await api("/api/outreach/preview", { method: "POST", body: JSON.stringify({ manager_id: mid }) });
    $("#ctrlOut").textContent = (data.lines || []).join("\n") || "пусто";
  }
  function openOutreachSamples() {
    window.open("/outreach-samples", "_blank", "noopener");
  }
  async function sendStart(go) {
    const mid = $("#ctrlMgr").value;
    const data = await api("/api/outreach/run", {
      method: "POST",
      body: JSON.stringify({ manager_id: mid, go }),
    });
    $("#ctrlOut").textContent = data.message || JSON.stringify(data);
    toast(go ? "Рассылка" : "Стоп", data.message || (go ? "запущена" : "остановлена"), go ? "info" : "warn");
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }
  function fmtTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function validatePhoneish(val, hintEl) {
    const v = (val || "").trim();
    if (!hintEl) return !!v;
    if (!v) {
      hintEl.textContent = "Заполните поле";
      hintEl.classList.remove("ok");
      return false;
    }
    hintEl.textContent = "ок";
    hintEl.classList.add("ok");
    return true;
  }

  const pwForm = $("#pwForm");
  if (pwForm) {
    pwForm.onsubmit = async (e) => {
      e.preventDefault();
      const errEl = $("#pwErr");
      if (errEl) errEl.textContent = "";
      const a = ($("#pwNew") || {}).value;
      const b = ($("#pwNew2") || {}).value;
      if (a !== b) {
        if (errEl) errEl.textContent = "Пароли не совпадают";
        return;
      }
      try {
        const data = await api("/api/password", {
          method: "POST",
          body: JSON.stringify({
            old_[REDACTED] || {}).value,
            new_[REDACTED]
          }),
        });
        state.user = data.user;
        state.csrf = data.csrf;
        showApp();
        connectWs();
        navTo("dialogs");
      } catch (err) {
        if (errEl) errEl.textContent = err.message || "Ошибка";
      }
    };
  }

  setClick("#btnLogout", async () => {
    persistCurrentDraft();
    await api("/api/logout", { method: "POST", body: "{}" });
    location.href = "/";
  });
  setClick("#btnTheme", () => {
    const order = ["dark", "light", "system"];
    const i = order.indexOf(state.theme);
    const next = order[(i + 1) % order.length];
    setTheme(next);
    state.prefs.theme = next;
    api("/api/prefs", { method: "POST", body: JSON.stringify({ theme: next }) }).catch(() => {});
  });
  const dialogFilterBar = $("#dialogFilterBar");
  if (dialogFilterBar) {
    dialogFilterBar.querySelectorAll("[data-dfilter]").forEach((b) => {
      b.onclick = () => {
        state.dialogScope = b.dataset.dfilter || "mine";
        localStorage.setItem("home24_dialog_scope", state.dialogScope);
        syncDialogFilterBar();
        loadDialogs(true);
      };
    });
    syncDialogFilterBar();
  }
  const laneBar = $("#laneBar");
  if (laneBar) {
    laneBar.querySelectorAll("[data-lane]").forEach((b) => {
      b.classList.toggle("active", (b.dataset.lane || "") === state.lane);
      b.onclick = () => setLane(b.dataset.lane || "");
    });
  }
  try {
    window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
      if (state.theme === "system") setTheme("system");
    });
  } catch {}
  $$("#sideNav button[data-page], #bottomNav button[data-page], #shellNav button[data-page]").forEach((b) => {
    b.onclick = () => {
      if (b.dataset.page === "more") {
        setDrawer(true);
        return;
      }
      navTo(b.dataset.page);
    };
  });
  const btnSide = $("#btnSideCollapse");
  if (btnSide) btnSide.onclick = () => setDrawer(false);
  const btnMobile = $("#btnMobileMenu");
  if (btnMobile) {
    btnMobile.onclick = () => {
      const app = $("#appShell");
      setDrawer(!(app && app.classList.contains("drawer-open")));
    };
  }
  function setListHidden(on) {
    const layout = document.querySelector(".dialogs-layout");
    if (!layout) return;
    layout.classList.toggle("list-hidden", !!on);
    localStorage.setItem("home24_list_hidden", on ? "1" : "0");
  }
  const btnHideList = $("#btnHideList");
  if (btnHideList) btnHideList.onclick = () => setListHidden(true);
  const btnShowList = $("#btnShowList");
  if (btnShowList) btnShowList.onclick = () => setListHidden(false);
  const bd = $("#sideBackdrop");
  if (bd) bd.onclick = () => setDrawer(false);

  setClick("#btnSend", sendReply);
  setClick("#btnCopyCard", () => {
    if (!state.dialog) return;
    copyText(guestCardText(state.dialog), "Карточка гостя");
  });
  async function patchChat(body) {
    if (!state.chatId) return;
    const data = await api(`/api/dialogs/${encodeURIComponent(state.chatId)}/flags`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (state.dialog) Object.assign(state.dialog, data);
    await loadDialogs(true);
    if (state.dialog) applyChatHeader(state.dialog, state.chatId);
  }
  setClick("#btnPin", async () => {
    if (!state.dialog) return;
    try {
      await patchChat({ pinned: state.dialog.pinned ? 0 : 1 });
      toast("Булавка", state.dialog.pinned ? "Чат закреплён" : "Булавка снята", "info");
    } catch (err) {
      toast("Булавка", err.message || "Не сохранилось", "error");
    }
  });
  setClick("#btnArchive", async () => {
    if (!state.dialog) return;
    const next = state.dialog.archived ? 0 : 1;
    try {
      await patchChat({ archived: next });
      toast(next ? "Архив" : "Смена", next ? "Чат убран из живой ленты" : "Чат снова в смене", "info");
      if (next) {
        state.chatId = "";
        state.dialog = null;
        $("#chatBody").classList.add("hidden");
        $("#chatEmpty").classList.remove("hidden");
      }
    } catch (err) {
      toast("Архив", err.message || "Не сохранилось", "error");
    }
  });
  setClick("#btnExport", async () => {
    if (!state.chatId) return;
    try {
      const r = await fetch(`/api/dialogs/${encodeURIComponent(state.chatId)}/export`, { credentials: "same-origin" });
      const text = await r.text();
      if (!r.ok) throw new Error("Не удалось собрать переписку");
      await copyText(text, "Переписка");
    } catch (err) {
      toast("Переписка", err.message || "Ошибка", "error");
    }
  });
  const chatNote = $("#chatNote");
  if (chatNote) {
    chatNote.addEventListener("blur", async () => {
      if (!state.chatId || !state.dialog) return;
      const value = chatNote.value || "";
      if ((state.dialog.note || "") === value) return;
      try {
        await patchChat({ note: value });
      } catch (err) {
        toast("Заметка", err.message || "Не сохранилось", "error");
      }
    });
  }
  function openFromDesk(chatId) {
    state.dialogScope = "all";
    localStorage.setItem("home24_dialog_scope", "all");
    navTo("dialogs");
    setTimeout(() => openChat(chatId), 60);
  }
  async function loadDesk() {
    const stats = $("#deskStats");
    const waiting = $("#deskWaiting");
    if (!stats) return;
    try {
      const data = await api("/api/desk");
      const cards = [
        ["Ждут", data.waiting],
        ["На боте", data.on_bot],
        ["У менеджера", data.on_manager],
        ["В архиве", data.archived],
        ["Булавки", data.pinned],
        ["Сообщений за сутки", data.messages_24h],
      ];
      stats.innerHTML = cards.map(([label, n]) =>
        `<div class="desk-stat"><b>${escapeHtml(String(n ?? 0))}</b><span>${escapeHtml(label)}</span></div>`
      ).join("");
      const items = data.waiting_items || [];
      waiting.innerHTML = items.length ? items.map((w) => {
        const mins = Math.floor((w.wait_sec || 0) / 60);
        const age = mins < 60 ? `${mins} мин` : `${Math.floor(mins / 60)} ч`;
        return `<button type="button" class="desk-wait" data-id="${escapeHtml(w.chat_id)}">
          <strong>${escapeHtml(w.name || w.chat_id)}</strong>
          <small>${escapeHtml(age)} · ${escapeHtml(w.manager_id || "—")}</small>
          <div>${escapeHtml(w.last_text || "")}</div>
        </button>`;
      }).join("") : `<div class="muted">Сейчас никто не ждёт ответа</div>`;
      waiting.querySelectorAll("[data-id]").forEach((el) => {
        el.onclick = () => openFromDesk(el.dataset.id);
      });
      const lead = $("#deskQuietLead");
      if (lead) {
        lead.textContent = `Тихих чатов старше 3 дней: ${data.quiet_ready || 0}. Кто ждёт ответа и чаты на булавке остаются в смене.`;
      }
    } catch (err) {
      stats.innerHTML = `<div class="muted">${escapeHtml(err.message || "Стол доступен администратору")}</div>`;
    }
  }
  const deskQuery = $("#deskQuery");
  if (deskQuery) {
    deskQuery.oninput = () => {
      clearTimeout(state._deskT);
      state._deskT = setTimeout(async () => {
        const q = deskQuery.value.trim();
        const box = $("#deskHits");
        if (!box) return;
        if (q.length < 2) { box.innerHTML = ""; return; }
        try {
          const data = await api("/api/search?q=" + encodeURIComponent(q));
          const hits = data.hits || [];
          box.innerHTML = hits.length ? hits.map((h) =>
            `<button type="button" class="desk-hit" data-id="${escapeHtml(h.chat_id)}">
              <strong>${escapeHtml(h.name || h.chat_id)}</strong>
              <small>${escapeHtml(h.role || "")} · ${escapeHtml(h.manager_id || "")}</small>
              <div>${escapeHtml(h.text || "")}</div>
            </button>`
          ).join("") : `<div class="muted">Ничего не нашлось</div>`;
          box.querySelectorAll("[data-id]").forEach((el) => {
            el.onclick = () => openFromDesk(el.dataset.id);
          });
        } catch (err) {
          box.innerHTML = `<div class="muted">${escapeHtml(err.message || "Ошибка поиска")}</div>`;
        }
      }, 250);
    };
  }
  setClick("#btnArchiveQuiet", async () => {
    const out = $("#deskOut");
    try {
      const data = await api("/api/archive-quiet", { method: "POST", body: "{}" });
      if (out) out.textContent = `В архив ушло чатов: ${data.archived || 0}`;
      toast("Архив", `Убрано: ${data.archived || 0}`, "info");
      loadDesk();
    } catch (err) {
      if (out) out.textContent = err.message || "Ошибка";
    }
  });
  setClick("#btnTake", () => takeover(true));
  setClick("#btnReturn", () => takeover(false));
  const logLevel = $("#logLevel");
  if (logLevel) logLevel.onchange = loadLogs;
  const logMgr = $("#logMgr");
  if (logMgr) {
    logMgr.oninput = () => {
      clearTimeout(state._logT);
      state._logT = setTimeout(loadLogs, 250);
    };
  }
  const logFollow = $("#logFollow");
  if (logFollow) {
    logFollow.onchange = () => { state.logFollow = !!logFollow.checked; };
  }
  const logTech = $("#logTechnical");
  if (logTech) {
    logTech.checked = !!state.logTechnical;
    logTech.onchange = () => {
      state.logTechnical = !!logTech.checked;
      localStorage.setItem("home24_log_technical", state.logTechnical ? "1" : "0");
      loadLogs();
    };
  }
  const btnLogRefresh = $("#btnLogRefresh");
  if (btnLogRefresh) btnLogRefresh.onclick = loadLogs;
  setClick("#btnPreview", sendPreview);
  setClick("#btnSamples", openOutreachSamples);
  setClick("#btnOpenMail", () => navTo("mail"));
  setClick("#btnSendGo", () => sendStart(true));
  setClick("#btnSendStop", () => sendStart(false));
  setClick("#btnMailNow", () => sendMail(true));
  setClick("#btnMailQueue", () => sendMail(false));
  setClick("#btnMailRefresh", () => loadMail());
  setClick("#btnAddStop", async () => {
    if (!validatePhoneish(($("#stopPhone") || {}).value, $("#stopPhoneHint"))) return;
    await api("/api/stops/add", {
      method: "POST",
      body: JSON.stringify({ phone: ($("#stopPhone") || {}).value.trim() }),
    });
    if ($("#stopPhone")) $("#stopPhone").value = "";
    if ($("#stopPhoneHint")) $("#stopPhoneHint").textContent = "";
    toast("Стоп-лист", "Добавлено", "info");
    loadControls();
  });
  setClick("#btnAssign", async () => {
    if (!validatePhoneish(($("#assignPhone") || {}).value, $("#assignPhoneHint"))) return;
    const data = await api("/api/assign", {
      method: "POST",
      body: JSON.stringify({
        phone: ($("#assignPhone") || {}).value.trim(),
        manager_id: ($("#assignMgr") || {}).value,
      }),
    });
    if ($("#ctrlOut")) $("#ctrlOut").textContent = data.message || "ok";
    toast("Закрепление", data.message || "ok", "info");
  });
  setClick("#btnCreateUser", async () => {
    const login = (($("#newUserLogin") || {}).value || "").trim();
    const mid = (($("#newUserMid") || {}).value || "").trim();
    let ok = true;
    if (!login) {
      if ($("#newUserLoginHint")) $("#newUserLoginHint").textContent = "Укажите логин";
      ok = false;
    } else if ($("#newUserLoginHint")) $("#newUserLoginHint").textContent = "";
    if (!mid) {
      if ($("#newUserMidHint")) $("#newUserMidHint").textContent = "Укажите manager_id";
      ok = false;
    } else if ($("#newUserMidHint")) $("#newUserMidHint").textContent = "";
    if (!ok) return;
    try {
      const r = await api("/api/users", {
        method: "POST",
        body: JSON.stringify({
          username: login,
          display_name: (($("#newUserName") || {}).value || "").trim(),
          manager_id: mid,
        }),
      });
      if ($("#usersOut")) {
        $("#usersOut").textContent =
          `Создан ${r.user.username}\nВременный [REDACTED]
      }
      if ($("#newUserLogin")) $("#newUserLogin").value = "";
      if ($("#newUserName")) $("#newUserName").value = "";
      if ($("#newUserMid")) $("#newUserMid").value = "";
      toast("Пользователь", "Создан " + r.user.username, "info");
      loadUsers();
    } catch (err) {
      if ($("#usersOut")) $("#usersOut").textContent = err.message || "Ошибка";
      toast("Ошибка", err.message || "Не удалось создать", "error");
    }
  });
  setClick("#btnDistSave", async () => {
    const r = await api("/api/distribution", {
      method: "POST",
      body: JSON.stringify({ mode: ($("#distMode") || {}).value }),
    });
    if ($("#usersOut")) $("#usersOut").textContent = `Режим: ${r.mode}`;
    toast("Распределение", r.mode, "info");
  });
  setClick("#btnRedistribute", async () => {
    const r = await api("/api/redistribute", { method: "POST", body: "{}" });
    if ($("#usersOut")) $("#usersOut").textContent = JSON.stringify(r, null, 2);
    toast("Раздача", "Готово", "info");
  });

  const dialogSearch = $("#dialogSearch");
  if (dialogSearch) {
    dialogSearch.addEventListener("input", () => {
      state.dialogFilter = dialogSearch.value;
      renderDialogList();
    });
  }
  const queueSearch = $("#queueSearch");
  if (queueSearch) {
    queueSearch.addEventListener("input", () => {
      state.queueFilter = queueSearch.value;
      renderQueue();
    });
  }
  const usersSearch = $("#usersSearch");
  if (usersSearch) {
    usersSearch.addEventListener("input", () => {
      state.usersFilter = usersSearch.value;
      renderUsers();
    });
  }

  async function loadTemplates() {
    // Always fetch (no once-dedupe) — picker must work even if a prior call hung.
    const q = state.chatId ? `?chat_id=${encodeURIComponent(state.chatId)}` : "";
    try {
      const data = await api(`/api/templates${q}`);
      state.templates = data.templates || [];
      state.tplCategories = data.categories || [];
      if (!state.templates.length) {
        const retry = await api("/api/templates");
        state.templates = retry.templates || [];
        state.tplCategories = retry.categories || state.tplCategories;
      }
      return data;
    } catch (err) {
      console.error("loadTemplates", err);
      toast("Шаблоны", err.message || "не загрузились", "error");
      state.templates = [];
      return null;
    }
  }

  function filteredTemplates() {
    const q = (state.tplQuery || "").trim().toLowerCase();
    const cat = state.tplCatFilter || "";
    return (state.templates || []).filter((t) => {
      if (cat && t.category !== cat) return false;
      if (!q) return true;
      const hay = `${t.title || ""} ${t.body || ""} ${t.category_label || ""} ${t.filled || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }

  function renderTplPicker() {
    const list = $("#tplList");
    const cats = $("#tplCats");
    if (!list || !cats) return;
    const allLabel = "Все";
    const catHtml = [`<button type="button" class="tpl-cat ${!state.tplCatFilter ? "active" : ""}" data-cat="">${allLabel}</button>`]
      .concat((state.tplCategories || []).map((c) =>
        `<button type="button" class="tpl-cat ${state.tplCatFilter === c.id ? "active" : ""}" data-cat="${escapeHtml(c.id)}">${escapeHtml(c.label)}</button>`
      )).join("");
    cats.innerHTML = catHtml;
    cats.querySelectorAll("[data-cat]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        state.tplCatFilter = b.dataset.cat || "";
        renderTplPicker();
      };
    });
    const items = filteredTemplates();
    if (!items.length) {
      list.innerHTML = `<div class="tpl-empty">Ничего не найдено</div>`;
      return;
    }
    list.innerHTML = items.map((t) => {
      const preview = (t.filled || t.body || "").replace(/\s+/g, " ").trim();
      const scope = t.scope === "personal" ? `<span class="tpl-scope">личное</span>` : "";
      return `<button type="button" class="tpl-item" data-tid="${escapeHtml(t.id)}" role="menuitem">
        <div class="tpl-title">${escapeHtml(t.title || "")} ${scope}
          <span class="tpl-cat-tag">${escapeHtml(t.category_label || t.category || "")}</span>
        </div>
        <div class="tpl-preview">${escapeHtml(preview)}</div>
      </button>`;
    }).join("");
    list.querySelectorAll("[data-tid]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        insertTemplate(b.dataset.tid);
      };
    });
  }

  function insertTemplate(tid) {
    const t = (state.templates || []).find((x) => x.id === tid);
    if (!t) return;
    const text = (t.filled || t.body || "").trim();
    const ta = $("#replyText");
    if (!ta || !text) return;
    ta.value = ta.value ? (ta.value.replace(/\s*$/, "") + "\n" + text) : text;
    if (state.chatId) setDraft(state.chatId, ta.value);
    resizeComposer();
    updateCharCount();
    closeTplPicker();
    ta.focus();
  }

  function positionTplPicker() {
    const box = $("#tplPicker");
    const anchor = $("#btnTemplates") || $("#replyText") || $(".composer");
    if (!box || !anchor) return;
    const r = anchor.getBoundingClientRect();
    const width = Math.min(440, window.innerWidth - 24);
    let left = Math.max(12, Math.min(r.left, window.innerWidth - width - 12));
    const height = Math.min(420, window.innerHeight * 0.55);
    let top = r.top - height - 8;
    if (top < 12) {
      // мало места сверху — открыть под кнопкой
      top = Math.min(window.innerHeight - height - 12, r.bottom + 8);
    }
    box.style.width = width + "px";
    box.style.left = left + "px";
    box.style.top = top + "px";
    box.style.bottom = "auto";
  }

  async function openTplPicker() {
    try {
      const box = $("#tplPicker");
      if (!box) {
        toast("Шаблоны", "Элемент списка не найден — обновите страницу (Ctrl+F5)", "error");
        return;
      }
      // вынести из .card (backdrop-filter + overflow:hidden клипят fixed)
      if (box.parentElement !== document.body) {
        document.body.appendChild(box);
      }
      state.tplOpen = true;
      box.classList.remove("hidden");
      box.style.display = "flex";
      const list = $("#tplList");
      if (list) list.innerHTML = `<div class="tpl-empty">Загрузка шаблонов…</div>`;
      positionTplPicker();
      await loadTemplates();
      renderTplPicker();
      positionTplPicker();
      const search = $("#tplSearch");
      if (search) {
        search.value = state.tplQuery || "";
        try {
          search.focus();
          search.select();
        } catch {}
      }
    } catch (err) {
      console.error("openTplPicker", err);
      toast("Шаблоны", (err && err.message) || "не открылись", "error");
    }
  }

  function closeTplPicker() {
    state.tplOpen = false;
    const box = $("#tplPicker");
    if (box) {
      box.classList.add("hidden");
      box.style.display = "";
    }
  }

  // global for inline fallback / Edge quirks
  window.__home24OpenTemplates = () => {
    if (state.tplOpen) closeTplPicker();
    else openTplPicker();
  };

  const replyText = $("#replyText");
  if (replyText) {
    replyText.addEventListener("input", () => {
      if (state.chatId) setDraft(state.chatId, replyText.value);
      resizeComposer();
      updateCharCount();
    });
    // slash: ловим до вставки символа (keydown) и как единственный символ
    replyText.addEventListener("keydown", (e) => {
      const empty = !(replyText.value || "").trim();
      if (
        e.[REDACTED] "/"
        && empty
        && !e.ctrlKey
        && !e.metaKey
        && !e.altKey
      ) {
        e.preventDefault();
        openTplPicker();
        return;
      }
      if (e.[REDACTED] "Escape" && state.tplOpen) {
        e.preventDefault();
        closeTplPicker();
        return;
      }
      if (e.[REDACTED] "Enter") {
        const newlineMode = state.prefs && state.prefs.composer_enter === "newline";
        if (newlineMode) {
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            sendReply();
          }
          return;
        }
        if (!e.shiftKey) {
          e.preventDefault();
          sendReply();
        }
      }
    });
  }

  const btnTemplates = $("#btnTemplates");
  if (btnTemplates) {
    // capture phase so nothing (notify overlay, etc.) steals the click
    btnTemplates.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (state.tplOpen) closeTplPicker();
        else openTplPicker();
      },
      true
    );
  }
  const tplClose = $("#tplClose");
  if (tplClose) {
    tplClose.addEventListener("click", (e) => {
      e.stopPropagation();
      closeTplPicker();
    });
  }
  const tplSearch = $("#tplSearch");
  if (tplSearch) {
    tplSearch.addEventListener("input", () => {
      state.tplQuery = tplSearch.value || "";
      renderTplPicker();
    });
    tplSearch.addEventListener("keydown", (e) => {
      if (e.[REDACTED] "Escape") {
        e.preventDefault();
        closeTplPicker();
        $("#replyText") && $("#replyText").focus();
      }
      if (e.[REDACTED] "Enter") {
        e.preventDefault();
        const first = filteredTemplates()[0];
        if (first) insertTemplate(first.id);
      }
    });
  }
  const tplAddPersonal = $("#tplAddPersonal");
  if (tplAddPersonal) {
    tplAddPersonal.onclick = async (e) => {
      e.stopPropagation();
      const title = prompt("Название личного шаблона");
      if (!title) return;
      const body = prompt("Текст шаблона (можно {имя}, {менеджер})");
      if (!body) return;
      try {
        await api("/api/templates", {
          method: "POST",
          body: JSON.stringify({
            title,
            body,
            category: "greeting",
            scope: "personal",
          }),
        });
        toast("Шаблоны", "Личный шаблон сохранён", "info");
        await loadTemplates();
        renderTplPicker();
      } catch (err) {
        toast("Шаблоны", err.message || "ошибка", "error");
      }
    };
  }
  document.addEventListener("click", (e) => {
    const box = $("#tplPicker");
    if (!box || box.classList.contains("hidden")) return;
    if (box.contains(e.target) || (btnTemplates && btnTemplates.contains(e.target))) return;
    closeTplPicker();
  });
  window.addEventListener("resize", () => {
    if (state.tplOpen) positionTplPicker();
  });

  window.addEventListener("beforeunload", persistCurrentDraft);

  document.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select" || (e.target && e.target.isContentEditable);
    if (e.[REDACTED] "Escape") {
      setDrawer(false);
      $("#notifyPanel") && $("#notifyPanel").classList.add("hidden");
      closeTplPicker();
      return;
    }
    if (typing) return;
    if (!e.altKey && !e.ctrlKey && !e.metaKey && state.page === "dialogs" && (e.[REDACTED] "j" || e.[REDACTED] "k" || e.[REDACTED] "ArrowDown" || e.[REDACTED] "ArrowUp")) {
      const items = filteredDialogs();
      if (items.length) {
        e.preventDefault();
        const idx = items.findIndex((d) => d.chat_id === state.chatId);
        const down = e.[REDACTED] "j" || e.[REDACTED] "ArrowDown";
        const next = down ? Math.min(items.length - 1, Math.max(0, idx) + (idx < 0 ? 0 : 1)) : Math.max(0, (idx < 0 ? 0 : idx - 1));
        if (items[next] && items[next].chat_id !== state.chatId) openChat(items[next].chat_id);
      }
    }
    if (e.[REDACTED] "/" && state.page === "dialogs") {
      e.preventDefault();
      const ta = $("#replyText");
      const chatOpen = !!state.chatId && $("#chatBody") && !$("#chatBody").classList.contains("hidden");
      if (ta && chatOpen && !(ta.value || "").trim()) {
        ta.focus();
        openTplPicker();
      } else if (ta && chatOpen) {
        // даже если в композере есть текст — открыть picker по кнопке-эквиваленту
        openTplPicker();
      } else {
        $("#dialogSearch") && $("#dialogSearch").focus();
      }
    }
    if (e.altKey && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      const map = { "1": "dialogs", "2": "queue", "3": "logs", "4": "controls", "5": "prefs", "6": "users", "7": "settings", "8": "accounts" };
      if (map[e.key]) {
        e.preventDefault();
        const page = map[e.key];
        if ((page === "users" || page === "settings" || page === "accounts") && !(state.user && state.user.is_admin)) return;
        navTo(page);
      }
    }
  });

  function updateBell() {
    const b = $("#bellBadge");
    if (!b) return;
    const n = state.unread || 0;
    b.textContent = String(n);
    b.classList.toggle("hidden", n <= 0);
  }

  async function pollNotify() {
    try {
      const data = await api("/api/notifications");
      state.unread = data.unread || 0;
      updateBell();
    } catch {}
  }

  async function openNotify() {
    const data = await api("/api/notifications");
    state.unread = 0;
    updateBell();
    await api("/api/notifications/read", { method: "POST", body: "{}" });
    const list = $("#notifyList");
    if (list) {
      list.innerHTML = (data.notifications || []).map((n) =>
        `<div class="notify-item"><div class="t">${escapeHtml(n.title || n.message || "Событие")}</div>
         <div class="b">${escapeHtml(n.body || n.message || "")}</div></div>`
      ).join("") || `<div class="muted" style="padding:1rem">Пусто</div>`;
    }
    const panel = $("#notifyPanel");
    if (panel) panel.classList.remove("hidden");
  }

  async function loadPrefsPage() {
    const data = await api("/api/prefs");
    applyPrefs(data.prefs || {});
    const dn = $("#prefDisplayName");
    const sig = $("#prefSignature");
    if (dn) dn.value = data.display_name || "";
    if (sig) sig.value = (data.prefs && data.prefs.signature) || "";
    const p = data.prefs || {};
    const setSel = (id, val) => { const el = $(id); if (el) el.value = val; };
    const setChk = (id, val) => { const el = $(id); if (el) el.checked = !!val; };
    setSel("#prefTheme", p.theme || "dark");
    setSel("#prefFontSize", p.font_size || "md");
    setSel("#prefComposerEnter", p.composer_enter || "send");
    setSel("#prefDialogFilter", p.dialog_filter || "mine");
    setChk("#prefCompact", p.compact_chat);
    setChk("#prefNotifySound", p.notify_sound !== false);
    setChk("#prefNotifyBrowser", p.notify_browser);
    setChk("#prefNotifyToast", p.notify_toast !== false);
    await renderPrefTemplates();
  }

  async function renderPrefTemplates() {
    const host = $("#prefTplList");
    if (!host) return;
    await loadTemplates();
    const personal = (state.templates || [])
      .filter((t) => t.scope === "personal")
      .sort((a, b) => {
        const sa = Number(a.sort); const sb = Number(b.sort);
        const na = Number.isFinite(sa) ? sa : 100;
        const nb = Number.isFinite(sb) ? sb : 100;
        return na - nb || String(a.title || "").localeCompare(String(b.title || ""));
      });
    if (!personal.length) {
      host.innerHTML = `<div class="muted">Пока нет личных шаблонов — добавьте свой вариант приветствия или прощания.</div>`;
      return;
    }
    host.innerHTML = personal.map((t, i) => `
      <div class="pref-tpl-row" data-ptid="${escapeHtml(t.id)}">
        <div class="tpl-settings-meta">
          <strong>${escapeHtml(t.title)}</strong>
          <span class="pill">${escapeHtml(t.category_label || t.category)}</span>
        </div>
        <div class="muted" style="white-space:pre-wrap;font-size:0.84rem">${escapeHtml(t.body)}</div>
        <div class="pref-tpl-actions">
          <button type="button" class="btn secondary btn-sm" data-pref-up="${i}" ${i === 0 ? "disabled" : ""}>↑</button>
          <button type="button" class="btn secondary btn-sm" data-pref-down="${i}" ${i === personal.length - 1 ? "disabled" : ""}>↓</button>
          <button type="button" class="btn secondary btn-sm" data-pref-edit="${escapeHtml(t.id)}">Изменить</button>
          <button type="button" class="btn secondary btn-sm" data-pref-del="${escapeHtml(t.id)}">Удалить</button>
        </div>
      </div>`).join("");
    host.querySelectorAll("[data-pref-edit]").forEach((b) => {
      b.onclick = () => editPrefTemplate(b.dataset.prefEdit);
    });
    host.querySelectorAll("[data-pref-del]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("Удалить личный шаблон?")) return;
        await api(`/api/templates/${encodeURIComponent(b.dataset.prefDel)}`, { method: "DELETE" });
        toast("Шаблоны", "Удалено", "info");
        await renderPrefTemplates();
      };
    });
    host.querySelectorAll("[data-pref-up]").forEach((b) => {
      b.onclick = async () => {
        const i = Number(b.dataset.prefUp);
        if (i <= 0) return;
        const ids = personal.map((t) => t.id);
        [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
        await api("/api/templates/reorder", { method: "POST", body: JSON.stringify({ ids }) });
        await renderPrefTemplates();
      };
    });
    host.querySelectorAll("[data-pref-down]").forEach((b) => {
      b.onclick = async () => {
        const i = Number(b.dataset.prefDown);
        const ids = personal.map((t) => t.id);
        if (i >= ids.length - 1) return;
        [ids[i], ids[i + 1]] = [ids[i + 1], ids[i]];
        await api("/api/templates/reorder", { method: "POST", body: JSON.stringify({ ids }) });
        await renderPrefTemplates();
      };
    });
  }

  async function editPrefTemplate(tid) {
    const t = tid ? (state.templates || []).find((x) => x.id === tid) : null;
    const title = prompt("Название", t ? t.title : "");
    if (title == null) return;
    const body = prompt("Текст ({имя}, {менеджер})", t ? t.body : "");
    if (body == null) return;
    const cat = prompt("Категория: greeting или closing", (t && t.category) || "greeting") || "greeting";
    await api("/api/templates", {
      method: "POST",
      body: JSON.stringify({
        id: tid || undefined,
        title: title.trim(),
        body: body.trim(),
        category: cat.trim() === "closing" ? "closing" : "greeting",
        scope: "personal",
      }),
    });
    $("#prefTplOut").textContent = "Сохранено";
    toast("Шаблоны", "Сохранено", "info");
    await renderPrefTemplates();
  }

  const btnPrefTplAdd = $("#btnPrefTplAdd");
  if (btnPrefTplAdd) btnPrefTplAdd.onclick = () => editPrefTemplate("");

  const btnPrefProfileSave = $("#btnPrefProfileSave");
  if (btnPrefProfileSave) {
    btnPrefProfileSave.onclick = async () => {
      const r = await api("/api/prefs", {
        method: "POST",
        body: JSON.stringify({
          display_name: ($("#prefDisplayName") || {}).value || "",
          signature: ($("#prefSignature") || {}).value || "",
        }),
      });
      if (r.user) {
        state.user = r.user;
        $("#userPill").textContent = `${r.user.display_name} · ${r.user.role}`;
      }
      applyPrefs(r.prefs || {});
      $("#prefOut").textContent = "Профиль сохранён";
      toast("Настройки", "Профиль сохранён", "info");
    };
  }

  const btnPrefUiSave = $("#btnPrefUiSave");
  if (btnPrefUiSave) {
    btnPrefUiSave.onclick = async () => {
      const browserOn = !!($("#prefNotifyBrowser") || {}).checked;
      if (browserOn && "Notification" in window && Notification.permission === "default") {
        await Notification.requestPermission();
      }
      const r = await api("/api/prefs", {
        method: "POST",
        body: JSON.stringify({
          theme: ($("#prefTheme") || {}).value,
          font_size: ($("#prefFontSize") || {}).value,
          composer_enter: ($("#prefComposerEnter") || {}).value,
          dialog_filter: ($("#prefDialogFilter") || {}).value,
          compact_chat: !!($("#prefCompact") || {}).checked,
          notify_sound: !!($("#prefNotifySound") || {}).checked,
          notify_browser: browserOn,
          notify_toast: !!($("#prefNotifyToast") || {}).checked,
        }),
      });
      applyPrefs(r.prefs || {});
      renderDialogList();
      $("#prefOut").textContent = "Сохранено · data/user_prefs.json";
      toast("Настройки", "Сохранено", "info");
    };
  }

  const btnPrefPwSave = $("#btnPrefPwSave");
  if (btnPrefPwSave) {
    btnPrefPwSave.onclick = async () => {
      const oldp = ($("#prefPwOld") || {}).value || "";
      const n1 = ($("#prefPwNew") || {}).value || "";
      const n2 = ($("#prefPwNew2") || {}).value || "";
      if (n1 !== n2) {
        toast("Пароль", "Пароли не совпадают", "error");
        return;
      }
      try {
        const r = await api("/api/password", {
          method: "POST",
          body: JSON.stringify({ old_[REDACTED] new_[REDACTED] }),
        });
        if (r.user) state.user = r.user;
        if (r.csrf) state.csrf = r.csrf;
        $("#prefPwOld").value = "";
        $("#prefPwNew").value = "";
        $("#prefPwNew2").value = "";
        toast("Пароль", "Пароль изменён", "info");
      } catch (err) {
        toast("Пароль", err.message || "ошибка", "error");
      }
    };
  }

  async function loadSettings() {
    const data = await api("/api/settings");
    state.settings = data;
    const warns = (data.accounts || [])
      .filter((a) => (a.counters && a.counters.paused_today) || a.paused)
      .map((a) => {
        const r = (a.counters && a.counters.pause_reason) || a.status_note || a.status;
        return `${a.label || a.id}: ${r}`;
      });
    const warnBox = $("#settingsWarn");
    if (warnBox) {
      warnBox.classList.toggle("hidden", !warns.length);
      warnBox.textContent = warns.length
        ? ("Стоп на сегодня — " + warns.join(" · "))
        : "";
    }
    const sr = data.service_reports || {};
    const savedChk = $("#prefSavedReports");
    if (savedChk) savedChk.checked = !!sr.saved_messages_reports;
    const cw = data.check_window || {};
    const setNum = (id, val) => { const el = $(id); if (el && val != null) el.value = val; };
    const cwEn = $("#prefCheckWindows");
    if (cwEn) cwEn.checked = cw.enabled !== false;
    setNum("#prefCheckInterval", cw.interval_min != null ? cw.interval_min : 3);
    setNum("#prefCheckJitter", cw.jitter != null ? cw.jitter : 0.3);
    setNum("#prefNightStart", cw.night_start_hour != null ? cw.night_start_hour : 23);
    setNum("#prefNightEnd", cw.night_end_hour != null ? cw.night_end_hour : 8);
    setNum("#prefNightInterval", cw.night_interval_min != null ? cw.night_interval_min : 15);
    setNum("#prefActiveIdle", cw.active_idle_min != null ? cw.active_idle_min : 10);
    const weekCap = Number(data.defaults?.weekly || 210);
    const potential = weekCap * 6;
    $("#settingsAccounts").innerHTML = `<div class="settings-block"><h4>Лимиты аккаунта бота</h4>
      <p class="muted lead">По умолчанию день ${data.defaults?.daily || 30} / неделя ${weekCap}. Потенциал: ${potential} (неделя × 6). После нового входа — тишина outreach ${data.defaults?.quiet_hours_after_login || 24}ч (настраивается).</p>` +
      ((data.accounts || []).map((a) => {
        const c = a.counters || {};
        const paused = c.paused_today || a.paused;
        const quiet = a.quiet_active || c.quiet_active;
        const warn = quiet
          ? ` · ${escapeHtml(a.quiet_label || c.quiet_reason || "тишина")}`
          : paused ? ` · ${escapeHtml(c.pause_reason || a.status_note || "стоп")}` : "";
        return `<div class="acc-row ${paused || quiet ? "paused" : ""}">
          <strong>${escapeHtml(a.label || a.id)}</strong>
          <span class="pill">${escapeHtml(a.id)}</span>
          <span class="muted">сегодня <b>${c.sent_today || 0}</b>/${a.daily_send_limit} · неделя <b>${c.sent_week || 0}</b>/${a.weekly_send_limit}${warn}</span>
          <label class="field">день <input data-acc-daily="${escapeHtml(a.id)}" class="ctl" type="number" min="1" value="${a.daily_send_limit}" style="width:5.5rem"/></label>
          <label class="field">неделя <input data-acc-weekly="${escapeHtml(a.id)}" class="ctl" type="number" min="1" value="${a.weekly_send_limit}" style="width:5.5rem"/></label>
          <label class="field">менеджер <input data-acc-mgr="${escapeHtml(a.id)}" class="ctl" value="${escapeHtml(a.manager_id || "")}" placeholder="пусто = общий" style="width:7.5rem"/></label>
          <label class="field">тишина после входа (ч) <input data-acc-quiet-h="${escapeHtml(a.id)}" class="ctl" type="number" min="0" max="168" value="${Number(a.quiet_hours_after_login ?? 24)}" style="width:5rem" title="Часов без outreach после нового логина"/></label>
          <label class="field">не слать outreach до <input data-acc-quiet-until="${escapeHtml(a.id)}" class="ctl" type="datetime-local" value="${escapeHtml(toLocalDatetimeValue(a.no_outreach_until))}" style="width:13rem" title="Пусто = снять тишину"/></label>
        </div>`;
      }).join("") || `<div class="muted">Нет аккаунтов — подключите в «Аккаунты»</div>`) + `</div>`;
    $("#settingsManagers").innerHTML = `<div class="settings-block"><h4>Доли менеджеров</h4>
      <p class="muted lead">Квота дня: ${escapeHtml(JSON.stringify(data.shares_today || {}))}</p>
      <div class="table-wrap"><table class="table sticky-head"><thead><tr><th>Менеджер</th><th>Доля</th><th>Сегодня</th><th>Неделя</th><th>Квота дня</th></tr></thead><tbody>` +
      (data.managers || []).map((m) => `<tr>
        <td>${escapeHtml(m.name)} [${escapeHtml(m.id)}]</td>
        <td><input data-share="${escapeHtml(m.id)}" class="ctl" type="number" min="1" value="${m.share_weight || 1}" style="width:4.5rem"/></td>
        <td>${m.sent_today || 0}</td><td>${m.sent_week || 0}</td><td>${m.share_today || 0}</td>
      </tr>`).join("") + `</tbody></table></div></div>`;
    await renderSettingsTemplates();
  }

  async function renderSettingsTemplates() {
    const host = $("#settingsTemplates");
    if (!host) return;
    const data = await loadTemplates();
    const cats = state.tplCategories || [];
    const catOpts = cats.map((c) =>
      `<option value="${escapeHtml(c.id)}">${escapeHtml(c.label)}</option>`
    ).join("");
    const shared = (state.templates || []).filter((t) => t.scope === "shared");
    host.innerHTML = shared.map((t) => `
      <div class="tpl-settings-row" data-sid="${escapeHtml(t.id)}">
        <div class="tpl-settings-meta">
          <strong>${escapeHtml(t.title)}</strong>
          <span class="pill">${escapeHtml(t.category_label || t.category)}</span>
          <span class="muted">${escapeHtml(t.id)}</span>
        </div>
        <div class="muted" style="white-space:pre-wrap;font-size:0.84rem">${escapeHtml(t.body)}</div>
        <div class="tpl-settings-actions">
          <button type="button" class="btn secondary btn-sm" data-edit-tpl="${escapeHtml(t.id)}">Изменить</button>
          <button type="button" class="btn secondary btn-sm" data-del-tpl="${escapeHtml(t.id)}">Удалить</button>
        </div>
      </div>`).join("") || `<div class="muted">Нет общих шаблонов</div>`;
    host.querySelectorAll("[data-edit-tpl]").forEach((b) => {
      b.onclick = () => openTplEditor(b.dataset.editTpl);
    });
    host.querySelectorAll("[data-del-tpl]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("Удалить шаблон?")) return;
        try {
          await api(`/api/templates/${encodeURIComponent(b.dataset.delTpl)}`, { method: "DELETE" });
          toast("Шаблоны", "Удалено", "info");
          await renderSettingsTemplates();
        } catch (err) {
          toast("Шаблоны", err.message || "ошибка", "error");
        }
      };
    });
    const btnNew = $("#btnTplNew");
    if (btnNew) {
      btnNew.onclick = () => openTplEditor("");
    }
    // stash for editor
    state._tplCatOpts = catOpts;
  }

  function openTplEditor(tid) {
    const host = $("#settingsTemplates");
    if (!host) return;
    const t = tid ? (state.templates || []).find((x) => x.id === tid) : null;
    const form = document.createElement("div");
    form.className = "tpl-edit-form";
    form.innerHTML = `
      <strong>${t ? "Редактирование" : "Новый общий шаблон"}</strong>
      <label class="field">Название <input id="tplEditTitle" class="ctl" value="${escapeHtml(t && t.title || "")}"/></label>
      <label class="field">Категория <select id="tplEditCat" class="ctl">${state._tplCatOpts || ""}</select></label>
      <label class="field">Текст <textarea id="tplEditBody" class="ctl">${escapeHtml(t && t.body || "")}</textarea></label>
      <div class="form-actions">
        <button type="button" class="btn" id="tplEditSave">Сохранить</button>
        <button type="button" class="btn secondary" id="tplEditCancel">Отмена</button>
      </div>`;
    host.prepend(form);
    const sel = form.querySelector("#tplEditCat");
    if (sel && t) sel.value = t.category;
    form.querySelector("#tplEditCancel").onclick = () => form.remove();
    form.querySelector("#tplEditSave").onclick = async () => {
      const title = form.querySelector("#tplEditTitle").value.trim();
      const body = form.querySelector("#tplEditBody").value.trim();
      const category = form.querySelector("#tplEditCat").value;
      try {
        await api("/api/templates", {
          method: "POST",
          body: JSON.stringify({
            id: tid || undefined,
            title,
            body,
            category,
            scope: "shared",
          }),
        });
        $("#tplSettingsOut").textContent = "Шаблон сохранён";
        toast("Шаблоны", "Сохранено", "info");
        await renderSettingsTemplates();
      } catch (err) {
        toast("Шаблоны", err.message || "ошибка", "error");
      }
    };
  }

  setClick("#btnBell", () => openNotify());
  setClick("#btnNotifyClose", () => {
    $("#notifyPanel") && $("#notifyPanel").classList.add("hidden");
  });
  setClick("#btnSettingsSave", async () => {
    const accounts = [...document.querySelectorAll("[data-acc-daily]")].map((el) => {
      const id = el.dataset.accDaily;
      const untilEl = document.querySelector(`[data-acc-quiet-until="${id}"]`);
      const untilRaw = untilEl ? untilEl.value.trim() : "";
      let no_outreach_until = 0;
      if (untilRaw) {
        const ms = Date.parse(untilRaw);
        no_outreach_until = Number.isNaN(ms) ? 0 : Math.floor(ms / 1000);
      }
      const qhEl = document.querySelector(`[data-acc-quiet-h="${id}"]`);
      return {
        id,
        daily_send_limit: Number(el.value),
        weekly_send_limit: Number(document.querySelector(`[data-acc-weekly="${id}"]`).value),
        manager_id: document.querySelector(`[data-acc-mgr="${id}"]`).value.trim(),
        quiet_hours_after_login: qhEl ? Number(qhEl.value) : 24,
        no_outreach_until,
      };
    });
    const managers = [...document.querySelectorAll("[data-share]")].map((el) => ({
      id: el.dataset.share,
      share_weight: Number(el.value),
    }));
    const savedOn = !!($("#prefSavedReports") || {}).checked;
    const check_window = {
      enabled: !!($("#prefCheckWindows") || {}).checked,
      interval_min: Number(($("#prefCheckInterval") || {}).value || 3),
      jitter: Number(($("#prefCheckJitter") || {}).value || 0.3),
      night_start_hour: Number(($("#prefNightStart") || {}).value || 23),
      night_end_hour: Number(($("#prefNightEnd") || {}).value || 8),
      night_interval_min: Number(($("#prefNightInterval") || {}).value || 15),
      active_idle_min: Number(($("#prefActiveIdle") || {}).value || 10),
    };
    const r = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        accounts,
        managers,
        service_reports: { saved_messages_reports: savedOn },
        check_window,
      }),
    });
    $("#settingsOut").textContent = r.ok ? "Сохранено" : JSON.stringify(r);
    toast("Настройки", r.ok ? "Сохранено" : "Ошибка", r.ok ? "info" : "error");
    loadSettings();
  });

  boot();
})();
