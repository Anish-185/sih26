"""Checks for the Milestone 7 hardening pass.

* coverage classes: INSPECTION_SUPPORTED / STANDARD_ONLY / UNSUPPORTED, with reasons
* knowledge domains: jewellery hallmark / HUID evidence never becomes a package-label rule
* IS-number normalization, validated against the verified knowledge base
* brand != product name
* email normalization for OCR-inserted spaces
* provenance of every normalized value, and regressions

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_hardening.py

Exit 0 = all checks passed, 1 = something failed.

Controlled OCR fixtures + the real knowledge base and requirement data, plus the
real local OCR engine on the synthetic sample labels. No LM Studio / OpenRouter.
"""

from __future__ import annotations

import json
import sys
import tempfile
import warnings
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app.compliance import evaluate_compliance  # noqa: E402
from app.declarations import DeclarationKnowledge, extract_declarations  # noqa: E402
from app.inspection import InspectionAnalyzer, PackageUpload  # noqa: E402
from app.main import app  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.product_identification import identify_product  # noqa: E402
from app.requirements import coverage_by_standard, knowledge_domain, load_requirements  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0
FINDER = ProductStandardFinder(SearchEngine())
ITEMS = FINDER.search_engine.items
KB = {i.id: i for i in ITEMS}
REAL = load_requirements(ITEMS)
SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "ocr-labels"
WATER_QUOTE = "A consumer should therefore expect to see the ISI Mark with the IS number (IS 14543 or IS 13428) on the bottle."


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


def fields(lines, knowledge=None):
    stage = extract_declarations(label(lines), knowledge)
    return {d.field: d for d in stage.fields}


def evaluate(lines, requirements=REAL):
    regions = label(lines)
    stage = extract_declarations(regions)
    product = identify_product(stage, regions, FINDER)
    return evaluate_compliance(product, stage, requirements, ITEMS), product, stage


def data_file(rows: list[dict]):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "req.json"
        path.write_text(json.dumps({"requirements": rows}), encoding="utf-8")
        return load_requirements(ITEMS, path)


WATER = ["AQUA PURE", "PACKAGED DRINKING WATER", "NET QUANTITY: 1 L"]


# ------------------------------------------------------------ 1-3 IS normalization


