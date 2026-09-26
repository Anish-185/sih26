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

Phase 8 uses it in three places, always AFTER retrieval has chosen the standard:
``attach`` (clauses for a confident /ask answer), ``scope_of`` ("why this result?")
and ``unsupported_citations`` (the guard that withholds an answer citing a clause
MetrIQ did not supply).
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.knowledge.loader import load_knowledge_base
from app.knowledge.schema import KnowledgeItem
from app.language import FILLER, FOLLOW_UP_WORDS
from app.retrieval import RetrievalResult, SearchEngine
from app.retrieval.engine import RetrievalConfig
from app.retrieval.text import tokenize


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


# Shown with every clause, everywhere: values such as "1.0 1 to 1.1 1" (litres read
# as "1") survive by design, because MetrIQ never corrects OCR. This label is what
# makes that honest.
OCR_LABEL = ("OCR text from a scanned BIS document, via the Public.Resource.Org / Internet "
             "Archive mirror. Not verified by a person; it may contain character errors. "
             "Check any value against the named PDF page.")

_NOTE = "\n\nMetrIQ note:"
_PDF_PAGE = re.compile(r"PDF pages? (\d+)")


def label_of(item: KnowledgeItem) -> str:
    """"5.2.3" / "B-5.1" — read from the stored reference ("Clause 5.2.3, …")."""
    return (item.reference or "").split(",")[0].removeprefix("Clause ").strip()


def view(item: KnowledgeItem) -> dict:
    """One clause for display: its own text and MetrIQ's note kept apart, verbatim."""
    text, _, note = item.content.partition(_NOTE)
    page = _PDF_PAGE.search(item.reference or "")
    return {
        "id": item.id,
        "standard_number": item.standard_number or "",
        "clause": label_of(item),
        "heading": item.title.split(" — ", 1)[-1],
        "text": text.strip(),
        "note": ("MetrIQ note:" + note).strip() if note else "",
        "reference": item.reference or "",
        "source_url": item.source_url or "",
        "pdf_page": int(page.group(1)) if page else None,
    }


def residual_query(standard: KnowledgeItem, query: str) -> str:
    """The part of the query that says WHICH clause, once the standard is chosen.

    The words that identified the standard ("packaged drinking water") appear in nearly
    every one of its clauses, so ranked on the whole query they outweigh the word that
    names a clause ("sampling"). Dropped: stopwords (``tokenize``), FILLER, the Phase 6
    process words, and every word of the standard's own record — title, keywords,
    document name, number. One exception, read from the data rather than a new list: a
    process word that is a word of one of this standard's main-body section headings
    ("8 MARKING", "21 TESTS") names a clause here, so it stays. Annex headings do not
    count ("F-1 GENERAL REQUIREMENTS OF" would keep "requirements" everywhere).
    """
    number = standard.standard_number or ""
    identifying = set(tokenize(" ".join([standard.title, *standard.keywords,
                                         standard.document_name or "", number])))
    headings = {word for clause in clauses_for(number) if label_of(clause).isdigit()
                for word in tokenize(clause.title.split(" — ", 1)[-1])}
    return " ".join(t for t in tokenize(query)
                    if t not in identifying and t not in FILLER
                    and (t not in FOLLOW_UP_WORDS or t in headings))


def attach(results: list[RetrievalResult], query: str,
           per_standard: int = 3, total: int = 6) -> list[KnowledgeItem]:
    """Clauses of the standards retrieval already found, ranked against the query.

    The caller decides WHEN (only a confident answer); this only decides which of
    that standard's clauses match, ranked on ``residual_query``. When nothing is
    left of the query but the standard itself — or what is left names no clause
    ("tell me about …") — only its scope clause is attached.
    Capped so the model's context stays small.
    """
    attached: list[KnowledgeItem] = []
    for result in results:
        item = result.item
        if item.category != "indian_standards" or not item.standard_number:
            continue
        residual = residual_query(item, query)
        ranked = ([r.item for r in rank_within(item.standard_number, residual) if r.score > 0]
                  if residual else []) or scope_of(item.standard_number)[:1]
        attached += ranked[:per_standard][: total - len(attached)]
        if len(attached) >= total:
            break
    return attached


def scope_of(standard_number: str) -> list[KnowledgeItem]:
    """The scope clause (1) and its sub-clauses (1.1, 1.2 …) that MetrIQ holds."""
    return [c for c in clauses_for(standard_number)
            if label_of(c) == "1" or label_of(c).startswith("1.")]


# A clause is cited only with a marker: "clause 5.2.3", "cl. 9", "Annex B" or an
# annex-style number with a dot, "F-1.4". A bare dotted number is a quantity ("1.5
# litres", "9.1 kg"), never checked, or every amount would trip the guard. Without the
# dot, "M-20" (concrete grade), "Class B-1" and "Type A-2" are names, not clauses; an
# explicit "Annex F-1" still counts. A range ("clauses 5.2.1 to 5.2.9") cites both ends.
# Hindi / Telugu: in live hi/te answers the model wrote "Clause 9" in English every time
# and used no native word for "clause"; the one native marker seen was Hindi "अनुबंध F"
# (Annex F). अनुबंध also means "contract / agreement", so it counts only when followed
# by an annex letter.
_LABEL = r"(?:[A-Z]-)?\d+(?:\.\d+)*"
_CITED = re.compile(rf"\b(?:clauses?|cl\.)\s*({_LABEL})(?:\s*(?:to|-|–|—)\s*({_LABEL}))?", re.IGNORECASE)
_ANNEX_STYLE = re.compile(r"(?<![\w-])([A-Z]-\d+(?:\.\d+)+)(?![\w-])")
_ANNEX = re.compile(r"(?:\bAnnex|(?<!\S)अनुबंध)\s+([A-Z])(?:-(\d+(?:\.\d+)*))?\b")


def cited(text: str) -> set[str]:
    labels = {m.group(1) for m in _ANNEX_STYLE.finditer(text)}
    for m in _CITED.finditer(text):
        labels |= {g.upper() for g in m.groups() if g}
    for m in _ANNEX.finditer(text):
        labels.add(f"Annex {m.group(1)}")
        if m.group(2):
            labels.add(f"{m.group(1)}-{m.group(2)}")
    return labels


def unsupported_citations(answer: str, context: str) -> set[str]:
    """Clauses the answer cites that appear nowhere in the context MetrIQ supplied."""
    held = cited(context)            # "Clause 9, PDF page 14", "Annex B" … as supplied

    def supplied(label: str) -> bool:
        if label in held:
            return True
        if re.search(rf"(?m)^{re.escape(label)}\.?\s", context):
            return True                      # a clause heading line: "9 SAMPLING"
        # A dotted or annex-style number is specific enough to accept as a cross-reference
        # inside supplied clause text ("given in 5.2.1 to 5.2.9"). A bare "9" is not: it
        # appears everywhere as a quantity, so it counts only through the two checks above.
        return ("." in label or "-" in label) and re.search(
            rf"(?<![\w.-]){re.escape(label)}(?![\w-]|\.\d)", context) is not None
    return {label for label in cited(answer) if not supplied(label)}
