# -*- coding: utf-8 -*-
"""Home24 admin dashboard — aiohttp. Гость видит только форму входа."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import webbrowser
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from bot.config import get_settings
from bot.dashboard import auth as dash_auth
from bot.hub import get_hub
from bot.managers import get_registry
from bot.rate_limit import OutreachLimiter
from bot.store import Store, dialog_brief, dialog_lane, dialog_tone
from bot.web_login import create_app as create_login_routes_app

logger = logging.getLogger("home24.dashboard")

STATIC = Path(__file__).resolve().parent / "static"
# Картинки едут вместе с кодом. data/brand перекрывает их, только если файл
# реально лежит на диске — выкладка без каталога data/ больше не роняет логотип.
PACKAGED_BRAND = Path(__file__).resolve().parent / "brand"
DATA_BRAND = Path("data/brand")


def resolve_brand_dir() -> Path:
    marker = "home24-logo.svg"
    if (DATA_BRAND / marker).is_file():
        return DATA_BRAND
    return PACKAGED_BRAND
HOST = (os.getenv("DASHBOARD_HOST") or "[REDACTED]").strip()
PORT = int(os.getenv("DASHBOARD_PORT") or os.getenv("HOME24_LOGIN_PORT") or "43125")
DEMO = (os.getenv("HOME24_DASHBOARD_DEMO") or "").strip().lower() in ("1", "true", "yes", "on")


def _asset_hash() -> str:
    h = hashlib.md5()
    for name in ("dashboard.js", "dashboard.css"):
        p = STATIC / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


ASSET_HASH = _asset_hash()

# Публичные пути без сессии (остальное → 401).
# QR Telegram и примеры рассылки только после входа: иначе чужой человек
# сканирует QR и забирает аккаунт.
_PUBLIC_EXACT = frozenset({"/", "/api/login", "/api/invite"})
_PUBLIC_PREFIX = ()  # invite page handled by exact + path check


def _store() -> Store:
    return Store(get_settings().db_path)


def _user(request: web.Request) -> dash_auth.DashUser | None:
    tok = request.cookies.get(dash_auth.COOKIE_NAME) or ""
    return dash_auth.parse_session_token(tok)


def _require(request: web.Request) -> dash_auth.DashUser:
    u = _user(request)
    if not u:
        raise web.HTTPUnauthorized(text='{"error":"unauthorized"}', content_type="application/json")
    return u


def _require_admin(request: web.Request) -> dash_auth.DashUser:
    u = _require(request)
    if not u.is_admin:
        raise web.HTTPForbidden(text='{"error":"forbidden"}', content_type="application/json")
    return u


def _client_ip(request: web.Request) -> str:
    """X-Forwarded-For только от локального nginx. Снаружи заголовок подделывается."""
    remote = (request.remote or "").split("%", 1)[0]
    if remote in ("[REDACTED]", "::1"):
        fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if fwd:
            return fwd
    return request.remote or ""


def _csrf_ok(request: web.Request) -> bool:
    cookie = request.cookies.get(dash_auth.CSRF_COOKIE) or ""
    header = request.headers.get("X-CSRF-Token") or ""
    return dash_auth.check_csrf(cookie, header)


def _cookie_secure(request: web.Request) -> bool:
    """Публичные туннели отдают HTTPS. Без Secure браузер куки не оставляет."""
    proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if proto == "https" or request.scheme == "https":
        return True
    host = (request.headers.get("Host") or "").split(":")[0].lower()
    return host.endswith(
        (
            ".serveousercontent.com",
            ".lhr.life",
            ".trycloudflare.com",
            ".localhost.run",
        )
    )


def _set_auth_cookies(
    resp: web.Response, user: dash_auth.DashUser, *, secure: bool, csrf: str = ""
) -> str:
    [REDACTED]
    csrf = csrf or dash_auth.new_csrf_token()
    resp.set_cookie(
        dash_auth.COOKIE_NAME,
        token,
        httponly=True,
        samesite="Lax",
        secure=secure,
        max_age=dash_auth.SESSION_TTL,
        path="/",
    )
    resp.set_cookie(
        dash_auth.CSRF_COOKIE,
        csrf,
        httponly=False,
        samesite="Lax",
        secure=secure,
        max_age=dash_auth.SESSION_TTL,
        path="/",
    )
    return csrf


def _user_public(u: dash_auth.DashUser) -> dict[str, Any]:
    return {
        "username": u.username,
        "role": u.role,
        "manager_id": u.manager_id,
        "display_name": u.display_name,
        "is_admin": u.is_admin,
        "must_change_password": bool(u.must_change_password),
    }


def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    if path.startswith("/invite/") or path.startswith("/brand/"):
        return True
    if path.startswith("/static/fonts"):
        return True
    return False


# Вход как home24.msk.ru: камень #F4F4F2, чёрный набор, Spectral + Inter.
_GATE_CSS = """
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;min-height:100vh;font-family:Inter,system-ui,sans-serif;color:#111;background:#F4F4F2}
::selection{background:rgba(213,161,122,.38);color:inherit}
.bar{position:sticky;top:0;z-index:2;height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 16px;border-bottom:1px solid rgba(17,17,17,.1);background:rgba(244,244,242,.88);backdrop-filter:blur(12px)}
.bar .side{font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:#111}
.bar img{height:46px;width:auto;display:block}
.sheet{max-width:460px;margin:0 auto;padding:72px 20px 80px}
.eyebrow{margin:0 0 14px;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#6B6B68}
h1{margin:0;font-family:Spectral,Georgia,serif;font-weight:500;font-size:clamp(2.4rem,6vw,3.4rem);letter-spacing:-.03em;line-height:1.02}
.lede{margin:16px 0 0;color:#6B6B68;font-size:15px;line-height:1.7;max-width:34rem}
label{display:block;margin:22px 0 8px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#6B6B68}
input{width:100%;padding:14px 14px;border:1px solid rgba(17,17,17,.12);border-radius:14px;background:#fff;color:#111;font-size:16px;font-family:inherit}
input:focus{outline:none;border-color:#111}
button{margin-top:22px;width:100%;height:48px;border:0;border-radius:18px;background:#111;color:#fff;cursor:pointer;font-family:inherit;font-size:11px;font-weight:500;letter-spacing:.14em;text-transform:uppercase}
button:hover{background:#3A3A38}
.err{color:#9B4B33;margin-top:14px;min-height:1.2em;font-size:14px}
.foot{margin-top:28px;color:#6B6B68;font-size:12px;line-height:1.6}
"""

LOGIN_HTML = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Home24 — вход</title>
<link rel="icon" href="/brand/favicon.svg"/>
<link rel="stylesheet" href="/static/fonts.css"/>
<style>__GATE_CSS__</style></head><body>
<header class="bar">
  <span class="side">Меню</span>
  <img src="/brand/home24-logo.svg" alt="Home24"/>
  <span class="side">Москва</span>
</header>
<main class="sheet">
<p class="eyebrow">Панель менеджеров</p>
<h1>Вход в смену.</h1>
<p class="lede">Логин и пароль. После входа откроются ваши диалоги, архив и рассылка.</p>
<form id="f">
<label>Логин<input name="u" autocomplete="username" required/></label>
<label>Пароль<input name="p" type="password" autocomplete="current-password" required/></label>
<button type="submit">Войти</button>
<div class="err" id="e"></div>
</form>
<p class="foot">Посуточная аренда в Москве и МО напрямую.</p>
</main>
<script>
document.getElementById('f').onsubmit=async(ev)=>{
  ev.preventDefault();
  document.getElementById('e').textContent='';
  const fd=new FormData(ev.target);
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:fd.get('u'),[REDACTED]
  const j=await r.json().catch(()=>({}));
  if(!r.ok){document.getElementById('e').textContent=j.error||'Ошибка входа';return;}
  location.href=j.next||'/app';
};
</script></body></html>
"""

INVITE_HTML = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Home24 — пароль</title>
<link rel="icon" href="/brand/favicon.svg"/>
<link rel="stylesheet" href="/static/fonts.css"/>
<style>__GATE_CSS__</style></head><body>
<header class="bar">
  <span class="side">Меню</span>
  <img src="/brand/home24-logo.svg" alt="Home24"/>
  <span class="side">Москва</span>
</header>
<main class="sheet">
<p class="eyebrow">Первый вход</p>
<h1>Свой пароль.</h1>
<p class="lede">Два одинаковых поля, минимум 8 символов. Временный пароль после этого не нужен.</p>
<form id="f">
<label>Новый пароль<input name="p" type="password" minlength="8" required/></label>
<label>Ещё раз<input name="p2" type="password" minlength="8" required/></label>
<button type="submit">Сохранить и войти</button>
<div class="err" id="e"></div>
</form>
</main>
<script>
const [REDACTED]
document.getElementById('f').onsubmit=async(ev)=>{
  ev.preventDefault();
  const fd=new FormData(ev.target);
  if(fd.get('p')!==fd.get('p2')){document.getElementById('e').textContent='Пароли не совпадают';return;}
  const r=await fetch('/api/invite',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token,[REDACTED]
  const j=await r.json().catch(()=>({}));
  if(!r.ok){document.getElementById('e').textContent=j.error||'Ошибка';return;}
  location.href='/app';
};
</script></body></html>
"""

LOGIN_HTML = LOGIN_HTML.replace("__GATE_CSS__", _GATE_CSS)
INVITE_HTML = INVITE_HTML.replace("__GATE_CSS__", _GATE_CSS)

def _ico(path_d: str) -> str:
    return (
        '<svg class="nav-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round" '
        f'd="{path_d}"/></svg>'
    )


_ICO_CHAT = _ico(
    "M4 6.5h16a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H9l-4 3v-3H4A1.5 1.5 0 0 1 2.5 16V8A1.5 1.5 0 0 1 4 6.5z"
)
_ICO_QUEUE = _ico("M12 7v5l3 2M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z")
_ICO_LOGS = _ico("M6 7h12M6 12h12M6 17h8")
_ICO_CTRL = _ico("M5 8h14M5 16h14M8 5v6M16 13v6")
_ICO_MAIL = _ico("M4 7h16v10H4zM4 7l8 6 8-6")
_ICO_DESK = _ico("M4 5h16v3H4zM6 8v11M18 8v11M4 19h16")
_ICO_USERS = _ico(
    "M16 19v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 17.5V19M11.5 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM17 11a2.5 2.5 0 1 0 0-5"
)
_ICO_SET = _ico(
    "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM12 3.5v2M12 18.5v2M4.9 6.5l1.4 1.4M17.7 16.1l1.4 1.4M3.5 12h2M18.5 12h2M4.9 17.5l1.4-1.4M17.7 7.9l1.4-1.4"
)
_ICO_ACC = _ico("M7 8.5a5 5 0 0 1 10 0c0 4-5 7.5-5 7.5S7 12.5 7 8.5zM9.5 18.5h5")
_ICO_MORE = _ico("M6 12h.01M12 12h.01M18 12h.01")
_ICO_MENU = _ico("M5 7h14M5 12h14M5 17h14")
_ICO_COLLAPSE = _ico("M15 6l-6 6 6 6")
_ICO_BELL = _ico(
    "M6.5 16.5h11M8 16.5V11a4 4 0 0 1 8 0v5.5M10.5 16.5a1.5 1.5 0 0 0 3 0"
)
_ICO_SEARCH = _ico("M10.5 4.5a6 6 0 1 0 4.2 10.3L19.5 19.5M10.5 4.5a6 6 0 0 1 0 12")
_ICO_CLOSE = _ico("M7 7l10 10M17 7L7 17")

INDEX_HTML = """<!doctype html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Home24 — панель</title>
<link rel="icon" href="/brand/favicon.svg"/>
<link rel="stylesheet" href="/static/fonts.css"/>
<link rel="stylesheet" href="/static/dashboard.css?v=__ASSET_HASH__"/>
</head>
<body>
<div id="pwShell" class="login-wrap hidden">
  <form class="login-card" id="pwForm">
    <h2>Смените пароль</h2>
    <p class="muted">Первый вход — задайте свой пароль (мин. 8 символов).</p>
    <label class="field">Текущий (временный)<input id="pwOld" type="password" required autocomplete="current-password"/></label>
    <label class="field">Новый пароль<input id="pwNew" type="password" minlength="8" required autocomplete="new-password"/></label>
    <label class="field">Ещё раз<input id="pwNew2" type="password" minlength="8" required autocomplete="new-password"/></label>
    <div class="form-actions"><button class="btn" type="submit">Сохранить</button></div>
    <div class="err" id="pwErr"></div>
  </form>
</div>

<div id="appShell" class="app hidden">
  <div id="sideBackdrop" class="side-backdrop" hidden></div>
  <aside class="sidebar" id="sidebar">
    <div class="brand">
      <img src="/brand/home24-logo.svg" alt="Home24" width="40" height="40"/>
      <div class="brand-text">
        <h1>Home24</h1>
        <small>команда продаж</small>
      </div>
      <button type="button" class="btn-icon side-collapse" id="btnSideCollapse" title="Свернуть меню" aria-label="Свернуть меню">__ICO_COLLAPSE__</button>
    </div>
    <nav class="nav" id="sideNav">
      <button type="button" data-page="dialogs" class="active"><span class="nav-ico" aria-hidden="true">__ICO_CHAT__</span><span class="nav-label">Диалоги</span></button>
      <button type="button" data-page="desk" id="navDesk" class="hidden"><span class="nav-ico" aria-hidden="true">__ICO_DESK__</span><span class="nav-label">Стол</span></button>
      <button type="button" data-page="mail"><span class="nav-ico" aria-hidden="true">__ICO_MAIL__</span><span class="nav-label">Рассылка</span></button>
      <button type="button" data-page="queue"><span class="nav-ico" aria-hidden="true">__ICO_QUEUE__</span><span class="nav-label">Очередь</span></button>
      <button type="button" data-page="logs"><span class="nav-ico" aria-hidden="true">__ICO_LOGS__</span><span class="nav-label">Журнал</span></button>
      <button type="button" data-page="controls"><span class="nav-ico" aria-hidden="true">__ICO_CTRL__</span><span class="nav-label">Управление</span></button>
      <button type="button" data-page="prefs" id="navPrefs"><span class="nav-ico" aria-hidden="true">__ICO_SET__</span><span class="nav-label">Мои настройки</span></button>
      <button type="button" data-page="users" id="navUsers" class="hidden"><span class="nav-ico" aria-hidden="true">__ICO_USERS__</span><span class="nav-label">Пользователи</span></button>
      <button type="button" data-page="settings" id="navSettings" class="hidden"><span class="nav-ico" aria-hidden="true">__ICO_SET__</span><span class="nav-label">Настройки</span></button>
      <button type="button" data-page="accounts" id="navAccounts" class="hidden"><span class="nav-ico" aria-hidden="true">__ICO_ACC__</span><span class="nav-label">Аккаунты</span></button>
    </nav>
    <div class="side-foot">
      <div id="userPill" class="pill">—</div>
      <div class="row side-actions">
        <button type="button" class="btn secondary" id="btnTheme" title="Тема">Тема</button>
        <button type="button" class="btn secondary" id="btnLogout">Выйти</button>
      </div>
    </div>
  </aside>
  <main class="main">
    <div class="topbar">
      <div class="topbar-left">
        <button type="button" class="btn-icon mobile-menu" id="btnMobileMenu" title="Меню" aria-label="Меню"><span class="menu-ico">__ICO_MENU__</span><span class="shell-menu-label">Меню</span></button>
        <div>
          <h2 id="pageTitle">Диалоги</h2>
          <p class="page-sub" id="pageSub">Чаты с клиентами</p>
        </div>
      </div>
      <nav class="shell-nav" id="shellNav" aria-label="Разделы">
        <button type="button" data-page="dialogs" class="active">Диалоги</button>
        <button type="button" data-page="desk" id="shellDesk" class="hidden">Стол</button>
        <button type="button" data-page="mail">Рассылка</button>
        <button type="button" data-page="queue">Очередь</button>
        <button type="button" data-page="logs">Журнал</button>
        <button type="button" data-page="controls">Управление</button>
      </nav>
      <div class="topbar-right">
        <span id="demoPill" class="pill demo hidden">DEMO — демо-данные</span>
        <button type="button" class="btn-bell" id="btnBell" title="Уведомления">
          <span class="bell-icon" aria-hidden="true">__ICO_BELL__</span>
          <span class="badge hidden" id="bellBadge">0</span>
        </button>
      </div>
    </div>
    <div id="statsStrip" class="stats-strip" aria-live="polite"></div>
    <div id="toastHost" class="toast-host"></div>
    <div id="notifyPanel" class="notify-panel hidden">
      <div class="notify-head"><strong>Уведомления</strong>
        <button type="button" class="btn secondary" id="btnNotifyClose">Закрыть</button></div>
      <div id="notifyList" class="notify-list"></div>
    </div>

    <section data-view="dialogs" class="grid-2 dialogs-layout">
      <div class="card clients-card">
        <div class="clients-head">
          <div class="clients-title">
            <h3>Клиенты</h3>
            <button type="button" class="btn-icon" id="btnHideList" title="Убрать список" aria-label="Убрать список клиентов">__ICO_COLLAPSE__</button>
          </div>
          <div class="lane-stats" id="laneStats"></div>
          <label class="search-wrap">
            <span class="search-ico" aria-hidden="true">__ICO_SEARCH__</span>
            <input id="dialogSearch" type="search" placeholder="Поиск клиента… (/)" autocomplete="off"/>
          </label>
        </div>
        <div class="dialog-filter-bar" id="dialogFilterBar" role="tablist" aria-label="Фильтр диалогов">
          <button type="button" class="filter-chip active" data-dfilter="mine">Мои</button>
          <button type="button" class="filter-chip" data-dfilter="all">Все</button>
          <button type="button" class="filter-chip" data-dfilter="needs_reply">Ждут ответа</button>
          <button type="button" class="filter-chip" data-dfilter="bot">Ведёт бот</button>
          <button type="button" class="filter-chip" data-dfilter="manager">У менеджера</button>
          <button type="button" class="filter-chip" data-dfilter="pinned">На булавке</button>
          <button type="button" class="filter-chip" data-dfilter="archive">Архив</button>
        </div>
        <div class="dialog-filter-bar" id="laneBar" role="tablist" aria-label="Исход диалога">
          <button type="button" class="filter-chip active" data-lane="">Все исходы</button>
          <button type="button" class="filter-chip" data-lane="hot">Срочные</button>
          <button type="button" class="filter-chip" data-lane="work">В работе</button>
          <button type="button" class="filter-chip" data-lane="later">Позже</button>
          <button type="button" class="filter-chip" data-lane="deal">Сделка</button>
          <button type="button" class="filter-chip" data-lane="lost">Не вышло</button>
          <button type="button" class="filter-chip" data-lane="issue">Проблема</button>
        </div>
        <div class="tone-legend" aria-hidden="true">
          <span><i class="swatch swatch-ready"></i>Срочные</span>
          <span><i class="swatch swatch-work"></i>В работе</span>
          <span><i class="swatch swatch-done"></i>Закрытые</span>
        </div>
        <div class="ready-strip hidden" id="readyStrip"></div>
        <div class="list" id="dialogList"></div>
      </div>
      <div class="card chat">
        <button type="button" class="btn secondary list-reveal" id="btnShowList">Клиенты</button>
        <div id="chatEmpty" class="chat-empty">
          <div class="empty-icon" aria-hidden="true">__ICO_CHAT__</div>
          <div class="empty-title">Выберите диалог</div>
          <div class="empty-sub">Черновики ответа сохраняются для каждого клиента отдельно</div>
        </div>
        <div id="chatBody" class="chat-body hidden">
          <div class="chat-meta">
            <div class="chat-title-row">
              <div class="av chat-av" id="chatAvatar">?</div>
              <div class="chat-title-block">
                <strong id="chatTitle">—</strong>
                <div class="chat-pills">
                  <span class="pill pill-stage" id="chatStage">—</span>
                  <span class="pill" id="chatNext">—</span>
                  <span class="pill" id="chatMgr">—</span>
                  <span class="pill" id="chatTg">—</span>
                  <span class="pill" id="takeState">—</span>
                </div>
                <div class="chat-brief" id="chatBrief"></div>
              </div>
              <div class="chat-actions">
                <button type="button" class="btn secondary" id="btnCopyCard" title="Скопировать карточку гостя">Карточка</button>
                <button type="button" class="btn secondary" id="btnExport" title="Скопировать переписку">Переписка</button>
                <button type="button" class="btn secondary" id="btnPin">Булавка</button>
                <button type="button" class="btn secondary" id="btnArchive">В архив</button>
                <button type="button" class="btn secondary" id="btnTake">Перехватить</button>
                <button type="button" class="btn secondary hidden" id="btnReturn">Вернуть боту</button>
              </div>
            </div>
          </div>
          <div class="msgs" id="msgs"></div>
          <div class="composer">
            <label class="note-row">
              <span>Заметка смены <em>гость не видит</em></span>
              <textarea id="chatNote" rows="2" placeholder="Договорённость, предоплата, что не писать в чат…"></textarea>
            </label>
            <div class="composer-tools">
              <button type="button" class="btn secondary btn-sm" id="btnTemplates" title="Шаблоны ответов (/)" aria-haspopup="dialog">Шаблоны</button>
              <span class="muted char-count" id="charCount">0</span>
            </div>
            <div id="tplPicker" class="tpl-picker hidden" role="dialog" aria-label="Шаблоны ответов">
              <div class="tpl-picker-head">
                <input type="search" id="tplSearch" class="ctl" placeholder="Поиск шаблона…" autocomplete="off"/>
                <button type="button" class="btn secondary btn-sm" id="tplClose" title="Закрыть" aria-label="Закрыть">__ICO_CLOSE__</button>
              </div>
              <div class="tpl-cats" id="tplCats"></div>
              <div class="tpl-list" id="tplList"></div>
              <div class="tpl-picker-foot">
                <button type="button" class="btn secondary btn-sm" id="tplAddPersonal">+ Личный</button>
                <span class="muted tpl-hint">Вставка в поле — можно править. / в пустом поле открывает список</span>
              </div>
            </div>
            <textarea id="replyText" rows="1" placeholder="Ответ клиенту…  (/ — шаблоны)"></textarea>
            <div class="composer-bar">
              <span class="muted composer-hint">Enter — отправить · Shift+Enter — новая строка · / — шаблоны</span>
              <button type="button" class="btn" id="btnSend">Отправить</button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section data-view="desk" class="hidden page-stack">
      <div id="deskStats" class="desk-stats"></div>
      <div class="form-grid">
        <div class="card">
          <div class="card-head"><h3>Ждут ответа</h3></div>
          <div id="deskWaiting" class="desk-list card-pad"></div>
        </div>
        <div class="card">
          <div class="card-head"><h3>Поиск по переписке</h3></div>
          <div class="card-pad form-stack">
            <label class="field">Фраза из чата
              <input id="deskQuery" class="ctl" placeholder="например, Прокшино или завтра" autocomplete="off"/>
            </label>
            <p class="muted lead">Ищет по всем сообщениям. Менеджер видит только свои чаты, админ — все.</p>
            <div id="deskHits" class="desk-list"></div>
          </div>
        </div>
      </div>
      <div class="card" id="deskAdminCard">
        <div class="card-head">
          <h3>Тихие чаты</h3>
          <button type="button" class="btn secondary" id="btnArchiveQuiet">В архив старше 3 дней</button>
        </div>
        <div class="card-pad">
          <p class="muted lead" id="deskQuietLead">Чаты без последнего сообщения от гостя и без булавки. Кто ждёт ответа, остаётся в смене.</p>
          <pre id="deskOut" class="out-box"></pre>
        </div>
      </div>
    </section>

    <section data-view="queue" class="hidden page-stack">
      <div id="queueProgress" class="progress-grid"></div>
      <div class="card">
        <div class="card-head">
          <h3>Очередь первых сообщений</h3>
          <label class="search-wrap compact">
            <span class="search-ico" aria-hidden="true">__ICO_SEARCH__</span>
            <input id="queueSearch" type="search" placeholder="Фильтр менеджера…" autocomplete="off"/>
          </label>
        </div>
        <div class="table-wrap">
          <table class="table sticky-head">
            <thead><tr>
              <th>Менеджер</th><th>Сегодня</th><th>Неделя</th><th>Осталось</th><th>В очереди</th>
              <th>Окно</th><th>Сессия</th><th>Статус</th>
            </tr></thead>
            <tbody id="queueBody"></tbody>
          </table>
        </div>
      </div>
    </section>

    <section data-view="logs" class="hidden page-stack">
      <div class="card log-card">
        <div class="card-head">
          <h3>Журнал</h3>
          <div class="toolbar">
            <select id="logLevel" class="ctl">
              <option value="">все уровни</option>
              <option>INFO</option><option>WARNING</option><option>ERROR</option>
            </select>
            <input id="logMgr" class="ctl" placeholder="manager_id" autocomplete="off"/>
            <label class="toggle"><input type="checkbox" id="logFollow" checked/> авто-скролл</label>
            <label class="toggle" title="aiohttp / telethon.network"><input type="checkbox" id="logTechnical"/> технические</label>
            <button type="button" class="btn secondary btn-sm" id="btnLogRefresh">Обновить</button>
          </div>
        </div>
        <div id="logBox" class="log-box" tabindex="0"></div>
      </div>
    </section>

    <section data-view="mail" class="hidden page-stack">
      <div class="form-grid">
        <div class="card">
          <div class="card-head"><h3>Кому написать</h3></div>
          <div class="card-pad form-stack">
            <p class="muted lead" id="mailWindow">Проверяю окно отправки…</p>
            <label class="field">Номера
              <textarea id="mailPhones" class="ctl mail-box" rows="6" placeholder="[REDACTED], Мария&#10;[REDACTED]"></textarea>
            </label>
            <p class="muted lead">Каждый номер с новой строки. Имя после запятой попадёт в приветствие. Уже отправленные и стоп-лист бот не трогает.</p>
            <div class="row">
              <button type="button" class="btn" id="btnMailNow">Отправить сейчас</button>
              <button type="button" class="btn secondary" id="btnMailQueue">В очередь на окно</button>
            </div>
            <pre id="mailOut" class="out-box"></pre>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h3>Как звучит первое сообщение</h3></div>
          <div class="card-pad">
            <div id="mailSamples" class="mail-samples"></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-head">
          <h3>Очередь</h3>
          <button type="button" class="btn secondary btn-sm" id="btnMailRefresh">Обновить</button>
        </div>
        <div class="table-wrap">
          <table class="table sticky-head">
            <thead><tr><th>Номер</th><th>Имя</th><th>Статус</th><th>Заметка</th></tr></thead>
            <tbody id="mailBody"></tbody>
          </table>
        </div>
      </div>
    </section>

    <section data-view="controls" class="hidden page-stack">
      <div class="form-grid">
        <div class="card">
          <div class="card-head"><h3>Рассылка</h3></div>
          <div class="card-pad form-stack">
            <label class="field">Менеджер
              <select id="ctrlMgr" class="ctl"></select>
            </label>
            <div class="row">
              <button type="button" class="btn" id="btnOpenMail">Открыть рассылку</button>
              <button type="button" class="btn secondary" id="btnPreview">Кто в очереди</button>
              <button type="button" class="btn danger" id="btnSendStop">Стоп</button>
            </div>
            <p class="muted lead">Номера и первое сообщение — в разделе «Рассылка». Здесь можно остановить уже идущую партию.</p>
            <pre id="ctrlOut" class="out-box"></pre>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h3>Стоп-лист и закрепление</h3></div>
          <div class="card-pad form-stack">
            <div class="field-row">
              <label class="field grow">Телефон или chat_id
                <input id="stopPhone" class="ctl" placeholder="+7900… или chat_id" autocomplete="off"/>
                <span class="field-hint" id="stopPhoneHint"></span>
              </label>
              <button type="button" class="btn secondary" id="btnAddStop">В стоп-лист</button>
            </div>
            <div class="field-row">
              <label class="field grow">Клиент
                <input id="assignPhone" class="ctl" placeholder="телефон / @user" autocomplete="off"/>
                <span class="field-hint" id="assignPhoneHint"></span>
              </label>
              <label class="field">Менеджер
                <select id="assignMgr" class="ctl"></select>
              </label>
              <button type="button" class="btn secondary" id="btnAssign">Закрепить</button>
            </div>
            <div class="table-wrap">
              <table class="table sticky-head">
                <thead><tr><th>Стоп</th><th>Тип</th><th></th></tr></thead>
                <tbody id="stopList"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section data-view="users" class="hidden page-stack">
      <div class="card">
        <div class="card-head">
          <h3>Команда Home24</h3>
          <label class="search-wrap compact">
            <span class="search-ico" aria-hidden="true">__ICO_SEARCH__</span>
            <input id="usersSearch" type="search" placeholder="Поиск…" autocomplete="off"/>
          </label>
        </div>
        <div class="card-pad form-stack">
          <div class="field-row wrap">
            <label class="field">Распределение клиентов
              <select id="distMode" class="ctl">
                <option value="even">равномерно по активным</option>
                <option value="manual">вручную (не трогать)</option>
              </select>
            </label>
            <button type="button" class="btn secondary" id="btnDistSave">Сохранить режим</button>
            <button type="button" class="btn secondary" id="btnRedistribute">Раздать незакреплённых</button>
          </div>
          <div class="field-row wrap">
            <label class="field"><span>Логин</span>
              <input id="newUserLogin" class="ctl" placeholder="логин менеджера" autocomplete="off"/>
              <span class="field-hint" id="newUserLoginHint"></span>
            </label>
            <label class="field"><span>Имя</span>
              <input id="newUserName" class="ctl" placeholder="отображаемое имя" autocomplete="off"/>
            </label>
            <label class="field"><span>manager_id</span>
              <input id="newUserMid" class="ctl" placeholder="как в managers.json" autocomplete="off"/>
              <span class="field-hint" id="newUserMidHint"></span>
            </label>
            <button type="button" class="btn" id="btnCreateUser">Создать менеджера</button>
          </div>
          <div id="teamRoster" class="team-grid"></div>
          <pre id="usersOut" class="out-box"></pre>
          <div class="table-wrap">
            <table class="table sticky-head">
              <thead><tr><th>Логин</th><th>Роль</th><th>manager_id</th><th>Статус</th><th></th></tr></thead>
              <tbody id="usersBody"></tbody>
            </table>
          </div>
        </div>
      </div>
    </section>

    <section data-view="prefs" class="hidden page-stack prefs-page">
      <div class="card">
        <div class="card-head"><h3>Профиль</h3></div>
        <div class="card-pad form-stack">
          <p class="muted lead">Личные удобства. Лимиты, аккаунты Telegram и админ-настройки здесь недоступны.</p>
          <div class="form-grid prefs-grid">
            <label class="field">Отображаемое имя
              <input id="prefDisplayName" class="ctl" maxlength="80" autocomplete="nickname"/>
            </label>
            <label class="field">Подпись для шаблонов <code>{менеджер}</code>
              <input id="prefSignature" class="ctl" maxlength="80" placeholder="как в шаблонах, напр. Анна"/>
            </label>
          </div>
          <div class="form-actions">
            <button type="button" class="btn" id="btnPrefProfileSave">Сохранить профиль</button>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-head">
          <h3>Мои шаблоны</h3>
          <button type="button" class="btn secondary btn-sm" id="btnPrefTplAdd">+ Шаблон</button>
        </div>
        <div class="card-pad form-stack">
          <p class="muted lead">Личные шаблоны рядом с общими приветствиями/прощаниями. Плейсхолдеры: <code>{имя}</code> <code>{менеджер}</code>.</p>
          <div id="prefTplList"></div>
          <pre id="prefTplOut" class="out-box"></pre>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Пароль</h3></div>
        <div class="card-pad form-stack">
          <div class="form-grid prefs-grid">
            <label class="field">Текущий пароль<input id="prefPwOld" class="ctl" type="password" autocomplete="current-password"/></label>
            <label class="field">Новый пароль<input id="prefPwNew" class="ctl" type="password" minlength="8" autocomplete="new-password"/></label>
            <label class="field">Ещё раз<input id="prefPwNew2" class="ctl" type="password" minlength="8" autocomplete="new-password"/></label>
          </div>
          <div class="form-actions">
            <button type="button" class="btn secondary" id="btnPrefPwSave">Сменить пароль</button>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Интерфейс и уведомления</h3></div>
        <div class="card-pad form-stack">
          <div class="form-grid prefs-grid">
            <label class="field">Тема
              <select id="prefTheme" class="ctl">
                <option value="dark">Тёмная</option>
                <option value="light">Светлая</option>
                <option value="system">Как в системе</option>
              </select>
            </label>
            <label class="field">Размер шрифта в чатах
              <select id="prefFontSize" class="ctl">
                <option value="sm">Мельче</option>
                <option value="md">Обычный</option>
                <option value="lg">Крупнее</option>
              </select>
            </label>
            <label class="field">Enter в композере
              <select id="prefComposerEnter" class="ctl">
                <option value="send">Enter — отправить</option>
                <option value="newline">Enter — новая строка (Ctrl+Enter — отправить)</option>
              </select>
            </label>
            <label class="field">Фильтр диалогов по умолчанию
              <select id="prefDialogFilter" class="ctl">
                <option value="mine">Мои</option>
                <option value="all">Все доступные</option>
                <option value="needs_reply">Ждут ответа</option>
                <option value="bot">Ведёт бот</option>
                <option value="manager">У менеджера</option>
              </select>
            </label>
          </div>
          <label class="check-row"><input type="checkbox" id="prefCompact"/> Компактный режим чатов</label>
          <label class="check-row"><input type="checkbox" id="prefNotifySound"/> Звук при новом сообщении клиента</label>
          <label class="check-row"><input type="checkbox" id="prefNotifyBrowser"/> Браузерные уведомления</label>
          <label class="check-row"><input type="checkbox" id="prefNotifyToast"/> Тосты в панели</label>
          <div class="form-actions">
            <button type="button" class="btn" id="btnPrefUiSave">Сохранить</button>
          </div>
          <pre id="prefOut" class="out-box"></pre>
        </div>
      </div>
    </section>

    <section data-view="settings" class="hidden page-stack">
      <div class="card">
        <div class="card-head"><h3>Лимиты и доли</h3></div>
        <div class="card-pad form-stack">
          <p class="muted lead">Основной аккаунт: <b>30/день</b>, <b>210/неделя</b>. Потенциал: <b>1260</b> (210 × 6). Пауза между первыми сообщениями 240 с, не больше 4 в час. Окно 10:00–20:00 МСК. FloodWait/PeerFlood — стоп на сегодня. После нового входа — тишина outreach (по умолчанию 24ч): бот только слушает и отвечает.</p>
          <div id="settingsWarn" class="alert bad hidden"></div>
          <div id="settingsAccounts"></div>
          <div id="settingsManagers"></div>
          <div class="settings-block">
            <h4>Сервисные отчёты</h4>
            <p class="muted lead">Статус «online» и ход рассылки — в панели. В Telegram Избранное по умолчанию <b>выкл.</b> (без дублей и пачек).</p>
            <label class="check-row"><input type="checkbox" id="prefSavedReports"/> Слать сервисные отчёты в Избранное Telegram</label>
          </div>
          <div class="settings-block">
            <h4>Окна проверки (офлайн-присутствие)</h4>
            <p class="muted lead">Сессия одна и постоянная, но статус аккаунта — <b>offline</b>. Бот читает и отвечает пачками раз в N минут (±jitter), ночью — реже. Ответ менеджера из панели уходит сразу.</p>
            <label class="check-row"><input type="checkbox" id="prefCheckWindows" checked/> Включить окна проверки</label>
            <label class="field">Интервал, мин <input id="prefCheckInterval" class="ctl" type="number" min="1" step="0.5" value="3"/></label>
            <label class="field">Jitter 0–0.9 <input id="prefCheckJitter" class="ctl" type="number" min="0" max="0.9" step="0.05" value="0.3"/></label>
            <label class="field">Ночь с (час) <input id="prefNightStart" class="ctl" type="number" min="0" max="23" value="23"/></label>
            <label class="field">Ночь до (час) <input id="prefNightEnd" class="ctl" type="number" min="0" max="23" value="8"/></label>
            <label class="field">Ночной интервал, мин <input id="prefNightInterval" class="ctl" type="number" min="1" step="1" value="15"/></label>
            <label class="field">Active mode: тишина гостя, мин <input id="prefActiveIdle" class="ctl" type="number" min="1" step="1" value="10" title="После ответа на гостя отвечаем сразу, пока гость молчит не дольше N минут"/></label>
            <p class="muted lead">Пока диалог активен (гость писал недавно) — ответ сразу, только с паузой «печатает». После тишины — снова окна проверки и offline.</p>
          </div>
          <div class="form-actions">
            <button type="button" class="btn" id="btnSettingsSave">Сохранить лимиты</button>
          </div>
          <pre id="settingsOut" class="out-box"></pre>
        </div>
      </div>
      <div class="card">
        <div class="card-head">
          <h3>Шаблоны ответов</h3>
          <button type="button" class="btn secondary btn-sm" id="btnTplNew">+ Шаблон</button>
        </div>
        <div class="card-pad form-stack">
          <p class="muted lead">Общие шаблоны для всех менеджеров (файл <code>data/templates.json</code>). По умолчанию только приветствие при перехвате и прощание. Плейсхолдеры: <code>{имя}</code> <code>{менеджер}</code>. Даты, гостей и район бот уже собирает сам.</p>
          <div id="settingsTemplates"></div>
          <pre id="tplSettingsOut" class="out-box"></pre>
        </div>
      </div>
    </section>

    <section data-view="accounts" class="hidden page-stack">
      <div class="card accounts-card">
        <div class="card-head">
          <h3>Telegram бота (аккаунты компании)</h3>
        </div>
        <div id="accountsBanner" class="alert bad hidden card-pad"></div>
        <div id="accountsStatusList" class="card-pad"></div>
        <p class="muted card-pad lead">Только админ. До <b>5 SIM</b> компании на этом ПК/сети (tdata / QR / код), <b>без прокси</b>. Один аккаунт — все менеджеры делят его; несколько — каждый можно привязать к веб-менеджеру в Настройках. Аккаунт <b>main</b>: 30/день и 210/неделя, выше панель не поднимет. Менеджеры работают только в панели. Панель не падает при отзыве сессии — войдите снова здесь.</p>
        <iframe src="about:blank" data-src="/accounts/" title="Вход Telegram" class="accounts-frame" id="accountsFrame"></iframe>
      </div>
    </section>
  </main>
  <nav class="bottom-nav" id="bottomNav" aria-label="Основное меню">
    <button type="button" data-page="dialogs" class="active"><span class="nav-ico">__ICO_CHAT__</span><span>Чаты</span></button>
    <button type="button" data-page="mail"><span class="nav-ico">__ICO_MAIL__</span><span>Рассылка</span></button>
    <button type="button" data-page="logs"><span class="nav-ico">__ICO_LOGS__</span><span>Журнал</span></button>
    <button type="button" data-page="controls"><span class="nav-ico">__ICO_CTRL__</span><span>Управл.</span></button>
    <button type="button" data-page="more" id="btnNavMore"><span class="nav-ico">__ICO_MORE__</span><span>Ещё</span></button>
  </nav>
</div>
<script src="/static/dashboard.js?v=__ASSET_HASH__"></script>
</body></html>
""".replace("__ICO_CHAT__", _ICO_CHAT).replace("__ICO_QUEUE__", _ICO_QUEUE).replace(
    "__ICO_LOGS__", _ICO_LOGS
).replace("__ICO_CTRL__", _ICO_CTRL).replace("__ICO_USERS__", _ICO_USERS).replace(
    "__ICO_SET__", _ICO_SET
).replace("__ICO_ACC__", _ICO_ACC).replace("__ICO_MORE__", _ICO_MORE).replace(
    "__ICO_MENU__", _ICO_MENU
).replace("__ICO_COLLAPSE__", _ICO_COLLAPSE).replace("__ICO_BELL__", _ICO_BELL).replace(
    "__ICO_SEARCH__", _ICO_SEARCH
).replace("__ICO_CLOSE__", _ICO_CLOSE).replace("__ICO_MAIL__", _ICO_MAIL).replace(
    "__ICO_DESK__", _ICO_DESK
).replace(
    "__ASSET_HASH__", ASSET_HASH
)


@web.middleware
async def harden_headers_middleware(request: web.Request, handler):
    resp = await handler(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    return resp


@web.middleware
async def trail_middleware(request: web.Request, handler):
    resp = await handler(request)
    try:
        from bot.dashboard.ingress import note_request

        note_request(request, int(getattr(resp, "status", 0) or 0))
    except Exception:
        pass
    return resp


@web.middleware
async def cache_control_middleware(request: web.Request, handler):
    """Не кэшировать /app и статику панели — иначе Windows Edge держит старый JS."""
    resp = await handler(request)
    path = request.path
    if path == "/app" or path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@web.middleware
async def security_middleware(request: web.Request, handler):
    path = request.path
    from bot.dashboard.ingress import quiet_path

    if quiet_path() and path == quiet_path():
        return await handler(request)
    # Публичные + /app (сам сделает редирект на логин)
    if _is_public_path(path) or path == "/app":
        return await handler(request)

    user = _user(request)
    if not user:
        # API / WS / static / brand / accounts — 401 без утечки данных
        return web.json_response({"error": "unauthorized"}, status=401)

    # Пока не сменил пароль — только me / password / logout
    if user.must_change_[REDACTED] = (
            path in ("/app", "/api/me", "/api/logout", "/api/password")
            or path.startswith("/static/")
            or path.startswith("/brand/")
        )
        if not allowed:
            return web.json_response(
                {"error": "must_change_password", "must_change_password": True},
                status=403,
            )

    # Telegram login UI — только админ (менеджеры без своих Telegram)
    if path.startswith("/accounts") and not user.is_admin:
        return web.json_response({"error": "forbidden"}, status=403)

    if request.method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/"):
        if path not in ("/api/login", "/api/invite") and not _csrf_ok(request):
            return web.json_response({"error": "csrf"}, status=403)
    return await handler(request)


async def handle_root(request: web.Request) -> web.Response:
    if _user(request):
        raise web.HTTPFound("/app")
    return web.Response(text=LOGIN_HTML, content_type="text/html", charset="utf-8")


async def handle_app(request: web.Request) -> web.Response:
    if not _user(request):
        raise web.HTTPFound("/")
    resp = web.Response(text=INDEX_HTML, content_type="text/html", charset="utf-8")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


async def handle_invite_page(request: web.Request) -> web.Response:
    return web.Response(text=INVITE_HTML, content_type="text/html", charset="utf-8")


async def handle_login(request: web.Request) -> web.Response:
    from bot.dashboard.ingress import login_next, note_login

    data = await request.json()
    ip = _client_ip(request)
    ua = (request.headers.get("User-Agent") or "")[:180]
    uname = str(data.get("username") or "")[:80]
    if dash_auth.login_rate_limited(ip):
        note_login(ip=ip, username=uname, ok=False, ua=ua, detail="пауза")
        return web.json_response({"error": dash_auth.AUTH_ERROR}, status=401)
    user = dash_auth.authenticate(
        data.get("username") or "",
        data.get("password") or "",
        client_ip=ip,
    )
    note_login(ip=ip, username=uname, ok=bool(user), ua=ua, detail="" if user else "отказ")
    if not user:
        return web.json_response({"error": dash_auth.AUTH_ERROR}, status=401)
    csrf = dash_auth.new_csrf_token()
    body: dict[str, Any] = {
        "ok": True,
        "user": _user_public(user),
        "csrf": csrf,
        "demo": DEMO,
    }
    nxt = login_next(user)
    if nxt:
        body["next"] = nxt
    resp = web.json_response(body)
    _set_auth_cookies(resp, user, secure=_cookie_secure(request), csrf=csrf)
    return resp


async def handle_invite_accept(request: web.Request) -> web.Response:
    data = await request.json()
    [REDACTED] or "").strip()
    [REDACTED] or ""
    try:
        user = dash_auth.accept_invite(token, password)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if not user:
        return web.json_response({"error": dash_auth.AUTH_ERROR}, status=401)
    csrf = dash_auth.new_csrf_token()
    resp = web.json_response({"ok": True, "user": _user_public(user), "csrf": csrf})
    _set_auth_cookies(resp, user, secure=_cookie_secure(request), csrf=csrf)
    return resp


async def handle_logout(request: web.Request) -> web.Response:
    u = _user(request)
    if u:
        dash_auth.invalidate_session(u.username)
    resp = web.json_response({"ok": True})
    resp.del_cookie(dash_auth.COOKIE_NAME, path="/")
    resp.del_cookie(dash_auth.CSRF_COOKIE, path="/")
    return resp


async def handle_me(request: web.Request) -> web.Response:
    u = _require(request)
    csrf = request.cookies.get(dash_auth.CSRF_COOKIE) or dash_auth.new_csrf_token()
    resp = web.json_response(
        {
            "user": _user_public(u),
            "csrf": csrf,
            "demo": DEMO,
            "distribution": dash_auth.get_distribution_mode(),
        }
    )
    if not request.cookies.get(dash_auth.CSRF_COOKIE):
        resp.set_cookie(
            dash_auth.CSRF_COOKIE,
            csrf,
            httponly=False,
            samesite="Lax",
            secure=_cookie_secure(request),
            max_age=dash_auth.SESSION_TTL,
            path="/",
        )
    return resp


async def handle_password_change(request: web.Request) -> web.Response:
    u = _require(request)
    data = await request.json()
    old = data.get("old_password") or ""
    new = data.get("new_password") or ""
    try:
        ok = dash_auth.change_own_password(u.username, old, new)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if not ok:
        return web.json_response({"error": "Неверный текущий пароль"}, status=400)
    fresh = dash_auth.find_user(u.username)
    if not fresh:
        return web.json_response({"error": "user gone"}, status=500)
    user = dash_auth.DashUser(
        username=str(fresh["username"]),
        role=str(fresh.get("role") or "manager"),
        manager_id=str(fresh.get("manager_id") or ""),
        display_name=str(fresh.get("display_name") or fresh["username"]),
        enabled=bool(fresh.get("enabled", True)),
        must_change_[REDACTED]
    )
    csrf = dash_auth.new_csrf_token()
    resp = web.json_response({"ok": True, "user": _user_public(user), "csrf": csrf})
    _set_auth_cookies(resp, user, secure=_cookie_secure(request), csrf=csrf)
    return resp


async def handle_users_list(request: web.Request) -> web.Response:
    _require_admin(request)
    return web.json_response(
        {
            "users": dash_auth.list_users_public(),
            "distribution": dash_auth.get_distribution_mode(),
        }
    )


async def handle_users_create(request: web.Request) -> web.Response:
    _require_admin(request)
    data = await request.json()
    try:
        created = dash_auth.create_manager_user(
            username=data.get("username") or "",
            display_name=data.get("display_name") or "",
            manager_id=data.get("manager_id") or "",
            temp_[REDACTED] or "",
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    mid = created["manager_id"]
    reg = get_registry()
    if mid not in reg.managers:
        reg.upsert(manager_id=mid, name=created.get("display_name") or mid)
    base = str(request.url.origin())
    invite_url = f"{base}/invite/{created['invite_token']}"
    return web.json_response(
        {
            "ok": True,
            "user": {
                "username": created["username"],
                "manager_id": mid,
                "must_change_password": True,
            },
            "temp_password": created["temp_password"],
            "invite_token": created["invite_token"],
            "invite_url": invite_url,
        }
    )


async def handle_users_enable(request: web.Request) -> web.Response:
    _require_admin(request)
    data = await request.json()
    username = (data.get("username") or "").strip()
    enabled = bool(data.get("enabled"))
    try:
        ok = dash_auth.set_user_enabled(username, enabled)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if not ok:
        return web.json_response({"error": "не найден"}, status=404)
    row = dash_auth.find_user(username)
    mid = str((row or {}).get("manager_id") or "")
    if mid:
        from bot.dashboard.distribute import on_manager_disabled, on_manager_enabled

        if enabled:
            on_manager_enabled(mid)
        else:
            on_manager_disabled(_store(), mid)
    return web.json_response({"ok": True, "enabled": enabled})


async def handle_users_delete(request: web.Request) -> web.Response:
    _require_admin(request)
    data = await request.json()
    username = (data.get("username") or "").strip()
    try:
        ok = dash_auth.delete_user(username)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if not ok:
        return web.json_response({"error": "не найден"}, status=404)
    return web.json_response({"ok": True})


async def handle_users_reset_pw(request: web.Request) -> web.Response:
    _require_admin(request)
    data = await request.json()
    username = (data.get("username") or "").strip()
    try:
        pw = dash_auth.reset_password(username, data.get("new_password") or "")
    except KeyError:
        return web.json_response({"error": "не найден"}, status=404)
    return web.json_response(
        {"ok": True, "temp_password": pw, "must_change_password": True}
    )


async def handle_distribution(request: web.Request) -> web.Response:
    _require_admin(request)
    if request.method == "GET":
        return web.json_response({"mode": dash_auth.get_distribution_mode()})
    data = await request.json()
    mode = (data.get("mode") or "").strip()
    try:
        dash_auth.set_distribution_mode(mode)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True, "mode": mode})


async def handle_redistribute(request: web.Request) -> web.Response:
    _require_admin(request)
    from bot.dashboard.distribute import redistribute_unassigned

    result = redistribute_unassigned(_store())
    return web.json_response(result)


async def handle_tg_accounts(request: web.Request) -> web.Response:
    u = _require(request)
    from bot.tg_accounts import get_tg_accounts

    items = get_tg_accounts().list_public()
    if not u.is_admin:
        # менеджер видит только свой / общий аккаунт (без session)
        mid = u.manager_id
        items = [
            a
            for a in items
            if not a.get("manager_id") or a.get("manager_id") == mid or a.get("is_main")
        ]
    return web.json_response({"accounts": items, "max": 5})


async def handle_tg_accounts_upsert(request: web.Request) -> web.Response:
    _require_admin(request)
    from bot.tg_accounts import get_tg_accounts

    data = await request.json()
    try:
        a = get_tg_accounts().upsert(
            account_id=(data.get("id") or "").strip(),
            label=data.get("label") or "",
            manager_id=data.get("manager_id") or "",
            daily_send_limit=data.get("daily_send_limit"),
            weekly_send_limit=data.get("weekly_send_limit"),
            is_main=bool(data.get("is_main")),
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True, "account": a.public_dict()})


async def handle_settings(request: web.Request) -> web.Response:
    """Лимиты аккаунтов + доли менеджеров + счётчики."""
    u = _require(request)
    from bot.dashboard.distribute import daily_shares_for_account, share_weights
    from bot.rate_limit import OutreachLimiter
    from bot.tg_accounts import get_tg_accounts

    tg = get_tg_accounts()
    accounts = []
    for a in tg.list_public():
        acc = tg.get(a["id"])
        lim = OutreachLimiter.for_account(_store(), acc) if acc else None
        c = lim.counts() if lim else {}
        accounts.append({**a, "counters": c})
    main = tg.main()
    daily = int(main.daily_send_limit) if main else 30
    shares = daily_shares_for_account(daily) if u.is_admin else {}
    reg = get_registry()
    managers = []
    for m in reg.list_public():
        if not u.is_admin and m["id"] != u.manager_id:
            continue
        lim = OutreachLimiter.for_manager(_store(), reg.get(m["id"]))
        managers.append(
            {
                **m,
                "share_today": shares.get(m["id"], 0),
                "sent_today": lim.manager_sent_today(),
                "sent_week": lim.manager_sent_week(),
            }
        )
    from bot.presence import get_check_settings
    from bot.service_reports import get_service_report_settings

    return web.json_response(
        {
            "accounts": accounts,
            "managers": managers,
            "weights": share_weights() if u.is_admin else {},
            "shares_today": shares,
            "defaults": {
                "daily": 30,
                "weekly": 210,
                "new_account_daily": 30,
                "quiet_hours_after_login": 24,
            },
            "service_reports": get_service_report_settings(),
            "check_window": get_check_settings(_store()),
        }
    )


async def handle_settings_save(request: web.Request) -> web.Response:
    _require_admin(request)
    from bot.service_reports import set_saved_messages_reports
    from bot.tg_accounts import get_tg_accounts

    data = await request.json()
    tg = get_tg_accounts()
    for a in data.get("accounts") or []:
        aid = (a.get("id") or "").strip()
        if not aid:
            continue
        kw: dict = {
            "account_id": aid,
            "label": a.get("label") or "",
            "manager_id": a.get("manager_id") or "",
            "daily_send_limit": a.get("daily_send_limit"),
            "weekly_send_limit": a.get("weekly_send_limit"),
            "is_main": bool(a.get("is_main")),
        }
        if "quiet_hours_after_login" in a:
            kw["quiet_hours_after_login"] = a.get("quiet_hours_after_login")
        if "no_outreach_until" in a:
            kw["no_outreach_until"] = a.get("no_outreach_until")
        tg.upsert(**kw)
    reg = get_registry()
    for m in data.get("managers") or []:
        mid = (m.get("id") or "").strip()
        if mid and mid in reg.managers:
            if "share_weight" in m:
                reg.set_share(mid, int(m["share_weight"]))
            if "enabled" in m:
                reg.set_enabled(mid, bool(m["enabled"]))
    if "service_reports" in data and isinstance(data.get("service_reports"), dict):
        set_saved_messages_reports(
            bool(data["service_reports"].get("saved_messages_reports"))
        )
    elif "saved_messages_reports" in data:
        set_saved_messages_reports(bool(data.get("saved_messages_reports")))
    if "check_window" in data and isinstance(data.get("check_window"), dict):
        from bot.presence import save_check_settings

        save_check_settings(_store(), data["check_window"])
    return web.json_response({"ok": True})


async def handle_notifications(request: web.Request) -> web.Response:
    u = _require(request)
    hub = get_hub()
    items = list(hub.notifications)
    if not u.is_admin:
        items = [n for n in items if not n.get("manager_id") or n["manager_id"] == u.manager_id]
    unread = hub.unread.get(u.manager_id, 0) if not u.is_admin else sum(hub.unread.values())
    return web.json_response({"notifications": items[:80], "unread": unread})


async def handle_notifications_read(request: web.Request) -> web.Response:
    u = _require(request)
    get_hub().clear_unread(u.manager_id or u.username)
    return web.json_response({"ok": True})


async def handle_dialogs(request: web.Request) -> web.Response:
    u = _require(request)
    store = _store()
    reg = get_registry()
    only_archived = request.rel_url.query.get("view") == "archive"
    census: dict[str, int] = {}
    if u.is_admin:
        dialogs = store.list_dialogs(
            admin=True, limit=200, only_archived=only_archived, census=census
        )
    else:
        dialogs = store.list_dialogs(
            manager_id=u.manager_id,
            default_manager_id=reg.default_manager_id,
            limit=200,
            only_archived=only_archived,
            census=census,
        )
    slim = []
    for d in dialogs:
        slim.append(
            {
                "chat_id": d.get("chat_id"),
                "name": d.get("name"),
                "contact_name": d.get("contact_name"),
                "manager_id": d.get("manager_id"),
                "step": d.get("step"),
                "handed_off": d.get("handed_off"),
                "phone": d.get("phone"),
                "dates": d.get("dates") or "",
                "guests": d.get("guests") or "",
                "district": d.get("district") or "",
                "favorite": d.get("favorite") or "",
                "updated_at": d.get("updated_at") or 0,
                "archived": int(d.get("archived") or 0),
                "pinned": int(d.get("pinned") or 0),
                "note": d.get("note") or "",
                "tone": d.get("tone") or "work",
                "lane": d.get("lane") or "work",
                "brief": d.get("brief") or "",
                "tg_status": (d.get("tg_status") or (d.get("context") or {}).get("tg_status") or ""),
                "last_message": d.get("last_message"),
                "context": {
                    "next": (d.get("context") or {}).get("next", ""),
                    "demo": (d.get("context") or {}).get("demo"),
                    "tg_status": (d.get("context") or {}).get("tg_status") or d.get("tg_status") or "",
                    "tg_account": (d.get("context") or {}).get("tg_account") or d.get("tg_account_id") or "",
                },
            }
        )
    return web.json_response({"dialogs": slim, "stats": census})


async def handle_dialog(request: web.Request) -> web.Response:
    u = _require(request)
    chat_id = request.match_info["chat_id"]
    store = _store()
    access = _chat_access(u, store, chat_id)
    if isinstance(access, web.Response):
        return access
    sess, mid = access
    guest_row = store.recent_messages(chat_id, limit=30)
    last_guest = ""
    for msg in reversed(guest_row):
        if msg.get("role") in ("guest", "user") and (msg.get("text") or "").strip():
            last_guest = msg["text"]
            break
    sess = {**sess, "last_guest": last_guest}
    contact = store.contact_by_chat(chat_id)
    ctx = dict(sess.get("context") or {})
    if contact:
        ctx["tg_status"] = contact.get("tg_status") or ctx.get("tg_status") or ""
    dialog = {
        **{
            k: sess.get(k)
            for k in (
                "chat_id",
                "name",
                "step",
                "handed_off",
                "manager_id",
                "dates",
                "guests",
                "district",
                "favorite",
                "archived",
                "pinned",
                "note",
            )
        },
        "contact_name": (contact or {}).get("name"),
        "phone": (contact or {}).get("phone"),
        "tg_status": (contact or {}).get("tg_status") or "",
        "telegram_user_id": (contact or {}).get("telegram_user_id") or "",
        "tg_account_id": (contact or {}).get("tg_account_id") or "",
        "tone": dialog_tone(sess),
        "lane": dialog_lane(sess),
        "brief": dialog_brief(sess),
        "context": ctx,
    }
    return web.json_response({"dialog": dialog, "messages": store.list_messages(chat_id, limit=150)})


async def handle_reply(request: web.Request) -> web.Response:
    u = _require(request)
    chat_id = request.match_info["chat_id"]
    data = await request.json()
    text = (data.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "пустой текст"}, status=400)
    store = _store()
    access = _chat_access(u, store, chat_id)
    if isinstance(access, web.Response):
        return access
    sess, mid = access
    mid = mid or u.manager_id
    if not u.is_admin and mid and mid != u.manager_id and not u.can_act_as(mid):
        return web.json_response({"error": "forbidden"}, status=403)
    contact = store.contact_by_chat(chat_id)
    acc_id = str((contact or {}).get("tg_account_id") or "")
    client = get_hub().get_client(mid, account_id=acc_id)
    real_chat = not str(chat_id).startswith("demo-")
    # любой ответ менеджера из панели = takeover (бот молчит до «Вернуть боту»)
    store.save_session(chat_id, handed_off=1, step="handed_off", manager_id=mid)
    label = u.display_name or u.username
    queued = False
    if client is not None:
        try:
            target = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            # сообщение менеджера — сразу; не mark_bot_outbound → NewMessage.out ставит takeover
            await client.send_message(target, text)
            try:
                from bot.presence import set_offline

                await set_offline(client)
            except Exception:
                pass
        except Exception as e:
            if real_chat:
                logger.exception("dashboard reply failed")
                return web.json_response({"error": type(e).__name__}, status=500)
    elif real_chat:
        from bot.panel_outbox import enqueue

        enqueue(chat_id, text)
        queued = True
    msg = store.add_message(chat_id, "manager", text, sender_label=label, manager_id=mid)
    get_hub().bus.publish("takeover", chat_id=chat_id, active=True, by=label)
    return web.json_response(
        {"ok": True, "message": msg, "handed_off": True, "queued": queued}
    )


async def handle_takeover(request: web.Request) -> web.Response:
    u = _require(request)
    chat_id = request.match_info["chat_id"]
    data = await request.json()
    active = bool(data.get("active"))
    store = _store()
    access = _chat_access(u, store, chat_id)
    if isinstance(access, web.Response):
        return access
    sess, mid = access
    mid = mid or u.manager_id
    store.save_session(
        chat_id,
        handed_off=1 if active else 0,
        step="handed_off" if active else (sess.get("step") or "await_intent"),
        manager_id=mid,
    )
    get_hub().bus.publish(
        "takeover", chat_id=chat_id, active=active, by=u.display_name or u.username
    )
    return web.json_response({"ok": True, "handed_off": active})


def _chat_access(u, store: Store, chat_id: str) -> tuple[dict, str] | web.Response:
    """Чат должен уже существовать. Пустой id не создаёт строку в базе."""
    sess = store.peek_session(chat_id)
    if not sess:
        return web.json_response({"error": "not_found"}, status=404)
    mid = store.contact_manager_id(chat_id=chat_id) or (sess.get("manager_id") or "")
    if u.is_admin:
        return sess, mid
    if mid and mid != u.manager_id:
        return web.json_response({"error": "forbidden"}, status=403)
    if not mid:
        default_mid = ""
        try:
            default_mid = get_registry().default_manager_id or ""
        except Exception:
            default_mid = ""
        if not default_mid or u.manager_id != default_mid:
            return web.json_response({"error": "forbidden"}, status=403)
    return sess, mid


async def handle_dialog_flags(request: web.Request) -> web.Response:
    u = _require(request)
    chat_id = request.match_info["chat_id"]
    data = await request.json()
    store = _store()
    access = _chat_access(u, store, chat_id)
    if isinstance(access, web.Response):
        return access
    fields: dict = {}
    if "archived" in data:
        fields["archived"] = 1 if data.get("archived") else 0
    if "pinned" in data:
        fields["pinned"] = 1 if data.get("pinned") else 0
    if "note" in data:
        fields["note"] = str(data.get("note") or "")[:2000]
    if not fields:
        return web.json_response({"error": "нечего сохранить"}, status=400)
    store.save_session(chat_id, **fields)
    sess = store.get_session(chat_id)
    return web.json_response(
        {
            "ok": True,
            "archived": int(sess.get("archived") or 0),
            "pinned": int(sess.get("pinned") or 0),
            "note": sess.get("note") or "",
        }
    )


async def handle_dialog_export(request: web.Request) -> web.Response:
    u = _require(request)
    chat_id = request.match_info["chat_id"]
    store = _store()
    access = _chat_access(u, store, chat_id)
    if isinstance(access, web.Response):
        return access
    sess, _mid = access
    contact = store.contact_by_chat(chat_id)
    name = sess.get("name") or (contact or {}).get("name") or chat_id
    phone = (contact or {}).get("phone") or ""
    lines = [f"{name}", phone, f"чат {chat_id}", ""]
    note = (sess.get("note") or "").strip()
    if note:
        lines.append(f"Заметка смены: {note}")
        lines.append("")
    for m in store.list_messages(chat_id, limit=400):
        role = {"guest": "Гость", "bot": "Бот", "manager": "Менеджер"}.get(m["role"], m["role"])
        who = m.get("sender_label") or role
        lines.append(f"{who}: {m.get('text') or ''}")
    body = "\n".join(lines).strip() + "\n"
    return web.Response(text=body, content_type="text/plain", charset="utf-8")


async def handle_desk(request: web.Request) -> web.Response:
    _require_admin(request)
    snap = _store().desk_snapshot()
    return web.json_response(snap)


async def handle_search(request: web.Request) -> web.Response:
    u = _require(request)
    q = request.rel_url.query.get("q") or ""
    rows = _store().search_messages(
        q,
        manager_id="" if u.is_admin else (u.manager_id or ""),
        admin=u.is_admin,
        limit=40,
    )
    return web.json_response({"hits": rows})


async def handle_archive_quiet(request: web.Request) -> web.Response:
    _require_admin(request)
    n = _store().archive_quiet()
    return web.json_response({"ok": True, "archived": n})


async def handle_queue(request: web.Request) -> web.Response:
    u = _require(request)
    store = _store()
    reg = get_registry()
    hub = get_hub()
    rows = []
    for m in reg.enabled_list():
        if not u.is_admin and m.id != u.manager_id:
            continue
        lim = OutreachLimiter.for_manager(store, m)
        st = store.stats_for_manager(m.id, default_manager_id=reg.default_manager_id)
        o = hub.outreach.get(m.id) or {}
        c = lim.counts()
        note = o.get("note") or ("идёт" if o.get("running") else "")
        if c.get("paused_today"):
            note = c.get("pause_reason") or "стоп на сегодня"
        if c.get("quiet_active"):
            note = c.get("quiet_reason") or note
        rows.append(
            {
                "id": m.id,
                "name": m.name,
                "sent_today": c["sent_today"],
                "daily_limit": lim.daily_limit,
                "sent_week": c["sent_week"],
                "weekly_limit": lim.weekly_limit,
                "remaining_today": c["remaining_today"],
                "remaining_week": c["remaining_week"],
                "pending": st["pending"],
                "in_work_hours": lim.in_work_hours(),
                "moscow_time": lim.now().strftime("%H:%M"),
                "session_online": bool(hub.get_client(m.id)),
                "paused_today": c.get("paused_today"),
                "quiet_active": bool(c.get("quiet_active")),
                "quiet_remaining_sec": int(c.get("quiet_remaining_sec") or 0),
                "quiet_reason": c.get("quiet_reason") or "",
                "outreach_note": note,
                "account_id": c.get("account_id") or "",
            }
        )
    return web.json_response({"managers": rows})


async def handle_logs(request: web.Request) -> web.Response:
    u = _require(request)
    level = request.rel_url.query.get("level") or ""
    mid = request.rel_url.query.get("manager_id") or ""
    tech_raw = (request.rel_url.query.get("technical") or "").strip().lower()
    technical = tech_raw in ("1", "true", "yes", "on")
    if not u.is_admin:
        mid = u.manager_id
    logs = get_hub().logs.list(
        level=level, manager_id=mid, limit=250, technical=technical
    )
    return web.json_response({"logs": logs, "technical": technical})


async def handle_managers(request: web.Request) -> web.Response:
    u = _require(request)
    reg = get_registry()
    items = reg.list_public()
    if not u.is_admin:
        items = [m for m in items if m["id"] == u.manager_id]
    return web.json_response({"managers": items})


def _outreach_plan(store: Store, *, manager_id: str = "", admin: bool = False):
    """Очередь дня по долям капа аккаунта бота.

    admin + пустой manager_id → вся дневная очередь по всем активным;
    иначе → только доля выбранного менеджера.
    """
    from bot.dashboard.distribute import build_day_queue, daily_shares_for_account
    from bot.tg_accounts import get_tg_accounts

    tg = get_tg_accounts()
    acc = (tg.for_manager(manager_id) if manager_id else None) or tg.main()
    daily = int(acc.daily_send_limit) if acc else 30
    aid = acc.id if acc else "main"
    lim = (
        OutreachLimiter.for_account(store, acc, manager_id=manager_id or "")
        if acc
        else OutreachLimiter(store, daily_limit=daily)
    )
    only = "" if (admin and not manager_id) else (manager_id or "")
    pending = build_day_queue(
        store, daily_limit=daily, account_id=aid, only_manager_id=only
    )
    shares = daily_shares_for_account(daily)
    return pending, lim, shares, aid


async def handle_outreach_preview(request: web.Request) -> web.Response:
    u = _require(request)
    data = await request.json()
    mid = (data.get("manager_id") or u.manager_id or "").strip()
    if mid and not u.can_act_as(mid):
        return web.json_response({"error": "forbidden"}, status=403)
    store = _store()
    pending, lim, shares, aid = _outreach_plan(
        store, manager_id=mid if not u.is_admin else mid, admin=u.is_admin
    )
    from bot.phrases import sample_outreach_texts

    sample_name = ""
    for c in pending[:8]:
        nm = (c.get("name") or "").strip()
        if nm and nm.lower() not in ("клиент", "гость", "client", "guest"):
            sample_name = nm.split()[0]
            break
    samples = sample_outreach_texts(name=sample_name or "Мария", limit=6)
    lines = [
        f"Превью /send: аккаунт [{aid}], в очереди на сегодня {len(pending)}",
        f"Доли активных менеджеров: {shares}",
        *lim.status_lines(pending_count=len(pending)),
        "",
        "—— Примеры текста рассылки (как уйдёт гостю) ——",
        *([f"{i+1}) {t}" for i, t in enumerate(samples)] or ["(нет шаблонов)"]),
        "",
        "—— Очередь ——",
    ]
    for c in pending[:25]:
        lines.append(
            f"· [{c.get('manager_id') or '—'}] {c['phone']} {c.get('name') or ''}".strip()
        )
    if len(pending) > 25:
        lines.append(f"… и ещё {len(pending) - 25}")
    return web.json_response(
        {
            "lines": lines,
            "count": len(pending),
            "shares": shares,
            "account_id": aid,
            "samples": samples,
        }
    )


async def handle_outreach_samples_page(_request: web.Request) -> web.Response:
    """Публичная страница — посмотреть тон рассылки без логина."""
    from bot.phrases import sample_outreach_texts

    with_name = sample_outreach_texts(name="Мария", hour=14)
    no_name = sample_outreach_texts(name="", hour=14)
    items_a = "".join(
        f'<li class="bubble"><div class="meta">с именем · вариант {i+1}</div>'
        f"<p>{_html_esc(t)}</p></li>"
        for i, t in enumerate(with_name)
    )
    items_b = "".join(
        f'<li class="bubble"><div class="meta">без имени · вариант {i+1}</div>'
        f"<p>{_html_esc(t)}</p></li>"
        for i, t in enumerate(no_name[:6])
    )
    html = f"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Home24 — примеры рассылки</title>
<style>
:root {{ --bg:#0f1419; --card:#1a222c; --ink:#e8eef4; --muted:#8b9aab; --accent:#3d9cf0; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:16px/1.45 system-ui,sans-serif; background:linear-gradient(160deg,#0f1419,#1a2836 50%,#121820); color:var(--ink); min-height:100vh; }}
main {{ max-width:720px; margin:0 auto; padding:2rem 1.25rem 3rem; }}
h1 {{ font-size:1.45rem; font-weight:650; margin:0 0 .35rem; }}
.lead {{ color:var(--muted); margin:0 0 1.5rem; }}
ul {{ list-style:none; padding:0; margin:0 0 2rem; display:grid; gap:.85rem; }}
.bubble {{ background:var(--card); border:1px solid #2a3644; border-radius:14px; padding:1rem 1.1rem; }}
.bubble p {{ margin:0; white-space:pre-wrap; }}
.meta {{ font-size:.75rem; color:var(--muted); margin-bottom:.45rem; text-transform:uppercase; letter-spacing:.04em; }}
a {{ color:var(--accent); }}
</style></head><body><main>
<h1>Примеры текста рассылки Home24</h1>
<p class="lead">Так выглядит первое сообщение бывшему гостю. Ротация шаблонов — соседние контакты не получают один и тот же текст.
<a href="/">← в панель</a></p>
<h2 style="font-size:1rem;color:var(--muted);font-weight:600">С именем</h2>
<ul>{items_a}</ul>
<h2 style="font-size:1rem;color:var(--muted);font-weight:600">Без имени</h2>
<ul>{items_b}</ul>
</main></body></html>"""
    return web.Response(text=html, content_type="text/html", charset="utf-8")


def _html_esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _mail_manager_id(u, requested: str) -> str:
    mid = (requested or u.manager_id or "").strip()
    if u.is_admin and not mid:
        mid = get_registry().default_manager_id or "anna"
    return mid


async def handle_outreach_board(request: web.Request) -> web.Response:
    u = _require(request)
    mid = _mail_manager_id(u, request.rel_url.query.get("manager_id") or "")
    if mid and not u.can_act_as(mid) and not u.is_admin:
        return web.json_response({"error": "forbidden"}, status=403)
    store = _store()
    rows = store.list_contacts(limit=300)
    if not u.is_admin:
        rows = [r for r in rows if (r.get("manager_id") or "") in ("", mid)]
    order = {"pending": 0, "failed": 1, "sent": 2, "stopped": 3}
    rows.sort([REDACTED] r: (order.get(r.get("status") or "", 9), -(r.get("id") or 0)))
    slim = [
        {
            "phone": r.get("phone") or "",
            "name": r.get("name") or "",
            "status": r.get("status") or "",
            "last_error": r.get("last_error") or "",
            "manager_id": r.get("manager_id") or "",
        }
        for r in rows[:40]
    ]
    from bot.outreach_jobs import read_status
    from bot.phrases import sample_outreach_texts

    pending, lim, _shares, aid = _outreach_plan(
        store, manager_id=mid, admin=u.is_admin
    )
    open_now = lim.in_work_hours()
    status = read_status(mid)
    return web.json_response(
        {
            "contacts": slim,
            "pending_today": len(pending),
            "sent_today": lim.sent_today(),
            "daily_limit": lim.daily_limit,
            "window_open": open_now,
            "window_label": (
                f"окно {lim.work_start}:00–{lim.work_end}:00, сейчас {lim.now().strftime('%H:%M')}"
            ),
            "account_id": aid,
            "status": status,
            "samples": sample_outreach_texts(name="Мария", limit=3),
        }
    )


async def handle_outreach_compose(request: web.Request) -> web.Response:
    u = _require(request)
    data = await request.json()
    mid = _mail_manager_id(u, data.get("manager_id") or "")
    if mid and not u.can_act_as(mid) and not u.is_admin:
        return web.json_response({"error": "forbidden"}, status=403)
    from bot.outreach_jobs import enqueue, parse_outreach_lines

    parsed = parse_outreach_lines(data.get("text") or "")
    if not parsed:
        return web.json_response(
            {"error": "Не вижу номеров. Каждый с новой строки: [REDACTED]"},
            status=400,
        )
    store = _store()
    queued: list[str] = []
    skipped: list[dict[str, str]] = []
    for item in parsed:
        phone = item["phone"]
        if phone.lower() == "@bdoxa":
            skipped.append({"phone": phone, "status": "свой аккаунт"})
            continue
        before = store.contact_by_phone(phone)
        store.add_contact(phone, item.get("name") or "", manager_id=mid)
        after = store.contact_by_phone(phone) or {}
        status = after.get("status") or ""
        if status == "pending":
            queued.append(phone)
        else:
            skipped.append({"phone": phone, "status": status or "пропуск"})
            if before and before.get("status") == status:
                pass
    now = bool(data.get("now"))
    if queued:
        enqueue(action="start", manager_id=mid, phones=queued, now=now)
    return web.json_response(
        {
            "ok": True,
            "queued": queued,
            "skipped": skipped,
            "now": now,
            "message": (
                f"В очереди бота: {len(queued)}. "
                + (
                    "Уйдут сейчас, не дожидаясь утра."
                    if now
                    else "Уйдут в рабочее окно 10:00–20:00."
                )
                if queued
                else "Новых номеров для отправки нет."
            ),
        }
    )


async def handle_outreach_run(request: web.Request) -> web.Response:
    u = _require(request)
    data = await request.json()
    mid = _mail_manager_id(u, data.get("manager_id") or "")
    go = bool(data.get("go"))
    if mid and not u.can_act_as(mid) and not u.is_admin:
        return web.json_response({"error": "forbidden"}, status=403)
    from bot.outreach_jobs import enqueue

    if not go:
        enqueue(action="stop", manager_id=mid)
        return web.json_response({"message": "Остановка передана боту. Текущая партия прервётся."})
    store = _store()
    pending, lim, shares, aid = _outreach_plan(
        store, manager_id=mid, admin=u.is_admin
    )
    if not pending:
        return web.json_response({"message": "В очереди никого нет", "shares": shares})
    now = bool(data.get("now"))
    enqueue(
        action="start",
        manager_id=mid,
        phones=[c["phone"] for c in pending if c.get("phone")],
        now=now,
    )
    return web.json_response(
        {
            "message": (
                f"Бот заберёт {len(pending)} номеров"
                + (" и отправит сейчас." if now else " в рабочее окно.")
                + f" Сегодня {lim.sent_today()}/{lim.daily_limit}, аккаунт {aid}."
            ),
            "shares": shares,
            "count": len(pending),
        }
    )


async def handle_stops(request: web.Request) -> web.Response:
    _require(request)
    return web.json_response({"stops": _store().list_stops()})


async def handle_stops_add(request: web.Request) -> web.Response:
    u = _require(request)
    data = await request.json()
    phone = (data.get("phone") or "").strip()
    chat_id = (data.get("chat_id") or "").strip()
    if not phone and not chat_id:
        return web.json_response({"error": "нужен phone или chat_id"}, status=400)
    store = _store()
    if phone and not u.is_admin:
        c = store.contact_by_phone(phone)
        if c and c.get("manager_id") and c["manager_id"] != u.manager_id:
            return web.json_response({"error": "forbidden"}, status=403)
    store.mark_stopped(phone=phone, chat_id=chat_id)
    return web.json_response({"ok": True})


async def handle_stops_remove(request: web.Request) -> web.Response:
    u = _require(request)
    if not u.is_admin:
        return web.json_response({"error": "только админ снимает стоп"}, status=403)
    data = await request.json()
    [REDACTED] or "").strip()
    phone = chat_id = ""
    if key.startswith("phone:"):
        phone = key.split(":", 1)[1]
    elif key.startswith("chat:"):
        chat_id = key.split(":", 1)[1]
    else:
        phone = key
    _store().remove_global_stop(phone=phone, chat_id=chat_id)
    return web.json_response({"ok": True})


async def handle_assign(request: web.Request) -> web.Response:
    u = _require(request)
    data = await request.json()
    phone = (data.get("phone") or "").strip()
    mid = (data.get("manager_id") or "").strip()
    if not phone or not mid:
        return web.json_response({"error": "phone и manager_id обязательны"}, status=400)
    if not u.is_admin:
        return web.json_response({"error": "только админ переназначает"}, status=403)
    store = _store()
    if not store.contact_by_phone(phone):
        store.add_contact(phone=phone, manager_id=mid)
    ok, why = store.assign_manager(phone, mid, allow_reassign=True)
    return web.json_response({"ok": ok, "message": "Закрепил." if ok else why})


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    u = _user(request)
    if not u:
        raise web.HTTPUnauthorized()
    if u.must_change_[REDACTED] web.HTTPForbidden()
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    hub = get_hub()
    q = hub.bus.subscribe()
    try:
        await ws.send_json({"kind": "hello", "user": _user_public(u), "demo": DEMO})
        while not ws.closed:
            get_task = asyncio.create_task(q.get())
            recv_task = asyncio.create_task(ws.receive())
            done, pending = await asyncio.wait(
                {get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            if recv_task in done:
                msg = recv_task.result()
                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.ERROR):
                    break
            if get_task in done:
                evt = get_task.result()
                mid = evt.get("manager_id") or ""
                if not u.is_admin and mid and mid != u.manager_id:
                    if evt.get("kind") not in ("hello",):
                        continue
                try:
                    await ws.send_json(evt)
                except Exception:
                    break
    finally:
        hub.bus.unsubscribe(q)
        await ws.close()
    return ws


async def handle_templates_list(request: web.Request) -> web.Response:
    u = _require(request)
    from bot.reply_templates import (
        fill_template,
        get_template_store,
        placeholder_vars,
        public_categories,
    )

    store = get_template_store()
    items = store.list_for(username=u.username, is_admin=u.is_admin)
    chat_id = (request.query.get("chat_id") or "").strip()
    dialog = None
    if chat_id:
        st = _store()
        sess = st.get_session(chat_id)
        mid = st.contact_manager_id(chat_id=chat_id) or (sess.get("manager_id") or "")
        if mid and not u.can_see_manager(mid) and not u.is_admin:
            return web.json_response({"error": "forbidden"}, status=403)
        contact = st.contact_by_chat(chat_id)
        ctx = dict(sess.get("context") or {})
        dialog = {
            **{k: sess.get(k) for k in (
                "name", "dates", "guests", "district", "favorite", "manager_id"
            )},
            "contact_name": (contact or {}).get("name"),
            "context": ctx,
        }
    from bot.user_prefs import manager_label

    mgr_name = manager_label(u.username, u.display_name or u.username)
    vars_map = placeholder_vars(dialog, manager_name=mgr_name)
    out = []
    for t in items:
        row = dict(t)
        row["category_label"] = next(
            (c["label"] for c in public_categories() if c["id"] == t["category"]),
            t["category"],
        )
        row["filled"] = fill_template(t["body"], vars_map)
        out.append(row)
    return web.json_response(
        {
            "templates": out,
            "categories": public_categories(),
            "vars": vars_map,
        }
    )


async def handle_templates_save(request: web.Request) -> web.Response:
    u = _require(request)
    from bot.reply_templates import get_template_store

    data = await request.json()
    scope = (data.get("scope") or "shared").strip()
    if scope == "shared" and not u.is_admin:
        return web.json_response({"error": "forbidden"}, status=403)
    if scope == "personal":
        owner = u.username
    else:
        owner = ""
    try:
        item = get_template_store().upsert(
            tid=(data.get("id") or None),
            title=str(data.get("title") or ""),
            body=str(data.get("body") or ""),
            category=str(data.get("category") or "greeting"),
            scope=scope,
            owner=owner,
            enabled=bool(data.get("enabled", True)),
            sort=data.get("sort"),
            actor=u.username,
            is_admin=u.is_admin,
        )
    except PermissionError as e:
        return web.json_response({"error": e.args[0] if e.args else str(e)}, status=403)
    except (ValueError, KeyError) as e:
        return web.json_response({"error": e.args[0] if e.args else str(e)}, status=400)
    return web.json_response({"ok": True, "template": item})


async def handle_templates_delete(request: web.Request) -> web.Response:
    u = _require(request)
    from bot.reply_templates import get_template_store

    tid = request.match_info["tid"]
    try:
        get_template_store().delete(tid, actor=u.username, is_admin=u.is_admin)
    except PermissionError as e:
        return web.json_response({"error": e.args[0] if e.args else str(e)}, status=403)
    except KeyError as e:
        return web.json_response({"error": e.args[0] if e.args else str(e)}, status=404)
    return web.json_response({"ok": True})


async def handle_templates_reorder(request: web.Request) -> web.Response:
    u = _require(request)
    from bot.reply_templates import get_template_store

    data = await request.json()
    ids = data.get("ids") or []
    if not isinstance(ids, list):
        return web.json_response({"error": "ids: list"}, status=400)
    items = get_template_store().reorder_personal(u.username, ids)
    personal = [t for t in items if t.get("scope") == "personal"]
    return web.json_response({"ok": True, "templates": personal})


async def handle_prefs_get(request: web.Request) -> web.Response:
    u = _require(request)
    from bot.user_prefs import get_user_prefs_store

    prefs = get_user_prefs_store().get(u.username)
    return web.json_response(
        {
            "prefs": prefs,
            "display_name": u.display_name or u.username,
            "username": u.username,
            "role": u.role,
            "manager_id": u.manager_id,
            "store_path": "data/user_prefs.json",
        }
    )


async def handle_prefs_save(request: web.Request) -> web.Response:
    u = _require(request)
    from bot.user_prefs import get_user_prefs_store

    data = await request.json()
    display_name = data.get("display_name")
    if display_name is not None:
        try:
            name = dash_auth.update_display_name(u.username, str(display_name))
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except KeyError:
            return web.json_response({"error": "user not found"}, status=404)
    else:
        name = u.display_name or u.username
    patch = {
        k: data[k]
        for k in (
            "signature",
            "theme",
            "notify_sound",
            "notify_browser",
            "notify_toast",
            "composer_enter",
            "font_size",
            "compact_chat",
            "dialog_filter",
        )
        if k in data
    }
    store = get_user_prefs_store()
    prefs = store.update(u.username, patch) if patch else store.get(u.username)
    # обновить сессию с новым display_name
    fresh = dash_auth.find_user(u.username) or {}
    user = dash_auth.DashUser(
        username=u.username,
        role=u.role,
        manager_id=u.manager_id,
        display_name=str(fresh.get("display_name") or name),
        enabled=True,
        must_change_[REDACTED]
        session_jti=u.session_jti,
    )
    return web.json_response(
        {"ok": True, "prefs": prefs, "user": _user_public(user)}
    )


_QR_PAGE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Вход Telegram</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:system-ui,sans-serif;background:#111;color:#eee}
main{width:min(420px,94vw);text-align:center}
img{background:#fff;padding:12px;border-radius:12px;width:min(320px,86vw);height:auto}
p{color:#bbb;line-height:1.45}
.err{color:#e88}
</style></head><body><main>
<h1>Вход в Telegram</h1>
<p>На телефоне: <b>Настройки → Устройства → Подключить устройство</b>. Сканируйте этот код из Telegram, не камерой галереи.</p>
<p id="msg">Готовлю код…</p>
<img id="q" alt="QR" src="/tg-qr.png"/>
</main>
<script>
async function tick(){
  const img=document.getElementById('q');
  const r=await fetch('/tg-qr.png?t='+Date.now(),{cache:'no-store'});
  const msg=r.headers.get('X-QR-Message')||'';
  document.getElementById('msg').textContent=msg;
  document.getElementById('msg').className=r.ok?'':'err';
  if(r.ok){
    const b=await r.blob();
    const u=URL.createObjectURL(b);
    img.src=u;
    img.hidden=false;
  } else {
    img.hidden=true;
  }
}
tick(); setInterval(tick, 3000);
</script></body></html>
"""


async def handle_tg_qr_page(_request: web.Request) -> web.Response:
    from bot.web_login import handle_qr_start

    try:
        await handle_qr_start(_request)
    except Exception:
        logger.exception("tg-qr start")
    return web.Response(text=_QR_PAGE, content_type="text/html", charset="utf-8")


async def handle_tg_qr_png(request: web.Request) -> web.Response:
    import base64

    from bot.web_login import _state, handle_qr_start

    if not _state.get("qr_b64") and not (_state.get("_qr_task") and not _state["_qr_task"].done()):
        try:
            await handle_qr_start(request)
        except Exception:
            logger.exception("tg-qr start")
    for _ in range(40):
        if _state.get("done"):
            break
        b64 = _state.get("qr_b64") or ""
        if b64:
            raw = base64.b64decode(b64)
            resp = web.Response(body=raw, content_type="image/png")
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-QR-Message"] = str(_state.get("message") or "Сканируйте QR")
            return resp
        if _state.get("status") == "error" and not _state.get("_qr_running"):
            break
        await asyncio.sleep(0.25)
    msg = str(_state.get("message") or "QR ещё не готов")
    if _state.get("done"):
        msg = "Вход выполнен. Можно закрыть страницу."
    return web.Response(
        text=msg,
        status=409 if not _state.get("done") else 200,
        headers={"X-QR-Message": msg, "Cache-Control": "no-store"},
    )


def create_dashboard_app() -> web.Application:
    dash_auth.ensure_users_file()
    dash_auth.ensure_unlisted_from_env()
    get_hub().attach_logging()
    try:
        from bot.telegram_api import api_credentials_ok

        ok_api, api_msg = api_credentials_ok()
        if not ok_api:
            logger.warning("%s", api_msg)
            get_hub().notify(
                "Нужны свои Telegram API ключи",
                api_msg,
                level="error",
            )
    except Exception:
        pass

    app = web.Application(
        middlewares=[
            harden_headers_middleware,
            trail_middleware,
            cache_control_middleware,
            security_middleware,
        ],
        client_max_size=2 * 1024 * 1024,
    )
    app.router.add_get("/", handle_root)
    app.router.add_get("/app", handle_app)
    app.router.add_get("/outreach-samples", handle_outreach_samples_page)
    app.router.add_get("/tg-qr", handle_tg_qr_page)
    app.router.add_get("/tg-qr.png", handle_tg_qr_png)
    app.router.add_get("/invite/{token}", handle_invite_page)
    app.router.add_post("/api/login", handle_login)
    app.router.add_post("/api/invite", handle_invite_accept)
    app.router.add_post("/api/logout", handle_logout)
    app.router.add_get("/api/me", handle_me)
    app.router.add_post("/api/password", handle_password_change)
    app.router.add_get("/api/users", handle_users_list)
    app.router.add_post("/api/users", handle_users_create)
    app.router.add_post("/api/users/enable", handle_users_enable)
    app.router.add_post("/api/users/delete", handle_users_delete)
    app.router.add_post("/api/users/reset-password", handle_users_reset_pw)
    app.router.add_get("/api/distribution", handle_distribution)
    app.router.add_post("/api/distribution", handle_distribution)
    app.router.add_post("/api/redistribute", handle_redistribute)
    app.router.add_get("/api/tg-accounts", handle_tg_accounts)
    app.router.add_post("/api/tg-accounts", handle_tg_accounts_upsert)
    app.router.add_get("/api/settings", handle_settings)
    app.router.add_post("/api/settings", handle_settings_save)
    app.router.add_get("/api/templates", handle_templates_list)
    app.router.add_post("/api/templates", handle_templates_save)
    app.router.add_post("/api/templates/reorder", handle_templates_reorder)
    app.router.add_delete("/api/templates/{tid}", handle_templates_delete)
    app.router.add_get("/api/prefs", handle_prefs_get)
    app.router.add_post("/api/prefs", handle_prefs_save)
    app.router.add_get("/api/notifications", handle_notifications)
    app.router.add_post("/api/notifications/read", handle_notifications_read)
    app.router.add_get("/api/dialogs", handle_dialogs)
    app.router.add_get("/api/dialogs/{chat_id}", handle_dialog)
    app.router.add_post("/api/dialogs/{chat_id}/reply", handle_reply)
    app.router.add_post("/api/dialogs/{chat_id}/takeover", handle_takeover)
    app.router.add_post("/api/dialogs/{chat_id}/flags", handle_dialog_flags)
    app.router.add_get("/api/dialogs/{chat_id}/export", handle_dialog_export)
    app.router.add_get("/api/desk", handle_desk)
    app.router.add_get("/api/search", handle_search)
    app.router.add_post("/api/archive-quiet", handle_archive_quiet)
    app.router.add_get("/api/queue", handle_queue)
    app.router.add_get("/api/logs", handle_logs)
    app.router.add_get("/api/managers", handle_managers)
    app.router.add_post("/api/outreach/preview", handle_outreach_preview)
    app.router.add_post("/api/outreach/run", handle_outreach_run)
    app.router.add_get("/api/outreach/board", handle_outreach_board)
    app.router.add_post("/api/outreach/compose", handle_outreach_compose)
    app.router.add_get("/api/stops", handle_stops)
    app.router.add_post("/api/stops/add", handle_stops_add)
    app.router.add_post("/api/stops/remove", handle_stops_remove)
    app.router.add_post("/api/assign", handle_assign)
    app.router.add_get("/ws", handle_ws)
    app.router.add_static("/static/", STATIC, show_index=False)
    brand = resolve_brand_dir()
    if brand.is_dir():
        app.router.add_static("/brand/", brand, show_index=False)

    login_app = create_login_routes_app()
    app.add_subapp("/accounts/", login_app)
    from bot.dashboard.ingress import attach

    attach(app)
    return app


async def run_dashboard(*, open_browser: bool = False) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / ".env")
    except Exception:
        logger.exception("dotenv load failed")
    app = create_dashboard_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    url = f"http://{HOST if HOST != '0.0.0.0' else '[REDACTED]'}:{PORT}/"
    logger.info("dashboard on %s (bind %s)", url, HOST)
    print(f"Панель Home24: {url}", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.server").setLevel(logging.WARNING)
    logging.getLogger("telethon.network").setLevel(logging.WARNING)
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / ".env")
    except Exception:
        pass
    asyncio.run(run_dashboard(open_browser=True))


if __name__ == "__main__":
    main()
