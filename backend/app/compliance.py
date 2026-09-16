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
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.declarations import DETECTED, NOT_DETECTED, UNCERTAIN, DeclarationStage
from app.product_identification import MATCHED, ProductIdentification
from app.requirements import (
    STANDARD_ONLY,
    SUPPORTED_FOR_INSPECTION,
    Requirement,
    RequirementSet,
)
from app.retrieval.text import find_standard_numbers, standard_number_key

PASS = "PASS"
FAIL = "FAIL"
REVIEW = "REVIEW"
NOT_SUPPORTED_RESULT = "NOT_SUPPORTED"

NO_STANDARD = "NO_STANDARD"

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
    observed_value: str | None
    expected_condition: str
    evidence_status: str  # SUFFICIENT | INSUFFICIENT | NOT_DETECTED | NOT_APPLICABLE
    evidence: list[CheckEvidence]
    source: RequirementSource | None


@dataclass(frozen=True)
class ComplianceEvaluation:
    overall_status: str  # PASS | FAIL | REVIEW
    coverage_status: str  # SUPPORTED_FOR_INSPECTION | STANDARD_ONLY | NO_STANDARD
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


# ------------------------------------------------------------------------ engine


def evaluate_compliance(
    product: ProductIdentification,
    declarations: DeclarationStage,
    requirements: RequirementSet,
    knowledge_items,
) -> ComplianceEvaluation:
    notes = [f"Requirement data problem: {e}" for e in requirements.errors]

    if product.status != MATCHED or not product.standard_number:
        return ComplianceEvaluation(
            overall_status=REVIEW, coverage_status=NO_STANDARD, reason_code="NO_STANDARD_IDENTIFIED",
            reason=(
                "No product and standard were identified with enough support, so no verified "
                "requirement can be applied. Standard candidates are not used for compliance."
            ),
            product_name=None, standard_number=None, knowledge_id=None, checks=[], notes=notes,
        )

    standard = product.standard_number
    items = {i.id: i for i in knowledge_items}
    applicable = requirements.for_standard(standard)
    checks = [_check(req, standard, declarations, items) for req in applicable]

    supported = [c for c in checks if c.result != NOT_SUPPORTED_RESULT]
    counts = {
        "supported_checks": len(supported),
        "passed": sum(c.result == PASS for c in supported),
        "failed": sum(c.result == FAIL for c in supported),
        "review": sum(c.result == REVIEW for c in supported),
        "not_supported": sum(c.result == NOT_SUPPORTED_RESULT for c in checks),
    }
    coverage = requirements.coverage(standard)
    status, code, reason = _aggregate(standard, coverage, counts)
    return ComplianceEvaluation(
        overall_status=status, coverage_status=coverage, reason_code=code, reason=reason,
        product_name=product.name, standard_number=standard, knowledge_id=product.knowledge_id,
        checks=checks, notes=notes, **counts,
    )


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


def _check(req: Requirement, standard: str, declarations: DeclarationStage, items) -> ComplianceCheck:
    base = dict(rule_id=req.id, requirement=req.description, rule_type=req.rule_type,
                standard_number=standard, source=_source(req, items))
    if not req.supported:
        return ComplianceCheck(
            **base, result=NOT_SUPPORTED_RESULT, reason_code="RULE_NOT_SUPPORTED",
            reason=req.unsupported_reason, observed_value=None,
            expected_condition="Cannot be checked deterministically from package text.",
            evidence_status="NOT_APPLICABLE", evidence=[],
        )
    rule = _RULES[req.rule_type]
    return rule(req, standard, declarations, base)


# ------------------------------------------------------------------------- rules


def _evidence(decl) -> CheckEvidence:
    return CheckEvidence(
        declaration_field=decl.field, declaration_status=decl.status, value=decl.value,
        raw_text=decl.raw_text, source_regions=list(decl.source_regions), image_id=decl.image_id,
        ocr_confidence=decl.ocr_confidence, bbox=decl.bbox,
        source_images=list(decl.source_images), source_sides=list(decl.source_sides),
    )


def _rule_printed_standard_number(req: Requirement, standard: str, declarations: DeclarationStage, base) -> ComplianceCheck:
    """The package prints the primary IS number of the identified standard."""
    expected = (standard_number_key(standard) or ("", ""))[0]
    expected_condition = f"The package text shows IS {expected}."
    pass_conf = req.parameters.get("min_ocr_confidence_pass", _DEFAULT_PASS_CONFIDENCE)
    fail_conf = req.parameters.get("min_ocr_confidence_fail", _DEFAULT_FAIL_CONFIDENCE)

    def result(res, code, reason, status, observed=None, evidence=()):
        return ComplianceCheck(**base, result=res, reason_code=code, reason=reason,
                               observed_value=observed, expected_condition=expected_condition,
                               evidence_status=status, evidence=list(evidence))

    if declarations.status == "NO_RELIABLE_TEXT":
        return result(REVIEW, "NO_RELIABLE_TEXT",
                      "The OCR found no reliable text, so the package evidence is insufficient.",
                      "INSUFFICIENT")

    decl = next((d for d in declarations.fields if d.field == req.declaration_field), None)
    if decl is None or decl.status == NOT_DETECTED:
        return result(REVIEW, "EVIDENCE_NOT_DETECTED",
                      "No IS number was detected in the OCR text of the uploaded image(s). It may be "
                      "on a side that was not photographed, or unreadable — not detected is not the "
                      "same as missing.",
                      "NOT_DETECTED")

    ev = [_evidence(decl)]
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
