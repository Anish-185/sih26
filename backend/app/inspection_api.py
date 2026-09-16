"""HTTP layer for the inspection pipeline.

    POST /inspection/ocr       multipart/form-data, field "image"
      -> InstantOcrOut
         (image info + quality + raw OCR regions — the evidence layer only;
          no model, no retrieval, no rules)

    POST /inspection/analyze   multipart/form-data, field "image"
      -> InspectionAnalysisOut
         (the same OCR evidence + declarations + product identification
          + ranked verified Indian Standard candidates)
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.inspection import (
    MAX_BYTES,
    ImageError,
    InspectionAnalysisOut,
    InspectionAnalyzer,
    InstantOcrOut,
)
from app.api import get_product_finder
from app.llm import LocalLLM
from app.ocr import OcrError

router = APIRouter(prefix="/inspection", tags=["inspection"])


@lru_cache(maxsize=1)
def get_analyzer() -> InspectionAnalyzer:
    # Product identification uses the shared knowledge base and retrieval engine.
    # The model is only asked for a search term when the package text identified
    # nothing; a short timeout keeps the request responsive, and if LM Studio is
    # down identification is simply deterministic-only.
    return InspectionAnalyzer(llm=LocalLLM(timeout=45.0), product_finder=get_product_finder())


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


@router.post("/ocr", response_model=InstantOcrOut)
async def instant_ocr(
    image: UploadFile = File(...),
    analyzer: InspectionAnalyzer = Depends(get_ocr_analyzer),
) -> InstantOcrOut:
    """Instant OCR: decode the uploaded image, run quality checks and local
    OCR, and return the raw OCR regions. Nothing is interpreted."""
    data = await _read_image(image)
    try:
        return analyzer.ocr(data, image.filename or "upload")
    except ImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OcrError as exc:
        raise HTTPException(status_code=503, detail=f"OCR unavailable: {exc}") from exc


@router.post("/analyze", response_model=InspectionAnalysisOut)
async def analyze(image: UploadFile = File(...)) -> InspectionAnalysisOut:
    """Smart Inspection: the same OCR step, then declaration extraction,
    product identification and verified Indian Standard candidates."""
    data = await _read_image(image)
    try:
        return get_analyzer().analyze(data, image.filename or "upload")
    except ImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OcrError as exc:
        raise HTTPException(status_code=503, detail=f"OCR unavailable: {exc}") from exc
