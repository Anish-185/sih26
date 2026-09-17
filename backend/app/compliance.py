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
evidence -> OCR region -> image, and requirement -> verified BIS record).
"""

from __future__ import annotations

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
    """Knowledge evidence behind a requirement: verified BIS record -> source URL."""

    knowledge_id: str
    title: str
    quote: str
    source_url: str | None
    document_name: str | None
    reference: str | None
    verification_status: str
    last_verified: str | None


@dataclass(frozen=True)
class ComplianceCheck:
    rule_id: str
    requirement: str
    rule_type: str
    standard_number: str
    result: str  # PASS | FAIL | REVIEW | NOT_SUPPORTED
    reason_code: str  # machine-readable, for a later explanation layer
    reason: str
    reason_category: str  # REASON_CATEGORIES value
    rule_condition: str  # the exact deterministic condition this rule applies
    observed_value: str | None
    expected_condition: str
    evidence_status: str  # SUFFICIENT | INSUFFICIENT | NOT_DETECTED | NOT_APPLICABLE
    evidence: list[CheckEvidence]
    source: RequirementSource | None


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


def _source(req: Requirement, items) -> RequirementSource | None:
    item = items.get(req.source_knowledge_id)
    if item is None:
        return None
    return RequirementSource(
        knowledge_id=item.id, title=item.title, quote=req.source_quote, source_url=item.source_url,
        document_name=item.document_name, reference=item.reference,
        verification_status=item.verification_status,
        last_verified=item.last_verified.isoformat() if item.last_verified else None,
    )


def _check(req: Requirement, standard: str, declarations: DeclarationStage, items, unreadable) -> ComplianceCheck:
    base = dict(rule_id=req.id, requirement=req.description, rule_type=req.rule_type,
                standard_number=standard, source=_source(req, items))
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


_RULES = {
    "printed_standard_number": _rule_printed_standard_number,
}
