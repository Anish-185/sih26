"""Downstream inspection pipeline (Phase 14).

    OCR regions
      -> declaration extraction   (deterministic)
      -> product classification   (deterministic, else local Qwen3-4B)
      -> Indian Standard lookup    (verified registry only)

Each stage is isolated: a failure in one stage degrades that stage to REVIEW and
the pipeline still returns. Nothing here fabricates a result.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.classification import ProductClassification, classify_product
from app.declarations import DeclarationStage, extract_declarations
from app.llm import LocalLLM
from app.standards_registry import StandardMatch, lookup_standard


@dataclass(frozen=True)
class PipelineStages:
    ocr: str
    declaration_extraction: str
    product_classification: str
    standard_lookup: str
    legal_metrology: str = "NEXT"
    officer_review: str = "PENDING"


@dataclass(frozen=True)
class DownstreamResult:
    declaration_stage: DeclarationStage
    classification: ProductClassification
    standard_match: StandardMatch
    stages: PipelineStages
    notes: list[str]


def _review_declarations(note: str) -> DeclarationStage:
    return DeclarationStage(
        status="REVIEW",
        fields=[],
        principal_display_panel=False,
        notes=[note],
    )


def _review_classification(note: str) -> ProductClassification:
    return ProductClassification(
        status="REVIEW",
        product_name=None,
        normalized_product=None,
        category=None,
        subcategory=None,
        confidence=0.0,
        method="deterministic",
        reason=note,
    )


def _review_match(note: str) -> StandardMatch:
    return StandardMatch(
        status="REVIEW",
        normalized_product="",
        standard=None,
        confidence=0.0,
        reason=note,
    )


def run_downstream(
    regions,
    ocr_text: str,
    llm: LocalLLM | None = None,
) -> DownstreamResult:
    notes: list[str] = []

    # 1) declaration extraction ------------------------------------------
    try:
        decl = extract_declarations(regions)
    except Exception as exc:  # noqa: BLE001
        decl = _review_declarations(f"Declaration extraction failed: {exc}")
        notes.append(str(exc))

    # 2) product classification ----------------------------------------
    try:
        cls = classify_product(decl, ocr_text, llm=llm)
    except Exception as exc:  # noqa: BLE001
        cls = _review_classification(f"Product classification failed: {exc}")
        notes.append(str(exc))

    # 3) Indian Standard lookup ----------------------------------------
    try:
        if cls.status == "CLASSIFIED" and cls.normalized_product:
            extra = " ".join(
                d.value for d in decl.declarations
                if d.field in ("product_name", "product_description")
            )
            match = lookup_standard(cls.normalized_product, extra_terms=extra)
        else:
            match = _review_match(
                "Product was not classified, so no standard lookup was attempted."
            )
    except Exception as exc:  # noqa: BLE001
        match = _review_match(f"Standard lookup failed: {exc}")
        notes.append(str(exc))

    stages = PipelineStages(
        ocr="COMPLETED",
        declaration_extraction=decl.status,
        product_classification=cls.status,
        standard_lookup=match.status,
    )
    return DownstreamResult(
        declaration_stage=decl,
        classification=cls,
        standard_match=match,
        stages=stages,
        notes=notes,
    )
