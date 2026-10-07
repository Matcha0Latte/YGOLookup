-- Migration 002 — effect foundation.
--
-- A card is NOT one blob of text: it is split into `effect` segments, and each
-- segment carries structured `effect_predicate` rows.
--
-- Tri-state rule: NULL in an action/zone column means UNKNOWN ("the parser did
-- not determine this"), never FALSE ("the card does not do this").

CREATE TABLE effect (
    effect_id      INTEGER PRIMARY KEY,
    card_id        INTEGER NOT NULL REFERENCES card(card_id) ON DELETE CASCADE,
    effect_index   INTEGER NOT NULL,
    scope          TEXT NOT NULL,             -- MAIN | PENDULUM | MONSTER
    marker         TEXT NOT NULL,             -- BLOCK | BULLET | LINE | SENTENCE
    raw_text       TEXT NOT NULL,
    text_sha256    TEXT NOT NULL,
    parser_version TEXT,
    parsed_at      TEXT,
    UNIQUE (card_id, effect_index)
);

CREATE INDEX idx_effect_card ON effect(card_id);
CREATE INDEX idx_effect_hash ON effect(text_sha256);

CREATE TABLE effect_predicate (
    predicate_id   INTEGER PRIMARY KEY,
    effect_id      INTEGER NOT NULL REFERENCES effect(effect_id) ON DELETE CASCADE,
    part           TEXT NOT NULL,             -- CONDITION | COST | RESOLUTION | RESTRICTION

    action         TEXT,                      -- NULL == UNKNOWN
    action_known   INTEGER NOT NULL DEFAULT 0,   -- 0 = UNKNOWN, 1 = determined
    source_zone    TEXT,
    destination_zone TEXT,

    -- Denormalized target columns: these exist purely so structured search can
    -- stay a single indexed SQL query. `payload_json` is the full truth.
    target_count       INTEGER,
    target_card_category TEXT,
    target_race        TEXT,
    target_attribute   TEXT,
    target_archetype   TEXT,
    target_name        TEXT,
    target_level_min   INTEGER,
    target_level_max   INTEGER,
    target_rank        INTEGER,
    target_link_rating INTEGER,
    target_atk_min     INTEGER,
    target_atk_max     INTEGER,
    target_tuner       TEXT NOT NULL DEFAULT 'UNKNOWN',

    once_per_turn  TEXT NOT NULL DEFAULT 'UNKNOWN',
    confidence     REAL NOT NULL DEFAULT 0,
    evidence       TEXT,
    payload_json   TEXT NOT NULL
);

CREATE INDEX idx_pred_effect   ON effect_predicate(effect_id);
CREATE INDEX idx_pred_part     ON effect_predicate(part);
CREATE INDEX idx_pred_action   ON effect_predicate(action, part);
CREATE INDEX idx_pred_source   ON effect_predicate(source_zone);
CREATE INDEX idx_pred_dest     ON effect_predicate(destination_zone);
CREATE INDEX idx_pred_race     ON effect_predicate(target_race);
CREATE INDEX idx_pred_attr     ON effect_predicate(target_attribute);
CREATE INDEX idx_pred_level    ON effect_predicate(target_level_min, target_level_max);
CREATE INDEX idx_pred_archetype ON effect_predicate(target_archetype);
