# -*- coding: utf-8 -*-
"""Лента заходов на панель. В смене её нет: чужой запрос отвечает как пустой 404."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from aiohttp import web

from bot.dashboard import auth as dash_auth

_LOCK = threading.RLock()
_HITS: deque[dict[str, Any]] = deque(maxlen=400)
_PRESENCE: dict[str, dict[str, Any]] = {}
_DB: sqlite3.Connection | None = None

_PAGE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>·</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;background:#0c0c0c;color:#f4f4f2;font:14px/1.4 ui-sans-serif,system-ui,sans-serif}
header{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:baseline;padding:16px 18px 8px}
h1{font:500 22px/1 Georgia,serif;margin:0;letter-spacing:-.02em}
.muted{color:#8d8d8a}
.nums{display:flex;flex-wrap:wrap;gap:8px;padding:0 18px 12px}
.num{background:#171717;border:1px solid #2a2a2a;border-radius:12px;padding:8px 12px;min-width:108px}
.num b{display:block;font-size:18px}
.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:12px;padding:0 18px 24px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
section{background:#141414;border:1px solid #262626;border-radius:16px;padding:12px;min-width:0}
h2{margin:0 0 8px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#c8c8c4}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:5px 6px;border-bottom:1px solid #242424;vertical-align:top}
th{color:#8d8d8a;font-weight:500}
tr.bad td{color:#ffb4a8}
tr.ok td:first-child{color:#b7e4c7}
.ip{font-variant-numeric:tabular-nums}
button,input,select{font:inherit;color:#f4f4f2;background:#101010;border:1px solid #333;border-radius:10px;padding:7px 10px}
button{cursor:pointer}
button.danger{border-color:#6b2c2c;color:#ffb4a8}
form.row{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.tape{max-height:320px;overflow:auto}
.ip-block{margin:0 0 12px}
.ip-head{display:flex;gap:10px;align-items:baseline;font-weight:600;padding:6px 0 2px;border-top:1px solid #2a2a2a}
.ip-head span{color:#8d8d8a;font-weight:400;font-size:12px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#5c5c5a;margin-right:6px}
.dot.on{background:#3dd68c}
.err{color:#ffb4a8;min-height:1.1em;margin:4px 0}
</style></head><body>
<header>
  <h1>Обзор</h1>
  <span class="muted" id="clock"></span>
  <span class="muted" id="self"></span>
  <a href="/app" style="color:#f4f4f2">Смена</a>
</header>
<div class="nums" id="nums"></div>
<div class="grid">
  <section>
    <h2>Кто на сайте</h2>
    <div class="tape" id="presence"></div>
    <h2 style="margin-top:14px">Входы</h2>
    <p class="muted">Логин, адрес, время по Москве. Пароли сюда не попадают.</p>
    <div class="tape" id="logins"></div>
  </section>
  <section>
    <h2>Что делают</h2>
    <div class="tape" id="actions"></div>
    <h2 style="margin-top:14px">Заходы, в том числе без входа</h2>
    <div class="tape" id="hits"></div>
  </section>
  <section>
    <h2>Аккаунты Telegram</h2>
    <p class="muted" id="proxy"></p>
    <form class="row" id="accAdd">
      <input name="id" placeholder="id слота" required/>
      <input name="label" placeholder="метка"/>
      <input name="manager_id" placeholder="менеджер"/>
      <button>Добавить слот</button>
    </form>
    <div class="err" id="accErr"></div>
    <div id="accounts"></div>
  </section>
  <section>
    <h2>Люди смены</h2>
    <form class="row" id="userAdd">
      <input name="username" placeholder="логин" required/>
      <input name="display_name" placeholder="имя"/>
      <select name="role"><option value="manager">менеджер</option><option value="admin">админ</option></select>
      <input name="manager_id" placeholder="id менеджера"/>
      <button>Добавить</button>
    </form>
    <div class="err" id="userErr"></div>
    <div id="users"></div>
    <h2 style="margin-top:14px">Журнал процесса</h2>
    <div class="tape" id="logs"></div>
  </section>
</div>
<script>
const $ = (id) => document.getElementById(id);
function csrf(){
  const m = document.cookie.match(/(?:^|; )home24_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}
function esc(s){
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
}
function when(ts){
  const n = Number(ts);
  if (!n) return "";
  return new Date(n * 1000).toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
}
function byIp(groups, cols, cls){
  const list = groups || [];
  if (!list.length) return "<p class='muted'>Пока пусто</p>";
  return list.map((g) => {
    const rows = (g.rows || []).map((r) => ({...r, _cls: cls ? cls(r) : ""}));
    const who = [...new Set(rows.map((r) => r.username).filter(Boolean))].join(", ");
    return `<div class="ip-block"><div class="ip-head"><span class="ip">${esc(g.ip)}</span><span>${esc(who)}</span><span>${rows.length}</span></div>${table(cols, rows)}</div>`;
  }).join("");
}
function table(cols, rows){
  if (!rows.length) return "<p class='muted'>Пока пусто</p>";
  const head = "<tr>" + cols.map((c) => "<th>" + esc(c[0]) + "</th>").join("") + "</tr>";
  const body = rows.map((r) => "<tr class='" + esc(r._cls || "") + "'>" + cols.map((c) => "<td>" + c[1](r) + "</td>").join("") + "</tr>").join("");
  return "<table>" + head + body + "</table>";
}
async function act(payload){
  const r = await fetch(location.pathname, {
    method: "POST",
    credentials: "same-origin",
    headers: {"Content-Type":"application/json","X-CSRF-Token":csrf()},
    body: JSON.stringify(payload)
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "не вышло");
  return j;
}
function paint(d){
  $("clock").textContent = when(d.now) + " Москва";
  $("self").textContent = d.self ? ("вы · " + d.self) : "";
  const logins = d.logins || [];
  const ips = new Set(logins.map((x) => x.ip).filter(Boolean));
  const fails = logins.filter((x) => x.kind === "login_fail").length;
  const online = (d.accounts || []).filter((a) => a.online).length;
  $("nums").innerHTML = [
    ["На сайте", (d.presence || []).length],
    ["Входов в ленте", logins.length],
    ["Отказов", fails],
    ["Адресов", ips.size],
    ["TG онлайн", online + "/" + (d.accounts || []).length],
    ["Ждут ответа", (d.desk && d.desk.waiting) || 0]
  ].map(([k,v]) => "<div class='num'><b>" + esc(v) + "</b><span class='muted'>" + esc(k) + "</span></div>").join("");
  $("presence").innerHTML = table(
    [["Кто",(r)=>esc(r.username)],["Откуда",(r)=>"<span class='ip'>"+esc(r.ip)+"</span>"],["Где",(r)=>esc(r.path)],["Когда",(r)=>esc(when(r.ts))]],
    d.presence || []
  );
  $("logins").innerHTML = byIp(d.logins_by_ip, [
    ["Когда",(r)=>esc(when(r.ts))],
    ["Кто",(r)=>esc(r.username || "—")],
    ["Итог",(r)=>esc(r.kind==="login_ok"?"вошёл":"отказ") + (r.n>1?" ×"+r.n:"")],
    ["Браузер",(r)=>esc((r.ua||"").slice(0,72))]
  ], (r)=>r.kind==="login_ok"?"ok":"bad");
  $("actions").innerHTML = byIp(d.actions_by_ip, [
    ["Когда",(r)=>esc(when(r.ts))],
    ["Кто",(r)=>esc(r.username||"—")],
    ["Что",(r)=>esc([r.detail, r.path].filter(Boolean).join(" ")) + (r.n>1?" ×"+r.n:"")]
  ]);
  $("hits").innerHTML = byIp(d.hits_by_ip, [
    ["Когда",(r)=>esc(r.ts?when(r.ts):(r.stamp||""))],
    ["Запрос",(r)=>esc((r.method||"")+" "+(r.path||"")) + (r.n>1?" ×"+r.n:"")],
    ["Код",(r)=>esc(r.status)]
  ]);
  $("proxy").textContent = d.proxy ? ("Выход Telegram: " + d.proxy) : "Выход Telegram: прямой";
  $("accounts").innerHTML = (d.accounts || []).map((a) => {
    const on = a.online ? "on" : "";
    return "<p><span class='dot "+on+"'></span><b>"+esc(a.label||a.id)+"</b> · "+esc(a.phone||"")+
      " · "+esc(a.status||"")+ (a.enabled?"":" · выключен")+
      "<br><span class='muted'>"+esc(a.id)+" · "+esc(a.manager_id||"общий")+
      " · связь "+esc(when(a.last_connect_at))+" · "+esc(a.device_model||"")+"</span> "+
      "<button data-acc='"+esc(a.id)+"' data-en='"+(a.enabled?"0":"1")+"'>"+(a.enabled?"Выключить":"Включить")+"</button> "+
      "<button class='danger' data-drop='"+esc(a.id)+"'>Удалить слот</button></p>";
  }).join("") || "<p class='muted'>Нет слотов</p>";
  $("users").innerHTML = (d.users || []).map((u) => {
    if (u.unlisted) return "<p><b>"+esc(u.display_name||u.username)+"</b> <span class='muted'>этот вход в списке смены не показывается</span></p>";
    return "<p><b>"+esc(u.display_name||u.username)+"</b> · "+esc(u.username)+" · "+esc(u.role)+
      (u.enabled?"":" · выключен")+
      "<br><span class='muted'>последний вход "+esc(u.last_ip||"—")+" · "+esc(when(u.last_at))+"</span> "+
      "<button data-user='"+esc(u.username)+"' data-en='"+(u.enabled?"0":"1")+"'>"+(u.enabled?"Выключить":"Включить")+"</button> "+
      "<button data-pw='"+esc(u.username)+"'>Новый пароль</button> "+
      "<button class='danger' data-udel='"+esc(u.username)+"'>Удалить</button></p>";
  }).join("");
  $("logs").innerHTML = table(
    [["Когда",(r)=>esc(when(r.ts))],["Уровень",(r)=>esc(r.level)],["Текст",(r)=>esc(r.message)]],
    (d.logs || []).slice().reverse()
  );
}
async function load(){
  const r = await fetch(location.pathname + "?part=feed", {credentials:"same-origin", cache:"no-store"});
  if (r.status === 404) { $("clock").textContent = "сессия кончилась"; return; }
  if (!r.ok) return;
  paint(await r.json());
}
document.body.addEventListener("click", async (ev) => {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) return;
  try {
    if (t.dataset.acc) {
      await act({act:"acc_enabled", id:t.dataset.acc, enabled:t.dataset.en==="1"});
    } else if (t.dataset.drop) {
      const id = t.dataset.drop;
      if (prompt("Чтобы удалить слот, введите его id. Файл сессии на диске останется.") !== id) return;
      await act({act:"acc_drop", id, confirm:id});
    } else if (t.dataset.user) {
      await act({act:"user_enabled", username:t.dataset.user, enabled:t.dataset.en==="1"});
    } else if (t.dataset.pw) {
      const j = await act({act:"user_pw", username:t.dataset.pw});
      alert("Временный пароль для " + t.dataset.pw + ": " + (j.temp_password || ""));
    } else if (t.dataset.udel) {
      if (!confirm("Удалить " + t.dataset.udel + "?")) return;
      await act({act:"user_drop", username:t.dataset.udel});
    } else return;
    $("accErr").textContent = "";
    $("userErr").textContent = "";
    await load();
  } catch (e) {
    $("accErr").textContent = e.message || String(e);
  }
});
$("accAdd").onsubmit = async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    await act({act:"acc_add", id:fd.get("id"), label:fd.get("label"), manager_id:fd.get("manager_id")});
    ev.target.reset();
    $("accErr").textContent = "";
    await load();
  } catch (e) { $("accErr").textContent = e.message || String(e); }
};
$("userAdd").onsubmit = async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    const j = await act({
      act:"user_add", username:fd.get("username"), display_name:fd.get("display_name"),
      role:fd.get("role"), manager_id:fd.get("manager_id")
    });
    ev.target.reset();
    $("userErr").textContent = j.temp_password ? ("временный [REDACTED] + j.temp_password) : "";
    await load();
  } catch (e) { $("userErr").textContent = e.message || String(e); }
};
load();
setInterval(() => { if (!document.hidden) load(); }, 8000);
</script>
</body></html>
"""


