# -*- coding: utf-8 -*-
"""Локальная веб-страница входа Home24 ([REDACTED]).

Три способа: tdata (opentele-ng UseCurrentSession), QR, телефон+код+2FA.
Код запрашивается только по кнопке, без циклов.
Идеи UX: tele-auto-gram (веб-код/2FA), telegram-mcp / opentele (QR, tdata). MIT/Apache.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import webbrowser
from pathlib import Path
from typing import Any

from aiohttp import web
from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from bot.device import telethon_device_kwargs
from bot.managers import get_registry
from bot.proxy import client_transport
from bot.tdata_import import (
    account_public_dict,
    copy_tdata,
    default_tdata_path,
    list_accounts_from_tdata,
    telegram_desktop_running,
)

logger = logging.getLogger("home24.web_login")

LOGIN_PORT = int(os.getenv("HOME24_LOGIN_PORT") or "43125")
# exit code for start.bat when session dies
EXIT_SESSION_DEAD = 42

_state: dict[str, Any] = {
    "status": "idle",
    "message": "Выберите менеджера и способ входа",
    "qr_b64": "",
    "need_2fa": False,
    "phone_hash": "",
    "phone": "",
    "done": False,
    "me": None,
    # None = ещё не выбирали (UI покажет default); "" = явно «общий»
    "manager_id": None,
    "account_id": "main",
    "tdata_accounts": [],  # public list
    "_tdata_sessions": {},  # index -> session string (server-only)
    "_client": None,
    "_qr": None,
    "_qr_task": None,
}


def _public_login_error(exc: BaseException, fallback: str) -> str:
    from bot.proxy import EgressProxyMissing

    if isinstance(exc, EgressProxyMissing):
        return str(exc)
    return fallback


def _api() -> tuple[int, str]:
    from bot.telegram_api import TelegramApiError, resolve_api_credentials

    try:
        return resolve_api_credentials()
    except TelegramApiError as e:
        raise RuntimeError(str(e)) from e


def _account_device() -> dict:
    """Стабильный fingerprint слота. Пишем на диск до connect."""
    try:
        from bot.tg_accounts import get_tg_accounts

        aid = (_state.get("account_id") or "main").strip() or "main"
        return get_tg_accounts().freeze_device_fingerprint(aid)
    except Exception:
        from bot.device import default_device_fingerprint

        return default_device_fingerprint()


def _slot_egress() -> str:
    try:
        from bot.tg_accounts import get_tg_accounts

        aid = (_state.get("account_id") or "main").strip() or "main"
        acc = get_tg_accounts().get(aid)
        if acc is None:
            return ""
        return (getattr(acc, "egress", "") or "").strip()
    except Exception:
        return ""


def _make_client(session: str = "") -> TelegramClient:
    api_id, api_hash = _api()
    # Тот же выход, что у рабочего клиента. Вход с IP панели, а работа
    # через другой прокси — типичная причина, по которой Telegram
    # гасит сессию через несколько дней.
    egress = _slot_egress()
    connection, proxy = client_transport(egress, have_slot=bool(egress))
    kw: dict = {
        "connection": connection,
        "timeout": 40,
        **telethon_device_kwargs(_account_device()),
    }
    if proxy:
        kw["proxy"] = proxy
    return TelegramClient(StringSession(session or None), api_id, api_hash, **kw)


async def _claim_login_client(client: TelegramClient, session: str = "") -> tuple[bool, str]:
    """Единственный login-клиент на слот; отказ если бот уже держит сессию."""
    from bot.client_registry import claim

    aid = (_state.get("account_id") or "main").strip() or "main"
    return claim(aid, client, role="login", session=session)


async def _connect_exclusive(client: TelegramClient, *, session: str = "") -> tuple[bool, str]:
    """Lock и пауза до TCP. Иначе вход по QR бьётся с уже живым ботом и Telegram гасит ключ."""
    from bot.client_registry import is_held
    from bot.instance_guard import acquire_account, pause_before_telegram, release_account

    aid = (_state.get("account_id") or "main").strip() or "main"
    if is_held(aid):
        return False, f"Аккаунт [{aid}] уже подключён в этом процессе."
    ok, msg = acquire_account(aid, role="login")
    if not ok:
        return False, msg
    try:
        await pause_before_telegram(aid)
        await client.connect()
    except Exception:
        release_account(aid)
        raise
    ok, msg = await _claim_login_client(client, session=session)
    if not ok:
        try:
            await client.disconnect()
        except Exception:
            pass
        if not is_held(aid):
            release_account(aid)
        return False, msg
    return True, "ok"


async def _release_login_client(*, disconnect: bool = True) -> None:
    from bot.client_registry import release

    aid = (_state.get("account_id") or "main").strip() or "main"
    client = _state.get("_client")
    _state["_client"] = None
    if disconnect and client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass
    await release(aid, disconnect=False)


def _hydrate_bind_from_accounts() -> None:
    """После рестарта: взять bind слота из tg_accounts ('' = общий), не форсить default."""
    if _state.get("manager_id") is not None:
        return
    try:
        from bot.tg_accounts import get_tg_accounts

        tg = get_tg_accounts()
        aid = (_state.get("account_id") or "main").strip() or "main"
        acc = tg.get(aid) or tg.main()
        if acc is None:
            return
        _state["account_id"] = acc.id
        # явно сохраняем "" как общий — не подменять на default_manager_id
        _state["manager_id"] = (acc.manager_id or "").strip()
    except Exception:
        logger.debug("hydrate bind skipped", exc_info=True)


def _selected_manager_id() -> str:
    """Выбранный bind: '' = общий; если ещё не выбирали (None) — default для UX входа."""
    _hydrate_bind_from_accounts()
    raw = _state.get("manager_id")
    if raw is None:
        try:
            return get_registry().default_manager_id
        except Exception:
            return "default"
    return str(raw or "").strip()


async def _finish_ok(client: TelegramClient, *, auth_source: str = "") -> dict[str, Any]:
    """Завершить вход: сначала полностью отключить login-клиент, потом сохранить сессию.

    Порядок важен: пока login-клиент online, бот не должен подключаться с тем же
    auth key (Telegram отзывает сессии при двух клиентах).
    """
    me = await client.get_me()
    sess = client.session.save()
    phone = ("+" + me.phone) if me.phone and not str(me.phone).startswith("+") else (me.phone or "")
    reg = get_registry()
    if _state.get("manager_id") is None:
        mid = reg.default_manager_id
    else:
        mid = str(_state.get("manager_id") or "").strip()
    if mid and mid not in reg.managers:
        mid = reg.default_manager_id
    preferred = (_state.get("account_id") or "").strip()
    account_id = preferred or "main"
    source = (auth_source or _state.get("auth_source") or "").strip()

    # 1) Полный disconnect login-клиента + снятие lock — до записи сессии
    try:
        await client.disconnect()
    except Exception:
        logger.debug("login disconnect before save", exc_info=True)
    _state["_client"] = None
    try:
        from bot.client_registry import release as release_client

        await release_client(account_id, disconnect=False)
    except Exception:
        logger.debug("login registry release", exc_info=True)

    # 2) Только теперь пишем сессию — бот может подхватить один клиент
    try:
        from bot.tg_accounts import get_tg_accounts

        tg = get_tg_accounts()
        mname = reg.managers[mid].name if mid in reg.managers else ("общий" if not mid else mid)
        acc = tg.apply_authorized_session(
            session=sess,
            phone=phone or "",
            telegram_user_id=int(me.id),
            manager_id=mid,
            preferred_account_id=preferred,
            label=mname if preferred and preferred != "main" else "",
            auth_source=source,
        )
        account_id = acc.id
        mid = (acc.manager_id or "").strip()
        if source == "tdata":
            _state["tdata_warning"] = True
    except ValueError as e:
        _state["status"] = "error"
        _state["message"] = str(e)
        _state["done"] = False
        return {**_public_status(), "ok": False}
    except Exception:
        logger.exception("tg_accounts save failed")

    # Источник истины — data/tg_accounts.json. Не пишем TELEGRAM_SESSION в .env / db meta
    # (старые копии в managers.json не обновляем, чтобы не плодить второй auth key).
    logger.info("session stored in tg_accounts.json only account=%s", account_id)

    _state["done"] = True
    _state["need_2fa"] = False
    _state["status"] = "ok"
    _state["manager_id"] = mid
    _state["account_id"] = account_id
    _state["me"] = {
        "id": me.id,
        "username": me.username or "",
        "phone": phone,
        "first_name": me.first_name or "",
        "manager_id": mid,
        "account_id": account_id,
    }
    if mid:
        mname = reg.managers[mid].name if mid in reg.managers else mid
        bind_txt = f"→ менеджер «{mname}» [{mid}]"
    else:
        bind_txt = "· общий для всех менеджеров"
    warn = ""
    if source == "tdata":
        warn = (
            " Внимание: сессия из Telegram Desktop (tdata). "
            "Не запускайте Desktop с тем же аккаунтом одновременно — "
            "Telegram отзовёт сессии. Надёжнее войти по QR или коду "
            "(отдельная авторизация)."
        )
    _state["message"] = (
        f"Готово: Telegram-аккаунт [{account_id}] {bind_txt}: "
        f"{me.first_name} @{me.username or '—'} ({phone or 'без телефона'}). "
        "Менеджеры работают в панели; сообщения уходят с этого аккаунта."
        + warn
    )
    logger.info("login ok account=%s manager=%s id=%s source=%s", account_id, mid or "*", me.id, source)
    try:
        from bot.config import get_settings
        from bot.dashboard.distribute import on_account_linked
        from bot.store import Store

        dist = on_account_linked(Store(get_settings().db_path), account_id, mid)
        if dist.get("assigned"):
            _state["message"] += f" Клиентов закреплено: {dist['assigned']}."
    except Exception:
        logger.exception("auto-distribute after telegram link failed")
    return {"ok": True, "me": _state["me"], "message": _state["message"], "manager_id": mid}


HTML = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Home24 — аккаунт бота</title>
<style>
:root{--bg:#0c0f0e;--card:#161c19;--text:#eef4f0;--muted:#8fa297;--acc:#3db88a;--ok:#3ecf8e;--bad:#e07070}
*{box-sizing:border-box}body{margin:0;font-family:"Segoe UI",Candara,Calibri,sans-serif;background:var(--bg);color:var(--text)}
main{max-width:720px;margin:0 auto;padding:1.5rem}
h1{font-size:1.5rem;margin:0 0 .5rem;font-family:Georgia,"Times New Roman",serif}h2{font-size:1.05rem;margin:1.4rem 0 .6rem;color:var(--acc)}
p,li{line-height:1.45;color:var(--muted)}.card{background:var(--card);border-radius:14px;padding:1rem 1.1rem;margin:.7rem 0;border:1px solid #243029}
button,.btn{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:.55rem 1rem;font-size:.95rem;cursor:pointer;margin:.2rem .3rem .2rem 0}
button.secondary{background:#243029}button:disabled{opacity:.5;cursor:not-allowed}
input,select{width:100%;padding:.55rem .7rem;border-radius:10px;border:1px solid #334;background:#0d1218;color:var(--text);margin:.35rem 0}
#status{padding:.75rem 1rem;border-radius:10px;background:#132033;margin:1rem 0;min-height:2.5rem}
#status.ok{background:#143028;color:var(--ok)}#status.err{background:#2a1518;color:var(--bad)}
#qrimg{background:#fff;padding:10px;border-radius:10px;display:inline-block;margin:.5rem 0}
.rec{border-left:3px solid var(--ok);padding-left:.75rem;margin:.5rem 0}
label{display:block;font-size:.85rem;color:var(--muted);margin-top:.4rem}
.hidden{display:none}
#toast{position:fixed;right:1rem;bottom:1rem;z-index:50;max-width:22rem;padding:.75rem 1rem;border-radius:12px;background:#1a2e24;color:var(--ok);border:1px solid #2a5a40;box-shadow:0 8px 24px rgba(0,0,0,.35);opacity:0;transform:translateY(8px);transition:opacity .2s,transform .2s;pointer-events:none}
#toast.show{opacity:1;transform:translateY(0)}#toast.err{background:#2a1518;color:var(--bad);border-color:#5a2a30}
</style></head><body><main>
<div id="toast" role="status" aria-live="polite"></div>
<h1>Home24 — Telegram бота</h1>
<p>Подключает <b>только админ</b>. Это аккаунт компании (SIM), не личные Telegram менеджеров. Менеджеры работают в панели — сообщения уходят с этого аккаунта.</p>
<div id="status">Загрузка…</div>

<section class="card">
<h2>Слот аккаунта</h2>
<p>Основной слот — <code>main</code>. При нескольких SIM компании можно выбрать слот и при желании привязать к веб-менеджеру (клиенты этого менеджера пишутся с этой SIM). Если аккаунт один — все менеджеры делят его.</p>
<label>Слот</label>
<select id="accSelect"><option value="main">main — основной</option>
<option value="acc2">acc2</option><option value="acc3">acc3</option>
<option value="acc4">acc4</option><option value="acc5">acc5</option></select>
<label>Веб-менеджер (опционально)</label>
<select id="mgrSelect"></select>
<button id="btnMgr" type="button" class="secondary">Сохранить выбор</button>
<p id="mgrHint" style="margin-top:.5rem"></p>
</section>

<section class="card" id="safetyCard">
<h2>Безопасность входа</h2>
<ul id="safetyList" class="rec" style="margin:.4rem 0;padding-left:1.1rem">
<li>Только <b>один</b> процесс Home24 на этот ПК (start.bat).</li>
<li>Один TelegramClient на аккаунт — второй экземпляр будет отклонён.</li>
<li>При отзыве сессии бот <b>не</b> перезапрашивает код сам — войдите вручную здесь.</li>
<li>Рекомендуется облачный пароль 2FA и проверка «Активные сессии» в Telegram.</li>
</ul>
<p id="safetyStatus" style="margin:.5rem 0;font-size:.9rem">Статус: …</p>
</section>

<section class="card">
<h2>1. Из Telegram Desktop (tdata)</h2>
<p class="rec">Просто, но рискованно: Desktop и бот с <b>одной</b> сессией одновременно → Telegram отзовёт все входы. <b>Закройте Desktop полностью</b> перед импортом. Надёжнее — QR или код ниже (отдельная авторизация).</p>
<p>Папка: <code id="tdataPath">—</code></p>
<button id="btnScanTdata" type="button">Найти аккаунты в Telegram Desktop</button>
<div id="tdataList" class="hidden"></div>
</section>

<section class="card">
<h2>2. QR-код</h2>
<p>В телефоне/другом Telegram: <b>Настройки → Устройства → Подключить устройство</b> — сканируйте QR со страницы (не камерой галереи).</p>
<button id="btnQr" type="button">Показать QR</button>
<button id="btnQrStop" type="button" class="secondary">Остановить QR</button>
<div id="qrBox" class="hidden"><div id="qrimg"></div></div>
<div id="qr2fa" class="hidden">
<label>Облачный пароль 2FA (если Telegram попросил)</label>
<input id="qrPwd" type="password" autocomplete="current-password"/>
<button id="btnQr2fa" type="button">Отправить пароль</button>
</div>
</section>

<section class="card">
<h2>3. Телефон и код</h2>
<p>Код уходит <b>только</b> когда нажмёте «Запросить код» — один раз, без повторов.</p>
<label>Номер</label>
<input id="phone" type="tel" placeholder="[REDACTED]" value="[REDACTED]"/>
<button id="btnCode" type="button">Запросить код</button>
<label>Код из чата «Telegram»</label>
<input id="code" type="text" inputmode="numeric" autocomplete="one-time-code"/>
<label>Облачный пароль 2FA (если спросят)</label>
<input id="pwd" type="password" autocomplete="current-password"/>
<button id="btnSign" type="button">Войти</button>
</section>

<p style="margin-top:1.5rem;font-size:.85rem">После успешного входа закройте эту вкладку и убедитесь, что бот запущен через <b>start.bat</b>.</p>
<script>
async function api(path, body){
  // относительные пути — работают и в /accounts/ iframe
  const p=path.startsWith('/') ? path.slice(1) : path;
  const opt={method: body? 'POST':'GET', headers:{'Content-Type':'application/json'}};
  if(body) opt.body=JSON.stringify(body);
  const r=await fetch(p, opt);
  return r.json();
}
function showToast(msg, ok=true){
  const t=document.getElementById('toast');
  if(!t) return;
  t.textContent=msg||'';
  t.className=ok?'show':'show err';
  clearTimeout(showToast._tm);
  showToast._tm=setTimeout(()=>{ t.className=''; }, 3200);
}
function setStatus(s, {forceSelect=false}={}){
  const el=document.getElementById('status');
  let msg=s.message||'';
  if(s.quiet_active && s.quiet_label){
    msg=(msg?msg+' ':'')+'⏱ '+s.quiet_label+' (outreach пауза, ответы гостям ок)';
  }
  el.textContent=msg;
  el.className=(s.status==='ok'||s.done)?'ok':(s.status==='error'?'err':'');
  if(s.qr_b64){
    document.getElementById('qrBox').classList.remove('hidden');
    document.getElementById('qrimg').innerHTML='<img width="280" height="280" src="data:image/png;base64,'+s.qr_b64+'"/>';
  }
  document.getElementById('qr2fa').classList.toggle('hidden', !s.need_2fa);
  if(s.managers){
    const sel=document.getElementById('mgrSelect');
    const acc=document.getElementById('accSelect');
    const cur=(s.manager_id==null?'':String(s.manager_id));
    const opts=[{id:'',name:'— общий (все менеджеры)'}].concat(s.managers);
    const prevMgr=sel.value;
    const prevAcc=acc.value;
    if(sel.options.length!==opts.length || sel.dataset.ready!=='1'){
      sel.innerHTML=opts.map(m=>
        `<option value="${m.id}">${m.name}${m.id?(' ['+m.id+']'):''}</option>`
      ).join('');
      sel.dataset.ready='1';
    }
    // не затирать выбор, пока пользователь редактирует / не сохранил
    const editing = document.activeElement===sel || document.activeElement===acc
      || sel.dataset.dirty==='1' || acc.dataset.dirty==='1';
    if(forceSelect || !editing){
      sel.value=cur;
      if(s.account_id) acc.value=s.account_id;
    } else {
      // после пересборки options восстановить локальный выбор
      if([...sel.options].some(o=>o.value===prevMgr)) sel.value=prevMgr;
      if(prevAcc) acc.value=prevAcc;
    }
    document.getElementById('mgrHint').textContent=
      'Слот '+ (acc.value||'main') + (sel.value?(' → веб-менеджер '+sel.value):' · общий для команды');
  }
}
const mgrSelect=document.getElementById('mgrSelect');
const accSelect=document.getElementById('accSelect');
mgrSelect.addEventListener('change',()=>{ mgrSelect.dataset.dirty='1'; });
accSelect.addEventListener('change',()=>{ accSelect.dataset.dirty='1'; });
document.getElementById('btnMgr').onclick=async()=>{
  const id=document.getElementById('mgrSelect').value; // '' = общий
  const account_id=document.getElementById('accSelect').value||'main';
  const r=await api('api/manager/select',{manager_id:id, account_id});
  mgrSelect.dataset.dirty='0';
  accSelect.dataset.dirty='0';
  setStatus(r,{forceSelect:true});
  if(r.ok!==false && r.status!=='error'){
    showToast(id?('Привязка: '+id):'Сохранено: общий аккаунт (все менеджеры)');
  } else {
    showToast(r.message||'Не удалось сохранить', false);
  }
};
document.getElementById('btnScanTdata').onclick=async()=>{
  const r=await api('api/tdata/scan',{});
  setStatus(r);
  const box=document.getElementById('tdataList');
  if(!r.ok){ box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  box.innerHTML=(r.accounts||[]).map(a=>
    `<div style="margin:.5rem 0"><button data-i="${a.index}" class="pick">${a.label}</button></div>`
  ).join('') || '<p>Аккаунты не найдены</p>';
  box.querySelectorAll('.pick').forEach(btn=>{
    btn.onclick=async()=>{
      const r2=await api('api/tdata/use',{index:Number(btn.dataset.i)});
      setStatus(r2);
    };
  });
};
document.getElementById('btnQr').onclick=async()=>{ setStatus(await api('api/qr/start',{})); };
document.getElementById('btnQrStop').onclick=async()=>{ setStatus(await api('api/qr/stop',{})); };
document.getElementById('btnQr2fa').onclick=async()=>{
  setStatus(await api('api/qr/2fa',{[REDACTED]
};
document.getElementById('btnCode').onclick=async()=>{
  setStatus(await api('api/phone/send_code',{phone:document.getElementById('phone').value}));
};
document.getElementById('btnSign').onclick=async()=>{
  setStatus(await api('api/phone/sign_in',{
    phone:document.getElementById('phone').value,
    code:document.getElementById('code').value,
    [REDACTED]
  }));
};
async function refresh(){
  const s=await api('api/status');
  setStatus(s); // не трогает select при dirty/focus
  if(s.tdata_path) document.getElementById('tdataPath').textContent=s.tdata_path;
  const phoneEl=document.getElementById('phone');
  if(s.default_phone && document.activeElement!==phoneEl && phoneEl.dataset.dirty!=='1'){
    phoneEl.value=s.default_phone;
  }
  const ss=document.getElementById('safetyStatus');
  if(ss && s.safety){
    const a=s.safety;
    const lock=a.account_lock||{};
    const parts=[
      'экземпляр PID '+ (a.instance_pid||'—'),
      'сессия: '+(a.session_status||'—')+(a.has_session?' (есть)':' (нет)'),
      lock.held?('слот занят PID '+lock.pid):'слот свободен для входа',
    ];
    if(a.last_connect_at){
      try{ parts.push('последний connect: '+new Date(a.last_connect_at*1000).toLocaleString('ru-RU')); }catch(e){}
    }
    if(a.tdata_warning || s.tdata_warning){
      parts.push('⚠ tdata: не запускайте Desktop параллельно');
    }
    if(a.device_model) parts.push('device: '+a.device_model);
    ss.textContent=parts.join(' · ');
  }
  const btn=document.getElementById('btnCode');
  if(btn && s.cooldown_sec>0){
    btn.disabled=true;
    btn.textContent='Подождите '+s.cooldown_sec+'с';
  } else if(btn){
    btn.disabled=false;
    btn.textContent='Запросить код';
  }
}
document.getElementById('phone').addEventListener('input',(e)=>{ e.target.dataset.dirty='1'; });
refresh(); setInterval(refresh, 2000);
if(!window.__qrBoot){ window.__qrBoot=1; document.getElementById('btnQr').click(); }
</script>
</main></body></html>
"""


