#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка RAG: что подтянется под реплику гостя (офлайн, без LLM).

Пример:
  PYTHONPATH=. python scripts/rag_probe.py "какой залог?"
  PYTHONPATH=. python scripts/rag_probe.py "Чехов какое метро?" --favorite Чехов
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.rag import clear_rag_cache, index_stats, rag_context_for_llm, retrieve  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Home24 RAG probe")
    p.add_argument("query", help="реплика гостя")
    p.add_argument("--district", default="")
    p.add_argument("--favorite", default="")
    p.add_argument("--k", type=int, default=6)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    clear_rag_cache()
    stats = index_stats()
    hits = retrieve(
        args.query,
        k=args.k,
        district=args.district or None,
        favorite=args.favorite or None,
    )
    block = rag_context_for_llm(
        args.query,
        district=args.district or None,
        favorite=args.favorite or None,
        k=args.k,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "stats": stats,
                    "hits": [
                        {
                            "id": h.chunk_id,
                            "source": h.source,
                            "title": h.title,
                            "text": h.text,
                        }
                        for h in hits
                    ],
                    "block": block,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(f"index: {stats['total']} chunks · {stats['by_source']}")
    print(f"query: {args.query!r}")
    if not hits:
        print("(пусто)")
    for i, h in enumerate(hits, 1):
        print(f"{i}. [{h.source}] {h.text}")
    print("\n--- system block ---\n")
    print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
