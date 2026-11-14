"""Вариативные фразы Home24 v2 — рассылка + диалог с перчинкой, без копипасты."""

from __future__ import annotations

import random
import re
from typing import Any

# заглушки вместо настоящего имени — никогда не вставлять в обращения
_PLACEHOLDER_NAMES = frozenset(
    {
        "клиент",
        "client",
        "гость",
        "guest",
        "user",
        "пользователь",
        "unknown",
        "неизвестно",
        "anna",
        "анна",
        "test",
        "тест",
        "имя",
        "name",
        "null",
        "none",
        "n/a",
        "-",
        "—",
        "–",
    }
)
_PHONE_NAME_RE = re.compile(r"^\+?\d{5,}$")
_DIGITS_HEAVY_RE = re.compile(r"^\d[\d\s\-\(\)]{4,}$")


def is_placeholder_name(name: str | None) -> bool:
    """True если это не настоящее имя (Клиент / Гость / телефон / пусто)."""
    s = (name or "").strip()
    if not s:
        return True
    low = s.lower().strip(" .,:;!?\"'«»")
    if low in _PLACEHOLDER_NAMES:
        return True
    if _PHONE_NAME_RE.match(low.replace(" ", "")) or _DIGITS_HEAVY_RE.match(s):
        return True
    # «Клиент 7900…» / «User_123»
    if low.startswith(("клиент", "client", "user", "guest", "гость")) and (
        len(low) <= 12 or any(ch.isdigit() for ch in low)
    ):
        return True
    return False


def real_first_name(name: str | None) -> str:
    """Первое слово настоящего имени или ''."""
    if is_placeholder_name(name):
        return ""
    s = (name or "").strip()
    s = re.sub(r"^(DEMO\s*[·•\-—]\s*)", "", s, flags=re.I).strip()
    if is_placeholder_name(s):
        return ""
    part = s.split()[0].strip(".,;:") if s else ""
    return "" if is_placeholder_name(part) else part


def already_greeted(sess: dict[str, Any] | None) -> bool:
    """После outreach / любого уже отправленного приветствия бота."""
    if not sess:
        return False
    ctx = sess.get("context")
    if not isinstance(ctx, dict):
        return False
    if ctx.get("greeted") or ctx.get("outreach"):
        return True
    if ctx.get("phr_greet") is not None:
        return True
    return False

# =============================================================================
# РАССЫЛКА (outreach) — тёплый менеджер, «вы», без клише. Ротация.
# {tod} = Доброе утро / Добрый день / Добрый вечер (МСК)
# =============================================================================

def tod_greeting(*, hour: int | None = None) -> str:
    """Приветствие по времени суток (Europe/Moscow по умолчанию)."""
    if hour is None:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            import os

            tz_name = (os.getenv("WORK_TIMEZONE") or "Europe/Moscow").strip()
            try:
                hour = datetime.now(ZoneInfo(tz_name)).hour
            except Exception:
                hour = datetime.now().hour
        except Exception:
            hour = 12
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    return "Добрый вечер"


# Источник всех реплик ниже: script.md (= new-materials/home24-script-user.md).
# Меняете текст гостю — меняйте в script.md и здесь одинаково
# (tests/test_script_sync.py сверяет, что реплики совпадают).
#
# Рассылка: первое письмо бывшему гостю. {stay} пустой или « в сентябре в квартире Твен».
# Каждый вариант заканчивается предложением рассказать. Что рассказать на «да» —
# OUTREACH_OFFER (тот же индекс), см. offer_facts().
GREETINGS: list[list[str]] = [
    [
        "{tod}{name_part}! Это Home24, вы у нас останавливались{stay}. "
        "У нас появилось кое-что новое для гостей, рассказать?",
    ],
    [
        "{tod}{name_part}! Пишу из Home24, вы жили у нас{stay}. "
        "Если снова понадобится квартира, можно бронировать напрямую у меня, так выходит выгоднее. "
        "Рассказать, как это работает?",
    ],
    [
        "{tod}{name_part}! Это Home24) Вы у нас уже бывали{stay}. "
        "Хотела рассказать про новые услуги, можно?",
    ],
    [
        "{tod}{name_part}! Это Home24, вы останавливались у нас{stay}. "
        "Теперь при прямой брони начисляем баллы, 500 сразу за регистрацию. Рассказать подробнее?",
    ],
    [
        "{tod}{name_part}! Это Home24, вы у нас останавливались{stay}. "
        "Теперь у нас можно устроить романтический вечер с кино на проекторе "
        "или отметить праздник в украшенной квартире. Интересно?",
    ],
    [
        "{tod}{name_part}! Это Home24, вы жили у нас{stay}. "
        "Если понадобится квартира на пару дней, для отдыха, родных или на время ремонта, пишите мне. "
        "Может, скоро понадобится?",
    ],
]