def quiet_path() -> str:
    raw = (os.getenv("HOME24_SIGHT_PATH") or "").strip()
    if not raw.startswith("/") or ".." in raw or len(raw) < 16:
        return ""
    return raw.rstrip("/") or raw


def _db_path() -> Path:
    raw = (os.getenv("HOME24_INGRESS_DB") or "data/ingress.sqlite").strip()
    return Path(raw)


def _conn() -> sqlite3.Connection:
    global _DB
    with _LOCK:
        if _DB is None:
            path = _db_path()
            if str(path) not in (":memory:",) and not str(path).startswith("file:"):
                path.parent.mkdir(parents=True, exist_ok=True)
            _DB = sqlite3.connect(str(path), check_same_thread=False)
            _DB.row_factory = sqlite3.Row
            _DB.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts REAL NOT NULL,
                  ip TEXT NOT NULL DEFAULT '',
                  ua TEXT NOT NULL DEFAULT '',
                  username TEXT NOT NULL DEFAULT '',
                  kind TEXT NOT NULL DEFAULT '',
                  path TEXT NOT NULL DEFAULT '',
                  status INTEGER NOT NULL DEFAULT 0,
                  detail TEXT NOT NULL DEFAULT ''
                )
                """
            )
            _DB.commit()
        return _DB


def reset_for_tests() -> None:
    global _DB
    with _LOCK:
        if _DB is not None:
            _DB.close()
            _DB = None
        _HITS.clear()
        _PRESENCE.clear()


def client_ip(request: web.Request) -> str:
    remote = (request.remote or "").split("%", 1)[0]
    if remote in ("[REDACTED]", "::1"):
        fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if fwd:
            return fwd[:64]
    return (request.remote or "")[:64]


def _session_user(request: web.Request) -> dash_auth.DashUser | None:
    tok = request.cookies.get(dash_auth.COOKIE_NAME) or ""
    if not tok:
        return None
    return dash_auth.parse_session_token(tok)


def _persist(
    *,
    ip: str,
    ua: str,
    username: str,
    kind: str,
    path: str,
    status: int,
    detail: str,
) -> None:
    detail = (detail or "")[:240]
    low = detail.lower()
    if "password" in low or "session" in low or "hash" in low:
        detail = ""
    now = time.time()
    with _LOCK:
        conn = _conn()
        conn.execute(
            "INSERT INTO events(ts,ip,ua,username,kind,path,status,detail) VALUES(?,?,?,?,?,?,?,?)",
            (now, ip[:64], ua[:180], username[:80], kind[:32], path[:180], int(status), detail),
        )
        conn.commit()
        last = int(conn.execute("SELECT MAX(id) FROM events").fetchone()[0] or 0)
        if last % 40 == 0:
            conn.execute("DELETE FROM events WHERE ts < ?", (now - 30 * 86400,))
            conn.commit()


def note_login(*, ip: str, username: str, ok: bool, ua: str = "", detail: str = "") -> None:
    kind = "login_ok" if ok else "login_fail"
    name = (username or "")[:80]
    _HITS.appendleft(
        {
            "ts": time.time(),
            "ip": ip,
            "method": "POST",
            "path": "/api/login",
            "status": 200 if ok else 401,
            "username": name,
        }
    )
    _persist(
        ip=ip,
        ua=ua,
        username=name,
        kind=kind,
        path="/api/login",
        status=200 if ok else 401,
        detail=detail if not ok else "",
    )
    if not ok or not name:
        return
    row = dash_auth.find_user(name)
    if row and row.get("unlisted"):
        return
    _PRESENCE[name] = {
        "username": name,
        "ip": ip,
        "ua": ua[:180],
        "path": "/app",
        "ts": time.time(),
    }


def note_request(request: web.Request, status: int) -> None:
    path = request.path or ""
    if path.startswith("/static") or path.startswith("/brand") or path.startswith("/ws"):
        return
    qp = quiet_path()
    if qp and path == qp:
        return
    if path in ("/api/login", "/api/invite"):
        return
    ip = client_ip(request)
    ua = (request.headers.get("User-Agent") or "")[:180]
    user = _session_user(request)
    name = user.username if user else ""
    if user and not user.unlisted:
        _PRESENCE[name] = {"username": name, "ip": ip, "ua": ua, "path": path[:180], "ts": time.time()}
    _HITS.appendleft(
        {
            "ts": time.time(),
            "ip": ip,
            "method": request.method,
            "path": path[:180],
            "status": int(status),
            "username": name,
        }
    )
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/"):
        _persist(
            ip=ip,
            ua=ua,
            username=name,
            kind="action",
            path=path,
            status=int(status),
            detail=request.method,
        )


def _rows(kind_prefix: str, limit: int) -> list[dict[str, Any]]:
    with _LOCK:
        cur = _conn().execute(
            "SELECT ts,ip,ua,username,kind,path,status,detail FROM events "
            "WHERE kind=? OR kind LIKE ? ORDER BY id DESC LIMIT ?",
            (kind_prefix, kind_prefix + "%", limit),
        )
        return [dict(r) for r in cur.fetchall()]


def _act_label(act: str) -> str:
    return {
        "acc_add": "добавил слот",
        "acc_enabled": "включил или выключил слот",
        "acc_drop": "удалил слот",
        "user_add": "добавил человека",
        "user_enabled": "включил или выключил человека",
        "user_drop": "удалил человека",
        "user_pw": "сбросил пароль",
    }.get(act, (act or "")[:64])


def _scrub(row: dict[str, Any]) -> dict[str, Any] | None:
    path = str(row.get("path") or "").split("?", 1)[0]
    if _is_own_path(path):
        if str(row.get("kind") or "").startswith("login"):
            item = dict(row)
            item["path"] = ""
            return item
        if str(row.get("kind") or "") == "action":
            item = dict(row)
            item["path"] = ""
            item["detail"] = _act_label(str(item.get("detail") or ""))
            return item
        return None
    return row


def _proxy_label() -> str:
    raw = (os.getenv("TELEGRAM_MTPROXY") or "").strip()
    host = raw.split(":", 1)[0] if raw else ""
    return host


def _is_own_path(url: str) -> bool:
    """Свои опросы обзора и статика. Иначе лента забивается GET пачками."""
    path = (url or "").split("?", 1)[0]
    if path.startswith("/static") or path.startswith("/brand"):
        return True
    if path in ("/favicon.ico", "/robots.txt"):
        return True
    qp = quiet_path()
    return bool(qp and path == qp)


def _fold_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Одинаковые заходы с одного адреса схлопываются в одну строку со счётчиком."""
    folded: list[dict[str, Any]] = []
    index: dict[tuple, int] = {}
    for row in rows:
        [REDACTED]
            str(row.get("ip") or ""),
            str(row.get("method") or ""),
            str(row.get("path") or ""),
            int(row.get("status") or 0),
            str(row.get("username") or ""),
            str(row.get("kind") or ""),
            str(row.get("detail") or ""),
        )
        if key in index:
            folded[index[key]]["n"] = int(folded[index[key]].get("n") or 1) + 1
            continue
        item = dict(row)
        item["n"] = 1
        index[key] = len(folded)
        folded.append(item)
    return folded


