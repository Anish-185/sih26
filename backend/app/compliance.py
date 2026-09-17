"""Deterministic compliance engine.

    identified standard (MATCHED product only)
      -> verified requirements that apply to it   (app.requirements)
      -> one deterministic rule per checkable requirement
      -> PASS / FAIL / REVIEW per check, NOT_SUPPORTED for areas it cannot check
      -> overall PASS / FAIL / REVIEW

Compliance = VERIFIED REQUIREMENT + OBSERVED PACKAGE EVIDENCE + DETERMINISTIC RULE.
No model, no retrieval score and no OCR guess decides a result. OCR text is only
ever an observed value; requirements come from trusted, validated data.

Evidence quality: a rule reads the declaration (with its OCR evidence). A value
that was not detected, is UNCERTAIN, or was read below the rule's OCR-confidence
threshold gives REVIEW — never PASS or FAIL. "Not detected" is never "missing":
the text may be on another side of the package or unreadable.

Product-specific applicability: the identified standard is only half the key.
The engine confirms which modelled product (``app.requirements`` products) the
package is, using the phrases product identification already matched — no new
scoring. Standard-wide requirements always apply; product-limited requirements
apply only to a confirmed product. ``InspectionCoverage`` records the result
(PRODUCT_CONFIRMED / PRODUCT_NOT_MODELLED / PRODUCT_NOT_CONFIRMED /
PRODUCT_AMBIGUOUS), the counts of verified requirements and deterministic rules
applied, and a deterministic ``explanation`` of what MetrIQ can and cannot
inspect here — so a REVIEW says *why* coverage is limited.

Overall aggregation policy (``AGGREGATION_POLICY``), in order:
  1. no identified standard                     -> REVIEW
  2. no supported (checkable) requirement       -> REVIEW
  3. any supported check FAILs                  -> FAIL
  4. any supported check is REVIEW              -> REVIEW
  5. all supported checks PASS, but some verified
     requirement areas cannot be checked          -> REVIEW
  6. all supported checks PASS, nothing unchecked -> PASS
So "no rules available" can never become PASS, and a PASS is never claimed while
part of a verified requirement set is unchecked.

Explanations ("why did this pass / fail / need review?") are deterministic and
come from the rule that ran — never from a model. Every check carries:
``rule_condition`` (the exact condition the rule applies, with its thresholds),
``reason_code`` (what happened), ``reason_category`` (one of ``REASON_CATEGORIES``),
a factual ``reason``, the observed value and both evidence chains (package
evidence -> OCR region -> image, and requirement -> verified record).

Rules (``_RULES``), each reading declarations only:
  printed_standard_number  the package prints the identified BIS standard's IS number
  field_present            every declaration group has reliable evidence — PASS or REVIEW, never FAIL
  value_format             a declared value has the form the verified requirement states
                           (MRP inclusive of taxes in Indian currency — PASS or REVIEW; net quantity in standard units)
  date_format              a declared date shows a month and a year — PASS or REVIEW, never FAIL
A rule only FAILs on clear, high-confidence evidence that contradicts the
requirement; absence is never a failure. Every check records the source
authority of its requirement (``source_category``: BIS or LEGAL_METROLOGY).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.declarations import DETECTED, NOT_DETECTED, UNCERTAIN, DeclarationStage
from app.product_identification import MATCHED, ProductIdentification
from app.requirements import (
    JEWELLERY_HALLMARKING,
    STANDARD_ONLY,
    UNSUPPORTED,
    InspectionProduct,
    Requirement,
    RequirementSet,
    knowledge_domain,
)
from app.retrieval.text import find_standard_numbers, standard_number_key

PASS = "PASS"
FAIL = "FAIL"
REVIEW = "REVIEW"
NOT_SUPPORTED_RESULT = "NOT_SUPPORTED"
NOT_APPLICABLE_RESULT = "NOT_APPLICABLE"  # the requirement does not apply to this package (evidenced exclusion)

NO_STANDARD = "NO_STANDARD"

# Which modelled product the package is, under the identified standard.
PRODUCT_CONFIRMED = "PRODUCT_CONFIRMED"  # the package text names exactly one modelled product
PRODUCT_NOT_MODELLED = "PRODUCT_NOT_MODELLED"  # no product record for this standard (standard-level data only)
PRODUCT_NOT_CONFIRMED = "PRODUCT_NOT_CONFIRMED"  # products are modelled, the package text names none of them
PRODUCT_AMBIGUOUS = "PRODUCT_AMBIGUOUS"  # the package text names more than one modelled product

# reason_code -> reason_category. Stable, machine-readable groups for the UI and
# a later explanation layer; a model may reword them but never change them.
REASON_CATEGORIES: dict[str, str] = {
    "OBSERVED_MATCHES": "REQUIREMENT_SATISFIED",
    "OBSERVED_DIFFERENT": "REQUIREMENT_NOT_SATISFIED",
    "EVIDENCE_NOT_DETECTED": "EVIDENCE_NOT_DETECTED",
    "EVIDENCE_NOT_DETECTED_UNREADABLE_IMAGES": "EVIDENCE_NOT_DETERMINABLE",
    "EVIDENCE_CONFLICT": "CONFLICTING_EVIDENCE",
    "EVIDENCE_UNCERTAIN": "INSUFFICIENT_EVIDENCE",
    "EVIDENCE_LOW_CONFIDENCE": "INSUFFICIENT_EVIDENCE",
    "EVIDENCE_NORMALIZED": "INSUFFICIENT_EVIDENCE",
    "NO_RELIABLE_TEXT": "INSUFFICIENT_EVIDENCE",
    "RULE_NOT_SUPPORTED": "NOT_SUPPORTED",
    "DECLARATION_PRESENT": "REQUIREMENT_SATISFIED",
    "VALUE_FORMAT_VALID": "REQUIREMENT_SATISFIED",
    "VALUE_FORMAT_INVALID": "REQUIREMENT_NOT_SATISFIED",
    "VALUE_FORMAT_UNCONFIRMED": "INSUFFICIENT_EVIDENCE",
    "EVIDENCE_NOT_LINKED": "INSUFFICIENT_EVIDENCE",
    "DATE_FORMAT_VALID": "REQUIREMENT_SATISFIED",
    "DATE_FORMAT_UNCONFIRMED": "INSUFFICIENT_EVIDENCE",
    "DATE_NOT_MANUFACTURE": "INSUFFICIENT_EVIDENCE",
    "REQUIREMENT_NOT_APPLICABLE": "NOT_APPLICABLE",
}

AGGREGATION_POLICY = (
    "FAIL if any supported check fails; otherwise REVIEW if any supported check needs "
    "review, if no supported check exists, if no standard was identified, or if some "
    "verified requirement areas cannot be checked; PASS only when every applicable "
    "requirement was checked and passed."
)

_DEFAULT_PASS_CONFIDENCE = 0.8
_DEFAULT_FAIL_CONFIDENCE = 0.9


# --------------------------------------------------------------------- data model


@dataclass(frozen=True)
class CheckEvidence:
    """Package evidence behind a check: declaration -> OCR regions -> image."""

    declaration_field: str
    declaration_status: str
    value: str | None
    raw_text: str
    source_regions: list[str]
    image_id: str | None
    ocr_confidence: float | None
    bbox: list[int] | None
    source_images: list[str] = field(default_factory=list)
    source_sides: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RequirementSource:
    """Knowledge evidence behind a requirement: verified record (BIS or Legal Metrology) -> source URL."""

    knowledge_id: str
    title: str
    quote: str
    source_url: str | None
    document_name: str | None
    reference: str | None
    verification_status: str
    last_verified: str | None
    source_authority: str = "BIS"  # BIS | LEGAL_METROLOGY
    source_organization: str | None = None


@dataclass(frozen=True)
class ComplianceCheck:
    rule_id: str
    requirement: str
    rule_type: str
    standard_number: str | None  # None for Legal Metrology packaged-commodity requirements
    result: str  # PASS | FAIL | REVIEW | NOT_SUPPORTED | NOT_APPLICABLE
    reason_code: str  # machine-readable, for a later explanation layer
    reason: str
    reason_category: str  # REASON_CATEGORIES value
    rule_condition: str  # the exact deterministic condition this rule applies
    observed_value: str | None
    expected_condition: str
    evidence_status: str  # SUFFICIENT | INSUFFICIENT | NOT_DETECTED | NOT_APPLICABLE
    evidence: list[CheckEvidence]
    source: RequirementSource | None
    source_category: str = "BIS"  # authority of the requirement: BIS | LEGAL_METROLOGY
    domain: str = "PACKAGE_LABEL"
    reference: str = ""  # rule / clause, e.g. "Rule 6(1)(e)"
    applicability: str = ""
    supporting_sources: list[RequirementSource] = field(default_factory=list)


@dataclass(frozen=True)
class InspectionCoverage:
    """What MetrIQ can inspect for this package: product -> standard -> requirements -> rules."""

    standard_number: str | None
    product_applicability: str  # PRODUCT_* | NO_STANDARD
    product_id: str | None
    product_name: str | None
    product_category: str | None
    applicability_source: RequirementSource | None  # verified record linking product -> standard
    verified_requirements: int  # applied to this package
    deterministic_rules: int
    unsupported_requirements: int
    not_applied_requirements: list[str]  # product-limited requirements the package did not confirm
    explanation: str  # deterministic: why coverage is what it is


@dataclass(frozen=True)
class ComplianceEvaluation:
    overall_status: str  # PASS | FAIL | REVIEW
    coverage_status: str  # INSPECTION_SUPPORTED | STANDARD_ONLY | UNSUPPORTED | NO_STANDARD
    reason_code: str
    reason: str
    product_name: str | None
    standard_number: str | None
    knowledge_id: str | None
    checks: list[ComplianceCheck]
    supported_checks: int = 0
    passed: int = 0
    failed: int = 0
    review: int = 0
    not_supported: int = 0
    policy: str = AGGREGATION_POLICY
    notes: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)  # deterministic, one fact per line
    unreadable_images: list[str] = field(default_factory=list)  # photos that gave no usable OCR
    inspection_coverage: InspectionCoverage | None = None


# ------------------------------------------------------------------------ engine


def evaluate_compliance(
    product: ProductIdentification,
    declarations: DeclarationStage,
    requirements: RequirementSet,
    knowledge_items,
    unreadable_images: list[str] | tuple = (),
) -> ComplianceEvaluation:
    """``unreadable_images`` labels photos of this package that gave no usable OCR
    (e.g. "BACK (image 2)"); evidence not found elsewhere is then undeterminable,
    not merely undetected."""
    notes = [f"Requirement data problem: {e}" for e in requirements.errors]
    unreadable = list(unreadable_images)

    if product.status != MATCHED or not product.standard_number:
        reason = (
            "No product and standard were identified with enough support, so no verified "
            "requirement can be applied. Standard candidates are not used for compliance."
        )
        coverage_info = InspectionCoverage(
            standard_number=None, product_applicability=NO_STANDARD, product_id=None, product_name=None,
            product_category=None, applicability_source=None, verified_requirements=0,
            deterministic_rules=0, unsupported_requirements=0, not_applied_requirements=[],
            explanation="No standard was identified, so MetrIQ's inspection coverage does not apply.",
        )
        return ComplianceEvaluation(
            overall_status=REVIEW, coverage_status=NO_STANDARD, reason_code="NO_STANDARD_IDENTIFIED",
            reason=reason, product_name=None, standard_number=None, knowledge_id=None, checks=[],
            notes=notes, summary=[reason, *_unreadable_lines(unreadable)], unreadable_images=unreadable,
            inspection_coverage=coverage_info,
        )

    standard = product.standard_number
    items = {i.id: i for i in knowledge_items}
    record = items.get(product.knowledge_id)
    if record is not None and knowledge_domain(record) == JEWELLERY_HALLMARKING:
        reason = (
            f"Standard {standard} is a jewellery hallmarking standard. Hallmark and HUID facts describe marks on "
            "jewellery, not package labels, so package-label inspection does not apply. No check was run."
        )
        return ComplianceEvaluation(
            overall_status=REVIEW, coverage_status=UNSUPPORTED, reason_code="DOMAIN_NOT_PACKAGE_LABEL",
            reason=reason, product_name=product.name, standard_number=standard, knowledge_id=product.knowledge_id,
            checks=[], notes=notes, summary=[reason, *_unreadable_lines(unreadable)], unreadable_images=unreadable,
            inspection_coverage=InspectionCoverage(
                standard_number=standard, product_applicability=PRODUCT_NOT_MODELLED, product_id=None,
                product_name=None, product_category=None, applicability_source=None, verified_requirements=0,
                deterministic_rules=0, unsupported_requirements=0, not_applied_requirements=[], explanation=reason,
            ),
        )
    applicability, confirmed, candidates = _confirm_product(product, requirements)
    applicable = requirements.for_product(standard, confirmed.id if confirmed else None)
    not_applied = [r for r in requirements.for_standard(standard) if r not in applicable]
    checks = [_check(req, standard, declarations, items, unreadable) for req in applicable]

    supported = [c for c in checks if c.result != NOT_SUPPORTED_RESULT]
    counts = {
        "supported_checks": len(supported),
        "passed": sum(c.result == PASS for c in supported),
        "failed": sum(c.result == FAIL for c in supported),
        "review": sum(c.result == REVIEW for c in supported),
        "not_supported": sum(c.result == NOT_SUPPORTED_RESULT for c in checks),
    }
    coverage = requirements.coverage(standard, confirmed.id if confirmed else None)
    if coverage == STANDARD_ONLY and any(r.supported for r in not_applied):
        status, code, reason = REVIEW, "PRODUCT_NOT_CONFIRMED", (
            f"Standard {standard} identified, but no supported deterministic inspection requirements "
            "are available for this package: MetrIQ's checkable requirements for it are limited to "
            f"specific products, and the package text did not confirm one of them."
        )
    else:
        status, code, reason = _aggregate(standard, coverage, counts)

    coverage_info = InspectionCoverage(
        standard_number=standard, product_applicability=applicability,
        product_id=confirmed.id if confirmed else None,
        product_name=confirmed.name if confirmed else None,
        product_category=confirmed.category if confirmed else None,
        applicability_source=_link_source(confirmed, standard, items),
        verified_requirements=len(applicable),
        deterministic_rules=counts["supported_checks"],
        unsupported_requirements=counts["not_supported"],
        not_applied_requirements=[r.id for r in not_applied],
        explanation=_coverage_explanation(standard, applicability, confirmed, candidates, applicable,
                                          requirements.products_for_standard(standard)),
    )
    summary = _summary(reason, counts, unreadable)
    summary.insert(len(summary) - len(_unreadable_lines(unreadable)), coverage_info.explanation)
    return ComplianceEvaluation(
        overall_status=status, coverage_status=coverage, reason_code=code, reason=reason,
        product_name=product.name, standard_number=standard, knowledge_id=product.knowledge_id,
        checks=checks, notes=notes, summary=summary,
        unreadable_images=unreadable, inspection_coverage=coverage_info, **counts,
    )


def _confirm_product(product: ProductIdentification, requirements: RequirementSet):
    """Which modelled product is this package? Uses only the phrases and label text
    that product identification already matched — deterministic containment."""
    standard = product.standard_number
    modelled = requirements.products_for_standard(standard)
    if not modelled:
        return PRODUCT_NOT_MODELLED, None, []
    phrases: list[str] = []
    for ev in product.evidence:
        if ev.match in ("product", "alias"):
            phrases.extend(t for t in (ev.matched_phrase, ev.clue.text, ev.clue.search_text) if t)
    matched = requirements.match_products(standard, phrases)
    if len(matched) == 1:
        return PRODUCT_CONFIRMED, matched[0], matched
    if len(matched) > 1:
        return PRODUCT_AMBIGUOUS, None, matched
    return PRODUCT_NOT_CONFIRMED, None, modelled


def _link_source(confirmed: InspectionProduct | None, standard: str, items) -> RequirementSource | None:
    link = confirmed.link(standard) if confirmed else None
    item = items.get(link.source_knowledge_id) if link else None
    if item is None:
        return None
    return RequirementSource(
        knowledge_id=item.id, title=item.title, quote=link.source_quote, source_url=item.source_url,
        document_name=item.document_name, reference=item.reference,
        verification_status=item.verification_status,
        last_verified=item.last_verified.isoformat() if item.last_verified else None,
    )


_LIMIT = "This is a limit of MetrIQ's current knowledge base, not a finding about the package."


def _coverage_explanation(standard, applicability, confirmed, candidates, applicable, modelled) -> str:
    """Deterministic, counts-based: what MetrIQ can and cannot inspect for this package."""
    rules = sum(r.supported for r in applicable)
    unsupported = len(applicable) - rules
    names = " / ".join(p.name for p in candidates or modelled)
    if applicability == PRODUCT_NOT_CONFIRMED:
        lead = (f"MetrIQ has product-specific requirement data under {standard} for {names}, but the "
                "package text did not name that product, so those requirements were not applied.")
    elif applicability == PRODUCT_AMBIGUOUS:
        lead = (f"The package text names more than one modelled product under {standard} ({names}), "
                "so product-specific requirements were not applied.")
    else:
        lead = ""
    who = f"{confirmed.name} under {standard}" if confirmed else standard
    if not applicable:
        body = (f"{standard} is a verified standard in the knowledge base, but MetrIQ does not yet have "
                f"structured verified requirement data that applies here, so no deterministic inspection "
                f"is possible. {_LIMIT}")
    elif rules == 0:
        body = (f"MetrIQ holds {_plural(len(applicable), 'verified requirement', 'verified requirements')} for "
                f"{who}, but none can be checked deterministically from package text. {_LIMIT}")
    else:
        body = (f"MetrIQ's knowledge base contains {_plural(rules, 'deterministic inspection rule', 'deterministic inspection rules')} "
                f"for {who}, out of {_plural(len(applicable), 'verified requirement', 'verified requirements')}"
                + (f"; {unsupported} cannot be checked from a package image." if unsupported else "."))
    return f"{lead} {body}".strip()


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _unreadable_lines(unreadable: list[str]) -> list[str]:
    if not unreadable:
        return []
    return [
        f"No usable OCR evidence from {', '.join(unreadable)}; declarations on "
        f"{'that photo' if len(unreadable) == 1 else 'those photos'} cannot be determined."
    ]


def _summary(reason: str, c: dict, unreadable: list[str]) -> list[str]:
    """One deterministic fact per line, derived only from the check counts."""
    lines = [reason]
    if c["supported_checks"]:
        lines.append(_plural(c["failed"], "supported check failed.", "supported checks failed."))
        lines.append(_plural(c["passed"], "supported check passed.", "supported checks passed."))
        lines.append(_plural(c["review"], "supported check needs review.", "supported checks need review."))
    if c["not_supported"]:
        lines.append(_plural(c["not_supported"], "requirement area cannot be checked from a package image.",
                             "requirement areas cannot be checked from a package image."))
    return lines + _unreadable_lines(unreadable)


def _aggregate(standard: str, coverage: str, c: dict) -> tuple[str, str, str]:
    if coverage == STANDARD_ONLY or c["supported_checks"] == 0:
        return REVIEW, "NO_SUPPORTED_REQUIREMENTS", (
            f"Standard {standard} identified, but no supported deterministic inspection "
            "requirements are available for it in the current knowledge base."
        )
    if c["failed"]:
        return FAIL, "SUPPORTED_CHECK_FAILED", (
            f"{c['failed']} supported check(s) failed against verified requirements for {standard}."
        )
    if c["review"]:
        return REVIEW, "SUPPORTED_CHECK_NEEDS_REVIEW", (
            f"No supported check failed, but {c['review']} could not be decided from the package "
            "evidence and need officer review."
        )
    if c["not_supported"]:
        return REVIEW, "REQUIREMENTS_NOT_CHECKABLE", (
            f"All {c['passed']} supported check(s) passed, but {c['not_supported']} verified "
            f"requirement area(s) for {standard} cannot be checked from a package image. "
            "This is not a compliance determination."
        )
    return PASS, "ALL_CHECKS_PASSED", (
        f"Every applicable verified requirement for {standard} was checked and passed."
    )


def _quoted_source(knowledge_id: str, quote: str, items) -> RequirementSource | None:
    item = items.get(knowledge_id)
    if item is None:
        return None
    return RequirementSource(
        knowledge_id=item.id, title=item.title, quote=quote, source_url=item.source_url,
        document_name=item.document_name, reference=item.reference,
        verification_status=item.verification_status,
        last_verified=item.last_verified.isoformat() if item.last_verified else None,
        source_authority=getattr(item, "source_authority", "BIS"),
        source_organization=item.source_organization,
    )


def _source(req: Requirement, items) -> RequirementSource | None:
    return _quoted_source(req.source_knowledge_id, req.source_quote, items)


def check_base(req: Requirement, standard: str | None, items) -> dict:
    """The fields every check of ``req`` carries, whatever its result."""
    supporting = [_quoted_source(q.knowledge_id, q.quote, items) for q in req.supporting_sources]
    return dict(rule_id=req.id, requirement=req.description, rule_type=req.rule_type,
                standard_number=standard, source=_source(req, items),
                source_category=req.source_category, domain=req.domain, reference=req.reference,
                applicability=req.applicability, supporting_sources=[s for s in supporting if s])


def check_requirement(req: Requirement, standard: str | None, declarations: DeclarationStage, items,
                      unreadable=()) -> ComplianceCheck:
    """Run one verified requirement's rule. ``items`` maps knowledge id -> record."""
    return _check(req, standard, declarations, items, list(unreadable))


