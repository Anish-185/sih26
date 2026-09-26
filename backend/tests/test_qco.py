"""Phase 9: the Quality Control Order layer (lookup-only design).

QCO records are rows of BIS's "Upcoming QCOs" table, excluded from the main search
and reached by exact standard number after retrieval. Every model call is stubbed.

  * no QCO status exists without a quoted official row;
  * a compulsory-certification listing record alone never yields NOTIFIED;
  * a passed enforcement date never yields NOTIFIED;
  * no QCO record is returned by the main search;
  * a mismatched row never attaches to a standard (and every reason is reachable);
  * /ask may mention a QCO only when a QCO record is attached (both directions);
  * the boundary quotes a row only on a whole multi-word phrase;
  * the ingest parser, the wording in three languages, and the drift probe.

    cd backend
    ./.venv/bin/python tests/test_qco.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import fetch_qco  # noqa: E402

from app import language as lang  # noqa: E402
from app import qco  # noqa: E402
from app.api import ProductStandardRequest, product_standard_post  # noqa: E402
from app.knowledge.schema import KnowledgeItem  # noqa: E402
from app.rag import BISQuestionAnswerer, untied_qco_claim  # noqa: E402
from app.retrieval import SearchEngine  # noqa: E402

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


class ReplyLLM:
    def __init__(self, reply: str) -> None:
        self.reply, self.prompts = reply, []

    def generate(self, *, system_prompt: str, user_prompt: str, **_) -> str:
        self.prompts.append(user_prompt)
        return self.reply


ENGINE = SearchEngine()
ALL = __import__("app.knowledge.loader", fromlist=["x"]).load_knowledge_base().items
KB = [i.standard_number for i in ALL if i.category == "indian_standards" and i.standard_number]
QCO_ROWS = [i for i in ALL if i.category == "quality_control_orders"]


def test_every_status_is_a_quoted_row() -> None:
    print("\n[1] no QCO status exists without a quoted official row")
    check("the table was ingested (29 rows)", len(QCO_ROWS) == 29, str(len(QCO_ROWS)))
    bad = []
    for number in KB:
        out = qco.status_for(number)
        if out.status not in qco.STATUSES:
            bad.append((number, "unknown status"))
        if out.status == qco.NOT_ESTABLISHED and out.rows:
            bad.append((number, "NOT_ESTABLISHED with rows"))
        if out.status != qco.NOT_ESTABLISHED:
            for row in out.rows:
                record = next(r for r in QCO_ROWS if r.reference == f"Sr. No. {row.sr_no}")
                verbatim = all(f"{label}: {value}" in record.content for label, value in [
                    ("Ministry/Department", row.ministry), ("Product", row.product),
                    ("Indian Standard", row.standard_as_printed), ("Enforcement date", row.enforcement_date)])
                if not (row.source_url in qco.STATUS_BY_TABLE and verbatim and row.read_on):
                    bad.append((number, row.sr_no))
    check("every status other than NOT_ESTABLISHED carries rows quoted verbatim from an official table",
          not bad, str(bad[:3]))
    check("every QCO record is a BIS-published table row from bis.gov.in, dated",
          all(r.source_authority == "QUALITY_CONTROL_ORDER" and r.source_url.startswith("https://www.bis.gov.in/")
              and r.last_verified and "publisher of the table" in r.source_organization for r in QCO_ROWS))
    check("the table URL the status rule reads is the one the ingest script fetches",
          fetch_qco.UPCOMING == qco.UPCOMING_TABLE)
    try:
        KnowledgeItem(id="x-bad", title="bad qco", category="quality_control_orders",
                      content="a QCO row that claims to be BIS", source_url="https://www.bis.gov.in/x")
        check("the loader rejects a QCO record whose authority is BIS", False)
    except ValueError:
        check("the loader rejects a QCO record whose authority is BIS", True)
    try:
        KnowledgeItem(id="x-bad", title="bad std", category="indian_standards", standard_number="IS 1",
                      content="a standard posing as a QCO row", source_url="https://www.bis.gov.in/x",
                      source_authority="QUALITY_CONTROL_ORDER")
        check("…and a BIS category carrying the QCO authority", False)
    except ValueError:
        check("…and a BIS category carrying the QCO authority", True)


def test_a_listing_is_not_a_qco() -> None:
    print("\n[2] a listing-page record alone never yields NOTIFIED")
    listed = [i for i in ALL if i.category == "indian_standards"
              and "Compulsory Certification" in (i.document_name or "")]
    uncovered = [i for i in listed if not qco.qco_for(i.standard_number)]
    check("hundreds of standards are on a compulsory-certification listing", len(listed) > 400, str(len(listed)))
    check("every listed standard with no QCO row is NOT_ESTABLISHED — never NOTIFIED or UPCOMING",
          all(qco.status_for(i.standard_number).status == qco.NOT_ESTABLISHED for i in uncovered))
    check("NOTIFIED is reached by no knowledge-base standard (no in-force table was found)",
          all(qco.status_for(n).status != qco.NOTIFIED for n in KB))
    check("no table maps to NOTIFIED", qco.NOTIFIED not in qco.STATUS_BY_TABLE.values())
    kettle = qco.status_for("IS 367:1993")
    check("IS 367:1993 (Scheme I listing) is NOT_ESTABLISHED, and the sentence separates the two facts",
          kettle.status == qco.NOT_ESTABLISHED and "different fact" in kettle.statements[0])


def test_a_passed_date_is_never_in_force() -> None:
    print("\n[3] a passed enforcement date never yields NOTIFIED")
    later = dt.date(2030, 1, 1)
    attached = [r["kb"] for r in qco.match_report(KB) if r["result"] == "ATTACHED"]
    outs = [qco.status_for(n, today=later) for n in attached]
    check("every attached row stays UPCOMING after its date has passed",
          outs and all(o.status == qco.UPCOMING for o in outs))
    check("…and says exactly that the date has passed and MetrIQ cannot confirm it took effect",
          all(any("That date has passed; MetrIQ cannot confirm whether the order took effect or was deferred."
                  in s for s in o.statements) for o in outs))
    before = qco.status_for("IS 1660:2024", today=dt.date(2026, 9, 1))
    check("before the date: the not-in-force sentence, no 'passed' sentence",
          any("does not state that this order is in force" in s for s in before.statements)
          and not any("has passed" in s for s in before.statements))
    for code in (lang.EN, lang.HI, lang.TE):
        text = lang.qco(code)
        check(f"{code}: every QCO sentence exists", set(text) >= {
            "label", "upcoming", "not_in_force", "passed", "not_established", "edition", "boundary"})
    words = " ".join(s for n in attached for s in qco.status_for(n, today=later).statements).lower()
    check("no sentence addresses the user's item ('your product must', 'must be certified')",
          "your product must" not in words and "must be certified" not in words)


def test_the_main_search_never_returns_a_qco() -> None:
    print("\n[4] no QCO record is returned by the main search")
    check("the engine's items hold no QCO record", all(i.category != "quality_control_orders" for i in ENGINE.items))
    queries = ["quality control order", "QCO", "upcoming QCOs notified and due for implementation",
               "enforcement date", *(qco.fields(r)["Product"] for r in QCO_ROWS)]
    leaked = [q for q in queries
              if any(r.item.category == "quality_control_orders" for r in ENGINE.search(q, limit=20).results)]
    check(f"none of {len(queries)} queries (every QCO product wording included) returns a QCO record",
          not leaked, str(leaked[:3]))


def _fake(number: str, sr: str = "99") -> KnowledgeItem:
    return KnowledgeItem(
        id=f"qco-fake-{sr}", title="Quality Control Order (upcoming): fake", category="quality_control_orders",
        content=(f"Sr. No.: {sr}\nMinistry/Department: Ministry of Tests\nProduct: Fake Product\n"
                 f"Indian Standard: {number}\nEnforcement date: 01 January 2027\nLink given for this row: none"),
        standard_number=number, source_authority="QUALITY_CONTROL_ORDER",
        source_organization="Bureau of Indian Standards (BIS), publisher of the table; order issued by Tests",
        source_url=qco.UPCOMING_TABLE, document_name="fake", reference=f"Sr. No. {sr}",
        verification_status="verified", last_verified="2026-09-26")


def test_a_mismatch_never_attaches() -> None:
    print("\n[5] a mismatched row never attaches to a standard")
    report = qco.match_report(KB)
    mism = [r for r in report if r["result"] == "MISMATCH"]
    check("the real table: 28 attached, 1 mismatch (Sr. 1, IS 12795:2020, number not in the KB)",
          len(report) == 29 and len(mism) == 1 and mism[0]["sr_no"] == "1"
          and mism[0]["reason"] == qco.NUMBER_NOT_IN_KB, str(mism))
    lab = next(r for r in QCO_ROWS if r.reference == "Sr. No. 1")
    check("…and that row attaches to no knowledge-base standard", all(lab not in qco.qco_for(n) for n in KB))
    check("whitespace and a missing 'IS ' are the only normalisation: '4003(Part 2):1986' -> IS 4003 (Part 2): 1986",
          [r.standard_number for r in qco.qco_for("IS 4003 (Part 2): 1986")] == ["4003(Part 2):1986"])

    original = qco._records
    fakes = (_fake("IS 1660:2016", "91"), _fake("IS 4003 (Part 3):1978", "92"),
             _fake("IS 16102 (Part 1):2012", "93"), _fake("IS 99999:2020", "94"), _fake("IS 14543 2016", "95"))
    qco._records = lambda: fakes
    try:
        reasons = {r["sr_no"]: r.get("reason") for r in qco.match_report(KB)}
        check("a different year is DIFFERENT_YEAR", reasons["91"] == qco.DIFFERENT_YEAR, str(reasons))
        check("a different part is PART_SECTION_DIFFERS", reasons["92"] == qco.PART_SECTION_DIFFERS)
        check("a KB record without a year is KB_RECORD_HAS_NO_YEAR", reasons["93"] == qco.KB_RECORD_HAS_NO_YEAR)
        check("an unknown number is NUMBER_NOT_IN_KB", reasons["94"] == qco.NUMBER_NOT_IN_KB)
        check("a missing colon is not 'whitespace' — no match, no correction",
              reasons["95"] is not None and not qco.qco_for("IS 14543:2016"))
        check("none of the mismatched rows attaches to any standard",
              not any(qco.qco_for(n) for n in ["IS 1660:2024", "IS 4003 (Part 1): 1978",
                                               "IS 16102 (Part 1)", "IS 14543:2016"]))
    finally:
        qco._records = original


def test_ask_mentions_a_qco_only_when_attached() -> None:
    print("\n[6] /ask may mention a QCO only when a QCO record is attached")
    q = "which standard applies to a glass screen protector?"
    llm = ReplyLLM("A glass screen protector is listed under a Quality Control Order with an "
                   "enforcement date of 01 April 2027 (IS 19348:2025).")
    ans = BISQuestionAnswerer(ENGINE, llm).ask(q)
    check("glass screen protector: its QCO row is attached", [r.standard_number for r in ans.qco] == ["IS 19348:2025"])
    check("…the model sees the row verbatim and MetrIQ's status",
          "QUALITY CONTROL ORDER RECORD 1" in llm.prompts[0] and "Enforcement date: 01 April 2027" in llm.prompts[0]
          and "METRIQ STATUS: UPCOMING" in llm.prompts[0])
    check("…and a QCO mention reaches the user", ans.fallback_reason == "MODEL", ans.fallback_reason)

    led = BISQuestionAnswerer(ENGINE, ReplyLLM("LED bulbs are covered by a Quality Control Order.")).ask(
        "which standard applies to an LED bulb?")
    check("LED bulb: no QCO row is attached", led.qco == [])
    check("…and the same kind of claim is withheld", led.fallback_reason.startswith("GUARD:"), led.fallback_reason)
    ctx = led.context
    check("untied_qco_claim: withheld with no attached row, allowed with one",
          untied_qco_claim("It is under a QCO.", led.results, ctx, [])
          and not untied_qco_claim("It is under a QCO.", led.results, ctx, ans.qco))
    low = BISQuestionAnswerer(ENGINE, ReplyLLM("ok")).ask("what does IS 17153 cover")
    check("a low-confidence answer attaches no QCO row", low.qco == [])

    body = product_standard_post(ProductStandardRequest(product="glass screen protector"))
    check("/product-standard carries the QCO status on the card",
          body.results and body.results[0].qco.status == qco.UPCOMING and body.results[0].qco.rows)


def test_the_boundary_quotes_a_row_only_on_a_whole_phrase() -> None:
    print("\n[7] the boundary: whole multi-word phrase only")
    gaps = ["shampoo", "school bag", "cooking oil", "biscuits", "paint", "mixer grinder",
            "refrigerator", "solar panel"]
    check("none of the eight gap products matches a QCO row", not any(qco.boundary_rows(p) for p in gaps))
    check("'coffee makers' matches the IS 302 (Part 1) row's listed 'Electric Coffee Makers'",
          [w for _, w in qco.boundary_rows("coffee makers")] == ["Electric Coffee Makers"])
    check("a single word never matches ('dishwashers', 'wrenches')",
          not qco.boundary_rows("dishwashers") and not qco.boundary_rows("wrenches"))
    ans = BISQuestionAnswerer(ENGINE, ReplyLLM("ok")).ask("coffee makers")
    lines = ans.boundary.lines if ans.boundary else []
    check("an abstention on 'coffee makers' quotes the row in MetrIQ's words",
          any("Electric Coffee Makers" in line and "does not say the order applies to your item" in line
              for line in lines), str(lines)[:200])


def test_ingest_and_drift() -> None:
    print("\n[8] ingest parser and drift probe")
    page = ("<table><tr><td colspan=2>Sr. No.</td><td>Ministry/ Department</td><td>Product</td>"
            "<td>Indian Standard</td><td>Enforcement date</td></tr>"
            "<tr><td rowspan=3>1</td><td rowspan=3>Ministry X</td><td>Things</td><td rowspan=3>12 : 2000</td>"
            "<td rowspan=3>01 October, 2026</td></tr><tr><td>Thing A</td></tr><tr><td>Thing B</td></tr>"
            "<tr><td>2</td><td>Dept Y</td><td>Widget</td><td>IS 7:1999</td><td>1 May 2027</td></tr></table>")
    rows = fetch_qco.parse_upcoming(page)
    check("rowspan sub-products stay with their row; cells stay verbatim",
          len(rows) == 2 and rows[0]["listed_products"] == ["Thing A", "Thing B"]
          and rows[0]["number"] == "12 : 2000" and rows[0]["date"] == "01 October, 2026")
    try:
        fetch_qco.parse_upcoming(page.replace("Enforcement date", "Date"))
        check("a changed header stops the ingest", False)
    except ValueError:
        check("a changed header stops the ingest", True)
    snapshot = json.loads((BACKEND.parent / "data" / "source_snapshots.json").read_text())
    check("the drift check has a recorded QCO baseline of 29 rows",
          len(snapshot["sources"].get("qco-upcoming", {}).get("items", [])) == 29)
    from app.report import _qco as report_row
    row = report_row(qco.for_standard("IS 19348:2025").model_dump())
    check("the PDF report row quotes the status, its sentences and the table source",
          row and row[0][0] == "Quality Control Order" and "QCO upcoming" in row[0][1]
          and "Sr. No. 28" in row[0][1] and "does not state that this order is in force" in row[0][1])
    check("…and a record saved before Phase 9 (no qco) prints no row", report_row(None) == [])
    source = (BACKEND / "app" / "qco.py").read_text()
    check("app/qco.py makes no network call and computes no status from today's date",
          "urllib" not in source and "httpx" not in source and "status = STATUS_BY_TABLE[" in source)


def main() -> int:
    test_every_status_is_a_quoted_row()
    test_a_listing_is_not_a_qco()
    test_a_passed_date_is_never_in_force()
    test_the_main_search_never_returns_a_qco()
    test_a_mismatch_never_attaches()
    test_ask_mentions_a_qco_only_when_attached()
    test_the_boundary_quotes_a_row_only_on_a_whole_phrase()
    test_ingest_and_drift()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
