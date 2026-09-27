# SIH26107 — Evidence-Backed AI Assistant for Indian Standards & BIS Services

Detailed history lives in docs/history/. When a task depends on an earlier phase, read that phase's file before changing code.

## What this project is

A polished, reliable hackathon prototype. A user (industry, MSME, startup, student,
or consumer) asks a BIS-related question in natural language and receives:

1. Relevant BIS information
2. Applicable or candidate Indian Standards **only when supported by evidence**
3. A simple explanation
4. "Why this result?" reasoning grounded in retrieved evidence
5. Official BIS sources
6. Useful next steps

## Core principle (do not violate)

This is an **evidence-backed retrieval and explanation system**.

```
natural language
  -> query understanding
  -> BIS knowledge retrieval
  -> evidence ranking
  -> grounded LLM explanation
  -> answer + evidence + next steps
```

**The LLM is NOT the source of truth. Retrieved BIS information is the source of truth.**

## MVP features (exactly these five)

1. BIS Q&A
2. Product -> Standard discovery  **(flagship)**
3. BIS certification guidance
4. BIS-recognized laboratory search
5. Hallmarking / HUID information

Flagship experience: **"Why this result?"** — for Product -> Standard queries, explain
why a candidate standard was retrieved using actual evidence (product category,
material, intended use, or other info present in the retrieved BIS source).

A standard may only be shown as a recommendation if it exists in the retrieved
knowledge base. **Never invent a standard number.**

## Trust & hallucination rules

The system must NEVER invent:

- Indian Standard numbers
- BIS clauses
- certification schemes
- fees
- testing requirements
- laboratory capabilities
- legal requirements
- HUID results
- certification outcomes

If evidence is insufficient, **explicitly communicate uncertainty or abstain** —
do not guess. Distinguish between: verified information, inferred relevance, uncertainty.

## Architecture

- **Frontend:** React + TypeScript + Vite + Tailwind CSS. shadcn/ui only where useful.
- **Backend:** Python + FastAPI.
- **Database:** PostgreSQL.
- **Retrieval:** Start with simple keyword / full-text retrieval. Add semantic/vector
  retrieval **only if** testing shows a meaningful improvement. Do not add vector
  infrastructure just because it sounds advanced.
- **AI:** LLM provider must be replaceable. Do not architect around Claude specifically.
  The LLM understands and explains retrieved information; retrieved BIS evidence is
  the source of truth.

## Scope limits

Hackathon prototype. **DO NOT introduce:** microservices, Kubernetes, Kafka, agent
swarms, multi-agent architecture, custom LLM training, fine-tuning, computer vision,
mobile apps, voice assistants, fake BIS APIs, fake HUID verification, fake laboratory
results, autonomous legal decisions, unnecessary infrastructure, massive scraping
infrastructure.

Prefer the smallest architecture that produces a reliable and impressive demo.

## Engineering rules

1. Inspect the existing repository before changing anything.
2. Preserve useful existing work.
3. Implement only the current milestone. Do not implement future milestones.
4. Do not add dependencies unless necessary.
5. Do not redesign the architecture without a concrete technical reason.
6. Do not refactor unrelated code.
7. Reuse existing patterns where appropriate.
8. Run relevant tests / checks / builds after changes.
9. Never claim something works without verifying it.
10. Prefer deterministic logic for retrieval, ranking, validation, and structured data.
11. Keep the code understandable to a beginner.
12. Do not create abstractions for hypothetical future requirements.
13. Do not create unnecessary files.
14. Do not use subagents for simple inspection, small edits, or straightforward debugging.
15. Parallelize independent tool operations; keep dependent work sequential.

## The developer

A complete beginner. Work incrementally. Explain what changed and why. Do not assume
familiarity with the codebase, the tools, or the frameworks.

## UI design direction

Aesthetic inspired by the *design philosophy* of Supermemory, but the product must
remain an original BIS interface. Do not copy Supermemory branding, logo, content,
or exact layouts.

Feel: minimal, premium, calm, editorial, modern, spacious, intentional, slightly
futuristic, content-first.

Color system:

- warm off-white / cream background
- very dark charcoal / near-black primary text
- muted warm-gray secondary text
- restrained cyan/blue accent

Avoid: purple AI gradients, blue-purple gradients, excessive neon, glassmorphism,
heavy shadows, huge rounded cards, excessive pills, noisy dashboards, decorative clutter.

Prefer: generous whitespace, strong typography, thin subtle borders, minimal surfaces,
small/moderate corner radii, subtle interaction states, precise alignment, editorial
composition. Premium information/research assistant, not a generic AI SaaS dashboard.

## Knowledge base

Prioritize official BIS information. For the prototype, use a **focused curated
dataset** — do not pretend to have complete BIS coverage. Potential categories:
BIS general info, Indian Standards, certification, certification procedures, testing,
laboratories, hallmarking, consumer information, FAQs.

## Development order (do not skip ahead)

