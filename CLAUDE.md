# SIH26107 — Evidence-Backed AI Assistant for Indian Standards & BIS Services

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
| 14 | OCR -> declarations -> product -> Indian Standard (this phase) |

*Phase 14 — OCR -> declaration extraction -> product classification -> verified
Indian Standard lookup. `POST /inspection/analyze` now runs the downstream
pipeline after OCR and returns `declaration_stage`, `classification`,
`standard_match` and a `pipeline` stage summary (the old `product` /
`declarations` / `checks` / `status` / `pipeline_stage` fields are gone). New
backend modules, each a single surface: `app/declarations.py` (deterministic
regex/keyword extraction of 14 declaration fields — every `Declaration` keeps its
`source_region_id` + `bbox` + `ocr_confidence` + `method`; FSSAI licence is
extracted but explicitly labelled food-safety, NOT a BIS standard),
`app/classification.py` (deterministic product rules first, local Qwen3-4B strict
-JSON fallback only when rules miss, `REVIEW` if the model is unavailable and no
rule matched — the model classifies, it never emits a standard number: any
standard-ish key or reason fragment is stripped), `app/standards_registry.py`
(loads `data/standards_registry.json` — hand-verified BIS standards only; keyword
-phrase overlap lookup returns the strongest verified match or `REVIEW`, never a
generated IS number; a single generic word cannot match), `app/pipeline.py`
(`run_downstream` — orchestrates the three stages, each isolated so one failure
degrades that stage to `REVIEW` and the rest still run). `app/inspection.py`
wires the pipeline in and converts the dataclasses to `*Out` models;
`app/inspection_api.py` injects `LocalLLM(timeout=45)`. `app/llm.py` now also
reads `LM_STUDIO_BASE_URL` / `LM_STUDIO_MODEL` (with `LLM_*` as fallback).
Registry seed: **IS 18140:2023 — Roasted Bengal Gram — Specification** (verified,
BIS committee FAD 16), IS 14543:2016 / IS 13428:2005 (packaged water). The
`data/knowledge/` BIS Q&A set is untouched and unrelated (it has no food
standards). Frontend: `InspectionView` keeps its exact design and adds a
"Declared fields" panel (click a field -> its OCR box highlights on the image),
an "Applicable Indian Standard" panel (number / title / source link / real
confidence / why-this-match, or a `REVIEW` state), and swaps the `PENDING`
literals in the downstream panel + the left summary for the real stage states.
Legal-metrology PASS/FAIL is still `NEXT`. Tests: `test_declarations.py` (31),
`test_standards_registry.py` (25), `test_classification.py` (21 — stubbed model),
`test_pipeline.py` (30 — end-to-end + degradation + HTTP contract);
`test_inspection_ocr.py` updated for the new response shape. Full suite 108
passed.*

*Phase 13 recap — real image -> OCR. `POST /inspection/analyze` (multipart, field
`image`) decodes the uploaded package image, computes lightweight quality
metrics (blur / brightness / contrast, numpy only), runs local OCR, and returns
the raw OCR regions (`text`, `confidence`, axis-aligned `bbox` + `polygon` in
source pixels, `OCR-NNN` id) plus the joined text. New backend modules:
`app/ocr.py` (engine wrapper — one surface, `run_ocr`), `app/inspection.py`
(models + `InspectionAnalyzer`), `app/inspection_api.py` (router, wired in
`app/main.py`). OCR engine: `rapidocr-onnxruntime` — the PaddleOCR PP-OCRv3
detection/cls/recognition weights run through ONNX Runtime, because PaddlePaddle
publishes no wheels for this Python; models ship in the wheel so OCR is fully
local with no network at inference. NOTHING downstream is done here — the
response's `product` / `declarations` / `checks` / `status` are explicitly
`"Pending extraction"` / `[]` / `"PENDING"`, never invented. The LLM (Qwen3-4B)
is untouched and is not involved in OCR. Frontend: `InspectionView` now runs the
real flow (upload -> `/inspection/analyze` -> OCR workspace with the image, the
overlaid boxes, per-region text/confidence, raw text, quality metrics); an empty
or failed OCR shows an honest empty / error state and never substitutes the old
demo inspection. `mocks.tsx` is unchanged and still backs History / Review /
Dashboard. Tests: `backend/tests/test_inspection_ocr.py` (41 checks — real
engine on synthesised labels, blank image -> zero regions, non-image -> error,
HTTP contract). `backend/tests/test_llm_adapter.py` regression test unchanged.
The deterministic rule engine, declaration extraction and PASS/FAIL remain
future phases.*

