from ygolookup.ingest.ygopro import bitmask


def test_decode_category():
    assert bitmask.decode_category(0x11) == "MONSTER"      # MONSTER|NORMAL
    assert bitmask.decode_category(0x2 | 0x10000) == "SPELL"
    assert bitmask.decode_category(0x4) == "TRAP"


def test_decode_attribute_and_race():
    assert bitmask.decode_attribute(0x20) == "DARK"
    assert bitmask.decode_attribute(0x10) == "LIGHT"
    assert bitmask.decode_race(0x2000) == "DRAGON"
    assert bitmask.decode_race(0x200) == "WINGED_BEAST"


def test_decoding_none_is_none_not_false():
    """A missing mask must decode to None (not applicable/unknown), never ''. """
    assert bitmask.decode_attribute(None) is None
    assert bitmask.decode_race(0) is None


def test_sub_category_monster_precedence():
    link = bitmask.TYPE_MONSTER | bitmask.TYPE_LINK | bitmask.TYPE_EFFECT
    assert bitmask.decode_sub_category(link, "MONSTER") == "LINK"

    xyz = bitmask.TYPE_MONSTER | bitmask.TYPE_XYZ | bitmask.TYPE_EFFECT
    assert bitmask.decode_sub_category(xyz, "MONSTER") == "XYZ"

    normal = bitmask.TYPE_MONSTER | bitmask.TYPE_NORMAL
    assert bitmask.decode_sub_category(normal, "MONSTER") == "NORMAL"


def test_sub_category_spell_trap():
    assert bitmask.decode_sub_category(bitmask.TYPE_SPELL | bitmask.TYPE_QUICK_PLAY, "SPELL") == "QUICK_PLAY"
    assert bitmask.decode_sub_category(bitmask.TYPE_SPELL | bitmask.TYPE_FIELD, "SPELL") == "FIELD"
    # A counter trap has no sub-type bit upstream -> NORMAL fallback.
    assert bitmask.decode_sub_category(bitmask.TYPE_TRAP, "TRAP") == "NORMAL"


def test_flags():
    mask = bitmask.TYPE_MONSTER | bitmask.TYPE_EFFECT | bitmask.TYPE_TUNER | bitmask.TYPE_PENDULUM
    assert bitmask.decode_flags(mask) == {"TUNER", "PENDULUM"}
    assert bitmask.decode_flags(None) == set()


def test_level_packs_pendulum_scale():
    level_field = 3 | (8 << 16)
    level, scale = bitmask.decode_level(level_field)
    assert (level, scale) == (3, 8)


def test_link_rating_only_for_link_monsters():
    assert bitmask.decode_link_rating(4, is_link=True) == 4
    assert bitmask.decode_link_rating(4, is_link=False) is None


def test_setcode_unpacks_up_to_four_archetypes():
    setcode = 0x0000_0001 | (0x0002 << 16)
    assert bitmask.decode_setcode(setcode) == ["0001", "0002"]
    assert bitmask.decode_setcode(0) == []