# Что предлагали в рассылке (индекс = индекс GREETINGS).
# services / direct / bonus / events — на «да» рассказываем факты, не спрашиваем даты.
# need — вопрос «может, скоро понадобится?», на «да» сразу даты.
OUTREACH_OFFER: list[str] = ["services", "direct", "services", "bonus", "events", "need"]

# Список доп. услуг — сразу гостю, без «откроется за день до заезда».
ADDON_SERVICES_LIST = (
    "1) организация праздников\n"
    "2) оформление романтических вечеров\n"
    "3) только для двоих 🤫\n"
    "4) фотосессии\n"
    "5) другие дополнительные услуги по запросу, если нужно позову коллегу по этим вопросам"
)

ADDON_SERVICES_REPLY = "Дополнительные услуги:\n" + ADDON_SERVICES_LIST

MANAGER_CONNECT_LINE = (
    "Хорошо, скоро к вам подключится менеджер, минут через 10–15."
)


# Факты на согласие «да / ага / ок / расскажите» (только из script.md, без выдумок).
# На явный вопрос «какие доп. услуги?» отвечаем ADDON_SERVICES_REPLY (см. bot/smart.py).
OFFER_FACTS: dict[str, str] = {
    "services": (
        "Можно устроить романтический вечер с кино на проекторе или тихо отметить праздник, "
        "квартиру украсим. А при прямой брони начисляем баллы, 500 за регистрацию)"
    ),
    "direct": (
        "Пишете мне напрямую, без комиссии агрегаторов, так уже выгоднее. "
        "Плюс баллы: 500 за регистрацию и потом с каждого проживания, 1 балл = 1 ₽."
    ),
    "bonus": (
        "Если бронировать напрямую, начисляем баллы: 500 за регистрацию и потом с каждого проживания. "
        "1 балл = 1 ₽. Подробнее тут: https://home24.msk.ru/loyalty"
    ),
    "events": (
        "Романтический вечер с кино на проекторе подготовим, а на праздник можем украсить квартиру. "
        "Шумные вечеринки нельзя, тихо отметить можно)"
    ),
}

# Гость написал первым — короткое приветствие, без сразу дат
INBOUND_HELLO: list[list[str]] = [
    ["Здравствуйте! Чем могу вам помочь?"],
]

# Середина разговора, без повторного представления
HELLO_MID: list[list[str]] = [
    ["Продолжим? Даты уже есть?"],
    ["Даты уже знаете или сначала посмотрим квартиры?"],
    ["С чего начнём, с дат или с района?"],
    ["Подобрать под ваши даты или сначала скинуть пару вариантов?"],
    ["Что уточним дальше, даты или сколько вас?"],
]

HOWAREYOU: list[list[str]] = [
    ["Хорошо, спасибо) Чем помочь?"],
    ["Всё хорошо, спасибо! Квартира нужна?"],
    ["Спасибо, отлично. Вы по квартире?"],
]

THANKS: list[str] = [
    "Если что — пишите, я рядом, помогу)",
    "❤️",
    "Пожалуйста) Если что — пишите, я рядом.",
    "Не за что) Я рядом, помогу.",
]

