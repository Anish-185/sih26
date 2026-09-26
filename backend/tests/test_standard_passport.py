"""Phase 11: the Standard Passport composer and its lookup.

  * the ?number= lookup: exact match, no match, several matches never auto-picked;
  * every section of an identity-level standard renders its honest empty state;
  * the clause-level Passport (IS 14543:2016) carries scope, requirements, withheld;
  * the composer calls no model, runs no search, and changes no data;
  * the HTTP contract of /standard-passport/lookup and /standard-passport/{id}.

    cd backend
    ./.venv/bin/python tests/test_standard_passport.py
"""

from __future__ import annotations

import hashlib
import sys
import warnings
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app import clauses, qco  # noqa: E402
from app import standard_passport as sp  # noqa: E402
from app.llm import LocalLLM  # noqa: E402
from app.main import app  # noqa: E402
from app.openrouter import OpenRouterLLM  # noqa: E402
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


def numbers(n: str) -> list[str]:
    return [m.standard_number for m in sp.lookup(n)]


def test_lookup() -> None:
    print("\n[1] ?number= lookup")
    check("exact: 'IS 14543:2016' names one record", numbers("IS 14543:2016") == ["IS 14543:2016"])
    check("the slash case: 'IS/IEC 62368 (Part 1) : 2023' names one record",
          numbers("IS/IEC 62368 (Part 1) : 2023") == ["IS/IEC 62368 (Part 1) : 2023"])
    check("spacing is not identity: 'IS 14543 : 2016' names the same record",
          numbers("IS 14543 : 2016") == ["IS 14543:2016"])
    check("no match: 'IS 99999' names nothing", numbers("IS 99999") == [])
    body = CLIENT.get("/standard-passport/lookup", params={"number": "IS 99999"}).json()
    check("…and the endpoint says MetrIQ holds no verified record, and guesses nothing nearby",
          body["matches"] == [] and "no verified record" in body["message"] and "does not guess" in body["message"])
    several = numbers("IS 16242 (Part 1)")
    check("several: 'IS 16242 (Part 1)' (no year) names both held editions",
          sorted(several) == ["IS 16242 (Part 1)", "IS 16242 (Part 1):2014"], str(several))
    check("…and 'IS 5175' names both 'IS 5175' and 'IS 5175:2022'",
          sorted(numbers("IS 5175")) == ["IS 5175", "IS 5175:2022"])
    body = CLIENT.get("/standard-passport/lookup", params={"number": "IS 16242 (Part 1)"}).json()
    check("the endpoint returns both and picks neither (no 'selected' / 'best' field, no message)",
          len(body["matches"]) == 2 and set(body) == {"number", "matches", "message"} and not body["message"])
    check("a year, when given, must match: 'IS 16242 (Part 1):2014' names that edition only",
          numbers("IS 16242 (Part 1):2014") == ["IS 16242 (Part 1):2014"])
    check("a part is identity: 'IS 302 (Part 2/Sec 3)' never names Sec 201",
          all("Sec 201" not in n for n in numbers("IS 302 (Part 2/Sec 3)")))
    check("IS 16102 (Part 1) names one record — its two catalogue editions are evidence, not records",
          numbers("IS 16102 (Part 1)") == ["IS 16102 (Part 1)"])


def _record_id(number: str) -> str:
    return sp.lookup(number)[0].id


def _barest_identity_standard() -> str:
    """A standard with no clause text, no listing order and no QCO row."""
    for item in sp._standards():
        n = item.standard_number
        if not clauses.clauses_for(n) and not qco.orders_named_by_listing(n) and not qco.qco_for(n):
            return item.id
    return ""


