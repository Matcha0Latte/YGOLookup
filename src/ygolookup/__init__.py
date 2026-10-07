"""YGOLookup — an intelligent Yu-Gi-Oh! card retrieval system.

Layer responsibilities (keep these boundaries intact):

    ingest     -> pull raw external card data, normalize it, never re-parse live
    db         -> canonical SQLite storage. SQLite is the source of truth.
    effects    -> split card text into Effect records + structured predicates
    query      -> serializable Query AST, independent of any storage engine
    retrieval  -> structured / fulltext / semantic / hybrid search backends
    agent      -> orchestration + tool surface (no DB business logic here)
    cli        -> thin presentation layer
"""

__version__ = "0.1.0"
