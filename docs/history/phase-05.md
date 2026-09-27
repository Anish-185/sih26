## Phase 5 — Standard currency (2026-09-25)

`app/standard_currency.py` answers one question per standard, deterministically and offline: is the
edition MetrIQ's record cites the newest one MetrIQ's evidence shows? It reads only
`data/standard_archive_index.json` (Phase 4's index, annotated by the build-time
`scripts/fetch_reaffirmations.py`). **It is a statement about MetrIQ's EVIDENCE, never about BIS's
catalogue** — MetrIQ holds no withdrawal data, and a plain-runner test asserts no code path can call a
standard "withdrawn" (every backend string literal, all frontend source, and a stub model saying it
through `/ask`, certification, laboratory search and the copilot guard — which withholds it as
`WITHDRAWAL_CLAIM`).

Statuses, and nothing else: `ACTIVE` · `REAFFIRMED` · `SUPERSEDED_BY` · `NOT_ESTABLISHED`. Signals,
strongest first: (1) a reaffirmation of the CITED edition — BIS's catalogue `reaffirm_year` (almost
always "0", i.e. unstated: 1 hit) or the edition's own cover page via the mirror ("(Reaffirmed 2020)",
quoted exactly — only the phrase, never the OCR noise around it); (2) BIS's Know Your Standards edition
list; (3) the mirror's edition list. A reaffirmation does not outrank a later edition (IS 14543:2016,
reaffirmed 2021, is still SUPERSEDED_BY IS 14543:2024, and says both); a reaffirmation dated after the
later edition is a contradiction -> NOT_ESTABLISHED. **ACTIVE is granted only on BIS's own catalogue**,
worded "BIS's own catalogue, read on <date>, lists X as the newest edition … a revision published after
that reading would not show here". A mirror that shows no later edition is NOT_ESTABLISHED, because a
third-party snapshot can lag a revision. A record with no cited year (the ten Phase 4 refused to date)
is NOT_ESTABLISHED and names every edition known. `LabRegistry.other_editions()` answers a different
question (which LIMS labs are listed against another edition) and is untouched; this module generalises
its idea — name the other editions, never hide them.

Distribution over the 505 standards: ACTIVE 238 · REAFFIRMED 98 · SUPERSEDED_BY 132 ·
NOT_ESTABLISHED 37 (14 no cited year / not among recorded editions, 13 unresolved by both routes,
10 mirror-only). Surfaced as `currency` on `/product-standard` results, inspection standard candidates,
the certification journey and its candidates, and an "Edition" row in the PDF report; frontend
`components/EditionCurrency.tsx` (existing tokens only). `check_knowledge.py` prints the distribution.
The cache helper in `fetch_standard_titles.py` now writes atomically — an interrupted run had left
zero-byte cache files that crashed the next one. Tests: `test_standard_currency.py`.