def _check(req: Requirement, standard: str | None, declarations: DeclarationStage, items, unreadable) -> ComplianceCheck:
    base = check_base(req, standard, items)
    if not req.supported:
        return ComplianceCheck(
            **base, result=NOT_SUPPORTED_RESULT, reason_code="RULE_NOT_SUPPORTED",
            reason=req.unsupported_reason, reason_category=REASON_CATEGORIES["RULE_NOT_SUPPORTED"],
            rule_condition="No deterministic rule: this verified requirement cannot be checked from package text.",
            observed_value=None,
            expected_condition="Cannot be checked deterministically from package text.",
            evidence_status="NOT_APPLICABLE", evidence=[],
        )
    rule = _RULES[req.rule_type]
    return rule(req, standard, declarations, base, unreadable)


# ------------------------------------------------------------------------- rules


def _evidence(decl) -> CheckEvidence:
    return CheckEvidence(
        declaration_field=decl.field, declaration_status=decl.status, value=decl.value,
        raw_text=decl.raw_text, source_regions=list(decl.source_regions), image_id=decl.image_id,
        ocr_confidence=decl.ocr_confidence, bbox=decl.bbox,
        source_images=list(decl.source_images), source_sides=list(decl.source_sides),
    )


def _rule_printed_standard_number(req: Requirement, standard: str, declarations: DeclarationStage, base,
                                  unreadable=()) -> ComplianceCheck:
    """The package prints the primary IS number of the identified standard."""
    expected = (standard_number_key(standard) or ("", ""))[0]
    expected_condition = f"The package text shows IS {expected}."
    pass_conf = req.parameters.get("min_ocr_confidence_pass", _DEFAULT_PASS_CONFIDENCE)
    fail_conf = req.parameters.get("min_ocr_confidence_fail", _DEFAULT_FAIL_CONFIDENCE)
    rule_condition = (
        f"PASS when the declared IS number includes IS {expected} and was read at "
        f"≥{round(pass_conf * 100)}% OCR confidence; FAIL when it shows a different IS number read at "
        f"≥{round(fail_conf * 100)}%; otherwise REVIEW (not detected, uncertain, conflicting or low confidence)."
    )

    def result(res, code, reason, status, observed=None, evidence=()):
        return ComplianceCheck(**base, result=res, reason_code=code, reason=reason,
                               reason_category=REASON_CATEGORIES[code], rule_condition=rule_condition,
                               observed_value=observed, expected_condition=expected_condition,
                               evidence_status=status, evidence=list(evidence))

    if declarations.status == "NO_RELIABLE_TEXT":
        return result(REVIEW, "NO_RELIABLE_TEXT",
                      "The OCR found no reliable text, so the package evidence is insufficient.",
                      "INSUFFICIENT")

    decl = next((d for d in declarations.fields if d.field == req.declaration_field), None)
    if (decl is None or decl.status == NOT_DETECTED) and unreadable:
        return result(REVIEW, "EVIDENCE_NOT_DETECTED_UNREADABLE_IMAGES",
                      f"No IS number was detected in the readable images, and {', '.join(unreadable)} gave no "
                      "usable OCR evidence, so whether the package shows it cannot be determined.",
                      "NOT_DETECTED")
    if decl is None or decl.status == NOT_DETECTED:
        return result(REVIEW, "EVIDENCE_NOT_DETECTED",
                      "No IS number was detected in the OCR text of the uploaded image(s). It may be "
                      "on a side that was not photographed, or unreadable — not being detected is not "
                      "a finding about the package.",
                      "NOT_DETECTED")

    ev = [_evidence(decl)]
    if decl.consistency == "CONFLICT":
        return result(REVIEW, "EVIDENCE_CONFLICT",
                      f"Conflicting values were detected across the package: {decl.reason}",
                      "INSUFFICIENT", None, ev)
    if decl.status == UNCERTAIN:
        return result(REVIEW, "EVIDENCE_UNCERTAIN",
                      f"The IS number on the package could not be read reliably: {decl.reason}",
                      "INSUFFICIENT", decl.value, ev)

    printed = [n.split(":")[0] for n in find_standard_numbers(decl.value or "")]
    confidence = decl.ocr_confidence or 0.0
    pct = round(confidence * 100)
    if decl.status == DETECTED and expected in printed:
        if confidence >= pass_conf:
            return result(PASS, "OBSERVED_MATCHES",
                          f"The package text shows IS {expected}, the identified standard (OCR {pct}%).",
                          "SUFFICIENT", decl.value, ev)
        return result(REVIEW, "EVIDENCE_LOW_CONFIDENCE",
                      f"IS {expected} was read, but only at {pct}% OCR confidence (a pass needs "
                      f"{round(pass_conf * 100)}%).", "INSUFFICIENT", decl.value, ev)
    if decl.extraction_method == "deterministic_normalization":
        # The number was recovered from corrupted OCR text: good enough to confirm a
        # match, never strong enough to fail a package.
        return result(REVIEW, "EVIDENCE_NORMALIZED",
                      f"The package text was read as '{decl.raw_text}' and normalized to {decl.value}, not "
                      f"IS {expected}. A normalized reading is not used to fail a package — confirm against the "
                      "physical package.", "INSUFFICIENT", decl.value, ev)
    if confidence >= fail_conf:
        return result(FAIL, "OBSERVED_DIFFERENT",
                      f"The package text shows {decl.value}, not IS {expected} (OCR {pct}%). "
                      "Confirm against the physical package.", "SUFFICIENT", decl.value, ev)
    return result(REVIEW, "EVIDENCE_LOW_CONFIDENCE",
                  f"The package text reads {decl.value}, not IS {expected}, but only at {pct}% OCR "
                  f"confidence (a fail needs {round(fail_conf * 100)}%) — possibly a misread.",
                  "INSUFFICIENT", decl.value, ev)