| Phase | Name |
|------:|------|
| 1  | Foundation |
| 2  | BIS knowledge base |
| 3  | Retrieval |
| 4  | RAG / AI answers |
| 5  | Product -> Standard |
| 6  | Certification |
| 7  | Laboratories |
| 8  | Hallmarking |
| 9  | Why this result |
| 10 | UI polish |
| 11 | Testing |
| 12 | Demo hardening |
| 13 | Real IMAGE -> OCR |
| 14 | OCR -> declarations -> product -> Indian Standard |

Only implement the current milestone. Do not start a new phase without being asked.

## Current state (2026-09-27, after Phase 11)

- **Tests:** full backend suite `394 passed` (`cd backend && ./.venv/bin/python -m pytest -q`;
  `test_plain_runners.py` runs every plain-Python runner, so pytest is the authoritative gate).
- **Knowledge base (`data/knowledge/`, 2,141 records):** 505 verified Indian Standards
  (`indian_standards.json`), 1,537 OCR clause records from 31 standards (`standard_clauses.json`,
  unverified, citation-only), 29 Quality Control Order rows (`quality_control_orders.json`),
  16 certification, 14 FAQs, 13 hallmarking, 7 Legal Metrology, 6 bis_general, 6 consumer
  information, 4 laboratories, 4 testing.
- **Laboratories:** BIS LIMS snapshot (`data/laboratories.json`) — 86 of 505 standards have a listed laboratory.
- **Coverage invariants (asserted by tests):** 15 requirements (7 checkable in principle — data
  annotation only, no engine runs them), 2 INSPECTION_SUPPORTED, 4 UNSUPPORTED (hallmarking), the
  rest STANDARD_ONLY. Currency: ACTIVE 238 · REAFFIRMED 98 · SUPERSEDED_BY 132 · NOT_ESTABLISHED 37.
  QCO: IN_FORCE 0 · UPCOMING 28 · NOT_ESTABLISHED 477. Certification guidance resolves for 498 of 505.
- **Retrieval baseline** (`tests/data/eval_baseline.json`): recall@1 85.6%, recall@5 98.1%,
  abstention 24.4%, false-match 13.4% — unchanged by every phase since Phase 2.
- **Models:** OpenRouter for `/ask`, certification and the copilot (vision: separate key/model); LM
  Studio only for inspection product-identification and Laboratory `explain=true`. No PASS/FAIL verdict anywhere.

## Commands

- Backend: `cd backend && ./.venv/bin/uvicorn app.main:app --port 8000` (needs `DATABASE_URL`,
  default `postgresql+psycopg:///metriq`; migrate with `alembic upgrade head`). Frontend:
  `cd frontend && npm install && npm run dev` (proxies `/api` -> :8000).
- Tests: `cd backend && ./.venv/bin/python -m pytest -q`, or one runner:
  `./.venv/bin/python tests/<file>`. PostgreSQL tests need the `metriq_test` database and refuse
  any database not named `*_test`.
- Frontend checks: `cd frontend && npx tsc --noEmit && npm run build`.
- Knowledge: `./.venv/bin/python scripts/check_knowledge.py` (validation + coverage tables; `--json`).
- Retrieval eval: `./.venv/bin/python scripts/eval_retrieval.py` (writes gitignored
  `tests/data/eval_latest.json`; only `--write-baseline` moves the committed baseline; `--derive`
  rebuilds the query set).
- Source drift: `./.venv/bin/python scripts/verify_snapshot.py` (reports only; `--record` moves the
  baseline; never writes the knowledge base).
- `backend/scripts/fetch_*.py` are build-time ingestion tools (stdlib only); the app never calls those sources at runtime.

## History index — key decisions per milestone and phase

### First revision (Phases 1–14, Milestones 1–15) — `docs/history/milestones-01-15.md`

