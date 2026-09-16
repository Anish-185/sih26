"""Downstream inspection pipeline.

    OCR regions
      -> declaration extraction   (deterministic)
      -> product identification   (existing BIS retrieval engine + product phrase gate)
      -> standard candidates      (verified knowledge-base records only)

Each stage is isolated: a failure in one stage degrades that stage to REVIEW and
the pipeline still returns. Nothing here fabricates a result.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.declarations import DeclarationStage, extract_declarations
from app.llm import LocalLLM
from app.product import ProductStandardFinder
from app.product_identification import MATCHED, ProductIdentification, identify_product


@dataclass(frozen=True)
class PipelineStages:
    ocr: str
    declaration_extraction: str
    product_identification: str
    standard_retrieval: str
    legal_metrology: str = "NEXT"
    officer_review: str = "PENDING"


@dataclass(frozen=True)
class DownstreamResult:
    declaration_stage: DeclarationStage
    product: ProductIdentification
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


def run_downstream(
    regions,
    llm: LocalLLM | None = None,
    finder: ProductStandardFinder | None = None,
) -> DownstreamResult:
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

    stages = PipelineStages(
        ocr="COMPLETED",
        declaration_extraction=decl.status,
        product_identification=product.status,
        standard_retrieval=MATCHED if product.status == MATCHED else "REVIEW",
    )
    return DownstreamResult(
        declaration_stage=decl,
        product=product,
        stages=stages,
        notes=notes,
    )
