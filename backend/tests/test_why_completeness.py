"""Checks for deterministic "why did this pass / fail / need review?" explanations
(app/compliance.py) and declaration completeness (app/completeness.py).

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_why_completeness.py

Exit 0 = all checks passed, 1 = something failed.

Controlled OCR stand-ins + the real knowledge base and requirement data.
No OCR model, network, LM Studio / OpenRouter.
"""

from __future__ import annotations

import dataclasses
import io
import json
import re
import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.completeness import declaration_completeness  # noqa: E402
from app.compliance import REASON_CATEGORIES, evaluate_compliance  # noqa: E402
from app.declarations import extract_declarations  # noqa: E402
from app.inspection import InspectionAnalyzer, PackageUpload  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import OcrError, RawRegion  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.product_identification import identify_product  # noqa: E402
from app.requirements import load_requirements  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0
FINDER = ProductStandardFinder(SearchEngine())
ITEMS = FINDER.search_engine.items
KB = {i.id: i for i in ITEMS}
REAL = load_requirements(ITEMS)
WATER_QUOTE = "A consumer should therefore expect to see the ISI Mark with the IS number (IS 14543 or IS 13428) on the bottle."
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


def requirement_set(rows):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "req.json"
        path.write_text(json.dumps({"requirements": rows}), encoding="utf-8")
        return load_requirements(ITEMS, path)


def printed_rule(rid="water-is-number", pass_conf=0.8, fail_conf=0.9):
    return {"id": rid, "applies_to": ["IS 14543:2016"], "description": "The package shows the IS number of its standard.",
            "rule_type": "printed_standard_number", "declaration_field": "standard_number",
            "parameters": {"min_ocr_confidence_pass": pass_conf, "min_ocr_confidence_fail": fail_conf},
            "source_knowledge_id": "packaged-water-must-carry-bis-mark", "source_quote": WATER_QUOTE}


SUPPORTED_ONLY = requirement_set([printed_rule()])
F, B, L, R = 601, 602, 603, 604


def evaluate(texts, requirements=REAL, conf=0.95, unreadable=()):
    raw = lines(*texts, conf=conf)
    regions = [dataclasses.make_dataclass("Rg", ["id", "text", "confidence", "bbox", "image_id", "side"])(
        f"OCR-{i:03d}", r.text, r.confidence, list(r.bbox), "IMG-T", "BACK") for i, r in enumerate(raw, 1)]
    stage = extract_declarations(regions)
    product = identify_product(stage, regions, FINDER)
    return evaluate_compliance(product, stage, requirements, ITEMS, unreadable), stage, product


def the(ev, rid="water-is-number"):
    return next(c for c in ev.checks if c.rule_id == rid)


WATER = ["AQUA PURE", "PACKAGED DRINKING WATER", "NET QUANTITY: 1 L"]


# ------------------------------------------------------------------ 1-6. WHY

