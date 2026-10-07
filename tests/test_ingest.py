import json
import sqlite3
from pathlib import Path

from ygolookup.db.connection import connect
from ygolookup.db.migrations import apply_migrations
from ygolookup.db.repository import (
    card_archetypes,
    card_external_ids,
    card_flags,
    find_card_by_name,
    stats,
)
from ygolookup.ingest.id_mapping import IdentityIndex, alias_report
from ygolookup.ingest.service import ingest_from_cdb, ingest_from_ygoprodeck

FIXTURE = Path(__file__).parent / "fixtures" / "ygoprodeck_sample.json"


def build_fake_cdb(path: Path) -> Path:
    """Create a minimal but structurally real cards.cdb."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE texts (id INTEGER PRIMARY KEY, name TEXT, desc TEXT,"
        " str1 TEXT, str2 TEXT, str3 TEXT, str4 TEXT, str5 TEXT, str6 TEXT,"
        " str7 TEXT, str8 TEXT, str9 TEXT, str10 TEXT, str11 TEXT, str12 TEXT,"
        " str13 TEXT, str14 TEXT, str15 TEXT, str16 TEXT)"
    )
    conn.execute(
        "CREATE TABLE datas (id INTEGER PRIMARY KEY, ot INTEGER, alias INTEGER,"
        " setcode INTEGER, type INTEGER, atk INTEGER, def INTEGER, level INTEGER,"
        " race INTEGER, attribute INTEGER, category INTEGER)"
    )
    conn.execute(
        "INSERT INTO texts (id, name, desc) VALUES (?,?,?)",
        (89631139, "Blue-Eyes White Dragon", "This legendary dragon is a powerful engine of destruction."),
    )
    conn.execute(
        "INSERT INTO datas VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (89631139, 3, 0, 0x0001, 0x1 | 0x10, 3000, 2500, 8, 0x2000, 0x10, 0),
    )
    conn.execute(
        "INSERT INTO texts (id, name, desc) VALUES (?,?,?)",
        (46986414, "Dark Magician", "The ultimate wizard in terms of attack and defense."),
    )
    conn.execute(
        "INSERT INTO datas VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (46986414, 3, 0, 0x0002, 0x1 | 0x10, 2500, 2100, 7, 0x2, 0x20, 0),
    )
    conn.commit()
    conn.close()
    return path


# ------------------------------------------------------------------- cdb import
def test_ingest_from_cdb_end_to_end(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    apply_migrations(conn)

    cdb = build_fake_cdb(tmp_path / "cards.cdb")
    result = ingest_from_cdb(conn, cdb)

    assert result.records_seen == 2
    assert result.cards_created == 2
    assert not result.errors

    card = find_card_by_name(conn, "Blue-Eyes White Dragon")
    assert card["race"] == "DRAGON"
    assert card["attribute"] == "LIGHT"
    assert card["level_rank"] == 8
    assert card["atk"] == 3000
    assert ("ygopro_passcode", "89631139") in card_external_ids(conn, card["card_id"])
    assert card_archetypes(conn, card["card_id"]) == ["setcode-0001"]
    conn.close()


def test_ingest_is_idempotent(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    apply_migrations(conn)
    cdb = build_fake_cdb(tmp_path / "cards.cdb")

    ingest_from_cdb(conn, cdb)
    second = ingest_from_cdb(conn, cdb)

    assert second.cards_created == 0
    assert second.cards_updated == 2
    assert stats(conn)["cards"] == 2  # no duplicates
    conn.close()


def test_raw_source_and_raw_records_are_persisted(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    apply_migrations(conn)
    ingest_from_cdb(conn, build_fake_cdb(tmp_path / "cards.cdb"))

    assert stats(conn)["raw_sources"] == 1
    assert stats(conn)["raw_card_records"] == 2

    row = conn.execute("SELECT payload_json FROM raw_card_record LIMIT 1").fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["canonical_name"]
    assert "raw_text" in payload
    conn.close()


def test_invalid_cdb_raises(tmp_path):
    from ygolookup.ingest.ygopro.cdb_reader import CdbFormatError

    conn = connect(tmp_path / "db.sqlite")
    apply_migrations(conn)
    bogus = tmp_path / "nope.cdb"
    bogus.write_bytes(b"not a sqlite file")
    try:
        ingest_from_cdb(conn, bogus)
        raise AssertionError("expected CdbFormatError")
    except (CdbFormatError, sqlite3.DatabaseError):
        pass
    conn.close()


# ------------------------------------------------------------ ygoprodeck import
def test_ingest_from_ygoprodeck_snapshot(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    apply_migrations(conn)

    result = ingest_from_ygoprodeck(conn, url="", raw_dir=tmp_path, local_path=FIXTURE)
    assert result.records_seen == 10
    assert result.cards_created == 10
    assert not result.errors

    s = stats(conn)
    assert s["cards"] == 10
    assert s["monsters"] == 8  # 7 real monsters + Sheep Token
    assert s["spells"] == 1  # Mystical Space Typhoon (Quick-Play)
    assert s["traps"] == 1  # Solemn Judgment (Counter)

    card = find_card_by_name(conn, "Decode Talker")
    assert card["link_rating"] == 3
    assert card_flags(conn, card["card_id"]) == []

    synchron = find_card_by_name(conn, "Junk Synchron")
    assert "TUNER" in card_flags(conn, synchron["card_id"])
    conn.close()


def test_archetype_and_name_rows(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    apply_migrations(conn)
    ingest_from_ygoprodeck(conn, url="", raw_dir=tmp_path, local_path=FIXTURE)

    bewd = find_card_by_name(conn, "Blue-Eyes White Dragon")
    assert card_archetypes(conn, bewd["card_id"]) == ["blue-eyes"]

    names = {r["name"] for r in conn.execute("SELECT name FROM card_name WHERE card_id = ?", (bewd["card_id"],))}
    assert "Blue-Eyes White Dragon" in names
    conn.close()


# -------------------------------------------------------------- id mapping
def test_identity_index_groups_by_key():
    from ygolookup.ingest.normalize import normalize_ygoprodeck_record

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
    records = [normalize_ygoprodeck_record(c) for c in data]
    index = IdentityIndex()
    index.extend(records)
    index.finalize()

    assert index.record_count == 10
    assert index.card_count == 10
    assert not index.collisions


def test_identity_index_detects_collision():
    from ygolookup.db.models import CardRecord, ExternalId

    a = CardRecord(
        canonical_name="Alpha",
        card_category="MONSTER",
        external_ids=[ExternalId("ygopro_passcode", "111")],
    )
    b = CardRecord(
        canonical_name="Beta",
        card_category="MONSTER",
        external_ids=[ExternalId("ygopro_passcode", "111")],
    )
    index = IdentityIndex()
    index.extend([a, b])
    index.finalize()
    assert "passcode:111" in index.collisions


def test_alias_report_is_informational_only():
    from ygolookup.db.models import CardRecord

    records = [
        CardRecord(canonical_name="Alt Art", card_category="MONSTER", alias_passcode=89631139),
        CardRecord(canonical_name="Normal", card_category="MONSTER"),
    ]
    assert alias_report(records) == {89631139: ["Alt Art"]}
