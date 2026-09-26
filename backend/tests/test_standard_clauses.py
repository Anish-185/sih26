"""Phase 7: the standard_clauses records — clause text from the Public.Resource.Org mirror.

What matters:
  1. clause records are citation-only: never offered as Product -> Standard candidates,
     never returned by the main search, reached only per standard through app/clauses.py,
  2. every record is traceable: a reference, a mirror source_url, the mirror named as
     the source, and MetrIQ's own sentence saying it is OCR text from a third-party mirror,
  3. no table was reproduced: no clause contains a run of table cells,
  4. a bare "page N" is only ever a printed page, and never without its PDF page,
  5. every clause of an amended standard says amendments are not incorporated.

    cd backend
    ./.venv/bin/python tests/test_standard_clauses.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.product import ProductStandardFinder  # noqa: E402
from app.clauses import clauses_for, rank_within  # noqa: E402
from app.retrieval import SearchEngine  # noqa: E402

CLAUSES = json.loads((BACKEND.parent / "data" / "knowledge" / "standard_clauses.json").read_text())
REPORT = (BACKEND.parent / "data" / "clause_ingest_report.md").read_text()

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


def clause_text(record: dict) -> list[str]:
    return record["content"].split("\n\nMetrIQ note:")[0].split("\n")


# A table cell as OCR writes it: a roman-numbered row, or a short line carrying a number.
# Written independently of the ingester's detector, so the test is not grading itself.
# A lettered item ("a) SS 500,") is a prose list, which BIS writes inside clauses.
def looks_like_cell(line: str) -> bool:
    return bool(re.match(r"^\(?[ivxl]+\)\s", line)) or (
        len(line.split()) <= 4 and any(c.isdigit() for c in line)
        and not line.startswith("[") and not re.match(r"^[a-z]\)", line))


def test_never_a_product_candidate() -> None:
    finder = ProductStandardFinder(SearchEngine())
    queries = ["packaged drinking water", "gas stove", "helmet", "gold jewellery", "plywood", "cement",
               "paints or similar finishes", "marking", "scope", "sampling"]
    # Every clause heading is a query that matches its own clause record as strongly as possible.
    queries += sorted({r["title"].split(" — ", 1)[-1] for r in CLAUSES})[:150]
    leaked = [(q, r.item.id) for q in queries for r in finder.find(q).results
              if r.item.category != "indian_standards"]
    check("no clause record is ever a Product -> Standard candidate", not leaked, str(leaked[:3]))


def test_citation_only() -> None:
    engine = SearchEngine()
    queries = ["IS 14543:2016", "IS 367:1993", "paint", "mixer grinder", "country of origin",
               "telephone number", "best before", "complete address", "sampling", "marking",
               "what is the capital of France"]
    queries += [r["title"] for r in CLAUSES[::40]]
    leaked = [(q, r.item.id) for q in queries for r in engine.search(q, limit=50).results
              if r.item.category == "standard_clauses"]
    check("no standard_clauses record is ever returned by the main search", not leaked, str(leaked[:3]))
    check("nor listed in the engine's items", not any(i.category == "standard_clauses" for i in engine.items))
    top = engine.search("IS 14543:2016").results
    check("a lookup of 'IS 14543:2016' returns the indian_standards record first",
          bool(top) and top[0].item.category == "indian_standards"
          and top[0].item.standard_number == "IS 14543:2016", top[0].item.id if top else "no results")


def test_per_standard_lookup() -> None:
    held = clauses_for("IS 14543:2016")
    check("clauses_for returns the standard's clauses", len(held) > 5
          and all(c.standard_number == "IS 14543:2016" for c in held))
    in_file = [r["id"] for r in CLAUSES if r["standard_number"] == "IS 14543:2016"]
    check("…in clause order", [c.id for c in held] == in_file)
    check("clauses_for is exact-string: no year is stripped", clauses_for("IS 14543") == [])
    check("…and one edition's clauses never attach to another edition", clauses_for("IS 14543:2024") == [])
    ranked = rank_within("IS 14543:2016", "sampling")
    check("rank_within finds that standard's sampling clause first",
          bool(ranked) and "SAMPLING" in ranked[0].item.title.upper(), ranked[0].item.title if ranked else "none")
    check("…from that standard only", all(r.item.standard_number == "IS 14543:2016" for r in ranked))
    check("rank_within on a standard with no clauses is an empty answer", rank_within("IS 269:2015", "cement") == [])


def test_traceable() -> None:
    check("clause records exist", len(CLAUSES) > 0)
    bad = [r["id"] for r in CLAUSES if not r.get("reference") or not r.get("source_url")]
    check("every clause record has a reference and a source_url", not bad, str(bad[:3]))
    check("every source_url is the mirror item", all(
        r["source_url"].startswith("https://archive.org/details/gov.in.is.") for r in CLAUSES))
    check("the mirror is always named as the source organization", all(
        r["source_organization"] == "Public.Resource.Org / Internet Archive (BIS document)" for r in CLAUSES))
    check("every record says it is OCR text from a third-party mirror, not a BIS publication", all(
        "not a BIS publication" in r["content"] and "MetrIQ has not corrected it" in r["content"]
        for r in CLAUSES))
    check("no record claims human verification", all(
        r["verification_status"] == "unverified" and not r.get("last_verified") for r in CLAUSES))
    ids = [r["id"] for r in CLAUSES]
    check("ids are unique", len(ids) == len(set(ids)))
    check("ids are never suffixed to force uniqueness",
          all(re.fullmatch(r"[a-z0-9-]+-clause-([a-z]-)?\d+(-\d+)*", i) for i in ids))
    check("every clause cites the standard its record cites", all(
        r["title"].startswith(r["standard_number"] + " Clause ") for r in CLAUSES))


def test_no_table_cells() -> None:
    runs = []
    for r in CLAUSES:
        lines, streak = clause_text(r), 0
        for line in lines[1:]:
            streak = streak + 1 if looks_like_cell(line) else 0
            if streak >= 3:
                runs.append(r["id"])
                break
    check("no clause content contains a table-cell run", not runs, str(runs[:5]))
    cut = [r for r in CLAUSES if "does not reproduce" in r["content"]]
    check("tables were cut and replaced by MetrIQ's own sentence", len(cut) > 0)


def test_pages() -> None:
    pattern = re.compile(r"^Clause (?:[A-Z]-)?\d+(?:\.\d+)*, (?:page not established"
                         r"|(?:pages? [^()]+ \()?PDF pages? \d+(?:–\d+)?\)?)$")
    bad = [r["reference"] for r in CLAUSES if not pattern.match(r["reference"])]
    check("every reference is 'Clause N, PDF page M', a printed page with its PDF page, or not established",
          not bad, str(bad[:3]))


def test_amendments_and_duplicates() -> None:
    amended = {line.split("|")[1].strip() for line in REPORT.splitlines()
               if line.startswith("| IS") and line.split("|")[10].strip() == "yes"}
    missing = [r["id"] for r in CLAUSES if r["standard_number"] in amended
               and "published amendments to" not in r["content"]]
    check("every clause of an amended standard says amendments are not incorporated", not missing, str(missing[:3]))
    check("amendment text never enters a clause", not any(
        re.search(r"(?im)^amendment no\.?\s*\d", r["content"]) for r in CLAUSES))
    per_standard = {}
    for r in CLAUSES:
        per_standard.setdefault(r["standard_number"], []).append(r["reference"].split(",")[0])
    check("no clause number appears twice in one standard", all(
        len(v) == len(set(v)) for v in per_standard.values()))
    check("every ingested standard keeps at least 5 clauses", all(len(v) >= 5 for v in per_standard.values()))


def main() -> int:
    test_never_a_product_candidate()
    test_citation_only()
    test_per_standard_lookup()
    test_traceable()
    test_no_table_cells()
    test_pages()
    test_amendments_and_duplicates()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
