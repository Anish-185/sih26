"""Certification journey: product -> standard -> scheme -> what to do next.

Deterministic. No LLM, no model of any kind. Every factual sentence a journey
shows is a WORD-FOR-WORD QUOTE from a verified knowledge-base record, together
with that record's official BIS URL. MetrIQ only decides which quotes are
relevant and what order to put them in; it never writes a requirement, a fee, a
timeline, a document list or a scheme of its own.

    product / standard number
          -> ProductStandardFinder      (Phase 5 retrieval + Phase 9 "why")
          -> resolve_scheme             (from each record's own verified text)
          -> journey steps              (quotes from the scheme's records)
          -> next steps + official sources
          -> verification status

How a scheme is established — two independent readings of verified text, never
a guess:

1. PROVENANCE. A standard record transcribed from BIS's own "Products under
   Compulsory Certification" listing carries that listing in `document_name`.
   Being on the Scheme I listing IS the statement that the route is Scheme I.
2. A STANDARD-SPECIFIC CERTIFICATION RECORD. A `certification` record whose text
   names this standard number and states a scheme (for example the packaged
   drinking water record, which says "Licences are granted under Scheme I").

Agreement, or only one of the two, establishes the scheme. Disagreement is
reported as a conflict and the journey drops to PARTIAL: MetrIQ does not choose.
Neither -> the scheme is not established and the status is INSUFFICIENT.

What this module will never do: say a product or manufacturer IS certified, say
a licence exists, invent a licence or scheme number, state a fee amount or a
processing time, or decide a legal obligation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.product import ProductStandardFinder, WhyThisResult, explain_candidate
from app.requirements import knowledge_domain, JEWELLERY_HALLMARKING
from app.retrieval import RetrievalResult, SearchEngine
from app.qco import QcoOut
from app.qco import for_standard as qco_for_standard
from app.standard_currency import CurrencyOut, currency_for

# ------------------------------------------------------------------ statuses

VERIFIED = "VERIFIED"
PARTIAL = "PARTIAL"
INSUFFICIENT = "INSUFFICIENT"

CONFIRMED = "CONFIRMED"
MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
NOT_IDENTIFIED = "NOT_IDENTIFIED"

INSUFFICIENT_MESSAGE = (
    "Certification guidance is limited because verified certification "
    "information is not currently available for this standard."
)
NO_STANDARD_MESSAGE = (
    "No verified Indian Standard was retrieved for this product, so no "
    "certification route can be established from the knowledge base."
)

# ------------------------------------------------------------------- schemes

SCHEME_I = "SCHEME_I"
SCHEME_II = "SCHEME_II"
SCHEME_IV = "SCHEME_IV"
HALLMARKING = "HALLMARKING"

SCHEME_NAMES = {
    SCHEME_I: "Scheme I — licence to use the Standard Mark (ISI Mark)",
    SCHEME_II: "Scheme II — Compulsory Registration Scheme (CRS)",
    SCHEME_IV: "Scheme IV — Certificate of Conformity (CoC)",
    HALLMARKING: "Hallmarking of gold and silver articles",
}
SCHEME_MARKS = {
    SCHEME_I: "Standard Mark (ISI Mark), under a licence",
    SCHEME_II: "BIS Registration Mark, with a unique R-number",
    SCHEME_IV: "Standard Mark, under a Certificate of Conformity",
    HALLMARKING: "BIS hallmark (BIS logo, purity, and a six-digit HUID)",
}

# A BIS compulsory-certification listing in `document_name` names the scheme the
# record was transcribed from. Matched on the listing's scheme wording only.
_PROVENANCE = (
    (SCHEME_II, re.compile(r"scheme\s*ii\b", re.I)),
    (SCHEME_IV, re.compile(r"scheme\s*iv\b", re.I)),
    (SCHEME_I, re.compile(r"scheme\s*i\b", re.I)),
)
# The same wording, read out of a certification record's own prose.
_IN_TEXT = (
    (SCHEME_II, re.compile(r"\bScheme\s*II\b")),
    (SCHEME_IV, re.compile(r"\bScheme\s*IV\b")),
    (SCHEME_I, re.compile(r"\bScheme\s*I\b")),
)

# The verified records whose quotes make up each scheme's journey, in the order
# the steps are presented. (step title, knowledge id, the phrase the quote must
# start from). A record that is missing, unverified, or whose text no longer
# contains the phrase is simply left out — the step then disappears rather than
# being filled in by MetrIQ.
_STEPS: dict[str, tuple[tuple[str, str, str], ...]] = {
    SCHEME_I: (
        ("Confirm the product is under compulsory certification",
         "products-under-compulsory-certification-scheme-i",
         "BIS publishes a list of products that require the ISI Mark"),
        ("Check the Quality Control Order that makes it mandatory",
         "quality-control-orders",
         "A Quality Control Order (QCO) is a notification issued by the Central Government"),
        ("Understand what BIS assesses before granting the licence",
         "standard-mark-isi-mark",
         "BIS states that under Scheme I a licence to use the Standard Mark"),
        ("Follow the official BIS guidelines for this scheme",
         "scheme-i-licence-process-guidelines",
         "BIS operates product certification for the Standard Mark under Scheme-I"),
        ("Apply through the official BIS portal",
         "bis-certification-online-application-portals",
         "BIS takes certification applications online through its own portals."),
        ("Check the fee BIS publishes for this standard",
         "bis-certification-fee-is-published-by-bis",
         "BIS publishes its fees rather than quoting them case by case."),
    ),
    SCHEME_II: (
        ("Confirm the product is under compulsory registration",
         "products-under-compulsory-registration-scheme-ii",
         "BIS publishes a list of electronics and IT goods that require BIS registration"),
        ("Check the legal basis and what registration grants",
         "crs-legal-basis-and-registration-mark",
         "The BIS CRS portal states that the Compulsory Registration Scheme is operated under"),
        ("Check who may apply",
         "crs-who-can-apply",
         "The BIS CRS portal states who may apply:"),
        ("Understand how the CRS route differs from the ISI Mark",
         "isi-mark-vs-crs-registration",
         "BIS operates two distinct routes for products under compulsory certification."),
        ("Apply through the official BIS CRS portal",
         "compulsory-registration-scheme-crs",
         "The Compulsory Registration Scheme (CRS) operates under Scheme II"),
        ("Check the fee BIS publishes for registration",
         "bis-certification-fee-is-published-by-bis",
         "BIS publishes its fees rather than quoting them case by case."),
    ),
    SCHEME_IV: (
        ("Understand the Certificate of Conformity route",
         "certificate-of-conformity",
         "For some compulsory-certification products the Central Government directs use"),
        ("Check the Quality Control Order that makes it mandatory",
         "quality-control-orders",
         "A Quality Control Order (QCO) is a notification issued by the Central Government"),
        ("Follow the official BIS guidelines for this scheme",
         "scheme-iv-coc-process-guidelines",
         "BIS operates the Certificate of Conformity route under Scheme-IV"),
        ("Apply through the official BIS portal",
         "bis-certification-online-application-portals",
         "BIS takes certification applications online through its own portals."),
    ),
    HALLMARKING: (
        ("Hallmarking is a separate BIS conformity assessment activity",
         "hallmarking-is-a-conformity-assessment-activity",
         "In addition to product certification, BIS runs hallmarking"),
    ),
}

# Added to every journey whose applicant may be outside India.
_FOREIGN_STEP = ("If the manufacturer is located outside India",
                 "foreign-manufacturers-certification-scheme-fmcs",
                 "The Foreign Manufacturers Certification Scheme (FMCS) is the route")


# ------------------------------------------------------------------- results

@dataclass(frozen=True)
class Evidence:
    """One verified record quoted word for word, with its official source."""

    knowledge_id: str
    title: str
    quote: str
    source_organization: str
    source_url: str | None
    document_name: str | None
    last_verified: str | None


@dataclass(frozen=True)
class JourneyStep:
    order: int
    title: str
    evidence: list[Evidence]


@dataclass(frozen=True)
class SchemeMatch:
    """Which BIS scheme the verified records say applies, and how we know."""

    scheme: str
    name: str
    mark: str
    basis: list[str]          # plain sentences: how the scheme was established
    evidence: list[Evidence]  # the records that establish it
    conflict: str = ""        # non-empty when the two readings disagree


@dataclass(frozen=True)
class Candidate:
    """One retrieved standard, with the existing Phase 9 explanation."""

    standard_number: str | None
    title: str
    knowledge_id: str
    confidence: str
    score: float
    source_url: str | None
    why: WhyThisResult


@dataclass(frozen=True)
class CertificationJourney:
    query: str
    product: str | None
    standard_selection: str            # CONFIRMED | MULTIPLE_CANDIDATES | NOT_IDENTIFIED
    standard_number: str | None
    standard_title: str | None
    candidates: list[Candidate]
    scheme: SchemeMatch | None
    verification_status: str           # VERIFIED | PARTIAL | INSUFFICIENT
    steps: list[JourneyStep]
    next_steps: list[str]
    why: list[str]
    limitations: list[str]
    sources: list[Evidence]
    message: str = ""
    disclaimer: str = (
        "This is certification guidance retrieved from published BIS information. "
        "It is not a statement that this product, manufacturer or any particular "
        "item is certified or holds a BIS licence, and it is not a legal "
        "determination. Confirm the applicable requirement with BIS."
    )
    grounded: bool = field(default=False)


# ------------------------------------------------------------------ helpers

def _evidence(item, quote: str) -> Evidence:
    return Evidence(
        knowledge_id=item.id,
        title=item.title,
        quote=quote,
        source_organization=item.source_organization,
        source_url=item.source_url,
        document_name=item.document_name,
        last_verified=item.last_verified.isoformat() if item.last_verified else None,
    )


def _sentence_from(item, phrase: str) -> str | None:
    """The sentence of `item.content` that starts with `phrase`, word for word.

    Returns None when the record no longer contains the phrase, so a reworded
    record drops its step instead of being paraphrased by MetrIQ.
    """
    start = item.content.find(phrase)
    if start < 0:
        return None
    end = item.content.find(". ", start + len(phrase))
    return item.content[start:] if end < 0 else item.content[start:end + 1]


def _standard_in(text: str, standard_number: str) -> bool:
    """True when `text` names this standard. Compared on digits and parts, so
    'IS 14543' matches 'IS 14543:2016' but never 'IS 145431'."""
    number = standard_number.split(":")[0].strip()
    if not number:
        return False
    return re.search(rf"{re.escape(number)}(?![0-9])", text) is not None


# ---------------------------------------------------------- scheme resolution

def resolve_scheme(item, knowledge_items) -> SchemeMatch | None:
    """Which scheme the verified records state for this standard. Deterministic."""
    by_id = {i.id: i for i in knowledge_items}

    if knowledge_domain(item) == JEWELLERY_HALLMARKING:
        source = by_id.get("hallmarking-is-a-conformity-assessment-activity")
        if source is None or source.verification_status != "verified":
            return None
        return SchemeMatch(
            scheme=HALLMARKING, name=SCHEME_NAMES[HALLMARKING], mark=SCHEME_MARKS[HALLMARKING],
            basis=[f"'{item.title}' is a jewellery hallmarking standard, which BIS runs as a separate "
                   "conformity assessment activity from product certification."],
            evidence=[_evidence(source, source.content)],
        )

    from_provenance = from_record = None
    basis: list[str] = []
    evidence: list[Evidence] = []

    document = item.document_name or ""
    if "compulsory certification" in document.lower():
        for scheme, pattern in _PROVENANCE:
            if pattern.search(document):
                from_provenance = scheme
                basis.append(
                    f"This record was transcribed from BIS's own listing \"{document}\", so BIS itself "
                    f"lists {item.standard_number} under {SCHEME_NAMES[scheme]}."
                )
                evidence.append(_evidence(item, item.content))
                break

    # A certification record that names this standard and states a scheme.
    for cert in knowledge_items:
        if cert.category != "certification" or cert.verification_status != "verified":
            continue
        if not item.standard_number or not _standard_in(cert.content, item.standard_number):
            continue
        for scheme, pattern in _IN_TEXT:
            if pattern.search(cert.content):
                from_record = scheme
                basis.append(
                    f"The verified record '{cert.title}' names {item.standard_number} and states "
                    f"{SCHEME_NAMES[scheme]}."
                )
                evidence.append(_evidence(cert, cert.content))
                break
        if from_record:
            break

    if from_provenance and from_record and from_provenance != from_record:
        return SchemeMatch(
            scheme=from_provenance, name=SCHEME_NAMES[from_provenance], mark=SCHEME_MARKS[from_provenance],
            basis=basis, evidence=evidence,
            conflict=(
                f"Two verified records disagree about the route for {item.standard_number}: the BIS listing "
                f"it was transcribed from indicates {SCHEME_NAMES[from_provenance]}, while another verified "
                f"record states {SCHEME_NAMES[from_record]}. MetrIQ does not choose between them — confirm "
                "with BIS."
            ),
        )

    scheme = from_provenance or from_record
    if scheme is None:
        return None
    return SchemeMatch(scheme=scheme, name=SCHEME_NAMES[scheme], mark=SCHEME_MARKS[scheme],
                       basis=basis, evidence=evidence)


def build_steps(scheme: str, knowledge_items) -> list[JourneyStep]:
    """The journey's steps, each one a quote from a verified record."""
    by_id = {i.id: i for i in knowledge_items}
    plan = list(_STEPS.get(scheme, ()))
    if scheme in (SCHEME_I, SCHEME_II, SCHEME_IV):
        plan.append(_FOREIGN_STEP)

    steps: list[JourneyStep] = []
    for title, knowledge_id, phrase in plan:
        source = by_id.get(knowledge_id)
        if source is None or source.verification_status != "verified":
            continue
        quote = _sentence_from(source, phrase)
        if quote is None:
            continue
        steps.append(JourneyStep(order=len(steps) + 1, title=title, evidence=[_evidence(source, quote)]))
    return steps


