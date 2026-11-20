# -*- coding: utf-8 -*-
"""Шаблоны быстрых ответов менеджера (data/templates.json)."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("home24.reply_templates")
_LOCK = threading.RLock()

CATEGORIES: list[tuple[str, str]] = [
    ("greeting", "Приветствие / перехват"),
    ("closing", "Прощание"),
]

CATEGORY_LABELS = {k: v for k, v in CATEGORIES}

# старые стоковые id (даты/цены и т.п.) — бот уже собирает это сам; убираем при обновлении
OBSOLETE_DEFAULT_IDS: frozenset[str] = frozenset(
    {
        "ask_dates",
        "ask_guests",
        "confirm_dates_guests",
        "ask_district",
        "confirm_district",
        "send_options",
        "send_options_short",
        "booking_confirm",
        "booking_hold",
        "payment_request",
        "payment_received",
        "checkin_info",
        "checkin_wifi",
        "followup_soft",
        "followup_dates",
        "decline_no_dates",
        "decline_polite",
    }
)


def default_templates_path() -> Path:
    return Path(os.getenv("TEMPLATES_PATH") or "data/templates.json")


def _first_name(raw: str) -> str:
    try:
        from bot.phrases import real_first_name

        return real_first_name(raw)
    except Exception:
        s = (raw or "").strip()
        s = re.sub(r"^(DEMO\s*[·•\-—]\s*)", "", s, flags=re.I).strip()
        if not s:
            return ""
        part = s.split()[0]
        return part.strip(".,;:")


DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "greet_takeover",
        "category": "greeting",
        "title": "Перехват от бота",
        "body": (
            "{имя}, добрый день! Это Home24 — "
            "продолжаю ваш диалог 🙂\n"
            "Все пожелания уже вижу, с радостью помогу дальше."
        ),
        "sort": 10,
    },
    {
        "id": "greet_intro",
        "category": "greeting",
        "title": "Короткое представление",
        "body": (
            "Здравствуйте{, имя}! Это Home24.\n"
            "Переписку передали мне — дальше помогу лично."
        ),
        "sort": 20,
    },
    {
        "id": "greet_warm",
        "category": "greeting",
        "title": "Тёплый вход",
        "body": (
            "{имя}, добрый день! Это снова Home24.\n"
            "Забираю диалог — пишите, чем могу помочь 🙂"
        ),
        "sort": 30,
    },
    {
        "id": "greet_brief",
        "category": "greeting",
        "title": "Очень коротко",
        "body": (
            "Добрый день{, имя}! Это Home24.\n"
            "Подключилась вместо бота — продолжим 🙂"
        ),
        "sort": 40,
    },
    {
        "id": "closing_thanks",
        "category": "closing",
        "title": "Спасибо / до встречи",
        "body": (
            "Спасибо, что выбрали Home24!\n"
            "Если что-то понадобится — пишите, я рядом. Хорошего дня 🙂"
        ),
        "sort": 10,
    },
    {
        "id": "closing_goodbye",
        "category": "closing",
        "title": "Мягкое прощание",
        "body": (
            "{имя}, тогда до связи!\n"
            "Было очень приятно помочь. До встречи в Home24 🙂"
        ),
        "sort": 20,
    },
    {
        "id": "closing_after_stay",
        "category": "closing",
        "title": "После проживания",
        "body": (
            "{имя}, надеюсь, всё прошло комфортно 🙂\n"
            "Будем рады видеть снова — до встречи!"
        ),
        "sort": 30,
    },
    {
        "id": "closing_short",
        "category": "closing",
        "title": "Короткое «всего доброго»",
        "body": "Всего доброго{, имя}! Если планы появятся — просто напишите.",
        "sort": 40,
    },
]


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    tid = str(raw.get("id") or "").strip()
    body = str(raw.get("body") or "").strip()
    if not tid or not body:
        return None
    cat = str(raw.get("category") or "greeting").strip()
    if cat not in CATEGORY_LABELS:
        cat = "greeting"
    scope = str(raw.get("scope") or "shared").strip()
    if scope not in ("shared", "personal"):
        scope = "shared"
    return {
        "id": tid,
        "category": cat,
        "title": str(raw.get("title") or tid)[:120],
        "body": body[:4000],
        "scope": scope,
        "owner": str(raw.get("owner") or "").strip(),
        "enabled": bool(raw.get("enabled", True)),
        "sort": int(raw.get("sort") or 100),
        "updated_at": float(raw.get("updated_at") or 0) or time.time(),
    }


def _seed_defaults() -> list[dict[str, Any]]:
    out = []
    for i, d in enumerate(DEFAULT_TEMPLATES):
        item = _normalize_item(
            {
                **d,
                "scope": "shared",
                "owner": "",
                "enabled": True,
                "updated_at": time.time(),
                "sort": int(d.get("sort") or (i + 1) * 10),
            }
        )
        if item:
            out.append(item)
    return out


class TemplateStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or default_templates_path())
        self.templates: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        with _LOCK:
            if not self.path.exists():
                self.templates = _seed_defaults()
                self._save_unlocked()
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("templates load failed — reseed")
                self.templates = _seed_defaults()
                self._save_unlocked()
                return
            items: list[dict[str, Any]] = []
            changed = False
            for raw in data.get("templates") or []:
                if not isinstance(raw, dict):
                    continue
                n = _normalize_item(raw)
                if not n:
                    continue
                # выкинуть устаревшие стоковые шаблоны (даты/цены — собирает бот)
                if (
                    n["scope"] == "shared"
                    and n["id"] in OBSOLETE_DEFAULT_IDS
                    and not n.get("owner")
                ):
                    changed = True
                    continue
                items.append(n)
            # preserve on update: добавить недостающие дефолты, не затирать правки
            have = {t["id"] for t in items}
            for d in _seed_defaults():
                if d["id"] not in have:
                    items.append(d)
                    changed = True
            self.templates = items
            if changed or not items:
                if not items:
                    self.templates = _seed_defaults()
                self._save_unlocked()

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "templates": sorted(
                self.templates,
                [REDACTED] t: (
                    0 if t["scope"] == "shared" else 1,
                    t.get("category") or "",
                    int(t.get("sort") or 100),
                    t.get("title") or "",
                ),
            ),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def save(self) -> None:
        with _LOCK:
            self._save_unlocked()

    def list_for(
        self,
        *,
        username: str = "",
        is_admin: bool = False,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        cat_order = {c: i for i, (c, _) in enumerate(CATEGORIES)}
        with _LOCK:
            out: list[dict[str, Any]] = []
            for t in self.templates:
                if not include_disabled and not t.get("enabled", True):
                    continue
                if t["scope"] == "shared":
                    out.append(dict(t))
                elif t["scope"] == "personal" and t.get("owner") == username:
                    out.append(dict(t))
            out.sort(
                [REDACTED] t: (
                    cat_order.get(t.get("category") or "", 99),
                    0 if t.get("scope") == "shared" else 1,
                    int(t["sort"]) if t.get("sort") is not None else 100,
                    t.get("title") or "",
                )
            )
            return out

    def reorder_personal(
        self, username: str, ordered_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Выставить sort личным шаблонам по порядку id. Чужие не трогаем."""
        owner = (username or "").strip()
        ids = [str(x).strip() for x in (ordered_ids or []) if str(x).strip()]
        with _LOCK:
            personal = [
                t
                for t in self.templates
                if t.get("scope") == "personal" and t.get("owner") == owner
            ]
            by_id = {t["id"]: t for t in personal}
            rank = 0
            for tid in ids:
                t = by_id.pop(tid, None)
                if not t:
                    continue
                t["sort"] = rank * 10
                t["updated_at"] = time.time()
                rank += 1
            # оставшиеся — в конец, порядок сохранить
            for t in sorted(by_id.values(), [REDACTED] x: int(x.get("sort") or 100)):
                t["sort"] = rank * 10
                t["updated_at"] = time.time()
                rank += 1
            self._save_unlocked()
            personal_out = [
                dict(t)
                for t in self.templates
                if t.get("scope") == "personal" and t.get("owner") == owner
            ]
            personal_out.sort(
                [REDACTED] t: (
                    int(t["sort"]) if t.get("sort") is not None else 100,
                    t.get("title") or "",
                )
            )
            return personal_out

    def get(self, tid: str) -> dict[str, Any] | None:
        with _LOCK:
            for t in self.templates:
                if t["id"] == tid:
                    return dict(t)
            return None

    def upsert(
        self,
        *,
        tid: str | None,
        title: str,
        body: str,
        category: str,
        scope: str,
        owner: str,
        enabled: bool = True,
        sort: int | None = None,
        actor: str,
        is_admin: bool,
    ) -> dict[str, Any]:
        title = (title or "").strip()[:120]
        body = (body or "").strip()[:4000]
        if not title or not body:
            raise ValueError("нужны title и body")
        if category not in CATEGORY_LABELS:
            raise ValueError("неизвестная категория")
        if scope not in ("shared", "personal"):
            raise ValueError("scope: shared|personal")
        if scope == "shared" and not is_admin:
            raise PermissionError("только админ может менять общие шаблоны")
        if scope == "personal":
            owner = (owner or actor or "").strip()
            if not owner:
                raise ValueError("нужен owner для личного шаблона")
            if not is_admin and owner != actor:
                raise PermissionError("чужой личный шаблон")
        with _LOCK:
            existing = None
            tid = (str(tid).strip() if tid else "") or ""
            if tid:
                for t in self.templates:
                    if t["id"] == tid:
                        existing = t
                        break
            if existing is not None:
                if existing["scope"] == "shared" and not is_admin:
                    raise PermissionError("только админ")
                if existing["scope"] == "personal" and not is_admin:
                    if existing.get("owner") != actor:
                        raise PermissionError("чужой личный шаблон")
                existing["title"] = title
                existing["body"] = body
                existing["category"] = category
                existing["enabled"] = enabled
                if sort is not None:
                    existing["sort"] = int(sort)
                existing["updated_at"] = time.time()
                # scope/owner не меняем при edit
                self._save_unlocked()
                return dict(existing)
            # новый шаблон: свой id (если передали и свободен) или авто
            new_id = tid or f"{scope}_{uuid.uuid4().hex[:10]}"
            item = _normalize_item(
                {
                    "id": new_id,
                    "title": title,
                    "body": body,
                    "category": category,
                    "scope": scope,
                    "owner": owner if scope == "personal" else "",
                    "enabled": enabled,
                    "sort": int(sort if sort is not None else 500),
                    "updated_at": time.time(),
                }
            )
            assert item
            self.templates.append(item)
            self._save_unlocked()
            return dict(item)

    def delete(self, tid: str, *, actor: str, is_admin: bool) -> None:
        with _LOCK:
            for i, t in enumerate(self.templates):
                if t["id"] != tid:
                    continue
                if t["scope"] == "shared" and not is_admin:
                    raise PermissionError("только админ")
                if t["scope"] == "personal" and not is_admin:
                    if t.get("owner") != actor:
                        raise PermissionError("чужой личный шаблон")
                self.templates.pop(i)
                self._save_unlocked()
                return
            raise KeyError("шаблон не найден")


