"""Checks for Milestone 8 — verified Legal Metrology package-label requirements.

Numbered to the milestone's test cases:

   1  valid MRP -> PASS                         10  wrong applicability -> rule not applied
   2  missing / uncertain MRP -> REVIEW          11  BIS requirement still works
   3  malformed MRP -> REVIEW, never a value     12  Legal Metrology source shown correctly
   4  "500 g" -> PASS                            13  hallmarking never leaks into package labels
   5  "500" (no unit) -> REVIEW                  14  OCR normalization preserved
   6  valid month and year -> PASS               15  multi-side evidence preserved
   7  ambiguous date -> REVIEW                   16  packaged-water IS-number rule unchanged
   8  manufacturer / packer evidence             17  STANDARD_ONLY standards stay STANDARD_ONLY
   9  consumer-care contact evidence

plus: source provenance, loader rejections, coverage report, HTTP contract.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_legal_metrology.py

Exit 0 = all checks passed, 1 = something failed.

Controlled OCR fixtures + the real knowledge base and requirement data, plus the
real local OCR engine on one synthetic sample label. No LM Studio / OpenRouter.
"""

from __future__ import annotations

import copy
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

from app.compliance import evaluate_compliance  # noqa: E402
from app.declarations import extract_declarations  # noqa: E402
from app.inspection import InspectionAnalyzer, PackageUpload  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import RawRegion  # noqa: E402
from app.package_label import evaluate_package_label  # noqa: E402
from app.pipeline import run_downstream  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.product_identification import identify_product  # noqa: E402
from app.requirements import coverage_by_standard, coverage_totals, load_requirements  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0
FINDER = ProductStandardFinder(SearchEngine())
ITEMS = FINDER.search_engine.items
KB = {i.id: i for i in ITEMS}
REAL = load_requirements(ITEMS)
REQ_PATH = Path(__file__).resolve().parents[2] / "data" / "inspection_requirements.json"
SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "ocr-labels"
FORBIDDEN = re.compile(r"legally missing|violat|illegal|non-?compliant|offen[cs]e", re.IGNORECASE)

Region = dataclasses.make_dataclass("Region", ["id", "text", "confidence", "bbox", "image_id", "side"])

KETTLE = ["ELECTRIC KETTLE", "Product name: Electric Kettle"]
FULL_LABEL = KETTLE + [
    "MRP ₹80.00 (Inclusive of all taxes)",
    "Net Quantity: 500 g",
    "Mfg. Date: 05/2024",
    "Manufactured by: Thermopot Appliances Pvt Ltd",
    "Address: Plot 12, Baddi Industrial Area, Solan 173205, Himachal Pradesh",
    "Consumer care: 1800-300-7788",
    "Email: care@thermopot.example",
]
WATER = ["AQUA PURE", "PACKAGED DRINKING WATER", "NET QUANTITY: 1 L"]


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def regions(texts, conf=0.95, image_id="IMG-T", side="BACK", start=1):
    out = []
    for i, t in enumerate(texts, start):
        c = conf[i - start] if isinstance(conf, (list, tuple)) else conf
        h = 60 if i == start else 30
        out.append(Region(f"OCR-{i:03d}", t, c, [10, 20 + 45 * i, 10 + 10 * len(t), 20 + 45 * i + h], image_id, side))
    return out


def label_eval(texts, conf=0.95, requirements=REAL, unreadable=()):
    regs = regions(texts, conf)
    stage = extract_declarations(regs)
    return evaluate_package_label(stage, regs, requirements, ITEMS, unreadable)


def the(ev, rid):
    return next(c for c in ev.checks if c.rule_id == rid)


MRP, QTY, MFR, NAME, DATE, CONTACT = (
    "lm-retail-sale-price-declared", "lm-net-quantity-declared", "lm-manufacturer-name-and-address",
    "lm-common-or-generic-name", "lm-month-and-year-of-manufacture", "lm-consumer-complaint-phone-and-email",
)


