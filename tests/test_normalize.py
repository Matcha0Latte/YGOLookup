import json
from pathlib import Path

import pytest

from ygolookup.ingest.normalize import normalize_cdb_row, normalize_ygoprodeck_record

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = json.loads((FIXTURES / "ygoprodeck_sample.json").read_text(encoding="utf-8"))["data"]

BY_NAME = {c["name"]: c for c in SAMPLE}


def record(name: str):
    return normalize_ygoprodeck_record(BY_NAME[name])


# ------------------------------------------------------------ YGOProDeck source
def test_normal_monster():
    r = record("Blue-Eyes White Dragon")
    assert r.card_category == "MONSTER"
    assert r.sub_category == "NORMAL"
    assert (r.race, r.attribute, r.level_rank) == ("DRAGON", "LIGHT", 8)
    assert (r.atk, r.defense) == (3000, 2500)
    assert r.archetypes == [("blue-eyes", "Blue-Eyes")]


def test_xyz_uses_level_field_as_rank():
    r = record("Number 39: Utopia")
    assert r.sub_category == "XYZ"
    assert r.level_rank == 4
    assert r.link_rating is None


def test_link_monster_has_no_defense():
    r = record("Decode Talker")
    assert r.sub_category == "LINK"
    assert r.link_rating == 3
    assert r.defense is None


def test_pendulum_sets_scale_and_flag():
    r = record("Timegazer Magician")
    assert r.pendulum_scale == 8
    assert "PENDULUM" in r.flags


def test_tuner_flag_from_type_string():
    r = record("Junk Synchron")
    assert "TUNER" in r.flags
    assert r.level_rank == 3


def test_unknown_stat_keeps_upstream_sentinel():
    """ATK/DEF of '?' is -1 upstream. Do NOT invent 0 — that would be a lie."""
    r = record("Exodia Necross")
    assert r.atk == -1
    assert r.defense == -1


def test_spell_sub_category_comes_from_race_field():
    r = record("Mystical Space Typhoon")
    assert r.card_category == "SPELL"
    assert r.sub_category == "QUICK_PLAY"
    assert r.race is None
    assert r.attribute is None


def test_trap_counter():
    r = record("Solemn Judgment")
    assert r.card_category == "TRAP"
    assert r.sub_category == "COUNTER"


def test_token():
    r = record("Sheep Token")
    assert r.card_category == "MONSTER"
    assert r.sub_category == "TOKEN"


def test_external_ids_carry_both_namespaces():
    r = record("Dark Magician")
    sources = {e.source for e in r.external_ids}
    assert sources == {"ygopro_passcode", "ygoprodeck_id"}
    assert r.external_id("ygopro_passcode") == "46986414"


def test_identity_key_prefers_passcode():
    assert record("Dark Magician").identity_key == "passcode:46986414"


def test_unknown_frame_type_falls_back_to_type_string():
    raw = dict(BY_NAME["Decode Talker"])
    raw.pop("frameType")
    r = normalize_ygoprodeck_record(raw)
    assert r.card_category == "MONSTER"
    assert r.sub_category == "LINK"


def test_invalid_type_string_raises():
    with pytest.raises(ValueError):
        normalize_ygoprodeck_record({"name": "X", "type": "banana", "frameType": "banana"})


# ----------------------------------------------------------------- cards.cdb
def _cdb_row(**overrides):
    row = {
        "id": 89631139,
        "name": "Blue-Eyes White Dragon",
        "desc": "This legendary dragon is a powerful engine of destruction.",
        "strings": {},
        "ot": 3,
        "alias": 0,
        "setcode": 0x0001,
        "type": 0x1 | 0x10,          # MONSTER | NORMAL
        "atk": 3000,
        "def": 2500,
        "level": 8,
        "race": 0x2000,             # DRAGON
        "attribute": 0x10,          # LIGHT
        "category": 0,
    }
    row.update(overrides)
    return row


def test_normalize_cdb_normal_monster():
    r = normalize_cdb_row(_cdb_row())
    assert (r.card_category, r.sub_category) == ("MONSTER", "NORMAL")
    assert (r.race, r.attribute, r.level_rank) == ("DRAGON", "LIGHT", 8)
    assert r.external_id("ygopro_passcode") == "89631139"
    assert r.raw_text.startswith("This legendary dragon")


def test_normalize_cdb_pendulum_unpacks_scale():
    r = normalize_cdb_row(
        _cdb_row(type=0x1 | 0x20 | 0x400000, level=3 | (8 << 16))  # EFFECT | PENDULUM
    )
    assert r.pendulum_scale == 8
    assert r.level_rank == 3
    assert "PENDULUM" in r.flags


def test_normalize_cdb_spell_has_no_monster_fields():
    r = normalize_cdb_row(
        _cdb_row(**{"type": 0x2 | 0x10000, "race": 0, "attribute": 0, "level": 0, "atk": 0, "def": 0})
    )
    assert r.card_category == "SPELL"
    assert r.sub_category == "QUICK_PLAY"
    assert r.race is None and r.attribute is None and r.level_rank is None


def test_normalize_cdb_link_rating():
    r = normalize_cdb_row(_cdb_row(type=0x1 | 0x20 | 0x1000000, level=3))
    assert r.sub_category == "LINK"
    assert r.link_rating == 3
    assert r.defense is None


def test_normalize_cdb_setcode_becomes_archetype_slug():
    r = normalize_cdb_row(_cdb_row(setcode=0x0001))
    assert r.archetypes == [("setcode-0001", "0001")]


def test_invalid_card_category_rejected_by_model():
    from ygolookup.db.models import CardRecord

    with pytest.raises(ValueError):
        CardRecord(canonical_name="X", card_category="PIZZA")
