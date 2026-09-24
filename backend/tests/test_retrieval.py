"""Checks for the Phase 3 retrieval engine and the /search API.

Plain Python, no test framework (matches tests/test_knowledge.py). Run with:

    cd backend
    ./.venv/bin/python tests/test_retrieval.py

Exit code 0 = all checks passed, 1 = something failed.

These run against the real verified knowledge base in data/knowledge/. No fake BIS
facts are introduced.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import search_get, search_post, SearchRequest  # noqa: E402
from app.retrieval import RetrievalConfig, SearchEngine  # noqa: E402
from app.retrieval.text import (  # noqa: E402
    find_standard_numbers,
    normalize,
    tokenize,
)

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


def top_id(query: str) -> str | None:
    out = ENGINE.search(query)
    return out.results[0].item.id if out.results else None


# --------------------------------------------------------------------- 1-2. keyword / title match


def test_keyword_and_title_match() -> None:
    print("\n[1/2] exact keyword and title matches")

    out = ENGINE.search("hallmarking charges")
    check("keyword query returns results", bool(out.results))
    check(
        "top result is the hallmarking charges record",
        top_id("hallmarking charges") == "hallmarking-charges",
        top_id("hallmarking charges") or "none",
    )

    # "Compulsory Registration Scheme" appears in a certification record title.
    tid = top_id("Compulsory Registration Scheme")
    check(
        "title phrase query finds the CRS certification record",
        tid == "compulsory-registration-scheme-crs",
        tid or "none",
    )


# --------------------------------------------------------------------- 3. standard-number match


def test_standard_number_match() -> None:
    print("\n[3] standard-number match")

    out = ENGINE.search("IS 1786:2008")
    check("IS 1786:2008 returns a result", bool(out.results))
    check(
        "IS 1786:2008 top result is the matching standard",
        out.results and out.results[0].item.standard_number == "IS 1786:2008",
        out.results[0].item.id if out.results else "none",
    )
    check(
        "standard-number match is high confidence",
        out.confidence == "high",
        out.confidence,
    )
    check(
        "reason cites the standard_number field",
        any(r.field == "standard_number" for r in out.results[0].reasons),
    )
    # bare number, no 'IS' prefix in query text still parses
    check("find_standard_numbers parses 'IS1786'", "1786" in find_standard_numbers("IS1786"))
    check(
        "find_standard_numbers parses 'is 14543:2016'",
        "14543:2016" in find_standard_numbers("is 14543:2016"),
    )


# --------------------------------------------------------------------- 4. multiple candidates


def test_multiple_candidates() -> None:
    print("\n[4] multiple candidate results")
    out = ENGINE.search("cement")
    check("'cement' returns several candidates", len(out.results) >= 3, str(len(out.results)))
    cement_standards = [
        r for r in out.results if r.item.category == "indian_standards"
    ]
    check(
        "at least 4 cement Indian Standards are returned",
        len(cement_standards) >= 4,
        str(len(cement_standards)),
    )
    check(
        "every returned Indian Standard is a cement standard",
        all("cement" in r.item.title.lower() for r in cement_standards),
    )


# --------------------------------------------------------------------- 5-6. irrelevant / no-result


def test_irrelevant_and_empty_queries_abstain() -> None:
    print("\n[5/6] irrelevant and empty queries abstain")

    # "bicycle" was dropped from this query: BIS lists Reflectors for Bicycles
    # under Scheme I, so a bicycle term now legitimately retrieves a standard.
    irrelevant = ENGINE.search("pizza delivery helicopter")
    check("irrelevant query abstains", irrelevant.abstained)
    check("irrelevant query has confidence 'none'", irrelevant.confidence == "none")
    check("irrelevant query returns no results", irrelevant.results == [])

    for q in ["", "   ", "a", "is"]:
        out = ENGINE.search(q)
        check(f"empty/tiny query {q!r} abstains", out.abstained and out.results == [])


# --------------------------------------------------------------------- 7. normalization


def test_query_normalization() -> None:
    print("\n[7] query normalization")

    check("normalize lowercases and strips punctuation", normalize("What is HUID???") == "what is huid")
    check("tokenize drops stopwords", tokenize("What is HUID") == ["huid"])

    check(
        "'What is HUID???' and 'huid' give the same top result",
        top_id("What is HUID???") == top_id("huid") == "what-is-huid",
    )
    check(
        "'IS1786' and 'is 1786' give the same top result",
        top_id("IS1786") == top_id("is 1786") == "is-1786-2008-hsd-steel-bars-for-concrete-reinforcement",
    )
    check(
        "accented / weird spacing still works",
        top_id("  HALL-MARKING   charges  ") == "hallmarking-charges",
    )


# --------------------------------------------------------------------- 8. ranking order


def test_ranking_order() -> None:
    print("\n[8] ranking order")

    out = ENGINE.search("hallmarking charges")
    ids = [r.item.id for r in out.results]
    check(
        "dedicated 'hallmarking-charges' ranks above the FAQ mention",
        ids.index("hallmarking-charges") < ids.index("faq-how-much-does-hallmarking-cost"),
        str(ids),
    )
    check(
        "results are sorted by descending score",
        all(out.results[i].score >= out.results[i + 1].score for i in range(len(out.results) - 1)),
    )

    out2 = ENGINE.search("what is huid")
    check(
        "'what-is-huid' outranks a record that only mentions huid in content",
        out2.results[0].item.id == "what-is-huid",
        out2.results[0].item.id,
    )


# --------------------------------------------------------------------- 9. provenance preserved


def test_provenance_preserved() -> None:
    print("\n[9] verification and source information is preserved")
    out = ENGINE.search("what is hallmarking")
    r = out.results[0]
    check("result exposes source_url", bool(r.source_url) and r.source_url.startswith("http"))
    check("result exposes verification_status", r.verification_status == "verified")
    check("underlying item is unchanged", r.item.source_url == r.source_url)
    check(
        "source_organization is carried on the item",
        r.item.source_organization == "Bureau of Indian Standards (BIS)",
    )


# --------------------------------------------------------------------- 10. matched terms / reasons


def test_matched_terms_and_reasons() -> None:
    print("\n[10] matched terms / reasons are generated")
    out = ENGINE.search("gold hallmarking purity")
    r = out.results[0]
    check("matched_terms is populated", len(r.matched_terms) >= 1)
    check("matched_terms are real query terms", set(r.matched_terms) <= set(out.query_terms) | set(out.query_standard_numbers))
    check("reasons are populated", len(r.reasons) >= 1)
    check("every reason has a field and a positive weight", all(x.field and x.weight > 0 for x in r.reasons))
    check("score equals the sum of reason weights", abs(r.score - round(sum(x.weight for x in r.reasons), 3)) < 1e-6)
    check(
        "a 'hallmarking' record matched the 'hallmarking' term",
        "hallmarking" in r.matched_terms,
    )


# --------------------------------------------------------------------- config is honoured


def test_config_is_configurable() -> None:
    print("\n[extra] thresholds are configurable")
    strict = SearchEngine(config=RetrievalConfig(threshold_high=999.0))
    out = strict.search("IS 1786:2008")
    check("raising threshold_high downgrades confidence", out.confidence != "high", out.confidence)
    check("but the result is still returned", bool(out.results))


# --------------------------------------------------------------------- API layer


def test_search_api() -> None:
    print("\n[api] GET/POST /search")

    resp = search_get(q="what is huid", limit=3)
    check("GET /search returns results", resp.count >= 1)
    check("GET /search top result is what-is-huid", resp.results[0].id == "what-is-huid")
    check("GET /search echoes confidence", resp.confidence in {"high", "medium", "low", "none"})
    check("GET /search respects limit", resp.count <= 3)
    first = resp.results[0]
    check("API result carries source_url", bool(first.source_url))
    check("API result carries verification_status", first.verification_status == "verified")
    check("API result carries reasons", len(first.reasons) >= 1)
    check("API result carries last_verified as ISO string", first.last_verified == "2026-09-17")

    posted = search_post(SearchRequest(query="IS 1786:2008"))
    check("POST /search standard-number query works", posted.results and posted.results[0].id.startswith("is-1786"))

    empty = search_get(q="")
    check("GET /search with empty query abstains cleanly", empty.abstained and empty.count == 0)

    junk = search_post(SearchRequest(query="zzzz qqqq xxxx"))
    check("POST /search with junk query abstains", junk.abstained)


def main() -> int:
    test_keyword_and_title_match()
    test_standard_number_match()
    test_multiple_candidates()
    test_irrelevant_and_empty_queries_abstain()
    test_query_normalization()
    test_ranking_order()
    test_provenance_preserved()
    test_matched_terms_and_reasons()
    test_config_is_configurable()
    test_search_api()

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