def test_standard_numbers() -> None:
    one = fields(["MRP Rs 20", "ISI  IS 14543"])["standard_number"]
    check("1 'ISI  IS 14543' -> IS 14543 read", one.status == "DETECTED" and one.value == "IS 14543", str(one))
    _, product, _ = evaluate(WATER + ["ISI  IS 14543"])
    check("1 ... and linked to the verified knowledge-base standard",
          product.status == "MATCHED" and product.standard_number == "IS 14543:2016"
          and any(ev.match == "standard_number" for ev in product.evidence), product.reason)
    _, product, _ = evaluate(WATER + ["ISI  IS 99999"])
    check("1 'ISI  IS 99999' is never treated as a verified standard",
          product.unverified_standard_numbers == ["IS 99999"] and product.standard_number == "IS 14543:2016",
          str(product.unverified_standard_numbers))

    two = fields(["MRP Rs 20", "ISTIS 14543"])["standard_number"]
    check("2 'ISTIS 14543' -> normalized to IS 14543 (verified number)",
          two.status == "DETECTED" and two.value == "IS 14543" and two.extraction_method == "deterministic_normalization",
          str(two))
    check("2 original OCR text preserved; note says what was normalized",
          two.raw_text == "ISTIS 14543" and "ISTIS 14543" in two.note and "verified" in two.note)
    check("2 provenance kept: region, box, image, OCR confidence",
          two.source_regions == ["OCR-002"] and two.bbox is not None and two.image_id == "IMG-TEST"
          and two.ocr_confidence == 0.95)
    for text in ("IS No. 14543", "IS NUMBER 14543", "Indian Standard 13428", "1S 16102"):
        d = fields(["MRP Rs 20", text])["standard_number"]
        check(f"2 '{text}' recovered only because the number is verified",
              d.status == "DETECTED" and d.extraction_method == "deterministic_normalization", str(d))
    check("2 'IS:14543' stays a clean (non-normalized) read",
          fields(["MRP Rs 20", "IS:14543"])["standard_number"].extraction_method == "deterministic")

    three = fields(["MRP Rs 20", "ISTIS 99999"])["standard_number"]
    check("3 'ISTIS 99999' -> UNCERTAIN, no number invented",
          three.status == "UNCERTAIN" and three.value is None and "not a verified standard" in three.reason, str(three))
    check("3 evidence of the unrecovered reference is kept", three.raw_text == "ISTIS 99999" and three.source_regions)
    empty = DeclarationKnowledge(frozenset(), ())
    check("3 no verified knowledge -> nothing is recovered",
          fields(["MRP Rs 20", "ISTIS 14543"], empty)["standard_number"].value is None)
    for text in ("This is 14543 grams", "Batch 14543", "Net 14543 g"):
        check(f"3 arbitrary digits are never an IS number ('{text}')",
              fields(["MRP Rs 20", text])["standard_number"].status == "NOT_DETECTED")
    both = fields(["MRP Rs 20", "IS 14543", "ISTIS 99999"])["standard_number"]
    check("3 an unverified corrupt reference does not conflict with a clean read",
          both.status == "DETECTED" and both.value == "IS 14543", str(both))

    ev, _, _ = evaluate(WATER + ["ISTIS 14543"])
    rule = next(c for c in ev.checks if c.rule_type == "printed_standard_number")
    check("normalized verified IS number can confirm a match (PASS)", rule.result == "PASS", rule.reason)
    _, conflict_product, _ = evaluate(WATER + ["ISTIS 13428"])
    check("a normalized number of a different verified record puts identification in REVIEW",
          conflict_product.status == "REVIEW", conflict_product.reason)
    _, water_product, _ = evaluate(WATER)
    other = extract_declarations(label(WATER + ["ISTIS 13428"]))
    ev = evaluate_compliance(water_product, other, REAL, ITEMS)
    rule = next(c for c in ev.checks if c.rule_type == "printed_standard_number")
    check("normalized reading is never used to FAIL a package -> REVIEW",
          rule.result == "REVIEW" and rule.reason_code == "EVIDENCE_NORMALIZED" and ev.overall_status == "REVIEW",
          rule.reason)
    ev, _, _ = evaluate(WATER + ["IS 14534"])
    check("clean different IS number still FAILs (existing rule preserved)",
          next(c for c in ev.checks if c.rule_type == "printed_standard_number").result == "FAIL")


# ------------------------------------------------------------ 4-5 product name


