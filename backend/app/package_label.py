"""Legal Metrology package-label evaluation.

    package declarations (OCR evidence)
      -> is the package within Chapter II of the Packaged Commodities Rules?  (Rule 3, observable exclusions)
      -> which packaged-commodity requirements apply?                       (requirement exclusions)
      -> one deterministic rule per checkable requirement                   (app.compliance rules)
      -> PASS / FAIL / REVIEW per check, NOT_SUPPORTED / NOT_APPLICABLE otherwise
      -> overall PASS / FAIL / REVIEW for the Legal Metrology requirements

This is a separate evidence system from BIS compliance (``app.compliance``):
its requirements come from Legal Metrology records (Department of Consumer
Affairs), every check says ``source_category = LEGAL_METROLOGY``, and its overall
result is never merged with the BIS result. A package can be BIS REVIEW and
Legal Metrology PASS.

Applicability is conservative and stated, never silent:

* Scope exclusions (``package_scope.exclusions``) are only applied on clear OCR
  evidence — a net quantity above 25 kg / 25 L, or "not for retail sale" printed on
  the label. Then no requirement is applied and the result is REVIEW (the
  exclusion is itself OCR evidence an officer should confirm).
* Requirement exclusions (e.g. food articles for Rule 6(1)(a) and 6(1)(d)) make
  that requirement NOT_APPLICABLE when their evidence is read (an FSSAI licence).
* Everything a label cannot show (retail vs. industrial buyer, medical devices,
  commodity-specific exemptions) is listed in ``assumptions`` with every result.

Overall aggregation (``AGGREGATION_POLICY``), in order:
  1. package excluded from Chapter II by evidence          -> REVIEW
  2. no Legal Metrology requirement data                   -> REVIEW
  3. no applicable checkable requirement                    -> REVIEW
  4. any check FAILs                                        -> FAIL
  5. any check is REVIEW                                    -> REVIEW
  6. all checks PASS, some requirement areas uncheckable    -> REVIEW
  7. all applicable requirements checked and passed         -> PASS
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.compliance import (
    FAIL,
    NOT_APPLICABLE_RESULT,
    NOT_SUPPORTED_RESULT,
    PASS,
    REASON_CATEGORIES,
    REVIEW,
    CheckEvidence,
    ComplianceCheck,
    RequirementSource,
    _evidence,
    _quoted_source,
    check_base,
    check_requirement,
)
from app.declarations import DETECTED, DeclarationStage
from app.requirements import LEGAL_METROLOGY, Exclusion, RequirementSet

SOURCE_AUTHORITY_NAME = "Legal Metrology (Department of Consumer Affairs)"

IN_SCOPE = "IN_SCOPE"  # no exclusion evidenced; the stated assumptions apply
OUT_OF_SCOPE = "OUT_OF_SCOPE"  # a Rule 3 exclusion is evidenced on the label
NO_REQUIREMENT_DATA = "NO_REQUIREMENT_DATA"

AGGREGATION_POLICY = (
    "FAIL if any Legal Metrology check fails; otherwise REVIEW if any check needs review, if no requirement "
    "applies, if the label shows the package is outside Chapter II, or if some applicable requirement areas "
    "cannot be checked; PASS only when every applicable requirement was checked and passed."
)

# Evidence thresholds for exclusions: an exclusion switches requirements off, so
# it needs a clean reading.
_EXCLUSION_CONFIDENCE = 0.8
_RE_NOT_FOR_RETAIL = re.compile(r"not\s*for\s*retail\s*sale", re.IGNORECASE)
_TO_KG = {"g": 0.001, "kg": 1.0, "mg": 0.000001}
_TO_L = {"ml": 0.001, "L": 1.0}


@dataclass(frozen=True)
class ExclusionFinding:
    """An exclusion whose evidence was read on the package."""

    id: str
    description: str
    observed: str
    source_regions: list[str]
    sources: list[RequirementSource]
    evidence: list[CheckEvidence] = field(default_factory=list)  # the OCR evidence of the exclusion


@dataclass(frozen=True)
class PackageLabelEvaluation:
    source_category: str  # LEGAL_METROLOGY
    source_authority: str  # human-readable authority name
    overall_status: str  # PASS | FAIL | REVIEW
    reason_code: str
    reason: str
    scope_status: str  # IN_SCOPE | OUT_OF_SCOPE | NO_REQUIREMENT_DATA
    scope: str  # what the scope is, from the source
    scope_source: RequirementSource | None
    exclusions_found: list[ExclusionFinding]
    assumptions: list[str]
    assumption_sources: list[RequirementSource]
    checks: list[ComplianceCheck]
    supported_checks: int = 0
    passed: int = 0
    failed: int = 0
    review: int = 0
    not_supported: int = 0
    not_applicable: int = 0
    policy: str = AGGREGATION_POLICY
    summary: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unreadable_images: list[str] = field(default_factory=list)
    # declaration field -> applied checkable requirement ids (for completeness)
    field_requirements: dict[str, list[str]] = field(default_factory=dict)


def evaluate_package_label(
    declarations: DeclarationStage,
    regions,
    requirements: RequirementSet,
    knowledge_items,
    unreadable_images: list[str] | tuple = (),
) -> PackageLabelEvaluation:
    items = {i.id: i for i in knowledge_items}
    unreadable = list(unreadable_images)
    notes = [f"Requirement data problem: {e}" for e in requirements.errors]
    scope = requirements.package_scope
    reqs = requirements.for_package()

    if scope is None or not reqs:
        reason = ("MetrIQ has no valid Legal Metrology package-label requirement data, so no Legal Metrology "
                  "check was run.")
        return PackageLabelEvaluation(
            source_category=LEGAL_METROLOGY, source_authority=SOURCE_AUTHORITY_NAME, overall_status=REVIEW,
            reason_code="NO_PACKAGE_REQUIREMENTS", reason=reason, scope_status=NO_REQUIREMENT_DATA, scope="",
            scope_source=None, exclusions_found=[], assumptions=[], assumption_sources=[], checks=[],
            summary=[reason], notes=notes, unreadable_images=unreadable,
        )

    scope_source = _quoted_source(scope.source.knowledge_id, scope.source.quote, items)
    assumption_sources = [s for s in (_quoted_source(q.knowledge_id, q.quote, items)
                                      for q in scope.assumption_sources) if s]
    common = dict(
        source_category=LEGAL_METROLOGY, source_authority=SOURCE_AUTHORITY_NAME, scope=scope.description,
        scope_source=scope_source, assumptions=list(scope.assumptions), assumption_sources=assumption_sources,
        notes=notes, unreadable_images=unreadable,
    )

    found = [f for f in (_exclusion_finding(e, declarations, regions, items) for e in scope.exclusions) if f]
    if found:
        checks = [_not_applicable(req, items, _scope_reason(found), found) for req in reqs]
        reason = (
            "The label indicates the package is outside the declarations chapter of the Legal Metrology "
            f"(Packaged Commodities) Rules, 2011: {'; '.join(f.description for f in found)} "
            "No Legal Metrology requirement was applied. This exclusion is read from OCR evidence — confirm it "
            "on the physical package."
        )
        return PackageLabelEvaluation(
            **common, overall_status=REVIEW, reason_code="PACKAGE_OUT_OF_SCOPE", reason=reason,
            scope_status=OUT_OF_SCOPE, exclusions_found=found, checks=checks, not_applicable=len(checks),
            summary=[reason],
        )

    checks: list[ComplianceCheck] = []
    field_requirements: dict[str, list[str]] = {}
    for req in reqs:
        excluded = [f for f in (_exclusion_finding(e, declarations, regions, items) for e in req.exclusions) if f]
        if excluded:
            checks.append(_not_applicable(req, items, " ".join(
                f"{f.description} (read: {f.observed})" for f in excluded), excluded))
            continue
        checks.append(check_requirement(req, None, declarations, items, unreadable))
        if req.supported:
            for name in req.fields:
                field_requirements.setdefault(name, []).append(req.id)

    counts = {
        "supported_checks": sum(c.result in (PASS, FAIL, REVIEW) for c in checks),
        "passed": sum(c.result == PASS for c in checks),
        "failed": sum(c.result == FAIL for c in checks),
        "review": sum(c.result == REVIEW for c in checks),
        "not_supported": sum(c.result == NOT_SUPPORTED_RESULT for c in checks),
        "not_applicable": sum(c.result == NOT_APPLICABLE_RESULT for c in checks),
    }
    status, code, reason = _aggregate(counts)
    return PackageLabelEvaluation(
        **common, overall_status=status, reason_code=code, reason=reason, scope_status=IN_SCOPE,
        exclusions_found=[], checks=checks, summary=_summary(reason, counts, scope.assumptions),
        field_requirements=field_requirements, **counts,
    )


# ------------------------------------------------------------------ exclusions


def _exclusion_finding(exclusion: Exclusion, declarations: DeclarationStage, regions, items) -> ExclusionFinding | None:
    """Deterministic evidence for one exclusion, or None. Needs a clean reading."""
    sources = [s for s in (_quoted_source(q.knowledge_id, q.quote, items) for q in exclusion.sources) if s]
    base = dict(id=exclusion.id, description=exclusion.description, sources=sources)
    fields = {d.field: d for d in declarations.fields}

    if exclusion.id == "NET_QUANTITY_ABOVE_25_KG_OR_25_L":
        d = fields.get("net_quantity")
        if not _clean(d) or d.numeric_value is None:
            return None
        kg = d.numeric_value * _TO_KG[d.unit] if d.unit in _TO_KG else None
        litres = d.numeric_value * _TO_L[d.unit] if d.unit in _TO_L else None
        if (kg is not None and kg > 25) or (litres is not None and litres > 25):
            return ExclusionFinding(**base, observed=f"net quantity {d.value}", source_regions=list(d.source_regions),
                                    evidence=[_evidence(d)])
        return None

    if exclusion.id == "NOT_FOR_RETAIL_SALE_DECLARED":
        hits = [r for r in regions or () if _RE_NOT_FOR_RETAIL.search(getattr(r, "text", "") or "")
                and _confidence(r) >= _EXCLUSION_CONFIDENCE]
        if hits:
            evidence = [CheckEvidence(
                declaration_field="label_text", declaration_status=DETECTED, value=r.text.strip(),
                raw_text=r.text, source_regions=[r.id], image_id=getattr(r, "image_id", None),
                ocr_confidence=round(_confidence(r), 4), bbox=list(r.bbox) if getattr(r, "bbox", None) else None,
                source_images=[getattr(r, "image_id")] if getattr(r, "image_id", None) else [],
                source_sides=[getattr(r, "side")] if getattr(r, "side", None) else [],
            ) for r in hits]
            return ExclusionFinding(**base, observed=f"'{hits[0].text.strip()}'", source_regions=[r.id for r in hits],
                                    evidence=evidence)
        return None

    if exclusion.id == "FOOD_ARTICLE_FSSAI_LICENCE":
        d = fields.get("fssai_license")
        if _clean(d):
            return ExclusionFinding(**base, observed=f"FSSAI licence {d.value}", source_regions=list(d.source_regions),
                                    evidence=[_evidence(d)])
        return None
    return None


def _clean(d) -> bool:
    return (d is not None and d.status == DETECTED and d.consistency != "CONFLICT"
            and (d.ocr_confidence or 0.0) >= _EXCLUSION_CONFIDENCE
            and d.extraction_method != "deterministic_normalization")


def _confidence(region) -> float:
    try:
        return float(region.confidence)
    except (TypeError, ValueError):
        return 0.0


def _scope_reason(found: list[ExclusionFinding]) -> str:
    return ("Not applied: the label indicates the package is outside Chapter II of the Packaged Commodities Rules — "
            + "; ".join(f"{f.description} (read: {f.observed})" for f in found))


def _not_applicable(req, items, reason: str, findings: list[ExclusionFinding]) -> ComplianceCheck:
    return ComplianceCheck(
        **check_base(req, None, items), result=NOT_APPLICABLE_RESULT, reason_code="REQUIREMENT_NOT_APPLICABLE",
        reason=reason, reason_category=REASON_CATEGORIES["REQUIREMENT_NOT_APPLICABLE"],
        rule_condition="Not applied: an exclusion stated in the verified source is evidenced on the package.",
        observed_value="; ".join(f.observed for f in findings), expected_condition="Does not apply to this package.",
        evidence_status="NOT_APPLICABLE", evidence=[e for f in findings for e in f.evidence],
    )


# ------------------------------------------------------------------ aggregation


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _aggregate(c: dict) -> tuple[str, str, str]:
    if c["supported_checks"] == 0:
        return REVIEW, "NO_APPLICABLE_CHECKS", (
            "No checkable Legal Metrology requirement applies to this package in MetrIQ's current data."
        )
    if c["failed"]:
        return FAIL, "SUPPORTED_CHECK_FAILED", (
            f"{_plural(c['failed'], 'Legal Metrology check', 'Legal Metrology checks')} failed on clear package "
            "evidence. Confirm against the physical package."
        )
    if c["review"]:
        return REVIEW, "SUPPORTED_CHECK_NEEDS_REVIEW", (
            f"No Legal Metrology check failed, but {c['review']} could not be decided from the package evidence "
            "and need officer review."
        )
    if c["not_supported"]:
        return REVIEW, "REQUIREMENTS_NOT_CHECKABLE", (
            f"All {c['passed']} checkable Legal Metrology requirements passed, but "
            f"{_plural(c['not_supported'], 'requirement area', 'requirement areas')} cannot be checked from a "
            "package image. This is not a compliance determination."
        )
    return PASS, "ALL_CHECKS_PASSED", "Every applicable Legal Metrology package-label requirement was checked and passed."


def _summary(reason: str, c: dict, assumptions) -> list[str]:
    lines = [reason]
    if c["supported_checks"]:
        lines.append(_plural(c["failed"], "check failed.", "checks failed."))
        lines.append(_plural(c["passed"], "check passed.", "checks passed."))
        lines.append(_plural(c["review"], "check needs review.", "checks need review."))
    if c["not_applicable"]:
        lines.append(_plural(c["not_applicable"], "requirement does not apply to this package (exclusion evidenced).",
                             "requirements do not apply to this package (exclusion evidenced)."))
    if c["not_supported"]:
        lines.append(_plural(c["not_supported"], "requirement area cannot be checked from a package image.",
                             "requirement areas cannot be checked from a package image."))
    if assumptions:
        lines.append("Applies on the assumption that the package is intended for retail sale; see assumptions.")
    return lines
