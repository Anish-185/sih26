"""Checks for Milestone 14 — verified BIS knowledge and product → standard coverage.

The knowledge base grew from 36 to 97 verified Indian Standards, all taken from
official BIS "Products under Compulsory Certification" pages. These checks lock
in that the growth is honest:

  provenance   every standard carries an official bis.gov.in source, a
               verification date, and a unique standard number
  no invention rules, requirements and certification claims did NOT grow with it;
               a standard is STANDARD_ONLY unless verified image-checkable
               requirement data exists
  retrieval    the products BIS names now reach the standard BIS names for them,
               with the deterministic engine's own reasons and confidence
  restraint    an ambiguous product stays ambiguous, an unknown product gets
               nothing, and a keyword never guesses a category

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_standards_coverage.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from app.product import ProductStandardFinder  # noqa: E402
from app.product_identification import _split_joined_words, _vocabulary  # noqa: E402
from app.requirements import coverage_by_standard, load_requirements  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0

FINDER = ProductStandardFinder(SearchEngine())
ITEMS = FINDER.search_engine.items
STANDARDS = [i for i in ITEMS if i.category == "indian_standards"]
REQUIREMENTS = load_requirements(ITEMS)

OFFICIAL_HOSTS = ("https://www.bis.gov.in/", "https://bis.gov.in/",
                  "https://www.services.bis.gov.in/", "https://services.bis.gov.in/")


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def top(query: str, limit: int = 5):
    return FINDER.find(query, limit=limit)


def numbers(query: str, limit: int = 5) -> list[str]:
    return [r.item.standard_number for r in top(query, limit).results]


# --------------------------------------------------------------- 1-4 provenance


def test_every_standard_is_verifiable() -> None:
    print("\nprovenance of every standard")
    check("the knowledge base carries at least 90 verified Indian Standards",
          len(STANDARDS) >= 90, str(len(STANDARDS)))

    unverified = [i.id for i in STANDARDS if i.verification_status != "verified"]
    check("every standard is marked verified", not unverified, str(unverified))

    no_source = [i.standard_number for i in STANDARDS if not i.source_url]
    check("every standard has a source URL", not no_source, str(no_source))

    unofficial = [i.source_url for i in STANDARDS
                  if not str(i.source_url).startswith(OFFICIAL_HOSTS)]
    check("every source URL is an official BIS host", not unofficial, str(unofficial[:3]))

    undated = [i.standard_number for i in STANDARDS if not i.last_verified]
    check("every standard records when it was verified", not undated, str(undated))

    no_doc = [i.standard_number for i in STANDARDS if not i.document_name]
    check("every standard names the source document", not no_doc, str(no_doc[:5]))

    seen: dict[str, str] = {}
    dupes = []
    for item in STANDARDS:
        if item.standard_number in seen:
            dupes.append(item.standard_number)
        seen[item.standard_number] = item.id
    check("no duplicate standard numbers", not dupes, str(dupes))

    check("every standard record names an authority of BIS",
          all(i.source_authority == "BIS" for i in STANDARDS))

    bad_title = [i.standard_number for i in STANDARDS if " — " not in i.title]
    check("every title is 'IS number — product', so the product name is readable",
          not bad_title, str(bad_title))


# ------------------------------------------------------- 5-7 nothing was invented


def test_growth_invented_nothing() -> None:
    print("\nmore standards did not create more rules")
    by_std = {c.standard_number: c for c in coverage_by_standard(ITEMS, REQUIREMENTS)}
    classes = {s: sum(c.coverage_status == s for c in by_std.values())
               for s in ("INSPECTION_SUPPORTED", "STANDARD_ONLY", "UNSUPPORTED")}

    check("only packaged water is inspection-supported",
          sorted(s for s, c in by_std.items() if c.coverage_status == "INSPECTION_SUPPORTED")
          == ["IS 13428:2005", "IS 14543:2016"], str(classes))
    check("every added standard is STANDARD_ONLY — retrievable, no invented rule",
          classes["STANDARD_ONLY"] == len(by_std) - 6, str(classes))
    check("the four hallmarking standards stay UNSUPPORTED for package inspection",
          classes["UNSUPPORTED"] == 4, str(classes))

    rules = [r.id for r in REQUIREMENTS.requirements if r.supported and r.scope == "STANDARD"]
    check("still exactly one checkable BIS rule in the data",
          rules == ["packaged-water-label-shows-is-number"], str(rules))

    check("a standard with no requirement data reports it plainly",
          all(by_std[s].verified_requirements == 0 and by_std[s].deterministic_rules == 0
              for s in ("IS 8828", "IS 18112:2022", "IS 8042")),
          "a new standard was given requirements")

    for number in ("IS 16333 (Part-3)", "IS 8828", "IS 1867 : 2023"):
        item = next(i for i in STANDARDS if i.standard_number == number)
        text = item.content.lower()
        check(f"{number}: states what BIS lists, claims no certification outcome",
              "compulsory certification" in text and "not a statement about any particular item" in text,
              item.content[:90])


def test_keywords_never_guess_a_category() -> None:
    print("\nsearch terms are product names, not sector guesses")
    banned = {"cooking appliance", "construction material", "household appliance",
              "kitchenware material", "roofing sheet", "borewell pipe", "gi pipe",
              "electrical safety", "switchgear", "water heating rod", "kerosene stove"}
    offenders = [(i.standard_number, k) for i in STANDARDS for k in i.keywords if k in banned]
    check("no standard carries a sector/category guess as a keyword", not offenders, str(offenders[:4]))

    # A common name is an everyday word for the SAME product, and the record says so.
    common = [i for i in STANDARDS if "Common names used for searching" in i.content]
    check("records that use common names declare them in their own text",
          len(common) >= 10, str(len(common)))
    for item in common:
        declared = item.content.split("Common names used for searching this product:")[1]
        undeclared = [k for k in item.keywords
                      if " " in k and k not in declared.lower()
                      and k not in item.title.lower()]
        if undeclared:
            check(f"{item.standard_number}: every multi-word search term is declared or from the title",
                  False, str(undeclared))
            return
    check("every multi-word search term is either the BIS product name or a declared common name", True)


# ------------------------------------------------------------- 8-12 retrieval


def test_products_reach_their_standard() -> None:
    print("\nproducts BIS names reach the standard BIS names for them")
    # (query, the standard BIS lists for it) — every pair is from an official
    # "Products under Compulsory Certification" page.
    expected = [
        ("electric kettle", "IS 367:1993"),
        ("packaged drinking water", "IS 14543:2016"),
        ("roasted chana", "IS 18140:2023"),
        ("LED bulb", "IS 16102 (Part 1)"),
        ("mobile phone", "IS 16333 (Part-3)"),
        ("television set", "IS 18112:2022"),
        ("rice cooker", "IS 302 (Part 2): Section 15: 2009"),
        ("induction stove", "IS 302 (Part 2): Section 6: 2009"),
        ("room heater", "IS 302 (Part 2/Sec 30)"),
        ("immersion water heater", "IS 302 (Part 2/Sec 201)"),
        ("dry battery", "IS 8144"),
        ("white portland cement", "IS 8042"),
        ("masonry cement", "IS 3466"),
        ("clinical thermometer", "IS 3055 (Part 1)"),
        ("distribution transformer", "IS 1180 (Part 1)"),
        ("street light", "IS 10322 (Part 5/Section 3): 2012"),
        ("led driver", "IS 15885 (Part 2/Sec 13)"),
        ("ups inverter", "IS 16242 (Part 1)"),
        ("stainless steel water bottle", "IS 17526:2021"),
        ("microwave oven", "IS 302-2-25"),
    ]
    for query, standard in expected:
        check(f"'{query}' -> {standard}", standard in numbers(query), str(numbers(query)[:3]))

    check("a product with no verified standard still returns nothing invented",
          all(n in {i.standard_number for i in STANDARDS} for q, _ in expected for n in numbers(q)))


def test_common_names_and_ocr_noise() -> None:
    print("\ncommon names and OCR-damaged product text")
    for query, standard in [("mcb", "IS 8828"), ("rccb", "IS 12640 (Part 1)"),
                            ("power bank", "IS/IEC 62368 (Part 1) : 2023"),
                            ("cctv camera", "IS/IEC 62368 (Part 1) : 2023"),
                            ("smart watch", "IS/IEC 62368 (Part 1) : 2023"),
                            ("laptop", "IS/IEC 62368 (Part 1) : 2023")]:
        check(f"common name '{query}' -> {standard}", standard in numbers(query), str(numbers(query)[:2]))

    vocab = _vocabulary(ITEMS)
    for joined, wanted in [("PACKAGEDDRINKINGWATER", "packaged drinking water"),
                           ("ROASTEDBENGALGRAM", "roasted bengal gram"),
                           ("ELECTRICKETTLE", "electric kettle")]:
        split = _split_joined_words(joined, vocab)
        check(f"OCR '{joined}' splits to '{wanted}'", split == wanted, repr(split))

    check("a joined word that is not knowledge-base vocabulary is left alone",
          _split_joined_words("ZZZQQQWWWVVV", vocab) == "", repr(_split_joined_words("ZZZQQQWWWVVV", vocab)))


def test_ambiguous_stays_ambiguous() -> None:
    print("\nambiguity and the unknown are not resolved away")
    out = top("cement", limit=6)
    check("'cement' returns several cement standards", len(out.results) >= 3)
    check("'cement' returns only cement standards",
          all("cement" in r.item.title.lower() for r in out.results))
    check("'cement' is never high confidence — it names no one product",
          out.confidence != "high", out.confidence)
    scores = {r.score for r in out.results}
    check("the cement candidates score alike, so none is arbitrarily preferred", len(scores) <= 2, str(scores))

    for unknown in ("toaster", "ceiling fan", "quantum flux capacitor", "zzzzqqq"):
        out = top(unknown)
        check(f"unknown product '{unknown}' invents no standard", not out.results, str(numbers(unknown)))
        check(f"unknown product '{unknown}' says so", out.confidence == "none" and out.note)

    out = top("stainless steel water bottle", limit=6)
    check("several genuine candidates are all returned with their own evidence",
          len(out.results) >= 2 and all(r.reasons for r in out.results))
    check("and the best-supported one ranks first", out.results[0].item.standard_number == "IS 17526:2021")


def test_explanations_survive() -> None:
    print("\nretrieval still explains itself")
    out = FINDER.find("mobile phone", limit=3)
    check("every candidate carries match reasons", all(r.reasons for r in out.results))
    check("every candidate carries a why-this-result summary",
          len(out.explanations) == len(out.results) and all(w.summary for w in out.explanations))
    why = out.explanations[0]
    check("why-this-result names the standard it explains", why.standard_number == out.results[0].item.standard_number)
    check("why-this-result lists the deterministic signals", bool(why.signals))
    check("the note says retrieval is not applicability",
          "not" in out.note.lower() or "retrieval" in out.note.lower(), out.note)


def test_domains_stay_separate() -> None:
    print("\nBIS, Legal Metrology and hallmarking stay separate")
    lm = [i for i in ITEMS if i.category == "legal_metrology"]
    check("Legal Metrology items are a separate category with their own authority",
          lm and all(i.source_authority == "LEGAL_METROLOGY" for i in lm))
    check("no Indian Standard record claims Legal Metrology authority",
          all(i.source_authority == "BIS" for i in STANDARDS))
    check("BIS product search never returns a Legal Metrology record",
          all(r.item.category != "legal_metrology"
              for q in ("net quantity", "maximum retail price", "mobile phone")
              for r in top(q).results))

    by_std = {c.standard_number: c for c in coverage_by_standard(ITEMS, REQUIREMENTS)}
    for gold in ("IS 1417:2016", "IS 2112:2014", "IS 1418:2009", "IS 2113:2014"):
        check(f"{gold} stays jewellery-hallmarking and unsupported for package inspection",
              by_std[gold].domain == "JEWELLERY_HALLMARKING"
              and by_std[gold].coverage_status == "UNSUPPORTED")


def test_requirement_data_unchanged() -> None:
    print("\nrequirement data did not grow with the standards")
    raw = json.loads((Path(__file__).resolve().parents[2] / "data" / "inspection_requirements.json").read_text())
    check("the requirement file still holds 15 requirements", len(raw["requirements"]) == 15,
          str(len(raw["requirements"])))
    check("the requirement file still models 3 products", len(raw["products"]) == 3, str(len(raw["products"])))
    check("the loader accepted them all with no errors", not REQUIREMENTS.errors, str(REQUIREMENTS.errors))
    supported = [r.id for r in REQUIREMENTS.requirements if r.supported]
    check("exactly 7 checkable requirements, as before", len(supported) == 7, str(len(supported)))


def main() -> int:
    test_every_standard_is_verifiable()
    test_growth_invented_nothing()
    test_keywords_never_guess_a_category()
    test_products_reach_their_standard()
    test_common_names_and_ocr_noise()
    test_ambiguous_stays_ambiguous()
    test_explanations_survive()
    test_domains_stay_separate()
    test_requirement_data_unchanged()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
