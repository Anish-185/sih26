"""Phase 10: sampling / conformity / test-method clause groups.

  * a standard without clause data returns the honest empty state, never prose;
  * no model, network or search call is made;
  * every grouped clause carries its reference as stored and the OCR label;
  * a clause enters a group only by its own words (fabricated clause records);
  * the table-pointer case stays in its group, pointer intact;
  * withheld counts are read from Phase 7's ingest report; unknown -> no number;
  * the HTTP contract of GET /standard-clauses.

    cd backend
    ./.venv/bin/python tests/test_clause_groups.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app import clause_groups as cg  # noqa: E402
from app import clauses  # noqa: E402
from app import language as lang  # noqa: E402
from app.knowledge.schema import KnowledgeItem  # noqa: E402
from app.main import app  # noqa: E402
from app.retrieval import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0
CLIENT = TestClient(app)


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def labels(result: cg.ClauseGroups, group: str) -> list[str]:
    return [clauses.label_of(c.item) for c in result.groups[group]]


def test_identity_only_is_honest() -> None:
    print("\n[1] a standard without clause data: the honest empty state")
    for code in (lang.EN, lang.HI, lang.TE):
        out = cg.groups_for("IS 1660:2024", code)
        check(f"{code}: IS 1660:2024 is IDENTITY_ONLY with MetrIQ's fixed sentence and nothing else",
              out.status == cg.IDENTITY_ONLY and out.message == lang.clause_groups(code)["identity_only"]
              and not out.groups and out.clause_count == 0 and out.withheld is None and not out.completeness)
    body = CLIENT.get("/standard-clauses", params={"standard_number": "IS 1660:2024"}).json()
    check("HTTP: IDENTITY_ONLY carries no groups and no clause text",
          body["status"] == "IDENTITY_ONLY" and body["groups"] == [] and "not its text" in body["message"])
    held = set(clauses._by_standard())
    without = [i.standard_number for i in SearchEngine().items
               if i.category == "indian_standards" and i.standard_number and i.standard_number not in held]
    check(f"all {len(without)} standards without clause records are IDENTITY_ONLY",
          len(without) > 450 and all(cg.groups_for(n).status == cg.IDENTITY_ONLY for n in without))
    unknown = cg.groups_for("IS 14543")
    check("a number not in the KB exactly as written ('IS 14543') is UNKNOWN_STANDARD, not a guess",
          unknown.status == cg.UNKNOWN_STANDARD and not unknown.groups)


def test_no_model_network_or_search() -> None:
    print("\n[2] no model, network or search call")
    source = (BACKEND / "app" / "clause_groups.py").read_text()
    code = source.split('"""', 2)[2]          # the code after the module docstring
    for banned in ("llm", "openrouter", "httpx", "urllib", "generate(", "SearchEngine", "get_engine",
                   "rank_within"):
        check(f"clause_groups.py code does not use {banned!r}", banned not in code)
    original = SearchEngine.search
    SearchEngine.search = lambda *a, **k: (_ for _ in ()).throw(AssertionError("search called"))
    try:
        out = cg.groups_for("IS 14543:2016")
        check("grouping IS 14543:2016 runs with the search engine disabled", out.status == cg.CLAUSE_TEXT)
    finally:
        SearchEngine.search = original


def test_every_clause_is_referenced_and_labelled() -> None:
    print("\n[3] every grouped clause: reference as stored + OCR label + quoted verbatim")
    missing, altered = [], []
    for number in clauses._by_standard():
        body = CLIENT.get("/standard-clauses", params={"standard_number": number}).json()
        for group in body["groups"]:
            for g in group["clauses"]:
                c = g["clause"]
                item = next(i for i in clauses.clauses_for(number) if i.id == c["id"])
                if not c["reference"] or c["reference"] != item.reference or c["ocr_label"] != clauses.OCR_LABEL \
                        or not g["matched"]:
                    missing.append((number, c["clause"]))
                if c["text"] != clauses.view(item)["text"]:
                    altered.append((number, c["clause"]))
    check("across all 31 clause-level standards, every grouped clause has its stored reference, "
          "the OCR label and a stated reason", not missing, str(missing[:3]))
    check("…and its text is the stored text, not a summary", not altered, str(altered[:3]))
    nine = next(c for c in cg.groups_for("IS 14543:2016").groups[cg.SAMPLING] if clauses.label_of(c.item) == "9")
    check("the amendments sentence travels with the clause (IS 14543:2016 has amendments)",
          "amendments to IS 14543:2016 are not incorporated" in clauses.view(nine.item)["note"])


def _fake(label: str, text: str) -> KnowledgeItem:
    return KnowledgeItem(
        id=f"is-00000-2000-clause-{label.lower().replace('.', '-')}", category="standard_clauses",
        title=f"IS 00000:2000 Clause {label} — {text.splitlines()[0][:40]}",
        content=f"{label} {text}\n\nMetrIQ note: fabricated for a test.", standard_number="IS 00000:2000",
        source_url="https://archive.org/details/test", reference=f"Clause {label}, PDF page 1",
        source_organization="test", verification_status="unverified")