def requirement_set(mutate):
    """The real requirement data with ``mutate(raw)`` applied, loaded from a temp file."""
    raw = json.loads(REQ_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "req.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return load_requirements(ITEMS, path)


def lm_row(rid):
    raw = json.loads(REQ_PATH.read_text(encoding="utf-8"))
    return copy.deepcopy(next(r for r in raw["requirements"] if r["id"] == rid))


# ---------------------------------------------------------------- sources


def test_sources() -> None:
    print("\nsources and provenance")
    lm_items = [i for i in ITEMS if i.category == "legal_metrology"]
    check("Legal Metrology records exist in the same knowledge base", len(lm_items) >= 5, str(len(lm_items)))
    for i in lm_items:
        check(f"{i.id}: LEGAL_METROLOGY, verified, official DoCA URL, document + reference + date",
              i.source_authority == "LEGAL_METROLOGY" and i.verification_status == "verified"
              and (i.source_url or "").startswith("https://consumeraffairs.gov.in/")
              and bool(i.document_name) and bool(i.reference) and i.last_verified is not None)
    check("every other record stays BIS", all(i.source_authority == "BIS" for i in ITEMS if i.category != "legal_metrology"))

    check("requirement data loads with no errors", not REAL.errors, str(REAL.errors))
    lm = REAL.for_package()
    check("Legal Metrology requirements are loaded", len(lm) >= 6, str(len(lm)))
    for r in lm:
        quotes = [(r.source_knowledge_id, r.source_quote)] + [(q.knowledge_id, q.quote) for q in r.supporting_sources]
        quotes += [(q.knowledge_id, q.quote) for e in r.exclusions for q in e.sources]
        check(f"{r.id}: domain PACKAGE_LABEL, source LEGAL_METROLOGY, rule reference",
              r.domain == "PACKAGE_LABEL" and r.source_category == "LEGAL_METROLOGY" and r.reference.startswith("Rule"))
        check(f"{r.id}: every quote is word for word in a verified Legal Metrology record",
              all(q in KB[k].content and KB[k].source_authority == "LEGAL_METROLOGY"
                  and KB[k].verification_status == "verified" for k, q in quotes))
        check(f"{r.id}: not tied to a BIS standard or product", not r.applies_to and not r.applies_to_products)

    checkable = sorted(r.id for r in lm if r.supported)
    check("exactly the six verified checkable rules (no inflated rule count)",
          checkable == sorted([MRP, QTY, MFR, NAME, DATE, CONTACT]), str(checkable))
    for r in lm:
        if not r.supported:
            check(f"{r.id}: uncheckable requirement states why", len(r.unsupported_reason) > 40)

    scope = REAL.package_scope
    check("package scope (Rule 3) quotes a Legal Metrology record",
          scope is not None and scope.source.quote in KB[scope.source.knowledge_id].content)
    check("scope exclusions are the two observable ones",
          scope is not None and {e.id for e in scope.exclusions}
          == {"NET_QUANTITY_ABOVE_25_KG_OR_25_L", "NOT_FOR_RETAIL_SALE_DECLARED"})
    check("unobservable applicability is stated as assumptions", scope is not None and len(scope.assumptions) >= 3)

    engine = FINDER.search_engine
    hits = engine.search("legal metrology packaged commodities rules retail sale price")
    check("BIS search never returns Legal Metrology records",
          all(KB[h.item.id].source_authority == "BIS" for h in hits.results))


def test_loader_rejections() -> None:
    print("\nloader rejects unsafe requirement data")

    def add(row):
        return requirement_set(lambda raw: raw["requirements"].append(row))

    bad = lm_row(MRP)
    bad["id"] = "lm-bad-quote"
    bad["source_quote"] = "Every package shall show the MRP in bold red letters."
    check("invented quote is rejected", any("lm-bad-quote" in e for e in add(bad).errors))

    bis_src = lm_row(NAME)
    bis_src["id"] = "lm-bis-source"
    bis_src["source_knowledge_id"] = "packaged-water-must-carry-bis-mark"
    bis_src["source_quote"] = "A consumer should therefore expect to see the ISI Mark with the IS number (IS 14543 or IS 13428) on the bottle."
    rs = add(bis_src)
    check("a PACKAGED_COMMODITY requirement quoting a BIS record is rejected",
          any("lm-bis-source" in e and "LEGAL_METROLOGY" in e for e in rs.errors), str(rs.errors))

    std_lm = lm_row(NAME)
    std_lm.update(id="bis-quoting-lm", scope="STANDARD", applies_to=["IS 14543:2016"])
    rs = add(std_lm)
    check("a BIS STANDARD requirement quoting a Legal Metrology record is rejected",
          any("bis-quoting-lm" in e and "BIS" in e for e in rs.errors), str(rs.errors))

    tied = lm_row(NAME)
    tied.update(id="lm-tied", applies_to=["IS 14543:2016"])
    check("a Legal Metrology requirement tied to a BIS standard is rejected",
          any("lm-tied" in e for e in add(tied).errors))

    fmt = lm_row(QTY)
    fmt.update(id="lm-made-up-format", format="net_quantity_in_imperial_units")
    check("an unimplemented format is rejected", any("lm-made-up-format" in e for e in add(fmt).errors))

    excl = lm_row(MFR)
    excl["id"] = "lm-made-up-exclusion"
    excl["exclusions"][0]["id"] = "LOOKS_EXPENSIVE"
    check("an unimplemented exclusion is rejected", any("lm-made-up-exclusion" in e for e in add(excl).errors))

    hallmark = lm_row(NAME)
    hallmark.update(id="lm-hallmark", source_knowledge_id="hallmark-components-since-huid",
                    source_quote="hallmark consists of 3 marks viz, BIS logo, purity of the article in caratage as "
                                 "well as fineness and six-digit alphanumeric HUID number.")
    rs = add(hallmark)
    check("13 a package-label requirement using hallmarking evidence is rejected",
          any("lm-hallmark" in e for e in rs.errors) and all(r.id != "lm-hallmark" for r in rs.requirements),
          str([e for e in rs.errors if "lm-hallmark" in e]))

    no_scope = requirement_set(lambda raw: raw.pop("package_scope"))
    check("without a valid package scope no Legal Metrology requirement is loaded",
          not no_scope.for_package() and any("package_scope" in e for e in no_scope.errors))
    ev = label_eval(FULL_LABEL, requirements=no_scope)
    check("... and the package-label result is REVIEW, not PASS", ev.overall_status == "REVIEW" and not ev.checks)


# ---------------------------------------------------------------- rules


def test_mrp() -> None:
    print("\nMRP — Rule 6(1)(e)")
    ev = label_eval(FULL_LABEL)
    c = the(ev, MRP)
    check("1 valid MRP inclusive of all taxes -> PASS", c.result == "PASS" and c.observed_value == "₹80.00", c.reason)
    check("1 PASS carries OCR evidence (region, box, image, confidence)",
          c.evidence and c.evidence[0].source_regions == ["OCR-003"] and c.evidence[0].bbox
          and c.evidence[0].image_id == "IMG-T" and c.evidence[0].ocr_confidence == 0.95)

    c = the(label_eval(KETTLE), MRP)
    check("2 MRP not detected -> REVIEW, never FAIL", c.result == "REVIEW" and c.reason_code == "EVIDENCE_NOT_DETECTED")
    check("2 not detected is not called missing", not FORBIDDEN.search(c.reason), c.reason)
    c = the(label_eval(KETTLE + ["MRP ₹80.00"]), MRP)
    check("2 MRP without 'inclusive of all taxes' -> REVIEW", c.result == "REVIEW" and c.reason_code == "VALUE_FORMAT_UNCONFIRMED")
    c = the(label_eval(KETTLE + ["MRP ₹80.00 (Inclusive of all taxes)"], conf=0.7), MRP)
    check("2 low-confidence MRP -> REVIEW", c.result == "REVIEW" and c.reason_code == "EVIDENCE_LOW_CONFIDENCE")

    c = the(label_eval(KETTLE + ["MRP: Rs. 8O (Incl. of all taxes)"]), MRP)
    check("3 malformed MRP 'Rs. 8O' -> REVIEW with its evidence, no invented value",
          c.result == "REVIEW" and c.reason_code == "EVIDENCE_UNCERTAIN" and c.observed_value is None
          and c.evidence and c.evidence[0].source_regions == ["OCR-003"], f"{c.reason_code} {c.observed_value}")
    c = the(label_eval(KETTLE + ["MRP US$ 4.99"]), MRP)
    check("3 MRP in a foreign currency -> REVIEW (affixed label may exist, Rule 6(9)), not FAIL",
          c.result == "REVIEW" and c.reason_code == "VALUE_FORMAT_UNCONFIRMED" and "6(9)" in c.reason, c.reason)
    check("MRP rule never FAILs", "Never FAIL" in c.rule_condition)


def test_net_quantity() -> None:
    print("\nNet quantity — Rule 6(1)(c), Rule 13")
    c = the(label_eval(FULL_LABEL), QTY)
    check("4 'Net Quantity: 500 g' -> PASS", c.result == "PASS" and c.observed_value == "500 g", c.reason)
    for text, want in (("Net Vol: 1 L", "1 L"), ("Net Wt. 2 kg", "2 kg")):
        c = the(label_eval(KETTLE + [text]), QTY)
        check(f"4 '{text}' -> PASS", c.result == "PASS" and c.observed_value == want, f"{c.result} {c.observed_value}")

    c = the(label_eval(KETTLE + ["Net Quantity: 500"]), QTY)
    check("5 'Net Quantity: 500' (no unit) -> REVIEW", c.result == "REVIEW" and c.reason_code == "EVIDENCE_UNCERTAIN", c.reason_code)
    c = the(label_eval(KETTLE + ["Net Quantity: 16 oz"]), QTY)
    check("5 non-SI unit '16 oz' -> REVIEW, not FAIL", c.result == "REVIEW" and c.reason_code == "VALUE_FORMAT_UNCONFIRMED")

    c = the(label_eval(KETTLE + ["Net Quantity: 1 dozen"]), QTY)
    check("dozen on the package (prohibited by Rule 13(4)) -> FAIL on clear evidence",
          c.result == "FAIL" and c.reason_code == "VALUE_FORMAT_INVALID" and "13(4)" in c.reason, c.reason)
    check("FAIL carries evidence and the verified source",
          c.evidence and c.evidence[0].source_regions and c.source and "dozen" in " ".join(s.quote for s in c.supporting_sources))
    c = the(label_eval(KETTLE + ["Net Quantity: 1 dozen"], conf=0.85), QTY)
    check("dozen read below the fail threshold -> REVIEW", c.result == "REVIEW")


def test_date() -> None:
    print("\nMonth and year of manufacture — Rule 6(1)(d)")
    for text in ("Mfg. Date: 05/2024", "Mfg. Date: May 2024", "Mfg. Date: 12/05/2024"):
        c = the(label_eval(KETTLE + [text]), DATE)
        check(f"6 '{text}' -> PASS", c.result == "PASS" and c.reason_code == "DATE_FORMAT_VALID", c.reason)
    c = the(label_eval(KETTLE + ["Mfg. Date: 11/12"]), DATE)
    check("7 ambiguous '11/12' -> REVIEW", c.result == "REVIEW" and c.reason_code == "DATE_FORMAT_UNCONFIRMED", c.reason)
    c = the(label_eval(KETTLE + ["Pkd. Date: 05/2024"]), DATE)
    check("7 packing date only -> REVIEW (2021 amendment asks for manufacture)",
          c.result == "REVIEW" and c.reason_code == "DATE_NOT_MANUFACTURE", c.reason_code)
    c = the(label_eval(KETTLE + ["Mfg. Date: 05/2024"], conf=0.7), DATE)
    check("7 low-confidence date -> REVIEW", c.result == "REVIEW")
    check("date rule never FAILs", "Never FAIL" in c.rule_condition)


def test_manufacturer_and_contact() -> None:
    print("\nManufacturer / packer — Rule 6(1)(a); consumer complaints — Rule 6(2)")
    ev = label_eval(FULL_LABEL)
    c = the(ev, MFR)
    check("8 manufacturer name + address on the same photo -> PASS",
          c.result == "PASS" and len(c.evidence) == 2 and "Thermopot" in (c.observed_value or ""), c.reason)
    check("8 observed value is not double-labelled", "Address: Address:" not in (c.observed_value or ""), c.observed_value)
    c = the(label_eval(KETTLE + ["Manufactured by: Thermopot Appliances Pvt Ltd"]), MFR)
    check("8 name without an address -> REVIEW", c.result == "REVIEW" and c.reason_code == "EVIDENCE_NOT_DETECTED")
    c = the(label_eval(KETTLE + ["Imported by: Globex Trading Pvt Ltd",
                                 "Address: 4 Marine Drive, Mumbai 400002, Maharashtra"]), MFR)
    check("8 importer name + address satisfies the name group", c.result == "PASS", c.reason)

    c = the(ev, CONTACT)
    check("9 consumer-care phone + email -> PASS", c.result == "PASS" and len(c.evidence) == 2, c.reason)
    c = the(label_eval(KETTLE + ["Consumer care: 1800-300-7788"]), CONTACT)
    check("9 phone without e-mail -> REVIEW, not FAIL", c.result == "REVIEW")
    name_addr = the(ev, "lm-consumer-complaint-name-and-address")
    check("9 complaint name/address is shown as not checkable, never scored",
          name_addr.result == "NOT_SUPPORTED" and name_addr.source_category == "LEGAL_METROLOGY")

    check("field_present never FAILs", all(c.result != "FAIL" for c in label_eval(KETTLE).checks))


def test_applicability() -> None:
    print("\napplicability")
    ev = label_eval(KETTLE + ["FSSAI Lic. No. 10012345000123", "Net Quantity: 500 g"])
    for rid in (MFR, DATE):
        c = the(ev, rid)
        check(f"10 food article (FSSAI licence read) -> {rid} NOT_APPLICABLE with the licence as evidence",
              c.result == "NOT_APPLICABLE" and c.evidence and "FSSAI" in (c.observed_value or ""), c.result)
    check("10 other requirements still apply to a food package", the(ev, QTY).result == "PASS")
    ev_low = label_eval(KETTLE + ["FSSAI Lic. No. 10012345000123"], conf=[0.95, 0.95, 0.6])
    check("10 an unclear FSSAI reading does not switch a requirement off", the(ev_low, MFR).result == "REVIEW")

    ev = label_eval(KETTLE + ["Net Quantity: 30 kg", "MRP ₹900 (Inclusive of all taxes)"])
    check("10 net quantity above 25 kg -> outside Chapter II, nothing applied, REVIEW",
          ev.scope_status == "OUT_OF_SCOPE" and ev.overall_status == "REVIEW"
          and all(c.result == "NOT_APPLICABLE" for c in ev.checks) and ev.exclusions_found[0].evidence)
    ev = label_eval(KETTLE + ["Net Quantity: 25 kg"])
    check("10 exactly 25 kg is still in scope", ev.scope_status == "IN_SCOPE")
    ev = label_eval(KETTLE + ["NOT FOR RETAIL SALE", "Net Quantity: 5 kg"])
    check("10 'not for retail sale' -> outside Chapter II, REVIEW",
          ev.scope_status == "OUT_OF_SCOPE" and ev.exclusions_found[0].id == "NOT_FOR_RETAIL_SALE_DECLARED"
          and ev.exclusions_found[0].evidence[0].source_regions == ["OCR-003"])
    ev = label_eval(FULL_LABEL)
    check("assumptions are stated with every result", ev.assumptions and any("retail" in a for a in ev.assumptions))

    check("overall: all checkable passed but some areas uncheckable -> REVIEW, not PASS",
          ev.overall_status == "REVIEW" and ev.reason_code == "REQUIREMENTS_NOT_CHECKABLE" and ev.passed == 6)
    only_checkable = requirement_set(lambda raw: raw.update(requirements=[
        r for r in raw["requirements"] if r.get("scope") != "PACKAGED_COMMODITY" or r["rule_type"] != "not_supported"]))
    ev = label_eval(FULL_LABEL, requirements=only_checkable)
    check("overall PASS only when every applicable requirement was checked and passed",
          ev.overall_status == "PASS" and ev.reason_code == "ALL_CHECKS_PASSED", ev.reason)
    ev = label_eval(KETTLE + ["Net Quantity: 1 dozen"])
    check("overall FAIL when a check fails on clear evidence", ev.overall_status == "FAIL")
    ev = label_eval(["~~", "..."], conf=0.2)
    check("no reliable text -> every checkable rule REVIEW",
          all(c.result in ("REVIEW", "NOT_SUPPORTED") for c in ev.checks) and ev.overall_status == "REVIEW")


# ---------------------------------------------------------------- separation + regressions


def bis_eval(texts):
    regs = regions(texts)
    stage = extract_declarations(regs)
    product = identify_product(stage, regs, FINDER)
    return evaluate_compliance(product, stage, REAL, ITEMS)


def test_bis_separation() -> None:
    print("\nBIS and Legal Metrology stay separate")
    bis = bis_eval(WATER + ["IS 14543", "MRP ₹20.00 (Inclusive of all taxes)"])
    printed = next(c for c in bis.checks if c.rule_id == "packaged-water-label-shows-is-number")
    check("11/16 packaged-water IS-number rule still PASSes", printed.result == "PASS" and printed.source_category == "BIS",
          printed.reason)
    check("11 BIS compliance holds only BIS checks", all(c.source_category == "BIS" for c in bis.checks))
    miss = bis_eval(WATER)
    check("16 IS number not read -> the BIS rule is still REVIEW",
          next(c for c in miss.checks if c.rule_id == "packaged-water-label-shows-is-number").result == "REVIEW")

    res = run_downstream(regions(WATER + ["IS 14543", "MRP ₹20.00 (Inclusive of all taxes)"]), finder=FINDER,
                         requirements=REAL)
    check("12 package-label checks all say LEGAL_METROLOGY with a Legal Metrology source record",
          all(c.source_category == "LEGAL_METROLOGY" and c.source and c.source.source_authority == "LEGAL_METROLOGY"
              and c.standard_number is None for c in res.package_label.checks))
    check("12 source authority name is Legal Metrology, not BIS",
          res.package_label.source_authority.startswith("Legal Metrology") and "BIS" not in res.package_label.source_authority)
    check("BIS and Legal Metrology results are reported separately in the pipeline",
          res.stages.compliance == res.compliance.overall_status
          and res.stages.package_label == res.package_label.overall_status)
    mrp = next(i for i in res.completeness.items if i.field == "mrp")
    check("completeness links MRP to the Legal Metrology requirement only",
          mrp.requirement_coverage == "VERIFIED_REQUIREMENT" and mrp.requirement_ids == [MRP], str(mrp.requirement_ids))
    check("no text calls anything legally missing",
          not any(FORBIDDEN.search(c.reason) for c in res.package_label.checks)
          and not any(FORBIDDEN.search(s) for s in res.package_label.summary))

    fssai = run_downstream(regions(["ROASTED CHANA", "FSSAI Lic. No. 10012345000123"]), finder=FINDER, requirements=REAL)
    completeness = {i.field: i for i in fssai.completeness.items}
    check("a NOT_APPLICABLE requirement does not link its field in completeness",
          MFR not in completeness["manufacturer"].requirement_ids)


def test_regressions() -> None:
    print("\nregressions")
    by_std = coverage_by_standard(ITEMS, REAL)
    counts = {s: sum(c.coverage_status == s for c in by_std) for s in ("INSPECTION_SUPPORTED", "STANDARD_ONLY", "UNSUPPORTED")}
    check("17 BIS coverage classes unchanged: 36 = 2 / 30 / 4",
          (len(by_std), counts["INSPECTION_SUPPORTED"], counts["STANDARD_ONLY"], counts["UNSUPPORTED"]) == (36, 2, 30, 4),
          str(counts))

    stage = extract_declarations(regions(WATER + ["ISTIS 14543"]))
    std = next(d for d in stage.fields if d.field == "standard_number")
    check("14 IS-number normalization preserved", std.value == "IS 14543" and std.extraction_method == "deterministic_normalization")
    stage = extract_declarations(regions(KETTLE + ["Email: care@ thermopot.example"]))
    email = next(d for d in stage.fields if d.field == "consumer_care")
    check("14 email normalization needs a contact cue and is preserved",
          email.value == "care@thermopot.example" and email.extraction_method == "deterministic_normalization", str(email.value))

    t = coverage_totals(ITEMS, REAL)
    check("coverage report separates BIS standards from Legal Metrology requirements",
          (t.bis_standards, t.bis_inspection_supported, t.bis_standard_only) == (36, 2, 30)
          and t.legal_metrology_requirements == 11 and t.legal_metrology_rules == 6
          and t.package_label_checkable_requirements == t.bis_rules + t.legal_metrology_rules == 7
          and t.deterministic_rules == 7, str(t))


def png(width: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, 400), "white").save(buf, format="PNG")
    return buf.getvalue()