def test_product_name() -> None:
    f = fields(["AQUA SPRING", "PACKAGED DRINKING WATER", "Net Quantity: 1 L"])
    check("4 brand-like line is not the product name",
          f["product_name"].value != "Aqua Spring" and f["product_name"].status == "UNCERTAIN", str(f["product_name"]))
    check("4 brand may be Aqua Spring (UNCERTAIN, not labelled)",
          f["brand"].value == "Aqua Spring" and f["brand"].status == "UNCERTAIN", str(f["brand"]))
    check("4 product line with product words is offered, uncertain",
          f["product_name"].value == "Packaged Drinking Water" and "brand" in f["product_name"].reason)
    led = fields(["LED BULB 9W", "Self-ballasted LED lamp, Cool Daylight 6500K", "Net Quantity: 1 N"])
    # The safety property is unchanged: a prominent descriptor is never offered as
    # a brand. Since Milestone 14 added "led bulb" to the verified BIS vocabulary
    # (BIS lists Self-Ballasted LED Lamps under the Compulsory Registration
    # Scheme), the prominent line is now recognised as the product name itself.
    check("4 a prominent descriptor sharing words with the product line is not offered as a brand",
          led["brand"].status == "NOT_DETECTED" and "brand" not in led["product_name"].reason,
          str(led["product_name"]))
    check("4 a prominent line made of knowledge-base product words is read as the product",
          led["product_name"].status == "DETECTED" and led["product_name"].value == "Led Bulb 9W",
          str(led["product_name"]))
    alone = fields(["AQUA SPRING", "Net Quantity: 1 L", "MRP Rs 20"])["product_name"]
    check("4 only a brand-like phrase -> product name UNCERTAIN with no value",
          alone.status == "UNCERTAIN" and alone.value is None and alone.raw_text == "AQUA SPRING", str(alone))
    labelled_brand = fields(["AQUA SPRING", "Brand: AQUA SPRING", "Net Quantity: 1 L"])
    check("4 labelled brand is kept; its text is not the product name",
          labelled_brand["brand"].value == "AQUA SPRING" and labelled_brand["product_name"].value != "Aqua Spring")

    five = fields(["Product Name: Roasted Bengal Gram", "Net Quantity: 200 g", "MRP Rs 45"])["product_name"]
    check("5 'Product Name: Roasted Bengal Gram' -> DETECTED",
          five.status == "DETECTED" and five.value == "Roasted Bengal Gram" and five.method == "regex", str(five))
    other = fields(["Generic Name: Ratlami Sev", "MRP Rs 20"])["product_name"]
    check("5 a labelled product name need not be in the knowledge base", other.status == "DETECTED"
          and other.value == "Ratlami Sev", str(other))
    junk = fields(["Product Name: SCAN QR CODE", "MRP Rs 20"])["product_name"]
    check("5 labelled QR noise is still rejected", junk.status == "UNCERTAIN" and junk.value is None, str(junk))
    kettle = fields(["ELECTRIC KETTLE 1.5 L", "Net Quantity: 1 N", "MRP Rs 899"])["product_name"]
    check("prominent line naming a knowledge-base product stays DETECTED",
          kettle.status == "DETECTED" and kettle.value == "Electric Kettle 1.5 L", str(kettle))


# ------------------------------------------------------------ 6-8 email


def test_email() -> None:
    six = fields(["MRP Rs 20", "Consumer Care: care@ clearflow.com"])["consumer_care"]
    check("6 'care@ clearflow.com' -> care@clearflow.com",
          six.status == "DETECTED" and six.value == "care@clearflow.com"
          and six.extraction_method == "deterministic_normalization", str(six))
    check("6 original OCR text preserved", six.raw_text == "Consumer Care: care@ clearflow.com" and "care@ clearflow.com" in six.note)
    seven = fields(["MRP Rs 20", "Email: care @clearflow.com"])["consumer_care"]
    check("7 'care @clearflow.com' -> care@clearflow.com", seven.value == "care@clearflow.com", str(seven))
    dot = fields(["MRP Rs 20", "care@clearflow .com"])["consumer_care"]
    check("7 'care@clearflow .com' -> care@clearflow.com", dot.value == "care@clearflow.com", str(dot))
    clean = fields(["MRP Rs 20", "care@clearflow.com"])["consumer_care"]
    check("clean email is not marked as normalized", clean.extraction_method == "deterministic")

    for text in ("Follow us @ freshfoods.com", "Follow @freshfoods.com", "Buy 2 @ 99 only", "Offers @ store.in",
                 "Contact: care @ clearflow . com", "Call us @ home", "care@ clear flow.com"):
        check(f"8 no fake email from '{text}'", fields(["MRP Rs 20", text])["consumer_care"].status == "NOT_DETECTED")


# ------------------------------------------------------------ 9-11 knowledge / coverage