# ------------------------------------------------ generic declaration rules


def _pct(value: float) -> int:
    return round(value * 100)


def _result_factory(base, rule_condition: str, expected_condition: str):
    def result(res, code, reason, status, observed=None, evidence=()):
        return ComplianceCheck(**base, result=res, reason_code=code, reason=reason,
                               reason_category=REASON_CATEGORIES[code], rule_condition=rule_condition,
                               observed_value=observed, expected_condition=expected_condition,
                               evidence_status=status, evidence=list(evidence))
    return result


def _find(declarations: DeclarationStage, field_name: str):
    return next((d for d in declarations.fields if d.field == field_name), None)


def _unusable(decls, what: str, pass_conf: float, unreadable, result):
    """REVIEW when none of ``decls`` (alternative fields for one declaration) is
    usable evidence. Returns (usable declaration, None) or (None, REVIEW check)."""
    present = [d for d in decls if d is not None and d.status != NOT_DETECTED]
    good = [d for d in present if d.status == DETECTED and d.consistency != "CONFLICT"]
    strong = [d for d in good if (d.ocr_confidence or 0.0) >= pass_conf]
    if strong:
        return strong[0], None
    if good:
        d = good[0]
        return None, result(REVIEW, "EVIDENCE_LOW_CONFIDENCE",
                            f"{what} was read as '{d.value}', but only at {_pct(d.ocr_confidence or 0.0)}% OCR "
                            f"confidence (a pass needs {_pct(pass_conf)}%).", "INSUFFICIENT", d.value, [_evidence(d)])
    conflict = next((d for d in present if d.consistency == "CONFLICT"), None)
    if conflict is not None:
        return None, result(REVIEW, "EVIDENCE_CONFLICT",
                            f"Conflicting values were detected across the package: {conflict.reason}",
                            "INSUFFICIENT", None, [_evidence(conflict)])
    if present:
        d = present[0]
        return None, result(REVIEW, "EVIDENCE_UNCERTAIN", f"{what} could not be read reliably: {d.reason}",
                            "INSUFFICIENT", d.value, [_evidence(d)])
    if unreadable:
        return None, result(REVIEW, "EVIDENCE_NOT_DETECTED_UNREADABLE_IMAGES",
                            f"{what} was not detected in the readable images, and {', '.join(unreadable)} gave no "
                            "usable OCR evidence, so whether the package shows it cannot be determined.",
                            "NOT_DETECTED")
    return None, result(REVIEW, "EVIDENCE_NOT_DETECTED",
                        f"{what} was not detected in the OCR text of the uploaded image(s). It may be on a side "
                        "that was not photographed, or unreadable — not being detected is not a finding about "
                        "the package.", "NOT_DETECTED")


