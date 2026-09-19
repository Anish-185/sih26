"""Checks for Milestone 18 — testing laboratory intelligence.

MetrIQ now holds a verified snapshot of BIS's own LIMS "IS-wise test facilities"
listing. These checks lock in that it stays evidence-backed discovery and never
becomes a laboratory recommendation engine:

  provenance   every record carries a BIS source URL, a document name and a
               retrieval date; nothing is synthetic
  explicit     a standard -> laboratory relationship exists ONLY because BIS
               lists it. Name, city and "it is a testing laboratory" never
               establish capability, and standard editions and parts never
               collide (IS 302 Part 2/Sec 3 is not Part 2/Sec 201)
  no invention no laboratory, address, contact, accreditation, NABL claim,
               recognition status or URL is ever produced that is not in a
               record; missing fields are reported as unavailable
  no ranking   no "best" / "recommended" / "most suitable"; ordering is
               alphabetical and says so
  honesty      validity is "as at the snapshot", never "currently valid";
               no result says no such laboratory exists
  isolation    laboratory discovery never touches PASS / FAIL / REVIEW, and the
               LLM never decides which laboratories are relevant
  regression   the Phase 7 API contract and the Milestone 17 language layer
               both still work

Every LLM call is stubbed — this suite spends no OpenRouter quota and needs
neither LM Studio nor the network.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_laboratory_intelligence.py
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app import lab_registry  # noqa: E402
from app import language as lang  # noqa: E402
from app.lab_registry import (  # noqa: E402
    CITY_MATCH,
    EXPIRED_AT_SNAPSHOT,
    NAME_MATCH,
    STANDARD_LISTED,
    VALID_AT_SNAPSHOT,
    LabRegistry,
    load_laboratories,
    standard_key,
)
from app.laboratory import LAB_SYSTEM_PROMPT, LaboratorySearchService  # noqa: E402
from app.main import app  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0

REGISTRY = load_laboratories()
ENGINE = SearchEngine()
FINDER = ProductStandardFinder(ENGINE)
CLIENT = TestClient(app)
DATA = Path(__file__).resolve().parents[2] / "data" / "laboratories.json"

KETTLE = "IS 367:1993"


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


class FakeLLM:
    """Records what it was asked; never reached by retrieval decisions."""

    def __init__(self) -> None:
        self.system_prompts: list[str] = []
        self.user_prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str, **_kw) -> str:
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        return "GROUNDED ANSWER"


def service(llm=None) -> tuple[LaboratorySearchService, FakeLLM]:
    fake = llm or FakeLLM()
    return LaboratorySearchService(
        search_engine=ENGINE, llm=fake, registry=REGISTRY, product_finder=FINDER,
    ), fake


# ------------------------------------------------------- 1. the snapshot


def test_snapshot_is_real_and_traceable() -> None:
    print("\n[1] the laboratory snapshot is real, official and traceable")

    check("the snapshot file exists", DATA.exists())
    payload = json.loads(DATA.read_text())
    source = payload["source"]
    check("it records the source organisation", source["organization"].startswith("Bureau of Indian"))
    check("it records the BIS LIMS URL", "lims.bis.gov.in" in source["url"])
    check("it records a retrieval date", bool(source.get("retrieved_on")))
    check("it says plainly that it is a snapshot, not a live feed",
          "not a live feed" in source["note"])

    check("the registry loaded without errors", REGISTRY.errors == [], str(REGISTRY.errors[:2]))
    check("it holds a substantial number of records", len(REGISTRY.records) > 500,
          str(len(REGISTRY.records)))

    bad_source = [r.lab_name for r in REGISTRY.records if "bis.gov.in" not in r.source_url]
    check("every record cites an official BIS URL", not bad_source, "; ".join(bad_source[:2]))
    check("every record carries a retrieval date", all(r.retrieved_on for r in REGISTRY.records))
    check("every record names its source document", all(r.document_name for r in REGISTRY.records))
    check("every record names a laboratory and a standard",
          all(r.lab_name and r.standard_as_listed for r in REGISTRY.records))

    # No synthetic filler: every laboratory name must look like a real listing,
    # not a placeholder.
    placeholders = [r.lab_name for r in REGISTRY.records
                    if re.search(r"\b(example|sample|test lab \d|lorem|foo|bar|tbd|xxx)\b",
                                 r.lab_name, re.I)]
    check("no placeholder or synthetic laboratory names", not placeholders,
          "; ".join(placeholders[:2]))


# ------------------------------------------------- 2. standard identity


def test_standard_identity_is_strict() -> None:
    print("\n[2] a standard's identity is exact — parts and editions never collide")

    check("'IS 367:1993' and 'IS 367 (1993)' are the same standard",
          standard_key("IS 367:1993").matches(standard_key("IS 367 (1993)")))
    check("a missing year still matches the same document",
          standard_key("IS 367").matches(standard_key("IS 367 (1993)")))
    check("different EDITIONS are different standards",
          not standard_key("IS 14543 (2016)").matches(standard_key("IS 14543 (2024)")))
    check("different SECTIONS are different standards",
          not standard_key("IS 302 (Part 2/Sec 3)").matches(standard_key("IS 302 (Part 2/Sec 201)")))
    check("different PARTS are different standards",
          not standard_key("IS 1489 (Part 1)").matches(standard_key("IS 1489 (Part 2)")))
    check("a different document number never matches",
          not standard_key("IS 367").matches(standard_key("IS 3671")))
    check("text with no standard number has no key", standard_key("a testing laboratory") is None)

    # The edition split must be visible, not silently hidden.
    others = REGISTRY.other_editions("IS 14543:2016")
    check("other editions of the same standard are reported, not merged",
          any("2024" in o for o in others), str(others))
    for match in REGISTRY.for_standard("IS 14543:2016"):
        if "2024" in match.record.standard_as_listed:
            check("a 2024-edition laboratory never appears under the 2016 edition", False)
            break
    else:
        check("a 2024-edition laboratory never appears under the 2016 edition", True)


# --------------------------------------------- 3. standard -> laboratory


def test_standard_to_laboratory() -> None:
    print("\n[3] standard -> laboratory, established only by the BIS listing")

    matches = REGISTRY.for_standard(KETTLE)
    check("IS 367:1993 has listed laboratories", len(matches) > 0, str(len(matches)))
    check("every match carries the STANDARD_LISTED signal",
          all(STANDARD_LISTED in m.why.signals for m in matches))
    check("every match names the standard as BIS listed it",
          all(standard_key(m.record.standard_as_listed).matches(standard_key(KETTLE))
              for m in matches))
    check("the explanation says BIS explicitly lists it",
          all("explicitly lists" in m.why.summary for m in matches))

    check("an unknown standard returns nothing", REGISTRY.for_standard("IS 999999:2099") == [])
    check("a non-standard string returns nothing", REGISTRY.for_standard("hello") == [])
    check("None returns nothing", REGISTRY.for_standard(None) == [])

    # Ordering is alphabetical — deliberately not a ranking.
    names = [m.record.lab_name.lower() for m in matches]
    check("results are ordered alphabetically, not ranked", names == sorted(names))

    covered = sum(1 for i in ENGINE.items
                  if i.category == "indian_standards" and i.standard_number
                  and REGISTRY.covers_standard(i.standard_number))
    check("many knowledge-base standards have laboratories", covered > 50, str(covered))


# ------------------------------- 4. product -> standard -> laboratory


def test_product_to_standard_to_laboratory() -> None:
    print("\n[4] product -> standard -> laboratory reuses the existing finder")

    svc, fake = service()
    matches, standard, how = svc.find_laboratories("Where can I test an electric kettle?")
    check("a product question finds laboratories", len(matches) > 0, str(len(matches)))
    check("via the product -> standard chain", how == "product", str(how))
    check("and lands on the kettle standard",
          standard_key(standard).matches(standard_key(KETTLE)), str(standard))
    check("no model was called to decide any of it", fake.system_prompts == [])

    # A standard named in the query is honoured directly.
    _, standard2, how2 = svc.find_laboratories("which lab can test IS 367")
    check("a standard named in the query is used directly", how2 == "query", str(how2))

    # An unknown product must NOT be carried forward as if it were certain.
    matches3, standard3, _ = svc.find_laboratories("Where can I test a zzqq flurbwidget?")
    check("an unknown product establishes no standard", standard3 is None, str(standard3))
    check("and invents no laboratories", matches3 == [], str(len(matches3)))

    # Without a product finder the service must not guess a product at all.
    plain = LaboratorySearchService(search_engine=ENGINE, llm=FakeLLM(), registry=REGISTRY)
    _, standard4, _ = plain.find_laboratories("Where can I test an electric kettle?")
    check("with no product finder, no product -> standard claim is made", standard4 is None)


# --------------------------------------------- 5. name / city / no-match


def test_name_city_and_no_match() -> None:
    print("\n[5] name and city search, and honest no-match behaviour")

    by_name = REGISTRY.search("TUV Rheinland")
    check("searching a laboratory name finds it", len(by_name) > 0, str(len(by_name)))
    check("and says it matched on the NAME", all(NAME_MATCH in m.why.signals for m in by_name))
    check("a name match never claims a standard capability",
          all(STANDARD_LISTED not in m.why.signals for m in by_name))

    by_city = REGISTRY.search("laboratories in Noida")
    check("a city question finds laboratories in that city", len(by_city) > 0, str(len(by_city)))
    check("and the explanation names the term that actually matched",
          all("noida" in m.why.summary.lower() for m in by_city))
    check("at least one matched on the CITY field",
          any(CITY_MATCH in m.why.signals for m in by_city))

    check("a too-short query matches nothing", REGISTRY.search("ab") == [])
    check("an empty query matches nothing", REGISTRY.search("") == [])
    # Filler words must not return the whole snapshot.
    for noise in ("laboratory", "testing laboratories", "which lab"):
        check(f"the filler query {noise!r} does not return everything",
              len(REGISTRY.search(noise)) < len(REGISTRY.records) // 2,
              str(len(REGISTRY.search(noise))))

    check("the no-match note is about MetrIQ's coverage, not existence",
          "not about which laboratories exist" in lab_registry.NO_MATCH)


# ------------------------------------------------ 6. nothing is invented


def test_nothing_is_invented() -> None:
    print("\n[6] no fabricated laboratories, contacts, accreditation or status")

    # Every field a record exposes must come from the snapshot.
    raw = json.loads(DATA.read_text())["laboratories"]
    raw_names = {r["lab_name"] for r in raw}
    check("every registry laboratory exists in the snapshot file",
          REGISTRY.laboratory_names <= raw_names)

    # The snapshot holds no contact data at all, so nothing may surface any.
    forbidden = ("phone", "email", "@", "tel:", "mobile")
    leaked = [r.lab_name for r in REGISTRY.records
              if any(f in (r.remark or "").lower() for f in ("email", "phone", "mobile"))]
    check("no contact details are carried in the records", not leaked, "; ".join(leaked[:2]))
    check("the registry exposes no contact field at all",
          not any(f in lab_registry.LabRecord.__dataclass_fields__ for f in forbidden))

    # No accreditation claim anywhere in what MetrIQ writes.
    written = " ".join([
        lab_registry.NO_MATCH, lab_registry.SNAPSHOT_NOTE, lab_registry.CURRENTNESS_NOTE,
        *(m.why.summary for m in REGISTRY.for_standard(KETTLE)),
    ]).lower()
    for claim in ("nabl accredited", "bis approved", "accredited laboratory",
                  "is accredited", "currently operational", "currently valid"):
        check(f"MetrIQ never writes {claim!r}", claim not in written)

    # No ranking language.
    for word in ("best", "recommended", "most suitable", "top laboratory", "guaranteed"):
        check(f"MetrIQ never writes {word!r}", word not in written)

    check("the snapshot note disclaims accreditation, scope, availability and status",
          all(x in lab_registry.SNAPSHOT_NOTE for x in
              ("accreditation", "scope", "availability", "operational status")))
    check("a currentness warning exists", "Confirm current scope" in lab_registry.CURRENTNESS_NOTE)


# ------------------------------------------------- 7. missing fields


def test_missing_fields_are_reported_not_filled() -> None:
    print("\n[7] a field the record does not hold is reported as unavailable")

    without_city = [r for r in REGISTRY.records if not r.city]
    check("some records genuinely have no city", len(without_city) > 0, str(len(without_city)))
    check("a missing city stays None — never guessed",
          all(r.city is None for r in without_city))

    without_validity = [r for r in REGISTRY.records if not r.validity_date]
    if without_validity:
        status, iso = without_validity[0].validity()
        check("a missing validity date reports NOT_STATED", status == "NOT_STATED", status)
        check("and carries no invented date", iso is None)

    check("there is a standard 'not available' wording",
          "Not available in the verified MetrIQ record." == lab_registry.NOT_AVAILABLE)

    # Validity is always "as at the snapshot", and computed, not asserted.
    with_validity = [r for r in REGISTRY.records if r.validity_date]
    check("validity dates parse into a status",
          all(r.validity(date(2026, 9, 19))[0] in
              {VALID_AT_SNAPSHOT, EXPIRED_AT_SNAPSHOT, "NOT_STATED"} for r in with_validity[:60]))
    sample = next(r for r in with_validity if r.validity(date(2026, 9, 19))[0] == VALID_AT_SNAPSHOT)
    check("a date far in the future is EXPIRED when judged from later",
          sample.validity(date(2099, 1, 1))[0] == EXPIRED_AT_SNAPSHOT)


# --------------------------------------------------- 8. the LLM's role


def test_llm_never_retrieves() -> None:
    print("\n[8] the model explains; it never decides which laboratories are relevant")

    svc, fake = service()
    out = svc.search("Where can I test an electric kettle?", explain=False)
    check("a full search with explain=False calls no model", fake.system_prompts == [])
    check("and still returns laboratories", len(out.laboratories) > 0, str(len(out.laboratories)))

    svc2, fake2 = service()
    out2 = svc2.search("Where can I test an electric kettle?", explain=True)
    check("with explain=True the model is called once", len(fake2.system_prompts) == 1)
    check("the laboratories were already decided before the call",
          len(out2.laboratories) == len(out.laboratories))

    prompt = " ".join(fake2.system_prompts[0].split())  # the prompt is hard-wrapped
    check("the prompt forbids inventing laboratory details",
          "Do NOT invent laboratory names" in prompt)
    check("it forbids inventing accreditation and operational status",
          "accreditation status" in prompt and "operational status" in prompt)
    check("it restricts naming to the supplied records",
          "MATCHED LABORATORY RECORDS" in prompt)
    check("it forbids ranking or recommending", "do not rank or recommend" in prompt.lower())
    check("it requires saying so when evidence is insufficient",
          "insufficient" in prompt.lower())

    user_prompt = fake2.user_prompts[0]
    check("the matched records are supplied to the model",
          "MATCHED LABORATORY RECORDS" in user_prompt)
    check("with their real names", any(m.record.lab_name[:18] in user_prompt
                                       for m in out2.laboratories))
    check("and are labelled as not establishing accreditation or status",
          "do not establish accreditation" in user_prompt)

    # With no matches the model is explicitly told to name nobody.
    svc3, fake3 = service()
    svc3.search("BIS laboratory recognition scheme", explain=True)
    if fake3.user_prompts:
        check("with no matched records the model is told to name none",
              "you must not name any laboratory" in fake3.user_prompts[0]
              or "MATCHED LABORATORY RECORDS" in fake3.user_prompts[0])


# ------------------------------------------------ 9. the HTTP contract


def test_http_contract() -> None:
    print("\n[9] /laboratory-search is extended, not broken")

    legacy = CLIENT.post("/laboratory-search", json={"query": "cement testing", "explain": False})
    check("a pre-existing request shape still works", legacy.status_code == 200,
          str(legacy.status_code))
    body = legacy.json()
    check("every pre-existing field is still present",
          {"query", "standard_context", "answer", "grounded", "confidence",
           "source_count", "sources", "note"} <= set(body))
    check("and the Milestone 17 language field survives", body["language"] == lang.EN)

    kettle = CLIENT.post("/laboratory-search",
                         json={"query": "Where can I test an electric kettle?", "explain": False})
    data = kettle.json()
    check("a product question returns laboratories", data["laboratory_count"] > 0,
          str(data["laboratory_count"]))
    check("it reports the standard they were matched on",
          standard_key(data["laboratory_standard"]).matches(standard_key(KETTLE)))
    check("and how that standard was established",
          data["laboratory_standard_source"] == "product")
    check("coverage is reported honestly", data["coverage"]["records"] == len(REGISTRY.records))

    record = data["laboratories"][0]
    check("each record carries its why", record["why"]["summary"].startswith("Relevant because"))
    check("each record carries its BIS source", "bis.gov.in" in record["source_url"])
    check("each record carries its retrieval date", bool(record["retrieved_on"]))
    check("each record carries a validity STATUS, not a claim",
          record["validity_status"] in {VALID_AT_SNAPSHOT, EXPIRED_AT_SNAPSHOT, "NOT_STATED"})

    by_number = CLIENT.post("/laboratory-search",
                            json={"standard_number": KETTLE, "explain": False})
    check("a standard number alone is a complete request", by_number.status_code == 200)
    check("and returns the same laboratories",
          by_number.json()["laboratory_count"] == data["laboratory_count"])
    check("reported as established from the given standard",
          by_number.json()["laboratory_standard_source"] == "standard")

    empty = CLIENT.post("/laboratory-search", json={"query": "", "explain": False})
    check("an empty request is handled cleanly", empty.status_code == 200)

    unknown = CLIENT.post("/laboratory-search",
                          json={"standard_number": "IS 999999:2099", "explain": False})
    check("an unknown standard returns no laboratories, not an error",
          unknown.status_code == 200 and unknown.json()["laboratory_count"] == 0)
    check("with the coverage-not-existence note",
          "not about which laboratories exist" in (unknown.json()["no_match_note"] or ""))

    bad = CLIENT.post("/laboratory-search", json={"query": 5})
    check("a malformed body is rejected with 422", bad.status_code == 422, str(bad.status_code))


# ------------------------------------------- 10. multilingual regression


def test_multilingual_still_works() -> None:
    print("\n[10] Milestone 17 still works through the laboratory route")

    english = CLIENT.post("/laboratory-search",
                          json={"query": "Where can I test an electric kettle?", "explain": False}).json()
    hindi = CLIENT.post("/laboratory-search",
                        json={"query": "इलेक्ट्रिक केतली की जांच कहाँ करवा सकता हूँ?",
                              "explain": False}).json()
    telugu = CLIENT.post("/laboratory-search",
                         json={"query": "ఎలక్ట్రిక్ కెటిల్‌ను ఎక్కడ పరీక్షించవచ్చు?",
                               "explain": False}).json()

    check("the Hindi query is detected as Hindi", hindi["language"] == lang.HI)
    check("the Telugu query is detected as Telugu", telugu["language"] == lang.TE)
    check("Hindi reaches the same standard", hindi["laboratory_standard"] == english["laboratory_standard"])
    check("Telugu reaches the same standard", telugu["laboratory_standard"] == english["laboratory_standard"])
    check("all three return the same laboratories",
          hindi["laboratory_count"] == telugu["laboratory_count"] == english["laboratory_count"],
          f'{hindi["laboratory_count"]}/{telugu["laboratory_count"]}/{english["laboratory_count"]}')
    check("the laboratory evidence itself is never translated",
          [r["lab_name"] for r in hindi["laboratories"]]
          == [r["lab_name"] for r in english["laboratories"]])


# --------------------------------------- 11. compliance stays untouched


def test_compliance_is_unaffected() -> None:
    print("\n[11] laboratory discovery never touches a compliance result")

    from app.inspection import InspectionAnalyzer, PackageUpload

    sample = Path(__file__).resolve().parents[2] / "samples" / "ocr-labels" / "synth_packaged-water.png"
    data = sample.read_bytes()

    with_labs = InspectionAnalyzer(product_finder=FINDER, lab_registry=REGISTRY)
    without = InspectionAnalyzer(product_finder=FINDER, lab_registry=LabRegistry())

    a = with_labs.analyze_package([PackageUpload(data, "w.png", "FRONT")])
    b = without.analyze_package([PackageUpload(data, "w.png", "FRONT")])

    check("the inspection surfaces laboratories", len(a.laboratories) > 0, str(len(a.laboratories)))
    check("an empty registry surfaces none", b.laboratories == [])
    check("BIS compliance is identical either way",
          a.compliance.overall_status == b.compliance.overall_status)
    check("its reason is identical", a.compliance.reason == b.compliance.reason)
    check("Legal Metrology is identical either way",
          a.package_label.overall_status == b.package_label.overall_status)
    check("the escalation decision is identical",
          a.escalation.required == b.escalation.required
          and a.escalation.system_result == b.escalation.system_result)
    check("the product identification is identical",
          a.product.standard_number == b.product.standard_number)

    # The compliance engine must not even be able to see laboratories.
    for module in ("compliance", "package_label", "escalation", "completeness", "declarations"):
        source = (Path(__file__).resolve().parents[1] / "app" / f"{module}.py").read_text()
        check(f"app/{module}.py does not import the laboratory registry",
              "lab_registry" not in source)

    lab = a.laboratories[0]
    check("an inspection laboratory carries its BIS source", "bis.gov.in" in lab.source_url)
    check("and its why", "explicitly lists" in lab.why)


# --------------------------------------------------- 12. the PDF report


def test_report_section() -> None:
    print("\n[12] the report shows discovery, never a test result")

    from reportlab.platypus import Paragraph, Table

    from app.report import _Doc, _laboratories, _register_fonts

    _register_fonts()

    def text_of(flowables) -> str:
        out: list[str] = []
        for f in flowables:
            if isinstance(f, Paragraph):
                out.append(f.getPlainText())
            elif isinstance(f, Table):
                out.extend(text_of(row) for row in f._cellvalues)
            elif isinstance(f, list):
                out.append(text_of(f))
        return " ".join(out)

    analysis = {"laboratories": [{
        "lab_name": "ABC Techno Labs India Private Limited", "osl_code": "1234567",
        "city": None, "standard_as_listed": "IS 14543 (2016)",
        "validity_date": "2027-10-15", "validity_status": VALID_AT_SNAPSHOT,
        "source_url": "https://lims.bis.gov.in/home/search_is_number/",
        "document_name": "BIS LIMS", "retrieved_on": "2026-09-19", "why": "x",
    }]}
    body = text_of(_laboratories(_Doc(), analysis))

    check("the section exists", "Relevant testing laboratories" in body)
    check("it states none of them tested this item",
          "none of these laboratories tested this item" in body)
    check("it states it formed no part of the compliance result",
          "part of the compliance result" in body)
    check("it disclaims accreditation and operational status",
          "accreditation" in body and "operational status" in body)
    check("it says the list is not ranked", "not ranked" in body)
    check("it carries the source and retrieval date",
          "lims.bis.gov.in" in body and "2026-09-19" in body)
    check("a missing city is shown as not stated", "Not stated in the record" in body)
    check("no laboratories means no section at all", _laboratories(_Doc(), {}) == [])


def main() -> int:
    test_snapshot_is_real_and_traceable()
    test_standard_identity_is_strict()
    test_standard_to_laboratory()
    test_product_to_standard_to_laboratory()
    test_name_city_and_no_match()
    test_nothing_is_invented()
    test_missing_fields_are_reported_not_filled()
    test_llm_never_retrieves()
    test_http_contract()
    test_multilingual_still_works()
    test_compliance_is_unaffected()
    test_report_section()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