*Phase 12 recap: demo hardening. Full clean-shell startup,
frontend<->backend integration and the deterministic demo path
(Product -> Standard -> Why this result -> evidence, LLM-free) were verified
end to end; no white screens, console errors or contract mismatches. One small
fix: `app/llm.py` now raises a short user-facing `LLMError` on an LM Studio HTTP
error / timeout ("LM Studio returned HTTP 400", "could not reach LM Studio
(ReadTimeout)") instead of stringifying the raw httpx exception, which had been
leaking an internal URL and an MDN link into the error callout. Behaviour is
unchanged — still a 503, still no fabricated answer. Regression test:
`backend/tests/test_llm_adapter.py` (15 checks, stubbed `httpx.post`). README
gained a "Demoing" note (lead with the LLM-free Product -> Standard path) and
the authoritative-test command.
Phase 11 recap: testing. No application code changed.
Added `backend/tests/test_rag.py` (dedicated grounded-RAG / `/ask` coverage:
evidence reaches the LLM, abstention makes no LLM call, sources preserved,
`/ask` returns 503 on an LLM outage, no invented standard numbers, system-prompt
trust rules), `backend/tests/test_api_contract.py` (drives the real ASGI app via
`TestClient`: every endpoint's shape + status codes, `limit` bounds -> 422,
malformed body -> 422, an adversarial product sweep proving every returned
`standard_number` exists in the KB), and `backend/tests/test_plain_runners.py`
(a pytest bridge that runs every plain-Python runner as a subprocess and fails
if any exits non-zero — so `python -m pytest -q` is now an authoritative gate,
not just the direct runners). Fake / raising local-model stand-ins keep every
LLM test deterministic and independent of LM Studio.
Phase 10 recap: targeted frontend polish only (no visual-identity change) —
`standardTitle()` helper, "Why this result" hierarchy, calmer timeout/model
error copy.
Phase 9 recap: deterministic "Why this result?" for
Product -> Standard discovery. Phase 9 adds NO new endpoint, NO new retrieval
engine and NO LLM call. The Phase 3 `SearchEngine` already records every scoring
point as a `MatchReason`; `app/product.py` gains a pure function
`explain_candidate(RetrievalResult) -> WhyThisResult` that turns those existing
reasons into a fixed-order list of `signals` plus one plain-language `summary`
("Retrieved as a candidate standard (strong/moderate/weak match) because …").
`strength` mirrors retrieval confidence; the wording never claims legal
applicability. `ProductStandardOutcome` gains a parallel `explanations` list
(empty on abstention) and a standing grounded `note`; `POST /product-standard`
exposes it as `why` on each result (alongside the untouched raw `reasons`).
Frontend: `StandardsView.tsx` shows `result.why.summary` as the lead of the
"Why this result" block, keeping the detailed reason breakdown beneath. Tests:
`backend/tests/test_why_this_result.py` (41 checks).
Phase 8 recap: Hallmarking / HUID information. Phase 8 added
NO new retrieval engine and NO new endpoint: hallmarking / HUID questions go
through the existing deterministic `SearchEngine` + grounded `/ask` pipeline
(`app/rag.py`). The curated KB's `hallmarking` category (plus hallmarking FAQs
and consumer pages) supplies the evidence; it contains no concrete HUID value to
leak. `rag.py`'s shared `SYSTEM_PROMPT` gained rule 6: never claim to verify /
authenticate a specific physical item's HUID, hallmark, licence or registration,
and never output a HUID not present in the supplied context. Frontend:
`frontend/src/features/HallmarkingView.tsx` (route `/hallmarking`, nav
"Hallmarking") calls `api.ask` and renders via the shared `<GroundedAnswer/>`;
it states plainly it does not run live HUID verification. Tests:
`backend/tests/test_hallmarking.py` (37 checks). No individual-lab / no
fabrication rules carry over from Phase 7.
Phase 7 recap: BIS-recognized laboratory search (`app/laboratory.py`,
`POST /laboratory-search`) — runs the Phase 3 `SearchEngine` over
`laboratories` / `testing`, never names a laboratory (KB has no lab records),
points to BIS's official lists + the LIMS portal, abstains with a fixed message
when no evidence is retrieved.
Phase 6 recap: certification guidance (`app/certification.py`,
`POST /certification-guidance`). Phase 5 recap: Product -> Standard discovery
(`app/product.py`, `POST /product-standard`).

