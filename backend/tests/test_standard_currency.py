"""Checks for Phase 5 — standard currency (app/standard_currency.py).

Whether the edition MetrIQ cites is the newest one ITS EVIDENCE shows. The
properties that matter:

  1. only the four statuses exist, and every verified standard gets one;
  2. the ten standards Phase 4 refused to pick a year for are never ACTIVE;
  3. BIS's own catalogue and the third-party mirror are kept apart — a mirror
     showing no later edition is never ACTIVE;
  4. the wording is about MetrIQ's evidence, and NO code path — the currency
     statements, the shipped code's strings, or the optional model prose — can
     call a standard "withdrawn". MetrIQ holds no withdrawal data.

Every model call is stubbed. Plain Python, no framework. Run:

    cd backend
    ./.venv/bin/python tests/test_standard_currency.py
"""

from __future__ import annotations

import io
import json
import sys
import tokenize
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app import standard_currency as sc  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))


KB_NUMBERS = [i["standard_number"] for i in
              json.loads((ROOT / "data/knowledge/indian_standards.json").read_text())]
REFUSED_TEN = ["IS 302 (Part 2/Sec 3)", "IS 12615", "IS 16102 (Part 1)", "IS 12640 (Part 2)",
               "IS 6452", "IS 8042", "IS 16242 (Part 1)", "IS 10322 (Part 5/Sec 1)", "IS 5175",
               "IS 15392"]
INDEX = {"generated_on": "2026-09-25",
         "sources": {"bis": {"url": "https://bis.example/kys"},
                     "archive": {"url": "https://archive.example/"}}}


def entry(years, route="bis", method="WILDCARD", reaffirmation=None, identical=None) -> dict:
    return {"method": method, "source_route": route, "reaffirmation": reaffirmation,
            "editions": [{"year": y, "identical_is": (identical or {}).get(y)} for y in years]}


def assess(number, e, filled=False):
    return sc._assess(number, e, filled, INDEX)


def test_every_standard_has_one_of_four_statuses() -> None:
    print("\n[1] every verified standard gets one of the four statuses")
    results = {n: sc.currency_for(n) for n in KB_NUMBERS}
    check("all KB standards resolve", all(results.values()),
          str([n for n, c in results.items() if c is None][:5]))
    check("only the four statuses", {c.status for c in results.values()} <= set(sc.STATUSES))
    dist = sc.distribution(KB_NUMBERS)
    check("the distribution sums to the knowledge base", sum(dist.values()) == len(KB_NUMBERS), str(dist))
    check("a number outside the knowledge base gets nothing", sc.currency_for("IS 99999:2020") is None)
    check("no number gets nothing", sc.currency_for(None) is None and sc.currency_for("") is None)
    for c in results.values():
        if c.status == sc.ACTIVE and c.evidence != sc.BIS_CATALOGUE:
            check("ACTIVE rests only on BIS's own catalogue", False, c.statement)
            break
    else:
        check("ACTIVE rests only on BIS's own catalogue", True)
    check("SUPERSEDED_BY always names the later edition",
          all(c.later_edition for c in results.values() if c.status == sc.SUPERSEDED_BY))
    check("official is true only for BIS's catalogue",
          all(c.official == (c.evidence == sc.BIS_CATALOGUE) for c in results.values()))


def test_the_ten_refused_standards() -> None:
    print("\n[2] the ten standards Phase 4 refused to date are never ACTIVE")
    for number in REFUSED_TEN:
        c = sc.currency_for(number)
        check(f"{number}: {c.status if c else None}",
              c is not None and c.status in (sc.NOT_ESTABLISHED, sc.SUPERSEDED_BY))
        check(f"{number}: names every edition it knows of", c is not None and len(c.editions) >= 2
              and all(e in c.statement for e in c.editions), c.statement if c else "")


