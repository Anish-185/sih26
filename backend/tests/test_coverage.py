"""Checks for Milestone 7: knowledge + rule coverage foundation.

    PRODUCT -> STANDARD -> APPLICABLE REQUIREMENTS -> DETERMINISTIC RULES -> EVIDENCE

Covers product-specific applicability (app/requirements.py), coverage states and
explanations (app/compliance.py), conservative extraction of names
(app/declarations.py), the coverage matrix + GET /inspection/coverage, and
regressions. Plain Python, no test framework (matches the other runners). Run:

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
from app.compliance import evaluate_compliance  # noqa: E402
from app.declarations import extract_declarations  # noqa: E402
from app.inspection import InspectionAnalyzer, PackageUpload  # noqa: E402
from app.main import app  # noqa: E402
from app.pipeline import run_downstream  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.product_identification import identify_product  # noqa: E402
from app.requirements import coverage_by_standard, coverage_matrix, load_requirements  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0
FINDER = ProductStandardFinder(SearchEngine())
ITEMS = FINDER.search_engine.items
KB = {i.id: i for i in ITEMS}
REAL = load_requirements(ITEMS)
SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "ocr-labels"

WATER_QUOTE = "A consumer should therefore expect to see the ISI Mark with the IS number (IS 14543 or IS 13428) on the bottle."
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
        "source_knowledge_id": "packaged-water-must-carry-bis-mark", "source_quote": WATER_QUOTE,
        **over,
    }


def evaluate(lines, requirements=REAL):
    regions = label(lines)
    stage = extract_declarations(regions)
    product = identify_product(stage, regions, FINDER)
    return evaluate_compliance(product, stage, requirements, ITEMS), product, stage


WATER = ["AQUA PURE", "PACKAGED DRINKING WATER", "NET QUANTITY: 1 L"]


def field(stage, name):
    return next(d for d in stage.fields if d.field == name)


# ------------------------------------------------------------------ 1-7 knowledge


def test_knowledge() -> None:
    check("real coverage data loads with no errors", REAL.errors == (), str(REAL.errors))

    ev, product, _ = evaluate(["ELECTRIC KETTLE 1.5 L", "Net Quantity: 1 N"])
    cov = ev.inspection_coverage
    check("1 standard-only: kettle identified, coverage STANDARD_ONLY",
          product.status == "MATCHED" and ev.coverage_status == "STANDARD_ONLY" and ev.checks == [], ev.reason)
    check("1 standard-only: product not modelled, zero requirements and rules",
          cov.product_applicability == "PRODUCT_NOT_MODELLED" and cov.verified_requirements == 0
          and cov.deterministic_rules == 0, str(cov))
    check("1 standard-only explanation names the knowledge-base limit, not the package",
          "does not yet have structured verified requirement data" in cov.explanation
          and "not a finding about the package" in cov.explanation, cov.explanation)

    ev, _, _ = evaluate(WATER + ["IS 14543"])
    cov = ev.inspection_coverage
    check("2 inspection-supported: water is SUPPORTED_FOR_INSPECTION",
          ev.coverage_status == "SUPPORTED_FOR_INSPECTION", ev.coverage_status)
    check("2 inspection-supported: counts 3 requirements, 1 rule, 2 unsupported",
          (cov.verified_requirements, cov.deterministic_rules, cov.unsupported_requirements) == (3, 1, 2), str(cov))
    check("2 explanation counts the deterministic rules for this product and standard",
          "1 deterministic inspection rule for Packaged Drinking Water under IS 14543:2016" in cov.explanation,
          cov.explanation)

    check("3 product-specific: packaged water confirmed from the label phrase",
          cov.product_applicability == "PRODUCT_CONFIRMED" and cov.product_id == "packaged-drinking-water")
    two_products = data_file({
        "products": [water_product()],
        "requirements": [is_number_rule(applies_to_products=["packaged-drinking-water"])],
    })
    ev, _, _ = evaluate(["AQUA PURE", "BOTTLED WATER", "PACKAGED DRINKING WATER"], two_products)
    check("3 product-limited requirement applies to the confirmed product",
          [c.rule_id for c in ev.checks] == ["water-is-number"], str([c.rule_id for c in ev.checks]))
    product = identify_product(extract_declarations(label(WATER)), label(WATER), FINDER)
    unconfirmed = dataclass_replace_evidence(product)
    ev = evaluate_compliance(unconfirmed, extract_declarations(label(WATER)), two_products, ITEMS)
    check("3 product not confirmed -> product-limited requirement NOT applied",
          ev.checks == [] and ev.inspection_coverage.product_applicability == "PRODUCT_NOT_CONFIRMED"
          and ev.inspection_coverage.not_applied_requirements == ["water-is-number"], str(ev.inspection_coverage))
    check("3 product not confirmed -> REVIEW with a product-specific reason",
          ev.overall_status == "REVIEW" and ev.reason_code == "PRODUCT_NOT_CONFIRMED"
          and "did not name that product" in ev.inspection_coverage.explanation, ev.reason)
    standard_wide = data_file({"products": [water_product()], "requirements": [is_number_rule()]})
    ev = evaluate_compliance(unconfirmed, extract_declarations(label(WATER)), standard_wide, ITEMS)
    check("3 standard-wide requirement applies even without product confirmation",
          [c.rule_id for c in ev.checks] == ["water-is-number"])

    ev, _, _ = evaluate(["LED BULB 9W", "Self-ballasted LED lamp, Cool Daylight 6500K", "Net Quantity: 1 N"])
    led = ev.inspection_coverage
    check("4 unsupported requirement: LED confirmed, 1 verified requirement, 0 rules",
          led.product_applicability == "PRODUCT_CONFIRMED" and (led.verified_requirements, led.deterministic_rules) == (1, 0),
          str(led))
    check("4 unsupported requirement is shown as NOT_SUPPORTED, never scored",
          [c.result for c in ev.checks] == ["NOT_SUPPORTED"] and ev.supported_checks == 0
          and ev.coverage_status == "STANDARD_ONLY" and ev.overall_status == "REVIEW")

    for r in REAL.requirements:
        src = KB[r.source_knowledge_id]
        check(f"5 {r.id} is verified: quote word for word in a verified record",
              r.source_quote in src.content and src.verification_status == "verified")
    check("5 only the printed IS-number rule is checkable (no invented rules)",
          [r.id for r in REAL.requirements if r.supported] == ["packaged-water-label-shows-is-number"])

    ev, _, _ = evaluate(WATER + ["IS 14543"])
    for c in ev.checks:
        check(f"6 requirement evidence: {c.rule_id} -> verified BIS record with URL",
              c.source is not None and c.source.quote in KB[c.source.knowledge_id].content
              and c.source.source_url and c.source.last_verified)
    link = ev.inspection_coverage.applicability_source
    check("6 product -> standard evidence: verified record quote + URL",
          link is not None and link.knowledge_id == "packaged-drinking-water-certification"
          and link.quote in KB[link.knowledge_id].content and link.source_url.startswith("https://"))
    rule = next(c for c in ev.checks if c.rule_id == "packaged-water-label-shows-is-number")
    e = rule.evidence[0]
    check("7 rule evidence: package chain image -> OCR region -> declaration -> observed value",
          rule.result == "PASS" and e.image_id == "IMG-TEST" and e.source_regions == ["OCR-004"]
          and e.declaration_field == "standard_number" and rule.observed_value == "IS 14543")
    check("7 rule evidence: rule condition states its thresholds", "≥80%" in rule.rule_condition)

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
    check("matrix covers every verified standard", len(by_std) == len(standards) == 36, str(len(by_std)))
    supported = sorted(s for s, c in by_std.items() if c.inspection_status == "SUPPORTED_FOR_INSPECTION")
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
          len(body["standards"]) == 36 and body["rows"] and body["errors"] == [], str(body.get("errors")))


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
    check("11 two prominent unlabelled lines -> product name UNCERTAIN (could be the brand)",
          name.status == "UNCERTAIN" and "brand" in name.reason and name.value == "Aqua Spring", str(name))

    fssai = field(extract_declarations(label(["MRP Rs 20", "FSSAl Lic.No.10099999000456"])), "fssai_license")
    check("OCR 'FSSAl' misread still reads the licence digits", fssai.value == "10099999000456", str(fssai))


# ------------------------------------------------------------------ 14-18 compliance


def test_compliance() -> None:
    ev, _, _ = evaluate(WATER + ["IS 14543"])
    rule = next(c for c in ev.checks if c.rule_id == "packaged-water-label-shows-is-number")
    check("14 supported rule works (PASS on the correct printed number)", rule.result == "PASS", rule.reason)
    check("18 existing IS-number rule: wrong number read clearly -> FAIL",
          next(c for c in evaluate(WATER + ["IS 14534"])[0].checks if c.rule_type == "printed_standard_number").result == "FAIL")

    check("15 unsupported requirements never PASS",
          all(c.result == "NOT_SUPPORTED" for c in ev.checks if c.rule_type == "not_supported"))
    check("15 PASS rule + unsupported areas -> overall REVIEW, not PASS",
          ev.overall_status == "REVIEW" and ev.reason_code == "REQUIREMENTS_NOT_CHECKABLE", ev.reason)

    ev, _, _ = evaluate(["ROASTED MASALA CHANA", "(Roasted Bengal gram with spices)"])
    check("16 standard-only -> REVIEW", ev.overall_status == "REVIEW" and ev.coverage_status == "STANDARD_ONLY")
    check("16 summary explains why it is only REVIEW",
          any("no deterministic inspection is possible" in s for s in ev.summary), str(ev.summary))

    ev, _, _ = evaluate(WATER)
    rule = ev.checks[0]
    check("17 insufficient evidence (IS number not detected) -> REVIEW",
          rule.result == "REVIEW" and rule.reason_code == "EVIDENCE_NOT_DETECTED" and ev.overall_status == "REVIEW")
    merged = evaluate(WATER + ["ISTIS 14543 CM/L-7654321"])[0]
    check("17 OCR-merged 'ISTIS 14543' is not read as a number -> REVIEW, never PASS",
          merged.checks[0].result == "REVIEW", merged.checks[0].reason)
    low = evaluate([*WATER, "IS 14543"], REAL)
    check("17 all explanations avoid 'missing' claims",
          not any(FORBIDDEN.search(s) for s in low[0].summary + [c.reason for c in low[0].checks]))

    res = run_downstream(label(WATER + ["IS 14543"]), finder=FINDER, requirements=REAL)
    linked = [i.field for i in res.completeness.items if i.requirement_coverage == "VERIFIED_REQUIREMENT"]
    check("completeness links only the field a verified rule uses", linked == ["standard_number"], str(linked))
    mrp = next(i for i in res.completeness.items if i.field == "mrp")
    check("completeness: detected MRP is an observation, not a requirement",
          mrp.requirement_coverage == "NOT_ESTABLISHED")
    led = run_downstream(label(["LED BULB 9W", "Self-ballasted LED lamp, Cool Daylight 6500K"]), finder=FINDER, requirements=REAL)
    check("completeness: LED has no requirement-linked fields (its requirement is not checkable)",
          led.completeness.with_verified_requirement == 0)
    check("completeness: not detected is never called missing",
          not any(FORBIDDEN.search(i.statement) for i in res.completeness.items))

    plain = declaration_completeness(extract_declarations(label(WATER)), REAL, "IS 14543:2016")
    check("completeness without a confirmed product applies no product-limited requirement",
          plain.with_verified_requirement == 0)

    import ast

    import app.compliance as compliance_module
    import app.requirements as requirements_module
    for module in (compliance_module, requirements_module):
        tree = ast.parse(Path(module.__file__).read_text())
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        check(f"no model decides coverage or results ({module.__name__})",
              not imported & {"app.llm", "httpx", "requests", "openai"}, str(imported))


# ------------------------------------------------------------------ real OCR


def analyze(name: str):
    upload = PackageUpload((SAMPLES / name).read_bytes(), filename=name)
    return InspectionAnalyzer(llm=None, product_finder=FINDER).analyze_package([upload])


def test_real_labels() -> None:
    water = analyze("synth_packaged-water.png")
    cov = water.compliance.coverage
    rule = next(c for c in water.compliance.checks if c.rule_id == "packaged-water-label-shows-is-number")
    check("real water: product + standard identified", water.product.standard_number == "IS 14543:2016")
    check("real water: product confirmed, 1 rule of 3 requirements",
          cov.product_applicability == "PRODUCT_CONFIRMED" and (cov.verified_requirements, cov.deterministic_rules) == (3, 1),
          str(cov))
    check("real water: actual deterministic check PASS on OCR evidence",
          rule.result == "PASS" and rule.evidence and rule.evidence[0].source_regions, rule.reason)
    check("real water: overall REVIEW (unsupported areas remain)", water.compliance.overall_status == "REVIEW")

    led = analyze("synth_led-lamp.png")
    check("real LED: STANDARD_ONLY REVIEW with its unsupported requirement listed",
          led.compliance.coverage_status == "STANDARD_ONLY" and led.compliance.overall_status == "REVIEW"
          and [c.result for c in led.compliance.checks] == ["NOT_SUPPORTED"], led.compliance.reason)

    kettle = analyze("synth_electric-kettle.png")
    check("real kettle: in the KB but no requirement data -> transparent REVIEW",
          kettle.product.standard_number == "IS 367:1993" and kettle.compliance.coverage.product_applicability == "PRODUCT_NOT_MODELLED"
          and kettle.compliance.checks == [] and "not a finding about the package" in kettle.compliance.coverage.explanation)

    noisy = analyze("synth_noisy-qr-label.png")
    fields = {d.field: d for d in noisy.declaration_stage.fields}
    check("real poor OCR: QR text never becomes a confident manufacturer",
          fields["manufacturer"].status != "DETECTED" and fields["manufacturer"].value is None, str(fields["manufacturer"]))
    check("real poor OCR: QR text never becomes a confident product name",
          fields["product_name"].status != "DETECTED" and fields["product_name"].value is None, str(fields["product_name"]))
    check("real poor OCR: no product, no standard, compliance REVIEW",
          noisy.product.status == "REVIEW" and noisy.compliance.coverage_status == "NO_STANDARD"
          and noisy.compliance.overall_status == "REVIEW")


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
    check("25 compliance response keeps its existing fields and adds coverage detail",
          {"overall_status", "coverage_status", "checks", "summary", "policy"} <= set(j["compliance"])
          and {"supported_checks", "passed", "product_applicability", "explanation"} <= set(j["compliance"]["coverage"]))


def main() -> int:
    print("knowledge + rule coverage foundation")
    for fn in (test_knowledge, test_matrix, test_extraction, test_compliance, test_real_labels, test_regression):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
