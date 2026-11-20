from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
import urllib.error
import urllib.request


def request(token: str, method: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    """Вызывает Bot API без вывода секретного URL или токена в ошибки и логи."""
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.telegram.org/bot%s/%s" % (token, method),
        data=body,
        headers={"User-Agent": "TG-Audience/1.0", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            raise ValueError("Telegram отклонил токен. Скопируйте его заново из BotFather.")
        if e.code == 409 and method == "getUpdates":
            raise ValueError("У бота настроен webhook. Удалите его или используйте другого нового бота.")
        raise ValueError("Telegram временно недоступен (HTTP %d)." % e.code)
    except (urllib.error.URLError, TimeoutError):
        raise ValueError("Не удалось связаться с Telegram. Попробуйте ещё раз через минуту.")
    except Exception:
        raise ValueError("Не удалось выполнить запрос к Telegram-боту.")

    if not response_payload.get("ok"):
        raise ValueError("Telegram не подтвердил запрос к боту.")
    return response_payload.get("result")


def identity(token: str) -> Dict[str, Any]:
    """Проверяет токен через официальный getMe."""
    result = request(token, "getMe") or {}
    if not result.get("username"):
        raise ValueError("Telegram не подтвердил токен бота.")
    return result


def recipient_from_updates(updates: Any) -> Optional[tuple[int, str]]:
    """Находит последнее /start из личного чата, не сохраняя текст сообщений."""
    if not isinstance(updates, list):
        return None
    for update in reversed(updates):
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") or {}
        text = str(message.get("text") or "").strip()
        if chat.get("type") != "private" or not re.match(r"^/start(?:@\w+)?(?:\s|$)", text):
            continue
        try:
            chat_id = int(chat["id"])
        except (KeyError, TypeError, ValueError):
            continue
        name = " ".join(str(chat.get(key) or "").strip()
                        for key in ("first_name", "last_name")).strip()
        username = str(chat.get("username") or "").strip().lstrip("@")
        label = name or ("@" + username if username else "Личный чат Telegram")
        if username and name:
            label += " (@%s)" % username
        return chat_id, label
    return None
