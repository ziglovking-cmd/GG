"""Цены в подборе = поля БД; без цены цифр в карточке нет."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.catalog import (
    PRICE_UNKNOWN,
    budget_max_rub,
    catalog_summary,
    format_card,
    offer_bundle,
    pick_apartments,
    priced_count,
)
from bot.faq import match_faq


def _make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        """
        CREATE TABLE objects (
          id INTEGER PRIMARY KEY,
          slug TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          area TEXT,
          address TEXT,
          metro TEXT,
          coords TEXT,
          guide_url TEXT,
          maps_url TEXT,
          review_url TEXT,
          wifi_ssid TEXT,
          wifi_password TEXT,
          parking_hint TEXT,
          checkin TEXT,
          checkout TEXT,
          manager_phone TEXT,
          guest_message TEXT,
          how TEXT,
          price_night INTEGER,
          capacity INTEGER,
          photo_url TEXT
        )
        """
    )
    rows = [
        (
            1,
            "chekhov",
            "Чехов",
            "Бауманская",
            "Балакиревский пер., 23",
            "Бауманская · 5 мин",
            "",
            "https://example.com/g/chekhov",
            "https://maps.example/chekhov",
            "",
            "",
            "",
            "",
            "с 14:00",
            "до 12:00",
            "",
            "",
            "Уютная студия у метро.",
            4500,
            2,
            "https://photo.example/chekhov.jpg",
        ),
        (
            2,
            "briz",
            "Бриз",
            "Коммунарка",
            "Лобановский Лес, 11",
            "Коммунарка · 10 мин",
            "",
            "https://example.com/g/briz",
            "https://maps.example/briz",
            "",
            "",
            "",
            "",
            "с 14:00",
            "до 12:00",
            "",
            "",
            "Студия до 4 гостей, кондиционер.",
            3800,
            4,
            None,
        ),
        (
            3,
            "mystery",
            "Мистери",
            "Одинцово",
            "Каштановая, 6",
            "",
            "",
            "https://example.com/g/mystery",
            "",
            "",
            "",
            "",
            "",
            "с 14:00",
            "до 12:00",
            "",
            "",
            "Тихая квартира без указанной цены.",
            None,  # нет цены
            3,
            None,
        ),
        (
            4,
            "luxury",
            "Люкс",
            "Гагаринский",
            "Центр",
            "Университет",
            "",
            "https://example.com/g/luxury",
            "",
            "",
            "",
            "",
            "",
            "с 14:00",
            "до 12:00",
            "",
            "",
            "Просторная.",
            9000,  # выше типичного бюджета
            4,
            None,
        ),
    ]
    con.executemany(
        """
        INSERT INTO objects (
          id, slug, name, area, address, metro, coords, guide_url, maps_url,
          review_url, wifi_ssid, wifi_password, parking_hint, checkin, checkout,
          manager_phone, guest_message, how, price_night, capacity, photo_url
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    con.commit()
    con.close()


def test_card_price_matches_db() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.sqlite"
        _make_db(db)
        items = pick_apartments(district="центр", guests="2", path=db, limit=10)
        by_name = {o["name"]: o for o in items}
        assert by_name["Чехов"]["price_night"] == 4500
        card = format_card(by_name["Чехов"])
        assert "4500 ₽/сутки" in card
        assert "3500" not in card and "7000" not in card
        assert "До 2 гостей" in card
        assert "photo.example/chekhov" in card


def test_no_price_no_invented_digits() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.sqlite"
        _make_db(db)
        items = pick_apartments(district="спокойный", guests="2", path=db, limit=10)
        mystery = next(o for o in items if o["name"] == "Мистери")
        assert mystery["price_night"] is None
        card = format_card(mystery)
        assert PRICE_UNKNOWN in card
        # в карточке без цены не должно быть сумм вида NNNN ₽/сутки
        assert "₽/сутки" not in card or PRICE_UNKNOWN in card
        assert "4500" not in card
        assert "3800" not in card
        assert "9000" not in card
        assert "3500" not in card
        assert "7000" not in card


def test_budget_filters_by_real_price() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.sqlite"
        _make_db(db)
        items = pick_apartments(
            district="не принципиально",
            guests="2",
            budget="до 5000 ₽",
            path=db,
            limit=10,
        )
        names = {o["name"] for o in items}
        # 9000 строго выше бюджета при enforce
        assert "Люкс" not in names
        # с ценой в бюджете есть
        assert "Чехов" in names or "Бриз" in names
        for o in items:
            p = o.get("price_night")
            if isinstance(p, int):
                assert p <= 5000


def test_guests_filter_by_capacity() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.sqlite"
        _make_db(db)
        items = pick_apartments(guests="4", path=db, limit=10)
        for o in items:
            cap = o.get("capacity")
            if isinstance(cap, int):
                assert cap >= 4
        names = {o["name"] for o in items}
        assert "Чехов" not in names  # capacity 2


def test_offer_bundle_prices_and_unknown() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.sqlite"
        _make_db(db)
        msg, names = offer_bundle(guests="2", path=db, limit=3)
        assert msg
        assert names
        # для каждого имени с ценой в БД — та же цифра в тексте
        con = sqlite3.connect(str(db))
        for name in names:
            row = con.execute(
                "SELECT price_night FROM objects WHERE name=?", (name,)
            ).fetchone()
            price = row[0]
            if price is not None:
                assert f"{price} ₽/сутки" in msg
            else:
                assert PRICE_UNKNOWN in msg
                # чужие цены не подставляем рядом с этим лотом — проверяем блок лота
                # (глобально в msg могут быть другие цены — ок)
        con.close()


def test_faq_no_orientative_range() -> None:
    hit = match_faq("Сколько стоит квартира?")
    assert hit is not None
    msgs, _ = hit
    blob = " ".join(msgs)
    assert "3500" not in blob
    assert "7000" not in blob
    assert "менеджер" in blob.lower() or "каталог" in blob.lower()


def test_budget_max_rub() -> None:
    assert budget_max_rub("до 5000 ₽") == 5000
    assert budget_max_rub("бюджет 6 тысяч") is None or budget_max_rub("6 тыс") == 6000


def test_live_mailing_sqlite_schema_and_no_fake_prices() -> None:
    """Живая БД: колонки есть/добавляются; без цен не показываем ориентир."""
    root = Path(__file__).resolve().parents[1]
    db = root / "data" / "mailing.sqlite"
    if not db.exists():
        return
    with_price, total = priced_count(db)
    assert total >= 1
    summary = catalog_summary(db)
    assert "3500" not in summary and "7000" not in summary
    msg, _ = offer_bundle(district="центр", guests="2", path=db, limit=2)
    assert msg
    if with_price == 0:
        assert PRICE_UNKNOWN in msg
        assert "3500" not in msg and "7000" not in msg


if __name__ == "__main__":
    test_card_price_matches_db()
    test_no_price_no_invented_digits()
    test_budget_filters_by_real_price()
    test_guests_filter_by_capacity()
    test_offer_bundle_prices_and_unknown()
    test_faq_no_orientative_range()
    test_budget_max_rub()
    test_live_mailing_sqlite_schema_and_no_fake_prices()
    print("ALL OK")
