## Phase 10 — Step 0: listing join on structure, drift on the Notification cell (2026-09-26)

**Join.** A listing row now joins a record when Phase 4's `parse_number` gives EQUAL (prefix, number,
parts, year) for the two numbers — exact on structure, not spelling — AND the product wording is
identical. The join also reads the third provenance wording Milestone 14's hand-transcribed records use
(`BIS lists the standard as "N"` + `BIS lists the following products against this standard in the …
list: A; B; …`). 469 of 496 rows join (was 435): 34 new — 32 IS/IEC 62368 (Part 1) products, IS 16046,
IS 16102 (Part 1), IS 302-2-25 (Microwave Ovens), IS 8828. IS 16102 (Part 1) joins because NEITHER side
carries a year, the parts agree and the wording is identical. 27 stay unjoined: 6 because the listing
gives no year where the record has one (IS 269 / 455 / 12330 / 1489 (Part 1) / 3854 / 694); 19 because
the product wording differs (11 IS/IEC 62368 products absent from, or spelt differently in, the record's
list — e.g. 32″ vs 32"; IS 16415 trailing "."; IS 12640 (Part 2), IS 302 (Part 2/Sec 3, 201, 202),
IS 16242 (Part 1) "Invertors of rating≤5kVA"); 2 because the record quotes no listed product
(IS 17803, IS 17526 — built from an advisory and a product manual). 439 standards now have a listing order.

**Guard regression fixed.** With IS 16102 (Part 1) now joined, LED lamps carry a listing order — whose
cell names the Electronics & IT Goods (Requirements for Compulsory Registration) Order, not a QCO. The
9.1 rule "any attached listing order ties a QCO" let "LED lamps are covered by a Quality Control Order"
through (`test_conversation_context.py` caught it). A listing order now ties a QCO claim only when its
own cell names a Quality Control Order.

**Drift.** `verify_snapshot.scheme_items` hashes number + product + Notification cell, so a cell change
alone is reported (tested on a synthetic page). The Scheme I / II baselines were re-recorded after
confirming number + product were identical to the previous baseline on all 421 + 75 rows.

## Phase 10 — Sampling, criteria for conformity and test methods (2026-09-26)

`app/clause_groups.py` answers the problem statement's "sampling frequencies, acceptance parameters and
required test equipment" by QUOTING clauses, never summarising and never computing a frequency. It is a
deterministic selector over `clauses.clauses_for(number)` — no search index, no model, no network — that
puts a clause in SAMPLING / CRITERIA_FOR_CONFORMITY / TEST_METHODS only by its OWN heading or text; a clause
may be in several, and each carries `matched` ("heading: SAMPLING", "text: size of the lot"). The rule
(word lists, heading vs text) is written in the module docstring. A HEADING is a first line after the
clause number of ≤ 8 words whose words of 4+ letters all start with a capital; otherwise the first line is
prose. Line breaks are read as spaces before matching (OCR breaks lines anywhere).

**TEST_METHODS rule — R chosen.** Counts over all 1,537 clauses of the 31 standards: H (test word in the
heading only) 91 · **R (H, or the text references a method-of-test annex / standard — "tested in
accordance with … IS 5401", "method prescribed in Annex C", "apparatus") 175** · W (any test word anywhere)
444. H misses IS 14543 entirely (0 — its test methods are referenced from requirement text); W admits
every "shall not crack when tested" requirement. R includes ambiguous clauses rather than drop evidence.

**Tables and completeness.** A grouped clause keeps Phase 7's table pointer (IS 14543 F-1.2.3 — the
scale-of-sampling clause, "according to Table 5" — is in SAMPLING with its pointer to PDF page 19; clause 9
carries the page-7 method table pointer); no table is reconstructed. Withheld counts are read from
`data/clause_ingest_report.md` (Dropped + Duplicates, each dropped clause named): IS 14543:2016 12,
IS 367:1993 3, IS 4151: 2015 7; a standard absent from the report says the groups may be incomplete,
without a number. Statuses: CLAUSE_TEXT · IDENTITY_ONLY (474 standards — MetrIQ's one sentence that it
holds the identity, not the text; never prose) · UNKNOWN_STANDARD. Sentences in `language.CLAUSE_GROUPS`
(en/hi/te), the eighth translated set.

**Delivery.** `GET /standard-clauses?standard_number=…&language=…` (read-only; no existing endpoint serves
it — /search and /product-standard rank records against a query and never return clause records, /ask
attaches ≤ 3 clauses per standard ranked against a question). `components/ClauseGroups.tsx` — standalone,
takes a number as stored, fetches on open — on clause-level Standards cards (for the Phase 11 Passport).
PDF report: "Sampling, conformity and test methods" section for the identified standard. /ask unchanged.
Tests: `test_clause_groups.py`.