def test_knowledge() -> None:
    check("9 real requirement data loads with no errors", REAL.errors == (), str(REAL.errors))
    check("9 hallmarking records are in the jewellery domain",
          all(knowledge_domain(KB[k]) == "JEWELLERY_HALLMARKING"
              for k in ("what-is-huid", "hallmark-components-since-huid", "is-1417-2016-gold-hallmarking-fineness")))
    check("9 general BIS records that merely mention hallmarking stay general",
          knowledge_domain(KB["bis-core-functions"]) == "GENERAL_BIS_INFORMATION")

    huid = {
        "id": "huid-six-digits", "applies_to": ["IS 1417:2016"],
        "description": "The article shows a six-digit alphanumeric HUID.",
        "rule_type": "not_supported", "unsupported_reason": "not a package label",
        "source_knowledge_id": "what-is-huid",
        "source_quote": KB["what-is-huid"].content.split(". ")[1],
    }
    via_general = {
        **huid, "id": "huid-via-general-record", "applies_to": ["IS 14543:2016"],
        "source_knowledge_id": "hallmarking-is-a-conformity-assessment-activity",
        "source_quote": "a six-digit alphanumeric HUID (Hallmark Unique Identification) number",
    }
    hallmark_quote_general = {
        **huid, "id": "hallmark-quote-in-general-record", "applies_to": ["IS 14543:2016"],
        "source_knowledge_id": "bis-care-app-for-consumers",
        "source_quote": "a consumer can use it to verify the six-digit HUID number on a hallmarked gold or silver article",
    }
    bad = data_file([huid, via_general, hallmark_quote_general])
    check("9 jewellery HUID evidence cannot become a package-label requirement",
          bad.requirements == (), str([r.id for r in bad.requirements]))
    for fragment in ("jewellery hallmarking evidence", "jewellery hallmarking standard", "about hallmarks / HUID"):
        check(f"9 rejection explains: {fragment}", any(fragment in e for e in bad.errors), str(bad.errors))
    jewellery = data_file([{**huid, "domain": "JEWELLERY_HALLMARKING"}])
    check("9 a jewellery-domain requirement is never applied to package inspection",
          jewellery.errors == () and jewellery.for_standard("IS 1417:2016") == [], str(jewellery.errors))
    check("9 unknown domain rejected", data_file([{**huid, "domain": "EVERYTHING"}]).requirements == ())

    by_std = {c.standard_number: c for c in coverage_by_standard(ITEMS, REAL)}
    kettle = by_std["IS 367:1993"]
    check("10 standard with no structured requirement -> STANDARD_ONLY with a reason",
          kettle.coverage_status == "STANDARD_ONLY" and kettle.verified_requirements == 0
          and "No verified image-checkable requirement data" in kettle.reason, kettle.reason)
    check("10 the Scheme I route is reported, not encoded as a rule",
          kettle.certification_route == "Scheme I (ISI Mark)" and "not encoded as a rule" in kettle.reason)
    led = by_std["IS 16102 (Part 1)"]
    check("10 LED: verified but uncheckable requirement -> STANDARD_ONLY, CRS route reported",
          led.coverage_status == "STANDARD_ONLY" and led.verified_requirements == 1 and led.deterministic_rules == 0
          and led.certification_route == "Scheme II (CRS registration)")
    water = by_std["IS 14543:2016"]
    check("11 verified image-checkable requirement -> INSPECTION_SUPPORTED",
          water.coverage_status == "INSPECTION_SUPPORTED" and (water.verified_requirements, water.deterministic_rules) == (3, 1),
          water.reason)
    gold = by_std["IS 1417:2016"]
    check("hallmarking standard -> UNSUPPORTED for package inspection",
          gold.coverage_status == "UNSUPPORTED" and gold.domain == "JEWELLERY_HALLMARKING" and "jewellery" in gold.reason)
    counts = {s: sum(c.coverage_status == s for c in by_std.values()) for s in ("INSPECTION_SUPPORTED", "STANDARD_ONLY", "UNSUPPORTED")}
    # The knowledge base grows; what must not change is that coverage is earned
    # from data. Only packaged water has image-checkable requirements, only the
    # four hallmarking standards are UNSUPPORTED, and every other standard is
    # STANDARD_ONLY — retrievable and explainable, with no invented rule.
    check("coverage classes stay data-derived: 2 inspection-supported, 4 hallmarking-unsupported",
          (counts["INSPECTION_SUPPORTED"], counts["UNSUPPORTED"]) == (2, 4)
          and counts["STANDARD_ONLY"] == len(by_std) - 6 and len(by_std) >= 36,
          str(counts))
    check("only one checkable BIS rule exists in the data (nothing invented)",
          [r.id for r in REAL.requirements if r.supported and r.scope == "STANDARD"]
          == ["packaged-water-label-shows-is-number"])
    for c in by_std.values():
        check(f"coverage row has a reason and source ({c.standard_number})", bool(c.reason) and bool(c.source_document))

    body = TestClient(app).get("/inspection/coverage").json()
    totals = body["totals"]
    check("GET /inspection/coverage exposes totals + reasons",
          totals["total"] == len(body["standards"])
          and (totals["inspection_supported"], totals["unsupported"]) == (2, 4)
          and totals["standard_only"] == totals["total"] - 6
          and all(s["reason"] for s in body["standards"]), str(totals))

    _, water_product, stage = evaluate(WATER + ["IS 14543"])
    gold_record = KB["is-1417-2016-gold-hallmarking-fineness"]
    gold_match = replace(water_product, knowledge_id=gold_record.id, standard_number=gold_record.standard_number,
                         name="Gold fineness grades used for hallmarking")
    ev = evaluate_compliance(gold_match, stage, REAL, ITEMS)
    check("a hallmarking standard in package inspection -> UNSUPPORTED REVIEW, no checks",
          ev.coverage_status == "UNSUPPORTED" and ev.overall_status == "REVIEW" and ev.checks == []
          and ev.reason_code == "DOMAIN_NOT_PACKAGE_LABEL", ev.reason)


