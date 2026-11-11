"""
Home24 manager bot for Telegram.

Менеджер выбирает квартиру — бот присылает ссылку на HTML-инструкцию.
Гость открывает сайт в браузере, Telegram ему не обязателен.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import socket
import hmac
import hashlib
import time
from pathlib import Path

# Many RU VPS resolve api.telegram.org to broken IPv6 and hang.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_first_getaddrinfo

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut
from telegram.request import HTTPXRequest

from admin_store import add_support_agent_reply, delete_library_video, patch_overlay, read_store, save_library_video
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "data" / "apartments.json").read_text(encoding="utf-8"))
APTS: list[dict] = CATALOG["apartments"]
BY_SLUG = {a["slug"]: a for a in APTS}
PHONE = CATALOG.get("phone", "+7 977 717-60-97")
BOT_USERNAME = (os.environ.get("TELEGRAM_BOT_USERNAME") or "GostSill_bot").lstrip("@")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("home24")

PAGE = 8
ADMIN_IDS = {
    int(x)
    for x in (os.environ.get("ADMIN_TELEGRAM_IDS") or "2032620613,8228063846").replace(" ", ",").split(",")
    if x.strip().isdigit()
}


def is_admin(user_id: int | None) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


def admin_secret() -> str:
    return os.environ.get("ADMIN_SECRET") or os.environ.get("TELEGRAM_BOT_TOKEN") or "home24-admin-dev"


def mint_admin_token(user_id: int, days: int = 14) -> str:
    exp = int(time.time()) + days * 86400
    payload = f"{user_id}.{exp}"
    sig = hmac.new(admin_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


OLD_ORIGIN = "https://89-111-184-212.sslip.io"


def public_base() -> str:
    env = (os.environ.get("PUBLIC_URL") or "").strip().rstrip("/")
    return env or OLD_ORIGIN


def manager_site() -> str:
    return public_base() + "/"


def site_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Открыть меню менеджера", url=manager_site())],
            [InlineKeyboardButton("К списку квартир в боте", callback_data="page:0:")],
        ]
    )


def site_html() -> str:
    url = manager_site()
    return (
        "<b>Home24 · меню менеджера</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Не все заходят в Telegram — ссылки можно брать с сайта.\n"
        "Нажали слоган квартиры — гостевая ссылка сразу в буфере. Отправьте её клиенту.\n\n"
        f'<a href="{url}">{url}</a>\n\n'
        "<i>Гость открывает инструкцию в браузере. Бот ему не нужен.</i>"
    )


def guest_url(a: dict) -> str:
    return f"{public_base()}/g/{a['slug']}"


def checkin_hour(a: dict) -> str:
    blob = a.get("checkin") or a.get("guestMessage") or ""
    m = re.search(r"Заезд с (\d{1,2}:\d{2})", blob)
    return m.group(1) if m else "14:00"


def guest_plain(a: dict) -> str:
    stored = (a.get("guestMessage") or "").strip()
    for old in (
        "https://62-109-2-78.sslip.io",
        "https://193-227-241-112.sslip.io",
    ):
        stored = stored.replace(old, public_base())
    if stored:
        return stored
    url = guest_url(a)
    park = (a.get("parkingHint") or "").strip()
    park_line = f"\n{park}" if park else ""
    return (
        f"Здравствуйте! Квартира «{a['name']}».\n"
        f"\n"
        f"Инструкция: {url}\n"
        f"\n"
        f"Адрес: {a['address']}\n"
        f"Заезд с {checkin_hour(a)}, выезд до 12:00.{park_line}\n"
        f"\n"
        f"Менеджер: {PHONE}"
    )


def _fold(s: str) -> str:
    t = (s or "").lower().replace("ё", "е").replace("э", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", t)


def find_apts(query: str) -> list[dict]:
    q = _fold(query)
    if not q:
        return APTS
    out = []
    for a in APTS:
        blob = _fold(" ".join(str(a.get(k) or "") for k in ("name", "slug", "area", "address", "metro", "id")))
        if q in blob:
            out.append(a)
    return out


def list_keyboard(items: list[dict], page: int = 0, query: str = "") -> InlineKeyboardMarkup:
    start = page * PAGE
    chunk = items[start : start + PAGE]
    rows = [
        [InlineKeyboardButton(f"{a['id']}. {a['name']}", callback_data=f"apt:{a['slug']}")]
        for a in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("‹ Назад", callback_data=f"page:{page-1}:{query[:40]}"))
    if start + PAGE < len(items):
        nav.append(InlineKeyboardButton("Вперёд ›", callback_data=f"page:{page+1}:{query[:40]}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔎 Поиск по слогану", callback_data="search")])
    rows.append([InlineKeyboardButton("Сайт менеджера", url=manager_site())])
    return InlineKeyboardMarkup(rows)


def apt_keyboard(a: dict) -> InlineKeyboardMarkup:
    url = guest_url(a)
    rows = [
        [InlineKeyboardButton("Открыть инструкцию", url=url)],
        [
            InlineKeyboardButton("Текст гостю ещё раз", callback_data=f"copy:{a['slug']}"),
            InlineKeyboardButton("FAQ", callback_data=f"faq:{a['slug']}"),
        ],
        [InlineKeyboardButton("« К списку квартир", callback_data="page:0:")],
    ]
    return InlineKeyboardMarkup(rows)


def guest_html(a: dict) -> str:
    url = guest_url(a)
    return (
        f"«{a['name']}»\n"
        f'<a href="{url}">{url}</a>\n\n'
        "Ниже текст, который можно сразу отправить гостю."
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    payload = (context.args or [""])[0]
    if payload and payload in BY_SLUG:
        await send_apartment(update, BY_SLUG[payload])
        return
    url = manager_site()
    await update.message.reply_text(
        "<b>Home24</b> — инструкции для гостей\n\n"
        "Выберите квартиру здесь или откройте сайт менеджера, если удобнее браузер.\n"
        f'<a href="{url}">{url}</a>\n'
        f'Бот: <a href="https://t.me/{BOT_USERNAME}">@{BOT_USERNAME}</a>\n\n'
        f"В каталоге {len(APTS)} объектов. Напишите слоган или листайте список.",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=False,
        reply_markup=list_keyboard(APTS, 0),
    )


async def cmd_site(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text(
        site_html(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=False,
        reply_markup=site_keyboard(),
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    await update.message.reply_text(
        f"Квартиры ({len(APTS)}). Нажмите нужную:",
        reply_markup=list_keyboard(APTS, 0),
    )


EDIT_FIELDS = [
    ("name", "Слоган"),
    ("address", "Адрес"),
    ("metro", "Метро"),
    ("wifi", "Wi‑Fi"),
    ("how", "Как добраться"),
    ("checkin", "Заселение"),
    ("checkout", "Выезд"),
    ("parking", "Парковка"),
    ("rules", "Правила"),
    ("district", "Район"),
    ("contacts", "Контакты"),
]
FIELD_TITLE = dict(EDIT_FIELDS)


def admin_site_url(user_id: int) -> str:
    return f"{public_base()}/admin?k={mint_admin_token(user_id)}"


def admin_home_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Открыть админку на сайте", url=admin_site_url(user_id))],
            [InlineKeyboardButton("Видео на все квартиры", callback_data="ad:vall")],
            [InlineKeyboardButton("Видео на выбранные", callback_data="ad:vsel")],
            [InlineKeyboardButton("Править тексты квартир", callback_data="ad:edit:0")],
            [InlineKeyboardButton("Библиотека роликов", callback_data="ad:lib:0")],
            [InlineKeyboardButton("Отмена", callback_data="ad:x")],
        ]
    )


def admin_home_html(user_id: int) -> str:
    url = admin_site_url(user_id)
    return (
        "<b>Админка Home24</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "То же, что на сайте: видео на все или выбранные квартиры, правка карточек, библиотека.\n\n"
        f'Сайт (логин/пароль или эта ссылка): <a href="{url}">{public_base()}/admin</a>\n\n'
        "В Telegram файл до ~20 МБ. Более тяжёлые ролики — через сайт."
    )


def pick_keyboard(picked: set[str], page: int = 0) -> InlineKeyboardMarkup:
    start = page * PAGE
    chunk = APTS[start : start + PAGE]
    rows = []
    for a in chunk:
        mark = "✓ " if a["slug"] in picked else ""
        rows.append(
            [InlineKeyboardButton(f"{mark}{a['id']}. {a['name']}", callback_data=f"ad:t:{page}:{a['slug']}")]
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("‹ Назад", callback_data=f"ad:vsel:{page-1}"))
    if start + PAGE < len(APTS):
        nav.append(InlineKeyboardButton("Вперёд ›", callback_data=f"ad:vsel:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(f"Готово, жду видео ({len(picked)})", callback_data="ad:vgo")])
    rows.append([InlineKeyboardButton("« В админку", callback_data="ad:home")])
    return InlineKeyboardMarkup(rows)


def edit_list_kb(page: int = 0) -> InlineKeyboardMarkup:
    start = page * PAGE
    chunk = APTS[start : start + PAGE]
    rows = [[InlineKeyboardButton(f"{a['id']}. {a['name']}", callback_data=f"ad:es:{a['slug']}")] for a in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("‹ Назад", callback_data=f"ad:edit:{page-1}"))
    if start + PAGE < len(APTS):
        nav.append(InlineKeyboardButton("Вперёд ›", callback_data=f"ad:edit:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("« В админку", callback_data="ad:home")])
    return InlineKeyboardMarkup(rows)


def field_kb(slug: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(title, callback_data=f"ad:f:{slug}:{key}")]
        for key, title in EDIT_FIELDS
    ]
    rows.append([InlineKeyboardButton("« К списку квартир", callback_data="ad:edit:0")])
    return InlineKeyboardMarkup(rows)


def library_kb(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    videos = read_store().get("videos") or []
    if not videos:
        return (
            "Библиотека пустая. Залейте ролик через кнопки выше или с сайта.",
            InlineKeyboardMarkup([[InlineKeyboardButton("« В админку", callback_data="ad:home")]]),
        )
    start = page * 6
    chunk = videos[start : start + 6]
    lines = ["<b>Библиотека роликов</b>\n"]
    rows = []
    for v in chunk:
        where = "все" if v.get("slugs") == "all" else f"{len(v.get('slugs') or [])} кв."
        title = (v.get("title") or "без названия")[:40]
        lines.append(f"• {title} · {where}")
        rows.append([InlineKeyboardButton(f"Удалить «{title[:28]}»", callback_data=f"ad:d:{v['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("‹ Назад", callback_data=f"ad:lib:{page-1}"))
    if start + 6 < len(videos):
        nav.append(InlineKeyboardButton("Вперёд ›", callback_data=f"ad:lib:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("« В админку", callback_data="ad:home")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def clear_admin_wait(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("admin_wait", None)
    context.user_data.pop("admin_picked", None)


async def show_admin_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user
    text = admin_home_html(user.id)
    markup = admin_home_kb(user.id)
    q = update.callback_query
    if q and q.message:
        try:
            await q.message.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=markup)
            return
        except BadRequest:
            pass
    msg = update.effective_message
    assert msg
    await msg.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=markup)


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message and update.effective_user
    if not is_admin(update.effective_user.id):
        return
    clear_admin_wait(context)
    await show_admin_home(update, context)


async def on_support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = update.effective_user
    assert q and q.data and user
    await q.answer()
    if not is_admin(user.id):
        return
    tid = q.data.split(":", 1)[-1]
    context.user_data["admin_wait"] = {"kind": "support", "thread": tid}
    if q.message:
        await q.message.reply_text("Напишите ответ одним сообщением — уйдёт гостю как обычный текст.")


async def on_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = update.effective_user
    assert q and q.data and user
    if not is_admin(user.id):
        await q.answer()
        return
    data = q.data
    await q.answer()
    parts = data.split(":")

    if data in {"ad:home", "ad:x"}:
        clear_admin_wait(context)
        await show_admin_home(update, context)
        return

    if data == "ad:vall":
        context.user_data["admin_wait"] = {"kind": "video", "slugs": "all"}
        await q.message.reply_text(
            "Пришлите видео следующим сообщением. Подпись станет названием для гостя.\n"
            "Поставлю на все квартиры, где такого ролика ещё нет (до ~20 МБ)."
        )
        return

    if parts[0] == "ad" and parts[1] == "vsel":
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        picked = set(context.user_data.get("admin_picked") or [])
        await q.message.edit_text(
            "Отметьте квартиры, затем «Готово, жду видео».",
            reply_markup=pick_keyboard(picked, page),
        )
        return

    if parts[0] == "ad" and parts[1] == "t" and len(parts) >= 4:
        page = int(parts[2])
        slug = parts[3]
        picked = set(context.user_data.get("admin_picked") or [])
        if slug in picked:
            picked.remove(slug)
        else:
            picked.add(slug)
        context.user_data["admin_picked"] = list(picked)
        await q.message.edit_reply_markup(reply_markup=pick_keyboard(picked, page))
        return

    if data == "ad:vgo":
        picked = list(context.user_data.get("admin_picked") or [])
        if not picked:
            await q.message.reply_text("Ничего не отмечено — выберите квартиры.")
            return
        context.user_data["admin_wait"] = {"kind": "video", "slugs": picked}
        await q.message.reply_text(
            f"Жду видео на {len(picked)} квартир. Подпись = название. До ~20 МБ."
        )
        return

    if parts[0] == "ad" and parts[1] == "edit":
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await q.message.edit_text("Какую квартиру править?", reply_markup=edit_list_kb(page))
        return

    if parts[0] == "ad" and parts[1] == "es" and len(parts) >= 3:
        slug = parts[2]
        a = BY_SLUG.get(slug)
        if not a:
            return
        await q.message.edit_text(
            f"«{a['name']}» — что меняем?",
            reply_markup=field_kb(slug),
        )
        return

    if parts[0] == "ad" and parts[1] == "f" and len(parts) >= 4:
        slug, field = parts[2], parts[3]
        if field not in FIELD_TITLE:
            return
        context.user_data["admin_wait"] = {"kind": "text", "slug": slug, "field": field}
        name = BY_SLUG.get(slug, {}).get("name", slug)
        await q.message.reply_text(
            f"Напишите новый текст для «{name}» → {FIELD_TITLE[field]}.\n"
            "Следующее сообщение целиком станет значением."
        )
        return

    if parts[0] == "ad" and parts[1] == "lib":
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        text, markup = library_kb(page)
        try:
            await q.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except BadRequest:
            await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    if parts[0] == "ad" and parts[1] == "d" and len(parts) >= 3:
        vid = parts[2]
        ok = delete_library_video(vid)
        text, markup = library_kb(0)
        note = "Удалил ролик из инструкций." if ok else "Уже нет такого ролика."
        await q.message.edit_text(f"{note}\n\n{text}", parse_mode=ParseMode.HTML, reply_markup=markup)
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message and update.message.text
    q = update.message.text.strip()
    if q.startswith("/"):
        return
    user = update.effective_user
    wait = context.user_data.get("admin_wait") if user and is_admin(user.id) else None
    if wait and wait.get("kind") == "support":
        tid = wait.get("thread") or ""
        if add_support_agent_reply(tid, q):
            clear_admin_wait(context)
            await update.message.reply_text("Отправил.")
        else:
            await update.message.reply_text("Чат не найден. Откройте сообщение поддержки ещё раз.")
        return
    if wait and wait.get("kind") == "text":
        slug, field = wait["slug"], wait["field"]
        patch_overlay(slug, field, q)
        clear_admin_wait(context)
        name = BY_SLUG.get(slug, {}).get("name", slug)
        await update.message.reply_text(
            f"Сохранил {FIELD_TITLE.get(field, field)} для «{name}». Гость увидит сразу.",
            reply_markup=admin_home_kb(user.id),
        )
        return
    if wait and wait.get("kind") == "video":
        await update.message.reply_text(
            "Сейчас жду видео, не текст. Пришлите ролик или нажмите «Отмена» в /admin."
        )
        return
    if q.lower() in {"сайт", "site", "меню", "menu", "web"}:
        await update.message.reply_text(
            site_html(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
            reply_markup=site_keyboard(),
        )
        return
    found = find_apts(q)
    if len(found) == 1:
        await send_apartment(update, found[0])
        return
    if not found:
        await update.message.reply_text(
            "Ничего не нашёл. Попробуйте «феррари», «матисс», «чаплин» или номер из списка.",
            reply_markup=list_keyboard(APTS, 0),
        )
        return
    await update.message.reply_text(
        f"Нашёл {len(found)} квартир по запросу «{q}»:",
        reply_markup=list_keyboard(found, 0, q),
    )


async def send_apartment(update: Update, a: dict, *, edit: bool = False) -> None:
    text = guest_html(a)
    markup = apt_keyboard(a)
    if edit and update.callback_query and update.callback_query.message:
        try:
            await update.callback_query.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
                reply_markup=markup,
            )
        except BadRequest:
            pass
        await update.callback_query.message.reply_text(guest_plain(a))
        return
    msg = update.effective_message
    assert msg
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await msg.reply_text(guest_plain(a))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    assert q and q.data
    if q.data.startswith("ad:"):
        await on_admin_callback(update, context)
        return
    await q.answer()
    data = q.data
    if data == "site":
        await q.message.reply_text(
            site_html(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
            reply_markup=site_keyboard(),
        )
        return
    if data == "search":
        await q.message.reply_text("Напишите слоган квартиры текстом — например: феррари")
        return
    if data.startswith("page:"):
        _, page_s, query = data.split(":", 2)
        items = find_apts(query)
        await q.message.edit_text(
            f"Квартиры ({len(items)}). Нажмите нужную:",
            reply_markup=list_keyboard(items, int(page_s), query),
        )
        return
    if data.startswith("apt:"):
        slug = data.split(":", 1)[1]
        await send_apartment(update, BY_SLUG[slug], edit=True)
        return
    if data.startswith("copy:"):
        slug = data.split(":", 1)[1]
        await q.message.reply_text(guest_plain(BY_SLUG[slug]))
        return
    if data.startswith("faq:"):
        slug = data.split(":", 1)[1]
        a = BY_SLUG[slug]
        url = guest_url(a)
        await q.message.reply_text(f"FAQ квартиры «{a['name']}»:\n{url}/faq")


async def on_shared_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not is_admin(user.id if user else None):
        return
    media = msg.video or msg.document
    if not media:
        return
    wait = context.user_data.get("admin_wait") or {}
    name = (getattr(media, "file_name", None) or "") + " " + (msg.caption or "")
    blob = name.lower().replace("ё", "е")
    coffee = any(k in blob for k in ("кофемаш", "кофевар", "кофемашин", "coffee"))
    if wait.get("kind") != "video" and not coffee:
        await msg.reply_text("Чтобы поставить ролик, откройте /admin и выберите «на все» или «на выбранные». Либо сайт.")
        return
    size = getattr(media, "file_size", None) or 0
    if size > 19_500_000:
        await msg.reply_text(
            "Telegram через бота не отдаёт файлы тяжелее ~20 МБ. Залейте этот ролик в админке на сайте: "
            f"{admin_site_url(user.id)}"
        )
        return
    dest_dir = Path(os.environ.get("SHARED_DIR") or "/opt/home24/shared")
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = getattr(media, "file_name", None) or ""
    low = fname.lower()
    ext = ".mp4"
    if low.endswith(".mov"):
        ext = ".mov"
    elif low.endswith(".m4v"):
        ext = ".m4v"
    elif low.endswith(".webm"):
        ext = ".webm"
    tmp = dest_dir / f"tg-upload{ext}"
    tg_file = await media.get_file()
    await tg_file.download_to_drive(custom_path=str(tmp))
    title = (msg.caption or "").strip() or ("Как пользоваться кофемашиной" if coffee else "Видео-инструкция")
    slugs = wait.get("slugs", "all") if wait.get("kind") == "video" else "all"
    item = save_library_video(title=title, src=tmp, slugs=slugs, skip_if_has=True)
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    clear_admin_wait(context)
    where = "все квартиры" if slugs == "all" else f"{len(slugs)} квартир"
    log.info("Admin video %s → %s", item.get("id"), where)
    await msg.reply_text(
        f"Поставил «{title}» на {where}, без дублей где ролик уже был.\n{public_base()}/g/ferrari/video",
        reply_markup=admin_home_kb(user.id),
    )


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN в .env")
    log.info("Guest site %s", public_base())
    # Pool size 1 (PTB default) lets long-poll occupy the only socket; replies then TimedOut.
    http = dict(
        connection_pool_size=16,
        connect_timeout=30.0,
        read_timeout=120.0,
        write_timeout=120.0,
        pool_timeout=30.0,
        http_version="1.1",
    )

    async def _post_init(application: Application) -> None:
        me = await application.bot.get_me()
        log.info("Telegram bot @%s (want @%s)", me.username or "?", BOT_USERNAME)
        public_cmds = [
            BotCommand("start", "Выбрать квартиру"),
            BotCommand("site", "Сайт менеджера — ссылки без Telegram"),
            BotCommand("list", "Список квартир"),
        ]
        await application.bot.set_my_commands(public_cmds, scope=BotCommandScopeDefault())
        admin_cmds = public_cmds + [BotCommand("admin", "Админка: видео и тексты")]
        for uid in ADMIN_IDS:
            try:
                await application.bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=uid))
            except (BadRequest, Forbidden) as exc:
                log.warning("Could not set admin commands for %s: %s", uid, exc)

    app = (
        Application.builder()
        .token(token)
        .request(HTTPXRequest(**http))
        .get_updates_request(HTTPXRequest(**http))
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler(["site", "menu", "web"], cmd_site))
    app.add_handler(CallbackQueryHandler(on_support_callback, pattern=r"^sup:"))
    app.add_handler(CallbackQueryHandler(on_admin_callback, pattern=r"^ad:"))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, on_shared_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        err = context.error
        if isinstance(err, (TimedOut, NetworkError)):
            log.warning("Telegram network: %s", err)
            return
        log.exception("Bot handler failed: %s", err)

    app.add_error_handler(on_error)
    log.info("Home24 Telegram bot polling, %s apartments", len(APTS))
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, timeout=30)


if __name__ == "__main__":
    main()