def _public_status() -> dict[str, Any]:
    tdata = default_tdata_path()
    reg = get_registry()
    _hydrate_bind_from_accounts()
    raw = _state.get("manager_id")
    if raw is None:
        # ещё не выбирали и нет слота в tg_accounts — UX default (не запись в _state)
        mid = reg.default_manager_id
    else:
        mid = str(raw or "").strip()  # "" = общий
    mgr = reg.get(mid) if mid else reg.default()
    phone_default = (
        (mgr.phone if mgr else "")
        or (os.getenv("MANAGER_PHONE") or "[REDACTED]")
    ).strip()
    quiet = {
        "quiet_active": False,
        "quiet_remaining_sec": 0,
        "quiet_label": "",
        "no_outreach_until": 0,
        "quiet_hours_after_login": 24,
    }
    try:
        from bot.tg_accounts import get_tg_accounts

        acc = get_tg_accounts().get((_state.get("account_id") or "main"))
        if acc:
            pub = acc.public_dict()
            quiet = {
                "quiet_active": bool(pub.get("quiet_active")),
                "quiet_remaining_sec": int(pub.get("quiet_remaining_sec") or 0),
                "quiet_label": pub.get("quiet_label") or "",
                "no_outreach_until": float(pub.get("no_outreach_until") or 0),
                "quiet_hours_after_login": int(pub.get("quiet_hours_after_login") or 24),
            }
    except Exception:
        pass
    safety: dict[str, Any] = {
        "one_instance": True,
        "instance_pid": os.getpid(),
        "session_status": "unknown",
        "last_connect_at": 0,
        "auth_source": "",
        "tdata_warning": False,
        "advice": [
            "Запускайте только один экземпляр Home24 (start.bat).",
            "Задайте облачный пароль 2FA в Telegram (Настройки → Конфиденциальность).",
            "Проверьте Активные сессии и завершите чужие устройства.",
            "Не держите Telegram Desktop с тем же аккаунтом, если вошли через tdata.",
        ],
    }
    try:
        from bot.instance_guard import global_status, lock_status
        from bot.client_registry import snapshot as client_snap

        g = global_status()
        aid = (_state.get("account_id") or "main").strip() or "main"
        alock = lock_status(f"account_{aid}")
        safety.update(
            {
                "one_instance": bool(g.get("global", {}).get("held"))
                or g.get("pid") == os.getpid(),
                "global_lock": g.get("global"),
                "account_lock": alock,
                "live_clients": client_snap(),
            }
        )
        from bot.tg_accounts import get_tg_accounts

        acc = get_tg_accounts().get(aid)
        if acc:
            safety["session_status"] = acc.status
            safety["last_connect_at"] = float(acc.last_connect_at or 0)
            safety["auth_source"] = acc.auth_source or ""
            safety["tdata_warning"] = (acc.auth_source or "") == "tdata"
            safety["has_session"] = bool((acc.session or "").strip())
            safety["device_model"] = acc.device_model or ""
            safety["revoked"] = acc.status == "revoked"
    except Exception:
        logger.debug("safety status", exc_info=True)
    cool_left = 0
    try:
        import time as _time

        cool_left = max(0, int(float(_state.get("code_cooldown_until") or 0) - _time.time()))
    except Exception:
        pass
    return {
        "ok": _state["status"] != "error",
        "status": _state["status"],
        "message": _state["message"],
        "qr_b64": _state.get("qr_b64") or "",
        "need_2fa": bool(_state.get("need_2fa")),
        "done": bool(_state.get("done")),
        "me": _state.get("me"),
        "manager_id": mid,
        "account_id": (_state.get("account_id") or "main"),
        "managers": reg.list_public(),
        "tdata_path": str(tdata) if tdata else "(не найдена — укажите путь вручную позже)",
        "tdata_running": telegram_desktop_running(),
        "default_phone": phone_default,
        "safety": safety,
        "cooldown_sec": cool_left,
        "tdata_warning": bool(safety.get("tdata_warning") or _state.get("tdata_warning")),
        **quiet,
    }