# ------------------------------------------------------------------- service

class CertificationJourneyService:
    """Builds a certification journey. Deterministic; never calls a model."""

    def __init__(self, search_engine: SearchEngine, product_finder: ProductStandardFinder,
                 max_candidates: int = 5) -> None:
        self.search_engine = search_engine
        self.product_finder = product_finder
        self.max_candidates = max_candidates

    # ----------------------------------------------------------- standard(s)

    def _by_standard_number(self, standard_number: str) -> list[RetrievalResult]:
        outcome = self.search_engine.search(standard_number, limit=self.max_candidates)
        wanted = standard_number.strip().lower()
        exact = [
            r for r in outcome.results
            if r.item.category == "indian_standards" and r.item.standard_number
            and r.item.standard_number.lower().split(":")[0] == wanted.split(":")[0]
        ]
        return exact or [r for r in outcome.results if r.item.category == "indian_standards"][:1]

    def _candidates(self, query: str, standard_number: str) -> tuple[list[RetrievalResult], str | None]:
        """(retrieved standard records, product label). Reuses Phase 5 retrieval."""
        if standard_number.strip():
            return self._by_standard_number(standard_number), None
        outcome = self.product_finder.find(query, limit=self.max_candidates)
        if not outcome.grounded:
            return [], None
        return list(outcome.results), outcome.product

    # ---------------------------------------------------------------- build

    def build(self, query: str = "", standard_number: str = "") -> CertificationJourney:
        query = query.strip()
        standard_number = standard_number.strip()
        items = self.search_engine.items

        results, product = self._candidates(query, standard_number)
        candidates = [
            Candidate(
                standard_number=r.item.standard_number, title=r.item.title, knowledge_id=r.item.id,
                confidence=r.confidence, score=r.score, source_url=r.item.source_url,
                why=explain_candidate(r),
            )
            for r in results
        ]

        if not results:
            return CertificationJourney(
                query=query or standard_number, product=None, standard_selection=NOT_IDENTIFIED,
                standard_number=None, standard_title=None, candidates=[], scheme=None,
                verification_status=INSUFFICIENT, steps=[],
                next_steps=[
                    "Describe the product in more detail, or give its Indian Standard number.",
                    "Search BIS's own list of products under compulsory certification: "
                    "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/"
                    "scheme-i-mark-scheme/?lang=en",
                ],
                why=["No verified Indian Standard record matched this query, so there is nothing to base a "
                     "certification route on."],
                limitations=["MetrIQ holds a curated subset of BIS information, not complete BIS coverage. "
                             "A product missing here is not a statement that no standard applies to it."],
                sources=[], message=NO_STANDARD_MESSAGE,
            )

        top = results[0]
        # More than one candidate is "several" only when the top one is not a
        # clear winner; the existing retrieval confidence decides, not new logic.
        tied = [r for r in results if r.score >= top.score - 1e-9]
        several = len(results) > 1 and (top.confidence != "high" or len(tied) > 1)
        selection = MULTIPLE_CANDIDATES if several else CONFIRMED

        schemes = {}
        for r in results if several else [top]:
            match = resolve_scheme(r.item, items)
            if match is not None:
                schemes.setdefault(match.scheme, match)

        why: list[str] = []
        limitations: list[str] = []

        if selection == CONFIRMED:
            why.append(f"Standard: {explain_candidate(top).summary}")
        else:
            why.append(
                f"{len(results)} verified standards were retrieved for this query with comparable evidence, "
                "so MetrIQ does not choose one. Each candidate is shown with why it was retrieved."
            )
            limitations.append(
                "The applicable Indian Standard was not confidently identified. Confirm which standard "
                "applies before relying on the route below."
            )

        # With several candidates a route is only shown when every one of them
        # points at the SAME scheme — then the route is supported whichever
        # standard turns out to apply.
        scheme = None
        if selection == CONFIRMED:
            scheme = schemes.get(next(iter(schemes), None)) if schemes else None
        elif len(schemes) == 1:
            scheme = next(iter(schemes.values()))
            why.append(
                f"Every retrieved candidate points to the same route ({scheme.name}), so the route below "
                "holds whichever of them applies."
            )
        elif len(schemes) > 1:
            limitations.append(
                "The retrieved candidates do not share one certification route ("
                + ", ".join(sorted(SCHEME_NAMES[s] for s in schemes))
                + "), so no single journey is shown."
            )

        if scheme is None:
            return CertificationJourney(
                query=query or standard_number, product=product, standard_selection=selection,
                standard_number=top.item.standard_number if selection == CONFIRMED else None,
                standard_title=top.item.title if selection == CONFIRMED else None,
                candidates=candidates, scheme=None, verification_status=INSUFFICIENT, steps=[],
                next_steps=_official_next_steps(top.item.source_url),
                why=why + ["No verified record states a BIS certification scheme for this standard."],
                limitations=limitations + [
                    "MetrIQ shows a certification route only when a verified BIS record states one. "
                    "No such record was found here."
                ],
                sources=[_evidence(top.item, top.item.content)],
                message=INSUFFICIENT_MESSAGE,
            )

        steps = build_steps(scheme.scheme, items)
        why.extend(f"Certification route: {sentence}" for sentence in scheme.basis)
        if scheme.conflict:
            limitations.append(scheme.conflict)

        # VERIFIED needs one confidently identified standard, an established
        # route, and the scheme's steps actually present in the knowledge base.
        expected = len(_STEPS.get(scheme.scheme, ()))
        status = VERIFIED
        if selection != CONFIRMED or scheme.conflict:
            status = PARTIAL
        elif scheme.scheme == HALLMARKING:
            # Hallmarking is a different activity with its own registration
            # journey, which MetrIQ does not model. Saying where it belongs is
            # correct but incomplete, so it is never reported as VERIFIED.
            status = PARTIAL
            limitations.append(
                "This is a jewellery hallmarking standard, not product certification. MetrIQ does not model "
                "the jeweller registration and Assaying and Hallmarking Centre journey; follow the BIS "
                "hallmarking pages linked above."
            )
        elif len(steps) < expected:
            status = PARTIAL
            limitations.append(
                f"{expected - len(steps)} of the {expected} steps BIS documents for this scheme are not "
                "covered by a verified record in MetrIQ's knowledge base and are not shown."
            )

        limitations.append(
            "MetrIQ does not state application fees, processing times, required documents or testing "
            "requirements. Those appear only in the BIS documents linked above."
        )
        if scheme.scheme != HALLMARKING:
            limitations.append(
                "Being listed under a scheme describes the route for the product type. It is not a "
                "statement that any particular item, manufacturer or licence is certified."
            )

        sources = _dedupe_evidence(
            [e for step in steps for e in step.evidence] + list(scheme.evidence)
            + [_evidence(top.item, top.item.content)]
        )

        return CertificationJourney(
            query=query or standard_number, product=product, standard_selection=selection,
            standard_number=top.item.standard_number if selection == CONFIRMED else None,
            standard_title=top.item.title if selection == CONFIRMED else None,
            candidates=candidates, scheme=scheme, verification_status=status, steps=steps,
            next_steps=[f"{step.order}. {step.title}" for step in steps]
                       + _official_next_steps(top.item.source_url),
            why=why, limitations=limitations, sources=sources, grounded=True,
        )


