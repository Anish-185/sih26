"""Inspection analysis — IMAGE -> OCR -> declarations -> product -> standard.

Two entry points share one OCR path:

* ``InspectionAnalyzer.ocr``     — Instant OCR: decode, quality, OCR, then
  deterministic declaration extraction linked to the OCR regions. No model, no
  retrieval, no rules. (POST /inspection/ocr)
* ``InspectionAnalyzer.analyze`` — Smart Inspection: the same OCR step, then
  the downstream pipeline. (POST /inspection/analyze)

``analyze`` decodes the uploaded package image, runs lightweight quality checks
and local OCR, then runs the downstream pipeline
(``app.pipeline``): deterministic declaration extraction, then product
identification and ranked standard candidates from the verified BIS knowledge
base through the existing retrieval engine (``app.product_identification``).

Compliance (``app.compliance``) applies only verified requirements with
deterministic rules; officer review is still a later phase (``PENDING``).
Nothing here is fabricated: a stage that cannot produce a reliable result reports
``REVIEW``.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.api import ReasonOut, WhyOut
from app.declarations import extract_declarations, has_reliable_text
from app.llm import LocalLLM
from app.product import ProductStandardFinder
from app.product_identification import RETRIEVAL_NOTE, product_name_of
from app.ocr import OCR_ENGINE, OcrError, RawRegion, run_ocr
from app.pipeline import run_downstream

# Guard rails for a demo backend on a laptop.
MAX_BYTES = 20 * 1024 * 1024          # 20 MB upload cap
MIN_DIMENSION = 80                    # px — smaller than this cannot hold a label
MAX_DIMENSION = 6000                  # px — anything larger is downscaled for OCR
OCR_MAX_SIDE = 2000                   # px — long side the OCR engine actually sees
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF", "MPO"}

# One inspection = one physical package, photographed from one or more sides.
MAX_IMAGES = 8
MAX_TOTAL_BYTES = 60 * 1024 * 1024
PACKAGE_SIDES = ("FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM")
SIDES = (*PACKAGE_SIDES, "UNKNOWN")


@dataclass(frozen=True)
class PackageUpload:
    """One uploaded photo of the package. ``filename`` is display-only, never trusted."""

    data: bytes
    filename: str = "upload"
    side: str | None = None


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
    id: str = Field(
        description="Unique within one inspection: OCR-001 for a single image, "
        "I2-OCR-001 for the second image of a multi-image package."
    )
    image_id: str = Field(description="The image this region was read from.")
    side: str = Field(default="UNKNOWN", description="Package side of that image.")
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


class ObservationOut(BaseModel):
    """One reading of a field, kept when the field was read more than once."""

    value: str | None = None
    source_regions: list[str]
    source_images: list[str]
    source_sides: list[str]
    ocr_confidence: float


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
    source_images: list[str] = Field(default_factory=list, description="Every image the value was read from.")
    source_sides: list[str] = Field(default_factory=list, description="Package sides of those images.")
    consistency: str = Field(
        default="",
        description='"SINGLE" | "DUPLICATE" (same value read more than once) | '
        '"CONFLICT" (different values — withheld, UNCERTAIN) | "" when not detected',
    )
    observations: list[ObservationOut] = Field(
        default_factory=list, description="Every reading, when the field was read more than once."
    )


class DeclarationStageOut(BaseModel):
    status: str = Field(
        description='"COMPLETED" | "PARTIAL" | "REVIEW" | "NO_RELIABLE_TEXT"'
    )
    fields: list[DeclarationOut] = Field(
        description="Every searched field exactly once, in display order."
    )
    principal_display_panel: bool
    notes: list[str] = Field(default_factory=list)


class PackageImageOut(BaseModel):
    """One photo of the package and its own OCR evidence."""

    image_id: str
    index: int = Field(description="1-based upload order.")
    side: str = Field(description='"FRONT" | "BACK" | "LEFT" | "RIGHT" | "TOP" | "BOTTOM" | "UNKNOWN"')
    filename: str
    status: str = Field(
        description='"COMPLETED" | "NO_RELIABLE_TEXT" (text read, none reliable) | '
        '"NO_TEXT" (no text detected) | "FAILED" (image unreadable or OCR error)'
    )
    error: str | None = None
    format: str | None = None
    width: int | None = None
    height: int | None = None
    bytes: int
    quality: QualityOut | None = None
    ocr: OcrOut | None = None
    notes: list[str] = Field(default_factory=list)


class PackageCoverageOut(BaseModel):
    """What the uploaded photos cover. "Not uploaded", "OCR failed" and "no text"
    are different states, and none of them means a declaration is absent."""

    image_count: int
    usable_images: int
    sides_uploaded: list[str]
    sides_not_uploaded: list[str]
    images_failed: list[str]
    images_no_text: list[str]
    images_no_reliable_text: list[str]


class InstantOcrOut(BaseModel):
    """Instant OCR — raw OCR evidence plus the declarations read from it.
    No product identification, standard lookup or compliance check."""

    status: str = Field(
        description='"COMPLETED" (text found) | "NO_TEXT" (nothing legible — '
        "needs a better photo or officer review)"
    )
    inspection_id: str
    created_at: str
    image: ImageInfoOut = Field(description="The first readable image (kept for single-image clients).")
    quality: QualityOut = Field(description="Quality of the first readable image.")
    ocr: OcrOut = Field(description="OCR regions of every image combined.")
    images: list[PackageImageOut]
    package: PackageCoverageOut
    declaration_stage: DeclarationStageOut
    notes: list[str] = Field(default_factory=list)


class ProductClueOut(BaseModel):
    """One piece of package text used to identify the product."""

    kind: str = Field(
        description='"product_name" | "product_description" | "brand" | '
        '"standard_number" | "ocr_text" | "model_hint"'
    )
    text: str = Field(description="The package text exactly as OCR/declarations read it.")
    search_text: str = Field(
        default="",
        description="What was searched when OCR ran words together; empty when identical.",
    )
    declaration_field: str | None = None
    declaration_status: str | None = None
    source_regions: list[str] = Field(default_factory=list, description="OCR region ids.")
    image_id: str | None = None
    ocr_confidence: float | None = None


class ProductEvidenceOut(BaseModel):
    """Why one package clue supports one knowledge-base standard."""

    clue: ProductClueOut
    match: str = Field(description='"product" | "alias" | "category" | "standard_number"')
    matched_phrase: str
    retrieval_confidence: str
    retrieval_score: float


class ProductIdentificationOut(BaseModel):
    status: str = Field(description='"MATCHED" | "REVIEW"')
    name: str | None = Field(
        default=None, description="BIS product description from the knowledge base."
    )
    knowledge_id: str | None = None
    standard_number: str | None = None
    confidence: str = Field(
        description="Retrieval confidence (high | medium | low | none) — not compliance."
    )
    method: str = Field(description='"deterministic" | "model_assisted"')
    reason: str
    evidence: list[ProductEvidenceOut] = Field(default_factory=list)
    unverified_standard_numbers: list[str] = Field(
        default_factory=list,
        description="IS numbers printed on the label with no verified knowledge-base record.",
    )
    notes: list[str] = Field(default_factory=list)


class StandardCandidateOut(BaseModel):
    """A verified knowledge-base standard supported by the package evidence."""

    id: str
    standard_number: str
    title: str
    product: str = Field(description="BIS product description from the knowledge base.")
    tier: str = Field(description='"product" | "alias" | "category" | "standard_number"')
    printed_on_label: bool
    score: float
    confidence: str = Field(description="Retrieval confidence — not compliance or certification.")
    matched_terms: list[str]
    reasons: list[ReasonOut]
    why: WhyOut
    evidence: list[ProductEvidenceOut]
    source_organization: str
    source_url: str | None = None
    document_name: str | None = None
    reference: str | None = None
    verification_status: str
    last_verified: str | None = None


class CheckEvidenceOut(BaseModel):
    """Package evidence behind a check: declaration -> OCR regions -> image."""

    declaration_field: str
    declaration_status: str
    value: str | None = None
    raw_text: str
    source_regions: list[str]
    image_id: str | None = None
    ocr_confidence: float | None = None
    bbox: list[int] | None = None
    source_images: list[str] = Field(default_factory=list)
    source_sides: list[str] = Field(default_factory=list)


class RequirementSourceOut(BaseModel):
    """Knowledge evidence behind a requirement: the verified BIS record it quotes."""

    knowledge_id: str
    title: str
    quote: str = Field(description="Word-for-word sentence from the verified record.")
    source_url: str | None = None
    document_name: str | None = None
    reference: str | None = None
    verification_status: str
    last_verified: str | None = None


class ComplianceCheckOut(BaseModel):
    rule_id: str
    requirement: str
    rule_type: str
    standard_number: str
    result: str = Field(description='"PASS" | "FAIL" | "REVIEW" | "NOT_SUPPORTED"')
    reason_code: str = Field(description="Machine-readable reason, e.g. EVIDENCE_NOT_DETECTED.")
    reason: str = Field(description="Deterministic, factual explanation produced by the rule.")
    reason_category: str = Field(
        description='"REQUIREMENT_SATISFIED" | "REQUIREMENT_NOT_SATISFIED" | "EVIDENCE_NOT_DETECTED" | '
        '"EVIDENCE_NOT_DETERMINABLE" | "CONFLICTING_EVIDENCE" | "INSUFFICIENT_EVIDENCE" | "NOT_SUPPORTED"'
    )
    rule_condition: str = Field(description="The exact deterministic condition the rule applies.")
    observed_value: str | None = None
    expected_condition: str
    evidence_status: str = Field(
        description='"SUFFICIENT" | "INSUFFICIENT" | "NOT_DETECTED" | "NOT_APPLICABLE"'
    )
    evidence: list[CheckEvidenceOut]
    source: RequirementSourceOut | None = None


class ComplianceCoverageOut(BaseModel):
    supported_checks: int
    passed: int
    failed: int
    review: int
    not_supported: int
    # Product-specific coverage: product -> standard -> requirements -> rules.
    product_applicability: str = Field(
        default="NO_STANDARD",
        description='"PRODUCT_CONFIRMED" | "PRODUCT_NOT_MODELLED" | "PRODUCT_NOT_CONFIRMED" | '
        '"PRODUCT_AMBIGUOUS" | "NO_STANDARD"',
    )
    product_id: str | None = None
    product_name: str | None = Field(default=None, description="Modelled inspection product, when confirmed.")
    product_category: str | None = None
    applicability_source: RequirementSourceOut | None = Field(
        default=None, description="Verified record that links the confirmed product to the standard."
    )
    verified_requirements: int = 0
    deterministic_rules: int = 0
    unsupported_requirements: int = 0
    not_applied_requirements: list[str] = Field(
        default_factory=list,
        description="Product-limited requirements under this standard that were not applied (product not confirmed).",
    )
    explanation: str = Field(default="", description="Deterministic: what MetrIQ can and cannot inspect here.")


class CoverageRowOut(BaseModel):
    """One row of MetrIQ's coverage matrix: product | standard | requirement | rule | evidence | status."""

    standard_number: str
    standard_knowledge_id: str
    standard_title: str
    product_id: str | None = None
    product_name: str | None = None
    product_category: str | None = None
    applicability_source: str | None = None
    requirement_id: str | None = None
    requirement: str | None = None
    rule_type: str | None = None
    declaration_field: str | None = None
    requirement_source: str | None = None
    status: str = Field(description='"SUPPORTED" | "UNSUPPORTED" | "NO_REQUIREMENT_DATA"')
    standard_coverage: str = Field(description='"SUPPORTED_FOR_INSPECTION" | "STANDARD_ONLY"')