async def handle_manager_select(req: web.Request) -> web.Response:
    data = await req.json()
    # явно разрешаем пустую строку = общий; не подменять на default
    mid_raw = data.get("manager_id")
    mid = "" if mid_raw is None else str(mid_raw).strip()
    account_id = (data.get("account_id") or "main").strip() or "main"
    if mid in ("-", "__shared__", "shared", "*"):
        mid = ""
    # устаревший ярлык «default» из старого UI — тоже общий, не anna
    if mid == "default":
        mid = ""
    reg = get_registry()
    if mid and mid not in reg.managers:
        _state["status"] = "error"
        _state["message"] = f"Неизвестный веб-менеджер: {mid}"
        return web.json_response({**_public_status(), "ok": False})
    _state["manager_id"] = mid  # "" остаётся общим
    _state["account_id"] = account_id
    _state["done"] = False
    _state["status"] = "idle"
    # сразу записать bind в tg_accounts.json (даже без повторного логина)
    try:
        from bot.tg_accounts import get_tg_accounts

        tg = get_tg_accounts()
        if account_id in tg.accounts or tg.accounts:
            if account_id not in tg.accounts:
                tg.upsert(account_id=account_id, is_main=(account_id == "main"))
            tg.upsert(account_id=account_id, manager_id=mid)
    except Exception:
        logger.exception("persist manager bind failed")
    bind = f"→ веб-менеджер [{mid}]" if mid else "· общий для всех менеджеров"
    _state["message"] = (
        f"Сохранено: слот Telegram [{account_id}] {bind}. "
        "Дальше — вход через Desktop / QR / телефон при необходимости."
    )
    _state["status"] = "ok"
    return web.json_response(_public_status())