- **Phases 5–9 (first revision):** Product -> Standard, certification, laboratories, hallmarking via
  `/ask` (never claim to verify a physical item's HUID / hallmark / licence), and a deterministic
  "Why this result?" from retrieval's own `MatchReason`s — no LLM, never claims legal applicability.
- **Phases 10–12:** UI polish; testing (fake LLMs, `test_plain_runners.py`); demo hardening
  (`LLMError` is a short user-facing message, never a raw httpx string).
- **Phase 13:** fully local OCR (`rapidocr-onnxruntime`); a failed OCR never substitutes demo data.
- **Phase 14:** declarations (14 fields, each keeps region/bbox/confidence/method; FSSAI licence is
  food-safety, NOT a BIS standard); the model classifies, it never emits a standard number. The
  separate standards registry was later retired into the knowledge base.
- **Milestones 1–7:** multi-side packages (CONFLICT withholds the value; a failed side is reported,
  never treated as absent); "Not detected" is never reported as legally missing; OCR normalization
  never guesses (`raw_text` keeps the original); a brand-like line is never the product name.
- **Milestone 8:** `legal_metrology` category with `source_authority: LEGAL_METROLOGY`, quotes checked
  against official DoCA PDFs; BIS search indexes BIS items only. (Its rule engine was deleted in the
  Final Hardening Pass; the knowledge stays.)
- **Milestone 9:** PostgreSQL; saved records immutable (triggers); `POST /inspections` takes photos only and re-analyses.
- **Milestone 10:** `app/escalation.py` — what could not be established from the photos, evidence-linked.
- **Milestone 11:** PDF report from the stored record only — no write, no recompute, no model; text XML-escaped.
- **Milestone 12:** hallmark / HUID evidence (`app/hallmark.py`) — observed, never authenticated; no
  FAIL; `verification_status` only NOT_VERIFIED / NOT_DETECTED; printed "verified/genuine" claims are
  recorded as untrusted and change nothing.
- **Milestone 13:** OpenRouter copilot — "It explains the record; it never produces it." Key
  server-side only; `guard()` WITHHOLDS invented IS numbers / HUIDs / URLs / authentication claims;
  package text is fenced as untrusted.
- **Milestone 14:** 36 -> 97 standards from BIS's compulsory-certification listings. Keyword policy: a
  keyword is BIS's own wording or a declared common name for the SAME product — sector guesses are
  banned and tested for. `min_terms_for_high`: "high" needs two pieces of evidence.
- **Milestone 15:** vision (`app/vision.py`) with its own key, model and budget. "A visual observation
  is deliberately weaker than OCR, and that is enforced, not hoped for": `_scrub` deletes numbers /
  claims, vision never becomes a declaration or names a standard, agreement never raises confidence,
  disagreement -> REVIEW and MetrIQ never chooses.

### Milestones 16–22 — `docs/history/milestones-16-22.md`

- **Milestone 16:** certification journey (`app/certification_journey.py`), no model — every sentence
  is a word-for-word quote from a verified record plus its URL. A scheme is established only from
  listing provenance or a certification record's text; a disagreement is a conflict (PARTIAL), never
  resolved; several candidates are never silently resolved into one; fees / times / documents are never stated.
- **Milestone 17:** "the language of interaction changes, the source of truth does not." `app/language.py`
  is deterministic (script detection + alias rewrite before retrieval); the KB is never translated;
  English appends nothing to prompts; identifiers (standard numbers, schemes, HUIDs, URLs) are never translated.
- **Milestone 18:** "MetrIQ identifies laboratories from verified laboratory evidence. It does not
  independently establish a laboratory's current accreditation, scope, availability, or operational
  status." LIMS snapshot read at build time only; a standard -> laboratory link exists ONLY because BIS
  lists it; edition-aware `StandardKey`; no ranking (alphabetical); validity only `*_AT_SNAPSHOT`.
- **Milestone 19:** "MetrIQ can identify and explain observable hallmark/HUID evidence, but it does not
  authenticate a physical jewellery item's hallmark, HUID, jeweller registration, or AHC status." No
  AUTHENTIC / VERIFIED / CERTIFIED state exists in any code path; the BIS logo is permanently
  NOT_SUPPORTED; "not detected" is about the photograph; a user HUID is a text comparison only.
- **Milestone 20:** "MetrIQ's copilot explains evidence produced by the deterministic system; it does
  not independently establish standards, compliance, laboratory status, certification applicability,
  or hallmark/HUID authenticity." Feature contexts are whitelisted; `EVIDENCE_VOCABULARY` keeps
  NOT_DETECTED / UNCERTAIN / UNSUPPORTED / NOT_AVAILABLE_IN_KNOWLEDGE_BASE distinct; guard gains
  laboratory status / ranking claims and fabricated amounts.
- **Milestone 21:** "MetrIQ connects evidence produced by its existing deterministic features into a
  unified product context. The context does not create new evidence and does not independently verify
  external facts." `app/product_context.py` is a composer only; `build_from_query` is server-derived,
  `build_from_analysis` composes a finished analysis; conflicts are carried word for word, never resolved.
- **Milestone 22:** the human officer-review workflow is removed. "The MetrIQ evidence graph visualizes
  relationships already established by the deterministic evidence pipeline. It does not independently
  infer standards, compliance, authenticity, laboratory validity, or certification applicability."
  `app/evidence_graph.py` is a projection; nothing downstream imports it; client payloads are whitelisted.

### After Milestone 22

- **Final Hardening Pass** — `docs/history/final-hardening.md`: MetrIQ is not an automated
  legal-compliance judge. `app/compliance.py` and `app/package_label.py` are deleted; `escalation.assess`
  returns `{required, reasons}` only; migration `0003_drop_compliance_verdicts` only drops NOT NULL.
  `/ask` and certification move to OpenRouter via `OPENROUTER_GROUNDED_MODEL`, independent of the
  copilot's `OPENROUTER_MODEL`. Any PASS/FAIL/compliant claim in generated text is `FABRICATED_VERDICT`.
- **Knowledge expansion (97 -> 505)** — `docs/history/knowledge-expansion.md`: the Scheme I / II
  pages read in full. De-notified products are skipped (listing one as notified would be a false legal
  claim); keywords come only from BIS's product name; the tool only appends.

### Revision 2 (Phases 1–11)

- **Phase 1** — `docs/history/phase-01.md`: MetrIQ is a BIS standards intelligence assistant, not an
  inspection product; the camera is a standards discovery entry point. BIS Q&A gets its own page
  (`components/AskPanel.tsx`, `/ask`). `verify_snapshot.py` hashes PARSED ROWS and never writes the KB.
  `/ask` degrades to evidence-only text (`language.EVIDENCE_ONLY`) on a provider outage — no 503.
- **Phase 2** — `docs/history/phase-02.md`: offline eval harness; the query set is DERIVED from
  official pairings, never self-authored; matching stays strict (an edition year is part of identity).
- **Phase 3** — `docs/history/phase-03.md`: informative abstention (`app/boundary.py`, no model).
  MetrIQ never says a product is absent from BIS's lists and says "It does NOT mean that no Indian
  Standard exists for this product."; coverage figures are counted, never typed; weak matches are
  shown but never offered as the answer.
- **Phase 4** — `docs/history/phase-04.md`: catalogue identity for all 505. SOURCE PROVENANCE IS A
  PARAMETER — `--source bis | archive`, mirrored text is never presented as coming from bis.gov.in. A
  year is filled only when exactly one edition exists; damaged titles are kept and flagged, never
  corrected; tests are year-tolerant, the eval harness is not.
- **Phase 5** — `docs/history/phase-05.md`: standard currency (`app/standard_currency.py`) is a
  statement about MetrIQ's EVIDENCE, never BIS's catalogue. Only ACTIVE / REAFFIRMED / SUPERSEDED_BY /
  NOT_ESTABLISHED; nothing may call a standard "withdrawn" (guard `WITHDRAWAL_CLAIM`); ACTIVE only on
  BIS's own catalogue; a mirror showing no later edition is NOT_ESTABLISHED.
- **Phase 6** — `docs/history/phase-06.md`: multi-turn context on `/ask` only — no router, no intent
  classifier, nothing stored server-side. Context comes only from a grounded high/medium
  Product -> Standard outcome, is re-derived (never trusted from the client), several standards are
  carried never narrowed, and inheritance needs a referring word plus no leftover word.
- **Phase 6.1** — `docs/history/phase-06.1.md`: a general statement is never applied to a specific
  product unless a record names it; guard `rag.untied_qco_claim`.
- **Phase 7** — `docs/history/phase-07.md`: clause text of 31 standards, CITATION-ONLY — excluded from
  `SearchEngine` (indexing it raised false-match 13.4% -> 17.4%) and reachable only through
  `app/clauses.py` by exact standard number. Text is the cited edition only, `unverified`, OCR'd,
  never corrected — unreadable clauses are dropped; tables are replaced by a pointer to the PDF page.
- **Phase 8** — `docs/history/phase-08.md`: clauses are ATTACHED after retrieval, never retrieved —
  only at high/medium confidence AND only for a confidently identified or named standard. Every
  clause display carries the fixed OCR label (`clauses.OCR_LABEL`, `components/ClauseText.tsx`);
  unsupported clause citations are guarded; `fallback_reason` is exposed.
- **Phase 8.1** — `docs/history/phase-08.1.md`: `clauses.residual_query` (rank on the words left after
  the standard's own vocabulary); annex-style labels need a dot.
- **Phase 9** — `docs/history/phase-09.md`: QCO layer, lookup-only. Status comes from WHICH TABLE a row
  is in, never from today's date — a passed date keeps UPCOMING with a sentence saying MetrIQ cannot
  confirm it took effect; IN_FORCE is 0 because no BIS table states it. Exact number match only;
  mismatches reported, never corrected; QCO records excluded from search.
- **Phase 9.1** — `docs/history/phase-09.1.md`: `NOTIFIED` renamed `IN_FORCE`. The listing's
  Notification column is evidence, not status (`status_for` never reads it); cells are quoted, never
  interpreted; S.O. / G.S.R. numbers absent from context are withheld. Plural fix (-ches/-shes/-xes/-sses).
- **Phase 10** — `docs/history/phase-10.md`: step 0 joins listing rows on parsed structure plus
  identical wording; a listing order ties a QCO claim only when its own cell names a QCO; drift hashes
  the Notification cell. Main: `app/clause_groups.py` QUOTES sampling / conformity / test-method
  clauses by their own heading or text — never summarises, never computes a frequency; rule R chosen.
- **Phase 11** — `docs/history/phase-11.md`: the Standard Passport is the ONE canonical page per
  standard (`/standard/:id`, read-only, no model, no retrieval). A number without a year lists every
  held edition and never picks one.

- **Phase UI-1** — `docs/history/phase-ui-1.md`: `/chat` is the one place to ask (`/ask` redirects;
  Hallmarking keeps `AskPanel`); Phase 6 context round-trips in page state. UI-1.1: Passport prints to PDF;
  OPEN: LED "is it mandatory?" — fixed 3/3 in fdc106d; rule-12 rewording (cba79d1) awaits live check after 05:30 IST reset.

## Open notes for later phases and known weaknesses (verbatim)

From Milestone 18 (`milestones-16-22.md`):

Coverage, measured: **1,205 records · 245 laboratories · 157 standards as listed · 83 cities**;
**78 of 97** verified KB standards have at least one listed laboratory, 19 have none, and that is
reported rather than padded. Recorded verbatim when present: lab name, OSL code, city, standard as
listed, product as listed, grade/type, recognition validity date, BIS remark. NOT recorded because
LIMS does not print it: address, phone, email, accreditation number, NABL status. Testing charges
are deliberately skipped (they change often and are not needed to find a laboratory).

From Milestone 19 (`milestones-16-22.md`):

or compliance module (tested). The jeweller registration and AHC workflows are deliberately NOT
built. Two real regressions were caught by existing suites and fixed at source: the report glued a

From the Final Hardening Pass (`final-hardening.md`):

all, unaffected. **`app/llm.py`/LM Studio remains in active use in exactly two places, and only
two:** the inspection pipeline's product-identification fallback (`inspection_api.py`,
`LocalLLM(timeout=45)`) and Laboratory search's `explain=true` path (`app/laboratory.py`,
`api.py::get_laboratory_service()`) — the user's instructions named only Certification and
Hallmarking for the provider swap, so Laboratory search was deliberately left as-is. The copilot