class Engine:
    def __init__(self, by_width):
        self.by_width = by_width

    def __call__(self, arr):
        r = self.by_width[arr.shape[1]]
        if isinstance(r, Exception):
            raise r
        return list(r), 0.01


def raw(*texts):
    out, y = [], 20
    for i, t in enumerate(texts):
        h = 50 if i == 0 else 25
        out.append(RawRegion(t, 0.95, (10, y, 10 + 10 * len(t), y + h),
                             [[10, y], [10 + 10 * len(t), y], [10 + 10 * len(t), y + h], [10, y + h]]))
        y += h + 15
    return out


def test_multiside() -> None:
    print("\nmulti-side packages")
    F, B, S = 701, 702, 703

    def package(by_width, sides):
        analyzer = InspectionAnalyzer(ocr_engine=Engine(by_width), product_finder=FINDER)
        return analyzer.analyze_package([PackageUpload(png(w), f"{s}.png", s) for w, s in sides])

    out = package({F: raw("ELECTRIC KETTLE", "Product name: Electric Kettle", "MRP ₹899.00 (Inclusive of all taxes)"),
                   B: raw("Manufactured by: Thermopot Appliances Pvt Ltd",
                          "Address: Plot 12, Baddi Industrial Area, Solan 173205, Himachal Pradesh",
                          "Net Quantity: 1 N")},
                  [(F, "FRONT"), (B, "BACK")])
    pl = out.package_label
    mrp, mfr = (next(c for c in pl.checks if c.rule_id == r) for r in (MRP, MFR))
    check("15 MRP on the front photo keeps its image + side", mrp.result == "PASS"
          and mrp.evidence[0].source_sides == ["FRONT"] and mrp.evidence[0].source_regions[0].startswith("I1-"))
    check("15 manufacturer on the back photo keeps its image + side", mfr.result == "PASS"
          and all(e.source_sides == ["BACK"] for e in mfr.evidence))

    split = package({F: raw("ELECTRIC KETTLE", "Manufactured by: Thermopot Appliances Pvt Ltd"),
                     B: raw("Address: Plot 12, Baddi Industrial Area, Solan 173205, Himachal Pradesh")},
                    [(F, "FRONT"), (B, "BACK")])
    c = next(c for c in split.package_label.checks if c.rule_id == MFR)
    check("15 name and address on different photos -> REVIEW (not linked)", c.result == "REVIEW"
          and c.reason_code == "EVIDENCE_NOT_LINKED", c.reason_code)

    conflict = package({F: raw("ELECTRIC KETTLE", "MRP ₹899.00 (Inclusive of all taxes)"),
                        B: raw("MRP ₹999.00 (Inclusive of all taxes)")}, [(F, "FRONT"), (B, "BACK")])
    c = next(c for c in conflict.package_label.checks if c.rule_id == MRP)
    check("15 conflicting MRP across photos -> REVIEW", c.result == "REVIEW" and c.reason_code == "EVIDENCE_CONFLICT")

    failed = package({F: raw("ELECTRIC KETTLE", "MRP ₹899.00 (Inclusive of all taxes)"), S: RuntimeError("boom")},
                     [(F, "FRONT"), (S, "LEFT")])
    c = next(c for c in failed.package_label.checks if c.rule_id == DATE)
    check("15 a failed side is reported, never treated as absent",
          c.result == "REVIEW" and c.reason_code == "EVIDENCE_NOT_DETECTED_UNREADABLE_IMAGES"
          and any("no usable OCR" in n for n in failed.package_label.notes), c.reason_code)


