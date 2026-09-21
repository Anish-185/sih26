"""Resolution: could MetrIQ establish this inspection's evidence chain from the photographed evidence?

MetrIQ produces no automatic PASS / FAIL / REVIEW compliance verdict.
``assess(analysis)`` reads a saved ``InspectionAnalysisOut`` as plain JSON and
reports, deterministically, every reason the product / standard / evidence
chain could not be fully established from the photos — never a legal or
compliance judgment. Deterministic; no model is involved, and nothing here
changes any other result.

Reasons (``REASONS``), each with the evidence system it comes from and the OCR
regions behind it:

  PIPELINE_ERROR              a pipeline stage failed and degraded to REVIEW
  IMAGES_UNREADABLE           a photo failed, or gave no (reliable) text
  IMAGE_QUALITY_LOW           a photo was flagged as low quality
  PRODUCT_NOT_IDENTIFIED      no product in the verified knowledge base matched
  MULTIPLE_CANDIDATES         more than one plausible product / standard remains
  PRODUCT_NOT_CONFIRMED       a candidate exists, but the label does not confirm it
  NO_VERIFIED_STANDARD        no verified BIS standard could be applied
  HALLMARK_NOT_VERIFIABLE     hallmark / HUID evidence (or claims printed about it) — MetrIQ never authenticates
  CONFLICTING_DECLARATIONS    photos or lines disagree on a declared value
  OCR_UNCERTAIN               a declaration MetrIQ has requirement data for could not be read reliably
  MISSING_EVIDENCE            a declaration MetrIQ has requirement data for was not found in the OCR text

``escalation_required`` is true whenever any reason is present.
"""

from __future__ import annotations

import re

REASONS: dict[str, str] = {
    "PIPELINE_ERROR": "Pipeline error",
    "IMAGES_UNREADABLE": "Unreadable photos",
    "IMAGE_QUALITY_LOW": "Low image quality",
    "PRODUCT_NOT_IDENTIFIED": "Product not identified",
    "MULTIPLE_CANDIDATES": "Several plausible products or standards",
    "PRODUCT_NOT_CONFIRMED": "Product not confirmed",
    "NO_VERIFIED_STANDARD": "No verified BIS standard",
    "HALLMARK_NOT_VERIFIABLE": "Hallmark / HUID cannot be verified",
    "CONFLICTING_DECLARATIONS": "Conflicting declarations",
    "OCR_UNCERTAIN": "Uncertain OCR evidence",
    "MISSING_EVIDENCE": "Evidence not found",
}

_RE_HALLMARK = re.compile(r"\bHUID\b|hall\s*mark", re.IGNORECASE)
_RE_FAILURE_NOTE = re.compile(r"(failed|error)\s*:", re.IGNORECASE)


def _reason(code: str, source: str, message: str, regions=(), checks=()) -> dict:
    return {
        "code": code,
        "label": REASONS[code],
        "source": source,  # OCR | PRODUCT | HALLMARKING | PIPELINE
        "message": message,
        "source_regions": sorted(set(regions)),
        "checks": list(dict.fromkeys(checks)),
    }


def _hallmark_included(analysis: dict) -> bool:
    h = analysis.get("hallmark")
    return bool(h) and (h.get("detected") or analysis.get("inspection_type") == "HALLMARK")


def _hallmark_reasons(analysis: dict, h: dict) -> list[dict]:
    """Structured hallmark evidence -> escalation. Detection is never authentication."""
    huid, purity = h["huid"], h["purity"]
    regions = [r for o in huid.get("candidates", []) + purity.get("candidates", []) + h.get("hallmark_text", [])
               for r in o["source_regions"]]
    out = []
    if h.get("detected"):
        what = {"DETECTED": f"Potential HUID {huid.get('value')} detected",
                "MULTIPLE": "Multiple potential HUID values detected",
                "UNCERTAIN": "Potential HUID detected with low OCR confidence or an unexpected form",
                }.get(huid["status"], "Hallmark evidence detected, but no potential HUID was read")
        out.append(_reason("HALLMARK_NOT_VERIFIABLE", "HALLMARKING",
                           f"{what}, but authenticity cannot be established from the uploaded image. External "
                           "authoritative HUID verification is required.", regions=regions))
        if purity["status"] == "CONFLICT":
            out.append(_reason("CONFLICTING_DECLARATIONS", "HALLMARKING", purity["reason"],
                               regions=[r for o in purity["candidates"] for r in o["source_regions"]]))
    elif analysis.get("inspection_type") == "HALLMARK":
        out.append(_reason("HALLMARK_NOT_VERIFIABLE", "HALLMARKING",
                           "Hallmark inspection, but no hallmark or HUID evidence was read in the photos; the "
                           "article must be examined physically."))
    claims = h.get("untrusted_claims") or []
    if claims:
        out.append(_reason("HALLMARK_NOT_VERIFIABLE", "HALLMARKING",
                           "Text printed on the item or package claims verification ("
                           + "; ".join(f"“{c['raw_text']}”" for c in claims[:3])
                           + "). Printed text is untrusted evidence and verifies nothing.",
                           regions=[r for c in claims for r in c["source_regions"]]))
    return out


