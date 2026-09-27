## Phase 11 — The Standard Passport (2026-09-27)

One page per Indian Standard, the ONE canonical destination for a standard's detail. Routes:
`/standard/:id` (the indian_standards record's stable slug id — numbers carry slashes) and
`/standard?number=<as stored>` → `GET /standard-passport/lookup`: a number WITH a year names that edition
only; WITHOUT a year it names every held edition of that number / part / section (via
`lab_registry.StandardKey`); one match redirects, several are listed and never picked (`IS 16242 (Part 1)`,
`IS 5175`), none shows "MetrIQ holds no verified record". IS 16102 (Part 1) is ONE record — its 2012 / 2026
editions are catalogue evidence shown in Identity and Currency.

**Composer.** `app/standard_passport.py` + `GET /standard-passport/{id}` — read-only, no model, no retrieval,
no write (tested with every model and the search engine disabled, data files hashed before/after). No
existing endpoint served it: /product-standard and /search need a query and rank; /certification-guidance
carries currency / QCO / listing orders but not identity, coverage, scope or clauses; /standard-clauses is
only the Phase 10 groups. It composes identity (record + Phase 4 catalogue; ICS code and sectional committee
are NOT held — the catalogue search returns neither — and the page says so), coverage (`product.text_held` +
Phase 10 withheld count), currency (Phase 5), legal status (Phase 9 QCO + 9.1 listing orders), scope and
requirement clauses (Phase 7), and only the sources stored with that evidence. Sections 7–10 are the existing
features composed by number on the page: ClauseGroups (`defaultOpen`), the M16 journey (explain=false), the
M18 laboratory snapshot (explain=false), and the evidence graph from `POST /product-context` with the
standard number. Every section renders, with MetrIQ's sentence when it has no data.

**One rule for order kinds.** `qco.QCO_NAMED` / `CRO_NAMED` now live in `app/qco.py`; `ListingGroupOut`
gains `names_qco` / `names_cro`, the /ask guard reads `names_qco`, and the Passport shows a visible "Names a
Quality Control Order" / "Names a Compulsory Registration Order" badge per listing group.

**Replaced, not added.** The Standards card keeps the query-specific summary (why this result, matched
terms, collapsed retrieval signals, compact currency / QCO / text-level labels) and links to the Passport;
catalogue block, full currency / QCO / listing panels, text note, scope and ClauseGroups moved off it, and the
page-level evidence graph moved to the Passport (`test_evidence_graph.py` asserts the new location). Links now
pointing at the Passport: Standards card number + "Open the standard passport" (replacing its certification
link), Product Intelligence's STANDARD link (was `/standards?q=`), the certification journey's standard and
candidates, Ask source standard numbers, inspection standard candidates. Coverage-boundary weak matches stay
unlinked — MetrIQ does not put them forward. Checked in a browser by the user (IS 14543:2016, IS 16102 (Part 1),
the IS/IEC 62368 slash lookup, the IS 16242 (Part 1) two-edition list, Standards "electric kettle", the Ask
follow-up chip). Tests: `test_standard_passport.py`.
