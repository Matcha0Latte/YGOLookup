-- Migration 003 — multi-language card text.
--
-- The effect parser reads Simplified Chinese, so the Chinese text needs a home
-- of its own. `card.raw_text` keeps the English source it was imported with;
-- nothing here overwrites it.

CREATE TABLE card_text (
    card_id     INTEGER NOT NULL REFERENCES card(card_id) ON DELETE CASCADE,
    lang        TEXT NOT NULL,          -- 'zh' | 'en' | 'ja'
    kind        TEXT NOT NULL,          -- 'effect' | 'pendulum' | 'types'
    source      TEXT NOT NULL,          -- 'ygocdb' | 'ygoprodeck' | 'cdb'
    text        TEXT NOT NULL,
    text_sha256 TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (card_id, lang, kind, source)
);

CREATE INDEX idx_card_text_lang ON card_text(lang, kind);
CREATE INDEX idx_card_text_sha  ON card_text(text_sha256);

-- Chinese names. `name_kind` records which upstream column each name came
-- from, because the simplified-Chinese official name is not always available
-- and the community name is the fallback.
--   official  -> sc_name (官方简体中文名称)
--   localized -> md_name (Master Duel 中文名)
--   alias     -> cn_name / nwbbs_n / cnocg_n (社区译名)
--   original  -> jp_name / en_name