DATES_OK: list[list[str]] = [
    ["Поняла. Сколько вас будет?"],
    ["Хорошо. А сколько человек?"],
    ["Поняла, а сколько вас будет?"],
    ["Сколько гостей?"],
    ["Сколько вас будет? Если с детьми, тоже напишите."],
]

# После выбора района — спрашиваем даты (воронка: район → даты → гости → календарь)
DISTRICT_OK: list[list[str]] = [
    ["Поняла. На какие даты нужна квартира?"],
    ["Хорошо. На какие даты смотрите?"],
    ["Приняла район. Когда заезд и на сколько ночей?"],
    ["Отлично. Напишите даты, можно примерно."],
]

GUESTS_OK: list[list[str]] = [
    ["Поняла. Сейчас сверю свободные квартиры по календарю."],
    ["Хорошо, смотрю, что свободно под вас."],
]

LOOKING_START: list[str] = [
    "У нас квартиры есть в разных районах — сейчас пришлю список 🙂",
    "Напишу, где есть квартиры, и выберете удобный район.",
    "Сначала район: пришлю, где у нас есть квартиры.",
]


def district_choice_message() -> str:
    """Районы зонами + узнаваемые якоря (метро/места), без имён квартир."""
    return (
        "В центре и ближе к центру, в спокойных районах "
        "(Коммунарка, Прокшино, Очаково) и за городом "
        "(Одинцово, Котельники). Напишите район или метро — подберу."
    )

BROWSING_START: list[list[str]] = [
    ["Поняла) Скинуть пару квартир на будущее?"],
    ["Могу прислать 2–3 варианта просто посмотреть, хотите?"],
    ["Скинуть пару вариантов на потом?"],
    ["Могу заранее показать несколько квартир, чтобы были на примете."],
]

SOFT_CLOSE_LEAD: list[str] = [
    "Хорошо! Надумаете, пишите)",
    "Договорились. Понадобится квартира, пишите.",
    "Хорошо, буду на связи.",
    "Поняла. Захотите посмотреть варианты, напишите.",
]

STOP_ACK: list[str] = [
    "Поняла, больше не пишу. Хорошего дня!",
    "Хорошо, убрала вас из рассылки. Извините за беспокойство.",
    "Поняла, извините. Всего доброго!",
    "Хорошо, не беспокою. Если понадобится квартира, пишите сами.",
]

# Передача коллеге — одно сообщение, ровно как в script.md
HANDOFF_LINE = "Сейчас подключу менеджера, он напишет вам здесь минут через 10–15."
HANDOFF: list[str] = [HANDOFF_LINE]

# После выбора квартиры — уточнить мелкие удобства до передачи менеджеру
COMFORT_EXTRAS_ASK = (
    "Возможно, вам потребуется что-то дополнительное для комфортного проживания? "
    "Например, лёд, чай-кофе побольше, удлинитель/зарядка или что-то другое? "
    "Может, что-то для питомца (если поездка с животным)?"
)

BOOKING_CONFIRM_ASK = (
    "Проверьте, пожалуйста: всё верно? Если да — напишите «да», передам менеджеру."
)

REPORT_DOCS_ASK = "Нужны ли отчётные документы?"

_DEPOSIT_SUMMARY = (
    "Залог 2 000 ₽, возвращается в день выезда после уборки."
)


def _pets_summary_line(sess: dict[str, Any]) -> str:
    """Строка про животных для итога: с доплатой или без животных."""
    from bot.apartments_map import allows_pets, pets_fee_rub

    fav = str(sess.get("favorite") or "").strip()
    ctx = _ctx(sess)
    prefs = str(ctx.get("prefs") or "").lower()
    pets_slot = str(ctx.get("pets") or "").strip()
    wants_pets = bool(
        pets_slot
        or re.search(r"животн|питомц|собак|кошк|кот\b|с\s*животн", prefs)
        or re.search(r"для\s*питомц", prefs)
    )
    if not wants_pets:
        return "Животные: без животных."
    if fav and allows_pets(fav):
        fee = pets_fee_rub(fav)
        if fee:
            fee_s = f"{fee:,}".replace(",", "\u00a0")
            return f"Животные: с животными, доплата {fee_s}\u00a0₽/сутки."
        return "Животные: с животными."
    return "Животные: с животными — по этой квартире доплату уточнит менеджер."


