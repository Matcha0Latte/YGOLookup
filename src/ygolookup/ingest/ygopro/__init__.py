"""YGOPro / Project Ignis data source adapters."""

from .bitmask import (
    decode_attribute,
    decode_category,
    decode_flags,
    decode_link_rating,
    decode_race,
    decode_setcode,
    decode_sub_category,
)
from .cdb_reader import iter_cdb_rows, validate_cdb

__all__ = [
    "decode_attribute",
    "decode_category",
    "decode_flags",
    "decode_link_rating",
    "decode_race",
    "decode_setcode",
    "decode_sub_category",
    "iter_cdb_rows",
    "validate_cdb",
]
