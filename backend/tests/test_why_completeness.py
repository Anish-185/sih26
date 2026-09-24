"""Checks for declaration completeness (app/completeness.py): what a verified
requirement links a field to, and what MetrIQ observed from OCR evidence.

MetrIQ produces no automatic PASS / FAIL / REVIEW compliance verdict — this
file used to also cover the removed deterministic rule engine's "why did this
pass / fail / need review?" explanations (``app.compliance``); that coverage
is gone with the engine. What remains is genuinely evidence-only.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_why_completeness.py

Exit 0 = all checks passed, 1 = something failed.

Controlled OCR stand-ins + the real knowledge base and requirement data.
No OCR model, network, LM Studio / OpenRouter.
"""

from __future__ import annotations

import io
import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.inspection import InspectionAnalyzer, PackageUpload  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import OcrError, RawRegion  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.requirements import load_requirements  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0
FINDER = ProductStandardFinder(SearchEngine())
ITEMS = FINDER.search_engine.items
KB = {i.id: i for i in ITEMS}
REAL = load_requirements(ITEMS)
FORBIDDEN = re.compile(r"legally missing|\b(?:is|are) missing|\b(?:is|are) absent|probably", re.IGNORECASE)  # affirmative claims only


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def png(width: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, 400), "white").save(buf, format="PNG")
    return buf.getvalue()


def lines(*texts, conf: float = 0.95, big_first: bool = True):
    out, y = [], 20
    for i, t in enumerate(texts):
        c = conf[i] if isinstance(conf, (list, tuple)) else conf
        h = 50 if (i == 0 and big_first) else 25
        out.append(RawRegion(t, c, (10, y, 10 + 10 * len(t), y + h), [[10, y], [10 + 10 * len(t), y], [10 + 10 * len(t), y + h], [10, y + h]]))
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


def package(by_width: dict, sides: list[tuple[int, str]]):
    analyzer = InspectionAnalyzer(ocr_engine=Engine(by_width), product_finder=FINDER)
    return analyzer.analyze_package([PackageUpload(png(w), f"{s}.png", s) for w, s in sides])


F, B, L, R = 601, 602, 603, 604
WATER = ["AQUA PURE", "PACKAGED DRINKING WATER", "NET QUANTITY: 1 L"]
# -------------------------------------------------------- 7-16. COMPLETENESS

