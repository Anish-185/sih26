"""Downstream inspection pipeline.

    OCR regions
      -> declaration extraction   (deterministic)
      -> product identification   (existing BIS retrieval engine + product phrase gate)
      -> standard candidates      (verified knowledge-base records only)
      -> modelled-product confirmation (which of MetrIQ's requirement-data products this is, if any —
                                        pure requirements-lookup, no rule)
      -> declaration completeness (what the photos show, never "legally missing")

MetrIQ produces no automatic legal/compliance verdict. Each stage is isolated: a
failure in one stage degrades that stage to REVIEW and the pipeline still
returns. Nothing here fabricates a result.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.completeness import DeclarationCompleteness, declaration_completeness
from app.declarations import DeclarationStage, extract_declarations
from app.llm import LocalLLM
from app.product import ProductStandardFinder
from app.product_identification import MATCHED, ProductIdentification, identify_product
from app.vision import VisionObservation
from app.requirements import RequirementSet, confirm_product, load_requirements


@dataclass(frozen=True)
class PipelineStages:
    ocr: str
    declaration_extraction: str
    product_identification: str
    standard_retrieval: str


@dataclass(frozen=True)
class DownstreamResult:
    declaration_stage: DeclarationStage
    product: ProductIdentification
    completeness: DeclarationCompleteness
    stages: PipelineStages
    notes: list[str]
    # Which modelled product (app.requirements) this package is, under the
    # identified standard — pure requirements-lookup, not a rule verdict.
    product_applicability: str | None = None
    confirmed_product_id: str | None = None
    confirmed_product_name: str | None = None
    confirmed_product_category: str | None = None


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


def run_downstream(
    regions,
    llm: LocalLLM | None = None,
    finder: ProductStandardFinder | None = None,
    requirements: RequirementSet | None = None,
    unreadable_images: list[str] | tuple = (),
    inspection_type: str = "PACKAGE",
    vision_observations: list[VisionObservation] | tuple = (),
) -> DownstreamResult:
    """``unreadable_images`` labels photos of this package that gave no usable OCR.
    ``inspection_type`` is informational only here (hallmarking standards have no
    modelled package-label products, so ``confirm_product`` naturally reports
    PRODUCT_NOT_MODELLED for them).
    ``vision_observations`` are optional visual observations of the package; they
    refine product identification only, and their absence changes nothing else."""
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
        product = identify_product(decl, regions, finder, llm=llm, vision=vision_observations)
    except Exception as exc:  # noqa: BLE001
        product = _review_product(f"Product identification failed: {exc}")
        notes.append(str(exc))

    try:
        items = finder.search_engine.items if finder is not None else []
        if requirements is None:
            requirements = load_requirements(items)
    except Exception as exc:  # noqa: BLE001
        items = []
        if requirements is None:
            requirements = RequirementSet((), ())
        notes.append(str(exc))

    # 3) which modelled product does this match, under the identified standard —
    #    pure requirements-lookup, no rule engine ---------------------------
    applicability = confirmed = None
    if product.status == MATCHED:
        try:
            applicability, confirmed, _candidates = confirm_product(product, requirements)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Product confirmation failed: {exc}")

    # 4) declaration completeness — detection status + whether a verified
    #    requirement covers the field; never "legally missing" ---------------
    standard = product.standard_number if product.status == MATCHED else None
    try:
        completeness = declaration_completeness(
            decl, requirements, standard, unreadable_images,
            product_id=confirmed.id if confirmed else None,
        )
    except Exception as exc:  # noqa: BLE001
        completeness = declaration_completeness(decl, RequirementSet((), ()), None, unreadable_images)
        notes.append(f"Completeness requirement lookup failed: {exc}")

    stages = PipelineStages(
        ocr="COMPLETED",
        declaration_extraction=decl.status,
        product_identification=product.status,
        standard_retrieval=MATCHED if product.status == MATCHED else "REVIEW",
    )
    return DownstreamResult(
        declaration_stage=decl,
        product=product,
        completeness=completeness,
        stages=stages,
        notes=notes,
        product_applicability=applicability,
        confirmed_product_id=confirmed.id if confirmed else None,
        confirmed_product_name=confirmed.name if confirmed else None,
        confirmed_product_category=confirmed.category if confirmed else None,
    )