# ------------------------------------------------------------ 12-14 regression


def test_regression() -> None:
    upload = PackageUpload((SAMPLES / "synth_packaged-water.png").read_bytes(), filename="water.png")
    water = InspectionAnalyzer(llm=None, product_finder=FINDER).analyze_package([upload])
    rule = next(c for c in water.compliance.checks if c.rule_id == "packaged-water-label-shows-is-number")
    names = {d.field: d for d in water.declaration_stage.fields}
    check("12 real water label: standard identified, product confirmed",
          water.product.standard_number == "IS 14543:2016"
          and water.compliance.coverage.product_applicability == "PRODUCT_CONFIRMED")
    check("12 real water label: IS-number check PASS, overall REVIEW (unchanged)",
          rule.result == "PASS" and water.compliance.overall_status == "REVIEW", rule.reason)
    check("12 real water label: 'AQUA SPRING' is no longer the product name",
          names["product_name"].value != "Aqua Spring", str(names["product_name"].value))
    check("12 real water label: OCR 'care@ clearflow.example' recovered with provenance",
          names["consumer_care"].value == "care@clearflow.example"
          and names["consumer_care"].extraction_method == "deterministic_normalization"
          and " " in names["consumer_care"].raw_text, str(names["consumer_care"]))

    client = TestClient(app)
    kettle_png = (SAMPLES / "synth_electric-kettle.png").read_bytes()
    multi = client.post(
        "/inspection/analyze",
        files=[("images", ("front.png", (SAMPLES / "synth_packaged-water.png").read_bytes(), "image/png")),
               ("images", ("back.png", kettle_png, "image/png"))],
        data={"sides": ["FRONT", "BACK"]},
    )
    j = multi.json()
    check("13 multi-side inspection still works", multi.status_code == 200 and len(j["images"]) == 2
          and {i["side"] for i in j["images"]} == {"FRONT", "BACK"}, str(multi.status_code))
    check("13 multi-side regions keep per-image ids",
          all(r["id"].startswith(("I1-", "I2-")) for img in j["images"] for r in img["ocr"]["regions"]))

    ev, _, _ = evaluate(WATER + ["IS 14543"])
    check("14 compliance engine: water PASS + unsupported areas -> REVIEW (unchanged)",
          ev.overall_status == "REVIEW" and ev.reason_code == "REQUIREMENTS_NOT_CHECKABLE"
          and ev.coverage_status == "INSPECTION_SUPPORTED")
    check("14 compliance engine: IS number not detected -> REVIEW (unchanged)",
          evaluate(WATER)[0].checks[0].reason_code == "EVIDENCE_NOT_DETECTED")
    body = client.post("/product-standard", json={"product": "packaged drinking water"}).json()
    check("Product -> Standard unchanged", body["results"][0]["standard_number"] == "IS 14543:2016")


def main() -> int:
    print("milestone 7 hardening: coverage classes, domains, OCR normalization, brand vs product")
    for fn in (test_standard_numbers, test_product_name, test_email, test_knowledge, test_regression):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