def test_own_words_only() -> None:
    print("\n[4] a clause enters a group only by its own words (fabricated records)")
    fakes = (
        _fake("1", "SAMPLING\nRepresentative samples shall be drawn as agreed."),
        _fake("2", "Coliform shall be absent in any 250 ml\nsample of the product."),
        _fake("3", "The product shall not crack when tested\nunder normal use."),
        _fake("4", "Lead shall not exceed 0.01 mg/l when tested in accordance\nwith the method given in IS 3025."),
        _fake("5", "Criteria for Conformity\nThe lot shall be declared as conforming if all requirements are met."),
        _fake("6", "Each container shall be marked with the\nname of the manufacturer."),
        _fake("7", "Type Test\nThree lamps are subjected to the checks below."),
    )
    original_by, original_known = clauses._by_standard, cg._known_standards
    clauses._by_standard = lambda: {"IS 00000:2000": fakes}
    cg._known_standards = lambda: frozenset({"IS 00000:2000"})
    try:
        out = cg.groups_for("IS 00000:2000")
        check("a SAMPLING heading enters SAMPLING", "1" in labels(out, cg.SAMPLING))
        check("'250 ml sample' in a requirement does NOT enter SAMPLING", "2" not in labels(out, cg.SAMPLING))
        check("'when tested' alone does NOT enter TEST_METHODS", "3" not in labels(out, cg.TEST_METHODS))
        check("'tested in accordance with … IS 3025' enters TEST_METHODS", "4" in labels(out, cg.TEST_METHODS))
        check("a 'Criteria for Conformity' heading enters CRITERIA_FOR_CONFORMITY",
              "5" in labels(out, cg.CRITERIA))
        check("a marking clause enters no group", all("6" not in labels(out, g) for g in cg.GROUPS))
        check("a 'Type Test' heading enters TEST_METHODS", "7" in labels(out, cg.TEST_METHODS))
        reason = next(c.matched for c in out.groups[cg.TEST_METHODS] if clauses.label_of(c.item) == "4")
        check("the reason names the words that matched", reason and reason[0].startswith("text: tested in accordance"),
              str(reason))
        check("a standard missing from the ingest report says the groups may be incomplete, with no number",
              out.withheld is None and out.completeness == lang.clause_groups(lang.EN)["incomplete_unknown"])
    finally:
        clauses._by_standard, cg._known_standards = original_by, original_known


def test_the_table_pointer_stays_in_its_group() -> None:
    print("\n[5] a clause whose table was cut keeps its pointer and its group")
    water = cg.groups_for("IS 14543:2016")
    scale = next((c for c in water.groups[cg.SAMPLING] if clauses.label_of(c.item) == "F-1.2.3"), None)
    check("IS 14543 F-1.2.3 (the scale-of-sampling clause, 'according to Table 5') is in SAMPLING",
          scale is not None)
    check("…with MetrIQ's pointer to PDF page 19 intact, and no table reconstructed",
          scale and "does not reproduce" in scale.item.content and "PDF page 19" in scale.item.content
          and "|" not in clauses.view(scale.item)["text"])
    nine = next(c for c in water.groups[cg.TEST_METHODS] if clauses.label_of(c.item) == "9")
    check("clause 9 (method table on PDF page 7) is in TEST_METHODS with its pointer",
          "See the source PDF, PDF page 7" in nine.item.content)


def test_withheld_counts() -> None:
    print("\n[6] withheld counts from the ingest report")
    for number, expected in [("IS 14543:2016", 12), ("IS 367:1993", 3), ("IS 4151: 2015", 7)]:
        out = cg.groups_for(number)
        check(f"{number}: {expected} withheld, named, and stated in the sentence",
              out.withheld == expected and len(out.withheld_clauses) == expected
              and f"{expected} clause(s)" in out.completeness)
    check("the rule counts are reported for the three TEST_METHODS rules",
          set(cg.rule_counts("IS 4151: 2015")) == {"H", "R", "W"})


def test_http_contract() -> None:
    print("\n[7] GET /standard-clauses")
    check("a missing standard_number is 422", CLIENT.get("/standard-clauses").status_code == 422)
    body = CLIENT.get("/standard-clauses", params={"standard_number": "IS 14543:2016", "language": "hi"}).json()
    check("the three groups come back in order, titled in the requested language",
          [g["group"] for g in body["groups"]] == list(cg.GROUPS) and body["language"] == "hi"
          and body["groups"][0]["title"] == lang.clause_groups(lang.HI)["titles"]["SAMPLING"])
    check("an unsupported language falls back to English",
          CLIENT.get("/standard-clauses", params={"standard_number": "IS 367:1993", "language": "xx"}
                     ).json()["language"] == "en")


def main() -> int:
    test_identity_only_is_honest()
    test_no_model_network_or_search()
    test_every_clause_is_referenced_and_labelled()
    test_own_words_only()
    test_the_table_pointer_stays_in_its_group()
    test_withheld_counts()
    test_http_contract()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
