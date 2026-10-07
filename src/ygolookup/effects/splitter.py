"""Card text -> Effect segments.

The splitter is deliberately conservative: over-splitting a card is safer than
merging two unrelated effects, because every segment keeps its own raw text and
can still be re-joined at query time.

Splitting happens in three passes:

    1. scope   : pendulum cards -> [Pendulum Effect] / [Monster Effect] blocks
    2. marker  : "●" bullet items are always separate effects
    3. line    : a line starting with an activation/effect keyword is its own
                 effect; otherwise leftover prose is split on sentence
                 boundaries when it reads like multiple effects
"""

from __future__ import annotations

import re

from .ontology import EffectScope, SegmentMarker
from .schema import EffectSegment

_PENDULUM_SPLIT = re.compile(
    r"\[\s*Pendulum Effect\s*\]|\[\s*Monster Effect\s*\]|^\s*Pendulum Effect\s*$|^\s*Monster Effect\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_BULLET = "●"

# A line beginning with one of these almost always starts a new effect.
_LINE_STARTERS = (
    "once per turn",
    "once per chain",
    "if ",
    "when ",
    "while ",
    "during ",
    "at the start of",
    "at the end of",
    "you can ",
    "your opponent cannot",
    "each turn",
    "each time",
    "every time",
    "this card gains",
    "this card cannot",
    "cannot be ",
    "must be ",
    "monsters you control gain",
    "all ",
    "apply the following effect",
    "apply this effect",
    "a monster ",
    "the first time",
    "activate this effect",
    "if this card is",
    "if a ",
    "if you ",
    "if your ",
)

# NOTE: deliberately does NOT split on ";". In PSCT ";" separates cost from
# resolution, which belongs to ONE effect — the parser handles it.
_SENTENCE_SPLIT = re.compile(r"(?<=\.)\s+(?=[A-Z“\"\w])")

# Summoning-material lines ("2 Level 4 monsters", "1 Tuner + 1+ non-Tuner
# monsters") are part of a card's text but are not effects. They are labelled so
# the parser can skip them instead of inventing a meaningless predicate.
_MATERIAL_LINE = re.compile(
    r"""^\s*
        (?:
            \d+\+?\s*(?:[\w\-']+\s+)*monsters?\s*(?:\+\s*.+)?   # "2 Level 4 monsters"
          | \d+\+?\s*[\w\-']+\s+\+\s+.+                          # "1 Tuner + 1+ non-Tuner monsters"
        )
        \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def split_scope(text: str) -> list[tuple[EffectScope, str]]:
    """Pass 1: separate pendulum blocks from monster blocks."""
    text = _clean(text)
    if not text:
        return []

    matches = list(_PENDULUM_SPLIT.finditer(text))
    pendulum_markers = [m for m in matches if "pendulum" in m.group(0).lower()]
    if not pendulum_markers:
        return [(EffectScope.MAIN, text)]

    out: list[tuple[EffectScope, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip(" \n:-\t")
        if not body:
            continue
        scope = EffectScope.PENDULUM if "pendulum" in match.group(0).lower() else EffectScope.MONSTER
        out.append((scope, body))
    return out or [(EffectScope.MAIN, text)]


def split_bullets(text: str) -> list[tuple[SegmentMarker, str]]:
    """Pass 2: '●' items are explicit, curated effect boundaries."""
    if _BULLET not in text:
        return [(SegmentMarker.BLOCK, text)]

    out: list[tuple[SegmentMarker, str]] = []
    head, _, rest = text.partition(_BULLET)
    head = head.strip(" \n:-")
    if head:
        out.append((SegmentMarker.LINE, head))
    for chunk in rest.split(_BULLET):
        chunk = chunk.strip()
        if chunk:
            out.append((SegmentMarker.BULLET, chunk))
    return out or [(SegmentMarker.BLOCK, text)]


def split_lines(text: str) -> list[tuple[SegmentMarker, str]]:
    """Pass 3: split remaining prose into line / sentence level effects."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) == 1 and _MATERIAL_LINE.match(lines[0]):
        return [(SegmentMarker.MATERIAL, lines[0])]
    if len(lines) <= 1:
        return _split_sentences(text)

    out: list[tuple[SegmentMarker, str]] = []
    buffer: list[str] = []
    for line in lines:
        lowered = line.lower()
        if not buffer and _MATERIAL_LINE.match(line):
            out.append((SegmentMarker.MATERIAL, line))
            continue
        starts_effect = any(lowered.startswith(starter) for starter in _LINE_STARTERS)
        if starts_effect and buffer:
            out.append((SegmentMarker.LINE, " ".join(buffer)))
            buffer = [line]
        else:
            buffer.append(line)
    if buffer:
        out.append((SegmentMarker.LINE, " ".join(buffer)))

    # A line that turned out to hold several sentences still deserves splitting:
    # "… Special Summon that target. Level 8 or lower monsters cannot attack …"
    # is two unrelated effects.
    expanded: list[tuple[SegmentMarker, str]] = []
    for marker, chunk in out:
        if marker is SegmentMarker.MATERIAL:
            expanded.append((marker, chunk))
            continue
        expanded.extend(_split_sentences(chunk))
    return expanded or [(SegmentMarker.BLOCK, text)]


def _split_sentences(text: str) -> list[tuple[SegmentMarker, str]]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    if len(parts) <= 1:
        return [(SegmentMarker.BLOCK, text)]
    return [(SegmentMarker.SENTENCE, part) for part in parts]


def split_effects(raw_text: str) -> list[EffectSegment]:
    """Full pipeline: raw card text -> ordered EffectSegments."""
    segments: list[EffectSegment] = []
    index = 0

    for scope, scope_text in split_scope(raw_text):
        for marker, chunk in split_bullets(scope_text):
            for sub_marker, sub_chunk in split_lines(chunk):
                final_marker = marker if marker is SegmentMarker.BULLET else sub_marker
                segments.append(
                    EffectSegment(index=index, scope=scope, marker=final_marker, raw_text=sub_chunk)
                )
                index += 1

    return segments
