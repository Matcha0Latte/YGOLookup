-- Migration 001 — canonical card database.
--
-- Design rules:
--   * `card.card_id` is an INTERNAL, system-owned key. No external id is ever
--     used as the permanent primary key.
--   * Every external identifier lives in `external_id`.
--   * The unmodified upstream record is preserved in `raw_card_record` so any
--     import can be re-parsed or audited without hitting the network again.

-- The runner creates this table before executing any migration, hence IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- raw source
CREATE TABLE raw_source (
    source_id      INTEGER PRIMARY KEY,
    source_name    TEXT NOT NULL,         -- 'ygopro_cdb' | 'ygoprodeck_json'
    source_version TEXT,                  -- dump date / release tag
    uri            TEXT,
    file_path      TEXT,
    content_sha256 TEXT,
    payload_bytes  INTEGER,
    record_count   INTEGER,
    fetched_at     TEXT NOT NULL,
    notes          TEXT,
    UNIQUE (source_name, content_sha256)
);

-- One row per upstream record, byte-preserved for re-parsing / debugging.
CREATE TABLE raw_card_record (
    raw_id         INTEGER PRIMARY KEY,
    source_id      INTEGER NOT NULL REFERENCES raw_source(source_id) ON DELETE CASCADE,
    card_id        INTEGER REFERENCES card(card_id) ON DELETE SET NULL,
    external_id    TEXT,
    payload_sha256 TEXT NOT NULL,
    payload_json   TEXT NOT NULL
);
CREATE INDEX idx_raw_card_record_card ON raw_card_record(card_id);
CREATE INDEX idx_raw_card_record_src  ON raw_card_record(source_id, external_id);

-- --------------------------------------------------------------------- card
CREATE TABLE card (
    card_id         INTEGER PRIMARY KEY,

    canonical_name  TEXT    NOT NULL,
    card_category   TEXT    NOT NULL,   -- MONSTER | SPELL | TRAP
    sub_category    TEXT,               -- NORMAL | EFFECT | FUSION | RITUAL |
                                        -- SYNCHRO | XYZ | LINK | PENDULUM |
                                        -- QUICK_PLAY | CONTINUOUS | EQUIP |
                                        -- FIELD | COUNTER | TOKEN | SKILL ...

    -- Monster-only attributes. NULL is meaningful: it means "not applicable",
    -- which is different from "unknown" — see docs/schema.md.
    race            TEXT,               -- DRAGON, SPELLCASTER, ...
    attribute       TEXT,               -- DARK, LIGHT, ...
    level_rank      INTEGER,            -- level, or rank for XYZ monsters
    link_rating     INTEGER,
    pendulum_scale  INTEGER,
    atk             INTEGER,            -- raw upstream value; -1 == '?'
    def             INTEGER,

    -- Raw upstream bitmasks are kept verbatim for traceability.
    type_mask       INTEGER,
    race_mask       INTEGER,
    attribute_mask  INTEGER,
    category_mask   INTEGER,
    setcode_mask    INTEGER,

    alias_passcode  INTEGER,            -- upstream 'alias' field, unresolved

    text_lang       TEXT NOT NULL DEFAULT 'en',
    raw_text        TEXT NOT NULL DEFAULT '',

    primary_source_id INTEGER REFERENCES raw_source(source_id),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX idx_card_category  ON card(card_category);
CREATE INDEX idx_card_race      ON card(race);
CREATE INDEX idx_card_attribute ON card(attribute);
CREATE INDEX idx_card_level     ON card(level_rank);
CREATE INDEX idx_card_name      ON card(canonical_name);

-- Names, localized names and informal aliases.
CREATE TABLE card_name (
    card_id    INTEGER NOT NULL REFERENCES card(card_id) ON DELETE CASCADE,
    lang       TEXT NOT NULL,            -- 'en' | 'ja' | 'zh' | ...
    name       TEXT NOT NULL,
    name_kind  TEXT NOT NULL DEFAULT 'official',  -- official | localized | alias
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (card_id, lang, name_kind, name)
);
CREATE INDEX idx_card_name_name ON card_name(name COLLATE NOCASE);

-- ------------------------------------------------------------ external ids
CREATE TABLE external_id (
    card_id     INTEGER NOT NULL REFERENCES card(card_id) ON DELETE CASCADE,
    source      TEXT NOT NULL,           -- ygopro_passcode | ygoprodeck_id | konami_cid
    external_id TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);
CREATE INDEX idx_external_id_card ON external_id(card_id, source);

-- -------------------------------------------------------------- archetypes
CREATE TABLE card_archetype (
    card_id       INTEGER NOT NULL REFERENCES card(card_id) ON DELETE CASCADE,
    archetype     TEXT NOT NULL,         -- normalized slug, e.g. 'blue-eyes'
    archetype_raw TEXT,                  -- upstream setcode value, verbatim
    PRIMARY KEY (card_id, archetype)
);
CREATE INDEX idx_card_archetype ON card_archetype(archetype);

-- ------------------------------------------------------------------- flags
-- Normalized boolean-ish labels: TUNER, PENDULUM, TOON, SPIRIT, UNION,
-- GEMINI, FLIP, TRAP_MONSTER, ... Keeps queries free of bitmask arithmetic.
CREATE TABLE card_flag (
    card_id INTEGER NOT NULL REFERENCES card(card_id) ON DELETE CASCADE,
    flag    TEXT NOT NULL,
    PRIMARY KEY (card_id, flag)
);
CREATE INDEX idx_card_flag ON card_flag(flag);