def _group_label(declarations: DeclarationStage, group) -> str:
    labels = []
    for name in group:
        d = _find(declarations, name)
        labels.append(d.label if d is not None else name.replace("_", " "))
    return " or ".join(labels)


def _rule_field_present(req: Requirement, standard, declarations: DeclarationStage, base,
                        unreadable=()) -> ComplianceCheck:
    """Every declaration group has reliable evidence. Never FAILs: a declaration
    that was not read is not evidence that the package lacks it."""
    groups = req.declaration_groups or ((req.declaration_field,),)
    pass_conf = req.parameters.get("min_ocr_confidence_pass", _DEFAULT_PASS_CONFIDENCE)
    names = [_group_label(declarations, g) for g in groups]
    expected = "The package text shows " + " and ".join(names) + "."
    rule_condition = (
        f"PASS when {' and '.join(names)} {'are each' if len(groups) > 1 else 'is'} detected at "
        f"≥{_pct(pass_conf)}% OCR confidence"
        + (" on the same photo" if req.require_same_image and len(groups) > 1 else "")
        + "; otherwise REVIEW (not detected, uncertain, conflicting or low confidence). "
        "Never FAIL: not reading a declaration is not evidence that the package lacks it."
    )
    result = _result_factory(base, rule_condition, expected)
    if declarations.status == "NO_RELIABLE_TEXT":
        return result(REVIEW, "NO_RELIABLE_TEXT",
                      "The OCR found no reliable text, so the package evidence is insufficient.", "INSUFFICIENT")

    picked = []
    for group, name in zip(groups, names):
        decl, review = _unusable([_find(declarations, f) for f in group], name, pass_conf, unreadable, result)
        if review is not None:
            return review
        picked.append(decl)

    evidence = [_evidence(d) for d in picked]
    observed = "; ".join(d.value if str(d.value).lower().startswith(d.label.lower()) else f"{d.label}: {d.value}"
                         for d in picked)
    if req.require_same_image and len(picked) > 1:
        shared = set(picked[0].source_images)
        for d in picked[1:]:
            shared &= set(d.source_images)
        if not shared:
            return result(REVIEW, "EVIDENCE_NOT_LINKED",
                          f"{' and '.join(names)} were read on different photos, so MetrIQ cannot tell that they "
                          "belong to the same declaration.", "INSUFFICIENT", observed, evidence)
    reads = "; ".join(f"{d.label} '{d.value}' ({_pct(d.ocr_confidence or 0.0)}%)" for d in picked)
    return result(PASS, "DECLARATION_PRESENT", f"The package text shows {reads}.", "SUFFICIENT", observed, evidence)


