"""Checks for Milestone 21 — the canonical product context.

MetrIQ connects evidence produced by its existing deterministic features into a
unified product context. The context does not create new evidence and does not
independently verify external facts. These checks hold it to that.

NO OpenRouter or LM Studio request is made here: the OCR engine is stubbed, the
copilot provider is a stub, and every other stage is the real deterministic code.

What is locked in:

  composition   the context is built only from what the features produced; the
                analysis it was composed from is byte-for-byte unchanged
  applicability AVAILABLE / NOT_AVAILABLE / NOT_APPLICABLE / UNCERTAIN are four
                different facts — hallmarking is never attached to a package and
                package inspection is never attached to jewellery
  provenance    every section names the system that produced its evidence
  honesty       no standard, route, laboratory status or authentication is
                invented; snapshot wording and M19 boundaries survive
  isolation     no result, rule or coverage number changes because of this layer

Run:  cd backend && ./.venv/bin/python tests/test_product_context.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app import product_context as pc  # noqa: E402
from app.api import (  # noqa: E402
    get_certification_journey_service,
    get_engine,
    get_lab_registry,
    get_product_finder,
)
from app.copilot import (  # noqa: E402
    CAPABILITIES,
    FEATURE_CAPABILITIES,
    InspectionCopilot,
    build_context,
    build_feature_context,
)
from app.copilot_api import get_copilot  # noqa: E402
from app.main import app  # noqa: E402
from app.requirements import coverage_totals, load_requirements  # noqa: E402

# The Milestone 13 fixtures: stubbed OCR, the real deterministic pipeline.
from test_copilot import HALLMARK_ANALYSIS, WATER_ANALYSIS, StubProvider, reply  # noqa: E402

PASS = 0
FAIL = 0

CLIENT = TestClient(app)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def query_context(product: str = "", standard_number: str = "") -> pc.ProductContext:
    return pc.build_from_query(
        product,
        finder=get_product_finder(),
        journey_service=get_certification_journey_service(),
        registry=get_lab_registry(),
        standard_number=standard_number,
    )


KETTLE = query_context("electric kettle")
WATER = pc.build_from_analysis(WATER_ANALYSIS)
JEWELLERY = pc.build_from_analysis(HALLMARK_ANALYSIS)


# ------------------------------------------------------- A  context creation


def test_product_context_creation() -> None:
    print("\nA. the canonical context is created from both entry points")
    check("a typed description produces a server-derived context", KETTLE.origin == "QUERY")
    check("a finished inspection produces a composed context", WATER.origin == "INSPECTION")
    for name, context in (("query", KETTLE), ("inspection", WATER), ("hallmark", JEWELLERY)):
        features = [s.feature for s in context.sections]
        check(f"{name}: every feature is represented exactly once",
              features == list(pc.FEATURES), str(features))
        check(f"{name}: every section carries an availability state",
              all(s.status in (pc.AVAILABLE, pc.NOT_AVAILABLE, pc.NOT_APPLICABLE, pc.UNCERTAIN)
                  for s in context.sections))
        check(f"{name}: the deterministic summary has one line per feature",
              len(context.summary) == len(pc.FEATURES))
        check(f"{name}: the summary states each availability",
              all(any(s.status in line for line in context.summary) for s in context.sections))

    out = pc.context_out(WATER).model_dump(mode="json")
    check("the response states plainly that the context creates no evidence",
          "does not create new evidence" in out["note"])
    check("an analysis carries its own context", WATER_ANALYSIS.get("product_context") is not None)
    check("and it is the same composition",
          WATER_ANALYSIS["product_context"]["availability"] == out["availability"])


# ------------------------------------------------------ B  product -> standard


def test_product_to_standard_connection() -> None:
    print("\nB. the product reaches the standard the EXISTING retrieval established")
    standard = KETTLE.section(pc.STANDARD)
    check("an electric kettle reaches IS 367:1993",
          standard.detail.get("standard_number") == "IS 367:1993", str(standard.detail))
    check("the standard is AVAILABLE", standard.status == pc.AVAILABLE)
    check("the existing deterministic why-this-result is reused, not regenerated",
          "Retrieved as a candidate standard" in (standard.detail.get("why_retrieved") or ""))
    check("provenance names retrieval and the knowledge base",
          set(standard.provenance) == {pc.DETERMINISTIC_RETRIEVAL, pc.BIS_KNOWLEDGE_BASE})
    check("the standard carries its verified source",
          any("bis.gov.in" in (s.get("source_url") or "") for s in standard.sources))
    check("retrieval confidence is stated as a text match, not applicability",
          any("not a legal determination" in x for x in standard.limitations))

    # The composer must never rerank: it reports the number identification chose.
    water_standard = WATER.section(pc.STANDARD)
    check("an inspection's context reports the standard identification chose",
          water_standard.detail.get("standard_number")
          == (WATER_ANALYSIS["product"] or {}).get("standard_number"))


# --------------------------------------------------- C  product -> certification


def test_product_to_certification_connection() -> None:
    print("\nC. the standard reaches its certification journey")
    cert = KETTLE.section(pc.CERTIFICATION)
    check("a route is linked for IS 367:1993", cert.status == pc.AVAILABLE, cert.headline)
    check("the scheme is the one the verified records state",
          "Scheme I" in (cert.detail.get("scheme") or ""), str(cert.detail.get("scheme")))
    check("the journey's steps are linked", len(cert.detail.get("steps") or []) > 0)
    journey = get_certification_journey_service().build(standard_number="IS 367:1993")
    from app.certification_journey import journey_out

    check("the journey's OWN limitations are carried word for word, none added or dropped",
          cert.limitations == tuple(journey_out(journey).limitations), str(cert.limitations))
    check("MetrIQ states that it does not give fees, times or required documents",
          any("does not state application fees" in x for x in cert.limitations))
    check("guidance never claims the item is certified",
          not any(w in cert.headline.lower() for w in ("is certified", "holds a licence")))


# ------------------------------------------------------ D  product -> inspection


def test_product_to_inspection_connection() -> None:
    print("\nD. an inspected product reaches its compliance evidence")
    inspection = WATER.section(pc.INSPECTION)
    check("the inspection is AVAILABLE", inspection.status == pc.AVAILABLE)
    check("the system result is the rule engine's own",
          inspection.detail.get("system_result") == WATER_ANALYSIS["escalation"]["system_result"])
    check("the BIS and Legal Metrology results are reported separately",
          inspection.detail.get("bis_result") == WATER_ANALYSIS["compliance"]["overall_status"]
          and inspection.detail.get("legal_metrology_result")
          == WATER_ANALYSIS["package_label"]["overall_status"])
    for key in ("failed_checks", "review_checks", "passed_checks", "checks_with_no_verified_rule"):
        check(f"{key} is a list of rule ids from the record", isinstance(inspection.detail.get(key), list))
    check("checks with no verified rule are named, never shown as passes",
          all(rid not in (inspection.detail.get("passed_checks") or [])
              for rid in inspection.detail.get("checks_with_no_verified_rule") or []))
    check("'not detected' is explained as a fact about the photographs",
          any("never reported as legally missing" in x for x in inspection.limitations))
    check("provenance names the rule engine", pc.DETERMINISTIC_RULE_ENGINE in inspection.provenance)

    check("a product that has not been inspected says exactly that",
          KETTLE.section(pc.INSPECTION).status == pc.NOT_AVAILABLE
          and "No package inspection has been run" in KETTLE.section(pc.INSPECTION).headline)


# ----------------------------------------------------- E  product -> laboratory


def test_product_to_laboratory_connection() -> None:
    print("\nE. the standard reaches the listed laboratories")
    lab = KETTLE.section(pc.LABORATORY)
    check("laboratories are AVAILABLE for IS 367:1993", lab.status == pc.AVAILABLE, lab.headline)
    check("the relationship is the BIS listing itself",
          "Being listed is the only relationship established" in lab.headline)
    check("every record names the standard it was listed against",
          all(r.get("standard_as_listed") for r in lab.detail["laboratories"]))
    check("provenance is the snapshot", lab.provenance == (pc.LABORATORY_SNAPSHOT,))

    unlisted = query_context(standard_number="IS 18140:2023").section(pc.LABORATORY)
    check("a standard with no listed laboratory is MetrIQ's coverage, not a claim about reality",
          unlisted.status == pc.NOT_AVAILABLE
          and "not about which laboratories exist" in unlisted.headline, unlisted.headline)


# ---------------------------------------------------- F/G  applicability rules


def test_hallmarking_is_connected_only_when_relevant() -> None:
    print("\nF-G. hallmarking attaches to jewellery only, and irrelevant features are excluded")
    check("a packaged product has hallmarking NOT_APPLICABLE",
          WATER.availability[pc.HALLMARKING] == pc.NOT_APPLICABLE)
    check("and says so as applicability, not as missing data",
          "does not apply to this product" in WATER.section(pc.HALLMARKING).headline)
    check("a hallmark inspection has hallmarking AVAILABLE",
          JEWELLERY.availability[pc.HALLMARKING] == pc.AVAILABLE)
    check("and package inspection NOT_APPLICABLE",
          JEWELLERY.availability[pc.INSPECTION] == pc.NOT_APPLICABLE)
    check("a jewellery standard makes hallmarking relevant without any inspection",
          query_context(standard_number="IS 1417").availability[pc.HALLMARKING] != pc.NOT_APPLICABLE)
    check("an ordinary product query never attaches hallmarking",
          KETTLE.availability[pc.HALLMARKING] == pc.NOT_APPLICABLE)

    # Relevance is decided by the EXISTING retrieval engine — which verified
    # records the words actually reach — not by a new classifier.
    jewellery_query = query_context("gold ring")
    check("a jewellery description makes hallmarking relevant",
          jewellery_query.availability[pc.HALLMARKING] == pc.NOT_AVAILABLE
          and "relevant here" in jewellery_query.section(pc.HALLMARKING).headline,
          jewellery_query.section(pc.HALLMARKING).headline)
    check("and no hallmark observation is invented for a typed description",
          jewellery_query.section(pc.HALLMARKING).detail == {})
    for ordinary in ("packaged drinking water", "led lamp", "cement"):
        check(f"'{ordinary}' does not become a hallmarking subject",
              query_context(ordinary).availability[pc.HALLMARKING] == pc.NOT_APPLICABLE)
    check("relevance is answered by retrieval, not by a keyword list in this module",
          "the EXISTING retrieval engine, not by a new classifier"
          in Path("app/product_context.py").read_text())

    # NOT_APPLICABLE and NOT_AVAILABLE must never be used interchangeably.
    water_hallmark = WATER.section(pc.HALLMARKING)
    check("a not-applicable section carries no fabricated detail", water_hallmark.detail == {})
    check("NOT_AVAILABLE is used when the feature applies but MetrIQ has nothing",
          KETTLE.section(pc.INSPECTION).status == pc.NOT_AVAILABLE)


# ----------------------------------------------------------- H/I/J  uncertainty


def test_uncertainty_is_preserved() -> None:
    print("\nH-J. identification, standard and route uncertainty survive intact")
    product = JEWELLERY.section(pc.PRODUCT)
    check("an unsettled identification is UNCERTAIN, never forced into a name",
          product.status == pc.UNCERTAIN and JEWELLERY.product_name is None)
    check("the identification's own reason is carried", bool(product.detail.get("reason")))

    standard = JEWELLERY.section(pc.STANDARD)
    check("no standard is STANDARD_NOT_ESTABLISHED, never a guess",
          standard.reason_code == pc.STANDARD_NOT_ESTABLISHED and standard.status == pc.NOT_AVAILABLE)
    check("and the context says MetrIQ never generates a standard number",
          any("never generates a standard number" in x for x in standard.limitations))

    unknown = query_context("flux capacitor for a time machine")
    check("an unknown product establishes no standard",
          unknown.section(pc.STANDARD).status == pc.NOT_AVAILABLE)
    check("and no certification route is invented for it",
          unknown.section(pc.CERTIFICATION).reason_code == pc.CERTIFICATION_ROUTE_NOT_AVAILABLE)
    check("and no laboratory is attached",
          unknown.section(pc.LABORATORY).status == pc.NOT_AVAILABLE)

    # A standard whose sources were a manual / advisory has no route data (M16).
    no_route = query_context(standard_number="IS 18140:2023").section(pc.CERTIFICATION)
    check("a standard with no verified route says so, never borrowing one from a similar product",
          no_route.status == pc.NOT_AVAILABLE
          and no_route.reason_code == pc.CERTIFICATION_ROUTE_NOT_AVAILABLE, no_route.headline)


# --------------------------------------------------- K/L  laboratory snapshot


def test_laboratory_snapshot_and_limitations_are_preserved() -> None:
    print("\nK-L. the laboratory snapshot keeps its date, its states and its limits")
    lab = KETTLE.section(pc.LABORATORY)
    check("the snapshot date is reported", lab.detail.get("snapshot_retrieved_on") == "2026-09-19")
    check("validity is only ever 'as at the snapshot'",
          all(r["recognition_validity_as_at_snapshot"] in
              ("VALID_AT_SNAPSHOT", "EXPIRED_AT_SNAPSHOT", "NOT_STATED")
              for r in lab.detail["laboratories"]))
    text = json.dumps(pc.context_out(KETTLE).model_dump(mode="json")).lower()
    for forbidden in ("currently valid", "nabl accredited", "is accredited", "currently recognised"):
        check(f"the context never says '{forbidden}'", forbidden not in text)

    limits = " ".join(lab.limitations)
    check("the snapshot limitation is MetrIQ's own wording",
          "does not independently establish a laboratory's current accreditation" in limits)
    check("the un-ingested Group-1 / Group-2 PDFs are disclosed", "Group-1 / Group-2" in limits)
    check("the absence of contact details is disclosed",
          "Address, telephone, e-mail, accreditation number and NABL status" in limits)
    check("no ranking is implied", "does not rank laboratories" in limits)
    check("a city the snapshot does not hold is left empty, never guessed",
          all(("city" in r) and (r["city"] is None or isinstance(r["city"], str))
              for r in lab.detail["laboratories"]))


# ----------------------------------------------------- M  hallmarking safety


def test_hallmarking_safety_is_preserved() -> None:
    print("\nM. hallmarking evidence stays observation, never authentication")
    hallmark = JEWELLERY.section(pc.HALLMARKING)
    detail = hallmark.detail
    check("verification status can only be NOT_VERIFIED / NOT_DETECTED",
          detail.get("verification_status") in ("NOT_VERIFIED", "NOT_DETECTED"))
    check("official verification is always still required",
          detail.get("official_verification_required") is True)
    check("the overall hallmark status stays REVIEW", detail.get("overall_status") == "REVIEW")
    check("a user-supplied HUID is a text comparison only",
          any("compared as text only" in x for x in hallmark.limitations))
    check("the BIS logo is stated to be unconfirmable by OCR",
          any("logo can never be confirmed" in x for x in hallmark.limitations))
    check("MetrIQ states it does not authenticate a hallmark, HUID, jeweller or AHC",
          any("does not authenticate" in x and "Assaying and Hallmarking Centre" in x
              for x in hallmark.limitations))

    text = json.dumps(pc.context_out(JEWELLERY).model_dump(mode="json")).lower()
    for forbidden in ("huid verified", "hallmark is authentic", "the jeweller is registered",
                      "ahc verified", "is authentic", "certified jewellery"):
        check(f"the context never says '{forbidden}'", forbidden not in text)
    check("uncertain purity is never resolved into a grade",
          detail["purity"]["status"] in ("DETECTED", "UNCERTAIN", "NOT_DETECTED", "CONFLICT", "MULTIPLE"))


# --------------------------------------------------- N  conflicts and agreement


def test_conflicts_are_preserved_not_resolved() -> None:
    print("\nN. disagreement between evidence sources stays visible")
    check("an agreement between the label and retrieval is recorded",
          any("agree (IS 14543:2016)" in c for c in WATER.conflicts), str(WATER.conflicts))

    conflicted = copy.deepcopy(WATER_ANALYSIS)
    conflicted["product"]["signals"]["conflicts"] = [
        "The label text names Packaged Drinking Water; the visual observation suggests a toaster."
    ]
    conflicted["product"]["signals"]["agreement"] = False
    context = pc.build_from_analysis(conflicted)
    check("an OCR / vision conflict is carried through word for word",
          any("suggests a toaster" in c for c in context.conflicts))
    check("MetrIQ does not choose between them",
          context.section(pc.PRODUCT).detail["evidence_sources"]["ocr_and_vision_agree"] is False)

    unverified = copy.deepcopy(WATER_ANALYSIS)
    unverified["product"]["unverified_standard_numbers"] = ["IS 99999"]
    check("a printed standard with no verified record is reported as such",
          any("no verified knowledge-base record" in c
              for c in pc.build_from_analysis(unverified).conflicts))


# ------------------------------------------------------------ O  provenance


def test_every_section_carries_provenance() -> None:
    print("\nO. every connected fact names the system that produced it")
    known = {pc.USER_DESCRIPTION, pc.OCR_TEXT, pc.DECLARATION, pc.VISION_OBSERVATION,
             pc.DETERMINISTIC_RETRIEVAL, pc.BIS_KNOWLEDGE_BASE, pc.DETERMINISTIC_RULE_ENGINE,
             pc.LABORATORY_SNAPSHOT, pc.HALLMARK_OBSERVATION}
    for name, context in (("query", KETTLE), ("inspection", WATER), ("hallmark", JEWELLERY)):
        for section in context.sections:
            check(f"{name}/{section.feature}: provenance is present and from the fixed vocabulary",
                  bool(section.provenance) and set(section.provenance) <= known,
                  str(section.provenance))
    check("a typed description is labelled as the user's own words, not evidence",
          KETTLE.section(pc.PRODUCT).provenance == (pc.USER_DESCRIPTION,))
    check("and the context says a typed description is not evidence about an item",
          any("not evidence about a physical item" in x
              for x in KETTLE.section(pc.PRODUCT).limitations))
    check("an identified product names the evidence that supported it",
          pc.OCR_TEXT in WATER.section(pc.PRODUCT).provenance)


# -------------------------------------------------- P  client payload whitelist


def test_client_payload_is_whitelisted() -> None:
    print("\nP. the copilot's product payload is whitelisted, and the query path takes only text")
    res = CLIENT.post("/product-context", json={"product": "electric kettle", "evil": "PASS"})
    check("the server-derived endpoint rejects an unexpected field", res.status_code == 422)
    check("it needs something to work from", CLIENT.post("/product-context", json={}).status_code == 422)
    ok = CLIENT.post("/product-context", json={"product": "electric kettle"})
    check("and answers a plain description", ok.status_code == 200)
    check("the response is server-derived", ok.json()["origin"] == "QUERY")

    payload = ok.json()
    payload["sections"][0]["detail"]["injected_fact"] = "This product is BIS certified."
    payload["unexpected_top_level"] = {"system_result": "PASS"}
    get_copilot.cache_clear()
    provider = StubProvider(reply("Explained."))
    app.dependency_overrides[get_copilot] = lambda: InspectionCopilot(provider)
    res = CLIENT.post("/copilot/explain", json={
        "capability": "EXPLAIN_PRODUCT_CONTEXT",
        "context": {"feature": "PRODUCT", "product": payload},
    })
    check("a product context can be explained", res.status_code == 200, res.text[:200])
    check("an unexpected top-level field never reaches the model",
          "unexpected_top_level" not in provider.calls[0]["user"])
    check("the response says there is no system result to protect here",
          res.json()["system_result"] is None and res.json()["context_type"] == "PRODUCT")

    bad = CLIENT.post("/copilot/explain", json={
        "capability": "EXPLAIN_PRODUCT_CONTEXT",
        "context": {"feature": "PRODUCT", "laboratory": {"query": "x"}},
    })
    check("a feature with the wrong payload is 422", bad.status_code == 422)
    wrong = CLIENT.post("/copilot/explain", json={
        "capability": "EXPLAIN_UNCERTAINTY",
        "context": {"feature": "PRODUCT", "product": payload},
    })
    check("a capability this context does not accept is 422", wrong.status_code == 422)
    app.dependency_overrides.clear()
    get_copilot.cache_clear()

    source = Path("app/product_context.py").read_text()
    for forbidden in ("from app.openrouter", "from app.vision", "from app.llm", "from app.copilot"):
        check(f"the composer imports no model surface ({forbidden.split('.')[-1]})", forbidden not in source)
    check("the composer states the trust boundary of each entry point",
          "SERVER-DERIVED" in source and "echoed back by the client" in source)


# ------------------------------------------------------- Q/R  copilot guards


def test_copilot_guards_and_language_still_apply() -> None:
    print("\nQ-R. the M20 guards and the M17 language layer are unchanged here")
    payload = pc.context_out(KETTLE).model_dump(mode="json")

    def run(text, language="auto"):
        provider = StubProvider(reply(text))
        return InspectionCopilot(provider).explain_feature(
            "PRODUCT", payload, "EXPLAIN_PRODUCT_CONTEXT", language=language), provider

    for text, reason in (
        ("IS 99999:2020 also applies to this kettle.", "FABRICATED_STANDARD"),
        ("See https://fake-bis.example/kettle for details.", "FABRICATED_SOURCE"),
        ("The BIS licence fee is Rs. 3,000.", "FABRICATED_AMOUNT"),
        ("Eureka Testing Laboratory is NABL accredited.", "LABORATORY_STATUS_CLAIM"),
        ("The best laboratory for this is in Noida.", "LABORATORY_RANKING_CLAIM"),
    ):
        result, _ = run(text)
        check(f"withheld: {text!r}", result.answer.withheld and result.answer.withheld_reason == reason,
              f"got {result.answer.withheld_reason!r}")

    good, _ = run("MetrIQ matched IS 367:1993 and lists laboratory records from its 2026-09-19 snapshot.")
    check("a grounded cross-feature answer is allowed", not good.answer.withheld)

    english, en_provider = run("MetrIQ matched IS 367:1993.", language="en")
    hindi, hi_provider = run("MetrIQ matched IS 367:1993.", language="hi")
    check("English adds no language clause and Hindi does",
          "LANGUAGE OF THE ANSWER" not in en_provider.calls[0]["system"]
          and "LANGUAGE OF THE ANSWER: Hindi." in hi_provider.calls[0]["system"])
    check("the evidence sent is identical in both languages",
          en_provider.calls[0]["user"] == hi_provider.calls[0]["user"])
    check("the response reports the language", hindi.language == "hi" and english.language == "en")

    check("the product context is one of the copilot's feature contexts",
          "PRODUCT" in FEATURE_CAPABILITIES and "EXPLAIN_PRODUCT_CONTEXT" in CAPABILITIES)
    instruction = CAPABILITIES["EXPLAIN_PRODUCT_CONTEXT"]["instruction"]
    check("the capability forbids presenting NOT_APPLICABLE as missing data",
          "never present a NOT_APPLICABLE" in instruction.replace("Never present a NOT_APPLICABLE",
                                                                  "never present a NOT_APPLICABLE"))
    inspection_ctx = build_context(WATER_ANALYSIS, "EXPLAIN_PRODUCT_CONTEXT")
    check("an inspection's context reaches the copilot with its availability states",
          (inspection_ctx.get("product_context") or {}).get("availability", {}).get("HALLMARKING")
          == pc.NOT_APPLICABLE)
    check("and is labelled as a composition that establishes nothing",
          "creates no evidence" in inspection_ctx["product_context"]["what_this_is"])


# ------------------------------------------- S/T  nothing deterministic moved


def test_existing_results_and_coverage_are_unchanged() -> None:
    print("\nS-T. no result, rule or coverage number changed")
    before = copy.deepcopy(WATER_ANALYSIS)
    pc.build_from_analysis(WATER_ANALYSIS)
    pc.build_from_analysis(WATER_ANALYSIS)
    check("composing a context mutates nothing in the analysis", WATER_ANALYSIS == before)

    for key in ("compliance", "package_label", "escalation", "product", "declaration_stage",
                "hallmark", "ocr"):
        check(f"{key} is untouched by the context layer", WATER_ANALYSIS.get(key) == before.get(key))

    items = get_engine().items
    requirements = load_requirements(items)
    totals = coverage_totals(items, requirements)
    check("requirements are still 15", len(requirements.requirements) == 15,
          str(len(requirements.requirements)))
    check("deterministic rules are still 7", totals.deterministic_rules == 7,
          str(totals.deterministic_rules))
    check("INSPECTION_SUPPORTED standards are still 2", totals.bis_inspection_supported == 2,
          str(totals.bis_inspection_supported))
    check("verified standards are still 97", totals.bis_standards == 97, str(totals.bis_standards))

    source = Path("app/product_context.py").read_text()
    for forbidden in ("from app.compliance", "from app.package_label", "from app.declarations",
                      "from app.pipeline", "from app.ocr", "from app.hallmark",
                      "from app.product_identification"):
        check(f"the composer cannot recompute a result ({forbidden.split('.')[-1]})",
              forbidden not in source)


# ------------------------------------------------- U  old records still load


def test_old_saved_inspections_still_load() -> None:
    print("\nU. an inspection saved before this milestone still composes safely")
    old = copy.deepcopy(WATER_ANALYSIS)
    for key in ("product_context", "laboratories", "certification", "hallmark", "completeness",
                "vision", "escalation"):
        old.pop(key, None)
    context = pc.build_from_analysis(old)
    check("a record with none of the newer fields still builds",
          [s.feature for s in context.sections] == list(pc.FEATURES))
    check("its missing laboratory data is NOT_AVAILABLE, never invented",
          context.availability[pc.LABORATORY] == pc.NOT_AVAILABLE)
    check("its missing certification data is NOT_AVAILABLE",
          context.availability[pc.CERTIFICATION] == pc.NOT_AVAILABLE)
    check("hallmarking stays NOT_APPLICABLE for a package",
          context.availability[pc.HALLMARKING] == pc.NOT_APPLICABLE)

    bare = pc.build_from_analysis({})
    check("even an empty analysis composes without raising",
          [s.feature for s in bare.sections] == list(pc.FEATURES))
    check("and claims nothing", bare.availability[pc.STANDARD] == pc.NOT_AVAILABLE
          and bare.product_name is None)
    check("the analysis field is optional, so old stored records deserialise",
          "product_context" in Path("app/inspection.py").read_text()
          and "default=None" in Path("app/inspection.py").read_text())


# ----------------------------------------------------- V  stale M18 UI copy


def test_stale_laboratory_copy_is_gone() -> None:
    print("\nV. the stale Milestone 18 laboratory copy is corrected")
    view = (FRONTEND / "features" / "LaboratoriesView.tsx").read_text()
    check("the page no longer claims MetrIQ holds no individual laboratory records",
          "does not hold individual laboratory records" not in view)
    check("it no longer claims results are not specific laboratory names",
          "not specific laboratory names" not in view)
    check("it describes the verified snapshot instead",
          "verified snapshot" in view or "verified BIS LIMS snapshot" in view)
    check("it still states the snapshot date", "2026" in view)
    check("it still states what a listing does not establish",
          "does not establish current" in view)
    check("it still states that MetrIQ does not rank laboratories",
          "does not rank laboratories" in view)


# ------------------------------------------------ W  no unsupported claims


def test_no_unsupported_claims_are_introduced() -> None:
    print("\nW. the layer introduces no claim its sources do not make")
    for name, context in (("query", KETTLE), ("inspection", WATER), ("hallmark", JEWELLERY)):
        text = json.dumps(pc.context_out(context).model_dump(mode="json")).lower()
        for forbidden in ("is legally compliant", "is non-compliant", "is bis certified",
                          "guaranteed", "we recommend", "best choice", "currently valid"):
            check(f"{name}: never says '{forbidden}'", forbidden not in text)

    # Every standard number that appears came from a verified record.
    numbers = {s.detail.get("standard_number") for s in KETTLE.sections if s.detail.get("standard_number")}
    known = {i.standard_number for i in get_engine().items if i.standard_number}
    check("every standard number in the context exists in the knowledge base",
          numbers <= known, str(numbers - known))

    # Every URL came from application data.
    urls = {src.get("source_url") for s in KETTLE.sections for src in s.sources if src.get("source_url")}
    known_urls = {i.source_url for i in get_engine().items if i.source_url}
    known_urls |= {r.source_url for r in get_lab_registry().records}
    check("every source URL in the context came from a verified record or the snapshot",
          urls <= known_urls, str(urls - known_urls))

    check("the summary is produced by MetrIQ, not by a model",
          "no model is involved in producing it" in Path("app/product_context.py").read_text())


def main() -> int:
    test_product_context_creation()
    test_product_to_standard_connection()
    test_product_to_certification_connection()
    test_product_to_inspection_connection()
    test_product_to_laboratory_connection()
    test_hallmarking_is_connected_only_when_relevant()
    test_uncertainty_is_preserved()
    test_laboratory_snapshot_and_limitations_are_preserved()
    test_hallmarking_safety_is_preserved()
    test_conflicts_are_preserved_not_resolved()
    test_every_section_carries_provenance()
    test_client_payload_is_whitelisted()
    test_copilot_guards_and_language_still_apply()
    test_existing_results_and_coverage_are_unchanged()
    test_old_saved_inspections_still_load()
    test_stale_laboratory_copy_is_gone()
    test_no_unsupported_claims_are_introduced()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
