# -*- coding: utf-8 -*-
"""Один ответ на пачку: без второго пересказа, чужого района и тех же карточек."""

from __future__ import annotations

import re
from typing import Any

_FILLER = {
    "поняла",
    "хорошо",
    "вижу",
    "приняла",
    "ясно",
    "ок",
    "подберу",
    "сейчас",
    "варианты",
    "вариант",
}

_DEFER_RE = re.compile(
    r"(?i)("
    r"сами\s*(уже\s*)?(район\s*)?(выбер|выбир)|"
    r"выбер(ите|и|ешь)\s*(район|вы|сами)|"
    r"на\s*ваш\s*выбор|"
    r"район\s*(не\s*важен|любой|на\s*вас)|"
    r"вам\s*виднее|"
    r"как\s*(вам|тебе)\s*удобн|"
    r"любой\s*район|"
    r"не\s*принцип|"
    r"без\s*разницы|"
    r"не\s*важно"
    r")"
)

_OPEN_LABELS = {
    "не принципиально",
    "любой",
    "любая",
    "любой район",
    "без разницы",
    "не важно",
    "на ваш выбор",
    "район на ваш выбор",
}


def guest_defers_district(text: str | None) -> bool:
    return bool(_DEFER_RE.search(text or ""))


def is_open_district(district: str | None) -> bool:
    d = (district or "").strip().lower()
    return d in _OPEN_LABELS or guest_defers_district(d)


def guest_district_phrase(district: str | None) -> str:
    """Как сказать район гостю. Служебное «не принципиально» вслух не произносим."""
    raw = (district or "").strip()
    if not raw:
        return ""
    if is_open_district(raw):
        return "район на ваш выбор"
    return raw


def _norm(text: str) -> str:
    s = (text or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in _norm(text).split() if len(t) > 2]


def _mentioned(label: str, guest_text: str) -> bool:
    lab = (label or "").strip().lower().replace("ё", "е")
    guest = (guest_text or "").lower().replace("ё", "е")
    if not lab or not guest:
        return False
    if lab in guest:
        return True
    stem = re.sub(r"[^a-zа-я0-9]+", "", lab)[:8]
    compact = re.sub(r"[^a-zа-я0-9]+", "", guest)
    return len(stem) >= 4 and stem in compact


def resolve_guest_district(
    guest_text: str,
    llm_raw: Any,
    session_district: Any,
) -> str | None:
    """Район только из слов гостя. Модель не подставляет Коммунарку сама."""
    from bot.catalog import match_catalog_place
    from bot.engine import parse_district
    from bot.smart import _normalize_district_label

    named = match_catalog_place(guest_text)
    if named:
        return named
    parsed = parse_district(guest_text)
    if parsed:
        return _normalize_district_label(parsed) or parsed

    llm = str(llm_raw or "").strip()
    if llm and llm.lower() not in ("null", "none", ""):
        if guest_defers_district(llm):
            llm_choice = None
        else:
            llm_named = match_catalog_place(llm)
            llm_parsed = parse_district(llm)
            llm_norm = _normalize_district_label(llm_parsed or llm)
            llm_choice = llm_named or llm_norm
        if llm_choice and _mentioned(str(llm_choice), guest_text):
            return _normalize_district_label(str(llm_choice)) or str(llm_choice)

    if session_district:
        kept = _normalize_district_label(str(session_district)) or str(session_district)
        return kept[:40]
    return None


def sentence_repeats(sentence: str, previous: str) -> bool:
    """Фраза уже была в прошлом ответе — в том числе «завтра на троих»."""
    sent = (sentence or "").strip()
    prev = previous or ""
    if not sent or not prev:
        return False
    n = _norm(sent)
    blob = _norm(prev)
    if len(n) >= 8 and n in blob:
        return True
    nums_new = set(re.findall(r"\d+", sent))
    nums_old = set(re.findall(r"\d+", prev))
    if nums_new and not nums_new <= nums_old:
        return False
    info = [t for t in _tokens(sent) if t not in _FILLER]
    prev_tokens = set(_tokens(prev))
    if not info or not prev_tokens:
        return False
    if set(info) <= prev_tokens and (len(info) >= 2 or len(n) <= 42):
        return True
    return False