def test_completeness() -> None:
    res = package({
        F: lines("ROASTED MASALA CHANA", "Brand: SUNRISE", "MRP ₹20"),
        B: lines("(Roasted Bengal gram with spices)", "Packed by: SUNRISE FOODS PVT LTD", "Net Quantity: 200 g",
                 "MRP ₹25", "Mfg Date: 03/2026", big_first=False),
    }, [(F, "FRONT"), (B, "BACK")])
    items = {i.field: i for i in res.completeness.items}

    brand = items["brand"]
    check("7 detected field", brand.status == "DETECTED" and brand.value == "SUNRISE")
    check("12 multi-side: brand sourced from FRONT", brand.source_sides == ["FRONT"] and "FRONT" in brand.statement)
    packer, nq = items["packer"], items["net_quantity"]
    check("12 multi-side: packer and net quantity sourced from BACK",
          packer.source_sides == ["BACK"] and nq.source_sides == ["BACK"] and nq.value == "200 g")
    check("11 field evidence preserved: regions, images, text, confidence",
          nq.source_regions == ["I2-OCR-003"] and nq.source_images == [res.images[1].image_id]
          and nq.raw_text == "Net Quantity: 200 g" and nq.ocr_confidence == 0.95)

    bb = items["best_before"]
    check("8 not detected field", bb.status == "NOT_DETECTED" and bb.value is None and bb.source_regions == [])
    check("8 not detected says 'not detected in the uploaded images', never missing",
          bb.statement == "Not detected in the OCR text of the uploaded images." and not FORBIDDEN.search(bb.statement), bb.statement)

    mrp = items["mrp"]
    check("13 conflicting values -> UNCERTAIN + conflict, no value chosen",
          mrp.status == "UNCERTAIN" and mrp.conflict and mrp.value is None)
    check("13 conflict statement lists both readings with their sides",
          "₹20 on FRONT" in mrp.statement and "₹25 on BACK" in mrp.statement, mrp.statement)

    unc = package({F: lines("PACKAGED DRINKING WATER", "Batch No"), B: lines("MRP ₹20", big_first=False)},
                  [(F, "FRONT"), (B, "BACK")])
    batch = next(i for i in unc.completeness.items if i.field == "batch_number")
    check("9 uncertain field (label with no readable value)", batch.status == "UNCERTAIN" and not batch.conflict
          and batch.statement.startswith("Uncertain:"), batch.statement)

    # Milestone 8: Legal Metrology package-label requirements also link fields
    # (tested in test_legal_metrology.py). Here only BIS links are asserted.
    bis_ids = {r.id for r in REAL.requirements if r.scope == "STANDARD"}
    check("10 no verified BIS requirement for chana fields -> no BIS-linked field",
          not any(set(i.requirement_ids) & bis_ids for i in res.completeness.items))
    water = package({F: lines(*WATER), B: lines("IS 14543", big_first=False)}, [(F, "FRONT"), (B, "BACK")])
    cov = {i.field: i.requirement_coverage for i in water.completeness.items}
    check("10/16 only the field used by a verified BIS requirement is BIS-linked",
          [i.field for i in water.completeness.items if set(i.requirement_ids) & bis_ids] == ["standard_number"],
          str(cov))
    check("16 VERIFIED_REQUIREMENT names the real requirement id",
          next(i for i in water.completeness.items if i.field == "standard_number").requirement_ids
          == ["packaged-water-label-shows-is-number"])
    grounded = {name for r in REAL.requirements if r.supported for name in r.fields}
    check("16 no field is claimed as required without a verified requirement",
          {i.field for i in water.completeness.items if i.requirement_coverage == "VERIFIED_REQUIREMENT"} <= grounded)
    for i in res.completeness.items + water.completeness.items:
        if FORBIDDEN.search(i.statement):
            check(f"16 {i.field} statement never claims absence", False, i.statement)
    check("16 completeness note says not detected is not a finding", "not a finding about the package" in res.completeness.note)

    decl_fields = [(f.field, f.status, f.value) for f in res.declaration_stage.fields]
    check("15 completeness invents no declaration: same fields, statuses and values",
          [(i.field, i.status, i.value) for i in res.completeness.items] == decl_fields)
    check("7/8/9 counts add up", res.completeness.detected + res.completeness.uncertain + res.completeness.not_detected
          == len(res.completeness.items) and res.completeness.conflicts == 1)

    failed = package({F: lines(*WATER), B: OcrError("engine crashed")}, [(F, "FRONT"), (B, "BACK")])
    std = next(i for i in failed.completeness.items if i.field == "standard_number")
    check("14 OCR failure on BACK -> completeness says the failed photo cannot be determined, not 'missing'",
          std.status == "NOT_DETECTED" and "BACK (image 2)" in std.statement and "cannot be determined" in std.statement, std.statement)
    check("14 nothing says missing / absent", not FORBIDDEN.search(std.statement))
    check("14 the analysis notes the unreadable photo",
          any("BACK (image 2)" in n or "no usable OCR evidence" in n for n in failed.notes), str(failed.notes))


# -------------------------------------------------------------- 17-25. REGRESSION

def test_regression() -> None:
    engine = Engine({F: lines(*WATER), B: lines("IS 14543", big_first=False)})
    analyzer = InspectionAnalyzer(ocr_engine=engine, product_finder=FINDER)
    instant = analyzer.ocr_package([PackageUpload(png(F), side="FRONT"), PackageUpload(png(B), side="BACK")])
    check("20 Instant OCR still works (per image, no compliance)",
          [i.ocr.region_count for i in instant.images] == [3, 1] and not hasattr(instant, "completeness"))
    check("21 declaration extraction still works",
          next(f for f in instant.declaration_stage.fields if f.field == "net_quantity").value == "1 L")
    full = analyzer.analyze_package([PackageUpload(png(F), side="FRONT"), PackageUpload(png(B), side="BACK")])
    check("22 product identification still works", full.product.standard_number == "IS 14543:2016")
    check("24 modelled-product confirmation still works",
          full.product.product_applicability == "PRODUCT_CONFIRMED" and "compliance" not in type(full.pipeline).model_fields)
    check("25 multi-side still works", full.package.sides_uploaded == ["FRONT", "BACK"] and len(full.images) == 2)
    single = analyzer.analyze(png(F), "front.png")
    check("25 single image still works with completeness", single.ocr.regions[0].id == "OCR-001" and single.completeness.items)
    body = TestClient(app).post("/product-standard", json={"product": "packaged drinking water"}).json()
    # Phase 3 added `boundary` (null whenever there is an answer); the original
    # keys must all survive.
    check("23 Product -> Standard unchanged",
          {"product", "results", "grounded", "confidence", "note"} <= set(body)
          and body.get("boundary") is None
          and body["results"][0]["standard_number"] == "IS 14543:2016" and body["results"][0]["why"]["summary"])
    retrieval_why = full.standards[0].why
    check("retrieval 'why this result' is a real explanation of the candidate standard",
          retrieval_why.summary.startswith("Retrieved as a candidate standard"))


def main() -> int:
    print("declaration completeness")
    for fn in (test_completeness, test_regression):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