def test_http() -> None:
    print("\nHTTP contract (real OCR engine)")
    client = TestClient(app)
    body = client.get("/inspection/coverage").json()
    totals = body["totals"]
    check("GET /inspection/coverage reports BIS and Legal Metrology separately",
          totals["total"] == 36 and totals["legal_metrology_requirements"] == 11
          and totals["legal_metrology_rules"] == 6 and totals["deterministic_rules"] == 7
          and len(body["legal_metrology"]["requirements"]) == 11
          and all(r["source_category"] == "LEGAL_METROLOGY" for r in body["legal_metrology"]["requirements"]),
          str(totals))

    path = SAMPLES / "synth_electric-kettle.png"
    with path.open("rb") as fh:
        r = client.post("/inspection/analyze", files={"image": (path.name, fh, "image/png")})
    data = r.json()
    pl = data.get("package_label") or {}
    results = {c["rule_id"]: c["result"] for c in pl.get("checks", [])}
    check("POST /inspection/analyze returns package_label next to BIS compliance",
          r.status_code == 200 and pl.get("source_category") == "LEGAL_METROLOGY" and "compliance" in data
          and data["pipeline"]["package_label"] == pl.get("overall_status"))
    check("real kettle label: all six checkable Legal Metrology rules PASS",
          all(results.get(rid) == "PASS" for rid in (MRP, QTY, MFR, NAME, DATE, CONTACT)), str(results))
    check("every PASS carries OCR evidence and a quoted Legal Metrology source",
          all(c["evidence"] and c["evidence"][0]["source_regions"] and c["source"]["source_authority"] == "LEGAL_METROLOGY"
              and c["source"]["quote"] and c["reference"] for c in pl["checks"] if c["result"] == "PASS"))


def main() -> int:
    test_sources()
    test_loader_rejections()
    test_mrp()
    test_net_quantity()
    test_date()
    test_manufacturer_and_contact()
    test_applicability()
    test_bis_separation()
    test_regressions()
    test_multiside()
    test_http()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