async def handle_index(_req: web.Request) -> web.Response:
    return web.Response(text=HTML, content_type="text/html", charset="utf-8")


async def handle_status(_req: web.Request) -> web.Response:
    return web.json_response(_public_status())


async def handle_tdata_scan(_req: web.Request) -> web.Response:
    try:
        if telegram_desktop_running():
            _state["status"] = "error"
            _state["message"] = (
                "Сначала полностью закройте Telegram Desktop "
                "(проверьте трей возле часов), затем нажмите снова."
            )
            return web.json_response({**_public_status(), "ok": False})
        src = default_tdata_path()
        if not src:
            _state["status"] = "error"
            _state["message"] = "Папка tdata не найдена. Установите Telegram Desktop и войдите в аккаунт."
            return web.json_response({**_public_status(), "ok": False})
        _state["status"] = "working"
        _state["message"] = "Копирую tdata и читаю аккаунты…"
        dest = copy_tdata(src)
        accounts = await list_accounts_from_tdata(dest, egress=_slot_egress())
        _state["_tdata_sessions"] = {a.index: a.session for a in accounts}
        _state["tdata_accounts"] = [account_public_dict(a) for a in accounts]
        if not accounts:
            _state["status"] = "error"
            _state["message"] = "В tdata нет авторизованных аккаунтов."
            return web.json_response({**_public_status(), "ok": False, "accounts": []})
        _state["status"] = "idle"
        _state["message"] = f"Найдено аккаунтов: {len(accounts)}. Выберите нужный."
        return web.json_response(
            {**_public_status(), "ok": True, "accounts": _state["tdata_accounts"]}
        )
    except Exception as e:
        logger.exception("tdata scan")
        _state["status"] = "error"
        _state["message"] = _public_login_error(e, f"Ошибка чтения tdata: {type(e).__name__}")
        return web.json_response({**_public_status(), "ok": False})


