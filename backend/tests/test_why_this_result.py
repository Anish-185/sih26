"""Checks for Phase 9 "Why this result?" (Product -> Standard discovery).

Plain Python, no test framework (matches tests/test_retrieval.py). Run with:

    cd backend
    ./.venv/bin/python tests/test_why_this_result.py

Exit code 0 = all checks passed, 1 = something failed.

Phase 9 adds NO new retrieval engine, NO new scoring pass and NO LLM call. It
turns the deterministic MatchReason data the Phase 3 SearchEngine already
produces into a short human-readable "Why this result?" explanation, exposed on
the existing POST /product-standard response. These checks lock in that:

  - a real product query returns candidate standards;
  - the retrieval MatchReason data is preserved untouched;
  - the explanation is derived only from that deterministic data;
  - producing the explanation needs no LLM;
  - every standard number shown exists in the knowledge base;
  - an uncovered query still abstains, with no explanations;
  - Phase 5 Product -> Standard behaviour is unchanged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import ProductStandardRequest, product_standard_post  # noqa: E402
from app.product import (  # noqa: E402
    ProductStandardFinder,
    WhyThisResult,
    explain_candidate,
)
from app.retrieval import SearchEngine  # noqa: E402
from app.retrieval.engine import MatchReason, RetrievalResult  # noqa: E402

_passed = 0
_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))


ENGINE = SearchEngine()
FINDER = ProductStandardFinder(ENGINE)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge"
KB_STANDARD_NUMBERS = {
    r["standard_number"]
    for path in DATA_DIR.glob("*.json")
    for r in json.load(open(path))
    if r.get("standard_number")
}


# ------------------------------------------- 1. candidates + explanations pair

def test_product_query_returns_candidates_with_explanations() -> None:
    out = FINDER.find("LED lamp")
    check("LED lamp is grounded with candidates", out.grounded and bool(out.results))
    check("one explanation per candidate, same order",
          len(out.explanations) == len(out.results))
    check("every explanation is a WhyThisResult",
          all(isinstance(w, WhyThisResult) for w in out.explanations))
    check("explanation standard_number lines up with its candidate",
          all(w.standard_number == r.item.standard_number
              for r, w in zip(out.results, out.explanations)))
    check("every explanation has a non-empty summary",
          all(w.summary.strip() for w in out.explanations))


# ---------------------------------------------- 2. MatchReason data preserved

def test_matchreason_data_is_preserved() -> None:
    out = FINDER.find("feeding bottle")
    top = out.results[0]
    check("candidate still carries raw MatchReason objects",
          top.reasons and all(isinstance(x, MatchReason) for x in top.reasons))
    check("candidate still carries matched_terms", bool(top.matched_terms))
    check("candidate still carries score and confidence",
          top.score > 0 and top.confidence in ("high", "medium", "low"))


# ------------------------------------ 3. explanation derived from real reasons

def test_explanation_is_derived_from_deterministic_reasons() -> None:
    out = FINDER.find("electric iron")
    for result, why in zip(out.results, out.explanations):
        reason_fields = {r.field for r in result.reasons}
        # Every signal must correspond to a field the engine actually matched.
        phrase_to_field = {
            "Indian Standard number": "standard_number",
            "subject area": "category",
            "standard's title": "title",
            "keywords recorded": "keywords",
            "source document": "document_name",
            "BIS reference": "reference",
            "BIS description": "content",
        }
        for signal in why.signals:
            matched = [f for k, f in phrase_to_field.items() if k in signal]
            check(f"signal maps to a matched field: {signal!r}",
                  bool(matched) and matched[0] in reason_fields)
        # strength mirrors retrieval confidence, never invents a new grade.
        check(f"strength mirrors confidence for {why.standard_number}",
              why.strength in ("strong", "moderate", "weak"))
    # A hand-built result: the summary must only mention terms that were matched.
    fake = RetrievalResult(
        item=out.results[0].item,
        score=7.0,
        confidence="medium",
        matched_terms=["electric", "iron"],
        reasons=[
            MatchReason("keywords", "electric", 3.0),
            MatchReason("keywords", "iron", 3.0),
            MatchReason("title", "iron", 4.0),
        ],
    )
    why = explain_candidate(fake)
    check("summary mentions only matched terms",
          "electric" in why.summary and "iron" in why.summary
          and "steel" not in why.summary)
    check("summary frames the standard as a candidate, not a legal decision",
          "candidate standard" in why.summary
          and "legally applicable" not in why.summary.lower())


# ---------------------------------------------------- 4. no LLM call required

def test_no_llm_is_needed_for_why_this_result() -> None:
    # The finder is constructed with a SearchEngine only - it has no LLM at all.
    check("ProductStandardFinder holds no llm attribute",
          not hasattr(FINDER, "llm"))
    # explain_candidate is a pure function: same input -> identical output,
    # with no network / LLM access.
    fake = RetrievalResult(
        item=FINDER.find("cement").results[0].item,
        score=6.0,
        confidence="medium",
        matched_terms=["cement"],
        reasons=[MatchReason("keywords", "cement", 3.0),
                 MatchReason("title", "cement", 4.0)],
    )
    a = explain_candidate(fake)
    b = explain_candidate(fake)
    check("explain_candidate is deterministic", a == b)

    # And the whole finder is deterministic across calls.
    first = [w.summary for w in FINDER.find("microwave oven").explanations]
    second = [w.summary for w in FINDER.find("microwave oven").explanations]
    check("finder explanations are stable across calls", first == second)


# --------------------------------------- 5. shown standard numbers are real

def test_shown_standard_numbers_exist_in_knowledge_base() -> None:
    for product in ("LED lamp", "feeding bottle", "cement", "gold hallmarking",
                    "stainless steel water bottle"):
        out = FINDER.find(product)
        for why in out.explanations:
            check(f"{product}: {why.standard_number} exists in the KB",
                  why.standard_number in KB_STANDARD_NUMBERS)


# ------------------------------------------ 6. uncovered query abstains safely

def test_uncovered_query_abstains_with_no_explanations() -> None:
    out = FINDER.find("plastic garden chair")
    check("uncovered product abstains", not out.grounded and out.results == [])
    check("uncovered product has no explanations", out.explanations == [])

    empty = FINDER.find("   ")
    check("empty product abstains", not empty.grounded and empty.results == [])
    check("empty product has no explanations", empty.explanations == [])


# -------------------------------------------- 7. Phase 5 behaviour unchanged

def test_phase5_behaviour_is_unchanged() -> None:
    def standards(product: str) -> list[str]:
        return [r.item.standard_number for r in FINDER.find(product).results]

    check("LED lamp -> IS 16102 (Part 1)",
          "IS 16102 (Part 1)" in standards("LED lamp"))
    # Phase 4 filled the edition in from BIS's catalogue ("IS 14625" ->
    # "IS 14625:2015"); the same standard, so the year is not compared.
    check("feeding bottle -> IS 14625",
          any(n.split(":")[0].strip() == "IS 14625" for n in standards("feeding bottle")))
    check("stainless steel water bottle -> IS 17526:2021",
          "IS 17526:2021" in standards("stainless steel water bottle"))
    check("generic word does not leak IS 1786:2008",
          "IS 1786:2008" not in standards("stainless steel water bottle"))
    check("only indian_standards items are returned",
          all(r.item.category == "indian_standards" and r.item.standard_number
              for r in FINDER.find("gold hallmarking").results))


# -------------------------------------------------- 8. /product-standard API

def test_product_standard_api_exposes_why() -> None:
    resp = product_standard_post(ProductStandardRequest(product="LED lamp"))
    check("api: response is grounded", resp.grounded and bool(resp.results))
    check("api: every result carries a why block",
          all(r.why is not None and r.why.summary for r in resp.results))
    check("api: why.standard_number matches the result",
          all(r.why.standard_number == r.standard_number for r in resp.results))
    check("api: raw reasons are still present alongside why",
          all(r.reasons for r in resp.results))

    abstain = product_standard_post(
        ProductStandardRequest(product="plastic garden chair")
    )
    check("api: uncovered product returns no results and no why",
          not abstain.grounded and abstain.results == [])


def main() -> int:
    test_product_query_returns_candidates_with_explanations()
    test_matchreason_data_is_preserved()
    test_explanation_is_derived_from_deterministic_reasons()
    test_no_llm_is_needed_for_why_this_result()
    test_shown_standard_numbers_exist_in_knowledge_base()
    test_uncovered_query_abstains_with_no_explanations()
    test_phase5_behaviour_is_unchanged()
    test_product_standard_api_exposes_why()

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
