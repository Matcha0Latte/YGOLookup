# Schema

SQLite is the source of truth. This document is the contract for every layer
above it — if a field is not documented here, no layer may assume it exists.

## Conventions

| Convention | Meaning |
| --- | --- |
| `card_id` | Internal, system-owned key. **Never** an external id. |
| `NULL` | "Not applicable" for this card (e.g. `race` on a Spell). |
| Sentinel `-1` | Upstream value meaning a printed `?` ATK/DEF. Kept verbatim, never coerced to 0. |
| `*_mask` | Raw upstream bitfield, preserved so any import can be re-derived. |
| `UNKNOWN` | Reserved for effect-layer extraction (see [Effect Schema](#effect-schema)) — never for card fields. |

---

## `raw_source`

One row per upstream snapshot. Lets any import be reproduced offline.

| Column | Type | Notes |
| --- | --- | --- |
| `source_id` | INTEGER PK | |
| `source_name` | TEXT | `ygopro_cdb` \| `ygoprodeck_json` |
| `source_version` | TEXT | dump date or file mtime |
| `uri` / `file_path` | TEXT | where the payload came from |
| `content_sha256` | TEXT | NULL for on-disk cdb imports |
| `payload_bytes` / `record_count` | INTEGER | |
| `fetched_at` | TEXT | local ISO-8601 |

`UNIQUE (source_name, content_sha256)` makes re-importing the same payload a
no-op at the source level.

## `raw_card_record`

Byte-preserved upstream record, one per card per source.

| Column | Notes |
| --- | --- |
| `raw_id` | PK |
| `source_id` | FK → `raw_source` |
| `card_id` | FK → `card`, set after upsert |
| `external_id` | upstream id, for debugging |
| `payload_sha256` / `payload_json` | normalized record as JSON |

This is what makes "re-parse without hitting the network" possible.

## `card`

| Column | Notes |
| --- | --- |
| `card_id` | internal PK |
| `canonical_name` | display name of the primary language |
| `card_category` | `MONSTER` \| `SPELL` \| `TRAP` |
| `sub_category` | `NORMAL` `EFFECT` `FUSION` `RITUAL` `SYNCHRO` `XYZ` `LINK` `PENDULUM` `QUICK_PLAY` `CONTINUOUS` `EQUIP` `FIELD` `COUNTER` `TRAP_MONSTER` `TOKEN` `SKILL` `MAXIMUM` `ARMOR` |
| `race` | `DRAGON`, `WINGED_BEAST`, `SEA_SERPENT`, … NULL for non-monsters |
| `attribute` | `EARTH` `WATER` `FIRE` `WIND` `LIGHT` `DARK` `DIVINE` |
| `level_rank` | level, or rank for XYZ |
| `link_rating` | Link Rating; NULL unless LINK |
| `pendulum_scale` | NULL unless PENDULUM |
| `atk` / `def` | raw upstream value, `-1` == `?` |
| `type_mask` etc. | upstream bitfields, verbatim |
| `alias_passcode` | upstream `alias`; **not** auto-merged (see [Aliases](#aliases)) |
| `text_lang` / `raw_text` | original effect text — always kept, never overwritten by derived data |
| `primary_source_id` | FK → `raw_source` |
| `created_at` / `updated_at` | local ISO-8601 |

## `card_name`

`(card_id, lang, name_kind, name)` PK.

- `name_kind`: `official` \| `localized` \| `alias`
- `is_primary`: 1 for the name used as `canonical_name`

## `external_id`

`(source, external_id)` PK — this is the only place external identifiers live.

| `source` | Meaning |
| --- | --- |
| `ygopro_passcode` | the 8-digit passcode used by YGOPro/EDOPro |
| `ygoprodeck_id` | YGOProDeck numeric id |
| `konami_cid` | reserved for the official OCG/TCG card id |

## `card_archetype`

`(card_id, archetype)` PK.

- `archetype`: normalized slug (`blue-eyes`)
- `archetype_raw`: upstream value. For `cards.cdb` this is the 16-bit setcode in
  hex, because the raw database has no archetype names.

## `card_flag`

`(card_id, flag)` PK. Normalized boolean labels decoded from the type bitmask:
`TUNER` `PENDULUM` `TOON` `SPIRIT` `UNION` `GEMINI` `FLIP` `TRAP_MONSTER`
`ARMOR` `MAXIMUM`. Keeps queries free of bit arithmetic.

## Aliases

Upstream `alias` marks an alternate artwork of an existing card. It is stored in
`card.alias_passcode` but **never merged automatically**: merging is a curation
decision, and a wrong upstream value would silently destroy a card. Use
`id_mapping.alias_report()` to review candidates.

---

## `effect`

One card → many effects. `raw_text` is always kept, so every structured claim
can be verified against the original wording.

| Column | Notes |
| --- | --- |
| `effect_id` | PK |
| `card_id` | FK → `card`, `ON DELETE CASCADE` |
| `effect_index` | order within the card; `UNIQUE (card_id, effect_index)` |
| `scope` | `MAIN` \| `PENDULUM` \| `MONSTER` |
| `marker` | how the splitter found it: `BLOCK` `BULLET` `LINE` `SENTENCE` `MATERIAL` |
| `raw_text` | the exact text slice |
| `text_sha256` | dedup / change detection |
| `parser_version` | which parser produced the predicates |

`marker = MATERIAL` marks summoning-material lines ("2 Level 4 monsters").
They are stored — the text is part of the card — but produce no predicates,
because a material requirement is not an effect.

## `effect_predicate`

One atomic claim about one part of one effect.

| Column | Notes |
| --- | --- |
| `part` | `CONDITION` \| `COST` \| `RESOLUTION` \| `RESTRICTION` |
| `action` | from the `Action` vocabulary; **NULL means UNKNOWN** |
| `action_known` | 0 = UNKNOWN, 1 = determined. Never infer FALSE from NULL. |
| `source_zone` / `destination_zone` | from the `Zone` vocabulary |
| `target_*` | denormalized target columns, purely for indexed SQL filtering |
| `target_tuner` | `TRUE` / `FALSE` / `UNKNOWN` |
| `once_per_turn` | `TRUE` / `FALSE` / `UNKNOWN` |
| `confidence` | 0–1 heuristic: how much of the clause was understood |
| `evidence` | the text span the parser matched |
| `payload_json` | the full structured object — this is the truth, the columns are a mirror |

### Three-valued semantics

| State | Meaning | SQL representation |
| --- | --- | --- |
| `TRUE` | explicitly present | `target_tuner = 'TRUE'` |
| `FALSE` | explicitly negated ("non-Tuner") | `target_tuner = 'FALSE'` |
| `UNKNOWN` | parser did not determine it | `target_tuner = 'UNKNOWN'` / `action IS NULL` |

`UNKNOWN` must never be treated as `FALSE`. A parser failure is not a claim
about the card.

### Vocabularies

`Action`: `SPECIAL_SUMMON` `NORMAL_SUMMON` `TRIBUTE_SUMMON` `ADD_TO_HAND`
`SEARCH` `DRAW` `SEND_TO_GRAVEYARD` `BANISH` `DESTROY` `NEGATE`
`RETURN_TO_HAND` `RETURN_TO_DECK` `TRIBUTE` `DISCARD` `MILL`
`CHANGE_POSITION` `INCREASE_ATK` `DECREASE_ATK` `EXCAVATE` `REVEAL` `ATTACH`
`DETACH` `GAIN_CONTROL` `COPY_EFFECT` `EQUIP` `SET_CARD`
`PREVENT_DESTRUCTION` `PREVENT_ACTIVATION` `CHANGE_NAME` `SHUFFLE`

`Zone`: `DECK` `EXTRA_DECK` `HAND` `GRAVEYARD` `BANISHED` `FIELD`
`MONSTER_ZONE` `SPELL_TRAP_ZONE` `PENDULUM_ZONE` `ANYWHERE`

`SEARCH` is the more specific form of `ADD_TO_HAND`: it is emitted when the
source is the Deck and the destination is the hand.

`target_card_category` may be `SPELL_TRAP`, which query translation expands to
`SPELL OR TRAP`.