async def handle_tdata_use(req: web.Request) -> web.Response:
    try:
        data = await req.json()
        idx = int(data.get("index"))
        sess = (_state.get("_tdata_sessions") or {}).get(idx)
        if not sess:
            return web.json_response(
                {**_public_status(), "ok": False, "message": "Сначала найдите аккаунты", "status": "error"}
            )
        _state["auth_source"] = "tdata"
        _state["message"] = (
            "Импорт из Telegram Desktop (tdata). Desktop с этим аккаунтом "
            "не должен работать одновременно — иначе Telegram отзовёт сессии. "
            "Надёжнее QR или код (отдельная авторизация)."
        )
        client = _make_client(sess)
        ok, msg = await _connect_exclusive(client, session=sess)
        if not ok:
            _state["status"] = "error"
            _state["message"] = msg
            return web.json_response({**_public_status(), "ok": False})
        _state["_client"] = client
        if not await client.is_user_authorized():
            await _release_login_client(disconnect=True)
            _state["status"] = "error"
            _state["message"] = "Сессия из tdata не принята Telegram."
            return web.json_response({**_public_status(), "ok": False})
        return web.json_response(await _finish_ok(client, auth_source="tdata"))
    except Exception as e:
        logger.exception("tdata use")
        _state["status"] = "error"
        _state["message"] = _public_login_error(
            e, f"Не удалось применить аккаунт: {type(e).__name__}"
        )
        return web.json_response({**_public_status(), "ok": False})