def assess(analysis: dict) -> dict:
    """``{"required": bool, "reasons": [...]}`` for one saved analysis."""
    reasons: list[dict] = []
    product = analysis.get("product") or {}
    package = analysis.get("package") or {}

    # ---- pipeline ------------------------------------------------------
    for note in analysis.get("notes") or []:
        if _RE_FAILURE_NOTE.search(note):
            reasons.append(_reason("PIPELINE_ERROR", "PIPELINE", note))

    # ---- photos / OCR ----------------------------------------------------
    unreadable = [*package.get("images_failed", []), *package.get("images_no_text", []),
                  *package.get("images_no_reliable_text", [])]
    if unreadable or (analysis.get("declaration_stage") or {}).get("status") == "NO_RELIABLE_TEXT":
        what = ", ".join(unreadable) if unreadable else "the uploaded photos"
        reasons.append(_reason("IMAGES_UNREADABLE", "OCR",
                               f"No usable OCR evidence from {what}; declarations there cannot be determined."))
    low = [img for img in analysis.get("images", []) if (img.get("quality") or {}).get("is_low_quality")]
    if low:
        details = "; ".join(f"{img['side']} ({img['filename']}): {', '.join(img['quality'].get('notes') or [])}"
                            for img in low)
        reasons.append(_reason("IMAGE_QUALITY_LOW", "OCR", f"Low image quality — {details}."))

    # ---- product / standard ------------------------------------------------
    candidates = list(dict.fromkeys(c["standard_number"] for c in analysis.get("standards", [])))
    applicability = product.get("product_applicability")
    if product.get("status") != "MATCHED":
        if len(candidates) > 1:
            reasons.append(_reason("MULTIPLE_CANDIDATES", "PRODUCT",
                                   f"{product.get('reason', '')} Candidates: {', '.join(candidates)}."))
        elif candidates:
            reasons.append(_reason("PRODUCT_NOT_CONFIRMED", "PRODUCT",
                                   f"{product.get('reason', '')} Candidate: {candidates[0]}."))
        else:
            reasons.append(_reason("PRODUCT_NOT_IDENTIFIED", "PRODUCT", product.get("reason", "")))
        reasons.append(_reason("NO_VERIFIED_STANDARD", "PRODUCT",
                               "No verified BIS standard could be applied, so no verified requirement evidence "
                               "was connected to this package."))
    elif applicability == "PRODUCT_AMBIGUOUS":
        reasons.append(_reason("MULTIPLE_CANDIDATES", "PRODUCT",
                               "The package text names more than one product MetrIQ has modelled requirement "
                               f"data for under {product.get('standard_number')}."))
    elif applicability == "PRODUCT_NOT_CONFIRMED":
        reasons.append(_reason("PRODUCT_NOT_CONFIRMED", "PRODUCT",
                               f"MetrIQ has product-specific requirement data under {product.get('standard_number')}, "
                               "but the package text did not confirm which modelled product this is."))

    # ---- hallmark ------------------------------------------------------------
    hallmark = analysis.get("hallmark")
    if hallmark is not None:
        reasons.extend(_hallmark_reasons(analysis, hallmark))
    else:  # analyses saved before structured hallmark evidence existed
        ocr_text = (analysis.get("ocr") or {}).get("text") or ""
        hallmark_regions = [r["id"] for r in (analysis.get("ocr") or {}).get("regions", []) if _RE_HALLMARK.search(r["text"])]
        if _RE_HALLMARK.search(ocr_text):
            reasons.append(_reason(
                "HALLMARK_NOT_VERIFIABLE", "OCR",
                "Hallmark / HUID information appears in this inspection. MetrIQ never authenticates a hallmark or "
                "verifies a HUID; it must be verified against an authoritative source (for example the "
                "official BIS Care App).",
                regions=hallmark_regions,
            ))

    # ---- declarations --------------------------------------------------------
    conflicts = [d for d in (analysis.get("declaration_stage") or {}).get("fields", []) if d.get("consistency") == "CONFLICT"]
    for d in conflicts:
        sides = sorted({s for o in d.get("observations", []) for s in o.get("source_sides", [])})
        where = f" across {', '.join(sides)}" if sides else ""
        regions = [r for o in d.get("observations", []) for r in o.get("source_regions", [])] or d["source_regions"]
        reasons.append(_reason("CONFLICTING_DECLARATIONS", "OCR",
                               f"{d['label']}: different values were read{where}. {d.get('reason', '')}".strip(),
                               regions=regions))

    # ---- declarations a verified requirement uses, but OCR could not settle ----
    completeness = analysis.get("completeness") or {}
    for item in completeness.get("items", []):
        if item.get("requirement_coverage") != "VERIFIED_REQUIREMENT" or item.get("conflict"):
            continue  # conflicts are already reported per declaration above
        if item.get("status") == "UNCERTAIN":
            reasons.append(_reason("OCR_UNCERTAIN", "OCR", f"{item['label']}: {item.get('statement', '')}",
                                   regions=item.get("source_regions", [])))
        elif item.get("status") == "NOT_DETECTED":
            reasons.append(_reason("MISSING_EVIDENCE", "OCR",
                                   f"{item['label']}: a verified requirement uses this field, but no OCR evidence "
                                   "was found for it in the uploaded photos."))

    order = list(REASONS)
    reasons.sort(key=lambda r: (order.index(r["code"]), r["source"]))
    return {"required": bool(reasons), "reasons": reasons}