def test_why() -> None:
    ev, _, _ = evaluate(WATER + ["IS 14543"], SUPPORTED_ONLY)
    c = the(ev)
    check("1 PASS has a deterministic reason", c.result == "PASS" and c.reason_code == "OBSERVED_MATCHES"
          and c.reason_category == "REQUIREMENT_SATISFIED" and "IS 14543" in c.reason, c.reason)
    check("1 PASS names the evidence it used", c.observed_value == "IS 14543" and c.evidence_status == "SUFFICIENT")

    ev, _, _ = evaluate(WATER + ["IS 14534"], SUPPORTED_ONLY)
    c = the(ev)
    check("2 FAIL has a deterministic reason", c.result == "FAIL" and c.reason_code == "OBSERVED_DIFFERENT"
          and c.reason_category == "REQUIREMENT_NOT_SATISFIED" and "IS 14534" in c.reason and "IS 14543" in c.reason, c.reason)

    for texts, conf, code, category in (
        (WATER, 0.95, "EVIDENCE_NOT_DETECTED", "EVIDENCE_NOT_DETECTED"),
        (WATER + ["IS 14543"], [0.95, 0.95, 0.95, 0.7], "EVIDENCE_LOW_CONFIDENCE", "INSUFFICIENT_EVIDENCE"),
        (WATER + ["IS 14543"], [0.95, 0.95, 0.95, 0.55], "EVIDENCE_UNCERTAIN", "INSUFFICIENT_EVIDENCE"),
    ):
        ev, _, _ = evaluate(texts, SUPPORTED_ONLY, conf=conf)
        c = the(ev)
        check(f"3 REVIEW has a deterministic reason ({code})",
              c.result == "REVIEW" and c.reason_code == code and c.reason_category == category and c.reason, c.reason)
        check(f"3 REVIEW reason never guesses ({code})", not FORBIDDEN.search(c.reason), c.reason)

    loose = requirement_set([printed_rule(pass_conf=0.65, fail_conf=0.75)])
    ev, _, _ = evaluate(WATER + ["IS 14543"], loose, conf=[0.95, 0.95, 0.95, 0.7])
    c = the(ev)
    check("4 rule_condition states the rule's actual thresholds from the requirement data",
          "IS 14543" in c.rule_condition and "65%" in c.rule_condition and "75%" in c.rule_condition, c.rule_condition)
    check("4 the same evidence passes under that rule (reason follows the rule, not a template)",
          c.result == "PASS" and "70%" in c.reason, c.reason)
    ev, _, _ = evaluate(WATER + ["IS 14543"], REAL, conf=[0.95, 0.95, 0.95, 0.7])
    for c in ev.checks:
        check(f"4 {c.rule_id}: category is the fixed mapping of its code",
              REASON_CATEGORIES[c.reason_code] == c.reason_category)
        consistent = {"PASS": {"REQUIREMENT_SATISFIED"}, "FAIL": {"REQUIREMENT_NOT_SATISFIED"},
                      "NOT_SUPPORTED": {"NOT_SUPPORTED"}}.get(c.result)
        check(f"4 {c.rule_id}: result and reason agree",
              c.reason_category in consistent if consistent else c.reason_category not in
              {"REQUIREMENT_SATISFIED", "REQUIREMENT_NOT_SATISFIED", "NOT_SUPPORTED"})

    res = package({F: lines(*WATER), B: lines("IS 14543", big_first=False)}, [(F, "FRONT"), (B, "BACK")])
    chk = next(c for c in res.compliance.checks if c.rule_id == "packaged-water-label-shows-is-number")
    e = chk.evidence[0]
    region = next(r for r in res.ocr.regions if r.id == e.source_regions[0])
    check("5 package evidence: side + region + image + source text + OCR confidence",
          e.source_sides == ["BACK"] and region.image_id == e.image_id == res.images[1].image_id
          and e.raw_text == "IS 14543" and e.ocr_confidence == 0.95)
    s = chk.source
    check("6 requirement evidence: verified BIS record, word-for-word quote, URL, date",
          s.verification_status == "verified" and s.quote in KB[s.knowledge_id].content
          and s.source_url.startswith("https://") and s.last_verified)
    ns = next(c for c in res.compliance.checks if c.result == "NOT_SUPPORTED")
    check("6 unsupported requirement explains itself and still cites its source",
          ns.reason_category == "NOT_SUPPORTED" and ns.reason and ns.source is not None and ns.evidence == [])


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

    check("10 no verified requirement for chana fields -> NOT_ESTABLISHED everywhere",
          all(i.requirement_coverage == "NOT_ESTABLISHED" for i in res.completeness.items))
    water = package({F: lines(*WATER), B: lines("IS 14543", big_first=False)}, [(F, "FRONT"), (B, "BACK")])
    cov = {i.field: i.requirement_coverage for i in water.completeness.items}
    check("10/16 only the field used by a verified requirement is VERIFIED_REQUIREMENT",
          [f for f, c in cov.items() if c == "VERIFIED_REQUIREMENT"] == ["standard_number"], str(cov))
    check("16 VERIFIED_REQUIREMENT names the real requirement id",
          next(i for i in water.completeness.items if i.field == "standard_number").requirement_ids
          == ["packaged-water-label-shows-is-number"])
    grounded = {r.declaration_field for r in REAL.requirements if r.supported}
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
    chk = next(c for c in failed.compliance.checks if c.rule_id == "packaged-water-label-shows-is-number")
    check("14 OCR failure on BACK -> check is undeterminable, not 'missing'",
          chk.result == "REVIEW" and chk.reason_code == "EVIDENCE_NOT_DETECTED_UNREADABLE_IMAGES"
          and chk.reason_category == "EVIDENCE_NOT_DETERMINABLE" and "BACK (image 2)" in chk.reason, chk.reason)
    std = next(i for i in failed.completeness.items if i.field == "standard_number")
    check("14 completeness says the failed photo cannot be determined",
          std.status == "NOT_DETECTED" and "BACK (image 2)" in std.statement and "cannot be determined" in std.statement, std.statement)
    check("14 overall summary mentions the unreadable photo",
          any("BACK (image 2)" in line and "cannot be determined" in line for line in failed.compliance.summary))
    check("14 nothing says missing / absent", not any(FORBIDDEN.search(t) for t in
          [chk.reason, std.statement, *failed.compliance.summary]))

    regions = lines(*WATER, "IS 14543")
    rg = [dataclasses.make_dataclass("Rg", ["id", "text", "confidence", "bbox", "image_id", "side"])(
        f"OCR-{i:03d}", r.text, r.confidence, list(r.bbox), "IMG-T", "BACK") for i, r in enumerate(regions, 1)]
    stage = extract_declarations(rg)
    conflicted = dataclasses.replace(stage, fields=[
        dataclasses.replace(f, status="UNCERTAIN", consistency="CONFLICT", value=None,
                            reason="Different values found on the package: IS 14543 (FRONT); IS 13428 (BACK).")
        if f.field == "standard_number" else f for f in stage.fields])
    ev = evaluate_compliance(identify_product(stage, rg, FINDER), conflicted, SUPPORTED_ONLY, ITEMS)
    c = the(ev)
    check("13 conflicting declaration propagates to compliance as REVIEW / CONFLICTING_EVIDENCE",
          c.result == "REVIEW" and c.reason_code == "EVIDENCE_CONFLICT" and c.reason_category == "CONFLICTING_EVIDENCE"
          and c.observed_value is None and ev.overall_status == "REVIEW", c.reason)