_INR = "INR"
_STANDARD_UNITS = {"g": "gram", "kg": "kilogram", "mg": "milligram", "ml": "millilitre", "L": "litre",
                   "N": "number of items"}
_COUNTING_WORDS = {"dozen"}  # Rule 13(4)
_RE_OTHER_UNIT_IN_TEXT = re.compile(r"\d\s*(fl\.?\s*oz|oz|ounces?|lbs?|pounds?|dozens?|doz)(?![a-z])", re.IGNORECASE)


def _rule_value_format(req: Requirement, standard, declarations: DeclarationStage, base,
                       unreadable=()) -> ComplianceCheck:
    """A declared value has the form the verified requirement states (``req.format``)."""
    pass_conf = req.parameters.get("min_ocr_confidence_pass", _DEFAULT_PASS_CONFIDENCE)
    fail_conf = req.parameters.get("min_ocr_confidence_fail", _DEFAULT_FAIL_CONFIDENCE)
    decl_all = _find(declarations, req.declaration_field)
    label = decl_all.label if decl_all is not None else req.declaration_field

    if req.format == "retail_sale_price_inclusive_of_taxes_in_indian_currency":
        expected = "An MRP (maximum retail price) declared inclusive of all taxes, in Indian currency."
        rule_condition = (
            f"PASS when an MRP with a rupee amount (₹ / Rs. / INR) and the words 'inclusive of all taxes' is read "
            f"at ≥{_pct(pass_conf)}% OCR confidence; otherwise REVIEW (no 'inclusive of all taxes', another "
            "currency, uncertain or low confidence). Never FAIL: an imported package may carry its declarations "
            "on an affixed label (Rule 6(9)) that was not photographed."
        )
    else:  # net_quantity_in_standard_units
        expected = "A net quantity with a standard unit (g, kg, mg, ml, L) or a number of items (N / U / pieces)."
        rule_condition = (
            f"PASS when a labelled net quantity with a standard unit is read at ≥{_pct(pass_conf)}% OCR "
            f"confidence and no other unit system appears in it; FAIL when it is stated as a dozen (Rule 13(4)), "
            f"read at ≥{_pct(fail_conf)}%; otherwise REVIEW (no unit, a non-SI unit such as oz or lb, uncertain "
            "or low confidence)."
        )
    result = _result_factory(base, rule_condition, expected)
    if declarations.status == "NO_RELIABLE_TEXT":
        return result(REVIEW, "NO_RELIABLE_TEXT",
                      "The OCR found no reliable text, so the package evidence is insufficient.", "INSUFFICIENT")
    decl, review = _unusable([decl_all], label, pass_conf, unreadable, result)
    if review is not None:
        return review
    ev = [_evidence(decl)]
    confidence = decl.ocr_confidence or 0.0
    normalized = decl.extraction_method == "deterministic_normalization"

    if req.format == "retail_sale_price_inclusive_of_taxes_in_indian_currency":
        if decl.unit == _INR:
            if "inclusive of all taxes" in (decl.note or ""):
                return result(PASS, "VALUE_FORMAT_VALID",
                              f"The package text shows the MRP {decl.value} inclusive of all taxes, in Indian "
                              f"currency (OCR {_pct(confidence)}%).", "SUFFICIENT", decl.value, ev)
            return result(REVIEW, "VALUE_FORMAT_UNCONFIRMED",
                          f"The MRP {decl.value} was read, but the words 'inclusive of all taxes' were not read with "
                          "it. They may be printed nearby and not captured by OCR — confirm on the package.",
                          "INSUFFICIENT", decl.value, ev)
        return result(REVIEW, "VALUE_FORMAT_UNCONFIRMED",
                      f"The MRP reads {decl.value} (OCR {_pct(confidence)}%), which is not in Indian currency. An "
                      "imported package may carry its declarations on an affixed label (Rule 6(9)) that was not "
                      "photographed, so this is not decided automatically — confirm on the physical package.",
                      "INSUFFICIENT", decl.value, ev)

    unit = decl.unit or ""
    if unit in _COUNTING_WORDS:
        if confidence >= fail_conf and not normalized:
            return result(FAIL, "VALUE_FORMAT_INVALID",
                          f"The net quantity is stated as '{decl.value}' (OCR {_pct(confidence)}%). Rule 13(4) does "
                          "not allow a dozen to be specified or indicated on a package. Confirm against the "
                          "physical package.", "SUFFICIENT", decl.value, ev)
        return result(REVIEW, "EVIDENCE_LOW_CONFIDENCE",
                      f"The net quantity reads '{decl.value}', but only at {_pct(confidence)}% OCR confidence "
                      f"(a fail needs {_pct(fail_conf)}%).", "INSUFFICIENT", decl.value, ev)
    if unit not in _STANDARD_UNITS:
        return result(REVIEW, "VALUE_FORMAT_UNCONFIRMED",
                      f"The net quantity is stated as '{decl.value}', not in an SI unit. An imported package may "
                      "carry its declarations on an affixed label (Rule 6(9)) that was not photographed, so this is "
                      "not decided automatically.", "INSUFFICIENT", decl.value, ev)
    other = _RE_OTHER_UNIT_IN_TEXT.search(decl.raw_text or "")
    if other:
        return result(REVIEW, "VALUE_FORMAT_UNCONFIRMED",
                      f"The net quantity {decl.value} is also stated with '{other.group(1)}' in the same text "
                      f"('{decl.raw_text}'). Rule 13 allows only SI units and no dozen, so the combined declaration "
                      "needs officer review.", "INSUFFICIENT", decl.value, ev)
    return result(PASS, "VALUE_FORMAT_VALID",
                  f"The package text shows the net quantity {decl.value} ({_STANDARD_UNITS[unit]}, a standard unit; "
                  f"OCR {_pct(confidence)}%).", "SUFFICIENT", decl.value, ev)