script-correct answer through end to end; it does **not** prove a live deployed model complies with
the instruction — no live OpenRouter call is made anywhere in the suite, by design (matches every
other test file's "no quota spent" convention).

From the knowledge expansion (`knowledge-expansion.md`):

**Coverage.** Scheme I contributes 421 listed products, Scheme II 75 products across 33 standards
(BIS lists many products against one IS — `IS/IEC 62368 (Part 1)` now carries 43). So **496 of the
769 products** notified under compulsory certification are covered, held as 505 standards. The
remaining ~273 sit in Quality Control Orders outside BIS's two listing pages and were deliberately
not guessed. Laboratory coverage is now **86 of 505** standards with at least one BIS-listed
laboratory (was 78 of 97) — the LIMS snapshot lists labs for a limited set of standards, and the
drop is reported on screen, not hidden.

literal count went 97 → 505. Seven of M14's fifteen named coverage gaps are now closed (toaster,
ceiling fan, pressure cooker, helmet, plywood, gas stove, bicycle); eight remain and are still
reported as gaps.

From Phase 1 (`phase-01.md`):

Not a new subsystem: a repositioning plus two pieces of demo insurance. **No feature was
deleted and the inspection code is untouched** — a later phase re-sources its declared-field
requirements from the standards themselves (IS 14543 clause 7 MARKING is the normative list),
which is why it is reframed rather than cut.

