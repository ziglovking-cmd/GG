"""Минимальный LLM + failover. Understand: groq → mistral-small → ministral → gemini.

Groq (GROQ_API_KEY) идёт первым, если ключ задан и GROQ_FIRST не 0.
Модель по умолчанию — та, что проверялась в new-materials/home24_script_groq_audit.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

logger = logging.getLogger("home24.llm")

_DEAD: dict[str, float] = {}
_DEAD_TTL_HARD = 30 * 60
_DEAD_TTL_SOFT = 45  # 503 busy — коротко
_DEAD_TTL_RATE = 10 * 60  # 429 rate-limit — 10 мин (mistral-small иначе только тормозит)
# Groq free: лимит токенов в минуту (~8000 TPM) — окно короткое, ждём минуту, не 10
_DEAD_TTL_RATE_GROQ = 60

GROQ_BASE_DEFAULT = "https://api.groq.com/openai/v1"
GROQ_MODEL_DEFAULT = "qwen/qwen3.8-27b"


@dataclass(frozen=True)
class Provider:
    name: str
    api_key: str
    base_url: str
    model: str

    @property
    def ready(self) -> bool:
        return bool(self.api_key.strip() and self.base_url.strip() and self.model.strip())

    @property
    def key(self) -> str:
        return f"{self.name}:{self.model}"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def load_providers(*, role: str = "edge") -> list[Provider]:
    """
    role=edge — дешёвый fallback.
    role=understand — v9 smart: mistral-small → ministral-8b → gemini-lite.
    """
    gemini_smart = _env("AI2_MODEL_SMART") or "gemini-3.5-flash-lite"
    gemini_edge = _env("AI2_MODEL") or "gemini-flash-lite-latest"
    mistral_smart = _env("AI1_MODEL_SMART") or "mistral-small-latest"
    mistral_edge = _env("AI1_MODEL") or _env("OPENAI_MODEL", "ministral-8b-latest")

    ai1_key = _env("AI1_API_KEY") or _env("OPENAI_API_KEY")
    ai1_base = _env("AI1_BASE_URL") or _env("OPENAI_BASE_URL", "https://api.mistral.ai/v1")
    ai2_key = _env("AI2_API_KEY")
    ai2_base = _env(
        "AI2_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai",
    )

    groq: list[Provider] = []
    groq_key = _env("GROQ_API_KEY")
    if groq_key:
        groq_model = (
            _env("GROQ_MODEL_SMART") if role == "understand" else _env("GROQ_MODEL_EDGE")
        ) or _env("GROQ_MODEL") or GROQ_MODEL_DEFAULT
        groq.append(
            Provider(
                name=_env("GROQ_NAME", "groq"),
                api_key=groq_key,
                base_url=_env("GROQ_BASE_URL", GROQ_BASE_DEFAULT),
                model=groq_model,
            )
        )
    groq_first = _env("GROQ_FIRST", "1").lower() not in ("0", "false", "no", "off")

    if role == "understand":
        # порядок: stronger mistral → cheap mistral → gemini (rate-limit friendly)
        raw = [
            Provider(
                name=_env("AI1_NAME", "mini") + "-smart",
                api_key=ai1_key,
                base_url=ai1_base,
                model=mistral_smart,
            ),
            Provider(
                name=_env("AI1_NAME", "mini"),
                api_key=ai1_key,
                base_url=ai1_base,
                model=mistral_edge,
            ),
            Provider(
                name=_env("AI2_NAME", "flash") + "-smart",
                api_key=ai2_key,
                base_url=ai2_base,
                model=gemini_smart,
            ),
            Provider(
                name=_env("AI2_NAME", "flash"),
                api_key=ai2_key,
                base_url=ai2_base,
                model=gemini_edge,
            ),
            Provider(
                name=_env("AI3_NAME", "backup"),
                api_key=_env("AI3_API_KEY"),
                base_url=_env("AI3_BASE_URL", ""),
                model=_env("AI3_MODEL", ""),
            ),
        ]
    else:
        raw = [
            Provider(
                name=_env("AI1_NAME", "mini"),
                api_key=ai1_key,
                base_url=ai1_base,
                model=mistral_edge,
            ),
            Provider(
                name=_env("AI2_NAME", "flash"),
                api_key=ai2_key,
                base_url=ai2_base,
                model=gemini_edge,
            ),
            Provider(
                name=_env("AI3_NAME", "backup"),
                api_key=_env("AI3_API_KEY"),
                base_url=_env("AI3_BASE_URL", ""),
                model=_env("AI3_MODEL", ""),
            ),
        ]
    raw = [*groq, *raw] if groq_first else [*raw, *groq]
    now = time.time()
    out: list[Provider] = []
    seen: set[str] = set()
    for p in raw:
        if not p.ready or p.key in seen:
            continue
        seen.add(p.key)
        until = _DEAD.get(p.key, 0)
        if until > now:
            logger.info("LLM skip dead %s until +%.0fs", p.key, until - now)
            continue
        out.append(p)
    logger.info(
        "LLM providers role=%s: %s",
        role,
        ", ".join(f"{p.name}:{p.model}" for p in out) or "none",
    )
    return out


def _is_groq(p: Provider) -> bool:
    return "groq.com" in p.base_url or p.name.lower().startswith("groq")


_THINK_RE = re.compile(r"(?is)<think>.*?</think>\s*")


def _strip_reasoning(content: str) -> str:
    """Qwen3 на Groq может вернуть <think>…</think> перед JSON — гостю это не нужно."""
    out = _THINK_RE.sub("", content or "")
    if "<think>" in out and "{" in out:  # обрезанный think без закрытия
        out = out[out.find("{", out.find("<think>")) :]
    return out.strip()


def _mark_dead(
    p: Provider,
    reason: str,
    *,
    soft: bool = False,
    rate_limit: bool = False,
) -> None:
    if rate_limit:
        ttl = _DEAD_TTL_RATE_GROQ if _is_groq(p) else _DEAD_TTL_RATE
    elif soft:
        ttl = _DEAD_TTL_SOFT
    else:
        ttl = _DEAD_TTL_HARD
    _DEAD[p.key] = time.time() + ttl
    logger.warning("LLM mark dead %s (%s) for %ss", p.key, reason, ttl)


def _is_quota_lock(err: Exception) -> bool:
    msg = str(err).lower()
    return any(
        x in msg
        for x in (
            "insufficient_quota",
            "model_requires_purchase",
            "credit",
            "billing",
            "payment required",
        )
    )


def _is_rate_limit_err(err: Exception) -> bool:
    msg = str(err).lower()
    return any(x in msg for x in ("429", "rate_limit", "rate limit", "rate_limited"))


def _is_rate_or_busy(err: Exception) -> bool:
    msg = str(err).lower()
    return _is_rate_limit_err(err) or any(
        x in msg
        for x in (
            "503",
            "high demand",
            "unavailable",
            "resource_exhausted",
            "overloaded",
        )
    )


async def chat_completion(
    providers: list[Provider],
    *,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 120,
    temperature: float = 0.2,
    json_mode: bool = True,
    timeout: float | None = None,
) -> tuple[str, str] | None:
    if not providers:
        return None
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.error("openai package missing")
        return None

    payload_msgs = [{"role": "system", "content": system}, *messages]
    last_err: Exception | None = None
    to = float(timeout) if timeout is not None else 7.0

    for p in providers:
        client = AsyncOpenAI(
            api_key=p.api_key, base_url=p.base_url, timeout=to, max_retries=0
        )
        use_json = (
            json_mode
            and "googleapis.com" not in p.base_url
            and "gemini" not in p.name.lower()
        )
        kwargs: dict[str, Any] = {
            "model": p.model,
            "messages": payload_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if use_json:
            kwargs["response_format"] = {"type": "json_object"}
        if _is_groq(p):
            rf = _env("GROQ_REASONING_FORMAT")  # hidden | parsed | raw; пусто — не передаём
            if rf:
                kwargs["extra_body"] = {"reasoning_format": rf}

        attempts = 2  # один retry с backoff
        for attempt in range(attempts):
            try:
                resp = await client.chat.completions.create(**kwargs)
                content = _strip_reasoning(resp.choices[0].message.content or "")
                if not content:
                    logger.warning("LLM %s empty content", p.name)
                    break
                stripped = content.strip().strip("`").strip()
                if stripped.lower() in ("json", "{", "{}", "") or (
                    content.startswith("```") and len(content) < 40
                ):
                    logger.warning("LLM %s truncated junk: %r", p.name, content[:60])
                    break
                if "{" in content:
                    try:
                        import json as _json

                        raw = content
                        if raw.startswith("```"):
                            raw = raw.strip("`")
                            if raw.lower().startswith("json"):
                                raw = raw[4:]
                        _json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
                    except Exception:
                        logger.warning(
                            "LLM %s bad/truncated json: %r", p.name, content[:80]
                        )
                        break
                logger.info("LLM ok via %s/%s", p.name, p.model)
                return content, f"{p.name}/{p.model}"
            except Exception as e1:
                last_err = e1
                if _is_quota_lock(e1):
                    _mark_dead(p, "quota/lock", soft=False)
                    break
                # 429: сразу следующий провайдер, cooldown 10 мин (не жечь latency)
                if _is_rate_limit_err(e1):
                    _mark_dead(p, "429 rate-limit", rate_limit=True)
                    logger.warning(
                        "LLM %s 429 → skip %.0fs, next provider", p.name, _DEAD_TTL_RATE
                    )
                    break
                if _is_rate_or_busy(e1) and attempt + 1 < attempts:
                    delay = 2.0 * (attempt + 1)
                    logger.warning(
                        "LLM %s busy, retry in %.1fs: %s", p.name, delay, e1
                    )
                    await asyncio.sleep(delay)
                    continue
                if _is_rate_or_busy(e1):
                    _mark_dead(p, "busy/503", soft=True)
                if use_json and ("response_format" in str(e1).lower() or "400" in str(e1)):
                    try:
                        kwargs.pop("response_format", None)
                        resp = await client.chat.completions.create(**kwargs)
                        content = _strip_reasoning(resp.choices[0].message.content or "")
                        if content:
                            logger.info(
                                "LLM ok via %s/%s (no json_mode)", p.name, p.model
                            )
                            return content, f"{p.name}/{p.model}"
                    except Exception as e2:
                        last_err = e2
                        if _is_quota_lock(e2):
                            _mark_dead(p, "quota/lock", soft=False)
                        elif _is_rate_limit_err(e2):
                            _mark_dead(p, "429 rate-limit", rate_limit=True)
                        elif _is_rate_or_busy(e2):
                            _mark_dead(p, "busy/503", soft=True)
                        logger.warning("LLM fail %s: %s", p.name, e2)
                else:
                    logger.warning("LLM fail %s: %s", p.name, e1)
                break

    if last_err:
        logger.error("all LLM providers failed: %s", last_err)
    return None