def _official_next_steps(standard_source_url: str | None) -> list[str]:
    out = ["Confirm the applicable requirement with BIS before acting on this guidance."]
    if standard_source_url:
        out.insert(0, f"Read the BIS page this standard was recorded from: {standard_source_url}")
    return out


def _dedupe_evidence(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str]] = set()
    out: list[Evidence] = []
    for e in evidence:
        key = (e.knowledge_id, e.quote)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


# --------------------------------------------------------------- coverage

@dataclass(frozen=True)
class CertificationCoverage:
    total_standards: int
    verified: int      # a route is established and every documented step is present
    partial: int       # a route is established but the journey is incomplete
    insufficient: int  # no verified record states a route
    by_scheme: dict[str, int]


def certification_coverage(knowledge_items) -> CertificationCoverage:
    """Honest counts over the real knowledge base. Deterministic."""
    standards = [
        i for i in knowledge_items
        if i.category == "indian_standards" and i.verification_status == "verified" and i.standard_number
    ]
    verified = partial = insufficient = 0
    by_scheme: dict[str, int] = {}
    for item in standards:
        match = resolve_scheme(item, knowledge_items)
        if match is None:
            insufficient += 1
            continue
        by_scheme[match.scheme] = by_scheme.get(match.scheme, 0) + 1
        steps = build_steps(match.scheme, knowledge_items)
        if (match.conflict or match.scheme == HALLMARKING
                or len(steps) < len(_STEPS.get(match.scheme, ()))):
            partial += 1
        else:
            verified += 1
    return CertificationCoverage(len(standards), verified, partial, insufficient, by_scheme)