**Deliberately not done:** the optional VERIFIED / CACHED / CHANGED / NOT ESTABLISHED status
vocabulary. The badge it would replace is *retrieval* confidence (how well a query matched a
record); that vocabulary describes *snapshot freshness*, which is what Part B measures. Swapping
one for the other would label every answer with a fact the badge does not know.

From Phase 2 (`phase-02.md`):

**What the baseline actually found, all of it real and none of it fixed here (Phase 2 measures):**

1. **Legal Metrology is unreachable through this engine by design** — `engine.py` indexes only
   records whose `source_authority` is `BIS`, so all 7 Legal Metrology records are loaded but
   never indexed. Their 26 queries therefore expect abstention, and what the block really
   measures is whether a Legal Metrology question gets confidently mis-answered with an unrelated
   BIS standard. **It does: 16 of 26.** "medical devices" → IS 7620 (Part 1), "amendment 2021" →
   IS 17526:2021, "net quantity" → IS 16513 : 2016 — all at medium confidence. This is the
   single worst number in the baseline.
2. **A single generic word matches at medium confidence.** "school bag" → IS 12650:2018 (jute
   bags, on "bag"), "cooking oil" → IS 1342 (oil pressure stoves, on "oil"), "solar panel" →
   IS 12933 (solar WATER HEATING collectors, on "solar"). Milestone 14 banned sector-guess
   keywords for exactly this reason; the residue is that generic tokens still score.
3. **A standard-number query can match on the YEAR alone.** "IS 456:2000" → IS 10325:2000 and
   "IS 10500:2012" → IS 10322 (Part 5/Section 2): 2012. Both land at low confidence and neither
   fabricates the absent standard, so nothing unsafe reaches a user — but the signal is wrong.