def test_known_cases() -> None:
    print("\n[3] known cases from the real index")
    c = sc.currency_for("IS 14543:2016")
    check("IS 14543:2016 is SUPERSEDED_BY IS 14543:2024",
          c.status == sc.SUPERSEDED_BY and c.later_edition == "IS 14543:2024", c.statement)
    check("... on BIS's own catalogue", c.evidence == sc.BIS_CATALOGUE and c.official)
    check("... worded as MetrIQ's evidence",
          c.statement.startswith("MetrIQ's verified evidence shows a later edition"))
    if c.reaffirmed_year:
        check("... and its earlier reaffirmation is kept, not hidden", str(c.reaffirmed_year) in c.statement)


def test_rules() -> None:
    print("\n[4] the rules, on controlled index entries")
    c = assess("IS 1:2019", entry([2019]))
    check("BIS lists ours as newest -> ACTIVE", c.status == sc.ACTIVE)
    check("ACTIVE admits a later revision would not show", "would not show here" in c.statement)
    c = assess("IS 1:2019", entry([2019]), filled=True)
    check("a year MetrIQ took from the catalogue says so", "took the year from that same catalogue" in c.statement)
    c = assess("IS 1:2011", entry([2011], route="archive"))
    check("mirror shows no later edition -> NOT_ESTABLISHED, never ACTIVE",
          c.status == sc.NOT_ESTABLISHED and c.evidence == sc.ARCHIVE_MIRROR)
    c = assess("IS 1:2011", entry([2011, 2020], route="archive"))
    check("mirror shows a later edition -> SUPERSEDED_BY, not official",
          c.status == sc.SUPERSEDED_BY and not c.official and "mirror" in c.statement)
    c = assess("IS 1:2016", entry([2016, 2024], identical={2024: "ISO 1:2022"}))
    check("the later edition's identical ISO is named", "ISO 1:2022" in c.statement)
    reaff = {"year": 2021, "source": "archive_document", "quote": "Indian Standard (Reaffirmed 2021)",
             "url": "https://archive.org/details/x"}
    c = assess("IS 1:2016", entry([2016], reaffirmation=reaff))
    check("a cover-page reaffirmation -> REAFFIRMED, quoted",
          c.status == sc.REAFFIRMED and "(Reaffirmed 2021)" in c.statement and c.reaffirmed_year == 2021)
    check("... sourced to the document, not to BIS", c.evidence == sc.ARCHIVE_DOCUMENT and not c.official)
    c = assess("IS 1:2016", entry([2016, 2024], reaffirmation=reaff))
    check("a reaffirmation does not outrank a later edition", c.status == sc.SUPERSEDED_BY)
    c = assess("IS 1:2016", entry([2016, 2019], reaffirmation=reaff))
    check("a reaffirmation AFTER the later edition is a conflict -> NOT_ESTABLISHED",
          c.status == sc.NOT_ESTABLISHED and "does not choose" in c.statement)
    bis_reaff = dict(reaff, source="bis_catalogue", quote="reaffirm_year: 2021")
    c = assess("IS 1:2016", entry([2016], reaffirmation=bis_reaff))
    check("BIS's own reaffirm_year -> REAFFIRMED, official", c.status == sc.REAFFIRMED and c.official)
    c = assess("IS 1", entry([2007, 2024]))
    check("no cited year -> NOT_ESTABLISHED", c.status == sc.NOT_ESTABLISHED and c.cited_edition is None)
    c = assess("IS 1:2022", entry([2008, 2020]))
    check("cited edition newer than every listed one -> NOT_ESTABLISHED", c.status == sc.NOT_ESTABLISHED)
    c = assess("IS 1:2022", entry([], method="NOT_FOUND"))
    check("unresolved -> NOT_ESTABLISHED with no source", c.status == sc.NOT_ESTABLISHED
          and c.evidence == sc.NO_EVIDENCE and c.source_url is None)


def _strings_in(path: Path) -> list[str]:
    with path.open("rb") as handle:
        return [t.string for t in tokenize.tokenize(handle.readline) if t.type == tokenize.STRING]


