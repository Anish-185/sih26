"""Checks for Milestone 10 — resolution: could MetrIQ establish this inspection's
evidence chain from the photos?

MetrIQ produces no automatic PASS / FAIL / REVIEW compliance verdict.
``app.escalation.assess()`` reports, deterministically, every reason the
product / standard / declaration evidence chain could not be fully established
— OCR quality, product identification, declaration completeness against
verified requirement data, and hallmark evidence. Covers every reason on real
pipeline output (controlled OCR text, real declaration extraction, product
identification, declaration completeness), determinism, and the
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
SOURCES = {"OCR", "PRODUCT", "HALLMARKING", "PIPELINE"}


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

WATER = ["AQUA PURE", "PACKAGED DRINKING WATER", "NET QUANTITY: 1 L"]


# ------------------------------------------------------------------ tests


def test_resolve_or_establish() -> None:
    print("\ncould MetrIQ establish the evidence chain?")
    # IS 367:1993 (kettle) has no modelled requirement product in MetrIQ's verified
    # data, so there is no verified-requirement gap to report: nothing is outstanding.
    _, kettle = analyse((931, "FRONT", raw(*KETTLE)))
    result = assess(kettle)
    check("real kettle label -> nothing outstanding (its standard has no modelled requirement data)",
          result == {"required": False, "reasons": []}, str(result))

    # IS 14543:2016 (packaged water) DOES have a modelled product and a verified,
    # checkable requirement (the printed IS number) — not printing it is a real gap.
    _, water_no_number = analyse((934, "FRONT", raw(*WATER)))
    r = assess(water_no_number)
    check("water without its printed IS number -> escalated, MISSING_EVIDENCE",
          r["required"] and codes(r) == ["MISSING_EVIDENCE"], str(r))
    check("every reason has a code, label, known source and message",
          all(x["code"] in REASONS and x["label"] == REASONS[x["code"]] and x["source"] in SOURCES and x["message"]
              for x in r["reasons"]))

    _, water_with_number = analyse((935, "FRONT", raw(*WATER, "IS 14543")))
    check("water WITH its printed IS number -> nothing outstanding",
          assess(water_with_number) == {"required": False, "reasons": []})

    before = copy.deepcopy(water_no_number)
    check("deterministic: the same analysis always gives the same assessment",
          assess(water_no_number) == assess(water_no_number))
    check("assessment never changes the analysis it read", water_no_number == before)


def test_reasons() -> None:
    print("\nescalation reasons")
    _, d = analyse((941, "FRONT", raw("SUNSHINE", "Best quality since 1990")))
    r = assess(d)
    check("1 product cannot be identified -> PRODUCT_NOT_IDENTIFIED", by_code(r, "PRODUCT_NOT_IDENTIFIED")
          and by_code(r, "PRODUCT_NOT_IDENTIFIED")[0]["source"] == "PRODUCT")
    check("2 no verified BIS standard -> NO_VERIFIED_STANDARD", bool(by_code(r, "NO_VERIFIED_STANDARD")))

    _, d = analyse((942, "FRONT", raw("COMBO PACK", "Product name: Electric Kettle", "Packaged Drinking Water")))
    r = assess(d)
    check("3 several plausible products / standards -> MULTIPLE_CANDIDATES lists them",
          by_code(r, "MULTIPLE_CANDIDATES") and "IS 14543:2016" in by_code(r, "MULTIPLE_CANDIDATES")[0]["message"]
          and "IS 367:1993" in by_code(r, "MULTIPLE_CANDIDATES")[0]["message"], str(codes(r)))

    _, d = analyse((943, "FRONT", raw("AQUA", "IS 14543")))
    check("4 a single weakly supported candidate -> PRODUCT_NOT_CONFIRMED", bool(by_code(assess(d), "PRODUCT_NOT_CONFIRMED")))

    _, d = analyse((944, "FRONT", raw(*WATER, "IS 14543", conf=0.5)))
    r = assess(d)
    check("5 OCR too uncertain on a verified-requirement field -> OCR_UNCERTAIN with its region",
          by_code(r, "OCR_UNCERTAIN") and by_code(r, "OCR_UNCERTAIN")[0]["source_regions"], str(codes(r)))

    _, d = analyse((945, "FRONT", raw("PACKAGED DRINKING WATER", "MRP ₹899.00 (Inclusive of all taxes)")),
                   (946, "BACK", raw("MRP ₹999.00 (Inclusive of all taxes)")),
                   (947, "LEFT", RuntimeError("camera file unreadable")))
    r = assess(d)
    conflict = by_code(r, "CONFLICTING_DECLARATIONS")
    check("6 conflicting declarations across sides -> CONFLICTING_DECLARATIONS with sides and both regions",
          conflict and "FRONT" in conflict[0]["message"] and "BACK" in conflict[0]["message"]
          and {"I1-OCR-002", "I2-OCR-001"} <= set(conflict[0]["source_regions"]), str(conflict))
    check("7 a photo that could not be read -> IMAGES_UNREADABLE", by_code(r, "IMAGES_UNREADABLE")
          and "LEFT" in by_code(r, "IMAGES_UNREADABLE")[0]["message"])

    _, d = analyse((948, "FRONT", raw(*WATER, "IS 14543")), textured=False)
    check("8 a low-quality photo -> IMAGE_QUALITY_LOW", bool(by_code(assess(d), "IMAGE_QUALITY_LOW")))

    _, d = analyse((950, "FRONT", raw("GOLD RING", "22K916 HUID: AB12CD", "Hallmarked jewellery")))
    hallmark = by_code(assess(d), "HALLMARK_NOT_VERIFIABLE")
    check("9 hallmark / HUID text -> HALLMARK_NOT_VERIFIABLE with its OCR regions, never verified",
          hallmark and {"OCR-002", "OCR-003"} <= set(hallmark[0]["source_regions"])
          and "authenticity cannot be established" in hallmark[0]["message"], str(hallmark))

    order = list(REASONS)
    r = assess(d)
    check("reasons come in a fixed order", [order.index(c) for c in codes(r)] == sorted(order.index(c) for c in codes(r)))


def test_pipeline_error() -> None:
    print("\npipeline errors always escalate")

    class BrokenFinder:
        def __init__(self):
            self.search_engine = self

        @property
        def items(self):
            raise RuntimeError("knowledge base unavailable")

        def find(self, *a, **k):
            raise RuntimeError("knowledge base unavailable")

    analyzer = InspectionAnalyzer(ocr_engine=Engine({960: raw("CEMENT", "Net Quantity: 30 kg")}),
                                  product_finder=BrokenFinder())
    out = analyzer.analyze_package([PackageUpload(photo(960), "f.png", "FRONT")])
    d = out.model_dump(mode="json")
    r = assess(d)
    check("a broken knowledge base still degrades to REVIEW and escalates",
          r["required"] and "PRODUCT_NOT_IDENTIFIED" in codes(r), str(r))

    # A raised exception in escalation itself is handled by the caller (app.inspection),
    # not by assess() — asserted in test_inspection_records.py / analyze_package directly.
    crafted = copy.deepcopy(d)
    crafted["notes"] = ["Downstream pipeline error: simulated failure"]
    check("a note recording a pipeline failure -> PIPELINE_ERROR",
          bool(by_code(assess(crafted), "PIPELINE_ERROR")))


def test_analyze_contract() -> None:
    print("\n/inspection/analyze")
    client = TestClient(app)
    path = SAMPLES / "synth_electric-kettle.png"
    with path.open("rb") as fh:
        body = client.post("/inspection/analyze", files={"image": (path.name, fh, "image/png")}).json()
    esc = body.get("escalation") or {}
    check("the analysis response carries the escalation assessment",
          "required" in esc and "reasons" in esc, str(esc)[:200])
    body_copy = copy.deepcopy(body)
    body_copy.pop("escalation")
    check("the response's escalation equals a fresh assessment of the same analysis",
          assess(body_copy) == esc)
    check("the response carries no compliance verdict",
          "compliance" not in body and "package_label" not in body, str(list(body)))


def main() -> int:
    test_resolve_or_establish()
    test_reasons()
    test_pipeline_error()
    test_analyze_contract()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