def _relax_quiet_if_requested() -> None:
    """Срочный старт рассылки: не держать 24ч тишины после этого входа."""
    flag = (os.getenv("HOME24_SKIP_QUIET") or "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return
    try:
        from bot.tg_accounts import get_tg_accounts

        tg = get_tg_accounts()
        aid = (_state.get("account_id") or "main").strip() or "main"
        acc = tg.get(aid) or tg.main()
        if acc is None:
            return
        acc.quiet_hours_after_login = 0
        acc.no_outreach_until = 0
        tg.save()
        logger.info("quiet skipped after login account=%s", acc.id)
    except Exception:
        logger.exception("skip quiet failed")


async def _qr_loop(client: TelegramClient) -> None:
    import io

    import qrcode

    global _state
    while _state.get("_qr_running"):
        try:
            qr = await client.qr_login()
            _state["_qr"] = qr
            img = qrcode.make(qr.url)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            _state["qr_b64"] = base64.b64encode(buf.getvalue()).decode()
            _state["status"] = "qr"
            # Ждём до реального expires токена (не фиксированные 90 с — иначе stale QR).
            exp = getattr(qr, "expires", None)
            if exp is not None:
                try:
                    import datetime as _dt

                    now = _dt.datetime.now(tz=_dt.timezone.utc)
                    expires_at = exp if exp.tzinfo else exp.replace(tzinfo=_dt.timezone.utc)
                    sec = max(5.0, (expires_at - now).total_seconds())
                    _state["message"] = (
                        f"Отсканируйте QR. Обновится через ~{int(sec)} с, когда токен истечёт."
                    )
                except Exception:
                    _state["message"] = "Отсканируйте QR. Он обновится сам, когда токен истечёт."
            else:
                _state["message"] = "Отсканируйте QR. Он обновится сам, когда токен истечёт."
            try:
                # timeout=None → Telethon ждёт до qr.expires
                await qr.wait(timeout=None)
            except SessionPasswordNeededError:
                pwd = (os.getenv("TELEGRAM_2FA") or "").strip()
                if pwd:
                    try:
                        await client.sign_in([REDACTED]
                        if await client.is_user_authorized():
                            await _finish_ok(client, auth_source="qr")
                            _relax_quiet_if_requested()
                            return
                    except Exception:
                        logger.exception("qr auto 2fa failed")
                _state["need_2fa"] = True
                _state["status"] = "need_2fa"
                _state["message"] = "QR принят. Введите облачный пароль 2FA на странице."
                return
            except asyncio.TimeoutError:
                _state["message"] = "QR устарел — рисую новый…"
                continue
            if await client.is_user_authorized():
                await _finish_ok(client, auth_source="qr")
                _relax_quiet_if_requested()
                return
        except asyncio.CancelledError:
            return
        except Exception as e:
            _state["status"] = "error"
            _state["message"] = f"QR: {type(e).__name__}"
            await asyncio.sleep(3)


async def handle_qr_start(_req: web.Request) -> web.Response:
    try:
        if _state.get("_qr_task") and not _state["_qr_task"].done():
            return web.json_response(_public_status())
        client = _state.get("_client")
        if client is None:
            client = _make_client()
            ok, msg = await _connect_exclusive(client)
            if not ok:
                _state["status"] = "error"
                _state["message"] = msg
                return web.json_response({**_public_status(), "ok": False})
            _state["_client"] = client
            _state["auth_source"] = "qr"
        if await client.is_user_authorized():
            return web.json_response(await _finish_ok(client, auth_source="qr"))
        _state["_qr_running"] = True
        _state["need_2fa"] = False
        _state["_qr_task"] = asyncio.create_task(_qr_loop(client))
        _state["status"] = "qr"
        _state["message"] = "Готовлю QR…"
        return web.json_response(_public_status())
    except Exception as e:
        logger.exception("qr start")
        _state["status"] = "error"
        err = str(e)
        msg = (
            err
            if ("my.telegram.org" in err or "TELEGRAM_API" in err)
            else _public_login_error(e, f"Не удалось стартовать QR: {type(e).__name__}")
        )
        _state["message"] = msg
        return web.json_response({**_public_status(), "ok": False})


async def handle_qr_stop(_req: web.Request) -> web.Response:
    _state["_qr_running"] = False
    t = _state.get("_qr_task")
    if t and not t.done():
        t.cancel()
    _state["qr_b64"] = ""
    _state["status"] = "idle"
    _state["message"] = "QR остановлен"
    return web.json_response(_public_status())


async def handle_qr_2fa(req: web.Request) -> web.Response:
    data = await req.json()
    pwd = (data.get("password") or "").strip()
    client = _state.get("_client")
    if not client or not pwd:
        _state["status"] = "error"
        _state["message"] = "Введите пароль 2FA"
        return web.json_response({**_public_status(), "ok": False})
    try:
        # do not log password
        await client.sign_in([REDACTED]
        if await client.is_user_authorized():
            return web.json_response(await _finish_ok(client))
        _state["status"] = "error"
        _state["message"] = "Пароль принят, но вход не завершён"
        return web.json_response({**_public_status(), "ok": False})
    except PasswordHashInvalidError:
        _state["status"] = "error"
        _state["message"] = "Неверный облачный пароль 2FA"
        return web.json_response({**_public_status(), "ok": False})
    except Exception as e:
        logger.exception("qr 2fa")
        _state["status"] = "error"
        _state["message"] = f"2FA: {type(e).__name__}"
        return web.json_response({**_public_status(), "ok": False})


async def handle_send_code(req: web.Request) -> web.Response:
    """Явная кнопка — один запрос, затем cooldown. Без авто-повторов."""
    import time as _time

    from telethon.errors import FloodWaitError

    data = await req.json()
    phone = "".join(ch for ch in (data.get("phone") or "") if ch.isdigit() or ch == "+")
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    if len(phone) < 8:
        _state["status"] = "error"
        _state["message"] = "Укажите номер в формате +7…"
        return web.json_response({**_public_status(), "ok": False})
    now = _time.time()
    cool_until = float(_state.get("code_cooldown_until") or 0)
    if cool_until > now:
        left = int(cool_until - now)
        _state["status"] = "error"
        _state["message"] = (
            f"Подождите {left}с перед повторным запросом кода "
            "(защита от FloodWait / отзыва сессий)."
        )
        return web.json_response({**_public_status(), "ok": False, "cooldown_sec": left})
    if _state.get("phone_hash") and _state.get("phone") == phone:
        left = max(0, int(cool_until - now)) if cool_until else 60
        _state["status"] = "error"
        _state["message"] = (
            "Код уже запрашивали для этого номера. Введите код из чата «Telegram» "
            f"или подождите {max(left, 60)}с."
        )
        return web.json_response({**_public_status(), "ok": False})
    try:
        # отклонить вход, если бот уже держит этот слот
        from bot.instance_guard import lock_status

        aid = (_state.get("account_id") or "main").strip() or "main"
        st = lock_status(f"account_{aid}")
        if st.get("held") and int(st.get("pid") or 0) != os.getpid():
            _state["status"] = "error"
            _state["message"] = (
                f"Аккаунт [{aid}] уже используется процессом PID {st.get('pid')}. "
                "Остановите второй экземпляр Home24 перед входом."
            )
            return web.json_response({**_public_status(), "ok": False})

        client = _state.get("_client")
        if client is None:
            client = _make_client()
            ok, msg = await _connect_exclusive(client)
            if not ok:
                _state["status"] = "error"
                _state["message"] = msg
                return web.json_response({**_public_status(), "ok": False})
            _state["_client"] = client
            _state["auth_source"] = "code"
        if await client.is_user_authorized():
            return web.json_response(await _finish_ok(client, auth_source="code"))
        sent = await client.send_code_request(phone, force_sms=False)
        _state["phone"] = phone
        _state["phone_hash"] = sent.phone_code_hash
        _state["code_cooldown_until"] = now + 60
        _state["status"] = "code_sent"
        ctype = type(sent.type).__name__ if sent.type else "?"
        _state["message"] = (
            f"Код отправлен ({ctype}). Смотрите чат «Telegram». "
            "Повторный запрос — не раньше чем через 60с."
        )
        return web.json_response({**_public_status(), "cooldown_sec": 60})
    except FloodWaitError as e:
        wait = int(getattr(e, "seconds", 0) or 0)
        _state["code_cooldown_until"] = now + max(wait, 1)
        _state["status"] = "error"
        _state["message"] = (
            f"Telegram FloodWait: подождите {wait}с, затем запросите код снова."
        )
        return web.json_response(
            {**_public_status(), "ok": False, "flood_wait_sec": wait}
        )
    except Exception as e:
        logger.exception("send_code")
        _state["status"] = "error"
        err = str(e)
        _state["message"] = (
            err
            if ("my.telegram.org" in err or "TELEGRAM_API" in err)
            else _public_login_error(e, f"Не удалось запросить код: {type(e).__name__}")
        )
        return web.json_response({**_public_status(), "ok": False})


async def handle_sign_in(req: web.Request) -> web.Response:
    data = await req.json()
    phone = _state.get("phone") or (data.get("phone") or "")
    phone = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    code = "".join(ch for ch in (data.get("code") or "") if ch.isdigit())
    pwd = (data.get("password") or "").strip()
    phone_hash = _state.get("phone_hash") or ""
    client = _state.get("_client")
    if not client or not phone_hash:
        _state["status"] = "error"
        _state["message"] = "Сначала нажмите «Запросить код»"
        return web.json_response({**_public_status(), "ok": False})
    if len(code) < 5:
        _state["status"] = "error"
        _state["message"] = "Введите код из цифр"
        return web.json_response({**_public_status(), "ok": False})
    try:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_hash)
        except SessionPasswordNeededError:
            if not pwd:
                _state["need_2fa"] = True
                _state["status"] = "need_2fa"
                _state["message"] = "Нужен облачный пароль 2FA — введите в поле ниже и нажмите «Войти»"
                return web.json_response({**_public_status(), "ok": False})
            await client.sign_in([REDACTED]
        if await client.is_user_authorized():
            return web.json_response(await _finish_ok(client))
        _state["status"] = "error"
        _state["message"] = "Вход не завершён"
        return web.json_response({**_public_status(), "ok": False})
    except PhoneCodeInvalidError:
        _state["status"] = "error"
        _state["message"] = "Неверный код. Новый код сам не запрашиваю."
        return web.json_response({**_public_status(), "ok": False})
    except PhoneCodeExpiredError:
        _state["phone_hash"] = ""
        _state["status"] = "error"
        _state["message"] = "Код просрочен. Нажмите «Запросить код» снова позже."
        return web.json_response({**_public_status(), "ok": False})
    except PasswordHashInvalidError:
        _state["status"] = "error"
        _state["message"] = "Неверный облачный пароль 2FA"
        return web.json_response({**_public_status(), "ok": False})
    except Exception as e:
        logger.exception("sign_in")
        _state["status"] = "error"
        _state["message"] = f"Ошибка входа: {type(e).__name__}"
        return web.json_response({**_public_status(), "ok": False})


def create_app() -> web.Application:
    # не форсить default_manager_id: общий ('') должен переживать рестарт из tg_accounts
    _hydrate_bind_from_accounts()
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/manager/select", handle_manager_select)
    app.router.add_post("/api/tdata/scan", handle_tdata_scan)
    app.router.add_post("/api/tdata/use", handle_tdata_use)
    app.router.add_post("/api/qr/start", handle_qr_start)
    app.router.add_post("/api/qr/stop", handle_qr_stop)
    app.router.add_post("/api/qr/2fa", handle_qr_2fa)
    app.router.add_post("/api/phone/send_code", handle_send_code)
    app.router.add_post("/api/phone/sign_in", handle_sign_in)
    return app


async def run_login_server(*, open_browser: bool = True, port: int = LOGIN_PORT) -> None:
    """Блокирующий сервер логина до успешного входа (или Ctrl+C)."""
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "[REDACTED]", port)
    await site.start()
    url = f"http://[REDACTED]:{port}/"
    logger.info("login UI %s", url)
    print(f"Откройте страницу входа: {url}", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        while not _state.get("done"):
            await asyncio.sleep(0.5)
    finally:
        _state["_qr_running"] = False
        await runner.cleanup()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # load .env from cwd
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / ".env")
    except Exception:
        pass
    asyncio.run(run_login_server(open_browser=True))


if __name__ == "__main__":
    main()