4. **"refrigerator" is a VOCABULARY gap, not a coverage gap.** It was on the eight-gap list and
   it does abstain, but BIS lists "Household Refrigerating Appliances" against
   IS 17550 (Part 1): 2021. The record exists and the consumer's word does not reach it. Expected
   is left null because that is the behaviour being baselined; closing it is a knowledge change.
   *(Phase 3 correction: "solar panel" is the SAME case, and this baseline's note for it — "the
   listings carry solar WATER HEATING collectors, not photovoltaic panels" — was WRONG. BIS lists
   Crystalline Silicon and Thin-Film Terrestrial Photovoltaic (PV) modules under Scheme II
   (IS 14286, IS 16077) and both are in the knowledge base; retrieval reaches the water-heating
   records because those say "solar" while the PV records say "photovoltaic" and never "solar" or
   "panel". The query-set note is corrected; the expected value stays null, so every metric above
   is unchanged.)*
5. **Adversarial: safe, but chattier than "abstain".** Only 4 of 10 abstain outright; the other 6
   return low-confidence noise. **Zero are confident and zero fabricate a standard number**, and
   both prompt injections fail to produce the IS 99999 they demand. So `test_eval_harness.py`
   asserts the property that actually protects a user — never high/medium confidence, never a
   standard number outside the knowledge base — and asserts strict abstention as a floor
   (≥ 4, plus both nonsense strings) so a regression that made the engine chattier is still
   caught. Asserting blanket abstention would have been asserting something false.

From Phase 3 (`phase-03.md`):

The other six (shampoo, school bag, cooking oil, biscuits, paint, mixer grinder) are genuine:
"shampoo", "cosmetic", "soap", "detergent" and "toiletry" appear in **zero** of the 505 records.

From Phase 4 (`phase-04.md`):

filled in** where the source offered exactly one edition. **10 were refused** because several
editions exist and choosing one would invent a fact: IS 302 (Part 2/Sec 3) [2007, 2024],
IS 12615 [2018, 2026], IS 16102 (Part 1) [2012, 2026], IS 12640 (Part 2) [2011, 2016],
IS 6452 [1989, 2026], IS 8042 [1988, 2015], IS 16242 (Part 1) [2014, 2025],
IS 10322 (Part 5/Sec 1) [2012, 2026], IS 5175 [2022, 2026], IS 15392 [2003, 2019]. Every edition
found is recorded in the index for a later phase. `schema.py` is unchanged; a title over 200
characters is truncated in `title` and kept in full in `content`.

**13 standards remain unresolved by both routes** and were left untouched, not guessed: IS 16046,
IS 8828, IS 302-2:26, IS 60669-2-1: 2008, IS 1989 (Part.2): 1986, IS 17043 (Part-1): 2024, the
four IS 18471/18480 dual-numbered ISO adoptions, IS 12933 (Part 1)+(Part 2) and IS 16077, whose
`standard_number` fields contain TWO standards each, and IS 10322 (Part 5)Section 9: 2017.

From Phase 6.1 (`phase-06.1.md`):

or one of its standard numbers, else MetrIQ's evidence text replaces the prose. No guard for rule 9 (not
feasible without false positives — see the phase report). `AskPanel` links "Testing laboratories for …" to

From Phase 7 (`phase-07.md`) — Phase 8 built this; the label rule stands:

**NOTE FOR PHASE 8 (not built):** every UI surface that displays clause text must carry a fixed label
that it is OCR text from a scanned document and must be checked against the named PDF page — values like
"1.0 1 to 1.1 1" (litres read as 1), "60 I/h" and "gf/cm?" survive by design, because nothing is corrected.
Also: the evidence-only fallback's fixed sentence (`language.EVIDENCE_ONLY`) calls its records "verified
BIS records"; that stops being true once clause records can appear in it. No path filters on
`verification_status` in a way that would hide clause records from `/ask` or the copilot — the filters
that exist are all also restricted to `indian_standards` / `certification` records.

From Phase 8 (`phase-08.md`) — 8.1's `residual_query` addressed the ranking weakness:

report's standard section prints the text level and scope with the same label. Links open the archive item
with "PDF page N" as text — a page-specific link was NOT verified (no browser was available), so none is
used. Known weakness, not tuned: `rank_within` lets product words outrank the asked-about word
("sampling for packaged drinking water" attaches 3.2 / 5.3 / 5.4, not 9 SAMPLING). Tests:

From Phase 9.1 (`phase-09.1.md`):

`test_certification.py` caught it, the eval set has no such query. Ceiling: a singular "mattress" still
finds nothing (only "mattresses" reaches IS 16014), as before the fix. Affected

From Phase 10 step 0 (`phase-10.md`):

carries a year, the parts agree and the wording is identical. 27 stay unjoined: 6 because the listing
gives no year where the record has one (IS 269 / 455 / 12330 / 1489 (Part 1) / 3854 / 694); 19 because
the product wording differs (11 IS/IEC 62368 products absent from, or spelt differently in, the record's
list — e.g. 32″ vs 32"; IS 16415 trailing "."; IS 12640 (Part 2), IS 302 (Part 2/Sec 3, 201, 202),
IS 16242 (Part 1) "Invertors of rating≤5kVA"); 2 because the record quotes no listed product
(IS 17803, IS 17526 — built from an advisory and a product manual). 439 standards now have a listing order.