# ---------------------------------------------------- API response models
#
# Defined here, not in app/api.py, so the HTTP layer and the inspection
# pipeline expose one definition of a journey instead of two.

class WhyOut(BaseModel):
    """The Phase 9 "Why this result?" explanation, as JSON."""

    standard_number: str
    strength: str
    signals: list[str]
    summary: str


class EvidenceOut(BaseModel):
    """One verified knowledge record, quoted word for word."""

    knowledge_id: str
    title: str
    quote: str
    source_organization: str
    source_url: str | None = None
    document_name: str | None = None
    last_verified: str | None = None


class JourneyStepOut(BaseModel):
    order: int
    title: str
    evidence: list[EvidenceOut]


class SchemeOut(BaseModel):
    scheme: str
    name: str
    mark: str
    basis: list[str]
    evidence: list[EvidenceOut]
    conflict: str = ""


class JourneyCandidateOut(BaseModel):
    standard_number: str | None = None
    title: str
    knowledge_id: str
    confidence: str
    score: float
    source_url: str | None = None
    why: WhyOut
    currency: CurrencyOut | None = None
    qco: QcoOut | None = None


class CertificationJourneyOut(BaseModel):
    query: str
    product: str | None = None
    standard_selection: str
    standard_number: str | None = None
    standard_title: str | None = None
    currency: CurrencyOut | None = None
    # Phase 9: Quality Control Order evidence — a different fact from the scheme
    # listing this journey is built on, and never inferred from it.
    qco: QcoOut | None = None
    candidates: list[JourneyCandidateOut]
    scheme: SchemeOut | None = None
    verification_status: str
    steps: list[JourneyStepOut]
    next_steps: list[str]
    why: list[str]
    limitations: list[str]
    sources: list[EvidenceOut]
    grounded: bool
    message: str = ""
    disclaimer: str