def _card_names(text: str) -> list[str]:
    return re.findall(r"«([^»]{2,40})»", text or "")


def offers_already_sent(text: str, previous: str) -> bool:
    names = _card_names(text)
    if len(names) < 1 or not re.search(r"(?m)^1\)|Почему подходит", text or ""):
        return False
    prev = (previous or "").lower()
    return all(name.lower() in prev for name in names)


def strip_repeated_outbound(msgs: list[str], previous: str) -> list[str]:
    """Убрать пересказ прошлого пузыря и повтор той же подборки."""
    prev = previous or ""
    out: list[str] = []
    seen_blob = prev
    for raw in msgs or []:
        text = (raw or "").strip()
        if not text:
            continue
        if offers_already_sent(text, seen_blob):
            continue
        if re.search(r"(?m)^1\)", text):
            out.append(text)
            seen_blob = (seen_blob + "\n" + text).strip()
            continue
        parts = re.split(r"(?<=[.!?…])\s+|(?<=\))\s+(?=[А-ЯЁA-Z])", text)
        kept = [
            p.strip()
            for p in parts
            if p.strip() and (_is_short_ack(p.strip()) or not sentence_repeats(p.strip(), seen_blob))
        ]
        if kept and all(_is_short_ack(k) for k in kept):
            kept = []  # одно «Хорошо)» без сути — не отправляем
        joined = " ".join(kept).strip()
        if not joined or sentence_repeats(joined, seen_blob):
            continue
        out.append(joined)
        seen_blob = (seen_blob + "\n" + joined).strip()
    return out


_HESITATION_LEAD = re.compile(
    r"(?i)^(?:ну+|эм+|мм+|хм+|ээ+|типа|короче|в\s+общем|как\s+бы|щас|"
    r"секунду|минутку|одну\s+минуту|сейчас\s+подумаю|сейчас\s+гляну|сейчас\s+подберу)\b[,.\s!—-]*"
)
_STALL_TAIL = re.compile(
    r"(?i)\s*[—,-]?\s*(?:сейчас\s+подберу|сейчас\s+гляну|сейчас\s+вернусь|"
    r"одну\s+минуту|секунду|минутку|щас\s+вернусь)[.!…]*\s*$"
)


def smooth_speech(text: str) -> str:
    """Готовая фраза: без «ну», «эм», «секунду» и «сейчас подберу»."""
    raw = (text or "").strip()
    if not raw:
        return raw
    if re.fullmatch(r"[\s🙂😊👍🙏❤️]+", raw):
        return raw  # одиночный смайлик — без точки
    if re.search(r"(?m)^1\)", raw):
        lines = raw.split("\n")
        lines[0] = _smooth_prose(lines[0])
        return "\n".join(lines).strip()
    return _smooth_prose(raw)