From Phase 11 (`phase-11.md`):

only the Phase 10 groups. It composes identity (record + Phase 4 catalogue; ICS code and sectional committee
are NOT held — the catalogue search returns neither — and the page says so), coverage (`product.text_held` +

## Repository layout

```
sih26/
  CLAUDE.md            # this file — project rules
  README.md            # setup & run instructions
  backend/             # Python + FastAPI service
    app/
      main.py          # FastAPI app: /health + the api.py router
      api.py           # /search, /ask, /product-standard, /certification-guidance
      llm.py           # LM Studio / Qwen3-4B local LLM adapter (used by /ask — unchanged)
      openrouter.py    # Milestone 13: the ONLY OpenRouter surface, key stays server-side
      vision.py        # Milestone 15: visual product understanding (separate key/model/budget)
      product_context.py # M21: the canonical product context — composes existing evidence, creates none
      copilot.py       # M13 + M20: grounded context (inspection + feature) + system prompt + guard
      copilot_api.py   # M13 + M20: GET /copilot/status, POST /copilot/explain (read-only)
      evidence_graph.py # M22: projects existing evidence onto nodes/edges — explains, never decides
      graph_api.py     # M22: POST /evidence-graph (read-only; whitelisted client payloads)
      language.py      # Milestone 17: language detection + retrieval aliases (en / hi / te)
      rag.py           # grounded BIS question-answering pipeline (/ask)
      product.py       # Phase 5: Product -> Standard discovery + Phase 9 "Why this result?"
      certification.py # Phase 6: BIS certification guidance (retrieval + grounded LLM answer)
      certification_journey.py # Milestone 16: deterministic product -> standard -> scheme -> next steps
      laboratory.py    # Phase 7 + M18: laboratory search (guidance + verified lab records)
      lab_registry.py  # Milestone 18: verified BIS LIMS laboratory snapshot + deterministic lookup
      ocr.py           # Phase 13: local OCR engine wrapper (rapidocr-onnxruntime)
      inspection.py    # InspectionAnalyzer + response models (ocr / analyze)
      inspection_api.py# POST /inspection/ocr (Instant OCR) + /inspection/analyze; one package = `image` or `images`+`sides`
      declarations.py  # deterministic declarations: DETECTED / UNCERTAIN / NOT_DETECTED, linked to OCR regions
      product_identification.py # product + standard candidates over the KB (retrieval engine + phrase gate)
      requirements.py  # verified products + requirements: load, validate (quotes in verified records),
                       #   product-specific applicability, coverage matrix (knowledge only, no verdict —
                       #   the final hardening pass removed compliance.py/package_label.py, the deterministic
                       #   PASS/FAIL/REVIEW rule engines that used to sit on top of this data)
      completeness.py  # declaration completeness: detection status + verified-requirement coverage, never "missing"
      pipeline.py      # OCR -> declarations -> product identification -> standard candidates -> completeness
      db.py            # Milestone 9: PostgreSQL engine/session (DATABASE_URL)
      records.py       # Milestone 9: saved inspections (immutable evidence; no compliance verdict is stored)
      records_api.py   # Milestone 9: /inspections save, list, stats, detail, stored photos, review
      escalation.py    # Milestone 10: deterministic resolve-or-escalate decision + evidence-linked reasons
      report.py        # Milestone 11: evidence-backed PDF report from the stored record (read-only)
      hallmark.py      # Milestone 12: hallmark / HUID evidence + checks — observed, never authenticated
      report_fonts/    # Noto Sans TTFs (SIL OFL 1.1) used by the PDF report
      knowledge/       # knowledge-base schema + loader
        schema.py      # KnowledgeItem pydantic model + validation rules
        loader.py      # load + validate data/knowledge/, report every problem
      retrieval/       # Phase 3: deterministic lexical search
        text.py        # normalize / tokenize / parse standard numbers
        engine.py      # SearchEngine, scoring, ranking, confidence, abstention
    alembic.ini            # Alembic config (URL from DATABASE_URL)
    migrations/            # Alembic migrations (0001_inspection_records, 0002_escalation,
                           #   0003_drop_compliance_verdicts)
    scripts/
      check_knowledge.py   # CLI: validate the knowledge base
      fetch_lims_laboratories.py # M18: one-off BIS LIMS ingestion -> data/laboratories.json
    tests/                 # plain-Python runners: `./.venv/bin/python tests/<file>`
      test_knowledge.py    # KB schema + loader (broken-KB fixtures)
      test_retrieval.py    # retrieval ranking / abstention + /search API
      test_product.py      # Product -> Standard
      test_why_this_result.py # deterministic why-this-result
      test_certification.py # certification guidance
      test_laboratory.py   # laboratory search (Phase 7)
      test_laboratory_intelligence.py # M18: lab snapshot, standard->lab, why, no fabrication
      test_hallmarking.py  # hallmarking / HUID (via /ask)
      test_rag.py          # grounded RAG pipeline + /ask (fake LLM, 503 path)
      test_multilingual.py # Milestone 17: detection, aliases, same evidence in every language
      test_api_contract.py # real ASGI app via TestClient: shapes, 422, 404, 503
      test_llm_adapter.py  # app/llm.py: healthy parse + clean LLMError on every failure
      test_inspection_ocr.py # Phase 13: real OCR engine on synthesised labels + HTTP contract
      test_instant_ocr.py  # Instant OCR: /inspection/ocr evidence, stubbed engine failures, validation
      test_declarations.py # declaration extraction on controlled OCR fixtures (+ real-label regressions)
      test_product_identification.py # product/standard candidates, REVIEW paths, model stubbed
      test_multiside.py    # multi-side packages: per-image provenance, duplicates/conflicts, failed sides
      test_why_completeness.py # declaration completeness, never "legally missing" (no compliance verdict)
      test_coverage.py     # Milestone 7: product applicability, coverage matrix, junk-name rejection, real labels
      test_hardening.py    # Milestone 7 hardening: coverage classes, domains, IS/email normalization, brand != product
      test_inspection_records.py # Milestone 9/10: migrations, persistence, resolution states, stats (PostgreSQL)
      test_escalation.py   # Milestone 10: every escalation reason, resolve-or-escalate decision, determinism
      test_report.py       # Milestone 11: PDF report content, honesty, escaping, read-only endpoint (PostgreSQL)
      test_hallmark_inspection.py # Milestone 12: HUID / purity extraction, untrusted text, escalation, report
      test_hallmark_enhancement.py # M19: components, vision fusion, user HUID, no authentication state
      test_copilot.py      # Milestone 13: provider, grounding, injection defence, withheld answers, independence
      test_copilot_context.py # M20: feature contexts, evidence vocabulary, lab/hallmark/cert safety, language
      test_product_context.py # M21: cross-feature composition, applicability, provenance, trust boundary
      test_evidence_graph.py # M22: graph projection, chain, provenance, safety, whitelist, UI shape
      test_no_review_workflow.py # M22: the human review workflow is gone (superseded by the final
                                 #   hardening pass, which also removed the PASS/FAIL/REVIEW it once
                                 #   asserted survived — see "Final Hardening Pass" below)
      test_standards_coverage.py # Milestone 14: standard provenance, product→standard retrieval, no invented rules
      test_vision_fusion.py # Milestone 15: vision adapter, scrubbing, OCR/vision fusion, graceful failure
      test_pipeline.py     # OCR -> standard candidates end-to-end + stage degradation
      test_plain_runners.py # pytest bridge — runs every runner, makes pytest authoritative
      fixtures/broken_kb/  # deliberately invalid KB for the loader tests
    requirements.txt
    .env.example
  docs/history/        # detailed milestone / phase history, moved verbatim from this file
  data/
    knowledge/         # the knowledge base: one JSON file per category (BIS; legal_metrology.json = Legal Metrology)
    inspection_requirements.json # inspection products + requirements, each quoting a verified knowledge record
  samples/
    ocr-labels/        # sample package images for testing /inspection/analyze
  frontend/            # React + Vite app
```

### Knowledge base

`data/knowledge/` holds one JSON array file per category. `KnowledgeItem`
(`backend/app/knowledge/schema.py`) is a flat structure that maps 1:1 to a future
PostgreSQL row. Rules: unique slug IDs, non-sample items need a `source_url`,
`indian_standards` items need a `standard_number` (unique within that category),
`verified` items need `source_url` + `last_verified`. Validate with
`./.venv/bin/python scripts/check_knowledge.py`.

Phase 2B populated it from official BIS pages only (`bis.gov.in`,
`services.bis.gov.in`). Indian Standards records come mostly from the BIS "Products
under Compulsory Certification" lists (Scheme I / Scheme II), so they carry BIS's
own product description, not the verbatim catalogue title — each record's `content`
states this. Do not treat the dataset as complete BIS coverage.

### Retrieval (Phase 3)

`app/retrieval/engine.py` — `SearchEngine.search(query)` returns a `SearchOutcome`
with ranked `RetrievalResult`s. Scoring is a transparent weighted sum over
`title` / `keywords` / `standard_number` / `category` / `document_name` /
`reference` / `content`; every point is recorded as a `MatchReason` (for the future
"Why this result?"). Confidence (`high` / `medium` / `low` / `none`) comes from the
top hit's score plus query-term coverage; all weights and thresholds live in
`RetrievalConfig`. `abstained` is true (and `results` empty) when nothing matches.
The LLM must never generate the match reasons — retrieval produces them.