def _extras_summary_line(sess: dict[str, Any]) -> str:
    """Доп. услуги / удобства из prefs после вопроса про комфорт."""
    prefs = str(_ctx(sess).get("prefs") or "")
    bits: list[str] = []
    for part in re.split(r"\s*;\s*", prefs):
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        if "доп. удобства не нужны" in low or "доп удобства не нужны" in low:
            continue
        m = re.match(r"(?i)доп\.\s*для\s*комфорта:\s*(.+)$", p)
        if m:
            bits.append(m.group(1).strip())
            continue
        if re.search(r"(?i)лёд|лед|чай|кофе|удлинител|зарядк|питомц", p) and "животн" not in low:
            bits.append(p)
    if not bits:
        return "Доп. услуги: без доп. услуг."
    return "Доп. услуги: " + "; ".join(bits) + "."


def _docs_summary_line(sess: dict[str, Any]) -> str:
    """Отчётные документы: да или нет."""
    flag = str(_ctx(sess).get("report_docs") or "").strip().lower()
    if flag in ("да", "yes", "true", "1"):
        return "Отчётные документы: да."
    if flag in ("нет", "no", "false", "0"):
        return "Отчётные документы: нет."
    return "Отчётные документы: уточним."


def booking_summary_message(sess: dict[str, Any]) -> str:
    """Итог для сверки с гостем перед передачей менеджеру."""
    dates = str(sess.get("dates") or "—").strip() or "—"
    district = str(sess.get("district") or "—").strip() or "—"
    fav = str(sess.get("favorite") or "").strip()
    flat = f"«{fav}»" if fav else "—"
    guests = str(sess.get("guests") or "").strip()
    lines = [
        "Давайте сверим, всё ли верно:",
        f"• Даты: {dates}",
    ]
    if guests:
        lines.append(f"• Гостей: {guests}")
    lines.extend(
        [
            f"• Район: {district}",
            f"• Квартира: {flat}",
            f"• {_DEPOSIT_SUMMARY}",
            f"• {_pets_summary_line(sess)}",
            f"• {_extras_summary_line(sess)}",
            f"• {_docs_summary_line(sess)}",
            "",
            BOOKING_CONFIRM_ASK,
        ]
    )
    return "\n".join(lines)

# «подумаю / позже» — не стоп-лист, мягко оставить дверь открытой
LATER_LINE = (
    "Хорошо, как надумаете — напишите, подберу квартиру)"
)

# «подумаем / прдумаем / позже» — гости откладывают выбор
_LATER_THINK_RE = re.compile(
    r"(?i)^\s*(здравствуйте[,!\s]*)?(да[,!\s]*)?"
    r"(я\s*)?(по\s*думаю|подумаем|прдумаем|подум\w*|прдум\w*|"
    r"позже\s*напиш\w*|напишу\s*позже|не\s*сейчас|пока\s*не\s*готов\w*)"
    r"[\s!.)…]*$"
)


def is_later_think(text: str) -> bool:
    """«подумаем / прдумаем / позже» — не кидать воронку районов."""
    return bool(_LATER_THINK_RE.match((text or "").strip()))


# глобальная ротация рассылки (чтобы соседние гости не получали один текст)
_GREET_RR: int = -1
_GREET_RECENT: list[int] = []
_GREET_RECENT_MAX = 8


def _ctx(sess: dict[str, Any]) -> dict[str, Any]:
    c = sess.get("context")
    return dict(c) if isinstance(c, dict) else {}