def _smooth_prose(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    t = re.sub(r"(?i)\b(поняла|хорошо|ясно|ок)[,!]?\s+\1\b", r"\1", t)
    t = re.sub(r"(?i)не\s+принципиально", "район на ваш выбор", t)
    prev = None
    while prev != t:
        prev = t
        t = _HESITATION_LEAD.sub("", t).strip()
    t = _STALL_TAIL.sub("", t).strip(" ,—-")
    # script.md: «без длинных тире» — вместо них запятая
    t = re.sub(r"[ \t]+—[ \t]+", ", ", t)
    t = re.sub(r",\s*,", ",", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"[ \t]+([,.!?…])", r"\1", t)
    t = re.sub(r"^[—-]\s*", "", t).strip()
    if t and t[0].isalpha() and t[0].islower():
        t = t[0].upper() + t[1:]
    # «Пожалуйста)» — скобка вместо смайлика тоже конец фразы
    if t and t[-1] not in ".!?…🙂😊):" and not re.search(r"https?://\S+$", t):
        t += "."
    return t


def question_key(text: str) -> str:
    """Один тип вопроса в фразе. Утверждение «спокойный район» вопросом не считается."""
    low = (text or "").lower()
    if re.search(r"были\s*у|впервые", low):
        return "returning"
    if re.search(
        r"напишите номер|номер \(1|номер или название|какой ближе|какой вариант",
        low,
    ):
        return "pick"
    if re.search(
        r"на какие даты|какие даты|даты примерно|даты заезда|даты поездки|"
        r"даты и сколько|удобные даты|напишите даты|подскажите даты|"
        r"когда (планируете )?заезд|на какие числа",
        low,
    ):
        return "dates"
    if re.search(
        r"сколько человек|сколько вас|сколько будет гост|число гостей|"
        r"вас будет|сколько гостей",
        low,
    ):
        return "guests"
    if re.search(r"какой район|район удобн|район вам удобн|центр\w* или|где потише", low):
        return "district"
    return ""


def question_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for part in re.split(r"(?<=[.!?…])\s+|\n+", text or ""):
        key = question_key(part)
        if key:
            keys.add(key)
    return keys


def collapse_repeat_asks(msgs: list[str], previous: str = "") -> list[str]:
    """В одном ответе и следом за прошлым — один вопрос каждого типа."""
    seen = question_keys(previous)
    acc = previous or ""
    out: list[str] = []
    dropped: list[str] = []
    for raw in msgs or []:
        text = (raw or "").strip()
        if not text:
            continue
        if re.search(r"(?m)^1\)", text):
            parts = text.split("\n\n")
            if len(parts) >= 2:
                foot_key = question_key(parts[-1])
                if foot_key and foot_key in seen:
                    parts = parts[:-1]
            kept_card = "\n\n".join(p for p in parts if p.strip()).strip()
            if not kept_card:
                continue
            out.append(kept_card)
            seen |= question_keys(kept_card)
            acc = (acc + "\n" + kept_card).strip()
            continue
        kept: list[str] = []
        for sent in re.split(r"(?<=[.!?…])\s+|(?<=\))\s+(?=[А-ЯЁA-Z])", text):
            bit = sent.strip()
            if not bit:
                continue
            key = question_key(bit)
            if key and key in seen:
                if bit.rstrip().endswith("?"):
                    dropped.append(key)
                continue
            if sentence_repeats(bit, acc):
                continue
            kept.append(bit)
            if key:
                seen.add(key)
            acc = (acc + " " + bit).strip()
        if kept:
            out.append(" ".join(kept))
    # гость ответил на другое, а вопрос снят как повтор — без него тупик (10.11 «С 3 по 6 декабря.»)
    # «как определитесь, напишите… Сколько человек поедет?» — сам себе противоречит: вопрос убираем
    if out and is_closing("\n".join(out)) and not any(re.search(r"(?m)^1\)", m) for m in out):
        trimmed = []
        for m in out:
            sents = [x for x in re.split(r"(?<=[.!?…])\s+|(?<=\))\s+(?=[А-ЯЁA-Z])", m) if x.strip()]
            keep = [x for x in sents if not (x.rstrip().endswith("?") and question_key(x))]
            if keep:
                trimmed.append(" ".join(keep))
        out = trimmed or out
    if dropped and out and not any("?" in m for m in out) and not is_closing("\n".join(out)):
        follow = follow_up_ask(dropped[-1], previous)
        if follow:
            out[-1] = f"{out[-1].rstrip()} {follow}"
    return _single_trailing_question(out)


_FOLLOW_UP_ASKS: dict[str, tuple[str, ...]] = {
    "district": (
        "А по району что удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?",
        "Район какой смотрим — центр, ближе к центру, зелёный, спальный или Подмосковье?",
        "Где удобнее жить, в центре или в спокойном районе?",
    ),
    "dates": (
        "А по датам уже понятно, когда заезд?",
        "Когда примерно планируете заезд?",
    ),
    "guests": ("А сколько вас будет?", "Сколько человек поедет?"),
    "returning": ("А вы у нас уже были?", "Вы у нас уже останавливались?"),
}


_SHORT_ACK_RE = re.compile(
    r"(?i)^(?:хорошо|поняла|отлично|ок|окей|да|ясно|супер|ничего\s+страшного)\b[^?]{0,30}$"
)
_CLOSING_RE = re.compile(
    r"(?i)как\s+(?:только\s+)?определитесь|как\s+появятся|(?:как\s+)?будете\s+готовы|как\s+надумаете|"
    r"будем\s+ждать|если\s+что-то\s+планируете|"
    r"напишите,\s+(?:когда|подберу)|когда\s+будут\s+даты|больше\s+не\s+побеспокою|пишите\s+в\s+любое"
)


def _is_short_ack(sentence: str) -> bool:
    """«Хорошо, даты потом)» — связка перед вопросом, не пересказ: не вырезать как повтор."""
    return bool(_SHORT_ACK_RE.match((sentence or "").strip()))


def is_closing(text: str) -> bool:
    """Бот сказал «напишите, когда определитесь» — вопрос следом противоречит."""
    return bool(_CLOSING_RE.search(text or ""))


def follow_up_ask(kind: str, previous: str = "") -> str:
    """Тот же вопрос другими словами — чтобы ответ не обрывался и не звучал заезженно."""
    prev = _norm(previous or "")
    for cand in _FOLLOW_UP_ASKS.get(kind, ()):
        if _norm(cand) not in prev:
            return cand
    return ""


def _single_trailing_question(msgs: list[str]) -> list[str]:
    """Факты остаются, вопрос в пачке один — самый последний."""
    pieces: list[tuple[str, Any]] = []
    found: list[tuple[int, int]] = []
    for raw in msgs:
        if re.search(r"(?m)^1\)", raw):
            parts = raw.split("\n\n")
            pieces.append(("card", parts))
            if parts and question_key(parts[-1]):
                found.append((len(pieces) - 1, -1))
            continue
        sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+|(?<=\))\s+(?=[А-ЯЁA-Z])", raw) if s.strip()]
        pieces.append(("prose", sents))
        for i, sent in enumerate(sents):
            if question_key(sent):
                found.append((len(pieces) - 1, i))
    if len(found) <= 1:
        return msgs
    drop = set(found[:-1])
    out: list[str] = []
    for idx, (kind, data) in enumerate(pieces):
        if kind == "card":
            parts = list(data)
            if (idx, -1) in drop:
                parts = parts[:-1]
            text = "\n\n".join(p for p in parts if p.strip()).strip()
            if text:
                out.append(text)
            continue
        kept = [sent for i, sent in enumerate(data) if (idx, i) not in drop]
        if kept:
            out.append(" ".join(kept))
    return out


