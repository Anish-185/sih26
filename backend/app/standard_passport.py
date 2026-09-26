"""The Standard Passport: everything MetrIQ holds about ONE Indian Standard (Phase 11).

A COMPOSER, in the style of ``product_context.py``: it reads evidence other modules
already produce and creates none. No model, no retrieval, no rule engine, no write.

    lookup(number)     the indian_standards records a number names. A number WITH a year
                       names that edition only; WITHOUT a year it names every edition
                       MetrIQ holds of that number / part / section — one record
                       redirects, several are listed and never auto-picked.
    build(record_id)   the Passport's own sections (identity, coverage, currency, legal
                       status, scope, requirements, sources), each composed from:
                         identity     the record itself + Phase 4 catalogue identity
                         coverage     product.text_held (Phase 8) + clause_groups (Phase 10)
                         currency     standard_currency.currency_for (Phase 5)
                         legal        qco.for_standard (Phase 9) + qco.listing_orders_for (9.1)
                         scope / reqs clauses.scope_of / clauses.clauses_for (Phase 7)
                       Sampling & testing, certification, laboratories and the evidence
                       graph are rendered by the page from their EXISTING endpoints.

Every section that has no data says so in MetrIQ's own sentence; nothing is hidden.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import BaseModel, Field

from app import clause_groups, clauses
from app import qco as qco_module
from app.knowledge.loader import load_knowledge_base
from app.knowledge.schema import KnowledgeItem
from app.lab_registry import standard_key
from app.product import text_held
from app.standard_currency import CurrencyOut, currency_for

NOT_HELD_ICS = ("MetrIQ does not hold this standard's ICS code or its sectional committee: the BIS "
                "catalogue search MetrIQ read returns neither, and MetrIQ does not infer them.")
NO_CATALOGUE = ("MetrIQ holds no catalogue title for this standard: neither BIS's catalogue nor the "
                "Public.Resource.Org mirror resolved it (Phase 4), and MetrIQ does not guess one.")
NO_LISTING_DESCRIPTION = ("This record does not quote a product description from BIS's "
                          "compulsory-certification listing.")
NO_CURRENCY = "MetrIQ holds no edition evidence for this standard."
NO_LISTING_ORDER = ("BIS's compulsory-certification listing names no order for this standard in "
                    "MetrIQ's data (or its listing row did not match this record exactly).")
NO_SCOPE_IDENTITY = "MetrIQ holds this standard's identity but not its text, so it cannot quote its scope."
NO_SCOPE_CLAUSE = "MetrIQ holds clause text of this standard, but not its scope clause."
NO_REQUIREMENTS_IDENTITY = ("MetrIQ holds this standard's identity but not its text, so it cannot "
                            "show its requirement clauses.")
NO_REQUIREMENTS_CLAUSE = "MetrIQ holds no clause of this standard beyond its scope."

_DESCRIBED = re.compile(r'(?:The BIS list describes the product as|BIS product description): "(.+?)"')
_LISTED = re.compile(r"BIS lists the following products against this standard in the [^:]*list: (.+?)\.(?= |$)")


@lru_cache(maxsize=1)
def _standards() -> tuple[KnowledgeItem, ...]:
    return tuple(i for i in load_knowledge_base().items
                 if i.category == "indian_standards" and i.standard_number)


# ------------------------------------------------------------------ lookup


class PassportMatch(BaseModel):
    id: str
    standard_number: str
    title: str


def lookup(number: str) -> list[PassportMatch]:
    """The records a standard number names. Exact on number, part and section; a year,
    when given, must be equal. Never ranks, never picks among several."""
    wanted = standard_key(number)
    if wanted is None:
        return []
    found = []
    for item in _standards():
        key = standard_key(item.standard_number)
        same = (key and key.doc == wanted.doc and key.part == wanted.part
                and key.section == wanted.section and (not wanted.year or key.year == wanted.year))
        if same:
            found.append(PassportMatch(id=item.id, standard_number=item.standard_number, title=item.title))
    return found


# ------------------------------------------------------------------ passport


class IdentityOut(BaseModel):
    title: str
    standard_number: str
    cited_edition: str | None = Field(default=None, description="The year in the number as stored; null when none.")
    editions_known: list[str] = Field(default_factory=list, description="From Phase 5's edition evidence.")
    catalogue: dict | None = None
    catalogue_note: str = ""
    listing_description: str | None = Field(default=None, description="BIS's own product wording, quoted.")
    listing_note: str = ""
    listing_document: str | None = None
    listing_url: str | None = None
    ics_committee_note: str = NOT_HELD_ICS
    last_verified: str | None = None


class CoverageOut(BaseModel):
    level: str = Field(description='"CLAUSE" | "IDENTITY"')
    note: str
    clause_count: int = 0
    withheld: int | None = None
    completeness: str = ""


class LegalOut(BaseModel):
    qco: qco_module.QcoOut
    listing_orders: qco_module.ListingOrdersOut | None = None
    listing_note: str = ""


class ClausesSectionOut(BaseModel):
    clauses: list[dict] = Field(default_factory=list, description="Each as api.ClauseOut, verbatim.")
    note: str = ""


class SourceOut(BaseModel):
    label: str
    url: str


class StandardPassportOut(BaseModel):
    id: str
    standard_number: str
    identity: IdentityOut
    coverage: CoverageOut
    currency: CurrencyOut | None = None
    currency_note: str = ""
    legal: LegalOut
    scope: ClausesSectionOut
    requirements: ClausesSectionOut
    sources: list[SourceOut]


def _year(number: str) -> str | None:
    key = standard_key(number)
    return key.year or None if key else None


def build(record_id: str) -> StandardPassportOut | None:
    """The Passport for one indian_standards record, or None when the id is unknown."""
    from app.api import _catalogue_out, clause_out   # api imports this module

    item = next((i for i in _standards() if i.id == record_id), None)
    if item is None:
        return None
    number = item.standard_number or ""

    catalogue = _catalogue_out(item.content)
    described = _DESCRIBED.search(item.content)
    listed = _LISTED.search(item.content)
    listing_description = described.group(1) if described else (listed.group(1) if listed else None)
    currency = currency_for(number)
    identity = IdentityOut(
        title=item.title, standard_number=number, cited_edition=_year(number),
        editions_known=list(currency.editions) if currency else [],
        catalogue=catalogue.model_dump() if catalogue else None,
        catalogue_note="" if catalogue else NO_CATALOGUE,
        listing_description=listing_description,
        listing_note="" if listing_description else NO_LISTING_DESCRIPTION,
        listing_document=item.document_name, listing_url=item.source_url,
        last_verified=item.last_verified.isoformat() if item.last_verified else None,
    )

    level, note, scope_items = text_held(number)
    groups = clause_groups.groups_for(number)
    coverage = CoverageOut(level=level, note=note, clause_count=groups.clause_count,
                           withheld=groups.withheld, completeness=groups.completeness)

    listing = qco_module.listing_orders_for(number)
    legal = LegalOut(qco=qco_module.for_standard(number), listing_orders=listing,
                     listing_note="" if listing else NO_LISTING_ORDER)

    all_clauses = clauses.clauses_for(number)
    scope_ids = {c.id for c in scope_items}
    scope = ClausesSectionOut(
        clauses=[clause_out(c).model_dump() for c in scope_items],
        note="" if scope_items else (NO_SCOPE_IDENTITY if level == "IDENTITY" else NO_SCOPE_CLAUSE))
    rest = [c for c in all_clauses if c.id not in scope_ids]
    requirements = ClausesSectionOut(
        clauses=[clause_out(c).model_dump() for c in rest],
        note="" if rest else (NO_REQUIREMENTS_IDENTITY if level == "IDENTITY" else NO_REQUIREMENTS_CLAUSE))

    return StandardPassportOut(
        id=item.id, standard_number=number, identity=identity, coverage=coverage,
        currency=currency, currency_note="" if currency else NO_CURRENCY, legal=legal,
        scope=scope, requirements=requirements,
        sources=_sources(item, currency, legal, all_clauses),
    )


def _sources(item, currency, legal: LegalOut, all_clauses) -> list[SourceOut]:
    """Only sources stored with the evidence shown — the record's, the edition
    evidence's, the QCO rows', the listing's and its Gazette links, the clause mirror."""
    out: dict[str, str] = {}

    def add(url: str | None, label: str) -> None:
        if url and url not in out:
            out[url] = label

    add(item.source_url, item.document_name or "BIS source of this record")
    if currency:
        add(currency.source_url, currency.source_label)
    for row in legal.qco.rows:
        add(row.source_url, row.table)
    for group in (legal.listing_orders.groups if legal.listing_orders else []):
        add(group.source_url, f"BIS Scheme {group.scheme} listing")
        for order in group.orders:
            add(order.url, f"Gazette: {order.number or order.text}")
    if all_clauses:
        add(all_clauses[0].source_url, all_clauses[0].source_organization)
    return [SourceOut(label=label, url=url) for url, label in out.items()]
