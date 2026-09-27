# Phase 6.1 — grounding fixes (moved verbatim from CLAUDE.md; originally inside the Phase 6 section)

**Phase 6.1 (grounding fixes found in the live transcript).** `/ask` prompt rules 8–9: a general FAQ /
bis_general statement is never applied to a specific product unless a record names it (compulsory listing
≠ QCO coverage), and a source is described only from its supplied text. Guard `rag.untied_qco_claim`: a
QCO named while a product is in play needs ONE retrieved record that mentions a QCO AND names that product
or one of its standard numbers, else MetrIQ's evidence text replaces the prose. No guard for rule 9 (not
feasible without false positives — see the phase report). `AskPanel` links "Testing laboratories for …" to
`/laboratories?standard=<number as stored>` for one standard, or `/laboratories?q=<product>` for several
(new `?q=` deep link on LaboratoriesView) — never a picked standard.

