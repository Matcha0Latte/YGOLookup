# Architecture

## Layers

```
Natural language
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│ Agent / orchestrator                                     │
│   agent/tools.py — get_card, search_cards,               │
│                    search_effects, plan_query, …          │
│   (no DB business logic; JSON in, JSON out)              │
└──────────────────────────────────────────────────────────┘
      │  Query AST
      ▼
┌──────────────────────────────────────────────────────────┐
│ query/                                                   │
│   planner.py  NL -> Query AST (rule-based placeholder)   │
│   parser.py   "race=DRAGON" -> Query AST                 │
│   dsl.py      the AST itself (JSON, storage-agnostic)    │
│   fields.py   field registry + enum validation           │
└──────────────────────────────────────────────────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│ retrieval/                                               │
│   structured/  compiler.py (AST -> SQL) + search.py      │
│   fulltext/    FTS5            (planned)                 │
│   semantic/    effect embeddings (planned, optional)     │
│   hybrid/      merge + rerank  (planned)                 │
└──────────────────────────────────────────────────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│ db/  SQLite — the source of truth                        │
│   migrations/  001_canonical_card.sql, 002_effect.sql    │
│   repository.py  the only writer of canonical card rows  │
└──────────────────────────────────────────────────────────┘
      ▲
      │
┌──────────────────────────────────────────────────────────┐
│ ingest/   upstream data -> normalized records            │
│   ygopro/cdb_reader.py     native cards.cdb              │
│   ygopro/ygoprodeck.py     JSON dump                     │
│   normalize.py             upstream -> CardRecord        │
│   id_mapping.py            identity keys                 │
│   pipeline.py              raw snapshot + upsert         │
└──────────────────────────────────────────────────────────┘
```

## Data flow

1. **Ingest** writes an immutable raw snapshot to `data/raw`, registers a
   `raw_source` row, stores each upstream record verbatim in `raw_card_record`,
   then upserts canonical `card` rows. Re-running is idempotent.
2. **Effect build** splits `card.raw_text` into `effect` segments and parses each
   into `effect_predicate` rows. Deterministic and cheap → rebuilding is normal.
3. **Query** arrives as natural language (planner) or a compact filter string
   (parser), and becomes a Query AST.
4. **Structured retrieval** compiles the AST into parameterized SQL and returns
   cards plus the effect text that produced each match.
5. **Verification** happens by reading `effect.raw_text` — the original
   wording — which every hit carries.

## Design decisions

| Decision | Reason |
| --- | --- |
| SQLite is the only fact store | the data is small (≈15k cards) and relational; no need for Postgres/Elasticsearch |
| `card_id` is internal | no external id is stable enough to be a permanent primary key |
| `raw_card_record` keeps the upstream payload | any import can be re-parsed or audited offline |
| One card → many effects, not one blob | "the card has an effect that …" is the actual query shape |
| Indexing granularity is `effect_id` | avoids the "one card = one embedding" trap; a vector hit points at a specific effect |
| `UNKNOWN` is a first-class state | a parser failure must never become "the card does not do this" |
| Query AST between NL and SQL | the same query can be served by structured / FTS / semantic backends |
| Nested `EXISTS`, not a flattened join | measured 68s → 0.1s on the full database |
| Parser is deterministic first | cheap, testable, reproducible; LLM extraction is an add-on, not the base |

## Module boundaries

- `ingest/` never writes SQL directly — it calls `db/repository.py`.
- `retrieval/` is read-only.
- `effects/` knows nothing about SQL; `effects/service.py` is the only bridge.
- `query/` knows nothing about SQL; `retrieval/structured/compiler.py` owns the
  translation.
- `agent/` contains no database logic — tools delegate and return JSON.

## Planned next phases

| Phase | Content |
| --- | --- |
| 4 | FTS5 over card names + effect text, wrapped as `fulltext_search` |
| 5 | Hybrid retrieval: structured ⊕ FTS ⊕ semantic, with merge/rerank |
| 6 | Semantic retrieval keyed on `effect_id`; deterministic fallback when no embedding model is configured |
| 7 | LLM query planner replacing the rule-based one; LLM effect extraction for long clauses |
| 8 | `search_rulings` / FAQ interface (the only part that may go online) |
