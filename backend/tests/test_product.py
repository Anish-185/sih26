"""Checks for Phase 5 Product -> Standard discovery.

Plain Python, no test framework (matches tests/test_retrieval.py). Run with:

    cd backend
    ./.venv/bin/python tests/test_product.py

Exit code 0 = all checks passed, 1 = something failed.

Runs against the real verified knowledge base in data/knowledge/. No fake BIS
facts are introduced.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.product import ProductStandardFinder  # noqa: E402
from app.retrieval import SearchEngine  # noqa: E402

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


FINDER = ProductStandardFinder(SearchEngine())


def standards(product: str) -> list[str]:
    return [r.item.standard_number for r in FINDER.find(product).results]

def names(query: str) -> list[str]:
    """Standard numbers for a query, ignoring a year Phase 4 filled in.

    Phase 4 completed 63 numbers from BIS's own catalogue ("IS 14625" ->
    "IS 14625:2015"). That is the SAME standard with its edition now known, so
    these checks compare the number without its year rather than a literal that
    would go stale again the next time an edition is established.
    """
    return [n.split(":")[0].strip() if ":" in n and n.split(":")[0].strip() else n
            for n in standards(query)]



def test_real_products_are_matched() -> None:
    out = FINDER.find("LED lamp")
    check("LED lamp -> IS 16102", "IS 16102 (Part 1)" in standards("LED lamp"))
    check("LED lamp is grounded", out.grounded)

    check("feeding bottle -> IS 14625", "IS 14625" in names("feeding bottle"))
    check("electric iron -> IS 302 part 2/sec 3",
          "IS 302 (Part 2/Sec 3)" in standards("electric iron"))
    check("microwave oven -> IS 302-2-25", "IS 302-2-25" in names("microwave oven"))
    check("laptop charger safety -> IS/IEC 62368",
          "IS/IEC 62368 (Part 1) : 2023" in standards("laptop charger safety"))


def test_single_word_products_still_work() -> None:
    # "cement" names 13 verified cement standards that score identically. Picking
    # one of them would be false precision, so the check is that every candidate
    # really is a cement standard and that the query does not resolve to "high".
    out = FINDER.find("cement", limit=6)
    check("cement -> only cement standards, none of them arbitrarily preferred",
          out.results and all("cement" in r.item.title.lower() for r in out.results),
          str([r.item.standard_number for r in out.results]))
    check("cement stays ambiguous — a one-word category is never high confidence",
          out.confidence != "high", out.confidence)
    check("battery -> IS 16046", "IS 16046" in standards("battery"))
    check("tyre -> a tyre standard",
          any(s in names("tyre") for s in ("IS 15627", "IS 15633")))


def test_stainless_steel_water_bottle_has_coverage() -> None:
    # The knowledge base now carries the BIS standards that actually describe
    # this product (added in Phase 5): IS 17526 (stainless steel vacuum
    # flask/bottle) and IS 17803 (potable water bottles).
    out = FINDER.find("stainless steel water bottle")
    check("stainless steel water bottle is grounded", out.grounded)
    check("stainless steel water bottle -> IS 17526:2021",
          "IS 17526:2021" in standards("stainless steel water bottle"))
    # With a larger knowledge base other steel/water standards can also match a
    # word, so the guarantee is about ranking: the two standards that actually
    # describe this product come first, far ahead of any word-level match. The
    # explicit "not returned" checks below still bar unrelated domains.
    # IS 17803's own title literally reads "Potable Water Bottles (Copper,
    # Stainless Steel, Aluminium)" -- a full-title match against every query
    # word -- so it now correctly outranks IS 17526, whose title never says
    # "water" at all (that keyword-only match is described at Phase 5, above).
    check("the two water-bottle standards rank first and second",
          [r.item.standard_number for r in out.results[:2]] == ["IS 17803:2022", "IS 17526:2021"],
          str([r.item.standard_number for r in out.results]))
    check("and they outrank every other candidate by a clear margin",
          len(out.results) < 3 or out.results[1].score > out.results[2].score * 1.5,
          str([(r.item.standard_number, r.score) for r in out.results[:3]]))

    # "steel water bottle" (no "stainless") should also reach the same standards.
    check("steel water bottle -> IS 17526:2021",
          "IS 17526:2021" in standards("steel water bottle"))


def test_generic_word_matches_do_not_leak() -> None:
    # For a water-bottle query, standards that only share a single generic word
    # ("steel", "water") must not be recommended.
    leaked = standards("stainless steel water bottle")
    for unrelated in ("IS 1786:2008", "IS 1161:2014", "IS 277:2003",
                      "IS 13428:2005", "IS 14543:2016"):
        check(f"{unrelated} not returned for a water bottle", unrelated not in leaked)

    # A product with no knowledge-base coverage must still abstain rather than
    # return a loose single-word match.
    out = FINDER.find("plastic garden chair")
    check("uncovered product abstains", not out.grounded and out.results == [])
    check("uncovered product confidence is none", out.confidence == "none")
    check("abstain note explains why", "loose single-word" in out.note)


def test_empty_product_abstains() -> None:
    out = FINDER.find("   ")
    check("empty product abstains", not out.grounded and out.results == [])


def test_only_indian_standards_are_returned() -> None:
    out = FINDER.find("gold hallmarking")
    check("gold hallmarking is grounded", out.grounded)
    check("every result is an indian_standards item with a standard number",
          all(r.item.category == "indian_standards" and r.item.standard_number
              for r in out.results))


def main() -> int:
    test_real_products_are_matched()
    test_single_word_products_still_work()
    test_stainless_steel_water_bottle_has_coverage()
    test_generic_word_matches_do_not_leak()
    test_empty_product_abstains()
    test_only_indian_standards_are_returned()

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