def _by_ip(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ip = str(row.get("ip") or "") or "без адреса"
        groups.setdefault(ip, []).append(row)

    def sort_key(ip: str) -> tuple:
        latest = 0.0
        for row in groups[ip]:
            latest = max(latest, float(row.get("ts") or 0))
        return (-latest, ip)

    return [{"ip": ip, "rows": groups[ip]} for ip in sorted(groups, [REDACTED]


def _tail_access(limit: int = 80) -> list[dict[str, Any]]:
    path = Path(os.getenv("HOME24_ACCESS_LOG") or "/var/log/nginx/access.log")
    try:
        data = path.read_bytes()
    except OSError:
        return []
    chunk = data[-500_000:]
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        # combined: ip - - [time] "METHOD path HTTP/x" status
        parts = line.split(" ", 6)
        if len(parts) < 7 or parts[0].count(".") < 1 and ":" not in parts[0]:
            continue
        ip = parts[0][:64]
        quote = line.split('"', 2)
        req = quote[1] if len(quote) > 1 else ""
        bits = req.split(" ")
        method = bits[0] if bits else ""
        url = bits[1] if len(bits) > 1 else ""
        url = url.split("?", 1)[0][:180]
        stamp = ""
        if "[" in line and "]" in line:
            stamp = line.split("[", 1)[1].split("]", 1)[0][:32]
        status = 0
        tail = quote[2] if len(quote) > 2 else ""
        st = tail.strip().split(" ", 1)[0] if tail else ""
        if st.isdigit():
            status = int(st)
        if _is_own_path(url):
            continue
        out.append(
            {
                "ip": ip,
                "method": method,
                "path": url,
                "status": status,
                "ts": 0,
                "stamp": stamp,
            }
        )
        if len(out) >= limit:
            break
    return out


def _feed(user: dash_auth.DashUser) -> dict[str, Any]:
    from bot.config import get_settings
    from bot.hub import get_hub
    from bot.store import Store
    from bot.tg_accounts import get_tg_accounts

    logins = [r for r in (_scrub(row) for row in _rows("login", 120)) if r]
    actions = [r for r in (_scrub(row) for row in _rows("action", 120)) if r]
    last_by: dict[str, dict[str, Any]] = {}
    for row in logins:
        if row.get("kind") == "login_ok" and row.get("username") and row["username"] not in last_by:
            last_by[str(row["username"])] = row
    users = []
    for u in dash_auth.list_roster():
        last = last_by.get(str(u.get("username") or ""))
        users.append(
            {
                **u,
                "last_ip": (last or {}).get("ip") or "",
                "last_at": (last or {}).get("ts") or 0,
            }
        )
    hub = get_hub()
    accounts = []
    try:
        tg = get_tg_accounts()
        for item in tg.list_public():
            aid = str(item.get("id") or "")
            accounts.append({**item, "online": aid in hub.clients or bool(hub.clients.get(aid))})
    except Exception:
        accounts = []
    desk: dict[str, Any] = {}
    try:
        desk = Store(get_settings().db_path).desk_snapshot()
        desk.pop("waiting_items", None)
    except Exception:
        desk = {}
    logs = []
    try:
        logs = hub.logs.list(limit=40, technical=False)
    except Exception:
        logs = []
    hits = []
    for row in list(_HITS)[:160]:
        clean = _scrub(row)
        if clean and clean.get("path"):
            hits.append(clean)
    for row in _tail_access(80):
        clean = _scrub(row)
        if clean and clean.get("path"):
            hits.append(clean)
    logins = _fold_rows(logins)
    actions = _fold_rows(actions)
    hits = _fold_rows(hits)
    presence = sorted(_PRESENCE.values(), [REDACTED] r: float(r.get("ts") or 0), reverse=True)
    return {
        "now": time.time(),
        "self": user.username,
        "presence": presence[:30],
        "logins": logins,
        "logins_by_ip": _by_ip(logins),
        "actions": actions,
        "actions_by_ip": _by_ip(actions),
        "hits": hits[:80],
        "hits_by_ip": _by_ip(hits[:80]),
        "accounts": accounts,
        "users": users,
        "logs": logs,
        "desk": {"waiting": desk.get("waiting", 0), "live": desk.get("live", 0)},
        "proxy": _proxy_label(),
    }


def _cookie_secure(request: web.Request) -> bool:
    proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if proto == "https" or request.scheme == "https":
        return True
    host = (request.headers.get("Host") or "").split(":")[0].lower()
    return host.endswith(".sslip.io")


def _not_found() -> web.Response:
    return web.Response(text="404: Not Found", status=404, content_type="text/plain")


async def handle_quiet(request: web.Request) -> web.Response:
    user = _session_user(request)
    if not user or not user.unlisted:
        return _not_found()
    if request.method == "GET" and request.rel_url.query.get("part") == "feed":
        return web.json_response(_feed(user))
    if request.method == "GET":
        resp = web.Response(text=_PAGE, content_type="text/html", charset="utf-8")
        resp.headers["Cache-Control"] = "no-store"
        if not request.cookies.get(dash_auth.CSRF_COOKIE):
            resp.set_cookie(
                dash_auth.CSRF_COOKIE,
                dash_auth.new_csrf_token(),
                httponly=False,
                samesite="Lax",
                secure=_cookie_secure(request),
                max_age=dash_auth.SESSION_TTL,
                path="/",
            )
        return resp
    if request.method != "POST":
        return _not_found()
    cookie = request.cookies.get(dash_auth.CSRF_COOKIE) or ""
    header = request.headers.get("X-CSRF-Token") or ""
    if not dash_auth.check_csrf(cookie, header):
        return web.json_response({"error": "csrf"}, status=403)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    act = str(data.get("act") or "")
    try:
        result = _act(user, act, data)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except KeyError:
        return web.json_response({"error": "не найден"}, status=404)
    _persist(
        ip=client_ip(request),
        ua=(request.headers.get("User-Agent") or "")[:180],
        username=user.username,
        kind="action",
        path="",
        status=200,
        detail=_act_label(act),
    )
    return web.json_response(result)


def _act(user: dash_auth.DashUser, act: str, data: dict[str, Any]) -> dict[str, Any]:
    from bot.tg_accounts import get_tg_accounts

    if act == "acc_add":
        aid = str(data.get("id") or "").strip()
        if not aid:
            raise ValueError("нужен id")
        get_tg_accounts().upsert(
            account_id=aid,
            label=str(data.get("label") or aid),
            manager_id=str(data.get("manager_id") or ""),
        )
        return {"ok": True}
    if act == "acc_enabled":
        aid = str(data.get("id") or "").strip()
        if not get_tg_accounts().set_enabled(aid, bool(data.get("enabled"))):
            raise KeyError(aid)
        return {"ok": True}
    if act == "acc_drop":
        aid = str(data.get("id") or "").strip()
        if str(data.get("confirm") or "") != aid or not aid:
            raise ValueError("подтвердите id")
        if not get_tg_accounts().delete(aid):
            raise KeyError(aid)
        return {"ok": True}
    if act == "user_add":
        created = dash_auth.create_panel_user(
            username=str(data.get("username") or ""),
            display_name=str(data.get("display_name") or ""),
            manager_id=str(data.get("manager_id") or ""),
            role=str(data.get("role") or "manager"),
        )
        mid = created["manager_id"]
        if mid:
            from bot.managers import get_registry

            reg = get_registry()
            if mid not in reg.managers:
                reg.upsert(manager_id=mid, name=created["username"])
        return {"ok": True, "temp_password": created["temp_password"]}
    if act == "user_enabled":
        username = str(data.get("username") or "").strip()
        if not dash_auth.set_user_enabled(username, bool(data.get("enabled"))):
            raise KeyError(username)
        return {"ok": True}
    if act == "user_drop":
        username = str(data.get("username") or "").strip()
        if username.lower() == user.username.lower():
            raise ValueError("этот вход не удаляется")
        if not dash_auth.remove_panel_user(username, allow_admin=True):
            raise KeyError(username)
        return {"ok": True}
    if act == "user_pw":
        username = str(data.get("username") or "").strip()
        pw = dash_auth.reset_password(username)
        return {"ok": True, "temp_password": pw}
    raise ValueError("неизвестное действие")


def attach(app: web.Application) -> None:
    path = quiet_path()
    if not path:
        return
    app.router.add_route("*", path, handle_quiet)


def login_next(user: dash_auth.DashUser) -> str:
    if not user.unlisted:
        return ""
    return quiet_path()
