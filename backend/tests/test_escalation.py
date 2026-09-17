"""Checks for Milestone 10 — escalation: can the system resolve an inspection, or does an officer?

Covers every escalation reason on real pipeline output (controlled OCR text, real
declaration extraction, product identification, BIS compliance and Legal
Metrology checks), the resolve / escalate decision, determinism, and the
/inspection/analyze contract. No database, no LM Studio.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_escalation.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import copy
import io
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.api import get_product_finder  # noqa: E402
from app.escalation import REASONS, assess  # noqa: E402
from app.inspection import InspectionAnalyzer, PackageUpload  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import RawRegion  # noqa: E402

PASS = 0
FAIL = 0
SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "ocr-labels"
SOURCES = {"OCR", "PRODUCT", "BIS", "LEGAL_METROLOGY", "PIPELINE"}


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def photo(width: int, textured: bool = True) -> bytes:
    """A textured photo passes the image-quality checks; a flat one does not."""
    if textured:
        arr = np.random.default_rng(width).integers(40, 215, (400, width, 3), dtype=np.uint8)
        img = Image.fromarray(arr)
    else:
        img = Image.new("RGB", (width, 400), (15, 15, 15))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def raw(*texts, conf=0.95):
    out, y = [], 20
    for i, t in enumerate(texts):
        h = 50 if i == 0 else 25
        out.append(RawRegion(t, conf, (10, y, 10 + 10 * len(t), y + h),
                             [[10, y], [10 + 10 * len(t), y], [10 + 10 * len(t), y + h], [10, y + h]]))
        y += h + 15
    return out


class Engine:
    def __init__(self, by_width):
        self.by_width = by_width

    def __call__(self, arr):
        r = self.by_width[arr.shape[1]]
        if isinstance(r, Exception):
            raise r
        return list(r), 0.01


def analyse(*sides, textured=True):
    """sides: (width, side, regions | Exception). Returns the analysis as saved JSON."""
    analyzer = InspectionAnalyzer(ocr_engine=Engine({w: r for w, _, r in sides}), product_finder=get_product_finder())
    out = analyzer.analyze_package([PackageUpload(photo(w, textured), f"{s.lower()}.png", s) for w, s, _ in sides])
    return out, out.model_dump(mode="json")


def codes(result):
    return [r["code"] for r in result["reasons"]]


def by_code(result, code):
    return [r for r in result["reasons"] if r["code"] == code]


KETTLE = ["ELECTRIC KETTLE", "Product name: Electric Kettle", "MRP ₹899.00 (Inclusive of all taxes)",
          "Net Quantity: 1 N", "Mfg. Date: 02/2026", "Manufactured by: Thermopot Appliances Pvt Ltd",
          "Address: Plot 12, Baddi Industrial Area, Solan 173205, Himachal Pradesh",
          "Consumer care: 1800-300-7788", "Email: care@thermopot.example"]


def resolved(data: dict, bis="PASS", lm="PASS", keep_unsupported=False) -> dict:
    """A copy of a real analysis whose BIS and Legal Metrology results are set to a resolved state.
    MetrIQ's verified data has no standard whose every requirement is checkable, so a fully
    resolved inspection can only be shown by setting the results directly."""
    d = copy.deepcopy(data)
    d["compliance"].update(overall_status=bis, coverage_status="INSPECTION_SUPPORTED", reason_code="ALL_CHECKS_PASSED")
    d["package_label"]["overall_status"] = lm
    d["package_label"]["reason_code"] = "SUPPORTED_CHECK_FAILED" if lm == "FAIL" else "ALL_CHECKS_PASSED"
    if not keep_unsupported:
        d["package_label"]["checks"] = [c for c in d["package_label"]["checks"] if c["result"] != "NOT_SUPPORTED"]
    return d


# ------------------------------------------------------------------ tests


def test_resolve_or_escalate() -> None:
    print("\ncan the system resolve the case?")
    _, kettle = analyse((931, "FRONT", raw(*KETTLE)))
    result = assess(kettle)
    check("real kettle label -> escalated (BIS standard-only, Legal Metrology areas not checkable)",
          result["required"] and result["system_result"] == "REVIEW"
          and {"REQUIREMENT_NOT_CHECKABLE", "SYSTEM_RESULT_REVIEW"} <= set(codes(result)), str(codes(result)))
    check("every reason has a code, label, known source and message",
          all(r["code"] in REASONS and r["label"] == REASONS[r["code"]] and r["source"] in SOURCES and r["message"]
              for r in result["reasons"]))

    ok = assess(resolved(kettle))
    check("PASS with every applicable requirement checked -> not escalated, no reasons",
          ok == {"required": False, "system_result": "PASS", "reasons": []}, str(ok))
    unsupported = assess(resolved(kettle, keep_unsupported=True))
    check("PASS with requirement areas that cannot be checked -> escalated (they could overturn a PASS)",
          unsupported["required"] and codes(unsupported) == ["REQUIREMENT_NOT_CHECKABLE"])

    _, dozen = analyse((932, "FRONT", raw(*KETTLE[:3], "Net Quantity: 1 dozen", *KETTLE[4:])))
    fail = assess(resolved(dozen, bis="PASS", lm="FAIL", keep_unsupported=True))
    check("FAIL on clear evidence with only uncheckable areas left -> resolved, the reason is still listed",
          not fail["required"] and fail["system_result"] == "FAIL" and codes(fail) == ["REQUIREMENT_NOT_CHECKABLE"],
          str(fail))
    fail_bis_review = assess(resolved(dozen, bis="REVIEW", lm="FAIL", keep_unsupported=True))
    check("FAIL while BIS is still REVIEW -> escalated", fail_bis_review["required"]
          and "SYSTEM_RESULT_REVIEW" in codes(fail_bis_review))

    before = copy.deepcopy(kettle)
    check("deterministic: the same analysis always gives the same assessment", assess(kettle) == assess(kettle))
    check("assessment never changes the analysis or its results", kettle == before)


def test_reasons() -> None:
    print("\nescalation reasons")
    _, d = analyse((941, "FRONT", raw("SUNSHINE", "Best quality since 1990")))
    r = assess(d)
    check("1 product cannot be identified -> PRODUCT_NOT_IDENTIFIED", by_code(r, "PRODUCT_NOT_IDENTIFIED")
          and by_code(r, "PRODUCT_NOT_IDENTIFIED")[0]["source"] == "PRODUCT")
    check("2 no verified BIS standard -> NO_VERIFIED_STANDARD", bool(by_code(r, "NO_VERIFIED_STANDARD")))
    check("5 required evidence missing -> MISSING_EVIDENCE names the checks",
          by_code(r, "MISSING_EVIDENCE") and "lm-retail-sale-price-declared" in by_code(r, "MISSING_EVIDENCE")[0]["checks"])

    _, d = analyse((942, "FRONT", raw("COMBO PACK", "Product name: Electric Kettle", "Packaged Drinking Water")))
    r = assess(d)
    check("7 several plausible products / standards -> MULTIPLE_CANDIDATES lists them",
          by_code(r, "MULTIPLE_CANDIDATES") and "IS 14543:2016" in by_code(r, "MULTIPLE_CANDIDATES")[0]["message"]
          and "IS 367:1993" in by_code(r, "MULTIPLE_CANDIDATES")[0]["message"], str(codes(r)))

    _, d = analyse((943, "FRONT", raw("AQUA", "IS 14543")))
    check("a single weakly supported candidate -> PRODUCT_NOT_CONFIRMED", bool(by_code(assess(d), "PRODUCT_NOT_CONFIRMED")))

    _, d = analyse((944, "FRONT", raw(*KETTLE[:2], "MRP ₹899.00 (Inclusive of all taxes)", conf=0.7)))
    r = assess(d)
    check("3 OCR too uncertain -> OCR_UNCERTAIN with the checks and their OCR regions",
          by_code(r, "OCR_UNCERTAIN") and "lm-retail-sale-price-declared" in by_code(r, "OCR_UNCERTAIN")[0]["checks"]
          and by_code(r, "OCR_UNCERTAIN")[0]["source_regions"], str(codes(r)))

    _, d = analyse((945, "FRONT", raw("ELECTRIC KETTLE", "MRP ₹899.00 (Inclusive of all taxes)")),
                   (946, "BACK", raw("MRP ₹999.00 (Inclusive of all taxes)")),
                   (947, "LEFT", RuntimeError("camera file unreadable")))
    r = assess(d)
    conflict = by_code(r, "CONFLICTING_DECLARATIONS")
    check("4/9 conflicting declarations across sides -> CONFLICTING_DECLARATIONS with sides and both regions",
          conflict and "FRONT" in conflict[0]["message"] and "BACK" in conflict[0]["message"]
          and {"I1-OCR-002", "I2-OCR-001"} <= set(conflict[0]["source_regions"]), str(conflict))
    check("a photo that could not be read -> IMAGES_UNREADABLE", by_code(r, "IMAGES_UNREADABLE")
          and "LEFT" in by_code(r, "IMAGES_UNREADABLE")[0]["message"])

    _, d = analyse((948, "FRONT", raw(*KETTLE)), textured=False)
    check("a low-quality photo -> IMAGE_QUALITY_LOW", bool(by_code(assess(d), "IMAGE_QUALITY_LOW")))

    _, d = analyse((949, "FRONT", raw(*KETTLE)))
    r = assess(d)
    check("6 unsupported requirement areas -> REQUIREMENT_NOT_CHECKABLE for BIS and Legal Metrology",
          {x["source"] for x in by_code(r, "REQUIREMENT_NOT_CHECKABLE")} == {"BIS", "LEGAL_METROLOGY"})
    check("8 compliance result REVIEW -> SYSTEM_RESULT_REVIEW per evidence system",
          {x["source"] for x in by_code(r, "SYSTEM_RESULT_REVIEW")} == {"BIS", "LEGAL_METROLOGY"})

    _, d = analyse((950, "FRONT", raw("GOLD RING", "22K916 HUID: AB12CD", "Hallmarked jewellery")))
    hallmark = by_code(assess(d), "HALLMARK_NOT_VERIFIABLE")
    check("10 hallmark / HUID text -> HALLMARK_NOT_VERIFIABLE with its OCR regions, never verified",
          hallmark and {"OCR-002", "OCR-003"} <= set(hallmark[0]["source_regions"])
          and "authenticity cannot be established" in hallmark[0]["message"], str(hallmark))
    crafted = copy.deepcopy(d)
    crafted["ocr"]["text"], crafted["ocr"]["regions"] = "", []
    crafted["hallmark"]["detected"], crafted["hallmark"]["untrusted_claims"] = False, []
    crafted["compliance"]["reason_code"] = "DOMAIN_NOT_PACKAGE_LABEL"
    check("10 a jewellery hallmarking standard in package inspection -> HALLMARK_NOT_VERIFIABLE",
          bool(by_code(assess(crafted), "HALLMARK_NOT_VERIFIABLE")))

    _, d = analyse((951, "FRONT", raw("CEMENT", "Net Quantity: 30 kg")))
    scope = by_code(assess(d), "PACKAGE_SCOPE_EXCLUSION")
    check("11 Legal Metrology scope exclusion evidenced -> PACKAGE_SCOPE_EXCLUSION with its region",
          scope and scope[0]["source_regions"] == ["OCR-002"], str(scope))

    crafted = copy.deepcopy(d)
    crafted["package_label"]["reason_code"] = "ENGINE_ERROR"
    check("11 a failed pipeline stage -> PIPELINE_ERROR", bool(by_code(assess(crafted), "PIPELINE_ERROR")))

    order = list(REASONS)
    r = assess(d)
    check("reasons come in a fixed order", [order.index(c) for c in codes(r)] == sorted(order.index(c) for c in codes(r)))


def test_analyze_contract() -> None:
    print("\n/inspection/analyze")
    client = TestClient(app)
    path = SAMPLES / "synth_electric-kettle.png"
    with path.open("rb") as fh:
        body = client.post("/inspection/analyze", files={"image": (path.name, fh, "image/png")}).json()
    esc = body.get("escalation") or {}
    check("the analysis response carries the escalation assessment",
          esc.get("required") is True and esc.get("system_result") == "REVIEW" and esc.get("reasons"), str(esc)[:200])
    body_copy = copy.deepcopy(body)
    body_copy.pop("escalation")
    check("the response's escalation equals a fresh assessment of the same analysis",
          assess(body_copy) == esc)
    check("escalation does not change the system results",
          body["compliance"]["overall_status"] == "REVIEW" and body["package_label"]["overall_status"] == "REVIEW")


def main() -> int:
    test_resolve_or_escalate()
    test_reasons()
    test_analyze_contract()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