class StandardCoverageOut(BaseModel):
    standard_number: str
    knowledge_id: str
    title: str
    products: list[str]
    verified_requirements: int
    deterministic_rules: int
    unsupported_requirements: int
    inspection_status: str


class CoverageMatrixOut(BaseModel):
    """What MetrIQ can currently inspect, derived from the verified data — not a compliance result."""

    standards: list[StandardCoverageOut]
    rows: list[CoverageRowOut]
    errors: list[str] = Field(default_factory=list, description="Requirement data rejected by the loader.")


class ComplianceOut(BaseModel):
    """Deterministic compliance evaluation. Never decided by a model."""

    overall_status: str = Field(description='"PASS" | "FAIL" | "REVIEW"')
    coverage_status: str = Field(
        description='"SUPPORTED_FOR_INSPECTION" | "STANDARD_ONLY" | "NO_STANDARD"'
    )
    reason_code: str
    reason: str
    product_name: str | None = None
    standard_number: str | None = None
    knowledge_id: str | None = None
    coverage: ComplianceCoverageOut
    checks: list[ComplianceCheckOut]
    policy: str
    notes: list[str] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list, description="Deterministic overall explanation, one fact per line.")
    unreadable_images: list[str] = Field(default_factory=list)


class CompletenessItemOut(BaseModel):
    field: str
    label: str
    status: str = Field(description='"DETECTED" | "UNCERTAIN" | "NOT_DETECTED" (OCR evidence only)')
    conflict: bool
    value: str | None = None
    statement: str = Field(description='Factual; "not detected" never means legally missing.')
    requirement_coverage: str = Field(
        description='"VERIFIED_REQUIREMENT" (a verified, checkable requirement uses this field) | '
        '"NOT_ESTABLISHED" (MetrIQ does not know whether it is required)'
    )
    requirement_ids: list[str] = Field(default_factory=list)
    source_sides: list[str] = Field(default_factory=list)
    source_images: list[str] = Field(default_factory=list)
    source_regions: list[str] = Field(default_factory=list)
    raw_text: str = ""
    ocr_confidence: float | None = None


