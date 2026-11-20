"""Проверка календаря TravelLine на сервере: что свободно и что бот покажет гостю.

    python scripts/tl_check.py 2026-12-12 2026-12-15 3 Прокшино

Печатает все свободные квартиры из календаря (как их видит бот: название, адрес, район из script.md,
сколько свободно таких, цена) и отдельно — какие попали под район, который назвал гость.
Если квартира свободна в TravelLine, но не попала под район, — допишите её в раздел «Районы» в script.md.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    from bot.apartments_map import areas_for_place, place_short
    from bot.travelline import describe_availability_offer, matches_place, search_stays

    arrival = date.fromisoformat(argv[0])
    departure = date.fromisoformat(argv[1])
    adults = int(argv[2])
    place = " ".join(argv[3:]).strip()
    stays = search_stays(arrival, departure, adults)
    if stays is None:
        print("Календарь не ответил (нет связи с home24.msk.ru или TravelLine).")
        return 1
    print(f"Свободно в календаре на {arrival}–{departure}, гостей {adults}: {len(stays)}")
    for s in sorted(stays, [REDACTED] x: x.title):
        hit = "✓" if place and matches_place(s, place) else " "
        print(
            f" {hit} {s.title:<22} | TL: {s.raw_name or '-':<40} | адрес: {s.address or '—':<40} "
            f"| {place_short(s.title) or 'нет в «Адреса»'} | свободно: {s.available} | {s.price_total or '-'} ₽"
        )
    if place:
        print(f"\nРайон «{place}» по script.md: {areas_for_place(place) or 'не найден в «Районы»'}")
        text, names = describe_availability_offer(arrival, departure, stays, place)
        print(f"Под район попали: {', '.join(names) or 'никто'}\n\nОтвет гостю:\n{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