_store: TemplateStore | None = None


def get_template_store() -> TemplateStore:
    global _store
    with _LOCK:
        if _store is None:
            _store = TemplateStore()
        return _store


def reset_template_store_cache() -> None:
    global _store
    with _LOCK:
        _store = None


def placeholder_vars(
    dialog: dict[str, Any] | None,
    *,
    manager_name: str = "",
) -> dict[str, str]:
    """Значения плейсхолдеров из диалога + mailing.sqlite."""
    d = dialog or {}
    ctx = dict(d.get("context") or {})
    name = _first_name(
        str(d.get("contact_name") or d.get("name") or ctx.get("name") or "")
    )
    dates = str(d.get("dates") or ctx.get("dates") or "").strip() or "даты уточним"
    guests = str(d.get("guests") or ctx.get("guests") or "").strip() or "кол-во гостей уточним"
    district = (
        str(d.get("district") or ctx.get("district") or "").strip() or "район уточним"
    )
    favorite = str(d.get("favorite") or ctx.get("favorite") or "").strip()
    apt_name = favorite or "квартира"
    address = "адрес уточню"
    metro = ""
    price = "цену уточню"
    guide = ""

    obj = None
    if favorite:
        try:
            from bot.catalog import find_by_name, find_by_name_fuzzy

            obj = find_by_name(favorite) or find_by_name_fuzzy(favorite)
        except Exception:
            logger.exception("catalog lookup for template failed")
    if obj:
        apt_name = str(obj.get("name") or apt_name)
        if obj.get("address"):
            address = str(obj["address"])
        if obj.get("metro"):
            metro = str(obj["metro"])
        pn = obj.get("price_night")
        if isinstance(pn, int) and pn > 0:
            price = f"{pn} ₽/сутки"
        if obj.get("guide_url"):
            guide = str(obj["guide_url"])

    mgr = (manager_name or "").strip() or "менеджер Home24"

    return {
        "имя": name,
        "даты": dates,
        "гости": guests,
        "район": district,
        "квартира": apt_name,
        "адрес": address,
        "метро": metro,
        "цена": price,
        "инструкция": guide,
        "менеджер": mgr,
        "name": name,
        "dates": dates,
        "guests": guests,
        "district": district,
        "address": address,
        "price": price,
        "apartment": apt_name,
        "metro": metro,
        "manager": mgr,
    }


