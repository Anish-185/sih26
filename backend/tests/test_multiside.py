"""Checks for multi-side package inspection (one package, several photos).

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_multiside.py

Exit 0 = all checks passed, 1 = something failed.

A stand-in OCR engine returns controlled text per image (keyed by image width),
so every multi-side scenario is exact. The real knowledge base is used for
product / standard / compliance. No network, no LM Studio / OpenRouter.
"""

from __future__ import annotations

import io
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.inspection import ImageError, InspectionAnalyzer, PackageUpload  # noqa: E402
from app.inspection_api import get_ocr_analyzer  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import OcrError, RawRegion  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0
FINDER = ProductStandardFinder(SearchEngine())


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def png(width: int, color: str = "white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, 400), color).save(buf, format="PNG")
    return buf.getvalue()


def lines(*texts, conf: float = 0.95, start_y: int = 20, big_first: bool = True):
    out = []
    y = start_y
    for i, t in enumerate(texts):
        h = 50 if (i == 0 and big_first) else 25
        out.append(RawRegion(t, conf, (10, y, 10 + 10 * len(t), y + h), [[10, y], [10 + 10 * len(t), y], [10 + 10 * len(t), y + h], [10, y + h]]))
        y += h + 15
    return out


class PerImageEngine:
    """OCR stand-in: regions chosen by image width; a width mapped to an
    exception raises it."""

    def __init__(self, by_width: dict):
        self.by_width = by_width
        self.calls = 0

    def __call__(self, arr):
        self.calls += 1
        result = self.by_width[arr.shape[1]]
        if isinstance(result, Exception):
            raise result
        return list(result), 0.01


def analyzer(by_width: dict) -> InspectionAnalyzer:
    return InspectionAnalyzer(ocr_engine=PerImageEngine(by_width), product_finder=FINDER)


def field(result, name):
    return next(f for f in result.declaration_stage.fields if f.field == name)


FRONT_W, BACK_W, LEFT_W, RIGHT_W = 601, 602, 603, 604


# ---------------------------------------------------------------- 1-5. images

def test_images_and_provenance() -> None:
    one = analyzer({FRONT_W: lines("PACKAGED DRINKING WATER", "MRP ₹20")}).analyze(png(FRONT_W), "a.png")
    check("1 one image still works", one.product.status == "MATCHED" and len(one.images) == 1)
    check("1 single image keeps plain region ids", [r.id for r in one.ocr.regions] == ["OCR-001", "OCR-002"])
    check("1 single image side defaults to UNKNOWN", one.images[0].side == "UNKNOWN" and one.ocr.regions[0].side == "UNKNOWN")

    two = analyzer({FRONT_W: lines("PACKAGED DRINKING WATER"), BACK_W: lines("MRP ₹20", "Batch No: AP26001")}).ocr_package([
        PackageUpload(png(FRONT_W), "front.png", "FRONT"), PackageUpload(png(BACK_W), "back.png", "back"),
    ])
    check("2 two images -> two image records", [(i.index, i.side) for i in two.images] == [(1, "FRONT"), (2, "BACK")])
    check("2 region ids are unique and carry the image number",
          [r.id for r in two.ocr.regions] == ["I1-OCR-001", "I2-OCR-001", "I2-OCR-002"], str([r.id for r in two.ocr.regions]))
    check("4 side metadata is normalised ('back' -> BACK)", two.images[1].side == "BACK")

    engine = {FRONT_W: lines("A LINE"), BACK_W: lines("B LINE"), LEFT_W: lines("C LINE"), RIGHT_W: lines("D LINE")}
    four = analyzer(engine).ocr_package([
        PackageUpload(png(w), f"{s}.png", s) for w, s in zip((FRONT_W, BACK_W, LEFT_W, RIGHT_W), ("FRONT", "BACK", "LEFT", "RIGHT"))
    ])
    check("3 multiple images all OCR'd", four.package.usable_images == 4 and four.ocr.region_count == 4)
    check("4 not-uploaded sides are listed separately", four.package.sides_not_uploaded == ["TOP", "BOTTOM"])
    for img in four.images:
        check(f"5 {img.side} regions carry that image's id and side",
              all(r.image_id == img.image_id and r.side == img.side for r in img.ocr.regions))
    check("5 image ids are distinct", len({i.image_id for i in four.images}) == 4)

    try:
        analyzer({}).ocr_package([PackageUpload(png(FRONT_W), side="SIDEWAYS")])
        check("4 unknown side rejected", False)
    except ImageError as exc:
        check("4 unknown side rejected", "SIDEWAYS" in str(exc))
    try:
        analyzer({FRONT_W: []}).ocr_package([PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(FRONT_W), side="BACK")])
        check("duplicate identical photo rejected", False)
    except ImageError as exc:
        check("duplicate identical photo rejected", "more than once" in str(exc))


