## Phase 1 — Reframe and demo hardening (2026-09-24)

Not a new subsystem: a repositioning plus two pieces of demo insurance. **No feature was
deleted and the inspection code is untouched** — a later phase re-sources its declared-field
requirements from the standards themselves (IS 14543 clause 7 MARKING is the normative list),
which is why it is reframed rather than cut.

**Part A — the product is a BIS standards intelligence assistant.** The old identity,
"MetrIQ — AI-Assisted Legal Metrology Inspection", described a compliance audit the problem
statement never asked for and whose verdict engine the final hardening pass deliberately
removed, so it promised something MetrIQ does not do. The name stays; the strapline is now
"Indian Standards & BIS Services · Evidence-backed". Changed: `frontend/index.html` (title +
meta), `frontend/package.json`, both READMEs, the footer strapline and its four-stage band in
`components/layout.tsx`, and the home page. The camera is repositioned as a **standards
discovery entry point** — photograph a product → identify it → the standard that governs it →
the certification route → the laboratories BIS lists — sold as the fastest way *into* the
standards when you do not know what a product is officially called, never as an inspection.
The home page now leads with Q&A and Product → Standard; the camera is the demonstration
inside that story (a text link under the hero CTAs, and the third button in the closing CTA).
Hero counts are now read from `GET /inspection/coverage` (verified standards, standards with a
certification route) alongside the saved-inspection total, so the page opens on knowledge
rather than on audit counts.

**The missing surface, added:** BIS Q&A is the problem statement's first MVP feature and was
reachable only through the Hallmarking page. The ~90 lines of Q&A JSX inside
`HallmarkingView.tsx` became `components/AskPanel.tsx` (question field, language picker,
examples, the grounded answer, the empty state) and now serve two call sites: the new
`features/AskView.tsx` at route `/ask` (nav "Ask", first in the bar) and Hallmarking, which
differ only in their examples and empty-state copy. No new component vocabulary, no new
colours, no redesign.

**Part B — snapshot drift.** `backend/scripts/verify_snapshot.py` re-fetches the pages the
knowledge base was built from, parses them with the SAME parsers that ingested them
(`fetch_compulsory_certification.parse_scheme_i/ii`, `fetch_lims_laboratories.parse_rows` —
imported, not reimplemented), hashes the PARSED ROWS with `hashlib.sha256`, and reports the
difference against `data/source_snapshots.json`. Hashing the rows rather than the raw HTML is
the point: page chrome, banners and nonces change on every request and would report drift that
is not there, while a product appearing or disappearing always changes the hash — and because
the rows are stored, the report NAMES the added and removed products, not just "CHANGED".
**It never writes the knowledge base** (one `write_text` in the file, the baseline; asserted by
test), the application never reads the baseline (asserted), and `--record` is the only way to
move it. A source that is unreachable is reported as unreachable, never as drift. LIMS answers
one standard per request, so it is sampled (`--lims-standards`, default 5) and the report
prints the sample size next to the snapshot total — a sample is only honest if its size is on
the page. First recorded baseline (2026-09-24): Scheme I 421 rows, Scheme II 75 rows, LIMS 132
rows across 5 of 77 standards. This answers "what happens when BIS updates?" in one command,
with no runtime dependency on a government portal.

**Part C — evidence-only answers.** `/ask` used to return 503 when the provider was down, and
free OpenRouter model slugs have been pulled out from under this project before. Retrieval has
already succeeded by the time the model is called, so an outage now degrades the PROSE and
never the evidence: `app/rag.render_evidence()` renders the retrieved verified records as plain
text written by MetrIQ's own code — MetrIQ's fixed, translated lead sentence
(`language.EVIDENCE_ONLY`, the fourth and last hard-coded translated string set, beside
INSUFFICIENT / EMPTY_QUESTION / WITHHELD) followed by each record's stored title, standard
number, content, organization, document and URL, verbatim. Record text stays in its stored
English; the knowledge base is still never translated. `GroundedAnswer.explained` carries it
through `/ask` (`AskResponse.explained`), and the UI labels it "Evidence only" with a callout —
never silently. Abstention is unchanged and still never reaches the model. **Three tests were
rewritten because the behaviour deliberately changed** (`test_rag.py`, `test_api_contract.py`,
`test_multilingual.py`); `/ask` no longer has a 503 path at all. `/certification-guidance` and
`/laboratory-search` keep theirs — only `/ask` was in scope.

**Deliberately not done:** the optional VERIFIED / CACHED / CHANGED / NOT ESTABLISHED status
vocabulary. The badge it would replace is *retrieval* confidence (how well a query matched a
record); that vocabulary describes *snapshot freshness*, which is what Part B measures. Swapping
one for the other would label every answer with a fact the badge does not know.

**One pre-existing bug found and fixed while validating** (it failed at HEAD too, and it is
exactly the fragility Part C exists for): `openrouter.DEFAULT_MODEL` and
`vision.DEFAULT_VISION_MODEL` both still pointed at `inclusionai/ling-3.0-flash-vl:free`, which
OpenRouter has since withdrawn — checked live against its model list, not from memory. The
running configuration in the gitignored `backend/.env` had been moved on but the in-code
fallbacks had not, so a fresh clone with no `.env` pointed at a 404. Both now carry live slugs
(`nvidia/nemotron-3-super-120b-a12b:free` for text, `dots-studio/dots-3-note-preview:free` for
vision), and the two tests that hard-coded the slug now assert the invariant that matters (the
default is a concrete OpenRouter slug, and the constant is what the client uses) instead of a
literal that will drift again.

Tests: `test_snapshot_drift.py` (23 checks, entirely offline — hashing, row-level drift
reporting, "reports but never writes", and the recorded baseline's integrity).

