"""Identity resolution: upstream ids -> internal `card_id`.

Rules:
  1. An internal `card_id` is created by this system and never reused across
     different real cards.
  2. Two upstream records are the same card when they share an identity key.
     The passcode is the strongest key; the (lang, name) pair is the fallback
     used for passcode-less records (some anime / token entries).
  3. Upstream `alias` (alternate artwork of an existing card) is recorded but
     is NOT merged automatically — merging is a curation decision and would
     silently destroy data if the upstream value is wrong.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..db.models import CardRecord


@dataclass
class IdentityIndex:
    """Group normalized records by identity key before they hit the database."""

    groups: dict[str, list[CardRecord]] = field(default_factory=lambda: defaultdict(list))
    collisions: dict[str, list[str]] = field(default_factory=dict)

    def add(self, record: CardRecord) -> None:
        self.groups[record.identity_key].append(record)

    def extend(self, records: list[CardRecord]) -> None:
        for record in records:
            self.add(record)

    def finalize(self) -> dict[str, list[CardRecord]]:
        """Detect identity keys that captured clearly different cards."""
        for key, records in self.groups.items():
            names = {r.canonical_name.casefold() for r in records}
            if len(names) > 1:
                self.collisions[key] = sorted(names)
        return dict(self.groups)

    @property
    def card_count(self) -> int:
        return len(self.groups)

    @property
    def record_count(self) -> int:
        return sum(len(v) for v in self.groups.values())


def identity_key_for(record: CardRecord) -> str:
    return record.identity_key


def alias_report(records: list[CardRecord]) -> dict[int, list[str]]:
    """passcode -> list of card names whose `alias` points at it.

    Purely informational; surfaced by the CLI so a human can decide whether to
    merge alternate artworks.
    """
    out: dict[int, list[str]] = defaultdict(list)
    for record in records:
        if record.alias_passcode:
            out[int(record.alias_passcode)].append(record.canonical_name)
    return dict(out)
