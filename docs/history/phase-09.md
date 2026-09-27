## Phase 9 — Quality Control Order layer, lookup-only (2026-09-26)

**Step 0.** `scripts/eval_retrieval.py` now writes the gitignored `tests/data/eval_latest.json`;
only `--write-baseline` moves the committed `eval_baseline.json` (a plain run used to overwrite it,
date stamp included). The reproducibility test still compares against the committed baseline.

**Step 1 — what BIS publishes (checked 2026-09-26).** No HTML table and no PDF lists QCOs *in
force*. Found: (a) `bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/` — one HTML table,
29 rows, row 13 (IS 302 (Part 1)) spanning 90 listed appliances, no row links; (b) ~276 individual
order / amendment / rescind / withdrawal / suspension pages (WordPress attachments, one Gazette PDF
each — not a list); (c) two PDFs, neither a list: `Guidance-document-on-QCOs-Revised-1.pdf` (3 pages,
scanned guidance) and `QCO_HMD.pdf` (5 pages, hallmarking QCO exemptions); (d) the Scheme I / Scheme II
compulsory-certification pages carry a per-row "Notification" column naming each product's order with
S.O. number, date and Gazette link (378 of Scheme I's rows, 15 of Scheme II's). (d) was NOT ingested:
the column never says "in force" and its cells mix in rescind orders (K Acid, Acrylonitrile), a
temporary suspension (Linear Alkyl Benzene) and "superseded by" notes, so reading a status from it
would need the orders themselves. Left for a human decision.

**Ingest.** `scripts/fetch_qco.py` (build-time, stdlib) -> `data/knowledge/quality_control_orders.json`:
29 records, cells verbatim (IS number exactly as printed, enforcement date exactly as printed, the 90
sub-products inside row 13's record), `source_authority: QUALITY_CONTROL_ORDER` (new, one value; the
ministry is data), paired 1:1 with the new category `quality_control_orders` the way `legal_metrology`
is, `source_organization` naming BIS as publisher of the table and the ministry as issuer.
`SearchEngine.__init__` excludes the category exactly as it excludes `standard_clauses`; eval identical.
`verify_snapshot.py` gains a `qco-upcoming` probe (row + date + listed products hashed); baseline
recorded, 29 rows.

**Matching** (`app/qco.py`): normalise whitespace and a missing "IS " only; attach on an exact
number + part/section + year. 28 of 29 rows attach; the mismatch is Sr. 1, IS 12795:2020 (Linear Alkyl
Benzene) — `NUMBER_NOT_IN_KB`. Reasons: `NUMBER_NOT_IN_KB` / `PART_SECTION_DIFFERS` / `DIFFERENT_YEAR` /
`KB_RECORD_HAS_NO_YEAR`, printed by `check_knowledge.py`; never corrected. 16 of the 28 name an edition
MetrIQ's Phase 5 evidence shows is SUPERSEDED_BY — both facts are shown, the edition sentence saying
MetrIQ does not say which edition the order requires.

**Status** — `IN_FORCE` (a table stating in force: none exists, so 0) · `UPCOMING` (28 standards) ·
`NOT_ESTABLISHED` (477). Status comes from WHICH TABLE the row is in (`STATUS_BY_TABLE`), never from
today's date: a passed date keeps UPCOMING and adds "That date has passed; MetrIQ cannot confirm
whether the order took effect or was deferred." `NOT_ESTABLISHED` says a compulsory-certification
listing is a different fact. Sentences in `language.QCO` (en/hi/te), the sixth translated string set.

**Wiring.** `/ask` attaches QCO rows for the same confidently retrieved standards clauses attach to
(`GroundedAnswer.qco`), shows them to the model verbatim with MetrIQ's status, renders them in the
evidence-only fallback, and `untied_qco_claim` accepts an attached row as the tie; prompt rule 10
confines QCO claims to those records and forbids "in force". The boundary quotes a row when the
question's whole multi-word product phrase (stopwords / FILLER / FOLLOW_UP_WORDS removed, the
product-identification `_tokens` rule) appears in its product wording — none of the eight gap products
does; "coffee makers" does (row 13). `qco` sits beside `currency` on `/product-standard` results,
inspection standard candidates, the certification journey and its candidates, and the PDF report;
frontend `components/QcoStatus.tsx` on the Standards card and the journey. Tests: `test_qco.py`.