Frontend (MetrIQ): `frontend/` — React + TS + Vite + Tailwind v4. The product
is presented as "MetrIQ — AI-Assisted Legal Metrology Inspection". Standards,
Certification, Laboratories, Hallmarking and the header health dot call the real
API. The Inspection tab is real end to end through Phase 14: upload ->
`/inspection/analyze` -> OCR + declarations + product identification + verified
Indian Standard candidates from `data/knowledge/` (the Phase 14 classification rules
and separate standards registry were retired; IS 18140:2023 and IS 367:1993 moved
into the knowledge base). History / Review / Dashboard still run on clearly labelled
placeholder data (`frontend/src/mocks.tsx`) — the legal-metrology PASS/FAIL rule
engine and the officer report are not built yet. Run: backend on :8000, then
`cd frontend && npm install && npm run dev` (proxies `/api` -> :8000).

Phases 1–14 and inspection Milestones 1–5 (Instant OCR, declarations, product
identification, deterministic compliance, multi-side packages) are complete. A package
can be photographed from several sides: every image is OCR'd on its own, region ids
are unique per inspection (`I2-OCR-004`) and carry `image_id` + `side`, declarations
merge across photos (DUPLICATE keeps every source, CONFLICT withholds the value), and a
failed side is reported, never treated as absent. Milestone 6: every compliance check
explains itself deterministically (rule_condition, reason_code, reason_category, package
evidence and BIS requirement evidence), the evaluation has a counts-based `summary`, and
`completeness` reports each declaration as DETECTED / UNCERTAIN / NOT_DETECTED plus whether
a verified requirement covers it (`VERIFIED_REQUIREMENT` / `NOT_ESTABLISHED`). "Not
detected" is never reported as legally missing. Compliance coverage is data:
only standards with verified requirements in `data/inspection_requirements.json` are
`INSPECTION_SUPPORTED` (currently IS 14543:2016 and IS 13428:2005); every other
standard is `STANDARD_ONLY` and returns REVIEW. Milestone 7 (knowledge + rule coverage
foundation): coverage is PRODUCT -> STANDARD -> REQUIREMENT -> RULE -> EVIDENCE.
`data/inspection_requirements.json` gains a `products` list (each product -> standard link
quotes a verified record; aliases must be phrases of that standard's KB title/keywords) and
requirements may set `applies_to_products`. Compliance confirms the modelled product from the
phrases product identification already matched (`PRODUCT_CONFIRMED` / `PRODUCT_NOT_MODELLED` /
`PRODUCT_NOT_CONFIRMED` / `PRODUCT_AMBIGUOUS`), applies only that product's requirements, and
`compliance.coverage` carries requirement / rule counts plus a deterministic `explanation`.
`GET /inspection/coverage` and `scripts/check_knowledge.py` print the coverage matrix. The
knowledge base still supports exactly ONE checkable rule (printed IS number, packaged water);
LED lamps have one verified but uncheckable requirement (CRS registration); every other
standard has no requirement data. Declaration extraction rejects QR / barcode / website /
placeholder text as names (UNCERTAIN, value withheld, OCR evidence kept). The frontend adds
an "Inspection coverage" panel and "Declaration observations" wording. Milestone 7 hardening:
coverage classes are `INSPECTION_SUPPORTED` (renamed from SUPPORTED_FOR_INSPECTION) /
`STANDARD_ONLY` / `UNSUPPORTED`, each standard with a data-derived reason and its KB-stated
certification route (reported, never a rule) — currently 2 / 30 / 4 of 36. Requirements carry a
`domain` (`PACKAGE_LABEL` | `JEWELLERY_HALLMARKING` | `GENERAL_BIS_INFORMATION`); package
inspection applies only PACKAGE_LABEL, and the loader rejects package-label requirements or
product links that use hallmarking records, hallmarking standards or hallmark/HUID quotes;
a hallmarking standard in package inspection is `UNSUPPORTED`. Extraction normalizes corrupted
OCR without guessing (`extraction_method: deterministic_normalization`, `raw_text` keeps the
original): non-canonical IS references ("ISTIS 14543", "IS No. 14543") are recovered only when
the number is a verified KB standard, otherwise UNCERTAIN with no value; a normalized IS number
may PASS but never FAIL (REVIEW, `EVIDENCE_NORMALIZED`). Emails with one OCR-inserted space are
repaired only with a contact cue. The most prominent line is only the product name when it
contains KB product vocabulary or the label says "Product name:"; a brand-like line is never the
product name. The remaining work is verified requirement data and the officer review / report
surface.

Milestone 8 (verified Legal Metrology package-label requirements): the knowledge base gains a
`legal_metrology` category (`data/knowledge/legal_metrology.json`) whose items have
`source_authority: LEGAL_METROLOGY` (every other item is `BIS`; the schema enforces the pairing).
Records quote the Legal Metrology (Packaged Commodities) Rules, 2011 and its 2012 / 2015 / 2017 /
2021 / 2022 / 2025 amendments from official Department of Consumer Affairs PDFs
(`consumeraffairs.gov.in`); every quote was checked against the PDFs (text layer, or OCR + page image
for scanned Gazettes). BIS search indexes BIS items only. `inspection_requirements.json` gains
`package_scope` (Rule 3: observable exclusions — net quantity > 25 kg / 25 L, "not for retail sale" —
and stated assumptions a label cannot show) and `scope: PACKAGED_COMMODITY` requirements (domain
PACKAGE_LABEL, `reference` such as "Rule 6(1)(e)", `supporting_sources`, per-requirement `exclusions`
such as food articles via an FSSAI licence for Rules 6(1)(a) / 6(1)(d)). The loader rejects a
packaged-commodity requirement quoting BIS evidence, a BIS requirement quoting Legal Metrology
evidence, unimplemented formats / exclusions and hallmarking evidence. `app/package_label.py`
evaluates them as a separate result (`package_label` in `/inspection/analyze`, `pipeline.package_label`)
— never merged with BIS compliance. Generic rules in `app/compliance.py`: `field_present`
(PASS or REVIEW, never FAIL), `value_format` (MRP inclusive of all taxes in Indian currency — PASS or
REVIEW, a foreign-currency MRP is REVIEW because Rule 6(9) allows an affixed label; net quantity in SI
units — FAIL only for a dozen, Rule 13(4)), `date_format` (month and year, PASS or REVIEW; a packing date
alone is REVIEW). 11 Legal Metrology requirements, 6 checkable; overall PASS only when every applicable
requirement was checked, so with uncheckable areas the overall is REVIEW. Declaration extraction no
longer reads "Rs. 8O" as ₹8 (UNCERTAIN, value withheld). Coverage report / `GET /inspection/coverage`
separate BIS standards (36 = 2 / 30 / 4) from Legal Metrology requirements (11, 6 checkable); total
deterministic rules 7. Frontend: "Package label requirements" panel (requirement / rule / observed /
result, evidence + quoted Legal Metrology source), authority-aware source labels. Tests:
`test_legal_metrology.py` (129 checks).

Only implement the current milestone. Do not start a new phase without being asked.

## Repository layout

```
sih26/
  CLAUDE.md            # this file — project rules
  README.md            # setup & run instructions
  backend/             # Python + FastAPI service
    app/
      main.py          # FastAPI app: /health + the api.py router
      api.py           # /search, /ask, /product-standard, /certification-guidance
      llm.py           # LM Studio / Qwen3-4B local LLM adapter
      rag.py           # grounded BIS question-answering pipeline (/ask)
      product.py       # Phase 5: Product -> Standard discovery + Phase 9 "Why this result?"
      certification.py # Phase 6: BIS certification guidance
      laboratory.py    # Phase 7: BIS-recognized laboratory search
      ocr.py           # Phase 13: local OCR engine wrapper (rapidocr-onnxruntime)
      inspection.py    # InspectionAnalyzer + response models (ocr / analyze)
      inspection_api.py# POST /inspection/ocr (Instant OCR) + /inspection/analyze; one package = `image` or `images`+`sides`
      declarations.py  # deterministic declarations: DETECTED / UNCERTAIN / NOT_DETECTED, linked to OCR regions
      product_identification.py # product + standard candidates over the KB (retrieval engine + phrase gate)
      requirements.py  # verified products + requirements: load, validate (quotes in verified records),
                       #   product-specific applicability, coverage matrix
      compliance.py    # deterministic compliance engine: PASS / FAIL / REVIEW / NOT_SUPPORTED, no model;
                       #   every check carries rule_condition + reason_code/category + both evidence chains
      package_label.py # Milestone 8: Legal Metrology package-label evaluation (scope, exclusions, separate result)
      completeness.py  # declaration completeness: detection status + verified-requirement coverage, never "missing"
      pipeline.py      # OCR -> declarations -> product identification -> standard candidates -> compliance
      knowledge/       # knowledge-base schema + loader
        schema.py      # KnowledgeItem pydantic model + validation rules
        loader.py      # load + validate data/knowledge/, report every problem
      retrieval/       # Phase 3: deterministic lexical search
        text.py        # normalize / tokenize / parse standard numbers
        engine.py      # SearchEngine, scoring, ranking, confidence, abstention
    scripts/
      check_knowledge.py   # CLI: validate the knowledge base
    tests/                 # plain-Python runners: `./.venv/bin/python tests/<file>`
      test_knowledge.py    # KB schema + loader (broken-KB fixtures)
      test_retrieval.py    # retrieval ranking / abstention + /search API
      test_product.py      # Product -> Standard
      test_why_this_result.py # deterministic why-this-result
      test_certification.py # certification guidance
      test_laboratory.py   # laboratory search
      test_hallmarking.py  # hallmarking / HUID (via /ask)
      test_rag.py          # grounded RAG pipeline + /ask (fake LLM, 503 path)
      test_api_contract.py # real ASGI app via TestClient: shapes, 422, 404, 503
      test_llm_adapter.py  # app/llm.py: healthy parse + clean LLMError on every failure
      test_inspection_ocr.py # Phase 13: real OCR engine on synthesised labels + HTTP contract
      test_instant_ocr.py  # Instant OCR: /inspection/ocr evidence, stubbed engine failures, validation
      test_declarations.py # declaration extraction on controlled OCR fixtures (+ real-label regressions)
      test_product_identification.py # product/standard candidates, REVIEW paths, model stubbed
      test_compliance.py   # compliance rules, aggregation policy, grounding, traceability
      test_multiside.py    # multi-side packages: per-image provenance, duplicates/conflicts, failed sides
      test_why_completeness.py # why PASS/FAIL/REVIEW + declaration completeness, never "legally missing"
      test_coverage.py     # Milestone 7: product applicability, coverage matrix, junk-name rejection, real labels
      test_hardening.py    # Milestone 7 hardening: coverage classes, domains, IS/email normalization, brand != product
      test_legal_metrology.py # Milestone 8: Legal Metrology sources, rules, applicability, BIS separation, UI contract
      test_pipeline.py     # OCR -> standard candidates end-to-end + stage degradation
      test_plain_runners.py # pytest bridge — runs every runner, makes pytest authoritative
      fixtures/broken_kb/  # deliberately invalid KB for the loader tests
    requirements.txt
    .env.example
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