def pick(pool: list[Any], sess: dict[str, Any] | None, key: str) -> Any:
    """Случайный вариант без повтора прошлого для ключа."""
    if not pool:
        raise ValueError("empty pool")
    if len(pool) == 1:
        return pool[0]
    ctx = _ctx(sess) if sess else {}
    last = ctx.get(f"phr_{key}")
    choices = list(range(len(pool)))
    if isinstance(last, int) and 0 <= last < len(pool):
        choices = [i for i in choices if i != last] or choices
    idx = random.choice(choices)
    if sess is not None:
        ctx[f"phr_{key}"] = idx
        sess["context"] = ctx
    return pool[idx]


def pick_greeting_index(*, force_rr: bool = True) -> int:
    """Индекс приветствия для рассылки: round-robin + антиповтор последних N."""
    global _GREET_RR, _GREET_RECENT
    n = len(GREETINGS)
    if n <= 1:
        return 0
    if force_rr:
        _GREET_RR = (_GREET_RR + 1) % n
        # если попали в недавние — сдвиг
        tries = 0
        while _GREET_RR in _GREET_RECENT and tries < n:
            _GREET_RR = (_GREET_RR + 1) % n
            tries += 1
        idx = _GREET_RR
    else:
        banned = set(_GREET_RECENT)
        choices = [i for i in range(n) if i not in banned] or list(range(n))
        idx = random.choice(choices)
    _GREET_RECENT.append(idx)
    if len(_GREET_RECENT) > _GREET_RECENT_MAX:
        _GREET_RECENT = _GREET_RECENT[-_GREET_RECENT_MAX:]
    return idx


def sync_greet_rr(raw: str | int | None) -> None:
    """Подтянуть счётчик из store meta между рестартами."""
    global _GREET_RR
    try:
        _GREET_RR = int(raw) if raw is not None and str(raw).strip() != "" else _GREET_RR
    except Exception:
        pass


def greet_rr_value() -> int:
    return _GREET_RR


def stay_clause(sess: dict[str, Any] | None) -> str:
    """« в сентябре в квартире Твен», если про прошлый заезд известно. Иначе пусто."""
    ctx = _ctx(sess) if sess else {}
    when = str(ctx.get("stay_when") or (sess or {}).get("stay_when") or "").strip()
    place = str(ctx.get("stay_place") or (sess or {}).get("stay_place") or "").strip()
    if when and place:
        return f" в {when} в квартире {place}"
    if place:
        return f" в квартире {place}"
    if when:
        return f" в {when}"
    return ""


def fill(text: str, sess: dict[str, Any], *, site: str = "", channel: str = "", vk: str = "") -> str:
    safe = real_first_name(sess.get("name"))
    name_part = f", {safe}" if safe else ""
    tod = tod_greeting()
    stay = stay_clause(sess)
    # {имя} только если имя настоящее; иначе убираем «Имя, » в начале строки
    out = (
        text.replace("{tod}", tod)
        .replace("{name_part}", name_part)
        .replace("{stay}", stay)
        .replace("{даты}", str(sess.get("dates") or "даты уточним"))
        .replace("{гости}", str(sess.get("guests") or "уточним"))
        .replace("{район}", str(sess.get("district") or "любой"))
        .replace("{site}", site)
        .replace("{channel}", channel)
        .replace("{vk}", vk)
    )
    if safe:
        out = out.replace("{имя}", safe)
    else:
        out = re.sub(r"\{имя\}\s*,\s*", "", out)
        out = out.replace("{имя}", "")
        out = re.sub(r"^,\s*", "", out)
    return out


def _scrub_greeting_name(m: str) -> str:
    """Страховка: заглушки имени не должны проскочить в текст."""
    for bad in ("Клиент,", "Client,", "Гость,", "Guest,", "User,"):
        if m.startswith(bad) or f" {bad}" in f" {m}":
            m = m.replace(f", {bad[:-1]}", "").replace(bad + " ", "")
    if re.match(r"^(гость|клиент|client|guest|user),\s+", m, flags=re.I):
        m = re.sub(r"^(гость|клиент|client|guest|user),\s+", "", m, flags=re.I)
        if not m.lower().startswith(("привет", "здрав", "добр")):
            m = "Здравствуйте! " + m
    # убрать двойные пробелы / «!  » после вырезания имени
    m = re.sub(r"[ \t]{2,}", " ", m).strip()
    m = re.sub(r"!\s*,\s*", "! ", m)
    return m


