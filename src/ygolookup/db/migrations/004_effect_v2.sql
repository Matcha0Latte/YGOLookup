-- Migration 004 — effect schema v2 (Chinese source language).
--
-- Replaces the English-parser schema from 002 with the three-level model:
--
--     EffectUnit  ->  Clause  ->  Predicate
--
-- Differences that matter:
--   * a clause has a ROLE (CONDITION / COST / TARGET / RESOLUTION /
--     RESTRICTION / UNKNOWN); COST and CONDITION are distinct
--   * the object is a CardSelector; numeric conditions are structured
--     comparisons ({op, value}) instead of min/max column pairs
--   * predicates carry result_ref / object_ref for simple anaphora
--   * every value records how it was extracted (rule / grammar / llm) and the
--     Chinese span it came from
--
-- Tri-state rule still holds: NULL action + action_known = 0 means UNKNOWN,
-- never "the card does not do this".

DROP INDEX IF EXISTS idx_pred_effect;
DROP INDEX IF EXISTS idx_pred_part;
DROP INDEX IF EXISTS idx_pred_action;
DROP INDEX IF EXISTS idx_pred_source;
DROP INDEX IF EXISTS idx_pred_dest;
DROP INDEX IF EXISTS idx_pred_race;
DROP INDEX IF EXISTS idx_pred_attr;
DROP INDEX IF EXISTS idx_pred_level;
DROP INDEX IF EXISTS idx_pred_archetype;
DROP TABLE IF EXISTS effect_predicate;
DROP TABLE IF EXISTS effect;

-- ------------------------------------------------------------- effect unit
CREATE TABLE effect_unit (
    unit_id        INTEGER PRIMARY KEY,
    card_id        INTEGER NOT NULL REFERENCES card(card_id) ON DELETE CASCADE,
    unit_index     INTEGER NOT NULL,
    scope          TEXT NOT NULL,      -- MAIN | PENDULUM | MONSTER
    kind           TEXT NOT NULL,      -- NUMBERED | UNNUMBERED | MATERIAL | RESTRICTION
    marker         TEXT,               -- '①' | '②' | … NULL when unnumbered
    sub_index      INTEGER NOT NULL DEFAULT 0,   -- index within a '●' list
    raw_text       TEXT NOT NULL,
    text_sha256    TEXT,
    lang           TEXT NOT NULL DEFAULT 'zh',
    parse_status   TEXT NOT NULL DEFAULT 'UNRESOLVED',  -- OK | PARTIAL | UNRESOLVED
    parser_version TEXT,
    parsed_at      TEXT,
    UNIQUE (card_id, unit_index)
);

CREATE INDEX idx_unit_card   ON effect_unit(card_id);
CREATE INDEX idx_unit_kind   ON effect_unit(kind);
CREATE INDEX idx_unit_scope  ON effect_unit(scope);

-- ---------------------------------------------------------------- clause
CREATE TABLE effect_clause (
    clause_id    INTEGER PRIMARY KEY,
    unit_id      INTEGER NOT NULL REFERENCES effect_unit(unit_id) ON DELETE CASCADE,
    clause_index INTEGER NOT NULL,
    role         TEXT NOT NULL,   -- CONDITION|COST|TARGET|RESOLUTION|RESTRICTION|UNKNOWN
    raw_text     TEXT NOT NULL,
    start_offset INTEGER NOT NULL DEFAULT 0,
    end_offset   INTEGER NOT NULL DEFAULT 0,
    once_per_turn TEXT NOT NULL DEFAULT 'UNKNOWN',
    confidence   REAL NOT NULL DEFAULT 0,
    extracted_by TEXT NOT NULL DEFAULT 'grammar',
    UNIQUE (unit_id, clause_index)
);

CREATE INDEX idx_clause_unit ON effect_clause(unit_id);
CREATE INDEX idx_clause_role ON effect_clause(role);

-- ------------------------------------------------------------- predicate
CREATE TABLE effect_predicate (
    predicate_id INTEGER PRIMARY KEY,
    clause_id    INTEGER NOT NULL REFERENCES effect_clause(clause_id) ON DELETE CASCADE,
    pred_index   INTEGER NOT NULL,

    subject      TEXT NOT NULL DEFAULT 'UNKNOWN',
    action       TEXT,                      -- NULL == UNKNOWN
    action_known INTEGER NOT NULL DEFAULT 0,
    source_zone  TEXT,
    destination_zone TEXT,

    -- Denormalized CardSelector columns so structured search stays one indexed
    -- query. `object_json` is the full truth.
    object_count       INTEGER,
    object_count_op    TEXT,
    object_card_type   TEXT,
    object_race        TEXT,
    object_attribute   TEXT,
    object_archetype   TEXT,
    object_name        TEXT,
    object_level_op    TEXT,
    object_level_value INTEGER,
    object_rank_op     TEXT,
    object_rank_value  INTEGER,
    object_link_op     TEXT,
    object_link_value  INTEGER,
    object_atk_op      TEXT,
    object_atk_value   INTEGER,
    object_def_op      TEXT,
    object_def_value   INTEGER,
    object_tags        TEXT,

    result_ref   TEXT,
    object_ref   TEXT,
    modifiers_json TEXT NOT NULL DEFAULT '{}',

    confidence   REAL NOT NULL DEFAULT 0,
    extracted_by TEXT NOT NULL DEFAULT 'rule',
    source_text  TEXT,                      -- the Chinese span matched
    payload_json TEXT NOT NULL,
    UNIQUE (clause_id, pred_index)
);

CREATE INDEX idx_pred_clause  ON effect_predicate(clause_id);
CREATE INDEX idx_pred_action  ON effect_predicate(action, action_known);
CREATE INDEX idx_pred_source  ON effect_predicate(source_zone);
CREATE INDEX idx_pred_dest    ON effect_predicate(destination_zone);
CREATE INDEX idx_pred_race    ON effect_predicate(object_race);
CREATE INDEX idx_pred_attr    ON effect_predicate(object_attribute);
CREATE INDEX idx_pred_level   ON effect_predicate(object_level_op, object_level_value);
CREATE INDEX idx_pred_atk     ON effect_predicate(object_atk_op, object_atk_value);
CREATE INDEX idx_pred_archetype ON effect_predicate(object_archetype);
