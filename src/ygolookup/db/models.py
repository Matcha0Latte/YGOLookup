"""Canonical card models.

These dataclasses are the contract between the ingest layer and the database.
They are deliberately storage-agnostic (no SQL strings here) so the same
normalized record can come from a `cards.cdb`, a JSON API, or a test fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# --------------------------------------------------------------------- enums
# Kept as plain frozen sets (not Enum classes) because they are used for both
# validation and SQL binding, and because the upstream vocabulary is stable.

CARD_CATEGORIES = frozenset({"MONSTER", "SPELL", "TRAP"})

SUB_CATEGORIES = frozenset(
    {
        "NORMAL",
        "EFFECT",
        "FUSION",
        "RITUAL",
        "SYNCHRO",
        "XYZ",
        "LINK",
        "PENDULUM",
        "QUICK_PLAY",
        "CONTINUOUS",
        "EQUIP",
        "FIELD",
        "COUNTER",
        "TRAP_MONSTER",
        "TOKEN",
        "SKILL",
        "MAXIMUM",
        "ARMOR",
    }
)

# Sentinel used upstream for a printed "?" ATK/DEF.
ATK_DEF_UNKNOWN = -1


@dataclass(frozen=True)
class CardName:
    lang: str
    name: str
    kind: str = "official"  # official | localized | alias
    is_primary: bool = False


@dataclass(frozen=True)
class ExternalId:
    source: str  # ygopro_passcode | ygoprodeck_id | konami_cid
    value: str


@dataclass
class CardRecord:
    """One normalized, source-independent card."""

    canonical_name: str
    card_category: str
    raw_text: str = ""
    text_lang: str = "en"

    sub_category: str | None = None
    race: str | None = None
    attribute: str | None = None
    level_rank: int | None = None
    link_rating: int | None = None
    pendulum_scale: int | None = None
    atk: int | None = None
    defense: int | None = None

    # Upstream bitmasks, preserved verbatim for traceability.
    type_mask: int | None = None
    race_mask: int | None = None
    attribute_mask: int | None = None
    category_mask: int | None = None
    setcode_mask: int | None = None

    alias_passcode: int | None = None

    names: list[CardName] = field(default_factory=list)
    external_ids: list[ExternalId] = field(default_factory=list)
    archetypes: list[tuple[str, str | None]] = field(default_factory=list)  # (slug, raw)
    flags: set[str] = field(default_factory=set)

    # Stable dedup key chosen by the id_mapping layer (usually a passcode).
    identity_key: str = ""

    def __post_init__(self) -> None:
        if self.card_category not in CARD_CATEGORIES:
            raise ValueError(f"invalid card_category: {self.card_category!r}")
        if self.sub_category is not None and self.sub_category not in SUB_CATEGORIES:
            raise ValueError(f"invalid sub_category: {self.sub_category!r}")
        if not self.names:
            self.names = [
                CardName(lang=self.text_lang, name=self.canonical_name, kind="official", is_primary=True)
            ]
        if not self.identity_key:
            self.identity_key = self._default_identity_key()

    def _default_identity_key(self) -> str:
        for ext in self.external_ids:
            if ext.source == "ygopro_passcode" and ext.value and ext.value != "0":
                return f"passcode:{ext.value}"
        return f"name:{self.text_lang}:{self.canonical_name.casefold()}"

    def external_id(self, source: str) -> str | None:
        for ext in self.external_ids:
            if ext.source == source:
                return ext.value
        return None

    def add_flags(self, flags: Iterable[str]) -> None:
        self.flags.update(flags)
