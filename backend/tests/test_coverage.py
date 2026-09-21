"""Checks for Milestone 7: knowledge + rule coverage foundation.

    PRODUCT -> STANDARD -> APPLICABLE REQUIREMENTS -> DETERMINISTIC RULES -> EVIDENCE

Covers product-specific applicability (app/requirements.py: ``confirm_product``,
``coverage``), conservative extraction of names (app/declarations.py), the
coverage matrix + GET /inspection/coverage, declaration completeness, and
regressions. MetrIQ produces no automatic PASS/FAIL/REVIEW compliance verdict —
these checks are about what MetrIQ can identify and connect to verified
requirement data, not about a legal determination.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_coverage.py

Exit 0 = all checks passed, 1 = something failed.

Controlled OCR fixtures + the real knowledge base and requirement data, plus the
real local OCR engine on the synthetic sample labels. No LM Studio / OpenRouter.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app.completeness import declaration_completeness  # noqa: E402
from app.declarations import extract_declarations  # noqa: E402
from app.inspection import InspectionAnalyzer, PackageUpload  # noqa: E402
from app.main import app  # noqa: E402
from app.pipeline import run_downstream  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.product_identification import identify_product  # noqa: E402
from app.requirements import confirm_product, coverage_by_standard, coverage_matrix, load_requirements  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0
FINDER = ProductStandardFinder(SearchEngine())
ITEMS = FINDER.search_engine.items
KB = {i.id: i for i in ITEMS}
REAL = load_requirements(ITEMS)
SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "ocr-labels"

WATER_LINK_QUOTE = "packaged drinking water (other than natural mineral water) as per IS 14543:2016"
FORBIDDEN = re.compile(r"legally missing|\b(?:is|are) missing|\b(?:is|are) absent", re.IGNORECASE)


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


@dataclass
class Region:
    id: str
    text: str
    confidence: float
    bbox: list
    image_id: str | None = "IMG-TEST"


def label(lines: list[str], conf: float = 0.95) -> list[Region]:
    """First line printed large, the rest at body size."""
    out = []
    for n, text in enumerate(lines, start=1):
        y = 10 + 50 * n
        h = 60 if n == 1 else 30
        out.append(Region(f"OCR-{n:03d}", text, conf, [10, y, 10 + 12 * len(text), y + h]))
    return out


def data_file(payload: dict):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "req.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return load_requirements(ITEMS, path)


def water_product(**over) -> dict:
    return {
        "id": "packaged-drinking-water", "name": "Packaged Drinking Water",
        "aliases": ["packaged drinking water"], "category": "Packaged water",
        "standards": [{"standard_number": "IS 14543:2016", "applicability_status": "VERIFIED",
                       "source_knowledge_id": "packaged-drinking-water-certification",
                       "source_quote": WATER_LINK_QUOTE}],
        **over,
    }


def is_number_rule(**over) -> dict:
    return {
        "id": "water-is-number", "applies_to": ["IS 14543:2016"],
        "description": "The package shows the IS number of its Indian Standard.",
        "rule_type": "printed_standard_number", "declaration_field": "standard_number",
        "parameters": {"min_ocr_confidence_pass": 0.8, "min_ocr_confidence_fail": 0.9},
        "source_knowledge_id": "packaged-water-must-carry-bis-mark",
        "source_quote": "A consumer should therefore expect to see the ISI Mark with the IS number "
                        "(IS 14543 or IS 13428) on the bottle.",
        **over,
    }


def identify(lines, requirements=REAL):
    regions = label(lines)
    stage = extract_declarations(regions)
    product = identify_product(stage, regions, FINDER)
    return product, stage, requirements


WATER = ["AQUA PURE", "PACKAGED DRINKING WATER", "NET QUANTITY: 1 L"]


def field(stage, name):
    return next(d for d in stage.fields if d.field == name)


# ------------------------------------------------------------------ 1-7 knowledge


def test_knowledge() -> None:
    check("real coverage data loads with no errors", REAL.errors == (), str(REAL.errors))

    product, _, _ = identify(["ELECTRIC KETTLE 1.5 L", "Net Quantity: 1 N"])
    applicability, confirmed, _ = confirm_product(product, REAL)
    coverage = REAL.coverage(product.standard_number, confirmed.id if confirmed else None)
    check("1 standard-only: kettle identified, coverage STANDARD_ONLY",
          product.status == "MATCHED" and coverage == "STANDARD_ONLY")
    check("1 standard-only: product not modelled, zero requirements and rules",
          applicability == "PRODUCT_NOT_MODELLED"
          and REAL.for_product(product.standard_number, None) == [], str(applicability))

    product, _, _ = identify(WATER + ["IS 14543"])
    applicability, confirmed, _ = confirm_product(product, REAL)
    applicable = REAL.for_product(product.standard_number, confirmed.id if confirmed else None)
    coverage = REAL.coverage(product.standard_number, confirmed.id if confirmed else None)
    check("2 inspection-supported: water is INSPECTION_SUPPORTED", coverage == "INSPECTION_SUPPORTED", coverage)
    check("2 inspection-supported: counts 3 requirements, 1 rule",
          (len(applicable), sum(r.supported for r in applicable)) == (3, 1), str(applicable))

    check("3 product-specific: packaged water confirmed from the label phrase",
          applicability == "PRODUCT_CONFIRMED" and confirmed is not None and confirmed.id == "packaged-drinking-water")
    two_products = data_file({
        "products": [water_product()],
        "requirements": [is_number_rule(applies_to_products=["packaged-drinking-water"])],
    })
    product, _, _ = identify(["AQUA PURE", "BOTTLED WATER", "PACKAGED DRINKING WATER"], two_products)
    applicability, confirmed, _ = confirm_product(product, two_products)
    applied = two_products.for_product(product.standard_number, confirmed.id if confirmed else None)
    check("3 product-limited requirement applies to the confirmed product",
          [r.id for r in applied] == ["water-is-number"], str([r.id for r in applied]))

    unconfirmed_product = identify_product(extract_declarations(label(WATER)), label(WATER), FINDER)
    unconfirmed_product = dataclass_replace_evidence(unconfirmed_product)
    applicability, confirmed, _ = confirm_product(unconfirmed_product, two_products)
    applied = two_products.for_product(unconfirmed_product.standard_number, confirmed.id if confirmed else None)
    check("3 product not confirmed -> product-limited requirement NOT applied",
          applied == [] and applicability == "PRODUCT_NOT_CONFIRMED", applicability)
    standard_wide = data_file({"products": [water_product()], "requirements": [is_number_rule()]})
    applied = standard_wide.for_product(unconfirmed_product.standard_number, None)
    check("3 standard-wide requirement applies even without product confirmation",
          [r.id for r in applied] == ["water-is-number"])

    product, _, _ = identify(["LED BULB 9W", "Self-ballasted LED lamp, Cool Daylight 6500K", "Net Quantity: 1 N"])
    applicability, confirmed, _ = confirm_product(product, REAL)
    applied = REAL.for_product(product.standard_number, confirmed.id if confirmed else None)
    check("4 unsupported requirement: LED confirmed, 1 verified requirement, 0 rules",
          applicability == "PRODUCT_CONFIRMED" and (len(applied), sum(r.supported for r in applied)) == (1, 0),
          str(applied))

    for r in REAL.requirements:
        src = KB[r.source_knowledge_id]
        check(f"5 {r.id} is verified: quote word for word in a verified record",
              r.source_quote in src.content and src.verification_status == "verified")
    check("5 only the printed IS-number rule is checkable among BIS requirements (no invented rules)",
          [r.id for r in REAL.requirements if r.supported and r.scope == "STANDARD"]
          == ["packaged-water-label-shows-is-number"])

    bad = data_file({
        "products": [
            water_product(id="bad-quote", standards=[{**water_product()["standards"][0], "source_quote": "Packaged drinking water is a product."}]),
            water_product(id="bad-alias", aliases=["mineral spring water"]),
            water_product(id="bad-status", standards=[{**water_product()["standards"][0], "applicability_status": "CANDIDATE"}]),
            water_product(id="bad-standard", standards=[{**water_product()["standards"][0], "standard_number": "IS 99999"}]),
            water_product(),
        ],
        "requirements": [
            is_number_rule(id="unknown-product", applies_to_products=["electric-kettle"]),
            is_number_rule(id="unlinked-product", applies_to=["IS 13428:2005"], applies_to_products=["packaged-drinking-water"]),
        ],
    })
    check("invented products / links / aliases are rejected",
          [p.id for p in bad.products] == ["packaged-drinking-water"] and bad.requirements == (), str(bad.errors))
    for fragment in ("does not appear word for word", "is not a phrase of the title or keywords",
                     "must be VERIFIED", "not a verified standard", "is not a valid product", "has no verified link"):
        check(f"rejection explains: {fragment}", any(fragment in err for err in bad.errors), str(bad.errors))


def dataclass_replace_evidence(product):
    """The same MATCHED product, but with no product-phrase evidence left to confirm a modelled product."""
    from dataclasses import replace
    return replace(product, evidence=[ev for ev in product.evidence if ev.match == "standard_number"])


# ------------------------------------------------------------------ matrix


def test_matrix() -> None:
    by_std = {c.standard_number: c for c in coverage_by_standard(ITEMS, REAL)}
    standards = [i for i in ITEMS if i.category == "indian_standards"]
    # The invariant is "every standard in the knowledge base appears in the matrix",
    # not a fixed count — the knowledge base grows. The floor guards against it shrinking.
    check("matrix covers every verified standard",
          len(by_std) == len(standards) and len(standards) >= 36, str(len(by_std)))
    supported = sorted(s for s, c in by_std.items() if c.coverage_status == "INSPECTION_SUPPORTED")
    check("matrix: only packaged water is supported for inspection",
          supported == ["IS 13428:2005", "IS 14543:2016"], str(supported))
    check("matrix: LED has 1 verified requirement and 0 rules",
          (by_std["IS 16102 (Part 1)"].verified_requirements, by_std["IS 16102 (Part 1)"].deterministic_rules) == (1, 0))
    rows = coverage_matrix(ITEMS, REAL)
    kettle = [r for r in rows if r.standard_number == "IS 367:1993"]
    check("matrix row: kettle has NO_REQUIREMENT_DATA and no product record",
          len(kettle) == 1 and kettle[0].status == "NO_REQUIREMENT_DATA" and kettle[0].product_id is None)
    water = {(r.product_id, r.requirement_id): r.status for r in rows if r.standard_number == "IS 14543:2016"}
    check("matrix rows: water product -> IS number SUPPORTED, mark UNSUPPORTED",
          water.get(("packaged-drinking-water", "packaged-water-label-shows-is-number")) == "SUPPORTED"
          and water.get(("packaged-drinking-water", "packaged-water-bis-certification-mark")) == "UNSUPPORTED", str(water))
    mineral = {r.requirement_id for r in rows if r.standard_number == "IS 13428:2005"}
    check("matrix rows: drinking-water-only requirement is not listed for mineral water",
          "packaged-drinking-water-quality-limits" not in mineral, str(mineral))

    body = TestClient(app).get("/inspection/coverage").json()
    check("GET /inspection/coverage returns standards + rows + no errors",
          len(body["standards"]) == len(standards) and body["rows"] and body["errors"] == [],
          str(body.get("errors")))


# ------------------------------------------------------------------ 8-13 extraction


def test_extraction() -> None:
    stage = extract_declarations(label(["Net Quantity: 1 L", "Manufactured by: CLEARFLOW BEVERAGES PVT LTD"]))
    m = field(stage, "manufacturer")
    check("8 valid manufacturer stays DETECTED", m.status == "DETECTED" and m.value == "CLEARFLOW BEVERAGES PVT LTD", str(m))
    joined = extract_declarations(label(["Packed by: SUNRISEFOODSPVTLTD", "MRP Rs 45"]))
    check("8 OCR-joined company name is still accepted", field(joined, "packer").status == "DETECTED")

    regions = [Region("OCR-001", "Net Quantity: 1 L", 0.95, [10, 10, 300, 40]),
               Region("OCR-002", "Manufactured by:", 0.95, [10, 60, 200, 90]),
               Region("OCR-003", "SCANQRCODE", 0.95, [10, 95, 200, 125])]
    m = field(extract_declarations(regions), "manufacturer")
    check("9 SCANQRCODE rejected as manufacturer (UNCERTAIN, no value)",
          m.status == "UNCERTAIN" and m.value is None and "QR" in m.reason, str(m))
    check("13 rejected manufacturer keeps its OCR evidence",
          m.source_regions == ["OCR-002", "OCR-003"] and "SCANQRCODE" in m.raw_text and m.bbox is not None)

    for noise in ("Mfd by: SCAN QR CODE", "Manufactured by: BARCODE", "Packed by: www.aquafresh.example",
                  "Mfd by: Net Quantity 1 L", "Manufactured by: see overleaf", "Mfd by: XKCDQ"):
        stage = extract_declarations(label(["MRP Rs 20", noise]))
        who = next(d for d in stage.fields if d.field in ("manufacturer", "packer") and d.status != "NOT_DETECTED")
        check(f"10 noise rejected: '{noise}'", who.status == "UNCERTAIN" and who.value is None, str(who))

    both = extract_declarations(label(["MRP Rs 20", "Manufactured by: SCAN QR CODE",
                                       "Manufactured by: CLEARFLOW BEVERAGES PVT LTD"]))
    m = field(both, "manufacturer")
    check("10 a valid name elsewhere is not put in conflict with QR noise",
          m.status == "DETECTED" and m.value == "CLEARFLOW BEVERAGES PVT LTD", str(m))

    junk = extract_declarations(label(["SCANQRCODE", "Net Quantity: 1 L", "MRP Rs 20"]))
    name = field(junk, "product_name")
    check("11 junk product-name candidate -> UNCERTAIN, no value",
          name.status == "UNCERTAIN" and name.value is None and "Product name uncertain" in name.reason, str(name))
    check("13 uncertain product name keeps the raw OCR region",
          name.source_regions == ["OCR-001"] and name.raw_text == "SCANQRCODE")

    ok = extract_declarations(label(["ROASTED MASALA CHANA", "Net Quantity: 200 g", "MRP Rs 45"]))
    name = field(ok, "product_name")
    check("12 valid product name still DETECTED", name.status == "DETECTED" and name.value == "Roasted Masala Chana", str(name))

    brand = [Region("OCR-001", "AQUA SPRING", 0.95, [10, 10, 400, 70]),
             Region("OCR-002", "PACKAGED DRINKING WATER", 0.95, [10, 80, 500, 130]),
             Region("OCR-003", "Net Quantity: 1 L", 0.95, [10, 140, 200, 165]),
             Region("OCR-004", "MRP Rs 20", 0.95, [10, 170, 200, 195]),
             Region("OCR-005", "Batch No: CF-0526-B", 0.95, [10, 200, 200, 225])]
    name = field(extract_declarations(brand), "product_name")
    check("11 brand-like prominent line -> product name UNCERTAIN and never the brand text",
          name.status == "UNCERTAIN" and "brand" in name.reason and name.value != "Aqua Spring", str(name))

    fssai = field(extract_declarations(label(["MRP Rs 20", "FSSAl Lic.No.10099999000456"])), "fssai_license")
    check("OCR 'FSSAl' misread still reads the licence digits", fssai.value == "10099999000456", str(fssai))


# ------------------------------------------------------------------ 14-18 completeness


def test_completeness() -> None:
    res = run_downstream(label(WATER + ["IS 14543"]), finder=FINDER, requirements=REAL)
    bis_ids = {r.id for r in REAL.requirements if r.scope == "STANDARD"}
    linked = [i.field for i in res.completeness.items if set(i.requirement_ids) & bis_ids]
    check("completeness links only the field a verified BIS rule uses", linked == ["standard_number"], str(linked))
    mrp = next(i for i in res.completeness.items if i.field == "mrp")
    check("completeness: MRP is not linked to a BIS requirement (MetrIQ has no verified BIS MRP rule)",
          not set(mrp.requirement_ids) & bis_ids, str(mrp.requirement_ids))
    led = run_downstream(label(["LED BULB 9W", "Self-ballasted LED lamp, Cool Daylight 6500K"]), finder=FINDER, requirements=REAL)
    check("completeness: LED has no BIS-requirement-linked fields (its BIS requirement is not checkable)",
          not any(set(i.requirement_ids) & bis_ids for i in led.completeness.items))
    check("completeness: not detected is never called missing",
          not any(FORBIDDEN.search(i.statement) for i in res.completeness.items))

    plain = declaration_completeness(extract_declarations(label(WATER)), REAL, "IS 14543:2016")
    check("completeness without a confirmed product applies no product-limited requirement",
          plain.with_verified_requirement == 0)

    import ast

    import app.escalation as escalation_module
    import app.requirements as requirements_module
    for module in (requirements_module, escalation_module):
        tree = ast.parse(Path(module.__file__).read_text())
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        check(f"no model decides coverage or resolution ({module.__name__})",
              not imported & {"app.llm", "app.openrouter", "httpx", "requests", "openai"}, str(imported))


# ------------------------------------------------------------------ real OCR


def analyze(name: str):
    upload = PackageUpload((SAMPLES / name).read_bytes(), filename=name)
    return InspectionAnalyzer(llm=None, product_finder=FINDER).analyze_package([upload])


def test_real_labels() -> None:
    water = analyze("synth_packaged-water.png")
    check("real water: product + standard identified", water.product.standard_number == "IS 14543:2016")
    check("real water: product confirmed",
          water.product.product_applicability == "PRODUCT_CONFIRMED", water.product.product_applicability)
    check("real water: declaration for the IS number is DETECTED",
          field(water.declaration_stage, "standard_number").status == "DETECTED")

    led = analyze("synth_led-lamp.png")
    check("real LED: identified but not a modelled requirements product",
          led.product.standard_number is not None, led.product.reason)

    kettle = analyze("synth_electric-kettle.png")
    check("real kettle: in the KB but no requirement data -> PRODUCT_NOT_MODELLED",
          kettle.product.standard_number == "IS 367:1993"
          and kettle.product.product_applicability == "PRODUCT_NOT_MODELLED")

    noisy = analyze("synth_noisy-qr-label.png")
    fields = {d.field: d for d in noisy.declaration_stage.fields}
    check("real poor OCR: QR text never becomes a confident manufacturer",
          fields["manufacturer"].status != "DETECTED" and fields["manufacturer"].value is None, str(fields["manufacturer"]))
    check("real poor OCR: QR text never becomes a confident product name",
          fields["product_name"].status != "DETECTED" and fields["product_name"].value is None, str(fields["product_name"]))
    check("real poor OCR: no product, no standard identified",
          noisy.product.status == "REVIEW" and noisy.product.standard_number is None)


# ------------------------------------------------------------------ 19-25 regression


def test_regression() -> None:
    client = TestClient(app)
    check("/health responds", client.get("/health").status_code == 200)
    search = client.post("/search", json={"query": "packaged drinking water"}).json()
    check("/search still grounded", search.get("results"))
    body = client.post("/product-standard", json={"product": "packaged drinking water"}).json()
    check("22 Product -> Standard unchanged",
          set(body) == {"product", "results", "grounded", "confidence", "note"}
          and body["results"][0]["standard_number"] == "IS 14543:2016")
    check("23 Why-this-result still present", body["results"][0]["why"]["summary"].startswith("Retrieved as a candidate standard"))

    png = (SAMPLES / "synth_electric-kettle.png").read_bytes()
    instant = client.post("/inspection/ocr", files={"image": ("k.png", png, "image/png")})
    check("19 Instant OCR endpoint still works", instant.status_code == 200 and instant.json()["ocr"]["regions"])
    check("20 declaration extraction still returned by Instant OCR",
          any(d["status"] == "DETECTED" for d in instant.json()["declaration_stage"]["fields"]))

    multi = client.post(
        "/inspection/analyze",
        files=[("images", ("front.png", (SAMPLES / "synth_packaged-water.png").read_bytes(), "image/png")),
               ("images", ("back.png", png, "image/png"))],
        data={"sides": ["FRONT", "BACK"]},
    )
    j = multi.json()
    check("24 multi-side inspection still works", multi.status_code == 200 and len(j["images"]) == 2, str(multi.status_code))
    check("21 product identification still returned", j["product"]["status"] in ("MATCHED", "REVIEW"))
    check("25 no compliance verdict is returned", "compliance" not in j and "package_label" not in j, str(list(j)))


def main() -> int:
    print("knowledge + rule coverage foundation")
    for fn in (test_knowledge, test_matrix, test_extraction, test_completeness, test_real_labels, test_regression):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