_MONTH_NAMES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_RE_PACKING_ONLY = re.compile(r"\b(?:pkd|packed|packing|packaging)\b", re.IGNORECASE)
_RE_MANUFACTURE = re.compile(r"\b(?:mfg|mfd|manufactur\w*)\b", re.IGNORECASE)


def month_and_year(value: str) -> tuple[str | None, str]:
    """(reading, '') when a month and a year can be identified in ``value``;
    (None, why) otherwise. Deterministic; never guesses between two readings."""
    v = (value or "").strip().lower()
    m = re.fullmatch(r"([a-z]+)[\s/\-.,]*(\d{4}|\d{2})", v)
    if m:
        if m.group(1)[:3] in _MONTH_NAMES:
            return f"month {m.group(1)[:3].title()}, year {m.group(2)}", ""
        return None, f"'{value}' does not start with a month name."
    parts = re.split(r"[/\-.]", v)
    if not parts or not all(p.isdigit() for p in parts):
        return None, f"'{value}' is not a month and year in words or numerals."
    nums = [int(p) for p in parts]
    if len(parts) == 3:
        day_first, month_first = nums[1] <= 12 and nums[1] >= 1, nums[0] <= 12 and nums[0] >= 1
        if len(parts[2]) in (2, 4) and (day_first or month_first):
            return f"a full date with year {parts[2]}", ""
        return None, f"'{value}' has no valid month."
    if len(parts) == 2:
        month, year = nums
        if not 1 <= month <= 12:
            return None, f"'{value}' has no valid month ({parts[0]})."
        if len(parts[1]) == 4:
            return f"month {parts[0]}, year {parts[1]}", ""
        if len(parts[1]) == 2 and year > 12:
            return f"month {parts[0]}, year {parts[1]}", ""
        return None, (f"'{value}' could be a day and month without a year, or a month and a two-digit year — "
                      "it cannot be read unambiguously.")
    return None, f"'{value}' is not a month and year."