class _SaysWithdrawn:
    def generate(self, *, system_prompt: str, user_prompt: str, **_kw) -> str:
        return "IS 14543:2016 has been withdrawn by BIS."


def test_no_code_path_says_withdrawn() -> None:
    print("\n[5] no code path can call a standard withdrawn")
    statements = [f"{c.label} {c.statement} {c.boundary}" for c in map(sc.currency_for, KB_NUMBERS)]
    check("no currency statement for any KB standard", not any(sc.mentions_withdrawal(s) for s in statements))

    shipped = [p for p in (BACKEND / "app").rglob("*.py")]
    hits = [p.name for p in shipped if any(sc.mentions_withdrawal(s) for s in _strings_in(p))]
    check("no string literal in the backend application", not hits, str(hits))
    frontend = [p for p in (ROOT / "frontend/src").rglob("*.ts*")]
    hits = [p.name for p in frontend if sc.mentions_withdrawal(p.read_text())]
    check("nothing in the frontend source", not hits, str(hits))

    from app.certification import CertificationGuidanceService
    from app.copilot import CopilotAnswer, guard
    from app.lab_registry import load_laboratories
    from app.laboratory import LaboratorySearchService
    from app.product import ProductStandardFinder
    from app.rag import BISQuestionAnswerer
    from app.retrieval import SearchEngine

    engine = SearchEngine()
    llm = _SaysWithdrawn()
    answer = BISQuestionAnswerer(search_engine=engine, llm=llm).ask("packaged drinking water standard")
    check("/ask: model prose saying it is replaced by MetrIQ's own evidence text",
          not sc.mentions_withdrawal(answer.answer) and answer.explained is False)
    guidance = CertificationGuidanceService(search_engine=engine, product_finder=ProductStandardFinder(engine),
                                            llm=llm).guide("certification for packaged drinking water")
    check("/certification-guidance: replaced", not sc.mentions_withdrawal(guidance.answer))
    labs = LaboratorySearchService(search_engine=engine, llm=llm, registry=load_laboratories(),
                                   product_finder=ProductStandardFinder(engine)).search(
        "laboratory for packaged drinking water")
    check("/laboratory-search: replaced", not sc.mentions_withdrawal(labs.answer))
    guarded = guard(CopilotAnswer(answer="IS 14543 was withdrawn in 2024."), "IS 14543")
    check("copilot: withheld as WITHDRAWAL_CLAIM",
          guarded.withheld and guarded.withheld_reason == "WITHDRAWAL_CLAIM"
          and not sc.mentions_withdrawal(guarded.answer), guarded.answer)


def test_surfaces() -> None:
    print("\n[6] it reaches the API and the report")
    from fastapi.testclient import TestClient

    from app.main import app
    from app.report import _edition

    response = TestClient(app).post("/product-standard", json={"product": "packaged drinking water"})
    results = response.json()["results"]
    check("/product-standard carries currency on every result",
          response.status_code == 200 and results and all(r.get("currency") for r in results))
    rows = _edition(sc.currency_for("IS 14543:2016").model_dump())
    check("the report renders an Edition row with its boundary",
          rows and rows[0][0] == "Edition" and "not a statement from BIS" in rows[0][1])
    check("an old record with no currency renders nothing", _edition(None) == [])
    journey = TestClient(app).post("/certification-guidance",
                                   json={"question": "", "standard_number": "IS 14543:2016",
                                         "explain": False}).json().get("journey") or {}
    check("the certification journey carries currency",
          (journey.get("currency") or {}).get("status") == sc.SUPERSEDED_BY, str(journey.get("currency")))


def main() -> int:
    test_every_standard_has_one_of_four_statuses()
    test_the_ten_refused_standards()
    test_known_cases()
    test_rules()
    test_no_code_path_says_withdrawn()
    test_surfaces()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
