"""Checks for Milestone 20 — the contextual grounded copilot.

NO OpenRouter request is ever made here. Every provider is a stub, so the suite
costs nothing from the free daily quota and needs no API key.

Milestone 13 built the copilot over ONE context: a finished inspection. This
milestone widens it to the deterministic results of the feature pages (product
-> standard retrieval, a certification journey, a laboratory lookup), adds the
laboratory evidence to the inspection context, answers in the user's language,
and hardens the verification that MetrIQ runs over what the model wrote.

What is locked in here:

  context       each feature builds its own small grounded context — only
                application data, and only the part the question needs
  vocabulary    NOT_DETECTED / UNCERTAIN / UNSUPPORTED /
                NOT_AVAILABLE_IN_KNOWLEDGE_BASE stay four different things
  laboratory    a DATED SNAPSHOT: no current status, no accreditation, no
                ranking — a generated claim to the contrary is withheld
  hallmarking   observation is never authentication (Milestone 19 carries over)
  certification a route, never a certified item, a fee or a timeline
  language      the answer language changes; the evidence never does
  authority     the deterministic result still comes from the record
  failure       a provider outage never removes or weakens a MetrIQ result

Run:  cd backend && ./.venv/bin/python tests/test_copilot_context.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import language as lang  # noqa: E402
from app.copilot import (  # noqa: E402
    CAPABILITIES,
    EVIDENCE_VOCABULARY,
    FEATURE_CAPABILITIES,
    FEATURES,
    SYSTEM_PROMPT,
    InspectionCopilot,
    build_context,
    build_feature_context,
    collect_sources,
    render_prompt,
)
from app.copilot_api import get_copilot  # noqa: E402
from app.lab_registry import CURRENTNESS_NOTE, SNAPSHOT_NOTE  # noqa: E402
from app.main import app  # noqa: E402
from app.openrouter import CopilotUnavailable  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

# The Milestone 13 fixtures: stubbed OCR, real pipeline, no network.
from test_copilot import (  # noqa: E402
    HALLMARK_ANALYSIS,
    WATER_ANALYSIS,
    StubProvider,
    reply,
)

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


# --------------------------------------------------------------- feature data
#
# Exactly the shape the feature endpoints return, as the page received it.

STANDARD_PAYLOAD = {
    "product": "packaged drinking water",
    "confidence": "high",
    "note": "",
    "results": [
        {
            "id": "is-14543-2016",
            "title": "Packaged Drinking Water (Other Than Packaged Natural Mineral Water)",
            "standard_number": "IS 14543:2016",
            "confidence": "high",
            "matched_terms": ["packaged", "drinking", "water"],
            "why": {
                "standard_number": "IS 14543:2016",
                "strength": "strong",
                "signals": ["Title match: packaged drinking water", "Keyword match: drinking water"],
                "summary": "Retrieved as a candidate standard (strong match) because the title and "
                           "keywords describe this product.",
            },
            "source_url": "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/",
            "document_name": "Products under Compulsory Certification — Scheme I",
            "reference": None,
            "verification_status": "verified",
        }
    ],
}

CERTIFICATION_PAYLOAD = {
    "question": "What certification applies to packaged drinking water?",
    "product_context": "packaged drinking water",
    "journey": {
        "query": "IS 14543:2016",
        "standard_selection": "CONFIRMED",
        "standard_number": "IS 14543:2016",
        "standard_title": "Packaged Drinking Water",
        "verification_status": "VERIFIED",
        "scheme": {
            "scheme": "SCHEME_I",
            "name": "Scheme I (ISI Mark)",
            "mark": "ISI Mark",
            "basis": ["The verified BIS record states: Licences are granted under Scheme I."],
            "evidence": [],
            "conflict": "",
        },
        "steps": [
            {
                "order": 1,
                "title": "Apply through the BIS Manakonline portal",
                "evidence": [
                    {
                        "knowledge_id": "bis-apply-online",
                        "title": "Apply Online for BIS Certification",
                        "quote": "Applications for product certification are submitted online.",
                        "source_organization": "BIS",
                        "source_url": "https://www.bis.gov.in/apply-online/",
                        "document_name": "Apply Online",
                        "last_verified": "2026-09-19",
                    }
                ],
            }
        ],
        "next_steps": ["Use the official BIS application portal."],
        "limitations": ["MetrIQ does not parse the linked scheme PDFs, which may hold deeper detail."],
        "sources": [],
        "candidates": [],
        "why": [],
        "grounded": True,
        "message": "",
        "disclaimer": "Guidance only.",
    },
}

LAB_PAYLOAD = {
    "query": "where can I test packaged drinking water",
    "laboratory_standard": "IS 14543:2016",
    "laboratory_standard_source": "Reached from the product description through MetrIQ's retrieval.",
    "other_editions": ["IS 14543:2024"],
    "coverage": {
        "records": 1205, "laboratories": 245, "standards": 157,
        "retrieved_on": "2026-09-19", "note": "A snapshot of the BIS LIMS listing.",
    },
    "no_match_note": None,
    "laboratories": [
        {
            "lab_name": "Aqua Testing Services",
            "osl_code": "OSL-0421",
            "city": "Noida",
            "standard_as_listed": "IS 14543:2016",
            "product_as_listed": "Packaged drinking water",
            "grade_or_type": None,
            "validity_date": "2027-03-31",
            "validity_status": "VALID_AT_SNAPSHOT",
            "remark": None,
            "source_url": "https://lims.bis.gov.in/home/search_is_number/",
            "document_name": "BIS LIMS — IS-wise test facilities",
            "retrieved_on": "2026-09-19",
            "why": {"signals": ["STANDARD_LISTED"],
                    "summary": "BIS LIMS lists this laboratory against IS 14543:2016."},
        }
    ],
}

EMPTY_LAB_PAYLOAD = {
    "query": "laboratory for a wristwatch",
    "laboratory_standard": None,
    "other_editions": [],
    "coverage": LAB_PAYLOAD["coverage"],
    "no_match_note": "No matching verified laboratory record was found in MetrIQ's knowledge base.",
    "laboratories": [],
}


def run(payload_feature, payload, capability, text=None, language=lang.AUTO, question=""):
    """One stubbed feature explanation. Returns (result, provider)."""
    provider = StubProvider(text if text is not None else reply("Explained."))
    result = InspectionCopilot(provider).explain_feature(
        payload_feature, payload, capability, question=question, language=language
    )
    return result, provider


def run_inspection(analysis, capability, text=None, language=lang.AUTO, question=""):
    provider = StubProvider(text if text is not None else reply("Explained."))
    result = InspectionCopilot(provider).explain(
        analysis, capability, question=question, language=language
    )
    return result, provider


# ------------------------------------------------- A  inspection context


def test_grounded_answer_from_inspection_context() -> None:
    print("\nA. an inspection explains itself, and escalation stays the record's own evidence")
    result, provider = run_inspection(WATER_ANALYSIS, "EXPLAIN_INSPECTION")
    check("exactly one provider call for one user action", len(provider.calls) == 1)
    check("escalation is read from the record, never a verdict",
          result.escalation_required == WATER_ANALYSIS["escalation"]["required"])
    check("the context type is INSPECTION", result.context_type == "INSPECTION")
    check("MetrIQ's own confidence is deterministic", result.confidence == "GROUNDED")

    prompt = provider.calls[0]["user"]
    check("the prompt carries MetrIQ's own escalation evidence", '"resolvable_by_system"' in prompt)
    check("the prompt stays small enough for the free tier", len(prompt) < 40_000,
          f"{len(prompt)} chars")


def test_laboratory_evidence_reaches_the_inspection_context() -> None:
    print("\nA2. laboratory records reach the inspection context, labelled")
    analysis = copy.deepcopy(WATER_ANALYSIS)
    analysis["laboratories"] = [
        {k: v for k, v in LAB_PAYLOAD["laboratories"][0].items() if k != "why"} | {"why": "listed"}
    ]
    ctx = build_context(analysis, "EXPLAIN_LABORATORY")
    labs = ctx.get("testing_laboratories") or {}
    check("the laboratory section is built", labs.get("count") == 1)
    check("it is labelled a snapshot with MetrIQ's own wording", labs.get("limitation") == SNAPSHOT_NOTE)
    check("validity is reported as at the snapshot only",
          labs["records"][0]["recognition_validity_as_at_snapshot"] == "VALID_AT_SNAPSHOT")
    check("the section says MetrIQ does not rank laboratories", "does not rank" in labs["ordering"])
    check("it states that MetrIQ holds no contact details",
          "telephone" in labs["fields_metriq_does_not_hold"])

    none = copy.deepcopy(WATER_ANALYSIS)
    none["laboratories"] = []
    ctx_none = build_context(none, "EXPLAIN_LABORATORY")
    check("no laboratory record is reported as NOT_AVAILABLE_IN_KNOWLEDGE_BASE, not as 'none exist'",
          "NOT_AVAILABLE_IN_KNOWLEDGE_BASE" in (ctx_none["testing_laboratories"].get("no_match") or ""))

    check("a narrowly-scoped capability never sees the laboratory section",
          "testing_laboratories" not in build_context(WATER_ANALYSIS, "EXPLAIN_UNCERTAINTY"))


# ------------------------------------------------- B  standard context


def test_grounded_answer_from_standard_context() -> None:
    print("\nB. a product -> standard search explains itself")
    ctx = build_feature_context("STANDARD", STANDARD_PAYLOAD)
    search = ctx["product_to_standard_search"]
    check("the context type is the feature", ctx["context_type"] == "STANDARD")
    check("the query is carried", search["query"] == "packaged drinking water")
    check("the candidate keeps its verified standard number",
          search["candidates"][0]["standard_number"] == "IS 14543:2016")
    check("the deterministic why-this-result is reused, not regenerated",
          "strong match" in search["candidates"][0]["why_retrieved"])
    check("retrieval confidence is explicitly not legal applicability",
          "NOT a statement that the standard legally applies" in search["what_this_is"])
    check("there is no system result to contradict", "system_result" not in ctx)

    result, provider = run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD")
    check("one call, one answer", len(provider.calls) == 1 and result.context_type == "STANDARD")
    check("the source comes from the application, not the model",
          any("bis.gov.in" in (s["source_url"] or "") for s in result.sources))

    empty = build_feature_context("STANDARD", {"product": "flux capacitor", "results": []})
    check("an unknown product is NOT_AVAILABLE_IN_KNOWLEDGE_BASE, never a guessed standard",
          "NOT_AVAILABLE_IN_KNOWLEDGE_BASE" in empty["product_to_standard_search"]["no_candidate"])


# ------------------------------------------------- C  certification context


def test_grounded_answer_from_certification_context() -> None:
    print("\nC. a certification journey explains itself")
    ctx = build_feature_context("CERTIFICATION", CERTIFICATION_PAYLOAD)
    journey = ctx["certification_guidance"]
    check("the scheme is the one the verified records state", journey["scheme"] == "Scheme I (ISI Mark)")
    check("the route basis is quoted, not inferred",
          "Licences are granted under Scheme I" in journey["route_established_because"][0])
    check("guidance is explicitly not a certification status",
          "NOT a statement that this item" in journey["what_this_is"])
    check("the step's quoted source is in the source book",
          any("apply-online" in (e.get("source_url") or "") for e in ctx["verified_sources"].values()))
    check("the journey's own limitations travel with it", len(journey["limitations"]) == 1)

    missing = build_feature_context("CERTIFICATION", {"question": "?", "journey": None})
    check("no journey is reported as not held, never invented",
          missing["certification_guidance"]["status"] == "NOT_AVAILABLE_IN_KNOWLEDGE_BASE")


# ------------------------------------------------- D  laboratory context


def test_grounded_answer_from_laboratory_context() -> None:
    print("\nD. a laboratory lookup explains itself")
    ctx = build_feature_context("LABORATORY", LAB_PAYLOAD)
    search = ctx["laboratory_search"]
    check("the snapshot limitation is MetrIQ's own wording", search["limitation"] == SNAPSHOT_NOTE)
    check("the user is told to confirm before arranging testing",
          search["before_arranging_testing"] == CURRENTNESS_NOTE)
    check("the standard the listing is against is carried",
          search["standard_the_laboratories_are_listed_against"] == "IS 14543:2016")
    check("a different edition is reported separately, never merged",
          search["other_editions_of_this_standard_listed_separately"] == ["IS 14543:2024"])
    check("the snapshot date travels with the record",
          search["records"][0]["snapshot_retrieved_on"] == "2026-09-19")
    check("no field claims current validity",
          "currently valid" not in json.dumps(ctx).lower())

    empty = build_feature_context("LABORATORY", EMPTY_LAB_PAYLOAD)
    check("no match is MetrIQ's coverage, not a claim about which laboratories exist",
          "NOT_AVAILABLE_IN_KNOWLEDGE_BASE" in empty["laboratory_search"]["no_match"])


# ------------------------------------------------- E  hallmark context


def test_grounded_answer_from_hallmark_context() -> None:
    print("\nE. hallmark evidence explains itself and never authenticates")
    ctx = build_context(HALLMARK_ANALYSIS, "EXPLAIN_HALLMARK")
    hallmark = ctx.get("hallmarking") or {}
    check("the hallmark section is built", bool(hallmark))
    check("verification status can only be NOT_VERIFIED / NOT_DETECTED",
          hallmark["verification_status"] in ("NOT_VERIFIED", "NOT_DETECTED"))
    check("MetrIQ states that official verification is still required",
          hallmark.get("official_verification_required") is True)
    check("the components are observations of the photograph",
          isinstance(hallmark.get("components_observed_in_the_photograph"), list))
    printed = hallmark.get("untrusted_claims_printed_on_the_item") or []
    check("a 'HUID VERIFIED' printed on the item is recorded as untrusted printed text",
          any("VERIFIED" in (o.get("text_printed_on_item") or "").upper() for o in printed))
    metriq_own = dict(hallmark)
    metriq_own.pop("untrusted_claims_printed_on_the_item", None)
    text = json.dumps(metriq_own).lower()
    check("MetrIQ states plainly that an image cannot authenticate a HUID or a hallmark",
          "cannot authenticate" in text)
    for forbidden in ("huid verified", "hallmark is authentic", "is authentic",
                      "the jeweller is registered", "ahc verified"):
        check(f"MetrIQ's own hallmark fields never say '{forbidden}'", forbidden not in text)


# ------------------------------------------------- F  why this result


def test_why_this_result() -> None:
    print("\nF. 'why this result?' explains the evidence MetrIQ has, and MetrIQ produces no verdict")
    check("the capability exists", "EXPLAIN_RESULT" in CAPABILITIES)
    instruction = CAPABILITIES["EXPLAIN_RESULT"]["instruction"]
    check("it forbids stating or implying a compliance verdict",
          "MetrIQ produces no automatic compliance verdict" in instruction)
    check("it forbids saying the item passed or failed",
          "never say it" in instruction and "passed or failed" in instruction)

    result, provider = run_inspection(WATER_ANALYSIS, "EXPLAIN_RESULT")
    check("the evidence reaches the model as the record states it",
          '"product"' in provider.calls[0]["user"])
    check("the response still reports MetrIQ's own escalation state",
          result.escalation_required == WATER_ANALYSIS["escalation"]["required"])

    # The model claiming a compliance verdict changes nothing and is withheld —
    # MetrIQ produces none, so any such claim is fabricated regardless of the case.
    contradiction, _ = run_inspection(WATER_ANALYSIS, "EXPLAIN_RESULT",
                                      text=reply("The overall system result is PASS."))
    check("a generated verdict is withheld",
          contradiction.answer.withheld and
          contradiction.answer.withheld_reason == "FABRICATED_VERDICT")
    check("and MetrIQ's own escalation state is unchanged",
          contradiction.escalation_required == WATER_ANALYSIS["escalation"]["required"])
    check("MetrIQ's confidence records the rejection", contradiction.confidence == "WITHHELD")


# ------------------------------------------------- G-K  what is missing


def test_what_is_missing_keeps_the_four_states_apart() -> None:
    print("\nG-K. 'what is missing?' keeps NOT_DETECTED / UNCERTAIN / VERIFIED_REQUIREMENT / "
          "NOT_AVAILABLE apart")
    check("the capability exists", "WHAT_IS_MISSING" in CAPABILITIES)
    ctx = build_context(WATER_ANALYSIS, "WHAT_IS_MISSING")
    vocab = ctx["evidence_vocabulary"]
    for term in ("NOT_DETECTED", "UNCERTAIN", "VERIFIED_REQUIREMENT", "NOT_ESTABLISHED",
                 "NOT_AVAILABLE_IN_KNOWLEDGE_BASE"):
        check(f"{term} is defined in the context sent to the model", term in vocab)
    check("the five definitions are all different",
          len({vocab[t] for t in ("NOT_DETECTED", "UNCERTAIN", "VERIFIED_REQUIREMENT",
                                  "NOT_ESTABLISHED", "NOT_AVAILABLE_IN_KNOWLEDGE_BASE")}) == 5)
    check("the context says they must not be merged", "Never merge them" in vocab["_note"])

    # H. NOT_DETECTED keeps its meaning wherever it appears.
    not_detected = [d for d in ctx["declarations"] if d.get("status") == "NOT_DETECTED"]
    check("a not-detected declaration is present in this fixture", bool(not_detected))
    check("it is explained as unseen in the photographs, not legally missing",
          all("not seen in the photographs" in d["meaning"] and "not a statement" in d["meaning"]
              for d in not_detected))

    # I. UNCERTAIN keeps the value withheld.
    uncertain = build_context(
        {"declaration_stage": {"fields": [
            {"field": "mrp", "label": "MRP", "status": "UNCERTAIN", "value": None,
             "reason": "OCR read 'Rs. 8O' — the value could not be read reliably."}]}},
        "EXPLAIN_UNCERTAINTY")
    dec = uncertain["declarations"][0]
    check("an uncertain declaration keeps its status and withholds the value",
          dec["status"] == "UNCERTAIN" and dec["value"] is None)
    check("and states why it is uncertain", "could not be read" in dec["reason"])

    # J. VERIFIED_REQUIREMENT / NOT_ESTABLISHED are links to verified requirement
    # data, never a pass or a failure — MetrIQ produces no such verdict.
    check("VERIFIED_REQUIREMENT is defined as a link, never a pass",
          "Not a pass or a failure" in vocab["VERIFIED_REQUIREMENT"])
    check("NOT_ESTABLISHED is defined as MetrIQ's own coverage gap, not a legal statement",
          "does not cover it" in vocab["NOT_ESTABLISHED"])
    coverages = {i.get("requirement_coverage") for i in ctx["declaration_completeness"]["items"]}
    check("declaration completeness items only ever use the two coverage states",
          coverages <= {"VERIFIED_REQUIREMENT", "NOT_ESTABLISHED"})

    # K. NOT_AVAILABLE_IN_KNOWLEDGE_BASE is about MetrIQ's coverage.
    check("NOT_AVAILABLE is defined as MetrIQ's coverage, not reality",
          "coverage" in vocab["NOT_AVAILABLE_IN_KNOWLEDGE_BASE"])
    check("the instruction forbids calling any of them simply 'missing'",
          "Never call any of them simply 'missing'" in CAPABILITIES["WHAT_IS_MISSING"]["instruction"])


# ------------------------------------------------- L  sources


def test_sources_are_preserved_and_never_invented() -> None:
    print("\nL. sources come from the evidence; an invented one is withheld")
    for feature, payload in (("STANDARD", STANDARD_PAYLOAD), ("CERTIFICATION", CERTIFICATION_PAYLOAD),
                             ("LABORATORY", LAB_PAYLOAD)):
        sources = collect_sources(build_feature_context(feature, payload))
        check(f"{feature}: at least one source is carried", bool(sources))
        check(f"{feature}: every source URL came from the payload",
              all((s["source_url"] or "") in json.dumps(payload) for s in sources))

    fabricated, _ = run("LABORATORY", LAB_PAYLOAD, "EXPLAIN_LABORATORY",
                        text=reply("See https://fake-labs.example/list for the current list."))
    check("a URL that is not in the evidence is withheld",
          fabricated.answer.withheld and fabricated.answer.withheld_reason == "FABRICATED_SOURCE")

    quoted, _ = run("LABORATORY", LAB_PAYLOAD, "EXPLAIN_LABORATORY",
                    text=reply("The listing is published at https://lims.bis.gov.in/home/search_is_number/."))
    check("a URL that IS in the evidence is allowed through", not quoted.answer.withheld)


# ------------------------------------------------- M  laboratory snapshot


def test_laboratory_snapshot_wording_is_enforced() -> None:
    print("\nM. a laboratory is listed in a dated snapshot — never current, never ranked")
    ok, _ = run("LABORATORY", LAB_PAYLOAD, "EXPLAIN_LABORATORY",
                text=reply("BIS LIMS listed Aqua Testing Services against IS 14543:2016 at the snapshot date."))
    check("a listing statement is allowed", not ok.answer.withheld)

    for text, reason in (
        ("Aqua Testing Services is NABL accredited.", "LABORATORY_STATUS_CLAIM"),
        ("This laboratory is currently valid for this test.", "LABORATORY_STATUS_CLAIM"),
        ("The laboratory is operational and available now.", "LABORATORY_STATUS_CLAIM"),
        ("Aqua Testing Services is the best laboratory for this product.", "LABORATORY_RANKING_CLAIM"),
        ("The nearest laboratory is the one in Noida.", "LABORATORY_RANKING_CLAIM"),
    ):
        result, _ = run("LABORATORY", LAB_PAYLOAD, "EXPLAIN_LABORATORY", text=reply(text))
        check(f"withheld: {text!r}", result.answer.withheld and result.answer.withheld_reason == reason,
              f"got {result.answer.withheld_reason!r}")

    honest, _ = run("LABORATORY", LAB_PAYLOAD, "EXPLAIN_LABORATORY",
                    text=reply("MetrIQ cannot establish whether this laboratory is accredited today."))
    check("an explicit denial of current status is NOT withheld", not honest.answer.withheld)

    check("the system prompt forbids inferring a current status from snapshot data",
          "Never infer a current status from snapshot data" in SYSTEM_PROMPT)
    check("the system prompt forbids ranking laboratories",
          "never rank laboratories" in SYSTEM_PROMPT)


# ------------------------------------------------- N  hallmark safety


def test_hallmark_and_huid_safety() -> None:
    print("\nN. hallmark / HUID: observation is never authentication")
    for text in (
        "The HUID is verified and the item is authentic.",
        "The hallmark was confirmed real by BIS.",
    ):
        result, _ = run_inspection(HALLMARK_ANALYSIS, "EXPLAIN_HALLMARK", text=reply(text))
        check(f"withheld: {text!r}",
              result.answer.withheld and result.answer.withheld_reason == "AUTHENTICATION_CLAIM")

    observed, _ = run_inspection(
        HALLMARK_ANALYSIS, "EXPLAIN_HALLMARK",
        text=reply("A six-character code was observed in the photograph; it was not verified."))
    check("an observation without a claim is allowed", not observed.answer.withheld)

    for forbidden in ("HUID verified", "HUID authentic", "hallmark authentic",
                      "the jeweller is registered", "AHC verified"):
        check(f"the system prompt names '{forbidden}' as forbidden", forbidden in SYSTEM_PROMPT)


# ------------------------------------------------- O  certification safety


def test_certification_safety() -> None:
    print("\nO. certification: a route, never a certified item and never an invented fee")
    fee, _ = run("CERTIFICATION", CERTIFICATION_PAYLOAD, "EXPLAIN_CERTIFICATION",
                 text=reply("The application fee is Rs. 1,000 and the licence takes 30 days."))
    check("a fee that is not in the evidence is withheld",
          fee.answer.withheld and fee.answer.withheld_reason == "FABRICATED_AMOUNT")

    ok, _ = run("CERTIFICATION", CERTIFICATION_PAYLOAD, "EXPLAIN_CERTIFICATION",
                text=reply("The verified records state that licences are granted under Scheme I."))
    check("a quoted route statement is allowed", not ok.answer.withheld)

    check("the prompt forbids stating a fee, a processing time or a required document",
          "Never state an application fee, a processing time" in SYSTEM_PROMPT)
    check("the prompt forbids saying a product or manufacturer IS certified",
          "say that a product, a manufacturer or an item IS certified" in SYSTEM_PROMPT)
    check("the journey's own limitation about unparsed PDFs reaches the model",
          "does not parse the linked scheme PDFs" in json.dumps(
              build_feature_context("CERTIFICATION", CERTIFICATION_PAYLOAD)))


# ------------------------------------------------- P  multilingual


def test_answer_language_changes_but_evidence_does_not() -> None:
    print("\nP. the answer language changes; the evidence never does")
    english, en_provider = run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD", language="en")
    check("English is the default and adds no language clause",
          en_provider.calls[0]["system"] == SYSTEM_PROMPT and english.language == "en")

    for code, name in (("hi", "Hindi"), ("te", "Telugu")):
        result, provider = run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD", language=code)
        system = provider.calls[0]["system"]
        check(f"{name}: the language clause is appended", f"LANGUAGE OF THE ANSWER: {name}." in system)
        check(f"{name}: identifiers must be reproduced exactly", "never translated" in system)
        check(f"{name}: the response reports the language", result.language == code)
        check(f"{name}: the evidence sent is byte-for-byte the English evidence",
              provider.calls[0]["user"] == en_provider.calls[0]["user"])

    detected, provider = run("STANDARD", STANDARD_PAYLOAD, "QUESTION",
                             question="इस मानक के लिए प्रमाणन क्या है?")
    check("an unrequested language is detected from the question", detected.language == "hi")
    check("the user's own question is sent unmodified",
          "इस मानक के लिए प्रमाणन क्या है?" in provider.calls[0]["user"])

    withheld, _ = run("LABORATORY", LAB_PAYLOAD, "EXPLAIN_LABORATORY", language="te",
                      text=reply("This laboratory is NABL accredited."))
    check("a withheld answer speaks the user's language too",
          withheld.answer.withheld and lang.WITHHELD["te"][:20] in withheld.answer.answer)

    check("app/language.py is still model-free and network-free",
          not any(x in Path("app/language.py").read_text()
                  for x in ("import httpx", "from app.llm", "from app.openrouter")))


# ------------------------------------------------- Q  no unsupported facts


def test_no_unsupported_facts() -> None:
    print("\nQ. nothing the evidence does not contain survives")
    invented, _ = run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD",
                      text=reply("IS 99999:2020 also applies to this product."))
    check("a standard number that is not in the evidence is withheld",
          invented.answer.withheld and invented.answer.withheld_reason == "FABRICATED_STANDARD")

    real, _ = run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD",
                  text=reply("The retrieved candidate is IS 14543:2016."))
    check("a standard number that IS in the evidence is allowed", not real.answer.withheld)

    huid, _ = run_inspection(HALLMARK_ANALYSIS, "EXPLAIN_HALLMARK",
                             text=reply("The HUID XY99ZZ was read from the photograph."))
    check("a HUID that is not in the evidence is withheld",
          huid.answer.withheld and huid.answer.withheld_reason == "FABRICATED_HUID")

    check("the prompt states that the model's own knowledge is not evidence",
          "Your pretrained knowledge NEVER overrides these and is never evidence" in SYSTEM_PROMPT)
    check("the prompt tells it to say when the evidence is insufficient",
          "Insufficient evidence in the inspection record." in SYSTEM_PROMPT)


# ------------------------------------------------- R  failure fallback


def test_provider_failure_never_weakens_metriq() -> None:
    print("\nR. a provider failure leaves every deterministic result intact")
    client = TestClient(app)
    for code, status in (("DAILY_LIMIT", 429), ("RATE_LIMITED", 429), ("TIMEOUT", 503),
                         ("PROVIDER_ERROR", 503), ("NOT_CONFIGURED", 503), ("BAD_RESPONSE", 503)):
        get_copilot.cache_clear()
        app.dependency_overrides[get_copilot] = lambda c=code: InspectionCopilot(
            StubProvider(error=CopilotUnavailable(c)))
        res = client.post("/copilot/explain", json={
            "capability": "EXPLAIN_LABORATORY",
            "context": {"feature": "LABORATORY", "laboratory": LAB_PAYLOAD},
        })
        check(f"{code} -> HTTP {status}", res.status_code == status, f"got {res.status_code}")
        check(f"{code}: the reason is reported in a header",
              res.headers.get("X-Copilot-Reason") == code)
        check(f"{code}: no provider URL or key leaks to the user",
              "openrouter.ai" not in res.text and "sk-" not in res.text)
    app.dependency_overrides.clear()
    get_copilot.cache_clear()

    check("MetrIQ's own laboratory evidence is unaffected by the outage",
          build_feature_context("LABORATORY", LAB_PAYLOAD)["laboratory_search"]["count"] == 1)


# ------------------------------------------------- S  malformed output


def test_malformed_model_output() -> None:
    print("\nS. malformed, truncated and empty model output")
    prose, _ = run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD",
                   text="IS 14543:2016 was retrieved for this product.")
    check("unstructured prose is accepted but flagged",
          not prose.answer.structured and prose.confidence == "UNSTRUCTURED")
    check("and the user is told the evidence was not structured",
          any("structured" in x for x in prose.answer.limitations))

    truncated, _ = run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD",
                       text='{"answer": "IS 14543:2016 was retrieved.", "evidence": [{"claim": "a", '
                            '"source": "b"}], "limitat')
    check("a reply cut short is salvaged, never shown as raw JSON",
          truncated.answer.answer == "IS 14543:2016 was retrieved." and
          "{" not in truncated.answer.answer)
    check("and the user is told it was cut short",
          any("cut short" in x for x in truncated.answer.limitations))

    raised = None
    try:
        run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD", text="   ")
    except CopilotUnavailable as exc:
        raised = exc
    check("an empty reply is a clean BAD_RESPONSE, never an empty answer",
          raised is not None and raised.code == "BAD_RESPONSE")

    raised = None
    try:
        run("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD", text='{"answer": {"nested": true}}')
    except CopilotUnavailable as exc:
        raised = exc
    check("a JSON object whose answer is not text is BAD_RESPONSE, never rendered",
          raised is not None and raised.code == "BAD_RESPONSE")


# ------------------------------------------------- T  API contract


def test_api_contract() -> None:
    print("\nT. the HTTP contract, extended and still strict")
    client = TestClient(app)
    get_copilot.cache_clear()
    provider = StubProvider(reply("Explained.", [{"claim": "c", "source": "s"}], ["limit"]))
    app.dependency_overrides[get_copilot] = lambda: InspectionCopilot(provider)

    res = client.post("/copilot/explain", json={
        "capability": "EXPLAIN_LABORATORY",
        "context": {"feature": "LABORATORY", "laboratory": LAB_PAYLOAD},
        "language": "hi",
    })
    check("a feature context returns 200", res.status_code == 200, res.text[:200])
    body = res.json()
    check("evidence_scope says the evidence was a feature context",
          body["evidence_scope"] == "FEATURE_CONTEXT" and body["context_type"] == "LABORATORY")
    check("there is no escalation state to report for a feature context",
          body["escalation_required"] is None)
    check("the language is reported and is never 'auto'", body["language"] == "hi")
    check("MetrIQ's deterministic confidence is reported",
          body["confidence"] in ("GROUNDED", "UNSTRUCTURED", "WITHHELD"))
    check("sources are returned from the evidence", len(body["sources"]) >= 1)
    check("the free budget is reported", "daily_remaining" in body["usage"])

    bad = [
        ({"capability": "EXPLAIN_LABORATORY"}, "no evidence source"),
        ({"capability": "EXPLAIN_LABORATORY", "inspection_id": "INS-20260919-AAAAAA",
          "context": {"feature": "LABORATORY", "laboratory": LAB_PAYLOAD}}, "two evidence sources"),
        ({"capability": "EXPLAIN_STANDARD",
          "context": {"feature": "LABORATORY", "laboratory": LAB_PAYLOAD}},
         "a capability the feature does not allow"),
        ({"capability": "EXPLAIN_LABORATORY", "context": {"feature": "LABORATORY"}},
         "a feature with no payload"),
        ({"capability": "EXPLAIN_LABORATORY",
          "context": {"feature": "TELEPORTER", "laboratory": LAB_PAYLOAD}}, "an unknown feature"),
        ({"capability": "EXPLAIN_LABORATORY", "language": "fr",
          "context": {"feature": "LABORATORY", "laboratory": LAB_PAYLOAD}}, "an unsupported language"),
        ({"capability": "EXPLAIN_LABORATORY", "system_result": "PASS",
          "context": {"feature": "LABORATORY", "laboratory": LAB_PAYLOAD}},
         "a field that could carry a result"),
    ]
    for payload, why in bad:
        res = client.post("/copilot/explain", json=payload)
        check(f"422 for {why}", res.status_code == 422, f"got {res.status_code}")

    res = client.get("/copilot/status")
    codes = {c["code"] for c in res.json()["capabilities"]}
    check("the status endpoint lists the new capabilities",
          {"EXPLAIN_RESULT", "WHAT_IS_MISSING", "EXPLAIN_STANDARD", "EXPLAIN_LABORATORY"} <= codes)
    check("the status endpoint never returns a key",
          "api_key" not in res.text and "sk-" not in res.text)

    # An inspection request with no language behaves exactly as before.
    res = client.post("/copilot/explain", json={
        "capability": "EXPLAIN_INSPECTION", "analysis": WATER_ANALYSIS})
    check("the pre-existing inspection request shape still works", res.status_code == 200, res.text[:200])
    check("and its escalation state is still the record's",
          res.json()["escalation_required"] == WATER_ANALYSIS["escalation"]["required"])

    app.dependency_overrides.clear()
    get_copilot.cache_clear()


# ------------------------------------------------- U/V  isolation and quota


def test_explaining_changes_nothing_and_costs_one_call() -> None:
    print("\nU-V. the copilot changes no result and makes exactly one call")
    before = copy.deepcopy(WATER_ANALYSIS)
    provider = StubProvider(reply("Explained."))
    copilot = InspectionCopilot(provider)
    copilot.explain(WATER_ANALYSIS, "EXPLAIN_RESULT")
    copilot.explain(WATER_ANALYSIS, "WHAT_IS_MISSING")
    copilot.explain_feature("LABORATORY", LAB_PAYLOAD, "EXPLAIN_LABORATORY")
    copilot.explain_feature("STANDARD", STANDARD_PAYLOAD, "EXPLAIN_STANDARD")
    check("the analysis is untouched by any number of explanations", WATER_ANALYSIS == before)
    check("four user actions -> exactly four provider calls", len(provider.calls) == 4)

    payloads = {"STANDARD": copy.deepcopy(STANDARD_PAYLOAD),
                "CERTIFICATION": copy.deepcopy(CERTIFICATION_PAYLOAD),
                "LABORATORY": copy.deepcopy(LAB_PAYLOAD)}
    for feature, payload in payloads.items():
        build_feature_context(feature, payload)
    check("building a context never mutates the payload",
          payloads == {"STANDARD": STANDARD_PAYLOAD, "CERTIFICATION": CERTIFICATION_PAYLOAD,
                       "LABORATORY": LAB_PAYLOAD})

    source = Path("app/copilot.py").read_text() + Path("app/copilot_api.py").read_text()
    for forbidden in ("from app.compliance", "from app.pipeline", "from app.package_label",
                      "from app.declarations", "from app.ocr", "from app.product_identification",
                      "from app.requirements", "from app.hallmark", "from app.report",
                      "from app.retrieval", "from app.rag"):
        check(f"the copilot still cannot recompute anything ({forbidden.split('.')[-1]})",
              forbidden not in source)
    check("the copilot never writes to the database",
          not any(x in source for x in ("session.commit", "session.add", "apply_review")))

    # Every feature capability is a real capability with an instruction.
    for feature in FEATURES:
        for capability in FEATURE_CAPABILITIES[feature]:
            check(f"{feature}/{capability} is a defined capability", capability in CAPABILITIES)

    check("no capability sends every section by accident",
          len(CAPABILITIES["EXPLAIN_STANDARD"]["sections"]) < len(CAPABILITIES["QUESTION"]["sections"]))

    prompt = render_prompt(build_feature_context("LABORATORY", LAB_PAYLOAD), "EXPLAIN_LABORATORY", "q")
    check("a feature prompt carries no untrusted package block (there is no OCR here)",
          "<<<UNTRUSTED_PACKAGE_TEXT>>>" not in prompt)
    check("and stays small", len(prompt) < 12_000, f"{len(prompt)} chars")


def main() -> int:
    test_grounded_answer_from_inspection_context()
    test_laboratory_evidence_reaches_the_inspection_context()
    test_grounded_answer_from_standard_context()
    test_grounded_answer_from_certification_context()
    test_grounded_answer_from_laboratory_context()
    test_grounded_answer_from_hallmark_context()
    test_why_this_result()
    test_what_is_missing_keeps_the_four_states_apart()
    test_sources_are_preserved_and_never_invented()
    test_laboratory_snapshot_wording_is_enforced()
    test_hallmark_and_huid_safety()
    test_certification_safety()
    test_answer_language_changes_but_evidence_does_not()
    test_no_unsupported_facts()
    test_provider_failure_never_weakens_metriq()
    test_malformed_model_output()
    test_api_contract()
    test_explaining_changes_nothing_and_costs_one_call()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