def finished_next_line(sess: dict[str, Any] | None, *, skip: set[str] | None = None) -> str:
    """Если модель не успела — сразу следующий вопрос, без «одну минуту»."""
    sess = sess or {}
    skip = skip or set()
    dates = str(sess.get("dates") or "").strip()
    guests = str(sess.get("guests") or "").strip()
    district = str(sess.get("district") or "").strip()
    options = []
    if not dates:
        options.append(("dates", "Подскажите, пожалуйста, на какие даты планируете поездку?"))
    if not guests:
        options.append(("guests", f"На {dates or 'эти даты'} — сколько вас будет?" if dates else "Подскажите, пожалуйста, сколько будет гостей?"))
    if not district:
        options.append(("district", "Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?"))
    options.append(("pick", "Напишите номер варианта или название — продолжу по нему."))
    for key, line in options:
        if key not in skip:
            return line
    return "Напишите, что изменить — даты, гостей или район."


class GuestInbox:
    """Пачка входящих одного чата. Повтор того же message id не копится."""

    def __init__(self) -> None:
        self.buckets: dict[str, list[dict[str, Any]]] = {}
        self.gen: dict[str, int] = {}

    def has(self, chat_id: str, message_id: str) -> bool:
        mid = str(message_id or "")
        if not mid:
            return False
        for item in self.buckets.get(str(chat_id), []):
            if str(item.get("message_id") or "") == mid:
                return True
        return False

    def push(self, item: dict[str, Any]) -> bool:
        cid = str(item.get("chat_id") or "")
        if not cid:
            return False
        mid = str(item.get("message_id") or "")
        bucket = self.buckets.setdefault(cid, [])
        if mid and any(str(x.get("message_id") or "") == mid for x in bucket):
            return False
        text = str(item.get("text") or "").strip()
        if text and any(str(x.get("text") or "").strip() == text for x in bucket):
            return False
        bucket.append(item)
        return True

    def bump(self, chat_id: str) -> int:
        cid = str(chat_id)
        self.gen[cid] = self.gen.get(cid, 0) + 1
        return self.gen[cid]

    def pop_if_gen(self, chat_id: str, gen: int) -> list[dict[str, Any]] | None:
        cid = str(chat_id)
        if self.gen.get(cid) != gen:
            return None
        return self.buckets.pop(cid, [])

    def steal(self, chat_id: str) -> list[dict[str, Any]]:
        """Забрать хвост, пришедший пока шёл ответ, и погасить старый таймер."""
        cid = str(chat_id)
        self.bump(cid)
        return self.buckets.pop(cid, [])


