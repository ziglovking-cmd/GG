# Home24 v10.21 · 14.11.2026 — RAG grounding

## Зачем

LLM в smart/edge получала либо слепой срез FAQ, либо общий каталог и могла
додумать метро, залог, животных, цены. Нужен retrieval только проверенных фактов.

## Что сделано

- Новый модуль `bot/rag.py`: индекс из FAQ, life-ситуаций, «Короткие факты»,
  карты/адресов/районов `script.md`, каталога (если БД есть) и жёстких policy-чанков.
- Retrieval на TF‑IDF по стемам (без chromadb/embeddings) — тот же стиль, что `bot/examples.py`.
- Подключение в `bot/smart.py` (основной understand) и `bot/ai.py` (edge fallback):
  блок «RAG — проверенные факты» + правило «нет факта → uncertain, не выдумывай».
- `scripts/rag_probe.py` — офлайн проверка retrieval.
- `tests/test_rag.py` — индекс, залог/питомцы/заезд/Арбат/метро, проводка в smart prompt.
- Env: `RAG_OFF`, `RAG_TOP_K`, `RAG_MAX_CHARS` (см. `.env.example`).

## Как проверить

```bash
PYTHONPATH=. python scripts/rag_probe.py "какой залог?"
PYTHONPATH=. python scripts/rag_probe.py "Чехов какое метро?" --favorite Чехов
PYTHONPATH=. python -m pytest tests/test_rag.py -q
```

## Не трогали

PeerFlood / лимиты рассылки, воронку район→даты→гости, TravelLine API.