def _rule_date_format(req: Requirement, standard, declarations: DeclarationStage, base,
                      unreadable=()) -> ComplianceCheck:
    """A declared manufacturing date identifies a month and a year. Never FAILs:
    an unreadable or partial date is not evidence of a missing declaration."""
    pass_conf = req.parameters.get("min_ocr_confidence_pass", _DEFAULT_PASS_CONFIDENCE)
    decl_all = _find(declarations, req.declaration_field)
    label = decl_all.label if decl_all is not None else req.declaration_field
    expected = "The month and year of manufacture, in words and/or numerals."
    rule_condition = (
        f"PASS when a date labelled as the manufacturing date is read at ≥{_pct(pass_conf)}% OCR confidence and "
        "unambiguously shows a month and a year (e.g. 05/2024, May 2024, 12/05/2024, 05/24); otherwise REVIEW "
        "(not detected, a packing date only, ambiguous such as 11/12, uncertain or low confidence). Never FAIL."
    )
    result = _result_factory(base, rule_condition, expected)
    if declarations.status == "NO_RELIABLE_TEXT":
        return result(REVIEW, "NO_RELIABLE_TEXT",
                      "The OCR found no reliable text, so the package evidence is insufficient.", "INSUFFICIENT")
    decl, review = _unusable([decl_all], label, pass_conf, unreadable, result)
    if review is not None:
        return review
    ev = [_evidence(decl)]
    raw = decl.raw_text or ""
    if _RE_PACKING_ONLY.search(raw) and not _RE_MANUFACTURE.search(raw):
        return result(REVIEW, "DATE_NOT_MANUFACTURE",
                      f"The date {decl.value} is labelled as a packing date ('{raw}'). Rule 6(1)(d), as amended in "
                      "2021, asks for the month and year of manufacture; a packing date alone does not show it.",
                      "INSUFFICIENT", decl.value, ev)
    reading, why = month_and_year(decl.value or "")
    if reading is None:
        return result(REVIEW, "DATE_FORMAT_UNCONFIRMED", f"The manufacturing date was read, but {why}",
                      "INSUFFICIENT", decl.value, ev)
    return result(PASS, "DATE_FORMAT_VALID",
                  f"The package text shows the manufacturing date {decl.value} — {reading} "
                  f"(OCR {_pct(decl.ocr_confidence or 0.0)}%).", "SUFFICIENT", decl.value, ev)


_RULES = {
    "printed_standard_number": _rule_printed_standard_number,
    "field_present": _rule_field_present,
    "value_format": _rule_value_format,
    "date_format": _rule_date_format,
}