def test_identity_level_empty_states() -> None:
    print("\n[2] an identity-level standard: every section says what MetrIQ does not hold")
    led = CLIENT.get(f"/standard-passport/{_record_id('IS 16102 (Part 1)')}").json()
    check("coverage IDENTITY, in MetrIQ's own words", led["coverage"]["level"] == "IDENTITY"
          and "not its text" in led["coverage"]["note"] and led["coverage"]["withheld"] is None)
    check("scope: the empty sentence, no clause", not led["scope"]["clauses"]
          and led["scope"]["note"] == sp.NO_SCOPE_IDENTITY)
    check("requirements: the empty sentence, no clause", not led["requirements"]["clauses"]
          and led["requirements"]["note"] == sp.NO_REQUIREMENTS_IDENTITY)
    check("ICS / committee: not held, said plainly", led["identity"]["ics_committee_note"] == sp.NOT_HELD_ICS)
    check("QCO: NOT_ESTABLISHED with its sentence", led["legal"]["qco"]["status"] == "NOT_ESTABLISHED"
          and "no Quality Control Order evidence" in led["legal"]["qco"]["statements"][0])
    group = led["legal"]["listing_orders"]["groups"][0]
    check("its listing order names a Compulsory Registration Order, NOT a Quality Control Order",
          group["names_cro"] and not group["names_qco"])
    check("the two catalogue editions are shown, and no edition is named for the record",
          led["identity"]["cited_edition"] is None
          and set(led["identity"]["editions_known"]) == {"IS 16102 (Part 1):2026", "IS 16102 (Part 1):2012"})

    bare_id = _barest_identity_standard()
    check("a standard with nothing but its identity exists to test", bool(bare_id))
    bare = CLIENT.get(f"/standard-passport/{bare_id}").json()
    check("…its currency section carries a status with its sentence, or says there is none",
          (bare["currency"] and bare["currency"]["statement"]) or bare["currency_note"] == sp.NO_CURRENCY)
    check("…its legal section says so, for the QCO AND the listing",
          bare["legal"]["qco"]["status"] == "NOT_ESTABLISHED" and bare["legal"]["listing_orders"] is None
          and bare["legal"]["listing_note"] == sp.NO_LISTING_ORDER)
    check("…and every section is present in the response, none dropped",
          {"identity", "coverage", "currency", "currency_note", "legal", "scope", "requirements", "sources"}
          <= set(bare))


def test_clause_level() -> None:
    print("\n[3] the clause-level Passport: IS 14543:2016")
    water = CLIENT.get(f"/standard-passport/{_record_id('IS 14543:2016')}").json()
    cov = water["coverage"]
    check("coverage CLAUSE with 126 clauses and the 12 withheld", cov["level"] == "CLAUSE"
          and cov["clause_count"] == 126 and cov["withheld"] == 12 and "12 clause(s)" in cov["completeness"])
    check("scope: clause 1, quoted, reference and OCR label intact",
          [c["clause"] for c in water["scope"]["clauses"]] == ["1"]
          and water["scope"]["clauses"][0]["reference"] == "Clause 1, PDF page 3"
          and water["scope"]["clauses"][0]["ocr_label"] == clauses.OCR_LABEL)
    reqs = water["requirements"]["clauses"]
    stored = [clauses.label_of(c) for c in clauses.clauses_for("IS 14543:2016")]
    check("requirements: every other clause, in clause order",
          [c["clause"] for c in reqs] == [x for x in stored if x != "1"], f"{len(reqs)}")
    check("…each with the amendments sentence (IS 14543:2016 has amendments)",
          all("amendments to IS 14543:2016 are not incorporated" in c["note"] for c in reqs))
    urls = {s["url"] for s in water["sources"]}
    check("sources: only ones stored with the evidence (record, edition evidence, clause mirror)",
          "https://archive.org/details/gov.in.is.14543.2016" in urls and all(u.startswith("http") for u in urls))


def _digest(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.read_bytes())
    return h.hexdigest()


def test_no_model_no_search_no_write() -> None:
    print("\n[4] the composer calls no model, runs no search, changes no data")
    data = [*(ROOT / "data").glob("*.json"), *(ROOT / "data" / "knowledge").glob("*.json")]
    before = _digest(data)
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called"))  # noqa: E731
    saved = (OpenRouterLLM.generate, LocalLLM.generate, SearchEngine.search)
    OpenRouterLLM.generate = LocalLLM.generate = SearchEngine.search = boom
    try:
        for number in ("IS 14543:2016", "IS 16102 (Part 1)", "IS/IEC 62368 (Part 1) : 2023"):
            ok = CLIENT.get(f"/standard-passport/{_record_id(number)}").status_code == 200
            check(f"{number}: composed with every model and the search engine disabled", ok)
    finally:
        OpenRouterLLM.generate, LocalLLM.generate, SearchEngine.search = saved
    check("no data file changed", _digest(data) == before)
    source = (BACKEND / "app" / "standard_passport.py").read_text().split('"""', 2)[2]
    check("the module imports no model or network client",
          all(w not in source for w in ("openrouter", "LocalLLM", "httpx", "urllib", ".generate(")))


def test_http() -> None:
    print("\n[5] HTTP")
    check("an unknown id is 404", CLIENT.get("/standard-passport/no-such-record").status_code == 404)
    check("a missing ?number= is 422", CLIENT.get("/standard-passport/lookup").status_code == 422)
    check("record ids are path-safe (the reason the route uses them)",
          all("/" not in i.id and " " not in i.id for i in sp._standards()))


def main() -> int:
    test_lookup()
    test_identity_level_empty_states()
    test_clause_level()
    test_no_model_no_search_no_write()
    test_http()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
