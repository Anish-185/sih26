"""Checks for Phase 3 — an informative abstention that invents nothing.

When MetrIQ has no answer for a product it states its own boundary instead of
returning a dead end: what the verified data covers (counted from the knowledge
base), what the search did, why the boundary sits where it does, and where to
look next. Those sentences are MetrIQ's own, written by code and translated in
`app/language.py`, so no model is involved and there is nothing to invent.

The dangerous failure mode is the message itself becoming a claim. So the checks
here are mostly about what the boundary must NEVER contain:

  * a standard number — for an unknown product MetrIQ has none, and printing one
    would be exactly the fabrication this project exists to prevent,
  * a scheme name attached to the unknown product (the coverage sentence names
    Scheme I and Scheme II as a description of the DATASET, which is different
    and is asserted separately), and
  * a category or sector guess ("shampoo is probably a cosmetic").

There is one more, subtler rule. MetrIQ must never say "this product is not on
BIS's lists", because it cannot tell at runtime whether a product is genuinely
absent or merely listed under wording the query did not match — "refrigerator"
retrieves nothing although BIS lists Household Refrigerating Appliances, and
"solar panel" retrieves solar water heating although BIS lists Photovoltaic (PV)
modules. Both cases are asserted below.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_coverage_boundary.py

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

from app import boundary as bd  # noqa: E402
from app import language as lang  # noqa: E402
from app.main import app  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.retrieval import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0

ENGINE = SearchEngine()
FINDER = ProductStandardFinder(ENGINE)
COVERAGE = bd.measure(ENGINE.items)
CLIENT = TestClient(app)

# The eight consumer products that return nothing today.
UNKNOWN = ("shampoo", "school bag", "cooking oil", "biscuits",
           "paint", "solar panel", "mixer grinder", "refrigerator")

# Anything shaped like an Indian Standard number.
IS_NUMBER = re.compile(r"\bIS[\s/:]*\d", re.I)

# Category / sector words MetrIQ must never attach to an unknown product.
GUESSES = ("cosmetic", "personal care", "toiletr", "stationery", "food product",
           "foodstuff", "textile", "apparel", "chemical", "paint industry",
           "kitchen appliance", "home appliance", "cooking appliance",
           "construction material", "building material", "electronics",
           "probably", "likely", "appears to be", "seems to be", "may fall under",
           "would fall under", "belongs to", "is a type of", "category of")


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def spoken(boundary: bd.Boundary) -> str:
    """Only the prose MetrIQ writes — not the weak-match records it quotes."""
    return " ".join([boundary.heading, *boundary.lines,
                     boundary.next_step, boundary.weak_heading, boundary.weak_note])


def test_the_numbers_are_counted_not_typed() -> None:
    print("\n[1] the coverage numbers come from the knowledge base")
    standards = [i for i in ENGINE.items
                 if i.category == "indian_standards" and i.standard_number]
    check("the standards count is the real record count",
          COVERAGE.standards == len(standards), str(COVERAGE.standards))
    check("Scheme I + Scheme II + other accounts for every standard",
          COVERAGE.scheme_i + COVERAGE.scheme_ii + COVERAGE.other == COVERAGE.standards,
          f"{COVERAGE.scheme_i}+{COVERAGE.scheme_ii}+{COVERAGE.other}"
          f" != {COVERAGE.standards}")
    check("the Legal Metrology count is the real record count",
          COVERAGE.legal_metrology == sum(1 for i in ENGINE.items
                                          if i.category == "legal_metrology"))
    check("listed products are counted, and there are fewer than standards+1",
          0 < COVERAGE.products <= COVERAGE.standards, str(COVERAGE.products))

    source = (Path(__file__).resolve().parents[1] / "app" / "boundary.py").read_text()
    for number in (str(COVERAGE.standards), str(COVERAGE.products)):
        check(f"the figure {number} is not hard-coded in boundary.py",
              number not in source)
    check("every counted figure reaches the sentences",
          all(str(v) in spoken(bd.explain("x", COVERAGE, lang.EN))
              for v in (COVERAGE.standards, COVERAGE.scheme_i, COVERAGE.scheme_ii,
                        COVERAGE.products, COVERAGE.legal_metrology, COVERAGE.other)))


def test_an_unknown_product_invents_nothing() -> None:
    print("\n[2] an unknown product's message invents nothing, in every language")
    for language in (lang.EN, lang.HI, lang.TE):
        for product in UNKNOWN:
            outcome = FINDER.find(product, language=language)
            check(f"[{language}] {product}: MetrIQ still gives no standard",
                  not outcome.results and not outcome.grounded)
            if outcome.boundary is None:
                check(f"[{language}] {product}: a boundary is produced", False)
                continue
            text = spoken(outcome.boundary)

            found = IS_NUMBER.search(text)
            check(f"[{language}] {product}: no standard number in MetrIQ's own words",
                  found is None, found.group(0) if found else "")

            lowered = text.lower()
            hit = next((g for g in GUESSES if g in lowered), None)
            check(f"[{language}] {product}: no category or sector guess",
                  hit is None, hit or "")

            check(f"[{language}] {product}: the product is quoted, never described",
                  product in text)


def test_it_never_says_the_product_is_absent_from_bis() -> None:
    print("\n[3] MetrIQ never claims a product is absent from BIS's listings")
    # The claim is unprovable at runtime and is false for at least two of the
    # eight, so it must appear nowhere MetrIQ writes.
    forbidden = ("is not on those lists", "is not on the bis list",
                 "is not listed by bis", "there is no indian standard",
                 "bis does not list this product", "not notified by bis")
    for language in (lang.EN, lang.HI, lang.TE):
        text = spoken(bd.explain("shampoo", COVERAGE, language)).lower()
        hit = next((f for f in forbidden if f in text), None)
        check(f"[{language}] no claim that the product is absent from BIS's lists",
              hit is None, hit or "")

    # "no Indian Standard exists" may appear ONLY inside the sentence that denies
    # it. A bare assertion of it would be a claim about BIS that MetrIQ cannot make.
    for language in (lang.EN, lang.HI, lang.TE):
        text = spoken(bd.explain("shampoo", COVERAGE, language))
        bare = re.search(r"(?<!does NOT mean that )(?<!does not mean that )"
                         r"no Indian Standard exists", text)
        check(f"[{language}] 'no Indian Standard exists' appears only when denied",
              bare is None, bare.group(0) if bare else "")

    english = spoken(bd.explain("shampoo", COVERAGE, lang.EN)).lower()
    check("both possibilities are stated, and neither is resolved",
          "cannot tell which" in english
          and "different wording" in english
          and "not on the two bis listing pages" in english)
    check("and it says explicitly that this is not a claim about the standard existing",
          "does not mean that no indian standard exists" in english)


def test_the_vocabulary_misses_are_real() -> None:
    print("\n[4] the two products whose standard EXISTS but is not retrieved")
    # If these ever start retrieving, the "vocabulary miss" reasoning in
    # app/boundary.py's docstring is stale and should be revisited.
    numbers = {i.standard_number for i in ENGINE.items if i.standard_number}
    for product, standard, word in (
        ("refrigerator", "IS 17550 (Part 1): 2021", "refrigerating"),
        # Phase 4 established this edition from the Public.Resource.Org mirror.
        ("solar panel", "IS 14286 IS/IEC 61730 -1 IS/IEC 61730 -2:2010", "photovoltaic"),
    ):
        check(f"{standard} is in the knowledge base", standard in numbers)
        found = [r.item.standard_number for r in ENGINE.search(product, 5).results]
        check(f"but '{product}' does not retrieve it — a vocabulary miss, not a gap",
              standard not in found, str(found[:2]))
        check(f"because the record says '{word}', not '{product}'",
              any(word in i.content.lower() for i in ENGINE.items
                  if i.standard_number == standard))

    # And the genuine gaps really are absent from the data.
    for product, word in (("shampoo", "shampoo"), ("mixer grinder", "mixer"),
                          ("school bag", "school bag")):
        present = [i.standard_number for i in ENGINE.items
                   if word in (i.title + " " + " ".join(i.keywords)).lower()]
        check(f"'{product}': nothing in the knowledge base names it",
              not present, str(present[:3]))


def test_a_weak_match_is_never_offered_as_an_answer() -> None:
    print("\n[5] a weak match is shown as evidence, never as an answer")
    outcome = FINDER.find("solar panel")
    assert outcome.boundary is not None
    check("'solar panel' retrieves partial matches", bool(outcome.boundary.weak_matches))
    check("they are NOT returned as results", outcome.results == [])
    check("and MetrIQ says it is not putting them forward",
          "not as an answer" in outcome.boundary.weak_note.lower()
          and "not putting it forward" in outcome.boundary.weak_note.lower())
    check("the weak-match note exists in every language",
          all(bd.explain("x", COVERAGE, code,
                         weak_matches=outcome.boundary.weak_matches).weak_note.strip()
              for code in (lang.EN, lang.HI, lang.TE)))

    quiet = FINDER.find("shampoo")
    assert quiet.boundary is not None
    check("a product with no partial match shows no weak-match block",
          not quiet.boundary.weak_matches
          and not quiet.boundary.weak_note and not quiet.boundary.weak_heading)


def test_the_http_contract() -> None:
    print("\n[6] the boundary reaches both endpoints")
    body = CLIENT.post("/product-standard",
                       json={"product": "shampoo", "language": "hi"}).json()
    check("/product-standard returns a boundary on abstention",
          body["boundary"] is not None and body["results"] == [])
    check("in the requested language",
          body["boundary"]["language"] == lang.HI
          and lang.detect(body["boundary"]["lines"][2]) == lang.HI)
    check("with the official next step",
          body["boundary"]["next_step_url"] == bd.KNOW_YOUR_STANDARDS)

    answered = CLIENT.post("/product-standard", json={"product": "electric kettle"}).json()
    check("a product that IS found carries no boundary",
          answered["boundary"] is None and answered["results"])

    ask = CLIENT.post("/ask", json={"question": "which standard for shampoo"}).json()
    check("/ask returns a boundary when retrieval abstains",
          ask["boundary"] is not None and ask["sources"] == [])
    found = IS_NUMBER.search(" ".join(ask["boundary"]["lines"]))
    check("and it still names no standard number", found is None,
          found.group(0) if found else "")


def test_no_model_is_involved() -> None:
    print("\n[7] the sentences are MetrIQ's own")
    source = (Path(__file__).resolve().parents[1] / "app" / "boundary.py").read_text()
    for forbidden in ("llm", "openrouter", "LocalLLM", "generate(", "httpx", "requests"):
        check(f"boundary.py does not reach for a model: {forbidden!r}",
              forbidden not in source)
    check("every sentence lives in the language layer",
          set(lang.BOUNDARY) == {lang.EN, lang.HI, lang.TE})
    check("and every language defines the same keys",
          len({tuple(sorted(v)) for v in lang.BOUNDARY.values()}) == 1)
    check("the Hindi and Telugu sentences are actually in their own scripts",
          lang.detect(lang.BOUNDARY[lang.HI]["two_reasons"]) == lang.HI
          and lang.detect(lang.BOUNDARY[lang.TE]["two_reasons"]) == lang.TE)


def main() -> int:
    test_the_numbers_are_counted_not_typed()
    test_an_unknown_product_invents_nothing()
    test_it_never_says_the_product_is_absent_from_bis()
    test_the_vocabulary_misses_are_real()
    test_a_weak_match_is_never_offered_as_an_answer()
    test_the_http_contract()
    test_no_model_is_involved()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
