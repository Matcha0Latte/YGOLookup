# Query DSL

Natural language is never turned directly into SQL. It becomes a **Query AST**,
and a retrieval backend compiles that AST into whatever it needs (SQL, FTS5
MATCH, a vector query). This keeps the planner independent of storage.

The AST is plain JSON: serializable, diffable, and usable directly as test
fixtures.

---

## Top level

```json
{
  "select": "card",
  "limit": 50,
  "offset": 0,
  "min_confidence": 0.0,
  "where": { ...condition... }
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `select` | string | only `"card"` today |
| `limit` / `offset` | int | paging |
| `min_confidence` | float | reserved for filtering weakly-parsed predicates |
| `where` | condition \| omitted | omitted = match everything |

---

## Conditions

Three node types, freely nestable.

### Field condition

```json
{ "field": "card.race", "op": "eq", "value": "DRAGON" }
```

| Operator | Meaning |
| --- | --- |
| `eq` / `ne` | equal / not equal. `ne` also matches UNKNOWN (NULL). |
| `in` / `nin` | value must be a non-empty list. `nin` also matches UNKNOWN. |
| `lt` `lte` `gt` `gte` | numeric comparison |
| `contains` | case-insensitive substring (text fields only) |

### Boolean condition

```json
{ "and": [ ... ] }
{ "or":  [ ... ] }
{ "not": { ... } }
```

`and` / `or` take a non-empty list; `not` takes a single condition.

### Exists condition

```json
{
  "exists": "effect",
  "where": { "and": [ ...predicate conditions... ] }
}
```

Means: *the card has at least one effect whose predicates satisfy this*. This is
how effect-level and card-level constraints are combined, and how COST is kept
distinct from RESOLUTION.

---

## Fields

Field names are validated against a registry (`query/fields.py`). Unknown names
are rejected — nothing is interpolated into SQL.

### `card.*`

| Field | Type | Notes |
| --- | --- | --- |
| `card.card_id` | int | |
| `card.canonical_name` | text | |
| `card.card_category` | enum | `MONSTER` `SPELL` `TRAP` |
| `card.sub_category` | enum | `NORMAL` `EFFECT` `FUSION` `RITUAL` `SYNCHRO` `XYZ` `LINK` `PENDULUM` `QUICK_PLAY` `CONTINUOUS` `EQUIP` `FIELD` `COUNTER` `TRAP_MONSTER` `TOKEN` `SKILL` `MAXIMUM` `ARMOR` |
| `card.race` | enum | `DRAGON` `SPELLCASTER` … (upper snake case) |
| `card.attribute` | enum | `EARTH` `WATER` `FIRE` `WIND` `LIGHT` `DARK` `DIVINE` |
| `card.level_rank` | int | level, or rank for XYZ |
| `card.link_rating` | int | |
| `card.pendulum_scale` | int | |
| `card.atk` / `card.def` | int | `-1` means a printed `?` |
| `card.archetype` | text | joined table, matched on the normalized slug |
| `card.flag` | enum | `TUNER` `PENDULUM` `TOON` `SPIRIT` `UNION` `GEMINI` `FLIP` `TRAP_MONSTER` `ARMOR` `MAXIMUM` |
| `card.name` | text | any name/alias row; `contains` does a LIKE |

### `effect.*` (must be inside an `exists` block)

| Field | Type | Notes |
| --- | --- | --- |
| `effect.part` | enum | `CONDITION` `COST` `RESOLUTION` `RESTRICTION` |
| `effect.action` | enum | see below |
| `effect.source_zone` | enum | `DECK` `EXTRA_DECK` `HAND` `GRAVEYARD` `BANISHED` `FIELD` `MONSTER_ZONE` `SPELL_TRAP_ZONE` `PENDULUM_ZONE` `ANYWHERE` |
| `effect.destination_zone` | enum | same vocabulary |
| `effect.target_race` | enum | |
| `effect.target_attribute` | enum | |
| `effect.target_card_category` | enum | `MONSTER` `SPELL` `TRAP` `SPELL_TRAP` |
| `effect.target_archetype` / `effect.target_name` | text | |
| `effect.target_level` | int (virtual) | comparison only |
| `effect.target_atk` | int (virtual) | comparison only |
| `effect.target_rank` / `effect.target_link_rating` / `effect.target_count` | int | |
| `effect.target_tuner` | tri | `TRUE` `FALSE` `UNKNOWN` |
| `effect.once_per_turn` | tri | `TRUE` `FALSE` `UNKNOWN` |
| `effect.confidence` | number | parser confidence |

**Virtual range fields.** "Level 4 or lower" is stored as `target_level_max = 4`;
an exact "Level 4" as `min = max = 4`. `effect.target_level` with `lte` therefore
compiles to `(min <= ? OR max <= ?)` so both spellings are found. These fields
support comparison operators only.

**`SPELL_TRAP` asymmetry.** A predicate stored as `SPELL_TRAP` ("Target 1
Spell/Trap") is matched by a query for `SPELL` or for `TRAP`, but a query for
`SPELL_TRAP` requires the combined token.

**Action vocabulary:** `SPECIAL_SUMMON` `NORMAL_SUMMON` `TRIBUTE_SUMMON`
`ADD_TO_HAND` `SEARCH` `DRAW` `SEND_TO_GRAVEYARD` `BANISH` `DESTROY` `NEGATE`
`RETURN_TO_HAND` `RETURN_TO_DECK` `TRIBUTE` `DISCARD` `MILL` `CHANGE_POSITION`
`INCREASE_ATK` `DECREASE_ATK` `EXCAVATE` `REVEAL` `ATTACH` `DETACH`
`GAIN_CONTROL` `COPY_EFFECT` `EQUIP` `SET_CARD` `PREVENT_DESTRUCTION`
`PREVENT_ACTIVATION` `CHANGE_NAME` `SHUFFLE`

---

## Examples

### 4 星以下暗属性恶魔族怪兽

```json
{
  "select": "card",
  "limit": 50,
  "where": {
    "and": [
      { "field": "card.race", "op": "eq", "value": "FIEND" },
      { "field": "card.attribute", "op": "eq", "value": "DARK" },
      { "field": "card.level_rank", "op": "lte", "value": 4 }
    ]
  }
}
```

### 从额外卡组特殊召唤龙族怪兽

```json
{
  "where": {
    "exists": "effect",
    "where": {
      "and": [
        { "field": "effect.part", "op": "eq", "value": "RESOLUTION" },
        { "field": "effect.action", "op": "eq", "value": "SPECIAL_SUMMON" },
        { "field": "effect.source_zone", "op": "eq", "value": "EXTRA_DECK" },
        { "field": "effect.target_race", "op": "eq", "value": "DRAGON" }
      ]
    }
  }
}
```

### 以除外墓地怪兽为 COST 特殊召唤

```json
{
  "where": {
    "and": [
      {
        "exists": "effect",
        "where": {
          "and": [
            { "field": "effect.part", "op": "eq", "value": "COST" },
            { "field": "effect.action", "op": "eq", "value": "BANISH" },
            { "field": "effect.source_zone", "op": "eq", "value": "GRAVEYARD" }
          ]
        }
      },
      {
        "exists": "effect",
        "where": { "field": "effect.action", "op": "eq", "value": "SPECIAL_SUMMON" }
      }
    ]
  }
}
```

### 既不是龙族也不是魔法师族

```json
{ "where": { "not": { "or": [
  { "field": "card.race", "op": "eq", "value": "DRAGON" },
  { "field": "card.race", "op": "eq", "value": "SPELLCASTER" }
] } } }
```

---

## CLI usage

```bash
# compact filter syntax (bare names default to card.*, effect.* is auto-wrapped)
python -m ygolookup.cli search --filter race=DRAGON --filter "level<=4"
python -m ygolookup.cli search --filter effect.action=SPECIAL_SUMMON \
                               --filter effect.source_zone=EXTRA_DECK

# rule-based natural language planner
python -m ygolookup.cli search --nl "找能够从额外卡组特殊召唤龙族怪兽的卡"

# full AST from a file
python -m ygolookup.cli search --query-file query.json --explain
```

Aliases in the compact syntax: `level`/`rank` → `card.level_rank`,
`type` → `card.card_category`, `effect.race` → `effect.target_race`,
`effect.level` → `effect.target_level`.

---

## Planner

`query/planner.py` is a **deterministic placeholder** for the LLM planner. It
recognizes a fixed Chinese + English vocabulary of races, attributes, actions and
zones, and returns `{query, matched, unmatched}`.

`unmatched` matters: when the planner cannot map part of the question, the
caller should fall back to FTS or semantic retrieval rather than silently
dropping the intent. The LLM planner planned for a later phase returns the
same `Query` object, so nothing downstream changes.
