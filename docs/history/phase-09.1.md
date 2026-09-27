## Phase 9.1 — Orders named by BIS's listing, IN_FORCE, and a plural fix (2026-09-26)

**Rename.** The QCO status `NOTIFIED` is now `IN_FORCE` everywhere (code, tests, frontend, en/hi/te
labels): BIS's own page title uses "notified" to mean "published in the Gazette", the opposite of our
meaning. Still 0 standards: no BIS source states an order is in force.

**Listing Notification column — evidence, not status.** `fetch_compulsory_certification.py
--notifications` (same fetch, same parsers — they now also capture each cell's links and honour the
Notification cell's rowspan, so a stale cell cannot leak into the next group; the script has no cache,
deliberately, since `verify_snapshot.py` reuses its `fetch`) writes `data/listing_notifications.json`: per
listed row the Notification cell VERBATIM, each order it names (S.O. / G.S.R. number, date as printed —
with or without "dated" — and Gazette link) and flags RESCISSION / WITHDRAWAL / SUSPENSION / SUPERSESSION,
read from the cell text, the link text AND the link's file name (BIS often says "Rescind" only there).
496 rows (Scheme I 421, Scheme II 75); a row joins a record only on the exact listing number and product
wording that record's own text quotes — 435 join, 61 do not (mostly Milestone 14's hand-transcribed
records, e.g. `IS/IEC 62368: Part 1: 2023` × 43 products and `IS 269` vs `IS 269:2015`; listed by the
tests, never forced). 434 standards have a listing order; 53 joined records' cells are flagged (27
RESCISSION — footwear, Cotton Bales; 26 SUPERSESSION — LED luminaires). `qco.orders_named_by_listing()`
(exact number as stored) and `listing_orders_for()` (MetrIQ's sentences, `language.LISTING` en/hi/te —
the seventh translated set): "BIS's Scheme I listing names these orders for …", a flagged cell adds
"MetrIQ quotes the cell and does not interpret it, and does not say which of these orders, if any,
applies", and every block ends "It does not state that an order is in force". `status_for` never reads
it. `/ask` attaches it by the clause/QCO rule, shows the cell verbatim, and `untied_qco_claim` accepts it
as the tie; new guard `qco.unsupported_order_numbers` withholds an S.O. / G.S.R. number absent from the
context (`GUARD:UNSUPPORTED_ORDER_NUMBER`); the regulatory-term guard now reads BIS's "(Quality Control)
Order" as "quality control order". `listing_orders` sits beside `qco` on the Standards card
(`components/ListingOrders.tsx`), the journey, inspection candidates and the PDF report. Prompt rule 11:
attribute QCO / order statements to their source. The drift check still hashes number + product only, so
a change to a Notification cell alone is not reported as drift.

**Plural fix, accepted.** The rule existed twice: `product_identification._tokens` (phrase gate, QCO
boundary) and `retrieval.engine._contains_word` (retrieval). Both now treat -ches/-shes/-xes/-sses
plurals as "-es" (the engine also tries -zes, alongside the old "-s" form, so nothing that matched stops
matching; the phrase rule leaves -zes alone because "sizes" -> "siz" would break "size"). The engine's
singular -> "-es" direction covers -ch/-sh/-x/-z but NOT -ss: with it, "What is the BIS certification
process?" matched IS 16655 (welding clothing "for … allied processes") at HIGH confidence —
`test_certification.py` caught it, the eval set has no such query. Ceiling: a singular "mattress" still
finds nothing (only "mattresses" reaches IS 16014), as before the fix. Affected
record words: latches, punches, switches, wrenches, boxes, mattresses, processes. Eval: identical to
`eval_baseline.json` on every metric and row (baseline not rewritten). "pipe wrench" now retrieves
IS 4003 (Part 1) and (Part 2) at high confidence. Tests: `test_listing_orders.py`.