class CompletenessOut(BaseModel):
    standard_number: str | None = None
    items: list[CompletenessItemOut]
    detected: int
    uncertain: int
    not_detected: int
    conflicts: int
    with_verified_requirement: int
    unreadable_images: list[str] = Field(default_factory=list)
    note: str


class PipelineStagesOut(BaseModel):
    ocr: str
    declaration_extraction: str
    product_identification: str
    standard_retrieval: str
    compliance: str = "REVIEW"
    officer_review: str = "PENDING"


class InspectionAnalysisOut(BaseModel):
    inspection_id: str
    created_at: str
    image: ImageInfoOut
    quality: QualityOut
    ocr: OcrOut
    images: list[PackageImageOut]
    package: PackageCoverageOut
    declaration_stage: DeclarationStageOut
    product: ProductIdentificationOut
    standards: list[StandardCandidateOut] = Field(
        description="Ranked verified knowledge-base standards supported by the package evidence."
    )
    retrieval_note: str = RETRIEVAL_NOTE
    compliance: ComplianceOut
    completeness: CompletenessOut
    pipeline: PipelineStagesOut
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

OcrEngine = Callable[[np.ndarray], tuple[list[RawRegion], float]]


class InspectionAnalyzer:
    """Decode -> quality -> OCR [-> declarations -> product -> standard].

    Stateless; safe to reuse. ``llm`` is optional: when it is ``None`` (or the
    server is unreachable) product identification is deterministic only and
    unresolved stages report ``REVIEW``. Instant OCR never uses it.
    ``product_finder`` defaults to the API's shared knowledge-base finder.

    ``ocr_engine`` defaults to the real local engine (``app.ocr.run_ocr``);
    tests pass a stand-in to exercise failure handling without the model.
    """

    def __init__(
        self,
        llm: LocalLLM | None = None,
        ocr_engine: OcrEngine = run_ocr,
        product_finder: ProductStandardFinder | None = None,
    ) -> None:
        self._llm = llm
        self._ocr_engine = ocr_engine
        self._product_finder = product_finder

    def ocr(self, data: bytes, filename: str, side: str | None = None) -> InstantOcrOut:
        """Instant OCR of one image (see ``ocr_package``)."""
        return self.ocr_package([PackageUpload(data, filename, side)])

    def analyze(self, data: bytes, filename: str, side: str | None = None) -> InspectionAnalysisOut:
        """Smart Inspection of one image (see ``analyze_package``)."""
        return self.analyze_package([PackageUpload(data, filename, side)])

    def ocr_package(self, uploads: list[PackageUpload]) -> InstantOcrOut:
        """Instant OCR of one package photographed from one or more sides.

        Every image is validated and OCR'd on its own with the same engine; its
        regions keep their image_id and side. Declarations are extracted from all
        regions together. No product identification, standard retrieval, model
        call or rule check happens here.

        One image: any error is raised (unchanged single-image behaviour). Several
        images: a failed image is reported with status FAILED and the others are
        still processed; only if every image fails is an error raised.
        """
        sides = self._validate_package(uploads)
        multi = len(uploads) > 1
        images: list[PackageImageOut] = []
        errors: list[Exception] = []
        for index, (upload, side) in enumerate(zip(uploads, sides), start=1):
            try:
                images.append(self._read_image(upload, index, side, prefix=f"I{index}-" if multi else ""))
            except (ImageError, OcrError) as exc:
                if not multi:
                    raise
                errors.append(exc)
                images.append(PackageImageOut(
                    image_id=_image_id(upload.data), index=index, side=side,
                    filename=upload.filename or "upload", status="FAILED", error=str(exc),
                    bytes=len(upload.data),
                ))

        usable = [img for img in images if img.ocr is not None]
        if not usable:
            raise errors[0]

        regions = [r for img in usable for r in img.ocr.regions]
        notes: list[str] = []
        for img in images:
            label = _image_label(img) if multi else ""
            if img.status == "FAILED":
                notes.append(
                    f"{label}: OCR failed ({img.error}). No evidence could be read from this image, "
                    "so declarations on it cannot be determined."
                )
            else:
                notes.extend(f"{label}: {n}" if label else n for n in img.notes)

        # Deterministic declarations over every image's regions. Isolated so an
        # extraction bug can never break the OCR evidence.
        try:
            declaration_stage = _declaration_stage_out(extract_declarations(regions))
        except Exception as exc:  # noqa: BLE001
            declaration_stage = DeclarationStageOut(
                status="REVIEW", fields=[], principal_display_panel=False,
                notes=[f"Declaration extraction error: {exc}"],
            )
            notes.append(f"Declaration extraction error: {exc}")

        first = usable[0]
        return InstantOcrOut(
            status="COMPLETED" if regions else "NO_TEXT",
            inspection_id=f"INS-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
            created_at=datetime.now(timezone.utc).isoformat(),
            image=ImageInfoOut(
                image_id=first.image_id, filename=first.filename, format=first.format or "UNKNOWN",
                width=first.width or 0, height=first.height or 0, bytes=first.bytes,
            ),
            quality=first.quality,
            ocr=OcrOut(
                engine=OCR_ENGINE,
                text="\n".join(r.text for r in regions),
                region_count=len(regions),
                mean_confidence=round(sum(r.confidence for r in regions) / len(regions), 4) if regions else 0.0,
                duration_ms=sum(img.ocr.duration_ms for img in usable),
                regions=regions,
            ),
            images=images,
            package=_package_coverage(images),
            declaration_stage=declaration_stage,
            notes=notes,
        )

    def analyze_package(self, uploads: list[PackageUpload]) -> InspectionAnalysisOut:
        """Smart Inspection of one package: Instant OCR of every image, then the
        downstream pipeline (declarations -> product -> standards -> compliance)
        over the combined evidence."""
        evidence = self.ocr_package(uploads)
        regions = evidence.ocr.regions
        notes = list(evidence.notes)

        # ---- downstream pipeline (declarations -> product -> standard) ----
        # Isolated so a pipeline bug can never break the OCR response.
        # Photos that gave no usable OCR: evidence on them cannot be determined.
        package = evidence.package
        gaps = package.images_failed + package.images_no_text + package.images_no_reliable_text
        unreadable = gaps if len(evidence.images) > 1 else []

        try:
            downstream = run_downstream(regions, self._llm, self._product_finder, unreadable_images=unreadable)
            declaration_stage, product, standards, compliance, completeness, pipeline = (
                _declaration_stage_out(downstream.declaration_stage),
                _product_out(downstream.product),
                [_candidate_out(c) for c in downstream.product.candidates],
                _compliance_out(downstream.compliance),
                CompletenessOut(
                    **{k: v for k, v in downstream.completeness.__dict__.items() if k != "items"},
                    items=[CompletenessItemOut(**i.__dict__) for i in downstream.completeness.items],
                ),
                _pipeline_out(downstream.stages),
            )
            notes.extend(downstream.notes)
        except Exception as exc:  # noqa: BLE001
            declaration_stage, product, standards, compliance, pipeline = _all_review(
                f"Downstream pipeline error: {exc}"
            )
            completeness = CompletenessOut(
                items=[], detected=0, uncertain=0, not_detected=0, conflicts=0,
                with_verified_requirement=0, note=f"Downstream pipeline error: {exc}",
            )
            notes.append(f"Downstream pipeline error: {exc}")

        # The compliance result must say when some photos gave no usable evidence.
        if unreadable:
            compliance.notes.append(
                "Some images gave no usable OCR evidence (" + "; ".join(gaps) + "). Checks use the "
                "remaining images only; unread evidence is never treated as a finding about the package."
            )

        return InspectionAnalysisOut(
            inspection_id=evidence.inspection_id,
            created_at=evidence.created_at,
            image=evidence.image,
            quality=evidence.quality,
            ocr=evidence.ocr,
            images=evidence.images,
            package=package,
            declaration_stage=declaration_stage,
            product=product,
            standards=standards,
            compliance=compliance,
            completeness=completeness,
            pipeline=pipeline,
            notes=notes,
        )

    @staticmethod
    def _validate_package(uploads: list[PackageUpload]) -> list[str]:
        if not uploads:
            raise ImageError("Upload at least one image.")
        if len(uploads) > MAX_IMAGES:
            raise ImageError(f"At most {MAX_IMAGES} images per package.")
        if sum(len(u.data) for u in uploads) > MAX_TOTAL_BYTES:
            raise ImageError(f"Images exceed the {MAX_TOTAL_BYTES // (1024 * 1024)} MB total limit.")
        sides: list[str] = []
        for u in uploads:
            side = (u.side or "UNKNOWN").strip().upper() or "UNKNOWN"
            if side not in SIDES:
                raise ImageError(f"Unknown package side '{u.side}'. Use one of: {', '.join(SIDES)}.")
            sides.append(side)
        seen: set[str] = set()
        for u in uploads:
            key = hashlib.sha256(u.data).hexdigest()
            if u.data and key in seen:
                raise ImageError("The same image was uploaded more than once.")
            seen.add(key)
        return sides

    def _read_image(self, upload: PackageUpload, index: int, side: str, prefix: str) -> PackageImageOut:
        """Validate, measure and OCR one image. Raises ImageError / OcrError."""
        data = upload.data
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

        image_id = _image_id(data)
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
                    id=f"{prefix}OCR-{i:03d}",
                    image_id=image_id,
                    side=side,
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
        notes: list[str] = []
        if not regions:
            status = "NO_TEXT"
            notes.append(
                "OCR found no legible text in this image. "
                "Try a sharper, straight-on photo of the declaration panel."
            )
        elif not has_reliable_text(regions):
            status = "NO_RELIABLE_TEXT"
            notes.append("OCR read only low-confidence fragments in this image.")
        else:
            status = "COMPLETED"
        notes.extend(quality.notes)

        return PackageImageOut(
            image_id=image_id, index=index, side=side, filename=upload.filename or "upload",
            status=status, format=fmt, width=width, height=height, bytes=len(data), quality=quality,
            ocr=OcrOut(
                engine=OCR_ENGINE,
                text="\n".join(x.text for x in regions),
                region_count=len(regions),
                mean_confidence=mean_conf,
                duration_ms=int(elapsed * 1000),
                regions=regions,
            ),
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

def _image_id(data: bytes) -> str:
    return f"IMG-{hashlib.sha256(data).hexdigest()[:12].upper()}"


def _image_label(img: PackageImageOut) -> str:
    return f"{img.side} (image {img.index})"


def _package_coverage(images: list[PackageImageOut]) -> PackageCoverageOut:
    uploaded = [s for s in PACKAGE_SIDES if any(img.side == s for img in images)]
    return PackageCoverageOut(
        image_count=len(images),
        usable_images=sum(img.status in ("COMPLETED", "NO_RELIABLE_TEXT") for img in images),
        sides_uploaded=uploaded + (["UNKNOWN"] if any(img.side == "UNKNOWN" for img in images) else []),
        sides_not_uploaded=[s for s in PACKAGE_SIDES if s not in uploaded],
        images_failed=[_image_label(i) for i in images if i.status == "FAILED"],
        images_no_text=[_image_label(i) for i in images if i.status == "NO_TEXT"],
        images_no_reliable_text=[_image_label(i) for i in images if i.status == "NO_RELIABLE_TEXT"],
    )


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
                source_images=list(d.source_images),
                source_sides=list(d.source_sides),
                consistency=d.consistency,
                observations=[ObservationOut(**o.__dict__) for o in d.observations],
            )
            for d in stage.fields
        ],
        principal_display_panel=stage.principal_display_panel,
        notes=list(stage.notes),
    )