_COND_COMMA_NAME = re.compile(r"\{\s*,\s*имя\s*\}", re.I)
_COND_DOT_DATES = re.compile(r"\{\s*·\s*даты\s*\}", re.I)
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def fill_template(body: str, vars_map: dict[str, str]) -> str:
    """Подставить плейсхолдеры; условные {, имя} / { · даты} — если значение есть."""
    text = body or ""
    name = (vars_map.get("имя") or "").strip()
    dates = (vars_map.get("даты") or "").strip()
    # не подставлять заглушки в условные формы
    real_dates = dates if dates and dates != "даты уточним" else ""

    def _comma_name(_m: re.Match[str]) -> str:
        return f", {name}" if name else ""

    def _dot_dates(_m: re.Match[str]) -> str:
        return f" · {real_dates}" if real_dates else ""

    text = _COND_COMMA_NAME.sub(_comma_name, text)
    text = _COND_DOT_DATES.sub(_dot_dates, text)

    # без имени: «{имя}, добрый день» → «Добрый день»
    if not name:
        text = re.sub(r"\{имя\}\s*,\s*", "", text, flags=re.I)

    def _repl(m: re.Match[str]) -> str:
        [REDACTED]
        if key in vars_map:
            return vars_map[key]
        # case-insensitive
        for k, v in vars_map.items():
            if k.lower() == key.lower():
                return v
        return m.group(0)

    text = _PLACEHOLDER.sub(_repl, text)
    if not name:
        text = re.sub(r"^,\s*", "", text)
        # «добрый день» после удаления имени — с заглавной
        text = re.sub(
            r"^(добрый день|доброе утро|добрый вечер|здравствуйте)\b",
            lambda m: m.group(1)[:1].upper() + m.group(1)[1:],
            text,
            flags=re.I,
        )
    # убрать строки, ставшие пустыми (например пустой {метро})
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines).strip()


def public_categories() -> list[dict[str, str]]:
    return [{"id": k, "label": v} for k, v in CATEGORIES]
