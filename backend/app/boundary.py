"""An informative abstention: what MetrIQ's verified data covers, and what it does not.

When retrieval finds nothing for a product, "no results" tells the user nothing.
This module turns that dead end into a statement of MetrIQ's own boundary:

    what the verified data covers (with the real numbers, counted here)
    -> what the search actually did
    -> why the boundary sits where it does
    -> where to look next
    -> any weak match, labelled as evidence and NOT as an answer

Every sentence is MetrIQ's own, written by code and translated in
``app/language.py`` alongside the other hard-coded messages — no model is
involved, so there is nothing to invent. The counts are read from the knowledge
base at load time rather than typed in, so they cannot drift away from the data.

WHAT THIS MODULE DELIBERATELY DOES NOT SAY
------------------------------------------
It never says "this product is not on BIS's lists", and it never names a
category, sector or scheme for the unknown product. MetrIQ cannot tell at
runtime which of two situations it is in:

  * the product genuinely is not on the two BIS listing pages this data came
    from (shampoo, school bag, mixer grinder, biscuits — checked: zero records), or
  * it IS listed, under wording the query did not match. "refrigerator" retrieves
    nothing although BIS lists "Household Refrigerating Appliances-
    Characteristics and Test Methods" (IS 17550 (Part 1): 2021) and "Freezers"
    (IS 7872: 2018); "solar panel" retrieves solar WATER HEATING records although
    BIS lists "Crystalline Silicon Terrestrial Photovoltaic (PV) modules"
    (IS 14286) and the thin-film equivalent (IS 16077). The records say
    "refrigerating" and "photovoltaic"; the consumer says "refrigerator" and
    "solar panel", and the lexical engine does not stem or map between them.

Asserting the first when it is really the second would be a false claim about
BIS's own listings. So the message states both possibilities and resolves
neither — and says explicitly that this is NOT a statement that no Indian
Standard exists for the product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app import language as lang
from app import qco as qco_module
from app.knowledge.schema import KnowledgeItem

# BIS's Know Your Standards search — the official place to look for a standard by
# product name, and the one next step MetrIQ offers.
KNOW_YOUR_STANDARDS = "https://www.services.bis.gov.in/php/BIS_2.0/bisconnect/knowyourstandards/Indian_standards/isdetails/"

# How many products BIS notifies under compulsory certification in total, and how
# many sit in Quality Control Orders outside the two listing pages this dataset
# was transcribed from. Recorded in CLAUDE.md's 2026-09-24 knowledge-expansion
# note; approximate, and said as approximate.
NOTIFIED_PRODUCTS = 769
PRODUCTS_OUTSIDE_THE_LISTINGS = 273

_LISTED_PRODUCT = re.compile(r'The BIS list describes the product as: "(.+?)"')


@dataclass(frozen=True)
class WeakMatch:
    """A record retrieval reached by a partial word match only.

    Carried so the user can see what the search did. It is never an answer, and
    every surface that renders it says so.
    """

    standard_number: str | None
    title: str
    confidence: str
    matched_terms: list[str]
    source_url: str | None = None


@dataclass(frozen=True)
class Boundary:
    """MetrIQ's own explanation of why it did not answer."""

    language: str
    heading: str
    lines: list[str]
    next_step: str
    next_step_url: str
    weak_heading: str = ""
    weak_note: str = ""
    weak_matches: list[WeakMatch] = field(default_factory=list)


@dataclass(frozen=True)
class Coverage:
    """What the verified knowledge base actually holds, counted from it."""

    standards: int
    scheme_i: int
    scheme_ii: int
    products: int
    legal_metrology: int
    # Records from official BIS pages other than the two compulsory-certification
    # listings (Know Your Standards, advisories, product manuals).
    other: int


def measure(items: list[KnowledgeItem]) -> Coverage:
    """Count the coverage figures straight off the loaded knowledge base."""
    standards = [i for i in items if i.category == "indian_standards" and i.standard_number]
    products = {
        found.group(1)
        for i in standards
        if (found := _LISTED_PRODUCT.search(i.content))
    }
    return Coverage(
        standards=len(standards),
        scheme_i=sum(1 for i in standards if "Scheme I (ISI Mark)" in i.content),
        scheme_ii=sum(1 for i in standards if "Scheme II" in i.content),
        products=len(products),
        legal_metrology=sum(1 for i in items if i.category == "legal_metrology"),
        other=sum(1 for i in standards
                  if "Scheme I (ISI Mark)" not in i.content and "Scheme II" not in i.content),
    )


@lru_cache(maxsize=8)
def _cached(key: tuple) -> Coverage:
    return Coverage(*key)


def explain(
    product: str,
    coverage: Coverage,
    language: str = lang.EN,
    weak_matches: list[WeakMatch] | None = None,
) -> Boundary:
    """Build the abstention message. Deterministic; no model, no network."""
    text = lang.boundary(language)
    weak = list(weak_matches or [])

    lines = [
        text["covers"].format(
            standards=coverage.standards,
            scheme_i=coverage.scheme_i,
            scheme_ii=coverage.scheme_ii,
            products=coverage.products,
            legal_metrology=coverage.legal_metrology,
            other=coverage.other,
        ),
        text["not_found"].format(product=product.strip()),
        text["two_reasons"],
        # Phase 9: a row of BIS's QCO table whose product wording contains the user's
        # WHOLE multi-word product phrase is quoted — never a single-word match.
        *qco_module.boundary_sentences(qco_module.phrase_of(product), language),
        text["why_boundary"].format(
            notified=NOTIFIED_PRODUCTS,
            outside=PRODUCTS_OUTSIDE_THE_LISTINGS,
        ),
    ]

    return Boundary(
        language=language,
        heading=text["heading"],
        lines=lines,
        next_step=text["where_next"],
        next_step_url=KNOW_YOUR_STANDARDS,
        weak_heading=text["weak_heading"] if weak else "",
        weak_note=text["weak_body"] if weak else "",
        weak_matches=weak,
    )


def weak_matches_from(results, limit: int = 3) -> list[WeakMatch]:
    """Turn retrieval results MetrIQ is NOT putting forward into WeakMatch rows."""
    return [
        WeakMatch(
            standard_number=result.item.standard_number,
            title=result.item.title,
            confidence=result.confidence,
            matched_terms=list(result.matched_terms),
            source_url=result.item.source_url,
        )
        for result in results[:limit]
    ]