# ------------------------------------------------------------- 17-19. OVERALL

def test_overall_summary() -> None:
    fail, _, _ = evaluate(WATER + ["IS 14534"], SUPPORTED_ONLY)
    check("17 overall FAIL summary", fail.overall_status == "FAIL"
          and "1 supported check failed." in fail.summary and "0 supported checks passed." in fail.summary, str(fail.summary))
    review, _, _ = evaluate(WATER, REAL)
    check("18 overall REVIEW summary", review.overall_status == "REVIEW"
          and "1 supported check needs review." in review.summary
          and "2 requirement areas cannot be checked from a package image." in review.summary, str(review.summary))
    ok, _, _ = evaluate(WATER + ["IS 14543"], SUPPORTED_ONLY)
    check("19 overall PASS summary", ok.overall_status == "PASS"
          and "1 supported check passed." in ok.summary and "0 supported checks failed." in ok.summary, str(ok.summary))
    check("summary starts with the overall reason and has no score", ok.summary[0] == ok.reason
          and not any(re.search(r"\d+%", line) for line in ok.summary))
    led, _, _ = evaluate(["LED BULB 9W", "Self-ballasted LED lamp, Cool Daylight 6500K"], REAL)
    check("standard-only summary explains missing coverage", led.overall_status == "REVIEW"
          and "no supported deterministic inspection requirements" in led.summary[0], str(led.summary))


# -------------------------------------------------------------- 20-25. REGRESSION

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
    check("24 compliance still works", full.compliance.coverage.supported_checks == 1 and full.pipeline.compliance == "REVIEW")
    check("25 multi-side still works", full.package.sides_uploaded == ["FRONT", "BACK"] and len(full.images) == 2)
    single = analyzer.analyze(png(F), "front.png")
    check("25 single image still works with completeness", single.ocr.regions[0].id == "OCR-001" and single.completeness.items)
    body = TestClient(app).post("/product-standard", json={"product": "packaged drinking water"}).json()
    check("23 Product -> Standard unchanged", set(body) == {"product", "results", "grounded", "confidence", "note"}
          and body["results"][0]["standard_number"] == "IS 14543:2016" and body["results"][0]["why"]["summary"])
    retrieval_why = full.standards[0].why
    check("retrieval 'why this result' stays separate from compliance reasons",
          retrieval_why.summary.startswith("Retrieved as a candidate standard")
          and all(not c.reason.startswith("Retrieved") for c in full.compliance.checks))


def main() -> int:
    print("why did this pass / fail / need review + declaration completeness")
    for fn in (test_why, test_completeness, test_overall_summary, test_regression):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
