## Phase 7 — Clause text of 31 standards, citation-only (2026-09-26)

`data/knowledge/standard_clauses.json`: **1,537 clause records from 31 standards** (the SHIP list in
`data/clause_candidate_scores.md`, scored by `scripts/score_clause_candidates.py`; ingest report in
`data/clause_ingest_report.md`, built by `scripts/fetch_standard_clauses.py` — build-time, stdlib only,
reusing the scorer's fetch, cache, heading sequence and vocabulary). One new Category value,
`STANDARD_CLAUSES`; no new field. Text is the Public.Resource.Org / Internet Archive mirror of the
edition MetrIQ's record CITES (never another edition), `verification_status: unverified`, no
`last_verified`, and every record ends with MetrIQ's note that it is OCR text from a third-party mirror,
uncorrected — plus, for any standard with amendments (bound-in or separate), that published amendments
are not incorporated. Parsing starts at `1 SCOPE` and stops at the back matter, so amendment sheets never
enter a clause. Tables and figures are cut and replaced by MetrIQ's own sentence pointing at the PDF page.
Clauses are dropped (never corrected) for >10% unreadable prose lines, O/o/l/I-in-digits, Cyrillic/Greek
look-alike characters, or two columns merged on one line; heading-only clauses get no record.
`reference`: djvu.xml leaf N is PDF page N + 1 (verified on three PDFs; per item, leaf count == PDF page
count), so "Clause 5.2.3, PDF page 7", or "page 4 (PDF page 7)" where `_page_numbers.json` maps the leaf,
or "page not established". A bare "page N" is only ever a printed page.

**Citation-only, by measurement.** Indexed in the main search, clause records raised the false-match rate
13.4% -> 17.4% (generic words matched clause prose) and, carrying their parent's `standard_number`,
pushed the `indian_standards` record out of the top 5 on a number lookup — breaking the package
IS-number link, the certification journey, product context and currency. So `SearchEngine.__init__`
excludes `standard_clauses` from both `items` and the index (the only place the engine chooses its items;
no weight or threshold touched), and `app/clauses.py` is the only way in: `clauses_for(number)` (exact
string — "IS 14543" and "IS 14543:2024" get nothing) and `rank_within(number, query)` (the existing
SearchEngine scoring over one standard's clauses). It is a per-standard lookup AFTER the standard is
retrieved, not a second index. Nothing calls it yet except tests. The 31 parent `indian_standards` records
now say clause text of the cited base edition is held, OCR'd from the mirror, unverified by a person.
Eval harness after the fix: identical to `eval_baseline.json` on every metric and all 149 rows.
Tests: `test_clause_scoring.py`, `test_standard_clauses.py`.

**NOTE FOR PHASE 8 (not built):** every UI surface that displays clause text must carry a fixed label
that it is OCR text from a scanned document and must be checked against the named PDF page — values like
"1.0 1 to 1.1 1" (litres read as 1), "60 I/h" and "gf/cm?" survive by design, because nothing is corrected.
Also: the evidence-only fallback's fixed sentence (`language.EVIDENCE_ONLY`) calls its records "verified
BIS records"; that stops being true once clause records can appear in it. No path filters on
`verification_status` in a way that would hide clause records from `/ask` or the copilot — the filters
that exist are all also restricted to `indian_standards` / `certification` records.