def _clue_out(clue) -> ProductClueOut:
    return ProductClueOut(
        kind=clue.kind,
        text=clue.text,
        search_text=clue.search_text,
        declaration_field=clue.declaration_field,
        declaration_status=clue.declaration_status,
        source_regions=list(clue.source_regions),
        image_id=clue.image_id,
        ocr_confidence=clue.ocr_confidence,
    )


def _evidence_out(ev) -> ProductEvidenceOut:
    return ProductEvidenceOut(
        clue=_clue_out(ev.clue),
        match=ev.match,
        matched_phrase=ev.matched_phrase,
        retrieval_confidence=ev.retrieval_confidence,
        retrieval_score=ev.retrieval_score,
    )


def _product_out(product) -> ProductIdentificationOut:
    return ProductIdentificationOut(
        status=product.status,
        name=product.name,
        knowledge_id=product.knowledge_id,
        standard_number=product.standard_number,
        confidence=product.confidence,
        method=product.method,
        reason=product.reason,
        evidence=[_evidence_out(ev) for ev in product.evidence],
        unverified_standard_numbers=list(product.unverified_standard_numbers),
        notes=list(product.notes),
    )


def _candidate_out(candidate) -> StandardCandidateOut:
    result, item, why = candidate.result, candidate.result.item, candidate.why
    return StandardCandidateOut(
        id=item.id,
        standard_number=item.standard_number or "",
        title=item.title,
        product=product_name_of(item),
        tier=candidate.tier,
        printed_on_label=candidate.printed_on_label,
        score=result.score,
        confidence=result.confidence,
        matched_terms=list(result.matched_terms),
        reasons=[
            ReasonOut(field=r.field, term=r.term, weight=r.weight, detail=r.detail)
            for r in result.reasons
        ],
        why=WhyOut(
            standard_number=why.standard_number,
            strength=why.strength,
            signals=list(why.signals),
            summary=why.summary,
        ),
        evidence=[_evidence_out(ev) for ev in candidate.evidence],
        source_organization=item.source_organization,
        source_url=item.source_url,
        document_name=item.document_name,
        reference=item.reference,
        verification_status=item.verification_status,
        last_verified=item.last_verified.isoformat() if item.last_verified else None,
    )


