"""Checks for the deterministic compliance engine (app/compliance.py) and the
verified requirement data (app/requirements.py, data/inspection_requirements.json).

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_compliance.py

Exit 0 = all checks passed, 1 = something failed.

Controlled OCR fixtures + the real knowledge base. No OCR engine, no network,
no LM Studio / OpenRouter.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import app.compliance as compliance_module  # noqa: E402
from app.compliance import AGGREGATION_POLICY, _aggregate, evaluate_compliance  # noqa: E402
from app.declarations import extract_declarations  # noqa: E402
from app.inspection import InspectionAnalyzer  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import RawRegion  # noqa: E402
from app.pipeline import run_downstream  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.product_identification import identify_product  # noqa: E402
from app.requirements import RULE_TYPES, load_requirements  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0

FINDER = ProductStandardFinder(SearchEngine())
ITEMS = FINDER.search_engine.items
KB = {i.id: i for i in ITEMS}
KB_NUMBERS = {i.standard_number for i in ITEMS if i.standard_number}
REAL = load_requirements(ITEMS)

WATER_QUOTE = "A consumer should therefore expect to see the ISI Mark with the IS number (IS 14543 or IS 13428) on the bottle."
MARK_QUOTE = "no person may manufacture or sell packaged drinking water or packaged natural mineral water in India except under the BIS Certification Mark"


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


def label(lines: list[tuple[str, float]]) -> list[Region]:
    out = []
    for n, (text, conf) in enumerate(lines, start=1):
        y = 10 + 50 * n
        h = 60 if n == 1 else 30
        out.append(Region(f"OCR-{n:03d}", text, conf, [10, y, 10 + 12 * len(text), y + h]))
    return out


def requirement_set(rows: list[dict]):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "req.json"
        path.write_text(json.dumps({"requirements": rows}), encoding="utf-8")
        return load_requirements(ITEMS, path)


def printed_rule(rid="water-is-number", applies=("IS 14543:2016",), pass_conf=0.8, fail_conf=0.9) -> dict:
    return {
        "id": rid, "applies_to": list(applies),
        "description": "The package shows the IS number of its Indian Standard.",
        "rule_type": "printed_standard_number", "declaration_field": "standard_number",
        "parameters": {"min_ocr_confidence_pass": pass_conf, "min_ocr_confidence_fail": fail_conf},
        "source_knowledge_id": "packaged-water-must-carry-bis-mark", "source_quote": WATER_QUOTE,
    }


def unsupported_rule(rid="water-mark") -> dict:
    return {
        "id": rid, "applies_to": ["IS 14543:2016"],
        "description": "Sold under the BIS Certification Mark.",
        "rule_type": "not_supported", "unsupported_reason": "A mark is a graphic.",
        "source_knowledge_id": "packaged-water-must-carry-bis-mark", "source_quote": MARK_QUOTE,
    }


SUPPORTED_ONLY = requirement_set([printed_rule()])


def evaluate(lines, requirements=REAL):
    regions = label(lines)
    stage = extract_declarations(regions)
    product = identify_product(stage, regions, FINDER)
    return evaluate_compliance(product, stage, requirements, ITEMS), product, stage, regions


def water(is_text: str | None, conf: float = 0.95):
    lines = [("AQUA PURE", 0.95), ("PACKAGED DRINKING WATER", 0.95), ("NET QUANTITY: 1 L", 0.95)]
    if is_text:
        lines.append((is_text, conf))
    return lines


def the_check(ev, rule_id="water-is-number"):
    return next(c for c in ev.checks if c.rule_id == rule_id)


# ---------------------------------------------------------------- 1-4. rule results

def test_rule_results() -> None:
    ev, product, _, _ = evaluate(water("IS 14543"), SUPPORTED_ONLY)
    c = the_check(ev)
    check("1 supported requirement + valid evidence -> PASS", c.result == "PASS", c.reason)
    check("1 PASS observed value is the declaration value", c.observed_value == "IS 14543")
    check("1 PASS evidence is SUFFICIENT", c.evidence_status == "SUFFICIENT")

    ev, product, _, _ = evaluate(water("IS 14534"), SUPPORTED_ONLY)
    c = the_check(ev)
    check("2 product still identified from label text", product.status == "MATCHED", product.reason)
    check("2 supported requirement + violating evidence -> FAIL", c.result == "FAIL", c.reason)
    check("2 FAIL has a machine-readable reason", c.reason_code == "OBSERVED_DIFFERENT")

    ev, _, _, _ = evaluate(water(None), SUPPORTED_ONLY)
    c = the_check(ev)
    check("3 missing evidence -> REVIEW", c.result == "REVIEW" and c.reason_code == "EVIDENCE_NOT_DETECTED", c.reason)
    check("3 not detected is not called missing", "not the same as missing" in c.reason)
    check("3 no observed value is invented", c.observed_value is None and c.evidence == [])

    ev, _, stage, _ = evaluate(water("IS 14543", conf=0.55), SUPPORTED_ONLY)
    c = the_check(ev)
    check("4 uncertain declaration -> REVIEW", c.result == "REVIEW" and c.reason_code == "EVIDENCE_UNCERTAIN", c.reason)

    ev, _, _, _ = evaluate(water("IS 14543", conf=0.7), SUPPORTED_ONLY)
    c = the_check(ev)
    check("4 correct number read below the pass threshold -> REVIEW, not PASS",
          c.result == "REVIEW" and c.reason_code == "EVIDENCE_LOW_CONFIDENCE", c.reason)
    ev, _, _, _ = evaluate(water("IS 14534", conf=0.85), SUPPORTED_ONLY)
    c = the_check(ev)
    check("4 wrong number read below the fail threshold -> REVIEW (possible misread), not FAIL",
          c.result == "REVIEW" and c.reason_code == "EVIDENCE_LOW_CONFIDENCE", c.reason)

    unreadable = [Region("OCR-001", "~~", 0.3, [0, 0, 5, 5])]
    stage = extract_declarations(unreadable)
    fake_matched = identify_product(extract_declarations(label(water("IS 14543"))), label(water("IS 14543")), FINDER)
    ev = evaluate_compliance(fake_matched, stage, SUPPORTED_ONLY, ITEMS)
    check("4 no reliable OCR text -> REVIEW", the_check(ev).reason_code == "NO_RELIABLE_TEXT")


# ------------------------------------------------------------- 5-9. coverage + aggregation

def test_coverage_and_aggregation() -> None:
    ev, product, _, _ = evaluate([("ROASTED MASALA CHANA", 0.95), ("(Roasted Bengal gram with spices)", 0.9)])
    check("5 standard identified", product.status == "MATCHED" and ev.standard_number == "IS 18140:2023")
    check("5 zero supported requirements -> overall REVIEW",
          ev.overall_status == "REVIEW" and ev.coverage_status == "STANDARD_ONLY" and ev.checks == [])
    check("5 reason says standard found but no deterministic coverage",
          "no supported deterministic inspection requirements" in ev.reason, ev.reason)

    only_unsupported = requirement_set([unsupported_rule()])
    ev, _, _, _ = evaluate(water("IS 14543"), only_unsupported)
    check("6 only not_supported requirements -> STANDARD_ONLY, REVIEW",
          ev.coverage_status == "STANDARD_ONLY" and ev.overall_status == "REVIEW")
    check("6 unsupported requirement is shown as NOT_SUPPORTED, never scored",
          [c.result for c in ev.checks] == ["NOT_SUPPORTED"] and ev.supported_checks == 0)

    ev, _, _, _ = evaluate(water("IS 14543"), REAL)
    check("6 real data: IS number PASS but unsupported areas keep overall REVIEW",
          ev.overall_status == "REVIEW" and ev.reason_code == "REQUIREMENTS_NOT_CHECKABLE", ev.reason)
    check("6 real data coverage counts", (ev.supported_checks, ev.passed, ev.not_supported) == (1, 1, 2),
          str((ev.supported_checks, ev.passed, ev.not_supported)))

    strict = printed_rule("strict-fail", fail_conf=1.0)
    two = requirement_set([printed_rule(), strict])
    ev, _, _, _ = evaluate(water("IS 14534", conf=0.95), two)
    check("7 one FAIL + one REVIEW -> overall FAIL",
          sorted(c.result for c in ev.checks) == ["FAIL", "REVIEW"] and ev.overall_status == "FAIL", ev.reason)

    strict_pass = printed_rule("strict-pass", pass_conf=0.9)
    two = requirement_set([printed_rule(), strict_pass])
    ev, _, _, _ = evaluate(water("IS 14543", conf=0.85), two)
    check("8 PASS + REVIEW, no FAIL -> overall REVIEW",
          sorted(c.result for c in ev.checks) == ["PASS", "REVIEW"] and ev.overall_status == "REVIEW", ev.reason)

    ev, _, _, _ = evaluate(water("IS 14543"), SUPPORTED_ONLY)
    check("9 all supported checks PASS, nothing unchecked -> overall PASS",
          ev.overall_status == "PASS" and ev.reason_code == "ALL_CHECKS_PASSED", ev.reason)

    zero = {"supported_checks": 0, "passed": 0, "failed": 0, "review": 0, "not_supported": 0}
    check("policy: SUPPORTED coverage with zero checks still REVIEW",
          _aggregate("IS X", "SUPPORTED_FOR_INSPECTION", zero)[0] == "REVIEW")
    check("policy: FAIL dominates REVIEW and unsupported",
          _aggregate("IS X", "SUPPORTED_FOR_INSPECTION",
                     {**zero, "supported_checks": 3, "failed": 1, "review": 1, "not_supported": 2})[0] == "FAIL")
    check("policy text is documented on every evaluation", ev.policy == AGGREGATION_POLICY and "PASS only when" in ev.policy)


# -------------------------------------------------------------- 10-11. traceability

def test_traceability() -> None:
    ev, _, stage, regions = evaluate(water("IS 14543"), REAL)
    c = the_check(ev, "packaged-water-label-shows-is-number")
    by_id = {r.id: r for r in regions}
    e = c.evidence[0]
    check("10 evidence -> declaration field", e.declaration_field == "standard_number" and e.declaration_status == "DETECTED")
    check("10 evidence -> OCR region that holds the text",
          e.source_regions == ["OCR-004"] and "IS 14543" in by_id["OCR-004"].text)
    check("10 evidence -> image + box + OCR confidence",
          e.image_id == "IMG-TEST" and e.bbox == by_id["OCR-004"].bbox and e.ocr_confidence == 0.95)

    s = c.source
    check("11 requirement -> verified BIS knowledge record",
          s.knowledge_id == "packaged-water-must-carry-bis-mark" and s.verification_status == "verified")
    check("11 requirement quote is word for word in that record", s.quote in KB[s.knowledge_id].content)
    check("11 requirement keeps source URL + verification date",
          s.source_url and s.source_url.startswith("https://") and s.last_verified)
    for other in ev.checks:
        check(f"11 {other.rule_id} keeps its verified source", other.source is not None and other.source.quote in KB[other.source.knowledge_id].content)


# ------------------------------------------------------------- 12-14. no fabrication

def test_no_fabrication() -> None:
    check("12 real requirement data loads with no errors", REAL.errors == (), str(REAL.errors))
    for r in REAL.requirements:
        check(f"12 {r.id} is grounded in a verified record",
              r.source_quote in KB[r.source_knowledge_id].content and KB[r.source_knowledge_id].verification_status == "verified")
        check(f"12 {r.id} applies only to KB standards", set(r.applies_to) <= KB_NUMBERS)
    check("12 every implementable rule type has an engine rule, and vice versa",
          set(RULE_TYPES) == set(compliance_module._RULES))

    bad = requirement_set([
        {**printed_rule("bad-quote"), "source_quote": "Packaged water must show net quantity in litres on the label."},
        {**printed_rule("bad-source"), "source_knowledge_id": "does-not-exist"},
        {**printed_rule("bad-standard"), "applies_to": ["IS 99999:2020"]},
        {**printed_rule("bad-rule"), "rule_type": "llm_judgement"},
        {**printed_rule("bad-field"), "declaration_field": "colour"},
        {**printed_rule("bad-param"), "parameters": {"min_ocr_confidence_pass": 7}},
        {**unsupported_rule("no-reason"), "unsupported_reason": ""},
        printed_rule("dup"), printed_rule("dup"),
    ])
    accepted = [r.id for r in bad.requirements]
    check("12 invented / ungrounded requirements are rejected", accepted == ["dup"], str(accepted))
    for fragment in ("does not appear word for word", "not in the knowledge base", "not a verified standard",
                     "is not implemented", "not a declaration field", "out of range", "unsupported_reason", "duplicate id"):
        check(f"12 rejection explains: {fragment}", any(fragment in e for e in bad.errors), str(bad.errors))

    ev, product, _, _ = evaluate([("GLIMMER SHINE DELUXE", 0.95), ("IS 14543", 0.95), ("MRP ₹299", 0.9)])
    check("13 no identified product -> no standard used, no checks",
          product.status == "REVIEW" and ev.standard_number is None and ev.checks == [] and ev.coverage_status == "NO_STANDARD")
    check("13 printed IS number alone never triggers compliance for a candidate", ev.overall_status == "REVIEW")

    for lines in (water("IS 14543"), water("IS 14534"), water(None), water("IS 14543", 0.55)):
        ev, _, stage, regions = evaluate(lines, REAL)
        text = " ".join(r.text for r in regions)
        for c in ev.checks:
            check(f"14 {c.rule_id} observed value comes from OCR ({lines[-1][0]})",
                  c.observed_value is None or c.observed_value.replace("IS ", "") in text.replace("IS ", ""),
                  str(c.observed_value))
        check(f"13 evaluated standard is the identified KB standard ({lines[-1][0]})", ev.standard_number in KB_NUMBERS)


# ------------------------------------------------------ 15-19. independence + compatibility

class DownLLM:
    def generate(self, **kwargs):
        raise LLMError("could not reach OpenRouter")


def test_independence_and_compatibility() -> None:
    import ast

    import app.requirements as requirements_module

    for module in (compliance_module, requirements_module):
        tree = ast.parse(Path(module.__file__).read_text())
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        check(f"15 {module.__name__} imports no model or network client",
              not imported & {"app.llm", "httpx", "requests", "openai"}, str(imported))
    res = run_downstream(label(water("IS 14543")), llm=DownLLM(), finder=FINDER, requirements=REAL)
    check("15 model unavailable -> compliance still evaluated",
          res.compliance.supported_checks == 1 and res.compliance.passed == 1, res.compliance.reason)

    led = label([("LED BULB 9W", 0.9), ("Self-ballasted LED lamp, Cool Daylight 6500K", 0.9), ("Net Quantity: 1 N", 0.9)])
    res = run_downstream(led, finder=FINDER, requirements=REAL)
    check("16 LED still matched through the canonical SearchEngine",
          res.product.status == "MATCHED" and res.product.standard_number == "IS 16102 (Part 1)")
    check("16 LED compliance is STANDARD_ONLY REVIEW (no verified requirements)",
          res.compliance.coverage_status == "STANDARD_ONLY" and res.compliance.overall_status == "REVIEW")
    check("16 'LED BULB 9W' alone still does not match (no invented alias)",
          run_downstream(label([("LED BULB 9W", 0.9), ("Net Quantity: 1 N", 0.9)]), finder=FINDER).product.status == "REVIEW")

    client = TestClient(app)
    body = client.post("/product-standard", json={"product": "packaged drinking water"}).json()
    check("17 /product-standard response shape unchanged",
          set(body) == {"product", "results", "grounded", "confidence", "note"} and body["results"][0]["standard_number"] == "IS 14543:2016")

    def stub(arr):
        return [RawRegion("PACKAGED DRINKING WATER", 0.95, (10, 10, 400, 60), [[10, 10], [400, 10], [400, 60], [10, 60]]),
                RawRegion("IS 14543", 0.95, (10, 80, 200, 110), [[10, 80], [200, 80], [200, 110], [10, 110]])], 0.01
    buf = io.BytesIO()
    Image.new("RGB", (500, 200), "white").save(buf, format="PNG")
    analyzer = InspectionAnalyzer(ocr_engine=stub, product_finder=FINDER)
    instant = analyzer.ocr(buf.getvalue(), "w.png")
    check("18 Instant OCR still returns regions + declarations, no compliance",
          instant.ocr.region_count == 2 and not hasattr(instant, "compliance"))
    stds = {f.field: f for f in instant.declaration_stage.fields}
    check("19 declaration extraction still reads the IS number", stds["standard_number"].value == "IS 14543")
    full = analyzer.analyze(buf.getvalue(), "w.png")
    check("analyze response carries the compliance evaluation",
          full.compliance.standard_number == "IS 14543:2016" and full.pipeline.compliance == full.compliance.overall_status)
    check("analyze compliance check links to the stubbed OCR region",
          any(e.source_regions == ["OCR-002"] for c in full.compliance.checks for e in c.evidence))


def main() -> int:
    print("deterministic compliance engine")
    for fn in (
        test_rule_results,
        test_coverage_and_aggregation,
        test_traceability,
        test_no_fabrication,
        test_independence_and_compatibility,
    ):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
