"""Milestone 21 — the canonical product context.

MetrIQ connects evidence produced by its existing deterministic features into a
unified product context. **The context does not create new evidence and does not
independently verify external facts.**

    OCR / declarations / vision --------+
    deterministic identification -------+
    BIS retrieval ---------------------+--> CANONICAL PRODUCT CONTEXT --> views
    certification journey -------------+                                 --> copilot
    declaration completeness ----------+
    BIS LIMS laboratory snapshot ------+
    hallmark observations -------------+

This module is a COMPOSER. It contains no classifier, no ranking, no rule engine
and no model call. Every value it reports was produced by a module that already
existed; this file decides only which of them apply, says where each one came
from, and writes the deterministic summary.

Two entry points, with different trust properties — stated plainly because the
difference matters:

``build_from_query``     SERVER-DERIVED. The caller supplies a product
                         description or a standard number and nothing else.
                         MetrIQ runs its own retrieval, journey and laboratory
                         lookup. No client-supplied evidence is involved.

``build_from_analysis``  COMPOSED FROM A FINISHED ANALYSIS. The analysis comes
                         either from the database (server-side) or, on the live
                         inspection screen, echoed back by the client exactly as
                         ``/inspection/analyze`` produced it — the same trust
                         model the copilot's live path has always used. The
                         request model whitelists what may reach it.

Feature applicability is explicit, because "there is nothing here" and "this
does not apply to this product" are different facts:

    AVAILABLE       MetrIQ holds evidence for it
    NOT_AVAILABLE   the feature applies, but MetrIQ's verified data has nothing
    NOT_APPLICABLE  the feature does not apply to this product at all
    UNCERTAIN       evidence exists but does not settle the question
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

# ------------------------------------------------------------------ vocabulary

AVAILABLE = "AVAILABLE"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNCERTAIN = "UNCERTAIN"

PRODUCT = "PRODUCT"
STANDARD = "STANDARD"
CERTIFICATION = "CERTIFICATION"
INSPECTION = "INSPECTION"
LABORATORY = "LABORATORY"
HALLMARKING = "HALLMARKING"

FEATURES: tuple[str, ...] = (PRODUCT, STANDARD, CERTIFICATION, INSPECTION, LABORATORY, HALLMARKING)

# Where a fact came from. One of these is attached to every section, so a value
# on screen can always be traced back to the system that produced it.
USER_DESCRIPTION = "USER_DESCRIPTION"
OCR_TEXT = "OCR_TEXT"
DECLARATION = "DECLARATION"
VISION_OBSERVATION = "VISION_OBSERVATION"
DETERMINISTIC_RETRIEVAL = "DETERMINISTIC_RETRIEVAL"
BIS_KNOWLEDGE_BASE = "BIS_KNOWLEDGE_BASE"
DETERMINISTIC_RULE_ENGINE = "DETERMINISTIC_RULE_ENGINE"
LABORATORY_SNAPSHOT = "LABORATORY_SNAPSHOT"
HALLMARK_OBSERVATION = "HALLMARK_OBSERVATION"

# Reason codes the milestone requires to survive verbatim.
STANDARD_NOT_ESTABLISHED = "STANDARD_NOT_ESTABLISHED"
CERTIFICATION_ROUTE_NOT_AVAILABLE = "CERTIFICATION_ROUTE_NOT_AVAILABLE"

_MAX_LABS = 6
_MAX_CANDIDATES = 3


@dataclass(frozen=True)
class Section:
    """One feature's contribution. ``detail`` holds only keys that exist."""

    feature: str
    status: str
    headline: str
    reason_code: str = ""
    detail: dict = field(default_factory=dict)
    provenance: tuple[str, ...] = ()
    sources: tuple[dict, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductContext:
    origin: str  # "QUERY" | "INSPECTION"
    product_name: str | None
    product_status: str
    query: str = ""
    inspection_id: str | None = None
    sections: tuple[Section, ...] = ()
    conflicts: tuple[str, ...] = ()
    summary: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def section(self, feature: str) -> Section | None:
        return next((s for s in self.sections if s.feature == feature), None)

    @property
    def availability(self) -> dict[str, str]:
        return {s.feature: s.status for s in self.sections}


def _source(title, url=None, document=None, authority="BIS", reference=None) -> dict:
    return {"title": title, "source_url": url, "document_name": document,
            "authority": authority, "reference": reference}


def _dedupe(sources: list[dict]) -> tuple[dict, ...]:
    seen, out = set(), []
    for src in sources:
        key = (src.get("title"), src.get("source_url"))
        if key in seen:
            continue
        seen.add(key)
        out.append(src)
    return tuple(out)


# --------------------------------------------------------------- sections


def _product_section(analysis: dict) -> Section:
    """Product identity, exactly as the existing identification decided it."""
    product = analysis.get("product") or {}
    signals = product.get("signals") or {}
    status = product.get("status")
    vision = product.get("vision_status", "NOT_RUN")

    provenance = []
    if signals.get("ocr_supported"):
        provenance.append(OCR_TEXT)
    if signals.get("vision_supported"):
        provenance.append(VISION_OBSERVATION)
    if signals.get("knowledge_supported"):
        provenance.append(BIS_KNOWLEDGE_BASE)
    if (analysis.get("declaration_stage") or {}).get("fields"):
        provenance.append(DECLARATION)

    name = product.get("name")
    if status == "MATCHED" and name:
        state, headline = AVAILABLE, f"Identified as {name}."
    else:
        state = UNCERTAIN
        headline = (
            "Product identification did not settle on one product. "
            + (product.get("reason") or "")
        ).strip()

    detail = {
        "identification_status": status,
        "identification_confidence": product.get("confidence"),
        "method": product.get("method"),
        "reason": product.get("reason"),
        "evidence_sources": {
            "ocr_text": bool(signals.get("ocr_supported")),
            "visual_observation": bool(signals.get("vision_supported")),
            "knowledge_base": bool(signals.get("knowledge_supported")),
            "ocr_and_vision_agree": signals.get("agreement"),
        },
        "visual_observation_status": vision,
    }
    if product.get("unverified_standard_numbers"):
        detail["standard_numbers_printed_but_not_in_knowledge_base"] = (
            product["unverified_standard_numbers"][:5]
        )
    limitations = []
    if vision != "OK":
        limitations.append(
            "No visual observation contributed to this identification "
            f"(vision status {vision})."
        )
    return Section(PRODUCT, state, headline, detail=detail,
                   provenance=tuple(provenance) or (OCR_TEXT,),
                   limitations=tuple(limitations))


def _standard_section(standard_number, candidates, *, uncertain_identity: bool) -> Section:
    """The verified standard the EXISTING retrieval established. Never reranked."""
    if not standard_number:
        headline = (
            "No verified Indian Standard was established from the available evidence."
            if not candidates else
            "Several candidate standards were retrieved; none was established as the one that applies."
        )
        detail = {"candidates": candidates[:_MAX_CANDIDATES]} if candidates else {}
        return Section(STANDARD, UNCERTAIN if candidates else NOT_AVAILABLE, headline,
                       reason_code=STANDARD_NOT_ESTABLISHED, detail=detail,
                       provenance=(DETERMINISTIC_RETRIEVAL,),
                       limitations=("MetrIQ never generates a standard number. A standard is reported "
                                    "only when a verified knowledge-base record supports it.",))

    top = candidates[0] if candidates else {}
    status = UNCERTAIN if uncertain_identity else AVAILABLE
    # KB titles often start with the number itself; do not print it twice.
    title = (top.get("title") or "").strip()
    if title.lower().startswith(standard_number.lower()):
        title = title[len(standard_number):].lstrip(" -—:")
    headline = f"{standard_number} — {title or 'verified BIS knowledge-base record'}."
    if uncertain_identity:
        headline += " Reported as a candidate: product identification is not settled."
    detail = {
        "standard_number": standard_number,
        "title": top.get("title"),
        "retrieval_confidence": top.get("confidence"),
        "why_retrieved": top.get("why_retrieved"),
        "printed_on_label": top.get("printed_on_label"),
        "verification_status": top.get("verification_status"),
    }
    if len(candidates) > 1:
        detail["other_candidates"] = candidates[1:_MAX_CANDIDATES]
    sources = [_source(f"{standard_number} — {top.get('title') or ''}".strip(" —"),
                       top.get("source_url"), top.get("document_name"))] if top else []
    return Section(STANDARD, status, headline, detail=detail,
                   provenance=(DETERMINISTIC_RETRIEVAL, BIS_KNOWLEDGE_BASE),
                   sources=_dedupe(sources),
                   limitations=("Retrieval confidence is the strength of a text match against verified "
                                "BIS records. It is not a legal determination that the standard applies.",))


def _certification_section(journey: dict | None, standard_number: str | None) -> Section:
    """The Milestone 16 journey, linked — never inferred from a similar product."""
    if not standard_number:
        return Section(CERTIFICATION, NOT_AVAILABLE,
                       "No certification route can be looked up until a verified standard is established.",
                       reason_code=CERTIFICATION_ROUTE_NOT_AVAILABLE,
                       provenance=(BIS_KNOWLEDGE_BASE,))
    if not journey:
        return Section(CERTIFICATION, NOT_AVAILABLE,
                       f"MetrIQ holds no verified certification route information for {standard_number}.",
                       reason_code=CERTIFICATION_ROUTE_NOT_AVAILABLE,
                       provenance=(BIS_KNOWLEDGE_BASE,))

    scheme = journey.get("scheme") or {}
    verification = journey.get("verification_status")
    limitations = list(journey.get("limitations") or ())
    if verification == "INSUFFICIENT":
        return Section(
            CERTIFICATION, NOT_AVAILABLE,
            journey.get("message") or
            f"Verified certification information is not currently available for {standard_number}.",
            reason_code=CERTIFICATION_ROUTE_NOT_AVAILABLE,
            detail={"verification_status": verification,
                    "standard_selection": journey.get("standard_selection")},
            provenance=(BIS_KNOWLEDGE_BASE,),
            limitations=tuple(limitations),
        )

    status = AVAILABLE if verification == "VERIFIED" else UNCERTAIN
    headline = (
        f"{scheme.get('name') or 'A certification route'} is the route the verified BIS records state "
        f"for {standard_number}."
    )
    if scheme.get("conflict"):
        headline += " The verified sources disagree about the route; MetrIQ reports both."
    detail = {
        "verification_status": verification,
        "standard_selection": journey.get("standard_selection"),
        "scheme": scheme.get("name"),
        "mark": scheme.get("mark"),
        "conflict": scheme.get("conflict") or None,
        "steps": [{"order": s.get("order"), "title": s.get("title")}
                  for s in (journey.get("steps") or [])],
        "next_steps": list(journey.get("next_steps") or [])[:6],
    }
    sources = [
        _source(e.get("title"), e.get("source_url"), e.get("document_name"))
        for e in (journey.get("sources") or [])
    ]
    return Section(CERTIFICATION, status, headline, detail=detail,
                   provenance=(BIS_KNOWLEDGE_BASE,), sources=_dedupe(sources),
                   limitations=tuple(limitations))


def _inspection_section(analysis: dict | None, *, jewellery: bool) -> Section:
    """What the deterministic evidence pipeline established, linked. Nothing is
    recomputed and no legal/compliance verdict is produced here."""
    if analysis is None:
        return Section(INSPECTION, NOT_AVAILABLE,
                       "No package inspection has been run for this product.",
                       provenance=(DETERMINISTIC_RULE_ENGINE,))

    escalation = analysis.get("escalation") or {}
    product = analysis.get("product") or {}
    completeness = analysis.get("completeness") or {}

    if jewellery:
        headline = ("Package-label declaration checks do not apply to this item; "
                    "it is evaluated as a hallmark photograph instead.")
        status = NOT_APPLICABLE
    else:
        established = not escalation.get("required")
        status = AVAILABLE
        headline = (
            "MetrIQ established the product, standard and declaration evidence for this package from the photos."
            if established else
            f"MetrIQ could not establish {len(escalation.get('reasons') or [])} part(s) of the evidence chain "
            "from the photos; see the open items below."
        )

    detail = {
        "product_applicability": product.get("product_applicability"),
        "evidence_fully_established": not escalation.get("required"),
        "open_items": [r.get("code") for r in (escalation.get("reasons") or [])],
    }
    if completeness:
        detail["declarations"] = {
            "detected": completeness.get("detected"),
            "uncertain": completeness.get("uncertain"),
            "not_detected": completeness.get("not_detected"),
            "conflicts": completeness.get("conflicts"),
            "with_verified_requirement": completeness.get("with_verified_requirement"),
        }
    limitations = [
        "'Not detected' means the photographs did not show it. It is never reported as legally missing.",
        "MetrIQ reports observed evidence and verified knowledge; it does not produce a legal or compliance verdict.",
    ]
    return Section(INSPECTION, status, headline, detail=detail,
                   provenance=(DETERMINISTIC_RULE_ENGINE, OCR_TEXT, DECLARATION),
                   limitations=tuple(limitations))


def _laboratory_section(labs: list[dict], standard_number: str | None, coverage: dict | None,
                        other_editions: list[str] | None = None) -> Section:
    """BIS LIMS records, as at the snapshot. Never a current status, never ranked."""
    from app.lab_registry import CURRENTNESS_NOTE, NOT_AVAILABLE as LAB_NOT_AVAILABLE, SNAPSHOT_NOTE

    retrieved = (coverage or {}).get("retrieved_on")
    limitations = [
        SNAPSHOT_NOTE,
        CURRENTNESS_NOTE,
        "Ordering is alphabetical. MetrIQ does not rank laboratories.",
        f"A field the snapshot does not hold is reported as: {LAB_NOT_AVAILABLE} "
        "Address, telephone, e-mail, accreditation number and NABL status are not in the snapshot at all.",
        "BIS's Group-1 / Group-2 recognised-laboratory PDFs are not ingested, so MetrIQ's laboratory "
        "coverage is narrower than BIS's published picture.",
    ]
    if not standard_number:
        return Section(LABORATORY, NOT_AVAILABLE,
                       "Laboratories are looked up by standard, and no verified standard was established.",
                       reason_code=STANDARD_NOT_ESTABLISHED,
                       provenance=(LABORATORY_SNAPSHOT,), limitations=tuple(limitations))
    if not labs:
        return Section(
            LABORATORY, NOT_AVAILABLE,
            f"MetrIQ's laboratory snapshot holds no record listed against {standard_number}. "
            "That is a statement about MetrIQ's coverage, not about which laboratories exist.",
            detail={"snapshot_retrieved_on": retrieved,
                    "other_editions_listed_separately": list(other_editions or [])[:6]},
            provenance=(LABORATORY_SNAPSHOT,), limitations=tuple(limitations))

    detail = {
        "count": len(labs),
        "snapshot_retrieved_on": retrieved,
        "other_editions_listed_separately": list(other_editions or [])[:6],
        "laboratories": [
            {
                "lab_name": lab.get("lab_name"),
                "city": lab.get("city"),
                "standard_as_listed": lab.get("standard_as_listed"),
                "recognition_validity_as_at_snapshot": lab.get("validity_status"),
                "validity_date_as_listed": lab.get("validity_date"),
            }
            for lab in labs[:_MAX_LABS]
        ],
    }
    sources = [_source(lab.get("document_name"), lab.get("source_url"), lab.get("document_name"))
               for lab in labs[:_MAX_LABS] if lab.get("document_name")]
    return Section(
        LABORATORY, AVAILABLE,
        f"BIS LIMS lists {len(labs)} laboratory record(s) against {standard_number}, as at the "
        f"{retrieved or 'recorded'} snapshot. Being listed is the only relationship established.",
        detail=detail, provenance=(LABORATORY_SNAPSHOT,), sources=_dedupe(sources),
        limitations=tuple(limitations))


def _hallmark_section(hallmark: dict | None, *, jewellery: bool) -> Section:
    """Milestone 19 evidence, linked only when hallmarking is actually relevant."""
    if not jewellery:
        return Section(HALLMARKING, NOT_APPLICABLE,
                       "Hallmarking applies to gold and silver jewellery and artefacts. "
                       "It does not apply to this product.",
                       provenance=(HALLMARK_OBSERVATION,))
    if not hallmark:
        return Section(HALLMARKING, NOT_AVAILABLE,
                       "Hallmarking is relevant here, but MetrIQ holds no hallmark observation "
                       "for this product.",
                       provenance=(HALLMARK_OBSERVATION,))

    huid = hallmark.get("huid") or {}
    purity = hallmark.get("purity") or {}
    detail = {
        "detected": hallmark.get("detected"),
        "overall_status": hallmark.get("overall_status"),
        "verification_status": hallmark.get("verification_status"),
        "official_verification_required": hallmark.get("official_verification_required"),
        "huid": {"status": huid.get("status"), "potential_value_observed": huid.get("value")},
        "purity": {"status": purity.get("status"), "metal": purity.get("metal"),
                   "caratage": purity.get("caratage"), "fineness": purity.get("fineness")},
        "components_observed_in_the_photograph": [
            {"component": c.get("label"), "status": c.get("status")}
            for c in (hallmark.get("components") or [])
        ],
        "untrusted_claims_printed_on_the_item": len(hallmark.get("untrusted_claims") or []),
    }
    if hallmark.get("user_huid"):
        detail["user_provided_huid"] = {
            "comparison_with_ocr_text": (hallmark.get("user_huid") or {}).get("status"),
        }
    return Section(
        HALLMARKING,
        AVAILABLE if hallmark.get("detected") else NOT_AVAILABLE,
        ("Hallmark evidence was observed in the photograph. Observing a mark, a purity pair or a "
         "HUID-like code is not authentication." if hallmark.get("detected") else
         "No hallmark evidence was detected in the supplied photograph. That is a statement about "
         "the photograph, not about the article."),
        detail=detail, provenance=(HALLMARK_OBSERVATION, OCR_TEXT),
        limitations=(
            "MetrIQ does not authenticate a hallmark, a HUID, a jeweller registration or an "
            "Assaying and Hallmarking Centre. Official verification is required.",
            "A user-supplied HUID is compared as text only; a match establishes nothing about the article.",
            "The BIS logo is a graphic. OCR reads text, so the logo can never be confirmed by MetrIQ.",
        ))


# ---------------------------------------------------------------- conflicts


def _conflicts(analysis: dict, standard_number: str | None, candidates: list[dict]) -> tuple[str, ...]:
    """Disagreements the existing features already recorded. Never resolved here."""
    out: list[str] = []
    signals = (analysis.get("product") or {}).get("signals") or {}
    out.extend(signals.get("conflicts") or [])

    if signals.get("agreement") is True:
        out.append("The label text and the visual observation agree on the product. Agreement between "
                   "two observations is not verification.")

    printed = [c for c in candidates if c.get("printed_on_label")]
    if standard_number and any(c.get("standard_number") == standard_number for c in printed):
        out.append(f"The standard printed on the package and the standard retrieved from the verified "
                   f"knowledge base agree ({standard_number}).")
    unverified = (analysis.get("product") or {}).get("unverified_standard_numbers") or []
    if unverified:
        out.append("Standard number(s) printed on the package have no verified knowledge-base record: "
                   + ", ".join(unverified[:3]) + ".")
    return tuple(dict.fromkeys(out))


# ------------------------------------------------------------------ summary


def _summary(context_parts: dict) -> tuple[str, ...]:
    """The canonical summary. Deterministic, written from structured data only —
    no model is involved in producing it (a model may explain it afterwards)."""
    lines = []
    for feature, label in ((PRODUCT, "Product"), (STANDARD, "Standard"), (CERTIFICATION, "Certification"),
                           (INSPECTION, "Inspection"), (LABORATORY, "Laboratories"),
                           (HALLMARKING, "Hallmarking")):
        section = context_parts.get(feature)
        if section is None:
            continue
        lines.append(f"{label}: {section.status} — {section.headline}")
    return tuple(lines)


def _assemble(origin, *, product_name, product_status, sections, conflicts, query="",
              inspection_id=None) -> ProductContext:
    limitations: list[str] = []
    for section in sections:
        for item in section.limitations:
            if item not in limitations:
                limitations.append(item)
    return ProductContext(
        origin=origin,
        product_name=product_name,
        product_status=product_status,
        query=query,
        inspection_id=inspection_id,
        sections=tuple(sections),
        conflicts=tuple(conflicts),
        summary=_summary({s.feature: s for s in sections}),
        limitations=tuple(limitations),
    )


# --------------------------------------------------------- from an analysis


def _candidates_from_analysis(analysis: dict) -> list[dict]:
    return [
        {
            "standard_number": s.get("standard_number"),
            "title": s.get("title"),
            "confidence": s.get("confidence"),
            "printed_on_label": s.get("printed_on_label"),
            "why_retrieved": (s.get("why") or {}).get("summary"),
            "verification_status": s.get("verification_status"),
            "source_url": s.get("source_url"),
            "document_name": s.get("document_name"),
        }
        for s in (analysis.get("standards") or [])
    ]


def build_from_analysis(analysis: dict) -> ProductContext:
    """Compose a finished inspection into the canonical context. Nothing is rerun."""
    product = analysis.get("product") or {}
    hallmark = analysis.get("hallmark") or None
    jewellery = (
        analysis.get("inspection_type") == "HALLMARK"
        or bool((hallmark or {}).get("detected"))
    )

    candidates = _candidates_from_analysis(analysis)
    standard_number = product.get("standard_number")
    uncertain_identity = product.get("status") != "MATCHED"

    sections = [
        _product_section(analysis),
        _standard_section(standard_number, candidates, uncertain_identity=uncertain_identity),
        _certification_section(analysis.get("certification"), standard_number),
        _inspection_section(analysis, jewellery=jewellery),
        _laboratory_section(analysis.get("laboratories") or [], standard_number,
                            {"retrieved_on": (analysis.get("laboratories") or [{}])[0].get("retrieved_on")}
                            if analysis.get("laboratories") else None),
        _hallmark_section(hallmark, jewellery=jewellery),
    ]
    return _assemble(
        "INSPECTION",
        product_name=product.get("name"),
        product_status=product.get("status") or "REVIEW",
        sections=sections,
        conflicts=_conflicts(analysis, standard_number, candidates),
        inspection_id=analysis.get("inspection_id"),
    )


# ------------------------------------------------------------ from a query


def _is_jewellery_record(item) -> bool:
    from app.requirements import JEWELLERY_HALLMARKING, knowledge_domain

    return knowledge_domain(item) == JEWELLERY_HALLMARKING


def _hallmarking_is_relevant(engine, query: str, top_item) -> bool:
    """Is this a hallmarking subject at all?

    Answered by the EXISTING retrieval engine, not by a new classifier: MetrIQ
    asks which verified records the words reach. A jewellery standard, or a
    knowledge base whose best record for these words is a hallmarking record,
    makes hallmarking relevant; anything else does not.
    """
    if top_item is not None and _is_jewellery_record(top_item):
        return True
    if not query:
        return False
    try:
        results = engine.search(query, limit=1).results
    except Exception:  # noqa: BLE001 — applicability must never break the context
        return False
    return bool(results) and _is_jewellery_record(results[0].item)


def build_from_query(
    query: str,
    *,
    finder,
    journey_service=None,
    registry=None,
    standard_number: str = "",
) -> ProductContext:
    """Compose a context for a product that has NOT been inspected.

    Server-derived: the caller supplies only text. MetrIQ runs its EXISTING
    retrieval, its existing journey builder and its existing laboratory lookup.
    """
    from app.product import explain_candidate

    query = (query or "").strip()
    standard_number = (standard_number or "").strip()

    results = []
    if standard_number:
        outcome = finder.search_engine.search(standard_number, limit=5)
        wanted = standard_number.lower().split(":")[0]
        results = [r for r in outcome.results
                   if r.item.category == "indian_standards" and r.item.standard_number
                   and r.item.standard_number.lower().split(":")[0] == wanted]
    elif query:
        outcome = finder.find(query, limit=5)
        results = list(outcome.results) if outcome.grounded else []

    candidates = [
        {
            "standard_number": r.item.standard_number,
            "title": r.item.title,
            "confidence": r.confidence,
            "printed_on_label": False,
            "why_retrieved": explain_candidate(r).summary,
            "verification_status": r.item.verification_status,
            "source_url": r.item.source_url,
            "document_name": r.item.document_name,
        }
        for r in results
    ]
    top = results[0] if results else None
    # One confident candidate is an established standard; several equally ranked
    # ones are NOT silently resolved into one.
    settled = bool(top) and (len(results) == 1 or top.confidence == "high")
    resolved_number = top.item.standard_number if (top and settled) else None

    journey = None
    if resolved_number and journey_service is not None:
        try:
            from app.certification_journey import journey_out

            journey = journey_out(journey_service.build(standard_number=resolved_number)).model_dump(mode="json")
        except Exception:  # noqa: BLE001 — guidance never breaks the context
            journey = None

    labs, other_editions, lab_coverage = [], [], None
    if resolved_number and registry is not None:
        try:
            for match in registry.for_standard(resolved_number)[:_MAX_LABS]:
                record = match.record
                status, iso = record.validity()
                labs.append({
                    "lab_name": record.lab_name, "city": record.city,
                    "standard_as_listed": record.standard_as_listed,
                    "validity_status": status, "validity_date": iso,
                    "source_url": record.source_url, "document_name": record.document_name,
                    "retrieved_on": record.retrieved_on,
                })
            other_editions = registry.other_editions(resolved_number)
            lab_coverage = registry.coverage()
        except Exception:  # noqa: BLE001 — informational only
            labs, other_editions, lab_coverage = [], [], None

    jewellery = _hallmarking_is_relevant(finder.search_engine, query,
                                         top.item if top else None)

    product_section = Section(
        PRODUCT, UNCERTAIN,
        f"MetrIQ has not identified this product from evidence; “{query or standard_number}” is the "
        "description you supplied. Product identification runs on photographs of the item.",
        detail={"described_as": query or standard_number,
                "knowledge_base_product_description": (top.item.title if top else None)},
        provenance=(USER_DESCRIPTION,),
        limitations=("A typed description is not evidence about a physical item. Upload photographs to "
                     "have MetrIQ identify the product from OCR, declarations and a visual observation.",),
    )

    sections = [
        product_section,
        _standard_section(resolved_number, candidates, uncertain_identity=False),
        _certification_section(journey, resolved_number),
        _inspection_section(None, jewellery=jewellery),
        _laboratory_section(labs, resolved_number, lab_coverage, other_editions),
        _hallmark_section(None, jewellery=jewellery),
    ]
    return _assemble(
        "QUERY",
        product_name=None,
        product_status="NOT_IDENTIFIED",
        sections=sections,
        conflicts=(),
        query=query or standard_number,
    )


# ------------------------------------------------------------------- output


class ContextSourceOut(BaseModel):
    title: str | None = None
    source_url: str | None = None
    document_name: str | None = None
    authority: str = "BIS"
    reference: str | None = None


class ContextSectionOut(BaseModel):
    feature: str = Field(description="PRODUCT | STANDARD | CERTIFICATION | INSPECTION | LABORATORY | HALLMARKING")
    status: str = Field(description="AVAILABLE | NOT_AVAILABLE | NOT_APPLICABLE | UNCERTAIN")
    headline: str
    reason_code: str = ""
    detail: dict = Field(default_factory=dict, description="Only fields that exist. Never a placeholder.")
    provenance: list[str] = Field(default_factory=list, description="Which MetrIQ system produced this.")
    sources: list[ContextSourceOut] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ProductContextOut(BaseModel):
    """The canonical product context. Composed from existing evidence — never new evidence."""

    origin: str = Field(description='"QUERY" (server-derived) | "INSPECTION" (composed from a finished analysis)')
    query: str = ""
    inspection_id: str | None = None
    product_name: str | None = None
    product_status: str
    availability: dict[str, str]
    sections: list[ContextSectionOut]
    conflicts: list[str] = Field(default_factory=list,
                                 description="Disagreements the features recorded. Never resolved here.")
    summary: list[str] = Field(default_factory=list,
                               description="Deterministic summary, written from structured data only.")
    limitations: list[str] = Field(default_factory=list)
    note: str = (
        "MetrIQ connects evidence produced by its existing deterministic features into a unified "
        "product context. The context does not create new evidence and does not independently "
        "verify external facts."
    )


def context_out(context: ProductContext) -> ProductContextOut:
    return ProductContextOut(
        origin=context.origin,
        query=context.query,
        inspection_id=context.inspection_id,
        product_name=context.product_name,
        product_status=context.product_status,
        availability=context.availability,
        sections=[
            ContextSectionOut(
                feature=s.feature, status=s.status, headline=s.headline, reason_code=s.reason_code,
                detail=s.detail, provenance=list(s.provenance),
                sources=[ContextSourceOut(**src) for src in s.sources],
                limitations=list(s.limitations),
            )
            for s in context.sections
        ],
        conflicts=list(context.conflicts),
        summary=list(context.summary),
        limitations=list(context.limitations),
    )