# ------------------------------------------------------- 6-9. declarations across sides

def test_declarations_across_sides() -> None:
    a = analyzer({
        FRONT_W: lines("ROASTED MASALA CHANA", "Brand: SUNRISE", "MRP ₹45"),
        BACK_W: lines("Net Quantity: 200 g", "Brand: SUNRISE", "MRP Rs. 45.00", "Batch No: SR2026-0342"),
    })
    res = a.ocr_package([PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK")])
    front_id, back_id = res.images[0].image_id, res.images[1].image_id

    name = field(res, "product_name")
    check("6 declaration from the front keeps FRONT provenance",
          name.value == "Roasted Masala Chana" and name.source_sides == ["FRONT"] and name.source_images == [front_id])
    nq = field(res, "net_quantity")
    check("7 declaration from the back keeps BACK provenance",
          nq.value == "200 g" and nq.source_sides == ["BACK"] and nq.source_regions == ["I2-OCR-001"])

    brand = field(res, "brand")
    check("8 same brand on two sides -> one value, DUPLICATE", brand.value == "SUNRISE" and brand.consistency == "DUPLICATE")
    check("8 duplicate keeps both sources", brand.source_sides == ["FRONT", "BACK"] and len(brand.observations) == 2)
    mrp = field(res, "mrp")
    check("8 ₹45 and Rs. 45.00 are the same MRP -> DUPLICATE, DETECTED",
          mrp.status == "DETECTED" and mrp.consistency == "DUPLICATE" and mrp.source_sides == ["FRONT", "BACK"], f"{mrp.status} {mrp.consistency}")

    c = analyzer({FRONT_W: lines("PACKAGED DRINKING WATER", "MRP ₹20"), BACK_W: lines("MRP ₹25", "Batch: AP26001")})
    res = c.ocr_package([PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK")])
    mrp = field(res, "mrp")
    check("9 different MRPs on two sides -> UNCERTAIN CONFLICT", mrp.status == "UNCERTAIN" and mrp.consistency == "CONFLICT")
    check("9 conflict withholds a value (nothing chosen silently)", mrp.value is None)
    check("9 conflict lists both readings with their sides",
          [(o.value, o.source_sides) for o in mrp.observations] == [("₹20", ["FRONT"]), ("₹25", ["BACK"])],
          str([(o.value, o.source_sides) for o in mrp.observations]))
    check("9 conflict reason names FRONT and BACK", "FRONT" in mrp.reason and "BACK" in mrp.reason, mrp.reason)

    split = analyzer({
        FRONT_W: [RawRegion("MRP", 0.95, (10, 300, 60, 330), [[10, 300], [60, 300], [60, 330], [10, 330]])],
        BACK_W: [RawRegion("₹20", 0.95, (70, 302, 120, 330), [[70, 302], [120, 302], [120, 330], [70, 330]])],
    }).ocr_package([PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK")])
    m = field(split, "mrp")
    check("a label on one photo is never joined to a value on another photo",
          not (m.status == "DETECTED" and m.value == "₹20"), f"{m.status} {m.value} {m.source_regions}")


# ------------------------------------------------------ 10-12. missing / failed / empty

def test_partial_and_failed_sides() -> None:
    res = analyzer({FRONT_W: lines("PACKAGED DRINKING WATER"), BACK_W: lines("MRP ₹20")}).analyze_package([
        PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK"),
    ])
    nq = field(res, "net_quantity")
    check("10 field on no uploaded side -> NOT_DETECTED, no sources", nq.status == "NOT_DETECTED" and nq.source_regions == [])
    check("10 missing sides are 'not uploaded', not failures",
          res.package.sides_not_uploaded == ["LEFT", "RIGHT", "TOP", "BOTTOM"] and res.package.images_failed == [])

    engine = {FRONT_W: lines("PACKAGED DRINKING WATER"), BACK_W: lines("IS 14543"), LEFT_W: OcrError("engine crashed"),
              RIGHT_W: []}
    res = analyzer(engine).analyze_package([
        PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK"),
        PackageUpload(png(LEFT_W), side="LEFT"), PackageUpload(png(RIGHT_W), side="RIGHT"),
        PackageUpload(b"not an image at all", "evil.png", "TOP"),
    ])
    status = {i.side: i.status for i in res.images}
    check("11 OCR failure on one side does not fail the inspection",
          status == {"FRONT": "COMPLETED", "BACK": "COMPLETED", "LEFT": "FAILED", "RIGHT": "NO_TEXT", "TOP": "FAILED"}, str(status))
    left = next(i for i in res.images if i.side == "LEFT")
    check("11 failed side keeps its error and has no OCR", "engine crashed" in (left.error or "") and left.ocr is None)
    check("11 unreadable upload is FAILED with a readable error",
          "Could not read this file as an image" in (next(i for i in res.images if i.side == "TOP").error or ""))
    check("12 no text on one side -> NO_TEXT (different from FAILED)", res.package.images_no_text == ["RIGHT (image 4)"])
    check("11 failed sides listed", res.package.images_failed == ["LEFT (image 3)", "TOP (image 5)"])
    check("11 remaining evidence still processed", res.product.status == "MATCHED")
    check("11 the analysis notes that some images gave no usable evidence",
          any("no usable OCR evidence" in n and "LEFT (image 3)" in n for n in res.notes), str(res.notes))
    check("11 notes never claim absence", all("absent" not in n or "not" in n for n in res.notes))

    faint = analyzer({FRONT_W: lines("PACKAGED DRINKING WATER"), BACK_W: lines("~ ~", conf=0.2)}).ocr_package([
        PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK")])
    check("12 only low-confidence fragments -> NO_RELIABLE_TEXT", faint.images[1].status == "NO_RELIABLE_TEXT")

    try:
        analyzer({FRONT_W: OcrError("down"), BACK_W: OcrError("down")}).ocr_package([
            PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK")])
        check("every side failing raises", False)
    except OcrError:
        check("every side failing raises", True)


# --------------------------------------------- 13-17. product, standard, evidence

def test_combined_pipeline() -> None:
    front_only = analyzer({FRONT_W: lines("ROASTED MASALA CHANA", "MRP ₹45")}).analyze_package([
        PackageUpload(png(FRONT_W), side="FRONT")])
    check("13 front alone (keyword alias only) -> product REVIEW", front_only.product.status == "REVIEW", front_only.product.reason)

    both = analyzer({
        FRONT_W: lines("ROASTED MASALA CHANA", "MRP ₹45"),
        BACK_W: lines("NUTRITION NOTES", "(Roasted Bengal gram with spices)", "Net Quantity: 200 g", big_first=False),
    }).analyze_package([PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK")])
    check("13 front + back together -> product MATCHED", both.product.status == "MATCHED", both.product.reason)
    check("14 combined evidence -> verified IS 18140:2023", both.product.standard_number == "IS 18140:2023")
    sides = {i.image_id: i.side for i in both.images}
    ev_sides = sorted({sides[e.clue.image_id] for e in both.product.evidence if e.clue.image_id})
    check("14 product evidence comes from both sides", ev_sides == ["BACK", "FRONT"], str(ev_sides))
    check("14 standard candidate keeps evidence from both sides",
          {sides[e.clue.image_id] for e in both.standards[0].evidence if e.clue.image_id} == {"FRONT", "BACK"})

    water = analyzer({FRONT_W: lines("AQUA PURE", "PACKAGED DRINKING WATER"), BACK_W: lines("NET QUANTITY: 1 L", "IS 14543", big_first=False)})
    res = water.analyze_package([PackageUpload(png(FRONT_W), side="FRONT"), PackageUpload(png(BACK_W), side="BACK")])
    decl = next(d for d in res.declaration_stage.fields if d.field == "standard_number")
    back_id = res.images[1].image_id
    check("15 the IS-number declaration uses evidence from the back while the product came from the front",
          res.product.status == "MATCHED" and decl.status == "DETECTED" and decl.value == "IS 14543",
          f"{res.product.status} {decl.status} {decl.value}")
    check("16 declaration evidence preserves the back image id", decl.image_id == back_id and decl.source_images == [back_id])
    check("16 declaration evidence preserves the side", decl.source_sides == ["BACK"])
    check("17 declaration evidence preserves the OCR region", decl.source_regions == ["I2-OCR-002"])
    region = next(r for r in res.ocr.regions if r.id == "I2-OCR-002")
    check("17 that region exists on that image with that text", region.image_id == back_id and region.text == "IS 14543")
    check("MetrIQ still identifies the standard from the combined evidence, no verdict is produced",
          res.product.standard_number == "IS 14543:2016"
          and not hasattr(res, "compliance") and not hasattr(res, "package_label"))


# ------------------------------------------------------- 18. no fabrication

def test_no_fabrication() -> None:
    res = analyzer({
        FRONT_W: lines("PACKAGED DRINKING WATER", "MRP ₹20", "Brand: AQUA PURE"),
        BACK_W: lines("MRP ₹25", "Batch No: AP26001", "Mfg: 09/2026"),
        LEFT_W: OcrError("x"),
    }).analyze_package([PackageUpload(png(w), side=s) for w, s in ((FRONT_W, "FRONT"), (BACK_W, "BACK"), (LEFT_W, "LEFT"))])
    text_of = {r.id: r.text for r in res.ocr.regions}
    for f in res.declaration_stage.fields:
        if f.status == "NOT_DETECTED":
            check(f"18 {f.field} not detected -> no value, no sources", f.value is None and not f.source_regions and not f.source_sides)
            continue
        check(f"18 {f.field} sources are real regions", all(rid in text_of for rid in f.source_regions))
        if f.value:
            tokens = [t for t in f.value.lower().replace("₹", " ").split() if t.isalnum()]
            src = " ".join(text_of[rid] for rid in f.source_regions).lower()
            check(f"18 {f.field} value appears in its source text", all(t in src for t in tokens), f"{f.value} / {src}")
    check("18 no region is attributed to the failed side", all(r.side != "LEFT" for r in res.ocr.regions))


# ------------------------------------------------ 19-20. compatibility over HTTP

def test_http_compatibility() -> None:
    client = TestClient(app)
    engine = PerImageEngine({FRONT_W: lines("PACKAGED DRINKING WATER", "MRP ₹20"), BACK_W: lines("IS 14543")})
    app.dependency_overrides[get_ocr_analyzer] = lambda: InspectionAnalyzer(ocr_engine=engine)
    try:
        single = client.post("/inspection/ocr", files={"image": ("f.png", png(FRONT_W), "image/png")})
        check("19/20 single 'image' field still works", single.status_code == 200, single.text[:200])
        body = single.json()
        check("19 single response keeps image / quality / ocr / declaration_stage",
              {"image", "quality", "ocr", "declaration_stage"} <= body.keys() and body["ocr"]["regions"][0]["id"] == "OCR-001")

        multi = client.post("/inspection/ocr", files=[
            ("images", ("front.png", png(FRONT_W), "image/png")),
            ("images", ("back.png", png(BACK_W), "image/png")),
        ], data={"sides": ["FRONT", "BACK"]})
        check("20 multi-image Instant OCR over HTTP", multi.status_code == 200, multi.text[:200])
        mb = multi.json()
        check("20 per-image OCR returned with sides",
              [(i["side"], i["ocr"]["region_count"]) for i in mb["images"]] == [("FRONT", 2), ("BACK", 1)])
        check("20 combined declarations see both sides",
              next(f for f in mb["declaration_stage"]["fields"] if f["field"] == "standard_number")["source_sides"] == ["BACK"])
        check("20 Instant OCR still has no product / compliance", "product" not in mb and "compliance" not in mb)

        both = client.post("/inspection/ocr", files=[
            ("image", ("f.png", png(FRONT_W), "image/png")), ("images", ("b.png", png(BACK_W), "image/png"))])
        check("'image' and 'images' together -> 422", both.status_code == 422)
        mismatch = client.post("/inspection/ocr", files=[("images", ("f.png", png(FRONT_W), "image/png"))],
                               data={"sides": ["FRONT", "BACK"]})
        check("sides count mismatch -> 422", mismatch.status_code == 422)
        too_many = client.post("/inspection/ocr", files=[("images", (f"{w}.png", png(700 + w), "image/png")) for w in range(9)])
        check("more than 8 images -> 422", too_many.status_code == 422)
        not_image = client.post("/inspection/ocr", files=[("images", ("x.txt", b"hello", "text/plain"))])
        check("non-image file type -> 415", not_image.status_code == 415)
        none = client.post("/inspection/ocr")
        check("no image at all -> 422", none.status_code == 422)
    finally:
        app.dependency_overrides.clear()


def main() -> int:
    print("multi-side package inspection")
    for fn in (
        test_images_and_provenance,
        test_declarations_across_sides,
        test_partial_and_failed_sides,
        test_combined_pipeline,
        test_no_fabrication,
        test_http_compatibility,
    ):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