def sample_outreach_texts(
    *,
    name: str = "Анна",
    limit: int = 0,
    hour: int | None = None,
) -> list[str]:
    """Заполненные примеры рассылки (для превью в панели / проверки тона)."""
    tod = tod_greeting(hour=hour)
    safe = real_first_name(name)
    name_part = f", {safe}" if safe else ""
    out: list[str] = []
    for variant in GREETINGS:
        msgs = [
            _scrub_greeting_name(
                p.replace("{tod}", tod)
                .replace("{name_part}", name_part)
                .replace("{stay}", "")
            )
            for p in variant
        ]
        text = "\n".join(msgs).strip()
        if text:
            out.append(text)
        if limit and len(out) >= limit:
            break
    return out


def greeting_msgs(
    sess: dict[str, Any], *, outreach: bool = False
) -> tuple[list[str], dict[str, Any]]:
    """Приветствие. outreach=True — рассылка; иначе — тёплое входящее."""
    ctx = _ctx(sess)
    if outreach:
        idx = pick_greeting_index(force_rr=True)
        variant = GREETINGS[idx]
        ctx["phr_greet"] = idx
        ctx["outreach"] = True
        ctx["perk"] = "visit"
        topic = OUTREACH_OFFER[idx] if 0 <= idx < len(OUTREACH_OFFER) else ""
        ctx["offer"] = topic
        ctx["offer_open"] = bool(topic)
    else:
        variant = pick(INBOUND_HELLO, sess, "inbound")
    ctx["greeted"] = True
    sess["context"] = ctx
    msgs = [_scrub_greeting_name(fill(p, sess)) for p in variant]
    upd: dict[str, Any] = {"step": "await_intent", "context": ctx}
    if outreach:
        # рассылка идёт только бывшим гостям — «вы у нас уже были?» не спрашиваем
        upd["returning"] = "да"
    return msgs, upd


def soft_close_msgs(sess: dict[str, Any], *, site: str, channel: str, vk: str) -> list[str]:
    lead = fill(pick(SOFT_CLOSE_LEAD, sess, "close"), sess)
    bye = real_first_name(sess.get("name"))
    links = (
        f"Сайт: {site}\n"
        f"Канал: {channel}\n"
        f"VK: {vk}\n\n"
        + (f"Хорошего дня, {bye}!" if bye else "Хорошего дня!")
    )
    return [lead, links]


# —— «Да» на предложение из рассылки (дополнение к промпту, new-materials/home24_prompt_addon_services_da.md)

_CONSENT_RE = re.compile(
    r"(?i)^\s*(да+|ага|угу|ок|окей|ok|okay|давай(те)?|интересно|можно|конечно|"
    r"расскаж(и|ите)|рассказывайте|хочу|было бы интересно|да,?\s*(расскаж\w*|интересно|давайте|можно|конечно))"
    r"[\s!.)\]🙂]*$"
)
_OFFER_REFUSAL_RE = re.compile(
    r"(?i)^\s*(нет|не|неа|не надо|не нужно|не интересно|неинтересно|нет,?\s*спасибо|не,?\s*спасибо)[\s!.)]*$"
)
_OFFER_UNSURE_RE = re.compile(r"(?i)^\s*(не знаю|хз|\?+|а что именно\??|что за\s*\w*\??)\s*$")


_OFFER_ASK_RE = re.compile(
    r"(?i)(?:рассказать(?:\s+подробнее)?|интересно|можно|хотите(?:,?\s*подбер\w*)?|"
    r"подберу\s+квартир\w*|за\s+город|спокойн\w*\s+район)\s*[?)]*\s*$"
)
# После фактов про баллы/услуги — сразу выбор района/квартир, не пауза «напишите потом».
OFFER_PICK_ASK = (
    "Хотите, подберу квартиру? "
    "Вам ближе центр, спокойный район или за город?"
)
_OFFER_PICK_ASK_RE = re.compile(
    r"(?i)хотите,?\s*подбер|подберу\s+квартир\w*\s*\?|"
    r"ближе\s+центр|спокойн\w*\s+район|за\s+город"
)


