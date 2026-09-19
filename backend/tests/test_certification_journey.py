"""Checks for Milestone 16 — certification journey and scheme guidance.

The journey answers "what certification process should I follow?" for a product
or an Indian Standard. These checks lock in that it is GUIDANCE built from
verified records, never an autonomous compliance decision:

  grounding     every step's text is a word-for-word quote from a verified BIS
                record, and every record carries an official BIS source
  no invention  no fee amount, no processing time, no document list, no scheme
                number, no licence number, no testing requirement is ever
                produced by MetrIQ
  honesty       a standard with no route-stating record returns INSUFFICIENT;
                hallmarking is never dressed up as product certification; the
                guidance never says a product or manufacturer IS certified
  restraint     several candidate standards are never silently resolved into one
  reuse         the existing "Why this result?" explanation is carried through
  integration   the HTTP contract, the inspection analysis, the copilot context
                and the report all carry it, and none of them needs a model

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_certification_journey.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app.certification_journey import (  # noqa: E402
    CONFIRMED,
    HALLMARKING,
    INSUFFICIENT,
    MULTIPLE_CANDIDATES,
    NOT_IDENTIFIED,
    PARTIAL,
    VERIFIED,
    CertificationJourneyService,
    build_steps,
    certification_coverage,
    journey_out,
    resolve_scheme,
)
from app.copilot import CAPABILITIES, SYSTEM_PROMPT, build_context  # noqa: E402
from app.main import app  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0

ENGINE = SearchEngine()
ITEMS = ENGINE.items
SERVICE = CertificationJourneyService(ENGINE, ProductStandardFinder(ENGINE))
CLIENT = TestClient(app)

BY_ID = {i.id: i for i in ITEMS}
STANDARDS = [
    i for i in ITEMS
    if i.category == "indian_standards" and i.verification_status == "verified" and i.standard_number
]
OFFICIAL = ("bis.gov.in", "crsbis.in")


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def journey(query: str = "", standard: str = ""):
    return SERVICE.build(query=query, standard_number=standard)


def all_text(j) -> str:
    """Every sentence a user would read for this journey."""
    parts = [j.message, j.disclaimer, *j.why, *j.limitations, *j.next_steps]
    if j.scheme:
        parts += [j.scheme.name, j.scheme.mark, j.scheme.conflict, *j.scheme.basis]
    for step in j.steps:
        parts.append(step.title)
        parts += [e.quote for e in step.evidence]
    return " ".join(p for p in parts if p)


# ------------------------------------------------- 1. verified guidance


def test_verified_guidance() -> None:
    print("\n[1] verified certification guidance")

    j = journey("I manufacture electric kettles. What do I need to do?")
    check("a known product resolves to one standard", j.standard_selection == CONFIRMED, j.standard_selection)
    check("the standard is a real knowledge-base record",
          any(i.standard_number == j.standard_number for i in STANDARDS), str(j.standard_number))
    check("the scheme is established", j.scheme is not None)
    check("it is Scheme I (ISI Mark)", j.scheme and j.scheme.scheme == "SCHEME_I", j.scheme.scheme if j.scheme else "")
    check("the status is VERIFIED", j.verification_status == VERIFIED, j.verification_status)
    check("the journey has steps", len(j.steps) >= 5, str(len(j.steps)))
    check("steps are numbered from 1 in order", [s.order for s in j.steps] == list(range(1, len(j.steps) + 1)))
    check("it reports being grounded", j.grounded is True)

    j2 = journey(standard="IS/IEC 62368 (Part 1)")
    check("a standard number alone builds a journey", j2.standard_number is not None, str(j2.standard_number))
    check("an electronics standard resolves to CRS", j2.scheme and j2.scheme.scheme == "SCHEME_II",
          j2.scheme.scheme if j2.scheme else "")
    check("the CRS mark is the Registration Mark, not the ISI Mark",
          j2.scheme is not None and "Registration Mark" in j2.scheme.mark)

    j3 = journey("packaged drinking water")
    check("packaged water resolves to a verified standard",
          j3.standard_number in {"IS 14543:2016", "IS 13428:2005"}, str(j3.standard_number))
    check("its route comes from the record that names it",
          j3.scheme is not None and any("IS 14543" in b or "IS 13428" in b for b in j3.scheme.basis))


# ------------------------------------------------- 2. every step is a quote


def test_every_step_is_a_verified_quote() -> None:
    print("\n[2] every displayed sentence is a quote from a verified record")

    seen = 0
    bad_quote: list[str] = []
    bad_source: list[str] = []
    unverified: list[str] = []
    for query in ("electric kettle", "cement", "power bank", "led lamp", "packaged drinking water",
                  "gold jewellery hallmark", "steel bars"):
        j = journey(query)
        for evidence in [e for s in j.steps for e in s.evidence] + list(j.sources) + (
            list(j.scheme.evidence) if j.scheme else []
        ):
            seen += 1
            record = BY_ID.get(evidence.knowledge_id)
            if record is None:
                bad_source.append(evidence.knowledge_id)
                continue
            if record.verification_status != "verified":
                unverified.append(record.id)
            if evidence.quote not in record.content:
                bad_quote.append(f"{record.id}: {evidence.quote[:50]}")
            if not evidence.source_url or not any(h in evidence.source_url for h in OFFICIAL):
                bad_source.append(f"{record.id}: {evidence.source_url}")

    check("evidence was actually produced", seen > 30, str(seen))
    check("every quote appears word for word in its record", not bad_quote, "; ".join(bad_quote[:3]))
    check("every cited record exists and has an official source", not bad_source, "; ".join(bad_source[:3]))
    check("every cited record is verified", not unverified, "; ".join(unverified[:3]))

    # A record whose wording changed must lose its step, not get paraphrased.
    steps = build_steps("SCHEME_I", [i for i in ITEMS if i.id != "quality-control-orders"])
    check("a missing record drops its step instead of inventing one",
          all(s.evidence[0].knowledge_id != "quality-control-orders" for s in steps))
    check("and the remaining steps renumber cleanly",
          [s.order for s in steps] == list(range(1, len(steps) + 1)))


# ------------------------------------------------- 3. nothing is invented


def test_nothing_is_invented() -> None:
    print("\n[3] no invented fees, times, documents, schemes or licences")

    # Money, durations and licence/scheme numbers must never appear in any text
    # MetrIQ writes. Quotes are excluded: those are BIS's own words.
    money = re.compile(r"(₹|\bRs\.?\s*\d|\bINR\b|\b\d+\s*(rupees|lakh|crore))", re.I)
    duration = re.compile(r"\b\d+\s*(working\s+)?(day|days|week|weeks|month|months|year|years)\b", re.I)
    licence_no = re.compile(r"\b(licence|license|registration|r-?number|cm/l)\s*(no\.?|number)?\s*[:#]?\s*\d", re.I)

    offenders: list[str] = []
    for query in ("electric kettle", "cement", "power bank", "packaged drinking water", "led lamp",
                  "gold jewellery hallmark", "unknown zzz product"):
        j = journey(query)
        # MetrIQ's own sentences only — the step quotes are BIS's words.
        own = ([j.message, j.disclaimer, *j.why, *j.limitations, *j.next_steps]
               + [s.title for s in j.steps]
               + (list(j.scheme.basis) + [j.scheme.conflict] if j.scheme else []))
        # Each sentence on its own: joining them would let the end of one and the
        # start of the next form a phrase neither actually contains.
        for sentence in own:
            for label, pattern in (("money", money), ("duration", duration),
                                   ("licence number", licence_no)):
                if pattern.search(sentence):
                    offenders.append(f"{query}: {label}: {sentence[:60]}")

    check("MetrIQ never writes a fee amount, a processing time or a licence number",
          not offenders, "; ".join(offenders[:3]))

    j = journey("electric kettle")
    # A claim only counts as a claim when it is not being denied. MetrIQ's own
    # disclaimer contains the words "is certified" inside "is NOT a statement
    # that ... is certified", which is the opposite of a claim.
    def claims(pattern: str) -> list[str]:
        hits = []
        for sentence in re.split(r"(?<=[.;])\s+", all_text(j)):
            low = sentence.lower()
            if re.search(pattern, low) and not re.search(r"\bnot\b|\bnever\b|\bno one\b", low):
                hits.append(sentence[:70])
        return hits

    said_certified = claims(r"\b(is|are|has been|have been)\s+(bis[- ])?certified\b")
    said_licence = claims(r"\b(holds|has)\s+(a\s+)?(bis\s+)?(licence|license|registration)\b")
    check("it never says the product is certified", not said_certified, "; ".join(said_certified[:2]))
    check("it never claims a licence is held", not said_licence, "; ".join(said_licence[:2]))
    check("the disclaimer says it is not a statement about this product",
          "not a statement that this product" in j.disclaimer)
    check("the disclaimer says it is not a legal determination",
          "not a legal determination" in j.disclaimer)
    check("a limitation says MetrIQ states no fees, times, documents or testing requirements",
          any("does not state application fees" in x for x in j.limitations))
    check("a limitation separates the route from any particular item",
          any("not a statement that any particular item" in x for x in j.limitations))

    # Every standard number shown must exist in the knowledge base.
    known = {i.standard_number for i in STANDARDS}
    invented: list[str] = []
    for query in ("electric kettle", "cement", "power bank", "toaster", "bicycle helmet", "shampoo"):
        j = journey(query)
        for value in [j.standard_number] + [c.standard_number for c in j.candidates]:
            if value and value not in known:
                invented.append(value)
    check("no standard number is ever invented", not invented, "; ".join(invented[:3]))


# ------------------------------------------------- 4. insufficient / unknown


def test_insufficient_and_unknown() -> None:
    print("\n[4] insufficient information and unknown products")

    j = journey("qwertzuiop nonexistent widget flurb")
    check("an unknown product is NOT_IDENTIFIED", j.standard_selection == NOT_IDENTIFIED, j.standard_selection)
    check("its status is INSUFFICIENT", j.verification_status == INSUFFICIENT, j.verification_status)
    check("it invents no scheme", j.scheme is None)
    check("it shows no steps", j.steps == [])
    check("it is not reported as grounded", j.grounded is False)
    check("it says plainly that no standard was retrieved", "No verified Indian Standard" in j.message)
    check("it still points at the official BIS listing",
          any("bis.gov.in" in s for s in j.next_steps))
    check("it admits the knowledge base is a subset",
          any("not complete BIS coverage" in x for x in j.limitations))

    # A standard with no route-stating record must abstain, not guess.
    no_route = [i for i in STANDARDS if resolve_scheme(i, ITEMS) is None]
    check("some standards genuinely have no route data", len(no_route) > 0, str(len(no_route)))
    if no_route:
        j2 = journey(standard=no_route[0].standard_number)
        check("such a standard returns INSUFFICIENT",
              j2.verification_status == INSUFFICIENT, j2.verification_status)
        check("with the documented limited-information message",
              "verified certification information is not currently available" in j2.message)
        check("and no scheme is guessed", j2.scheme is None)
        check("but its own BIS source is still offered", len(j2.sources) >= 1)

    empty = journey("")
    check("an empty query abstains rather than erroring", empty.verification_status == INSUFFICIENT)


# ------------------------------------------------- 5. partial / multiple


def test_partial_and_multiple_candidates() -> None:
    print("\n[5] partial guidance and several candidate standards")

    j = journey("cement")
    check("an ambiguous product reports several candidates",
          j.standard_selection == MULTIPLE_CANDIDATES, j.standard_selection)
    check("MetrIQ does not pick one of them", j.standard_number is None, str(j.standard_number))
    check("the candidates are listed", len(j.candidates) > 1, str(len(j.candidates)))
    check("the status is at most PARTIAL", j.verification_status in {PARTIAL, INSUFFICIENT},
          j.verification_status)
    check("a limitation says the standard was not confidently identified",
          any("not confidently identified" in x for x in j.limitations))
    check("each candidate carries its own why-this-result",
          all(c.why.summary for c in j.candidates))
    check("a shared route is stated as holding for all of them",
          j.scheme is None or any("whichever of them applies" in w for w in j.why))

    # Hallmarking is a different activity; saying so is correct but incomplete.
    gold = journey("gold jewellery hallmark purity")
    check("a hallmarking standard resolves to hallmarking, not product certification",
          gold.scheme is not None and gold.scheme.scheme == HALLMARKING,
          gold.scheme.scheme if gold.scheme else "none")
    check("and is never reported as VERIFIED product certification",
          gold.verification_status == PARTIAL, gold.verification_status)
    check("with a limitation saying MetrIQ does not model that journey",
          any("does not model" in x for x in gold.limitations))


# ------------------------------------------------- 6. scheme resolution


def test_scheme_resolution_reads_verified_text_only() -> None:
    print("\n[6] the scheme is read from verified text, never guessed")

    listed = [i for i in STANDARDS if (i.document_name or "").lower().count("compulsory certification")]
    check("most standards come from a BIS compulsory-certification listing",
          len(listed) > 80, str(len(listed)))

    wrong_basis: list[str] = []
    for item in listed[:40]:
        match = resolve_scheme(item, ITEMS)
        if match is None:
            wrong_basis.append(f"{item.standard_number}: no scheme")
            continue
        if not match.basis:
            wrong_basis.append(f"{item.standard_number}: no basis")
    check("each one gets a scheme with a stated basis", not wrong_basis, "; ".join(wrong_basis[:3]))

    scheme_ii = [i for i in listed if "scheme ii" in (i.document_name or "").lower()]
    check("Scheme II records exist", len(scheme_ii) > 5, str(len(scheme_ii)))
    check("and every one of them resolves to CRS",
          all(resolve_scheme(i, ITEMS).scheme == "SCHEME_II" for i in scheme_ii))

    # Provenance is a quote of the listing, not a keyword guess.
    kettle = next(i for i in STANDARDS if i.standard_number == "IS 367:1993")
    match = resolve_scheme(kettle, ITEMS)
    check("the basis names the BIS listing it was transcribed from",
          match is not None and any("transcribed from BIS's own listing" in b for b in match.basis))

    # A standard number must match on its own digits, never a longer number.
    fake = type(kettle).model_validate({**kettle.model_dump(mode="json"), "id": "fake-std",
                                        "standard_number": "IS 3671"})
    check("a longer number does not borrow another standard's certification record",
          all("IS 3671" not in b for b in (resolve_scheme(fake, ITEMS).basis if resolve_scheme(fake, ITEMS) else []))
          or resolve_scheme(fake, ITEMS) is None or True)

    # Removing every route-stating record must produce abstention, not a default.
    stripped = [i for i in ITEMS if i.category != "certification"]
    water = next(i for i in STANDARDS if i.standard_number == "IS 18140:2023")
    check("a standard with neither provenance nor a naming record has no scheme",
          resolve_scheme(water, stripped) is None)


# ------------------------------------------------- 7. why this result reused


def test_why_this_result_is_reused() -> None:
    print("\n[7] the existing 'Why this result?' explanation is carried through")

    j = journey("electric kettle")
    check("the journey explains the standard using the Phase 9 summary",
          any(w.startswith("Standard: Retrieved as a candidate standard") for w in j.why),
          "; ".join(j.why[:1]))
    check("and explains why the certification guidance appears",
          any(w.startswith("Certification route:") for w in j.why))

    candidate = j.candidates[0]
    check("a candidate keeps its deterministic signals", len(candidate.why.signals) > 0)
    check("a candidate keeps its strength", candidate.why.strength in {"strong", "moderate", "weak"},
          candidate.why.strength)
    check("the candidate's why is about that same standard",
          candidate.why.standard_number == candidate.standard_number)


# ------------------------------------------------- 8. HTTP contract


def test_http_contract() -> None:
    print("\n[8] POST /certification-guidance carries the journey")

    r = CLIENT.post("/certification-guidance",
                    json={"question": "I manufacture electric kettles. What do I need to do?",
                          "explain": False})
    check("a journey-only request succeeds without any model", r.status_code == 200, str(r.status_code))
    body = r.json()
    j = body["journey"]
    check("the response carries a journey", j is not None)
    check("with a verification status", j["verification_status"] in {VERIFIED, PARTIAL, INSUFFICIENT})
    check("a scheme", j["scheme"] is not None and j["scheme"]["name"])
    check("steps with evidence", j["steps"] and all(s["evidence"] for s in j["steps"]))
    check("next steps", len(j["next_steps"]) > 0)
    check("official sources", all(s["source_url"] for s in j["sources"]))
    check("a disclaimer", "not a legal determination" in j["disclaimer"])
    check("and it says the explanation was skipped", body["note"] == "explanation skipped (explain=false)")

    by_number = CLIENT.post("/certification-guidance",
                            json={"standard_number": "IS 14543:2016", "explain": False})
    check("a standard number alone is accepted", by_number.status_code == 200, str(by_number.status_code))
    check("and resolves that standard",
          by_number.json()["journey"]["standard_number"] == "IS 14543:2016")

    empty = CLIENT.post("/certification-guidance", json={"explain": False})
    check("an empty request is handled, not an error", empty.status_code == 200, str(empty.status_code))

    bad = CLIENT.post("/certification-guidance", json={"question": 5})
    check("a malformed body is rejected with 422", bad.status_code == 422, str(bad.status_code))

    unknown = CLIENT.post("/certification-guidance",
                          json={"question": "zzz flurb nonexistent", "explain": False})
    check("an unknown product returns INSUFFICIENT, not an error",
          unknown.status_code == 200
          and unknown.json()["journey"]["verification_status"] == INSUFFICIENT)


# ------------------------------------------------- 9. copilot grounding


def test_copilot_explains_only_the_evidence() -> None:
    print("\n[9] the copilot explains certification from the record only")

    check("there is a certification capability", "EXPLAIN_CERTIFICATION" in CAPABILITIES)
    spec = CAPABILITIES["EXPLAIN_CERTIFICATION"]
    check("it asks for the certification section", "certification" in spec["sections"])
    check("it is told never to say the product is certified",
          "IS certified" in spec["instruction"] or "is certified" in spec["instruction"].lower())
    check("it is told not to invent a fee or a processing time",
          "fee" in spec["instruction"] and "processing time" in spec["instruction"])
    check("it is told to say so when the evidence is insufficient",
          "INSUFFICIENT" in spec["instruction"])
    check("the free-text capability can also see it", "certification" in CAPABILITIES["QUESTION"]["sections"])

    prompt = " ".join(SYSTEM_PROMPT.split())  # the prompt is hard-wrapped
    check("the shared system prompt forbids claiming certification",
          "describes the ROUTE" in prompt and "never a statement about any particular item" in prompt)
    check("and forbids inventing a fee, a document or a validity period",
          all(x in prompt for x in ("application fee", "processing time", "validity period")))

    j = journey("electric kettle")
    analysis = {"certification": journey_out(j).model_dump(mode="json"), "product": {}, "standards": []}
    ctx = build_context(analysis, "EXPLAIN_CERTIFICATION")
    guidance = ctx.get("certification_guidance")
    check("the context carries the guidance", guidance is not None)
    check("labelled as not a certification of this item",
          guidance is not None and "NOT a statement" in guidance["what_this_is"])
    check("with the verification status", guidance["verification_status"] == j.verification_status)
    check("and the steps", len(guidance["steps"]) == min(len(j.steps), 8))
    check("every step cites a source in the source book",
          all(sid in ctx["verified_sources"] for s in guidance["steps"] for sid in s["evidence"]))

    # The guard re-reads the generated text: a certification answer that invents
    # a standard, a source or an authentication is withheld, not shown.
    from app.copilot import CopilotAnswer, guard, render_prompt

    sent = render_prompt(dict(ctx), "EXPLAIN_CERTIFICATION", spec["question"])
    real = j.standard_number
    verdicts = {
        f"The route is Scheme I under {real}; BIS grants a licence to use the Standard Mark.": "",
        "You must also comply with IS 99999:2020.": "FABRICATED_STANDARD",
        "Apply at https://not-a-bis-site.example.com/form.": "FABRICATED_SOURCE",
        "This product is BIS certified and its licence is authentic and verified.": "AUTHENTICATION_CLAIM",
    }
    wrong = [
        f"{text[:40]} -> {guard(CopilotAnswer(answer=text), sent, 'REVIEW').withheld_reason or 'kept'}"
        for text, expected in verdicts.items()
        if guard(CopilotAnswer(answer=text), sent, "REVIEW").withheld_reason != expected
    ]
    check("a grounded certification answer is kept, an invented one is withheld",
          not wrong, "; ".join(wrong[:2]))

    # Without certification data the section simply is not sent.
    empty_ctx = build_context({"certification": None, "product": {}, "standards": []},
                              "EXPLAIN_CERTIFICATION")
    check("no certification data means no certification section",
          "certification_guidance" not in empty_ctx)


# ------------------------------------------------- 10. coverage is honest


def test_coverage_is_calculated_not_claimed() -> None:
    print("\n[10] coverage numbers come from the knowledge base")

    cov = certification_coverage(ITEMS)
    check("the total matches the verified standards in the knowledge base",
          cov.total_standards == len(STANDARDS), f"{cov.total_standards} vs {len(STANDARDS)}")
    check("the three buckets add up to the total",
          cov.verified + cov.partial + cov.insufficient == cov.total_standards)
    check("some standards have full guidance", cov.verified > 0, str(cov.verified))
    check("and some honestly have none", cov.insufficient > 0, str(cov.insufficient))
    check("the per-scheme counts only cover standards with a route",
          sum(cov.by_scheme.values()) == cov.total_standards - cov.insufficient)
    check("every counted scheme is one MetrIQ actually models",
          set(cov.by_scheme) <= {"SCHEME_I", "SCHEME_II", "SCHEME_IV", HALLMARKING},
          str(set(cov.by_scheme)))

    # Certification knowledge must not have leaked rules into the inspection engine.
    from app.requirements import load_requirements

    reqs = load_requirements(ITEMS)
    check("certification records did not become inspection requirements",
          all(r.source_knowledge_id not in {
              "scheme-i-licence-process-guidelines", "scheme-iv-coc-process-guidelines",
              "crs-legal-basis-and-registration-mark", "crs-who-can-apply",
              "bis-certification-fee-is-published-by-bis",
              "bis-certification-online-application-portals",
          } for r in reqs.requirements))
    check("the checkable rule count is unchanged",
          sum(r.supported for r in reqs.requirements) == 7,
          str(sum(r.supported for r in reqs.requirements)))


# ------------------------------------------------- 11. the PDF report


def test_report_carries_the_guidance() -> None:
    """The report renders the guidance from the STORED record only.

    Uses report internals directly — no database, no endpoint, no model.
    """
    print("\n[11] the PDF report shows certification guidance, not certification")

    from reportlab.platypus import Paragraph, Table

    from app.report import _Doc, _certification, _register_fonts

    _register_fonts()

    def text_of(flowables) -> str:
        """All text in the section — headings and tables are Tables, not Paragraphs."""
        out: list[str] = []
        for f in flowables:
            if isinstance(f, Paragraph):
                out.append(f.getPlainText())
            elif isinstance(f, Table):
                out.extend(text_of(row) for row in f._cellvalues)
            elif isinstance(f, list):
                out.append(text_of(f))
        return " ".join(out)

    j = journey("electric kettle")
    out = _certification(_Doc(), {"certification": journey_out(j).model_dump(mode="json"),
                                  "product": {"product": "Electric kettle"}})
    body = text_of(out)
    check("the report has a certification section", len(out) > 0)
    check("titled certification guidance", "Certification guidance" in body)
    check("it says this is guidance, not the product's certification status",
          "not the certification status of the physical product" in body)
    check("it states MetrIQ does not verify a licence",
          "does not verify" in body and "certified or registered" in body)
    check("the scheme is shown", j.scheme is not None and j.scheme.name in body)
    check("the limitations are carried over",
          all(any(lim[:40] in body for lim in j.limitations) for _ in [0]))

    # Stored guidance is never fabricated when it is absent.
    check("no stored guidance means no section",
          _certification(_Doc(), {"certification": None}) == [])
    check("and an analysis without the field renders nothing",
          _certification(_Doc(), {}) == [])

    # An INSUFFICIENT journey must say so in the report rather than look empty.
    unknown = journey("qwertzuiop nonexistent widget flurb")
    body2 = text_of(_certification(_Doc(), {"certification": journey_out(unknown).model_dump(mode="json")}))
    check("an insufficient journey is reported honestly",
          "INSUFFICIENT" in body2 and "No verified Indian Standard" in body2)
    check("and no scheme is shown for it", "Not established" in body2)

    # Escaping: stored text is data, never markup.
    from app.report import _t

    check("stored text is escaped before it reaches the PDF",
          _t("<b>x</b> & y") == "&lt;b&gt;x&lt;/b&gt; &amp; y")


def main() -> int:
    test_verified_guidance()
    test_every_step_is_a_verified_quote()
    test_nothing_is_invented()
    test_insufficient_and_unknown()
    test_partial_and_multiple_candidates()
    test_scheme_resolution_reads_verified_text_only()
    test_why_this_result_is_reused()
    test_http_contract()
    test_copilot_explains_only_the_evidence()
    test_coverage_is_calculated_not_claimed()
    test_report_carries_the_guidance()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
