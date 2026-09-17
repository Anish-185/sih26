"""Escalation: can the automated system resolve this inspection, or does it go to an officer?

    SYSTEM RESULT (PASS / FAIL / REVIEW)
      -> can the system confidently resolve this case?
           yes -> final system result, no officer review   (officer_status NOT_REQUIRED)
           no  -> officer review queue                      (officer_status PENDING)

``assess(analysis)`` reads a saved ``InspectionAnalysisOut`` as plain JSON (so the
database migration can reuse it for inspections saved before escalation existed)
and returns every reason the case cannot be resolved automatically. Deterministic;
no model is involved, and nothing here changes a result.

Reasons (``REASONS``), each with the evidence system it comes from and the OCR
regions / checks behind it:

  PIPELINE_ERROR              a pipeline stage failed and degraded to REVIEW
  IMAGES_UNREADABLE           a photo failed, or gave no (reliable) text
  IMAGE_QUALITY_LOW           a photo was flagged as low quality
  PRODUCT_NOT_IDENTIFIED      no product in the verified knowledge base matched
  MULTIPLE_CANDIDATES         more than one plausible product / standard remains
  PRODUCT_NOT_CONFIRMED       a candidate exists, but the label does not confirm it
  NO_VERIFIED_STANDARD        no verified BIS standard could be applied
  HALLMARK_NOT_VERIFIABLE     hallmark / HUID evidence (or claims printed about it) — MetrIQ never authenticates
  CONFLICTING_DECLARATIONS    photos or lines disagree on a declared value
  OCR_UNCERTAIN               a check could not rely on the OCR reading
  MISSING_EVIDENCE            a check found no evidence for a declaration
  REQUIREMENT_NOT_CHECKABLE   the standard / requirement areas cannot be checked from an image
  PACKAGE_SCOPE_EXCLUSION     the label indicates the Legal Metrology rules may not apply
  SYSTEM_RESULT_REVIEW        the BIS or Legal Metrology result is REVIEW

Only ``REQUIREMENT_NOT_CHECKABLE`` depends on the result: requirement areas that
cannot be checked could still overturn a PASS, but not a FAIL that clear evidence
already established. Every other reason always escalates. A FAIL is resolved
automatically only when nothing else is unresolved; a PASS only when every
applicable requirement was checked.
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
    "REQUIREMENT_NOT_CHECKABLE": "Requirements not checkable from an image",
    "PACKAGE_SCOPE_EXCLUSION": "Legal Metrology scope exclusion",
    "SYSTEM_RESULT_REVIEW": "System result is REVIEW",
}

_RE_HALLMARK = re.compile(r"\bHUID\b|hall\s*mark", re.IGNORECASE)

# check reason_category -> escalation reason
_CATEGORY_REASON = {
    "EVIDENCE_NOT_DETECTED": "MISSING_EVIDENCE",
    "EVIDENCE_NOT_DETERMINABLE": "MISSING_EVIDENCE",
    "CONFLICTING_EVIDENCE": "CONFLICTING_DECLARATIONS",
    "INSUFFICIENT_EVIDENCE": "OCR_UNCERTAIN",
}
_SOURCE_NAME = {"BIS": "BIS", "LEGAL_METROLOGY": "Legal Metrology", "HALLMARKING": "Hallmarking"}


def _reason(code: str, source: str, message: str, regions=(), checks=()) -> dict:
    return {
        "code": code,
        "label": REASONS[code],
        "source": source,  # OCR | PRODUCT | BIS | LEGAL_METROLOGY | HALLMARKING | PIPELINE
        "message": message,
        "source_regions": sorted(set(regions)),
        "checks": list(dict.fromkeys(checks)),
    }


def _hallmark_included(analysis: dict) -> bool:
    h = analysis.get("hallmark")
    return bool(h) and (h.get("detected") or analysis.get("inspection_type") == "HALLMARK")


def _package_label_applied(analysis: dict) -> bool:
    return analysis["package_label"].get("scope_status") != "NOT_APPLIED"


def system_results(analysis: dict) -> list[tuple[str, str]]:
    """(evidence system, result) for every evidence system that applies to this inspection."""
    out = [("BIS", analysis["compliance"]["overall_status"])]
    if _package_label_applied(analysis):
        out.append(("LEGAL_METROLOGY", analysis["package_label"]["overall_status"]))
    if _hallmark_included(analysis):
        out.append(("HALLMARKING", analysis["hallmark"]["overall_status"]))
    return out


def system_result(analysis: dict) -> str:
    """FAIL if any applicable evidence system FAILs; PASS only if all PASS; otherwise REVIEW."""
    results = [r for _, r in system_results(analysis)]
    if "FAIL" in results:
        return "FAIL"
    return "PASS" if all(r == "PASS" for r in results) else "REVIEW"


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
    """``{"required": bool, "system_result": ..., "reasons": [...]}`` for one saved analysis."""
    result = system_result(analysis)
    reasons: list[dict] = []
    compliance = analysis["compliance"]
    package_label = analysis["package_label"]
    product = analysis["product"]
    package = analysis.get("package") or {}
    systems = (("BIS", compliance),) + ((("LEGAL_METROLOGY", package_label),) if _package_label_applied(analysis) else ())

    # ---- pipeline ----------------------------------------------------------
    for source, ev in systems:
        if ev.get("reason_code") == "ENGINE_ERROR":
            reasons.append(_reason("PIPELINE_ERROR", source, ev.get("reason") or "A pipeline stage failed."))

    # ---- photos / OCR ------------------------------------------------------
    unreadable = [*package.get("images_failed", []), *package.get("images_no_text", []),
                  *package.get("images_no_reliable_text", [])]
    if unreadable or analysis["declaration_stage"]["status"] == "NO_RELIABLE_TEXT":
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
    applicability = (compliance.get("coverage") or {}).get("product_applicability")
    if product["status"] != "MATCHED":
        if len(candidates) > 1:
            reasons.append(_reason("MULTIPLE_CANDIDATES", "PRODUCT",
                                   f"{product['reason']} Candidates: {', '.join(candidates)}."))
        elif candidates:
            reasons.append(_reason("PRODUCT_NOT_CONFIRMED", "PRODUCT",
                                   f"{product['reason']} Candidate: {candidates[0]}."))
        else:
            reasons.append(_reason("PRODUCT_NOT_IDENTIFIED", "PRODUCT", product["reason"]))
    elif applicability == "PRODUCT_AMBIGUOUS":
        reasons.append(_reason("MULTIPLE_CANDIDATES", "PRODUCT", compliance.get("reason") or
                               "The package text names more than one modelled product."))
    if compliance.get("coverage_status") == "NO_STANDARD" and compliance.get("reason_code") != "ENGINE_ERROR":
        reasons.append(_reason("NO_VERIFIED_STANDARD", "BIS",
                               "No verified BIS standard could be applied, so no BIS requirement was checked."))

    hallmark = analysis.get("hallmark")
    if hallmark is not None:
        reasons.extend(_hallmark_reasons(analysis, hallmark))
        if compliance.get("reason_code") == "DOMAIN_NOT_PACKAGE_LABEL" and not any(
                r["code"] == "HALLMARK_NOT_VERIFIABLE" for r in reasons):
            reasons.append(_reason(
                "HALLMARK_NOT_VERIFIABLE", "BIS",
                f"{compliance.get('standard_number') or 'The identified standard'} is a jewellery hallmarking "
                "standard. MetrIQ never authenticates a hallmark or verifies a HUID; an officer must verify the "
                "article."))
    else:  # analyses saved before structured hallmark evidence existed
        ocr_text = (analysis.get("ocr") or {}).get("text") or ""
        hallmark_regions = [r["id"] for r in (analysis.get("ocr") or {}).get("regions", []) if _RE_HALLMARK.search(r["text"])]
        if compliance.get("reason_code") == "DOMAIN_NOT_PACKAGE_LABEL" or _RE_HALLMARK.search(ocr_text):
            reasons.append(_reason(
                "HALLMARK_NOT_VERIFIABLE", "BIS",
                "Hallmark / HUID information appears in this inspection. MetrIQ never authenticates a hallmark or "
                "verifies a HUID; an officer must verify it (for example through the official BIS CARE app).",
                regions=hallmark_regions,
            ))

    # ---- declarations ------------------------------------------------------
    conflicts = [d for d in analysis["declaration_stage"].get("fields", []) if d.get("consistency") == "CONFLICT"]
    for d in conflicts:
        sides = sorted({s for o in d.get("observations", []) for s in o.get("source_sides", [])})
        where = f" across {', '.join(sides)}" if sides else ""
        regions = [r for o in d.get("observations", []) for r in o.get("source_regions", [])] or d["source_regions"]
        reasons.append(_reason("CONFLICTING_DECLARATIONS", "OCR",
                               f"{d['label']}: different values were read{where}. {d.get('reason', '')}".strip(),
                               regions=regions))

    # ---- checks ------------------------------------------------------------
    grouped: dict[tuple[str, str], list[dict]] = {}
    for source, ev in systems:
        for c in ev.get("checks", []):
            code = None
            if c["result"] == "REVIEW":
                code = _CATEGORY_REASON.get(c["reason_category"], "OCR_UNCERTAIN")
            elif c["result"] == "NOT_SUPPORTED":
                code = "REQUIREMENT_NOT_CHECKABLE"
            if code:
                grouped.setdefault((code, source), []).append(c)
    for (code, source), checks in grouped.items():
        if code == "CONFLICTING_DECLARATIONS" and conflicts:
            continue  # already reported per declaration
        names = "; ".join(f"{c['reference'] or c['rule_id']}: {c['reason']}" if code != "REQUIREMENT_NOT_CHECKABLE"
                          else (c["reference"] or c["requirement"]) for c in checks)
        prefix = {
            "MISSING_EVIDENCE": "No evidence was read for",
            "OCR_UNCERTAIN": "The OCR evidence could not decide",
            "CONFLICTING_DECLARATIONS": "Conflicting evidence for",
            "REQUIREMENT_NOT_CHECKABLE": "Cannot be checked from a photo:",
        }[code]
        count = f"{len(checks)} {_SOURCE_NAME[source]} {'check' if len(checks) == 1 else 'checks'}"
        message = (f"{prefix} {names}" if code == "REQUIREMENT_NOT_CHECKABLE"
                   else f"{prefix} {count} — {names}")
        reasons.append(_reason(code, source, message,
                               regions=[r for c in checks for e in c.get("evidence", []) for r in e["source_regions"]],
                               checks=[c["rule_id"] for c in checks]))
    if compliance.get("coverage_status") in ("STANDARD_ONLY", "UNSUPPORTED") and \
            compliance.get("reason_code") != "DOMAIN_NOT_PACKAGE_LABEL":
        reasons.append(_reason("REQUIREMENT_NOT_CHECKABLE", "BIS",
                               f"{compliance.get('standard_number') or 'The identified standard'} has no requirement "
                               f"MetrIQ can check from a package image ({compliance['coverage_status']})."))

    if package_label.get("scope_status") == "OUT_OF_SCOPE":
        reasons.append(_reason(
            "PACKAGE_SCOPE_EXCLUSION", "LEGAL_METROLOGY", package_label.get("reason") or "",
            regions=[r for f in package_label.get("exclusions_found", []) for r in f.get("source_regions", [])],
        ))

    for source, ev in systems:
        if ev["overall_status"] == "REVIEW" and ev.get("reason_code") != "ENGINE_ERROR":
            reasons.append(_reason("SYSTEM_RESULT_REVIEW", source,
                                   f"{_SOURCE_NAME[source]} result is REVIEW: {ev.get('reason', '')}"))

    if _hallmark_included(analysis) and hallmark["overall_status"] == "REVIEW":
        reasons.append(_reason("SYSTEM_RESULT_REVIEW", "HALLMARKING", f"Hallmarking result is REVIEW: {hallmark['reason']}"))

    order = list(REASONS)
    reasons.sort(key=lambda r: (order.index(r["code"]), r["source"]))
    blocking = [r for r in reasons if not (r["code"] == "REQUIREMENT_NOT_CHECKABLE" and result == "FAIL")]
    return {"required": bool(blocking), "system_result": result, "reasons": reasons}
