"""Clause text of a standard MetrIQ has ALREADY retrieved (Phase 7, citation only).

Clause records (category ``standard_clauses``) are OCR text of the cited base edition,
from the Public.Resource.Org / Internet Archive mirror, unverified by a person. They
are deliberately NOT in the main search index (see ``SearchEngine.__init__``): joined
to it, generic words matched clause prose and clause records outranked their own
standard on a standard-number lookup.

So this is not a second global index. It is a per-standard lookup applied AFTER the
standard has been retrieved by the normal path:

    clauses_for(number)         every clause of exactly that standard, in clause order
    rank_within(number, query)  those clauses ranked against a question, by the EXISTING
                                SearchEngine scoring (no new scoring code)

Exact string match only: an edition's clauses never attach to another edition's number.
Nothing calls this yet except tests; Phase 8 wires it into answers.
"""

from __future__ import annotations

from functools import lru_cache

from app.knowledge.loader import load_knowledge_base
from app.knowledge.schema import KnowledgeItem
from app.retrieval import RetrievalResult, SearchEngine
from app.retrieval.engine import RetrievalConfig


@lru_cache(maxsize=1)
def _by_standard() -> dict[str, tuple[KnowledgeItem, ...]]:
    grouped: dict[str, list[KnowledgeItem]] = {}
    for item in load_knowledge_base().items:          # file order is clause order
        if item.category == "standard_clauses" and item.standard_number:
            grouped.setdefault(item.standard_number, []).append(item)
    return {number: tuple(items) for number, items in grouped.items()}


def clauses_for(standard_number: str) -> list[KnowledgeItem]:
    """All clause records whose standard_number is exactly this string, in clause order."""
    return list(_by_standard().get(standard_number, ()))


def rank_within(standard_number: str, query: str, limit: int | None = None) -> list[RetrievalResult]:
    """That standard's clauses ranked against the query. An empty list is a valid answer."""
    clauses = clauses_for(standard_number)
    if not clauses:
        return []
    # ponytail: an engine over one standard's clauses, built without SearchEngine's loader
    # (which excludes clause records). Same _index_item and scoring; add a constructor
    # argument to SearchEngine if a second caller ever needs this.
    engine = SearchEngine.__new__(SearchEngine)
    engine.config = RetrievalConfig()
    engine.load_errors = []
    engine._items = clauses
    engine._index = [SearchEngine._index_item(item) for item in clauses]
    return engine.search(query, limit=limit).results