def _coverage_out(ev) -> ComplianceCoverageOut:
    counts = dict(supported_checks=ev.supported_checks, passed=ev.passed, failed=ev.failed,
                  review=ev.review, not_supported=ev.not_supported)
    ic = getattr(ev, "inspection_coverage", None)
    if ic is None:
        return ComplianceCoverageOut(**counts)
    return ComplianceCoverageOut(
        **counts,
        product_applicability=ic.product_applicability, product_id=ic.product_id,
        product_name=ic.product_name, product_category=ic.product_category,
        applicability_source=RequirementSourceOut(**ic.applicability_source.__dict__) if ic.applicability_source else None,
        verified_requirements=ic.verified_requirements, deterministic_rules=ic.deterministic_rules,
        unsupported_requirements=ic.unsupported_requirements,
        not_applied_requirements=list(ic.not_applied_requirements), explanation=ic.explanation,
    )


def _compliance_out(ev) -> ComplianceOut:
    return ComplianceOut(
        overall_status=ev.overall_status,
        coverage_status=ev.coverage_status,
        reason_code=ev.reason_code,
        reason=ev.reason,
        product_name=ev.product_name,
        standard_number=ev.standard_number,
        knowledge_id=ev.knowledge_id,
        coverage=_coverage_out(ev),
        checks=[
            ComplianceCheckOut(
                rule_id=c.rule_id, requirement=c.requirement, rule_type=c.rule_type,
                standard_number=c.standard_number, result=c.result, reason_code=c.reason_code,
                reason=c.reason, reason_category=c.reason_category, rule_condition=c.rule_condition,
                observed_value=c.observed_value,
                expected_condition=c.expected_condition, evidence_status=c.evidence_status,
                evidence=[CheckEvidenceOut(**e.__dict__) for e in c.evidence],
                source=RequirementSourceOut(**c.source.__dict__) if c.source else None,
            )
            for c in ev.checks
        ],
        policy=ev.policy,
        notes=list(ev.notes),
        summary=list(ev.summary),
        unreadable_images=list(ev.unreadable_images),
    )


def _pipeline_out(stages) -> PipelineStagesOut:
    return PipelineStagesOut(
        ocr=stages.ocr,
        declaration_extraction=stages.declaration_extraction,
        product_identification=stages.product_identification,
        standard_retrieval=stages.standard_retrieval,
        compliance=stages.compliance,
        officer_review=stages.officer_review,
    )


def _all_review(note: str):
    """Fallback when the whole downstream pipeline raised."""
    return (
        DeclarationStageOut(
            status="REVIEW",
            fields=[],
            principal_display_panel=False,
            notes=[note],
        ),
        ProductIdentificationOut(
            status="REVIEW", confidence="none", method="deterministic", reason=note,
        ),
        [],
        ComplianceOut(
            overall_status="REVIEW", coverage_status="NO_STANDARD", reason_code="ENGINE_ERROR",
            reason=note, coverage=ComplianceCoverageOut(
                supported_checks=0, passed=0, failed=0, review=0, not_supported=0),
            checks=[], policy="",
        ),
        PipelineStagesOut(
            ocr="COMPLETED",
            declaration_extraction="REVIEW",
            product_identification="REVIEW",
            standard_retrieval="REVIEW",
        ),
    )