# —— Живая речь: одна и та же формулировка вопроса подряд звучит как анкета ——

_CANON_ASKS: dict[str, tuple[str, ...]] = {
    "dates": (
        "Подскажите, пожалуйста, на какие даты планируете поездку? 🙂",
        "Подскажите, пожалуйста, на какие даты планируете поездку?",
    ),
    "district": (
        "Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?",
        "Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?",
        "Вам ближе к центру, зелёный район, спальный или Подмосковье?",
        "Вам ближе к центру, зелёный, спальный или Подмосковье?",
    ),
}
def _district_variants() -> tuple[str, ...]:
    from bot.phrases import district_choice_message

    return (
        district_choice_message(),
        "У нас есть квартиры в разных районах — выберите удобный для себя.",
        "Какой район удобнее — центр, ближе к центру, зелёный, спальный или Подмосковье?",
    )


_DISTRICT_VARIANTS = _district_variants()
_ECHO_RE = re.compile(
    r"^(один|одна|двое|трое|четверо|пятеро|шестеро|\d{1,2}[–-]\d{1,2}|\d{1,2} (гостей|человек))\.$",
    re.I,
)
_ONLY_EMOJI_RE = re.compile(r"^[\s🙂😊👍🙏)(.!,…]*$")


def _variants(kind: str) -> tuple[str, ...]:
    if kind == "dates":
        from bot.phrases import LOOKING_START

        return tuple(LOOKING_START)
    return _DISTRICT_VARIANTS


def humanize(msgs: list[str], history: list[dict[str, Any]] | None = None) -> list[str]:
    """Чередует формулировки вопросов, убирает пузыри из одного смайлика, оживляет эхо «Четверо.»."""
    bots = [
        str(h.get("text") or "")
        for h in (history or [])
        if (h.get("role") or "") == "bot" and str(h.get("text") or "").strip()
    ]
    recent = "\n".join(bots[-6:]).lower()
    turn = len(bots)
    out: list[str] = []
    only_emoji = bool(msgs) and all(_ONLY_EMOJI_RE.match((m or "").strip()) and (m or "").strip() for m in msgs)
    for raw in msgs or []:
        t = (raw or "").strip()
        if not t or (_ONLY_EMOJI_RE.match(t) and not only_emoji):  # «😊» в ответ на «хорошо» — оставить
            continue
        if not re.search(r"(?m)^1\)", t):  # карточки не трогаем
            for kind, canon in _CANON_ASKS.items():
                for c in canon:
                    if c in t:
                        pool = _variants(kind)
                        pick = next(
                            (
                                pool[(turn + i) % len(pool)]
                                for i in range(len(pool))
                                if pool[(turn + i) % len(pool)].lower() not in recent
                            ),
                            pool[turn % len(pool)],
                        )
                        t = t.replace(c, pick)
                        break
        out.append(t)
    if len(out) == 1 and _ECHO_RE.match(out[0]):
        out[0] = "Поняла, " + out[0][:1].lower() + out[0][1:]
    # гость переспросил то же — не копируем прошлый ответ слово в слово
    if out and bots and "\n".join(out).strip() == bots[-1].strip() and not re.search(r"(?m)^1\)", bots[-1]):
        asks = [p for p in re.split(r"(?<=[.!?…])\s+|(?<=\))\s+(?=[А-ЯЁA-Z])", bots[-1]) if p.rstrip().endswith("?")]
        out = [f"Да) {asks[-1]}" if asks else "Да, всё так)"]
    return out
