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

## Effect Schema

Added in Phase 2 (migration `002_effect.sql`), documented here once landed.

| Table | Purpose |
| --- | --- |
| `effect` | one card → many effects, with `raw_text` preserved |
| `effect_predicate` | structured action / source / target / cost predicates |

All extracted values carry a tri-state (`TRUE` / `FALSE` / `UNKNOWN`) so that
"the parser did not understand this" is never mistaken for "the card does not
do this".
