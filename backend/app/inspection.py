"""Inspection analysis — IMAGE -> OCR -> declarations -> product -> standard.

Two entry points share one OCR path:

* ``InspectionAnalyzer.ocr``     — Instant OCR: decode, quality, OCR, then
  deterministic declaration extraction linked to the OCR regions. No model, no
  retrieval, no rules. (POST /inspection/ocr)
* ``InspectionAnalyzer.analyze`` — Smart Inspection: the same OCR step, then
  the downstream pipeline. (POST /inspection/analyze)

``analyze`` decodes the uploaded package image, runs lightweight quality checks
and local OCR, then runs the downstream pipeline
(``app.pipeline``): deterministic declaration extraction, product classification
(deterministic, else local Qwen3-4B), and a verified Indian Standard lookup.

Legal-metrology PASS/FAIL is still a later phase and is reported as ``NEXT``.
Nothing here is fabricated: a stage that cannot produce a reliable result reports
``REVIEW``.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.declarations import extract_declarations
from app.llm import LocalLLM
from app.ocr import OCR_ENGINE, OcrError, RawRegion, run_ocr
from app.pipeline import run_downstream

# Guard rails for a demo backend on a laptop.
MAX_BYTES = 20 * 1024 * 1024          # 20 MB upload cap
MIN_DIMENSION = 80                    # px — smaller than this cannot hold a label
MAX_DIMENSION = 6000                  # px — anything larger is downscaled for OCR
OCR_MAX_SIDE = 2000                   # px — long side the OCR engine actually sees
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF", "MPO"}


class ImageError(ValueError):
    """The uploaded bytes are not a usable image."""


# ---------------------------------------------------------------------------
# Response models  (mirrors backend/app/api.py conventions: `*Out` suffix)
# ---------------------------------------------------------------------------

class ImageInfoOut(BaseModel):
    image_id: str = Field(
        description="Content hash of the uploaded bytes, e.g. IMG-3F2A9C01B7DE. "
        "The same image always gets the same id."
    )
    filename: str
    format: str
    width: int
    height: int
    bytes: int


class QualityOut(BaseModel):
    blur_score: float = Field(
        description="Variance of the Laplacian. Higher = sharper; "
        "roughly < 100 indicates a blurred image."
    )
    brightness: float = Field(description="Mean luma, 0-255.")
    contrast: float = Field(description="Std-dev of luma, 0-255.")
    is_low_quality: bool
    notes: list[str]


class OcrRegionOut(BaseModel):
    id: str = Field(description="Stable within one analysis, e.g. OCR-001.")
    image_id: str = Field(description="The image this region was read from.")
    text: str = Field(description="Raw recognised text, exactly as OCR returned it.")
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: list[int] = Field(
        description="Axis-aligned [x1, y1, x2, y2] in source-image pixels."
    )
    polygon: list[list[int]] = Field(
        description="Original [[x,y] x4] quad (may be rotated), pixels."
    )


class OcrOut(BaseModel):
    engine: str
    text: str = Field(description="All region texts joined in reading order.")
    region_count: int
    mean_confidence: float
    duration_ms: int
    regions: list[OcrRegionOut]


class DeclarationOut(BaseModel):
    field: str
    label: str
    status: str = Field(
        description='"DETECTED" | "UNCERTAIN" | "NOT_DETECTED". NOT_DETECTED only '
        "means the OCR text did not contain it — not that it is legally missing."
    )
    value: str | None = None
    unit: str | None = None
    numeric_value: float | None = None
    raw_text: str = Field(description="OCR text of the source regions, verbatim.")
    source_regions: list[str] = Field(description="OCR region ids, e.g. OCR-004.")
    source_region_id: str | None = Field(default=None, description="First source region.")
    bbox: list[int] | None = Field(default=None, description="Union of the source boxes.")
    image_id: str | None = None
    ocr_confidence: float | None = Field(
        default=None,
        description="Lowest OCR reading confidence of the source regions. How sure "
        "the OCR engine was about the text — not whether the declaration is correct.",
    )
    method: str = Field(description='"regex" | "keyword" | "heuristic"')
    extraction_method: str = Field(description='"deterministic"')
    note: str = ""
    reason: str = Field(default="", description="Why UNCERTAIN / NOT_DETECTED.")


class DeclarationStageOut(BaseModel):
    status: str = Field(
        description='"COMPLETED" | "PARTIAL" | "REVIEW" | "NO_RELIABLE_TEXT"'
    )
    fields: list[DeclarationOut] = Field(
        description="Every searched field exactly once, in display order."
    )
    principal_display_panel: bool
    notes: list[str] = Field(default_factory=list)


class InstantOcrOut(BaseModel):
    """Instant OCR — raw OCR evidence plus the declarations read from it.
    No product identification, standard lookup or compliance check."""

    status: str = Field(
        description='"COMPLETED" (text found) | "NO_TEXT" (nothing legible — '
        "needs a better photo or officer review)"
    )
    created_at: str
    image: ImageInfoOut
    quality: QualityOut
    ocr: OcrOut
    declaration_stage: DeclarationStageOut
    notes: list[str] = Field(default_factory=list)


class ClassificationOut(BaseModel):
    status: str = Field(description='"CLASSIFIED" | "REVIEW"')
    product_name: str | None = None
    normalized_product: str | None = None
    category: str | None = None
    subcategory: str | None = None
    confidence: float
    method: str = Field(description='"deterministic" | "llm"')
    reason: str
    source_declarations: list[str] = Field(default_factory=list)


class StandardOut(BaseModel):
    number: str
    title: str
    source: str
    source_url: str
    reference: str = ""
    status: str = "verified"


class StandardMatchOut(BaseModel):
    status: str = Field(description='"MATCHED" | "REVIEW"')
    normalized_product: str | None = None
    standard: StandardOut | None = None
    confidence: float
    matched_keywords: list[str] = Field(default_factory=list)
    reason: str = ""


class PipelineStagesOut(BaseModel):
    ocr: str
    declaration_extraction: str
    product_classification: str
    standard_lookup: str
    legal_metrology: str = "NEXT"
    officer_review: str = "PENDING"


class InspectionAnalysisOut(BaseModel):
    inspection_id: str
    created_at: str
    image: ImageInfoOut
    quality: QualityOut
    ocr: OcrOut
    # Phase 14 — real downstream pipeline.
    declaration_stage: DeclarationStageOut
    classification: ClassificationOut
    standard_match: StandardMatchOut
    pipeline: PipelineStagesOut
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

OcrEngine = Callable[[np.ndarray], tuple[list[RawRegion], float]]


class InspectionAnalyzer:
    """Decode -> quality -> OCR [-> declarations -> product -> standard].

    Stateless; safe to reuse. ``llm`` is optional: when it is ``None`` (or the
    server is unreachable) the pipeline uses deterministic classification only
    and degrades unresolved stages to ``REVIEW``. Instant OCR never uses it.

    ``ocr_engine`` defaults to the real local engine (``app.ocr.run_ocr``);
    tests pass a stand-in to exercise failure handling without the model.
    """

    def __init__(
        self,
        llm: LocalLLM | None = None,
        ocr_engine: OcrEngine = run_ocr,
    ) -> None:
        self._llm = llm
        self._ocr_engine = ocr_engine

    def ocr(self, data: bytes, filename: str) -> InstantOcrOut:
        """Instant OCR: validate the image, measure quality, run OCR and return
        the raw regions. No declaration extraction, classification, standard
        lookup, model call or rule check happens here."""
        if not data:
            raise ImageError("Empty upload.")
        if len(data) > MAX_BYTES:
            raise ImageError(
                f"Image is {len(data) // (1024 * 1024)} MB; the limit is "
                f"{MAX_BYTES // (1024 * 1024)} MB."
            )

        image = self._decode(data)
        fmt = (image.format or "").upper() or "UNKNOWN"

        # Respect EXIF orientation so bounding boxes line up with what the
        # frontend renders, then work in RGB.
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size

        if min(width, height) < MIN_DIMENSION:
            raise ImageError(
                f"Image is {width}x{height}px — too small to read a label."
            )

        image_id = f"IMG-{hashlib.sha256(data).hexdigest()[:12].upper()}"
        arr = np.asarray(image, dtype=np.uint8)
        quality = self._quality(arr)

        ocr_arr, scale = self._prepare_for_ocr(arr)
        try:
            raw_regions, elapsed = self._ocr_engine(ocr_arr)
        except OcrError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OcrError(f"OCR failed unexpectedly: {exc}") from exc

        regions: list[OcrRegionOut] = []
        for i, r in enumerate(raw_regions, start=1):
            bbox = [int(round(v / scale)) for v in r.bbox]
            polygon = [[int(round(x / scale)), int(round(y / scale))] for x, y in r.polygon]
            regions.append(
                OcrRegionOut(
                    id=f"OCR-{i:03d}",
                    image_id=image_id,
                    text=r.text,
                    confidence=round(r.confidence, 4),
                    bbox=bbox,
                    polygon=polygon,
                )
            )

        mean_conf = (
            round(sum(x.confidence for x in regions) / len(regions), 4)
            if regions
            else 0.0
        )
        joined = "\n".join(x.text for x in regions)

        notes: list[str] = []
        if not regions:
            notes.append(
                "OCR found no legible text in this image. "
                "Try a sharper, straight-on photo of the declaration panel."
            )
        notes.extend(quality.notes)

        # Deterministic declarations over the OCR regions. Isolated so an
        # extraction bug can never break the OCR evidence.
        try:
            declaration_stage = _declaration_stage_out(extract_declarations(regions))
        except Exception as exc:  # noqa: BLE001
            declaration_stage = DeclarationStageOut(
                status="REVIEW", fields=[], principal_display_panel=False,
                notes=[f"Declaration extraction error: {exc}"],
            )
            notes.append(f"Declaration extraction error: {exc}")

        return InstantOcrOut(
            status="COMPLETED" if regions else "NO_TEXT",
            created_at=datetime.now(timezone.utc).isoformat(),
            image=ImageInfoOut(
                image_id=image_id,
                filename=filename or "upload",
                format=fmt,
                width=width,
                height=height,
                bytes=len(data),
            ),
            quality=quality,
            ocr=OcrOut(
                engine=OCR_ENGINE,
                text=joined,
                region_count=len(regions),
                mean_confidence=mean_conf,
                duration_ms=int(elapsed * 1000),
                regions=regions,
            ),
            declaration_stage=declaration_stage,
            notes=notes,
        )

    def analyze(self, data: bytes, filename: str) -> InspectionAnalysisOut:
        """Smart Inspection: Instant OCR, then the downstream pipeline."""
        evidence = self.ocr(data, filename)
        regions = evidence.ocr.regions
        notes = list(evidence.notes)

        # ---- downstream pipeline (declarations -> product -> standard) ----
        # Isolated so a pipeline bug can never break the OCR response.
        try:
            downstream = run_downstream(regions, evidence.ocr.text, self._llm)
            declaration_stage, classification, standard_match, pipeline = (
                _declaration_stage_out(downstream.declaration_stage),
                _classification_out(downstream.classification),
                _standard_match_out(downstream.standard_match),
                _pipeline_out(downstream.stages),
            )
            notes.extend(downstream.notes)
        except Exception as exc:  # noqa: BLE001
            declaration_stage, classification, standard_match, pipeline = _all_review(
                f"Downstream pipeline error: {exc}"
            )
            notes.append(f"Downstream pipeline error: {exc}")

        return InspectionAnalysisOut(
            inspection_id=f"INS-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
            created_at=evidence.created_at,
            image=evidence.image,
            quality=evidence.quality,
            ocr=evidence.ocr,
            declaration_stage=declaration_stage,
            classification=classification,
            standard_match=standard_match,
            pipeline=pipeline,
            notes=notes,
        )

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _decode(data: bytes) -> Image.Image:
        try:
            image = Image.open(io.BytesIO(data))
            image.load()  # force decode now so corrupt files fail here
        except (UnidentifiedImageError, OSError) as exc:
            raise ImageError(
                "Could not read this file as an image. Supported: JPG, PNG, WEBP."
            ) from exc
        if (image.format or "").upper() not in SUPPORTED_FORMATS:
            raise ImageError(
                f"Unsupported image format: {image.format or 'unknown'}. "
                "Use JPG, PNG or WEBP."
            )
        return image

    @staticmethod
    def _quality(arr: np.ndarray) -> QualityOut:
        luma = (
            0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
        ).astype(np.float64)

        brightness = float(luma.mean())
        contrast = float(luma.std())

        # Variance of the Laplacian (a 3x3 kernel) as a blur proxy — the same
        # measure OpenCV's cv2.Laplacian(...).var() gives, done with numpy.
        lap = (
            -4.0 * luma
            + np.roll(luma, 1, 0)
            + np.roll(luma, -1, 0)
            + np.roll(luma, 1, 1)
            + np.roll(luma, -1, 1)
        )
        blur_score = float(lap[1:-1, 1:-1].var())

        notes: list[str] = []
        if blur_score < 80:
            notes.append("Image looks blurred — OCR confidence may be low.")
        if brightness < 55:
            notes.append("Image is quite dark.")
        elif brightness > 225:
            notes.append("Image is over-exposed / washed out.")
        if contrast < 25:
            notes.append("Low contrast between text and background.")

        return QualityOut(
            blur_score=round(blur_score, 2),
            brightness=round(brightness, 2),
            contrast=round(contrast, 2),
            is_low_quality=bool(notes),
            notes=notes,
        )

    @staticmethod
    def _prepare_for_ocr(arr: np.ndarray) -> tuple[np.ndarray, float]:
        """Downscale very large images so OCR stays quick. Returns the array
        the engine sees and the scale factor (ocr_px / source_px) so boxes can
        be mapped back to source coordinates."""
        h, w = arr.shape[:2]
        long_side = max(h, w)
        if long_side <= OCR_MAX_SIDE:
            return arr, 1.0
        scale = OCR_MAX_SIDE / long_side
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        resized = Image.fromarray(arr).resize(new_size, Image.LANCZOS)
        return np.asarray(resized, dtype=np.uint8), scale


# ---------------------------------------------------------------------------
# dataclass (app.pipeline) -> pydantic (*Out) converters
# ---------------------------------------------------------------------------

def _declaration_stage_out(stage) -> DeclarationStageOut:
    return DeclarationStageOut(
        status=stage.status,
        fields=[
            DeclarationOut(
                field=d.field,
                label=d.label,
                status=d.status,
                value=d.value,
                unit=d.unit,
                numeric_value=d.numeric_value,
                raw_text=d.raw_text,
                source_regions=list(d.source_regions),
                source_region_id=d.source_region_id,
                bbox=d.bbox,
                image_id=d.image_id,
                ocr_confidence=d.ocr_confidence,
                method=d.method,
                extraction_method=d.extraction_method,
                note=d.note,
                reason=d.reason,
            )
            for d in stage.fields
        ],
        principal_display_panel=stage.principal_display_panel,
        notes=list(stage.notes),
    )


def _classification_out(cls) -> ClassificationOut:
    return ClassificationOut(
        status=cls.status,
        product_name=cls.product_name,
        normalized_product=cls.normalized_product,
        category=cls.category,
        subcategory=cls.subcategory,
        confidence=cls.confidence,
        method=cls.method,
        reason=cls.reason,
        source_declarations=list(cls.source_declarations),
    )


def _standard_match_out(match) -> StandardMatchOut:
    std = None
    if match.standard is not None:
        std = StandardOut(
            number=match.standard.standard_number,
            title=match.standard.title,
            source=match.standard.source,
            source_url=match.standard.source_url,
            reference=match.standard.reference,
            status=match.standard.status,
        )
    return StandardMatchOut(
        status=match.status,
        normalized_product=match.normalized_product or None,
        standard=std,
        confidence=match.confidence,
        matched_keywords=list(match.matched_keywords),
        reason=match.reason,
    )


def _pipeline_out(stages) -> PipelineStagesOut:
    return PipelineStagesOut(
        ocr=stages.ocr,
        declaration_extraction=stages.declaration_extraction,
        product_classification=stages.product_classification,
        standard_lookup=stages.standard_lookup,
        legal_metrology=stages.legal_metrology,
        officer_review=stages.officer_review,
    )


def _all_review(note: str):
    """Fallback quartet when the whole downstream pipeline raised."""
    return (
        DeclarationStageOut(
            status="REVIEW",
            fields=[],
            principal_display_panel=False,
            notes=[note],
        ),
        ClassificationOut(
            status="REVIEW",
            confidence=0.0,
            method="deterministic",
            reason=note,
        ),
        StandardMatchOut(status="REVIEW", confidence=0.0, reason=note),
        PipelineStagesOut(
            ocr="COMPLETED",
            declaration_extraction="REVIEW",
            product_classification="REVIEW",
            standard_lookup="REVIEW",
        ),
    )