def offer_topic_in(text: str | None) -> str:
    """Тема предложения, если реплика бота заканчивается «Рассказать? / Интересно?»."""
    t = (text or "").strip()
    if not t or not _OFFER_ASK_RE.search(t):
        return ""
    low = t.lower()
    # «…одну дополнительную услугу … бесплатно. Интересно?» — это сценарий perk, не рассылка
    if re.search(r"дополнительн\w*\s+услуг|достанется\s+бесплатно|услуг\w*\s+бесплатн", low):
        return ""
    if re.search(r"романт|кино|проектор|праздн|украс|отметить", low):
        return "events"
    if re.search(r"балл|бонус|лояльн", low):
        return "bonus"
    if re.search(r"напрямую|прямой\s+брон", low):
        return "direct"
    if re.search(r"услуг|нового|новое", low):
        return "services"
    return ""


def outreach_offer(sess: dict[str, Any] | None, last_bot: str | None = None) -> str:
    """Тема открытого предложения ('' если не предлагали или уже ответили).

    Берётся из рассылки (context.offer) или из последней реплики бота «…Рассказать?».
    """
    ctx = _ctx(sess) if sess else {}
    if ctx.get("offer_open"):
        # предложение из рассылки открыто, только пока последним было само письмо рассылки:
        # после «С 20 по 24 декабря, двое…» «да» — ответ на новый вопрос, не на рассылку (скрин 66)
        lb = (last_bot or "").lower()
        if last_bot is None or not lb or re.search(r"home24|рассказать|интересно|можно\?|понадобится\?", lb):
            return str(ctx.get("offer") or "")
        return offer_topic_in(last_bot)
    return offer_topic_in(last_bot)


def offer_facts(topic: str) -> str:
    return OFFER_FACTS.get(topic or "", "")


_GREETING_PREFIX_RE = re.compile(
    r"(?i)^\s*(здравствуйте|здрасьте|добрый\s+(день|вечер)|доброе\s+утро|привет\w*|приветствую)[\s!.,)]*"
)


def _strip_greeting(text: str) -> str:
    """«Здравствуйте! Да, расскажите» → «Да, расскажите»."""
    return _GREETING_PREFIX_RE.sub("", text or "").strip()


def is_consent(text: str) -> bool:
    return bool(_CONSENT_RE.match(_strip_greeting(text)))


def is_offer_refusal(text: str) -> bool:
    return bool(_OFFER_REFUSAL_RE.match(_strip_greeting(text)))


def is_offer_unsure(text: str) -> bool:
    return bool(_OFFER_UNSURE_RE.match(text or ""))


def hello_mid_msgs(sess: dict[str, Any]) -> list[str]:
    return [fill(p, sess) for p in pick(HELLO_MID, sess, "hello")]


def inbound_hello_msgs(sess: dict[str, Any]) -> list[str]:
    """Тёплое первое «здравствуйте», когда гость сам написал."""
    return [fill(p, sess) for p in pick(INBOUND_HELLO, sess, "inbound")]


def howareyou_msgs(sess: dict[str, Any]) -> list[str]:
    return [fill(p, sess) for p in pick(HOWAREYOU, sess, "howareyou")]


