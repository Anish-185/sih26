"""Phase 9.1: orders named by BIS's listing, the IN_FORCE rename, and the plural fix.

  * the rename is complete — no "NOTIFIED" status string remains;
  * a flagged rescission / suspension / supersession cell is never presented as the
    applicable order;
  * listing orders never set a status;
  * the join is exact, and rows that did not join are never returned;
  * an invented S.O. number is withheld and a supplied one passes (/ask, stubbed model);
  * an attached listing order ties an order to the product for untied_qco_claim;
  * "pipe wrench" reaches IS 4003's records (the accepted plural fix).

Every model call is stubbed.

    cd backend
    ./.venv/bin/python tests/test_listing_orders.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import fetch_compulsory_certification as cc  # noqa: E402

from app import language as lang  # noqa: E402
from app import qco  # noqa: E402
from app.api import ProductStandardRequest, product_standard_post  # noqa: E402
from app.knowledge.loader import load_knowledge_base  # noqa: E402
from app.product import ProductStandardFinder  # noqa: E402
from app.product_identification import _tokens  # noqa: E402
from app.rag import BISQuestionAnswerer, untied_qco_claim  # noqa: E402
from app.report import _listing_orders as report_row  # noqa: E402
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
        self.prompts.append((system_prompt, user_prompt))
        return self.reply


ENGINE = SearchEngine()
ITEMS = load_knowledge_base().items
KB = [i.standard_number for i in ITEMS if i.category == "indian_standards" and i.standard_number]
SNAPSHOT = json.loads((ROOT / "data" / "listing_notifications.json").read_text())
ROWS = SNAPSHOT["rows"]
JOINED = [r for r in ROWS if r["record_id"]]
FLAGGED = sorted({r["kb_standard_number"] for r in JOINED if r["flags"]})


def test_the_rename_is_complete() -> None:
    print("\n[1] NOTIFIED -> IN_FORCE")
    check("the status vocabulary is IN_FORCE / UPCOMING / NOT_ESTABLISHED",
          qco.STATUSES == ("IN_FORCE", "UPCOMING", "NOT_ESTABLISHED"))
    for code in (lang.EN, lang.HI, lang.TE):
        check(f"{code}: the label keys are the new vocabulary", set(lang.qco(code)["label"]) == set(qco.STATUSES))
    stray = []
    roots = [BACKEND / "app", BACKEND / "scripts", ROOT / "frontend" / "src",
             *[p for p in (BACKEND / "tests").glob("*.py") if p.name != Path(__file__).name]]
    for root in roots:
        for path in ([root] if root.is_file() else root.rglob("*")):
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                # "NOTIFIED_PRODUCTS" (a count of notified products) and BIS's own
                # "DE-NOTIFIED" wording are different concepts, not the status.
                if re.search(r"(?<![-\w])NOTIFIED(?![\w])", line):
                    stray.append(f"{path.name}:{n}")
    check("no NOTIFIED status string remains in the backend, scripts, tests or frontend", not stray, str(stray[:5]))


def test_a_flagged_cell_is_never_the_applicable_order() -> None:
    print("\n[2] a flagged cell is quoted, not interpreted")
    check("some joined cells are flagged (rescission / supersession)", len(FLAGGED) > 40, str(len(FLAGGED)))
    bad = []
    for number in FLAGGED:
        for code in (lang.EN, lang.HI, lang.TE):
            out = qco.listing_orders_for(number, code)
            flags = {f for g in out.groups for f in g.flags}
            if not flags or lang.listing(code)["flag"].split("{what}")[1] not in " ".join(out.statements):
                bad.append((number, code))
        text = " ".join(qco.listing_orders_for(number).statements).lower()
        # "applies" appears only inside MetrIQ's refusal to say which order applies.
        if text.count("applies") != text.count("does not say which of these orders, if any, applies"):
            bad.append((number, "applies"))
        negated = lang.listing(lang.EN)["boundary"].lower()
        if "in force" in text.replace(negated, ""):
            bad.append((number, "in force"))
    check("every flagged standard carries the do-not-interpret sentence, in en / hi / te, "
          "and never says which order applies or that one is in force", not bad, str(bad[:4]))
    chappal = qco.listing_orders_for("IS 10702: 1992")
    check("IS 10702 (Rubber Hawai Chappal): the rescission is flagged and the cell kept verbatim",
          chappal.groups[0].flags == ["RESCISSION"]
          and chappal.groups[0].notification == next(r["notification"] for r in JOINED
                                                     if r["kb_standard_number"] == "IS 10702: 1992"))
    cotton = next(r for r in JOINED if r["kb_standard_number"] == "IS 12171:2019")
    check("a flag read only from a link's file name still counts (IS 12171 Cotton Bales: 'Rescind' is "
          "only in the PDF's name)",
          cotton["flags"] == ["RESCISSION"] and not cc.FLAGS["RESCISSION"].search(cotton["notification"])
          and any(cc.FLAGS["RESCISSION"].search(o["url"] or "") for o in cotton["orders"]))
    check("the flag detector reads every cue it claims to",
          all(cc.FLAGS[name].search(text) for name, text in [
              ("RESCISSION", "K Acid QCO 2024 Rescind Order"), ("WITHDRAWAL", "Withdrawal Order"),
              ("SUSPENSION", "Temporary suspension of"), ("SUPERSESSION", "Superseded by X Order")]))


def test_listing_orders_never_set_a_status() -> None:
    print("\n[3] listing orders never set a status")
    with_orders = {r["kb_standard_number"] for r in JOINED if r["orders"]}
    no_qco_row = [n for n in with_orders if not qco.qco_for(n)]
    check("hundreds of standards have a listing order", len(with_orders) > 400, str(len(with_orders)))
    check("every one of them without a QCO-table row is NOT_ESTABLISHED",
          all(qco.status_for(n).status == qco.NOT_ESTABLISHED for n in no_qco_row), str(len(no_qco_row)))
    check("IN_FORCE is reached by no standard", all(qco.status_for(n).status != qco.IN_FORCE for n in KB))
    source = (BACKEND / "app" / "qco.py").read_text()
    body = source[source.index("def status_for"):source.index("def for_standard")]
    check("status_for reads no listing data", "_listing" not in body and "listing" not in body.lower())
    for number in ("IS 1660:2024", "IS 10702: 1992"):
        text = " ".join(qco.listing_orders_for(number).statements)
        check(f"{number}: the wording is about the listing, never the user's item",
              text.startswith("BIS's Scheme I listing names") and "your" not in text.lower()
              and "does not state that an order is in force" in text)


def test_the_join_is_exact() -> None:
    print("\n[4] the join is exact")
    items = {i.id: i for i in ITEMS}
    wrong = []
    for row in JOINED:
        item = items[row["record_id"]]
        keys = cc._record_keys(item.model_dump(mode="json"))
        structure = cc.number_structure(cc.clean_number(row["number_as_printed"]))
        if (row["scheme"], structure, row["product"]) not in {(sc, cc.number_structure(n), pr) for sc, n, pr in keys} \
                or row["kb_standard_number"] != item.standard_number:
            wrong.append(row["number_as_printed"])
    check(f"all {len(JOINED)} joined rows match the number and product wording their record quotes",
          not wrong, str(wrong[:3]))
    unjoined = [r for r in ROWS if not r["record_id"]]
    check("rows that did not join carry no standard and are never returned",
          all(r["kb_standard_number"] is None for r in unjoined)
          and not any(r in qco.orders_named_by_listing(n) for n in KB for r in unjoined[:5]))
    check("a near miss is not forced: listing 'IS 269' does not join the record 'IS 269:2015'",
          any(r["number_as_printed"] == "IS 269" and not r["record_id"] for r in ROWS)
          and qco.orders_named_by_listing("IS 269:2015") == [])
    check("formatting alone does not block a join: 'IS/IEC 62368: Part 1: 2023' joins "
          "'IS/IEC 62368 (Part 1) : 2023' (same prefix, number, parts and year)",
          any(r["number_as_printed"] == "IS/IEC 62368: Part 1: 2023"
              and r["kb_standard_number"] == "IS/IEC 62368 (Part 1) : 2023" for r in JOINED))
    check("structure must be EQUAL: a missing year or different parts never joins",
          cc.number_structure("IS 269") != cc.number_structure("IS 269:2015")
          and cc.number_structure("IS 302 (Part 2/Sec 3)") != cc.number_structure("IS 302 (Part 2/Sec 201)")
          and cc.number_structure("IS/IEC 62368: Part 1: 2023") == cc.number_structure("IS/IEC 62368 (Part 1) : 2023"))
    check("lookup is exact on the number as stored", qco.orders_named_by_listing("IS 1660") == []
          and qco.orders_named_by_listing("IS 1660:2024"))
    check("orders parse the S.O. number and the date as printed",
          cc.orders_in("x", [("u", "(S.O. No. 3858 (E) 27/10/2020)")])[0] == {
              "text": "(S.O. No. 3858 (E) 27/10/2020)", "url": "u", "number": "S.O. 3858(E)", "date": "27/10/2020"}
          and cc.order_number("GSR 759(E)") == "G.S.R. 759(E)")


def test_order_numbers_are_guarded() -> None:
    print("\n[5] an invented S.O. number is withheld, a supplied one passes")
    context = "SCHEME I NOTIFICATION CELL, AS PRINTED: ... (S.O. No. 3583 (E) dated 9th August 2023)"
    check("supplied, in any printed form, passes",
          not qco.unsupported_order_numbers("S.O. 3583(E), SO 3583 (E) and S.O.No.3583(E)", context))
    check("an invented number is flagged", qco.unsupported_order_numbers("S.O. 9999(E)", context) == {"SO9999"})
    check("a G.S.R. number is checked too", qco.unsupported_order_numbers("G.S.R. 759(E)", context) == {"GSR759"})
    check("a year or an IS number is not an order number", not qco.unsupported_order_numbers("IS 1660:2024 (2023)", ""))
    q = "which standard applies to wrought aluminium utensils?"
    good = BISQuestionAnswerer(ENGINE, ReplyLLM(
        "BIS's Scheme I listing names S.O. 3583(E), dated 9th August 2023, for Wrought Aluminium Utensils.")).ask(q)
    check("/ask: a supplied S.O. number reaches the user", good.fallback_reason == "MODEL", good.fallback_reason)
    llm = ReplyLLM("BIS's Scheme I listing names S.O. 9999(E) for Wrought Aluminium Utensils.")
    bad = BISQuestionAnswerer(ENGINE, llm).ask(q)
    check("/ask: an invented S.O. number is withheld",
          bad.fallback_reason == "GUARD:UNSUPPORTED_ORDER_NUMBER" and "9999" not in bad.answer)
    check("…and the model had been shown the listing cell verbatim",
          "LISTING ORDER RECORD 1" in llm.prompts[0][1] and "NOTIFICATION CELL, AS PRINTED" in llm.prompts[0][1])
    check("the system prompt asks for attribution to the source (rule 11)",
          "Attribute every statement about a Quality Control Order" in llm.prompts[0][0])
    low = BISQuestionAnswerer(ENGINE, ReplyLLM("ok")).ask("what does IS 17153 cover")
    check("a low-confidence answer attaches no listing order", low.listing_orders == [])


def test_a_listing_order_ties_an_order_to_the_product() -> None:
    print("\n[6] an attached listing order counts for untied_qco_claim")
    q = "which standard applies to rubber hawai chappal?"
    ans = BISQuestionAnswerer(ENGINE, ReplyLLM(
        "BIS's Scheme I listing names a Quality Control Order, S.O. 3858(E), for Rubber Hawai Chappal.")).ask(q)
    check("chappal: a listing order is attached and no QCO-table row is", ans.listing_orders and not ans.qco)
    check("…so a QCO mention attributed to the listing reaches the user", ans.fallback_reason == "MODEL",
          ans.fallback_reason)
    check("untied_qco_claim: withheld with nothing attached, allowed with the listing order",
          untied_qco_claim("It is under a QCO.", ans.results, ans.context, [], [])
          and not untied_qco_claim("It is under a QCO.", ans.results, ans.context, [], ans.listing_orders))
    led = BISQuestionAnswerer(ENGINE, ReplyLLM("LED bulbs are covered by a Quality Control Order.")).ask(
        "which standard applies to an LED bulb?")
    check("LED bulb: a listing order IS attached (it joins since Phase 10), but its cell names the "
          "Compulsory Registration Order, not a QCO — so the QCO claim is still withheld",
          led.listing_orders and led.fallback_reason.startswith("GUARD:"), led.fallback_reason)
    check("untied_qco_claim: a listing cell that names no QCO does not tie one",
          untied_qco_claim("It is under a QCO.", led.results, led.context, [], led.listing_orders))


def test_surfaces() -> None:
    print("\n[7] card, journey and report")
    body = product_standard_post(ProductStandardRequest(product="wrought aluminium utensils"))
    card = next(r for r in body.results if r.standard_number == "IS 1660:2024")
    check("/product-standard carries listing_orders beside qco", card.listing_orders and card.qco)
    row = report_row(card.listing_orders.model_dump())
    check("the PDF report row quotes MetrIQ's sentences and the Gazette links",
          row and row[0][0] == "Order named by BIS's listing" and "S.O. 3583(E)" in row[0][1] and "https://" in row[0][1])
    check("a record saved before Phase 9.1 prints no row", report_row(None) == [])


def test_the_plural_fix() -> None:
    print("\n[8] the plural fix")
    check("-ches / -shes / -xes / -sses drop 'es' in the phrase rule",
          _tokens("wrenches switches brushes boxes glasses") == ["wrench", "switch", "brush", "box", "glass"])
    check("…everything else is unchanged (bottles -> bottle, sizes -> size, glass stays)",
          _tokens("bottles sizes glass lamps") == ["bottle", "size", "glass", "lamp"])
    outcome = ENGINE.search("pipe wrench")
    check("'pipe wrench' retrieves IS 4003's records first, with high confidence",
          outcome.confidence == "high"
          and {r.item.standard_number for r in outcome.results[:2]} == {"IS 4003 (Part 1): 1978", "IS 4003 (Part 2): 1986"},
          str([r.item.standard_number for r in outcome.results[:2]]))
    found = ProductStandardFinder(ENGINE).find("pipe wrench")
    check("…and Product -> Standard returns them",
          {"IS 4003 (Part 1): 1978", "IS 4003 (Part 2): 1986"} <= {r.item.standard_number for r in found.results})
    process = ENGINE.search("What is the BIS certification process?")
    check("a singular -ss word does not reach its '-sses' plural: 'certification process' does not "
          "match IS 16655 (welding clothing 'for … allied processes')",
          "IS 16655 : 2017" not in [r.item.standard_number for r in process.results[:3]],
          str([r.item.standard_number for r in process.results[:3]]))
    check("…and the QCO boundary's phrase rule matches 'Pipe Wrenches'",
          "Pipe Wrenches-General Purpose" in [w for _, w in qco.boundary_rows("pipe wrench")])


def main() -> int:
    test_the_rename_is_complete()
    test_a_flagged_cell_is_never_the_applicable_order()
    test_listing_orders_never_set_a_status()
    test_the_join_is_exact()
    test_order_numbers_are_guarded()
    test_a_listing_order_ties_an_order_to_the_product()
    test_surfaces()
    test_the_plural_fix()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
