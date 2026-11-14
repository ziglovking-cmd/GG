#!/usr/bin/env python3
"""Обновление price_night / capacity / photo_url из официального сайта Home24.

Источник: https://home24.msk.ru/api/travelline/sync-state
(тот же каталог, что на сайте; цены TravelLine priceCache.pricePerNight).

Если карточка на сайте не сопоставлена уверенно — поля цены не трогаем,
slug попадает в data/price_manual_review.txt.

Яндекс.Карты: только fallback; при капче/403 не обходим защиту.

Пример:
  python scripts/update_prices.py
  python scripts/update_prices.py --db data/mailing.sqlite --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "mailing.sqlite"
SITE = "https://home24.msk.ru"
SYNC_URL = f"{SITE}/api/travelline/sync-state"
CACHE_PATH = ROOT / "data" / "travelline_sync_state.json"
REVIEW_PATH = ROOT / "reports" / "price_manual_review.txt"
REPORT_PATH = ROOT / "reports" / "price_update_report.json"

UA = "Home24CatalogPriceSync/1.0 (+local; polite; contact via home24.msk.ru)"
REQUEST_PAUSE_SEC = 1.2
LOG = logging.getLogger("update_prices")

OPTIONAL_COLS = (
    ("price_night", "INTEGER"),
    ("capacity", "INTEGER"),
    ("photo_url", "TEXT"),
    ("price_source", "TEXT"),
    ("price_updated_at", "TEXT"),
)


@dataclass
class SiteCard:
    card_id: str
    title: str
    address: str
    guests: int | None
    price: int | None
    photo_url: str | None
    room_type_id: str | None
    page_url: str


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _addr_key(s: str) -> str:
    s = _norm(s)
    s = re.split(r"\s*·\s*", s)[0]
    return re.sub(r"[^а-яa-z0-9]+", "", s)


def _title_key(s: str) -> str:
    s = _norm(s)
    s = re.sub(r"^(студия|квартира|апартаменты)\s+", "", s)
    return s.strip(" «»\"'")


def _site_slug(title: str, room_type_id: str | None, card_id: str) -> str:
    """Как Mh() на home24.msk.ru — кириллический slug + room type id."""
    base = (
        (title or "")
        .lower()
        .replace("ё", "е")
    )
    base = re.sub(r"[^a-zа-я0-9]+", "-", base, flags=re.I)
    base = re.sub(r"^-+|-+$", "", base) or "travelline"
    rid = room_type_id or card_id
    return f"{base}-{rid}".lower()


def ensure_columns(con: sqlite3.Connection) -> None:
    existing = {r[1] for r in con.execute("PRAGMA table_info(objects)")}
    for name, typ in OPTIONAL_COLS:
        if name not in existing:
            con.execute(f"ALTER TABLE objects ADD COLUMN {name} {typ}")
            LOG.info("added column objects.%s", name)
    con.commit()


def http_get_json(
    url: str,
    *,
    timeout: float = 180.0,
    retries: int = 3,
    pause: float = REQUEST_PAUSE_SEC,
) -> tuple[Any | None, str]:
    """Returns (data, error). error nonempty on failure / block. No captcha bypass."""
    last_err = "unknown"
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200) or 200
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode("utf-8", "ignore")
            if e.code in (401, 403, 429):
                return None, f"blocked HTTP {e.code}: {body[:120]}"
            last_err = f"HTTP {e.code}: {body[:120]}"
            time.sleep(pause * attempt)
            continue
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            LOG.warning("fetch attempt %s/%s failed: %s", attempt, retries, last_err)
            time.sleep(pause * attempt)
            continue

        text = raw.decode("utf-8", "ignore")
        if re.search(r"SmartCaptcha|captcha|are you not a robot|Access denied", text, re.I):
            return None, "captcha_or_access_denied"
        if status >= 400:
            return None, f"HTTP {status}"
        if "json" not in ctype and not text.lstrip().startswith("{"):
            return None, f"non-json response ({ctype})"
        try:
            return json.loads(text), ""
        except json.JSONDecodeError as e:
            return None, f"json: {e}"
    return None, last_err


def field_val(card: dict[str, Any], [REDACTED] -> Any:
    f = (card.get("fields") or {}).get(key) or {}
    if not isinstance(f, dict):
        return f
    local = f.get("local")
    if local not in (None, ""):
        return local
    return f.get("travelline")


def first_photo(card: dict[str, Any]) -> str | None:
    photos = field_val(card, "travellinePhotos") or []
    extra = field_val(card, "additionalPhotos") or []
    items = []
    if isinstance(photos, list):
        items.extend(photos)
    if isinstance(extra, list):
        items.extend(extra)
    items.sort([REDACTED] x: 0 if isinstance(x, dict) and x.get("isCover") else 1)
    for it in items:
        if isinstance(it, dict):
            url = it.get("url") or it.get("src")
            if isinstance(url, str) and url.startswith("http") and not it.get("hidden"):
                return url
        elif isinstance(it, str) and it.startswith("http"):
            return it
    return None


def parse_site_cards(payload: dict[str, Any]) -> list[SiteCard]:
    state = payload.get("state") or payload
    cards = state.get("cards") or []
    out: list[SiteCard] = []
    for c in cards:
        if (c.get("status") or "") != "published":
            continue
        title = str(field_val(c, "title") or "").strip()
        if not title:
            continue
        # не парковки / служебные
        if _norm(title).startswith("парковка"):
            continue
        addr_raw = str(field_val(c, "addressCoordinates") or field_val(c, "address") or "")
        addr = re.split(r"\s*·\s*", addr_raw)[0].strip()
        guests_raw = field_val(c, "guests")
        guests: int | None
        try:
            guests = int(guests_raw) if guests_raw is not None else None
        except (TypeError, ValueError):
            guests = None
        if guests is not None and guests < 1:
            guests = None
        pc = c.get("priceCache") or {}
        price_raw = pc.get("pricePerNight")
        if price_raw in (None, "", 0, "0"):
            price_raw = pc.get("widgetPricePerNight")
        try:
            price = int(price_raw) if price_raw not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        if price is not None and price <= 0:
            price = None
        room_id = str(c.get("travellineRoomTypeId") or "") or None
        slug = _site_slug(title, room_id, str(c.get("id") or ""))
        out.append(
            SiteCard(
                card_id=str(c.get("id") or ""),
                title=title,
                address=addr,
                guests=guests,
                price=price,
                photo_url=first_photo(c),
                room_type_id=room_id,
                page_url=f"{SITE}/apartments/{slug}",
            )
        )
    return out


def match_score(obj: sqlite3.Row, card: SiteCard) -> tuple[float, str]:
    name = _title_key(obj["name"])
    title = _title_key(card.title)
    addr_o = _addr_key(obj["address"] or "")
    addr_c = _addr_key(card.address)
    score = 0.0
    why: list[str] = []

    if name == title:
        score += 10
        why.append("name")
    else:
        ratio = SequenceMatcher(None, name, title).ratio()
        if ratio >= 0.9:
            score += 8
            why.append(f"name~{ratio:.2f}")
        elif ratio >= 0.78:
            score += 5
            why.append(f"name~{ratio:.2f}")

    if addr_o and addr_c:
        if addr_o == addr_c or addr_o in addr_c or addr_c in addr_o:
            score += 6
            why.append("addr")
        else:
            ar = SequenceMatcher(None, addr_o, addr_c).ratio()
            if ar >= 0.85:
                score += 4
                why.append(f"addr~{ar:.2f}")
            elif ar >= 0.7:
                score += 2
                why.append(f"addr~{ar:.2f}")

    # slug hint (ferrari ↔ …)
    slug = _norm(obj["slug"] or "")
    if slug and slug in _norm(card.page_url):
        score += 1
        why.append("slug")

    return score, ",".join(why)


def pick_card(obj: sqlite3.Row, cards: list[SiteCard]) -> tuple[SiteCard | None, float, str]:
    """Уверенный матч: имя (+ адрес при коллизиях)."""
    scored: list[tuple[float, str, SiteCard]] = []
    for c in cards:
        sc, why = match_score(obj, c)
        if sc > 0:
            scored.append((sc, why, c))
    if not scored:
        return None, 0.0, ""
    scored.sort([REDACTED] x: -x[0])
    best_sc, best_why, best = scored[0]

    # коллизия имён (два «Кандинский») — требуем адрес
    same_title = [
        x for x in scored if _title_key(x[2].title) == _title_key(obj["name"])
    ]
    if len(same_title) > 1:
        with_addr = [x for x in same_title if "addr" in x[1]]
        if not with_addr:
            return None, best_sc, "ambiguous_name:" + best_why
        with_addr.sort([REDACTED] x: -x[0])
        best_sc, best_why, best = with_addr[0]
        return best, best_sc, best_why

    # порог уверенности
    if best_sc >= 10:  # точное имя (+ возможно адрес)
        return best, best_sc, best_why
    if best_sc >= 12:  # name fuzzy + addr
        return best, best_sc, best_why
    if best_sc >= 9 and "name" in best_why and "addr" in best_why:
        return best, best_sc, best_why
    # name~0.9 alone ok if unique title on site
    if best_sc >= 8 and best_why.startswith("name~"):
        titles = [_title_key(c.title) for c in cards]
        if titles.count(_title_key(best.title)) == 1:
            return best, best_sc, best_why
    return None, best_sc, "low_confidence:" + best_why


def try_yandex_price(maps_url: str) -> tuple[int | None, str]:
    """Мягкая попытка; при капче/403 — пусто, без обхода."""
    if not maps_url or "yandex." not in maps_url:
        return None, "no_maps_url"
    time.sleep(REQUEST_PAUSE_SEC)
    req = urllib.request.Request(maps_url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
            status = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            return None, f"yandex_blocked_{e.code}"
        return None, f"yandex_http_{e.code}"
    except Exception as e:
        return None, f"yandex_{type(e).__name__}"
    html = raw.decode("utf-8", "ignore")
    if status in (401, 403) or re.search(
        r"SmartCaptcha|captcha|are you not a robot", html, re.I
    ):
        return None, "yandex_captcha"
    # не парсим сомнительные цифры с карт — слишком шумно; только явный priceRange
    m = re.search(
        r'"priceRange"\s*:\s*"([^"]+)"|itemprop="price"\s+content="(\d+)"',
        html,
        re.I,
    )
    if not m:
        return None, "yandex_no_price"
    blob = m.group(1) or m.group(2) or ""
    nums = [int(x) for x in re.findall(r"\d{3,6}", blob.replace(" ", ""))]
    if not nums:
        return None, "yandex_no_price"
    return nums[0], maps_url


def update_db(
    db_path: Path,
    cards: list[SiteCard],
    *,
    dry_run: bool,
    yandex_fallback: bool,
) -> dict[str, Any]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    ensure_columns(con)
    objs = list(con.execute("SELECT * FROM objects ORDER BY id"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    updated = 0
    manual: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    yandex_note = ""

    for obj in objs:
        card, score, why = pick_card(obj, cards)
        if card is None or card.price is None:
            # optional yandex
            y_price = None
            y_src = ""
            if yandex_fallback and card is None:
                y_price, y_src = try_yandex_price(obj["maps_url"] or "")
                if y_src.startswith("yandex_captcha") or y_src.startswith("yandex_blocked"):
                    yandex_note = y_src
                    yandex_fallback = False  # stop further attempts
            if y_price is None:
                manual.append(
                    {
                        "slug": obj["slug"],
                        "name": obj["name"],
                        "address": obj["address"],
                        "reason": why or "no_match",
                        "best_score": score,
                        "maps_url": obj["maps_url"] or "",
                    }
                )
                continue
            # yandex hit — still require name confidence; we only got here if no card
            manual.append(
                {
                    "slug": obj["slug"],
                    "name": obj["name"],
                    "address": obj["address"],
                    "reason": f"yandex_only_unverified:{y_src}",
                    "best_score": score,
                    "maps_url": obj["maps_url"] or "",
                }
            )
            continue

        source = card.page_url
        row = {
            "slug": obj["slug"],
            "name": obj["name"],
            "price_night": card.price,
            "capacity": card.guests,
            "photo_url": card.photo_url,
            "price_source": source,
            "matched_title": card.title,
            "matched_address": card.address,
            "score": score,
            "why": why,
        }
        if len(samples) < 5:
            samples.append(row)

        if dry_run:
            updated += 1
            continue

        con.execute(
            """
            UPDATE objects SET
              price_night = ?,
              capacity = COALESCE(?, capacity),
              photo_url = COALESCE(?, photo_url),
              price_source = ?,
              price_updated_at = ?
            WHERE id = ?
            """,
            (
                card.price,
                card.guests,
                card.photo_url,
                source,
                now,
                obj["id"],
            ),
        )
        updated += 1

    if not dry_run:
        con.commit()
    with_price = con.execute(
        "SELECT COUNT(*) FROM objects WHERE price_night IS NOT NULL AND price_night > 0"
    ).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
    con.close()

    report = {
        "site": SITE,
        "sync_url": SYNC_URL,
        "updated_at": now,
        "dry_run": dry_run,
        "site_cards": len(cards),
        "db_total": total,
        "prices_written": updated,
        "with_price_in_db": with_price,
        "manual_review": manual,
        "samples": samples,
        "yandex": yandex_note or ("skipped_after_block" if not yandex_fallback else "ok_or_unused"),
    }
    return report


def write_review(manual: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# Квартиры без уверенной цены — для ручной проверки",
        f"# generated {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    for m in manual:
        lines.append(
            f"{m['slug']}\t{m['name']}\t{m.get('address','')}\t{m.get('reason','')}\t"
            f"score={m.get('best_score')}\t{m.get('maps_url','')}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-yandex", action="store_true", help="не ходить в Яндекс.Карты")
    p.add_argument("--sync-file", type=Path, help="локальный sync-state.json вместо сети")
    p.add_argument("--pause", type=float, default=REQUEST_PAUSE_SEC)
    args = p.parse_args(argv)

    if not args.db.exists():
        LOG.error("db missing: %s", args.db)
        return 1

    if args.sync_file:
        payload = json.loads(args.sync_file.read_text(encoding="utf-8"))
        err = ""
        LOG.info("loaded sync from %s", args.sync_file)
    else:
        LOG.info("fetch %s", SYNC_URL)
        time.sleep(max(0.0, args.pause))
        payload, err = http_get_json(SYNC_URL, pause=max(0.0, args.pause))
        if err and CACHE_PATH.exists():
            LOG.warning("live fetch failed (%s); using cache %s", err, CACHE_PATH)
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            err = ""
        elif err:
            LOG.error("site blocked or unavailable: %s", err)
            print(
                "Сайт home24.msk.ru недоступен или блокирует VM "
                f"({err}). Защиту не обходим. Передайте --sync-file с выгрузкой API "
                "или положите кэш в data/travelline_sync_state.json.",
                file=sys.stderr,
            )
            return 2
        else:
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
                LOG.info("cached sync → %s", CACHE_PATH)
            except OSError:
                LOG.exception("could not write cache")

    cards = parse_site_cards(payload)
    LOG.info("published site cards with parseable data: %s", len(cards))
    with_price = sum(1 for c in cards if c.price)
    LOG.info("cards with price: %s", with_price)

    report = update_db(
        args.db,
        cards,
        dry_run=args.dry_run,
        yandex_fallback=not args.no_yandex,
    )
    write_review(report["manual_review"], REVIEW_PATH)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"site={SITE} prices={report['with_price_in_db']}/{report['db_total']} "
        f"written={report['prices_written']} manual={len(report['manual_review'])} "
        f"yandex={report['yandex']}"
    )
    for s in report["samples"]:
        print(
            f"  {s['slug']}: {s['price_night']} ₽ · cap={s['capacity']} · {s['price_source']}"
        )
    if report["manual_review"]:
        print("manual_review:")
        for m in report["manual_review"]:
            print(f"  {m['slug']}: {m['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