def client_report(sess: dict[str, Any], *, guest_text: str = "") -> str:
    """Отчёт менеджеру: слоты + предпочтения + бюджет/возражения."""
    ctx = _ctx(sess)
    notes = str(ctx.get("notes") or "").strip()
    prefs = str(ctx.get("prefs") or "").strip()
    budget = str(ctx.get("budget") or "").strip()
    objection = str(ctx.get("objection") or "").strip()
    lines = [
        "📋 Заявка Home24",
        f"Гость: {sess.get('name') or '—'} · chat={sess.get('chat_id') or '—'}",
        f"Даты: {sess.get('dates') or '—'}",
        f"Гости: {sess.get('guests') or '—'}",
        f"Район: {sess.get('district') or '—'}",
        f"Были раньше: {sess.get('returning') or '—'}",
        f"Любимая кв.: {sess.get('favorite') or '—'}",
    ]
    if budget:
        lines.append(f"Бюджет: {budget}")
    if prefs:
        lines.append(f"Предпочтения: {prefs}")
    if objection:
        lines.append(f"Возражения: {objection}")
    if notes:
        lines.append(f"Пожелания: {notes}")
    offers = ctx.get("offers") or []
    if offers:
        lines.append("Показывали: " + ", ".join(f"«{x}»" for x in offers[:5]))
    if guest_text:
        lines.append(f"Последнее сообщение: {guest_text[:240]}")
    return "\n".join(lines)


def offer_reply(
    sess: dict[str, Any],
    text: str,
    *,
    services_question: bool = False,
    last_bot: str | None = None,
) -> tuple[list[str], dict[str, Any], str] | None:
    """Ответ на открытое предложение из рассылки.

    Возвращает (messages, context, next_step) или None, если реплика не про предложение.
    «да / ага / ок / расскажите / ?» → факты по теме, без вопроса про даты.
    «нет / не надо» → мягко закрыть, без обиды и без заявки.
    Тема «need» («может, скоро понадобится?») + «да» → сразу спросить даты.
    """
    topic = outreach_offer(sess, last_bot)
    if not topic:
        return None
    ctx = _ctx(sess)
    raw = (text or "").strip()
    wants_flats = bool(
        re.search(r"(?i)(пришлите|покажите|скиньте|подберите|отправьте|киньте)\b.{0,25}вариант|"
                  r"какие\s+есть\s+вариант|^\W*(?:здравствуйте\W+)?(?:да\W+)?вариант", raw)
    )
    if wants_flats and not services_question:
        # «Да, пришлите варианты» — гость хочет квартиру, а не рассказ о предложении (скрин 66)
        ctx["offer_open"] = False
        ctx["perk"] = ""
        sess["context"] = ctx
        return [district_choice_message()], _ctx(sess), "await_district"
    if is_consent(raw) or is_offer_unsure(raw) or services_question:
        ctx["offer_open"] = False
        # «Да» на «Хотите, подберу квартиру?» → воронка, а не повтор фактов
        if _OFFER_PICK_ASK_RE.search(last_bot or "") and not services_question:
            ctx["perk"] = ""
            ctx.pop("offer_told", None)
            sess["context"] = ctx
            return [district_choice_message()], _ctx(sess), "await_district"
        if topic == "need" and not services_question:
            ctx["perk"] = ""  # обычная воронка: район → даты → гости → календарь
            sess["context"] = ctx
            ask = district_choice_message()
            if re.search(r"(?i)вариант|подбер|пришлите|покажите|скиньте", raw):
                ask = "С удовольствием подберу)\n\n" + district_choice_message()
            return [ask], _ctx(sess), "await_district"
        line = offer_facts("services" if (services_question and topic == "need") else topic)
        if line and not services_question:
            # сразу выбор квартир/района — не ждать второго «да» и не закрывать «Будем ждать!»
            sep = "\n\n" if re.search(r"https?://\S+$", line.rstrip()) else " "
            line = line.rstrip() + sep + OFFER_PICK_ASK
        ctx["perk"] = "orient"
        ctx["offer_told"] = topic
        ctx["offer_pick_ask"] = True
        return [line], ctx, "await_district"
    if is_later_think(raw) or is_offer_refusal(raw):
        ctx["offer_open"] = False
        ctx["perk"] = ""
        sess["context"] = ctx
        if is_later_think(raw):
            return [LATER_LINE], _ctx(sess), "done"
        return [pick(SOFT_CLOSE_LEAD, sess, "close")], _ctx(sess), "done"
    return None
