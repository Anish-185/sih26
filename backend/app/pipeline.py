"""Downstream inspection pipeline.

    OCR regions
      -> declaration extraction   (deterministic)
      -> product identification   (existing BIS retrieval engine + product phrase gate)
      -> standard candidates      (verified knowledge-base records only)
      -> compliance               (verified requirements + deterministic rules)
      -> declaration completeness (what the photos show, never "legally missing")

Each stage is isolated: a failure in one stage degrades that stage to REVIEW and
the pipeline still returns. Nothing here fabricates a result.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.completeness import DeclarationCompleteness, declaration_completeness
from app.compliance import REVIEW, ComplianceEvaluation, evaluate_compliance
from app.declarations import DeclarationStage, extract_declarations
from app.llm import LocalLLM
from app.product import ProductStandardFinder
from app.product_identification import MATCHED, ProductIdentification, identify_product
from app.requirements import RequirementSet, load_requirements


@dataclass(frozen=True)
class PipelineStages:
    ocr: str
    declaration_extraction: str
    product_identification: str
    standard_retrieval: str
    compliance: str = REVIEW
    officer_review: str = "PENDING"


@dataclass(frozen=True)
class DownstreamResult:
    declaration_stage: DeclarationStage
    product: ProductIdentification
    compliance: ComplianceEvaluation
    completeness: DeclarationCompleteness
    stages: PipelineStages
    notes: list[str]


def _review_declarations(note: str) -> DeclarationStage:
    return DeclarationStage(
        status="REVIEW",
        fields=[],
        principal_display_panel=False,
        notes=[note],
    )


def _review_product(note: str) -> ProductIdentification:
    return ProductIdentification(
        status="REVIEW", name=None, knowledge_id=None, standard_number=None,
        confidence="none", method="deterministic", reason=note, evidence=[], candidates=[],
    )


def _review_compliance(note: str) -> ComplianceEvaluation:
    return ComplianceEvaluation(
        overall_status=REVIEW, coverage_status="NO_STANDARD", reason_code="ENGINE_ERROR",
        reason=note, product_name=None, standard_number=None, knowledge_id=None, checks=[],
    )


def run_downstream(
    regions,
    llm: LocalLLM | None = None,
    finder: ProductStandardFinder | None = None,
    requirements: RequirementSet | None = None,
    unreadable_images: list[str] | tuple = (),
) -> DownstreamResult:
    """``unreadable_images`` labels photos of this package that gave no usable OCR."""
    notes: list[str] = []

    # 1) declaration extraction ------------------------------------------
    try:
        decl = extract_declarations(regions)
    except Exception as exc:  # noqa: BLE001
        decl = _review_declarations(f"Declaration extraction failed: {exc}")
        notes.append(str(exc))

    # 2) product identification + standard candidates -------------------
    try:
        if finder is None:
            from app.api import get_product_finder  # shared, already-loaded knowledge base

            finder = get_product_finder()
        product = identify_product(decl, regions, finder, llm=llm)
    except Exception as exc:  # noqa: BLE001
        product = _review_product(f"Product identification failed: {exc}")
        notes.append(str(exc))

    # 3) compliance — verified requirements + deterministic rules, no model -------
    try:
        items = finder.search_engine.items if finder is not None else []
        if requirements is None:
            requirements = load_requirements(items)
        compliance = evaluate_compliance(product, decl, requirements, items, unreadable_images)
    except Exception as exc:  # noqa: BLE001
        compliance = _review_compliance(f"Compliance evaluation failed: {exc}")
        notes.append(str(exc))

    # 4) declaration completeness — detection status + whether a verified
    #    requirement covers the field; never "legally missing" ---------------
    standard = product.standard_number if product.status == MATCHED else None
    confirmed = compliance.inspection_coverage.product_id if compliance.inspection_coverage else None
    try:
        completeness = declaration_completeness(
            decl, requirements if requirements is not None else RequirementSet((), ()),
            standard, unreadable_images, product_id=confirmed,
        )
    except Exception as exc:  # noqa: BLE001
        completeness = declaration_completeness(decl, RequirementSet((), ()), None, unreadable_images)
        notes.append(f"Completeness requirement lookup failed: {exc}")

    stages = PipelineStages(
        ocr="COMPLETED",
        declaration_extraction=decl.status,
        product_identification=product.status,
        standard_retrieval=MATCHED if product.status == MATCHED else "REVIEW",
        compliance=compliance.overall_status,
    )
    return DownstreamResult(
        declaration_stage=decl,
        product=product,
        compliance=compliance,
        completeness=completeness,
        stages=stages,
        notes=notes,
    )