def evidence_out(evidence) -> EvidenceOut:
    return EvidenceOut(
        knowledge_id=evidence.knowledge_id,
        title=evidence.title,
        quote=evidence.quote,
        source_organization=evidence.source_organization,
        source_url=evidence.source_url,
        document_name=evidence.document_name,
        last_verified=evidence.last_verified,
    )


def why_out(why) -> WhyOut:
    return WhyOut(
        standard_number=why.standard_number,
        strength=why.strength,
        signals=why.signals,
        summary=why.summary,
    )


def journey_out(journey: CertificationJourney) -> CertificationJourneyOut:
    return CertificationJourneyOut(
        query=journey.query,
        product=journey.product,
        standard_selection=journey.standard_selection,
        standard_number=journey.standard_number,
        standard_title=journey.standard_title,
        currency=currency_for(journey.standard_number),
        qco=qco_for_standard(journey.standard_number) if journey.standard_number else None,
        candidates=[
            JourneyCandidateOut(
                standard_number=c.standard_number,
                title=c.title,
                knowledge_id=c.knowledge_id,
                confidence=c.confidence,
                score=c.score,
                source_url=c.source_url,
                why=why_out(c.why),
                currency=currency_for(c.standard_number),
                qco=qco_for_standard(c.standard_number),
            )
            for c in journey.candidates
        ],
        scheme=(
            SchemeOut(
                scheme=journey.scheme.scheme,
                name=journey.scheme.name,
                mark=journey.scheme.mark,
                basis=journey.scheme.basis,
                evidence=[evidence_out(e) for e in journey.scheme.evidence],
                conflict=journey.scheme.conflict,
            )
            if journey.scheme
            else None
        ),
        verification_status=journey.verification_status,
        steps=[
            JourneyStepOut(
                order=step.order,
                title=step.title,
                evidence=[evidence_out(e) for e in step.evidence],
            )
            for step in journey.steps
        ],
        next_steps=journey.next_steps,
        why=journey.why,
        limitations=journey.limitations,
        sources=[evidence_out(e) for e in journey.sources],
        grounded=journey.grounded,
        message=journey.message,
        disclaimer=journey.disclaimer,
    )
