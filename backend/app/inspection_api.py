"""HTTP layer for the inspection pipeline.

Both endpoints take ONE package, photographed from one or more sides
(multipart/form-data):

    image  (+ optional side)       a single photo — the original contract
    images (+ optional sides)      several photos of the same package; `sides`,
                                   when given, lists one side per image in order
                                   (FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, UNKNOWN)

    POST /inspection/ocr       -> InstantOcrOut
         (per-image OCR evidence + combined declarations; no model, no
          retrieval, no rules)

    POST /inspection/analyze   -> InspectionAnalysisOut
         (the same evidence + product identification + verified Indian Standard
          candidates + deterministic compliance over all images)

    GET  /inspection/coverage  -> CoverageMatrixOut
         (what MetrIQ can currently inspect: product | standard | requirement |
          rule | status, derived from the verified data — not a compliance result)
"""

from __future__ import annotations

from functools import lru_cache, partial
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api import get_product_finder
from app.inspection import (
    MAX_BYTES,
    CoverageMatrixOut,
    CoverageRowOut,
    CoverageTotalsOut,
    LegalMetrologyCoverageOut,
    PackageRequirementRowOut,
    ImageError,
    InspectionAnalysisOut,
    InspectionAnalyzer,
    InstantOcrOut,
    PackageUpload,
    StandardCoverageOut,
)
from app.llm import LocalLLM
from app.vision import VisionClient
from app.requirements import (
    coverage_by_standard,
    coverage_matrix,
    coverage_totals,
    load_requirements,
    package_requirement_rows,
)
from app.ocr import OcrError

router = APIRouter(prefix="/inspection", tags=["inspection"])


@lru_cache(maxsize=1)
def get_analyzer() -> InspectionAnalyzer:
    # Product identification uses the shared knowledge base and retrieval engine.
    # The model is only asked for a search term when the package text identified
    # nothing; a short timeout keeps the request responsive, and if LM Studio is
    # down identification is simply deterministic-only.
    # Visual understanding uses its OWN OpenRouter key (OPENROUTER_VISION_API_KEY),
    # separate from the DeepSeek copilot's. Unconfigured = identification is
    # deterministic + OCR only, exactly as before.
    return InspectionAnalyzer(llm=LocalLLM(timeout=45.0), product_finder=get_product_finder(),
                              vision=get_vision())


@lru_cache(maxsize=1)
def get_vision() -> VisionClient:
    """One client per process, so its free-tier counter and image cache are shared."""
    return VisionClient()


@lru_cache(maxsize=1)
def get_ocr_analyzer() -> InspectionAnalyzer:
    # Instant OCR has no model at all, so it works when LM Studio is down.
    return InspectionAnalyzer(llm=None)


async def _read_image(image: UploadFile) -> bytes:
    """Reject non-image uploads and oversize files before decoding."""
    content_type = (image.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(
            status_code=415,
            detail=f"Expected an image upload, got '{content_type}'.",
        )

    data = await image.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds the {MAX_BYTES // (1024 * 1024)} MB limit.",
        )
    return data


async def _package(
    image: UploadFile | None,
    side: str | None,
    images: list[UploadFile] | None,
    sides: list[str] | None,
) -> list[PackageUpload]:
    """Turn the form into package uploads: either `image` or `images`, not both."""
    images = images or []
    if image is not None and images:
        raise HTTPException(status_code=422, detail="Send either 'image' or 'images', not both.")
    if image is not None:
        files, labels = [image], [side]
    elif images:
        if sides and len(sides) != len(images):
            raise HTTPException(
                status_code=422,
                detail=f"'sides' has {len(sides)} entries for {len(images)} images.",
            )
        files, labels = images, (sides or [None] * len(images))
    else:
        raise HTTPException(status_code=422, detail="Upload at least one image ('image' or 'images').")
    return [
        PackageUpload(data=await _read_image(f), filename=f.filename or "upload", side=label)
        for f, label in zip(files, labels)
    ]


def _run(fn, uploads):
    try:
        return fn(uploads)
    except ImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OcrError as exc:
        raise HTTPException(status_code=503, detail=f"OCR unavailable: {exc}") from exc


@router.post("/ocr", response_model=InstantOcrOut)
async def instant_ocr(
    image: UploadFile | None = File(None),
    side: str | None = Form(None),
    images: list[UploadFile] | None = File(None),
    sides: list[str] | None = Form(None),
    analyzer: InspectionAnalyzer = Depends(get_ocr_analyzer),
) -> InstantOcrOut:
    """Instant OCR: decode each uploaded image, run quality checks and local
    OCR, and return the raw OCR regions per image plus the declarations read
    from all of them. Nothing else is interpreted."""
    uploads = await _package(image, side, images, sides)
    return _run(analyzer.ocr_package, uploads)


@router.post("/analyze", response_model=InspectionAnalysisOut)
async def analyze(
    image: UploadFile | None = File(None),
    side: str | None = Form(None),
    images: list[UploadFile] | None = File(None),
    sides: list[str] | None = Form(None),
    inspection_type: Literal["PACKAGE", "HALLMARK"] = Form("PACKAGE"),
) -> InspectionAnalysisOut:
    """Smart Inspection: the same OCR step for every image, then declaration
    extraction, product identification, verified Indian Standard candidates and
    deterministic compliance over the combined evidence."""
    uploads = await _package(image, side, images, sides)
    return _run(partial(get_analyzer().analyze_package, inspection_type=inspection_type), uploads)


@router.get("/coverage", response_model=CoverageMatrixOut)
def coverage() -> CoverageMatrixOut:
    """MetrIQ's inspection coverage, read from the verified data files. BIS standards and
    Legal Metrology package-label requirements are reported separately."""
    items = get_product_finder().search_engine.items
    requirements = load_requirements(items)
    standards = coverage_by_standard(items, requirements)
    totals = coverage_totals(items, requirements)
    scope = requirements.package_scope
    return CoverageMatrixOut(
        totals=CoverageTotalsOut(
            total=totals.bis_standards, inspection_supported=totals.bis_inspection_supported,
            standard_only=totals.bis_standard_only, unsupported=totals.bis_unsupported,
            **{k: v for k, v in totals.__dict__.items() if not k.startswith("bis_") or k in ("bis_requirements", "bis_rules")},
        ),
        standards=[StandardCoverageOut(**c.__dict__) for c in standards],
        rows=[CoverageRowOut(**r.__dict__) for r in coverage_matrix(items, requirements)],
        legal_metrology=LegalMetrologyCoverageOut(
            scope=scope.description if scope else "",
            exclusions=[e.description for e in scope.exclusions] if scope else [],
            assumptions=list(scope.assumptions) if scope else [],
            requirements=[PackageRequirementRowOut(**r.__dict__) for r in package_requirement_rows(requirements)],
        ),
        errors=list(requirements.errors),
    )
