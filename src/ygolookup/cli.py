"""Command line entry point.

Thin presentation layer only — every command delegates to a library function.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import config
from .db.connection import connect
from .db.migrations import apply_migrations
from .db.repository import card_archetypes, card_external_ids, card_flags, card_names, find_card_by_name, stats
from .ingest.service import ingest_from_cdb, ingest_from_ygoprodeck


def _open_db(args) :
    conn = connect(args.db or config.db_path)
    apply_migrations(conn)
    return conn


def cmd_ingest(args) -> int:
    conn = _open_db(args)
    if args.source == "cdb":
        if not args.path:
            print("error: --path is required for --source cdb", file=sys.stderr)
            return 2
        result = ingest_from_cdb(conn, args.path)
    elif args.source == "ygoprodeck":
        result = ingest_from_ygoprodeck(
            conn,
            url=args.url or config.ygoprodeck_api,
            raw_dir=args.raw_dir or config.raw_dir,
            local_path=args.path,
        )
    else:  # pragma: no cover - argparse restricts choices
        print(f"error: unknown source {args.source}", file=sys.stderr)
        return 2

    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    if result.errors:
        print(f"warning: {len(result.errors)} record(s) failed", file=sys.stderr)
    conn.close()
    return 0


def cmd_stats(args) -> int:
    conn = _open_db(args)
    print(json.dumps(stats(conn), indent=2))
    conn.close()
    return 0


def cmd_card(args) -> int:
    conn = _open_db(args)
    row = find_card_by_name(conn, args.name, exact=not args.fuzzy)
    if row is None:
        print(f"no card matching {args.name!r}", file=sys.stderr)
        return 1
    payload = {
        "card_id": row["card_id"],
        "name": row["canonical_name"],
        "category": row["card_category"],
        "sub_category": row["sub_category"],
        "race": row["race"],
        "attribute": row["attribute"],
        "level_rank": row["level_rank"],
        "link_rating": row["link_rating"],
        "pendulum_scale": row["pendulum_scale"],
        "atk": row["atk"],
        "def": row["def"],
        "names": card_names(conn, row["card_id"]),
        "archetypes": card_archetypes(conn, row["card_id"]),
        "flags": card_flags(conn, row["card_id"]),
        "external_ids": [
            {"source": s, "value": v} for s, v in card_external_ids(conn, row["card_id"])
        ],
        "raw_text": row["raw_text"] if args.raw else "",
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ygo", description="YGOLookup card retrieval system")
    parser.add_argument("--db", type=Path, default=None, help="SQLite path (default: $YGO_DB_PATH)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="import card data")
    p_ingest.add_argument("--source", choices=["cdb", "ygoprodeck"], required=True)
    p_ingest.add_argument("--path", type=Path, default=None, help="cards.cdb path, or a local JSON snapshot")
    p_ingest.add_argument("--url", default=None, help="override the JSON source URL")
    p_ingest.add_argument("--raw-dir", type=Path, default=None, help="where raw snapshots are stored")
    p_ingest.set_defaults(func=cmd_ingest)

    p_stats = sub.add_parser("stats", help="database statistics")
    p_stats.set_defaults(func=cmd_stats)

    p_card = sub.add_parser("card", help="look up a single card")
    p_card.add_argument("name")
    p_card.add_argument("--fuzzy", action="store_true")
    p_card.add_argument("--raw", action="store_true", help="include the original effect text")
    p_card.set_defaults(func=cmd_card)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
