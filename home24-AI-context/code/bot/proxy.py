"""Опциональный SOCKS-прокси для Telethon.

По умолчанию прокси ВЫКЛЮЧЕН. Для Home24 (SIM компании на одном ПК) —
без прокси, без ротации IP и без маскировки устройства.
Не включать USE_PROXY без явной нужды админа.
  USE_PROXY=1 + data/working_proxy.txt  (host:port или host:port:user:pass)
  или TELEGRAM_PROXY=host:port[:user:pass]
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("home24.proxy")


class EgressProxyMissing(RuntimeError):
    """Слот просит чужой IP, а строки прокси нет. Напрямую не подключаемся."""


def _parse_line(line: str) -> tuple | None:
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None
    # socks5://host:port
    if "://" in line:
        line = line.split("://", 1)[1]
    parts = line.split(":")
    if len(parts) == 2:
        host, port = parts
        return ("socks5", host, int(port), True)
    if len(parts) >= 4:
        host, port, user, pwd = parts[0], parts[1], parts[2], ":".join(parts[3:])
        return ("socks5", host, int(port), True, user, pwd)
    return None


def load_proxy() -> tuple | None:
    env_line = (os.getenv("TELEGRAM_PROXY") or "").strip()
    if env_line:
        proxy = _parse_line(env_line)
        if proxy:
            logger.info("proxy %s:%s (env)", proxy[1], proxy[2])
            return proxy

    use = (os.getenv("USE_PROXY") or "").strip().lower() in ("1", "true", "yes", "on")
    if not use:
        return None

    path = Path("data/working_proxy.txt")
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        proxy = _parse_line(raw)
        if proxy:
            logger.info("proxy %s:%s (file)", proxy[1], proxy[2])
            return proxy
    return None


def load_proxy_for(egress: str) -> tuple | None:
    """Выход в Telegram для слота: server (напрямую), current или bought."""
    [REDACTED] or "server").strip().lower()
    if key in ("", "server", "direct", "none"):
        return None
    env_name = {"current": "TELEGRAM_PROXY_CURRENT", "bought": "TELEGRAM_PROXY_BOUGHT"}.get(key)
    if env_name:
        env_line = (os.getenv(env_name) or "").strip()
        if env_line:
            proxy = _parse_line(env_line)
            if proxy:
                logger.info("proxy %s:%s egress=%s", proxy[1], proxy[2], key)
                return proxy
    filename = {"current": "proxy_current.txt", "bought": "proxy_bought.txt"}.get(
        key, "working_proxy.txt"
    )
    path = Path("data") / filename
    if not path.exists():
        logger.warning("egress=%s proxy file missing: %s", key, path)
        return None
    proxy = _parse_line(path.read_text(encoding="utf-8"))
    if proxy:
        logger.info("proxy %s:%s egress=%s", proxy[1], proxy[2], key)
    return proxy


def load_mtproxy() -> tuple[str, int, str] | None:
    """Один постоянный MTProxy: host:port:secret.

    Нужен, когда датацентр аккаунтов с IP сервера не открывается.
    Секрет в лог не пишем. Пусто — прямое соединение, как раньше.
    """
    raw = (os.getenv("TELEGRAM_MTPROXY") or "").strip()
    if not raw or raw.startswith("#"):
        return None
    parts = raw.split(":")
    if len(parts) < 3 or not parts[1].isdigit():
        logger.warning("TELEGRAM_MTPROXY задан, но это не host:port:secret")
        return None
    host, port, [REDACTED] int(parts[1]), ":".join(parts[2:]).strip()
    if not host or not [REDACTED] None
    logger.info("mtproxy %s:%s", host, port)
    return host, port, secret


def client_transport(egress: str, *, have_slot: bool) -> tuple[type, tuple | None]:
    """Транспорт Telethon для слота.

    server/прямой выход с TELEGRAM_MTPROXY идёт только через него:
    иначе аккаунт сел бы на IP сервера и слетел бы при следующем включении прокси.
    current/bought остаются SOCKS и без строки по-прежнему не падают на IP сервера.
    """
    from telethon.network.connection import (
        ConnectionTcpAbridged,
        ConnectionTcpMTProxyIntermediate,
    )

    [REDACTED] or "").strip().lower()
    if (not have_slot or key in ("", "server", "direct", "none")) and (
        mt := load_mtproxy()
    ):
        return ConnectionTcpMTProxyIntermediate, mt
    return ConnectionTcpAbridged, proxy_for_slot(egress, have_slot=have_slot)


def proxy_for_slot(egress: str, *, have_slot: bool) -> tuple | None:
    """Прокси слота. current/bought без строки — ошибка, не тихий прямой выход."""
    [REDACTED] or "").strip().lower()
    if not have_slot or not [REDACTED] load_proxy()
    proxy = load_proxy_for(key)
    if key in ("current", "bought") and proxy is None:
        filename = "proxy_current.txt" if [REDACTED] "current" else "proxy_bought.txt"
        raise EgressProxyMissing(
            f"Выход «{key}» без прокси не открываю: аккаунт сел бы на IP сервера "
            f"и слетел бы, когда прокси появится. Впишите host:port в data/{filename}."
        )
    return proxy
