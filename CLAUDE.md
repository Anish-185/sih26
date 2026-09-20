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

Milestone 9 (officer review + inspection history): saved inspections live in PostgreSQL
(`DATABASE_URL`, default `postgresql+psycopg:///metriq`) through SQLAlchemy (`app/db.py`,
`app/records.py`) with an Alembic migration (`backend/migrations`, `alembic upgrade head`).
Tables: `inspections` (system result: `bis_result`, `legal_metrology_result`, combined
`system_result` — FAIL if either FAILs, PASS only if both PASS, else REVIEW — `system_reasons`,
product fields, `sides`, full `analysis` JSONB; officer review: `officer_status`
PENDING → IN_REVIEW → COMPLETED, `officer_decision` ACCEPT_SYSTEM_RESULT / OVERRIDE / MANUAL_REVIEW,
`officer_result` (OVERRIDE only, must differ from the system result), `officer_note`,
`review_started_at`, `review_completed_at`) and `inspection_images` (photo bytes per upload
position). Check constraints tie decision/status/timestamps together; triggers reject any update
of the system columns or stored photos. `app/records_api.py`: `POST /inspections` (multipart
photos only — the backend re-runs the analysis itself; any other form field → 422),
`GET /inspections` (`?officer_status=`), `GET /inspections/stats`, `GET /inspections/{id}`,
`GET /inspections/{id}/images/{index}`, `POST /inspections/{id}/review` (strict body: START, or
COMPLETE with decision / officer_result / note; unknown field → 422, wrong state or duplicate → 409,
unknown id → 404, malformed id → 422, database down → 503). OVERRIDE and MANUAL_REVIEW need a note.
Legal Metrology / BIS aggregation is unchanged: REVIEW stays REVIEW and the UI explains it.
Frontend: Inspection gains "Save for officer review"; `/review` (ReviewQueueView: PENDING +
IN_REVIEW), `/history` (real records), `/history/:id` (ReviewView: fixed system result panel,
officer review panel, and the exported inspection `Workspace` over the stored photos and saved
analysis), Dashboard counts from `/inspections/stats` with system results and officer states
separate. `frontend/src/mocks.tsx` is gone — no placeholder data remains. Tests:
`test_inspection_records.py` (61 checks; needs the `metriq_test` database, refuses any database not
named `*_test`). Full suite 169 passed.

Milestone 10 (final officer escalation): `app/escalation.py` `assess(analysis_json)` decides
deterministically whether the system can resolve an inspection or it goes to an officer, from the
finished analysis only (no model, changes no result). Reasons, each with `code` / `label` / `source`
(OCR, PRODUCT, BIS, LEGAL_METROLOGY, PIPELINE) / `message` / `source_regions` / `checks`:
PIPELINE_ERROR, IMAGES_UNREADABLE, IMAGE_QUALITY_LOW, PRODUCT_NOT_IDENTIFIED, MULTIPLE_CANDIDATES,
PRODUCT_NOT_CONFIRMED, NO_VERIFIED_STANDARD, HALLMARK_NOT_VERIFIABLE (HUID / hallmark text or a
hallmarking standard — never verified), CONFLICTING_DECLARATIONS, OCR_UNCERTAIN, MISSING_EVIDENCE,
REQUIREMENT_NOT_CHECKABLE, PACKAGE_SCOPE_EXCLUSION, SYSTEM_RESULT_REVIEW. REQUIREMENT_NOT_CHECKABLE does
not block a FAIL (it cannot overturn clear evidence); every other reason escalates. An assessment error
escalates. `InspectionAnalysisOut.escalation` carries it (`/inspection/analyze`). Saved inspections:
migration `0002_escalation` adds `escalation_required` + `escalation_reasons` (protected by the
immutability trigger) and the officer status `NOT_REQUIRED` (resolved by the system — final, never
queued, cannot be reviewed: 409; the trigger refuses moving it into the queue); unresolved inspections
start PENDING. Existing rows are backfilled with the same `assess`. `final_result` of a NOT_REQUIRED
inspection is its system result; stats gain `escalated` and `officer.NOT_REQUIRED`. Frontend:
`EscalationPanel` (records.tsx) — the path system result → can the system resolve it? → final system
result | officer queue → decision → final record, with clickable evidence-linked reasons — in the live
workspace and the saved inspection; save button "Save final result" / "Save and send to officer
review"; queue "Why escalated" column; History "Escalation" column; Dashboard "Resolved by system".
With the current verified data every real inspection escalates (no standard has every requirement
checkable). Tests: `test_escalation.py` (27), `test_inspection_records.py` (77, incl. 0002 backfill).

Milestone 11 (evidence-backed inspection reports): `app/report.py` renders a PDF (ReportLab platypus,
new dependency `reportlab`) from the persisted record only — `build_story(record_json, images, generated_at)`
returns the flowables, `render_report` builds the PDF with "page X / Y" chrome. No DB writes, no
recomputation, no model. Fonts: Noto Sans Regular/Medium/Bold + Noto Sans Mono in `app/report_fonts/`
(SIL OFL 1.1, `OFL.txt`) — they cover the rupee sign. Sections: header (ID, saved / generated in IST,
status) · 02 summary (product or "Not identified", brand, manufacturer/packer/importer, category or "Not
established", sides, SYSTEM RESULT and OFFICER FINAL DECISION boxes side by side) · 03 stored photos with
OCR boxes drawn on an in-memory copy (only sides that exist) · 04 OCR evidence (field | value | confidence |
side + region + raw text, region table capped at 60) · 05 declarations with stored statuses (NOT_DETECTED is
not "legally missing") · 06 BIS standard evidence (identified / candidate, why this result, source) or
"No verified BIS standard was identified by the automated retrieval process." · 07 Legal Metrology
requirements (checkable vs not checkable from an image, status, source + URL per requirement) · 08
compliance table (NOT_SUPPORTED shown as UNSUPPORTED, never PASS) · 09 automated system result with
escalation reasons, uncertain / conflicting declarations, unsupported checks · 10 officer review (never an
officer identity) · 11 final outcome (system result and officer decision both shown) · 12 only the sources
stored with the evidence. All stored text is XML-escaped. Endpoint `GET /inspections/{id}/report.pdf`
(422 malformed id, 404 unknown, 503 database down; session rolled back, never committed). Frontend:
"View report" (ReviewView header) — `LinkButton external` to the PDF URL. Tests: `test_report.py` (36:
PASS / FAIL / REVIEW, officer states, honesty, multi-side, escaping, stored-only URLs, endpoint read-only
with no LLM / recompute calls).

Milestone 12 (hallmark / HUID workflow): `app/hallmark.py` `evaluate_hallmark(regions, knowledge_items,
force)` — deterministic, never authenticates. Extracts a potential HUID (labelled six-character alphanumeric
code; low confidence / wrong length / unlabelled → UNCERTAIN, several → MULTIPLE, none selected; prose after
the word HUID such as "HUID VERIFIED" is never a value), purity (gold `22K916`-style pairs checked against the
verified IS 1417 grades, caratage-fineness mismatch or two marks → CONFLICT; silver only with silver context,
IS 2112 grades), "BIS" text, hallmark wording, and untrusted claims (verified / authentic / genuine / confirmed
… printed text — recorded, changes nothing). Every observation keeps region / image / side / bbox /
confidence / method. Checks quote verified records word for word: HALLMARK_HUID_OBSERVED (PASS = observed, not
verified), HALLMARK_PURITY_GRADE, HALLMARK_BIS_LOGO (NOT_SUPPORTED, graphic), HUID_AUTHENTICITY (NOT_SUPPORTED,
external authoritative verification required). No FAIL; `verification_status` NOT_VERIFIED / NOT_DETECTED
only; hallmark `overall_status` always REVIEW. Knowledge: `gold-purity-grades-for-hallmarking` and
`what-is-huid` now quote the BIS Hallmarking FAQ verbatim (re-verified 2026-09-17, the FAQ prints "24KS(995)"),
new verified `silver-purity-grades-for-hallmarking`. `InspectionAnalysisOut` gains `inspection_type`
(PACKAGE | HALLMARK, form field on `/inspection/analyze` and `POST /inspections`) and `hallmark`; a HALLMARK
inspection reports Legal Metrology as `scope_status` NOT_APPLIED (reason_code NOT_A_PACKAGE_INSPECTION).
`app.escalation.system_result` combines every applicable evidence system (BIS, Legal Metrology unless not
applied, hallmarking when detected or a hallmark inspection); `system_reasons` gains HALLMARKING. Escalation
uses the structured evidence ("Potential HUID X detected, but authenticity cannot be established from the
uploaded image"), untrusted claims add a reason, a hallmarking standard still escalates. No DB migration.
Report: numbered sections, "Hallmarking evidence" (observed vs verification, checks, untrusted claims), Legal
Metrology "not applied", BIS Hallmarking sources. Frontend: `HallmarkEvidence.tsx` panel (OBSERVED FROM THE
IMAGE | VERIFICATION STATUS) in the workspace; Hallmarking page gains "Inspect a hallmark photo" (analyse, save
to officer review, HUID reference field = text comparison only). Sample `synth_hallmark-closeup.png`. Tests:
`test_hallmark_inspection.py` (58).

Milestone 13 (grounded copilot via OpenRouter): an OPTIONAL explanation layer over a finished
inspection. It explains the record; it never produces it. `app/openrouter.py` is the only module that
talks to OpenRouter (`OpenRouterLLM`, same `generate(system_prompt=, user_prompt=)` surface as
`app/llm.py`'s `LocalLLM`, which is untouched and still serves `/ask`): env `OPENROUTER_API_KEY` /
`OPENROUTER_MODEL` (default `deepseek/deepseek-v4-flash-0731:free`, verified against OpenRouter's model
list and end to end; the model is configuration — no caller hardcodes it, so any OpenRouter chat model
works) /
`OPENROUTER_BASE_URL` / `OPENROUTER_TIMEOUT` / `OPENROUTER_DAILY_LIMIT` (45) / `OPENROUTER_MINUTE_LIMIT`
(15), read from a gitignored `backend/.env` by `load_env_file()` (an exported variable always wins);
the key is server-side only — never in the frontend, never in a response, never in an error. Failures
become `CopilotUnavailable` with a stable code (NOT_CONFIGURED / DAILY_LIMIT / RATE_LIMITED / TIMEOUT /
PROVIDER_ERROR / BAD_RESPONSE) and a short user-facing sentence; no automatic retry; `UsageLimiter`
refuses a request locally before it reaches the network, and refunds the daily slot when the provider
never served it. The payload sends `reasoning: {"enabled": false}` (OpenRouter normalises it per model
and ignores it where reasoning does not apply) — without it a reasoning model spends the whole budget
thinking about the long grounded prompt and returns empty content. `app/copilot.py`: `build_context` turns the finished analysis (live or persisted) into
a compact grounded context — only the sections the question needs, a `SourceBook` so each verified quote
is sent once, NOT_DETECTED declarations and unsupported checks reduced to one line (~23k characters,
about 6k tokens); OCR / package text goes last, inside `<<<UNTRUSTED_PACKAGE_TEXT>>>` markers, with
markers and role prefixes inside it neutralised. `SYSTEM_PROMPT` states the source-of-truth hierarchy,
forbids inventing a standard / HUID / requirement / URL, forbids changing PASS/FAIL/REVIEW, forbids
authenticating an item, and requires "Insufficient evidence in the inspection record." over a guess.
The model is not trusted to have obeyed: `guard()` re-reads the generated text deterministically and
WITHHOLDS it (replacing it with MetrIQ's own sentence) when it cites an IS number, HUID or URL that is
not in the context, claims an authentication, or states an overall verdict other than the deterministic
one — a check-level PASS inside a REVIEW case is not a contradiction. `system_result` in the response is
always read from the record. `parse_response` also salvages a reply cut short by the token limit — the
complete `answer` and evidence entries are recovered and the officer is told it was cut short, so raw
JSON is never shown. `app/copilot_api.py`: `GET /copilot/status` (configured flag, model,
remaining free budget, capabilities — no key) and `POST /copilot/explain` (strict body: exactly one of
`inspection_id` or `analysis`, one of nine capabilities, optional question/rule_id; 422 on anything else,
404 unknown id, 429 on a free-tier limit, 503 otherwise). Read-only: the session is rolled back and never
committed, nothing is recomputed, and the copilot imports no pipeline module. Frontend:
`features/CopilotPanel.tsx` — a panel, not a chat: prompt chips, one text field, the answer with its
evidence, limitations and the sources stored with the evidence, the deterministic result shown beside it,
and the free budget in the footer; in the inspection workspace and on the officer review page
(`hideCopilot` keeps it in one place there). One request per user action; nothing is ever called
automatically. Tests: `test_copilot.py` (204 checks, every provider call stubbed — no tokens spent) plus
copilot read-only checks in `test_inspection_records.py`. With no key configured, or with OpenRouter down,
every result, check, source, escalation, officer decision and PDF report is unchanged.


Milestone 14 (verified BIS knowledge + product → standard coverage): the knowledge base grew from 36 to
**97 verified Indian Standards** (161 records in total), every one of them carrying an official
`bis.gov.in` source, a source document, and a verification date. The 61 new records are transcribed from
three official BIS "Products under Compulsory Certification" pages — Scheme I (ISI Mark), Scheme II
(Compulsory Registration Scheme) and Scheme IV (Certificate of Conformity) — so the product ↔ standard
relationship IS the BIS listing; nothing is inferred. Each record's `content` quotes BIS's own product
description verbatim and states plainly that it is the listing's wording, not the catalogue title, and
that being listed is not a statement about any particular item. Four existing records that BIS lists
against MANY products (notably `IS/IEC 62368 (Part 1)`, which covers 31 notified products from laptops
to power banks to CCTV cameras) gained those product names, so "power bank" or "smart watch" now reaches
the standard BIS names for it. **Keyword policy:** a keyword may only be BIS's own wording or a common
name for the SAME product, and every common name is declared in the record's own text
("Common names used for searching this product: …"); sector guesses ("cooking appliance", "construction
material", "gi pipe") are banned and tested for — an early draft of this milestone added "cooking stove"
to the oil-pressure-stove record and made "cooking oil" match it with high confidence, which is exactly
the false precision this project forbids. **Retrieval:** unchanged engine, one precision fix —
`RetrievalConfig.min_terms_for_high` makes "high" mean what the thresholds always claimed (a title AND a
keyword match, i.e. two pieces of evidence), so a single common word counted twice in two fields can no
longer resolve an ambiguous query; a standard-number match is exempt. "cement" now returns 13 equally
scored cement standards at `medium` instead of arbitrarily preferring one. **Nothing else grew:**
requirements stay 15 (7 checkable), deterministic rules stay 7, INSPECTION_SUPPORTED stays 2 (packaged
water only) and UNSUPPORTED stays 4 (the hallmarking standards); every added standard is STANDARD_ONLY —
identified, explained and sourced, with no invented image rule. Product identification improves for free:
`_vocabulary` is built from titles and keywords, so the richer vocabulary splits more OCR-joined words
and recognises more prominent lines as product names ("LED BULB 9W" is now read as the product). Coverage
report: `scripts/check_knowledge.py` gains a "Product → Standard coverage" table (CATEGORY | PRODUCT |
STANDARD | REQ | IMG | RULES | STATUS) and a `--json` mode for the machine-readable matrix; the frontend
Standards page shows each candidate's coverage status and its KB-recorded certification route, loaded
once from the existing `GET /inspection/coverage`. Measured on a fixed 30-query consumer probe, candidates
went from 11 to 15; the 15 remaining misses (toaster, ceiling fan, refrigerator, pressure cooker, helmet,
school bag, cooking oil, biscuits, shampoo, paint, plywood, solar panel, gas stove, mixer grinder,
bicycle) are real coverage gaps — those products are not on the BIS pages used here and were deliberately
not guessed. Tests: `test_standards_coverage.py` (81 checks: provenance, no invented rules, banned
keyword categories, 20 product → standard pairs, common names, OCR splitting, ambiguity, unknown
products, explanations, domain separation). Count-based assertions in `test_coverage.py`,
`test_hardening.py` and `test_legal_metrology.py` now assert the invariant ("every standard appears",
"2 supported / 4 unsupported / the rest STANDARD_ONLY") instead of a literal 36, so the knowledge base
can grow without rewriting tests.


Milestone 15 (vision-assisted product identification + OCR evidence fusion): an OPTIONAL second evidence
source for ONE question — what product is this? `app/vision.py` is the only module that talks to the
vision model (`VisionClient`, OpenRouter multimodal, default `inclusionai/ling-3.0-flash-vl:free`, verified
`input_modalities: ['text','image','video']`). It uses a **separate OpenRouter key**
(`OPENROUTER_VISION_API_KEY`, never the copilot's `OPENROUTER_API_KEY`), its own model (`VISION_MODEL`),
its own budget (`VISION_MAX_IMAGES` 2, `VISION_DAILY_LIMIT` 40, `VISION_MINUTE_LIMIT` 10) and its own
failure path, so a vision outage cannot touch the DeepSeek copilot and vice versa. Requests send
`reasoning: {"enabled": false}` (Ling reasons by default) and a base64 `image_url` content part; identical
image bytes are answered from an in-process cache, so saving an inspection — which re-runs the analysis
server-side — never spends the quota twice.

**A visual observation is deliberately weaker than OCR, and that is enforced, not hoped for.** `_scrub`
deletes any IS number, licence number, HUID, FSSAI number, price, quantity, date or certification claim
the model writes *before* the observation reaches the application, and records `scrubbed: true` plus a
limitation saying so; a `product_label` containing a digit is rejected outright. Declarations are
unreachable from here: `app/declarations.py` and `app/compliance.py` do not import vision at all, and
vision output never becomes a declaration. Vision cannot name a standard either — like the existing
`_model_hint`, it produces a product *clue* that goes through the same phrase gate and the same
deterministic `ProductStandardFinder`, so it can only ever retrieve records the knowledge base already
holds.

**Evidence fusion** (`_fuse` in `app/product_identification.py`, deterministic, no model): the result
carries `signals` (`ocr_supported` / `vision_supported` / `knowledge_supported` / `agreement` /
`conflicts`) and `vision_status` (`OK` | `UNAVAILABLE` | `NOT_RUN`). Outcomes — OCR and vision agree →
MATCHED, agreement stated in the reason, **retrieval confidence unchanged** (agreement is not verified
evidence); they disagree → REVIEW with the conflict quoted in full, MetrIQ never chooses; no OCR product
evidence but vision has some → REVIEW, `method: vision_assisted`, needs officer confirmation; photos of
one package that appear to show different products → a cross-side conflict; vision unavailable or
unconfigured → byte-for-byte the pre-Milestone-15 result. The "the label text names more than one
product" rule now counts only OCR-supported candidates, so a vision-derived candidate can never be
blamed on the label.

Multi-side: every readable photo is observed independently (up to the cap) and keeps its own
`image_id` / `side`; a failed side is reported, never treated as absent. Persistence needs **no
migration** — the analysis is stored as JSONB and both new fields are defaulted, so inspections saved
before this milestone still load (tested). Report: a separate numbered "Visual product observations"
section, never under BIS evidence, labelled "Unverified visual observation" with the model named.
Copilot: the observations enter the grounded context labelled UNVERIFIED and the system prompt ranks them
BELOW every other source and forbids calling them verified; DeepSeek is never sent an image. Frontend:
the existing Product identification panel gains a "Visual observation" block, a Support row
(OCR text / Visual / Knowledge base) and the conflict text — no redesign. Tests:
`test_vision_fusion.py` (155 checks, every provider call stubbed — no tokens spent).


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
      llm.py           # LM Studio / Qwen3-4B local LLM adapter (used by /ask — unchanged)
      openrouter.py    # Milestone 13: the ONLY OpenRouter surface, key stays server-side
      vision.py        # Milestone 15: visual product understanding (separate key/model/budget)
      product_context.py # M21: the canonical product context — composes existing evidence, creates none
      copilot.py       # M13 + M20: grounded context (inspection + feature) + system prompt + guard
      copilot_api.py   # M13 + M20: GET /copilot/status, POST /copilot/explain (read-only)
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
                       #   product-specific applicability, coverage matrix
      compliance.py    # deterministic compliance engine: PASS / FAIL / REVIEW / NOT_SUPPORTED, no model;
                       #   every check carries rule_condition + reason_code/category + both evidence chains
      package_label.py # Milestone 8: Legal Metrology package-label evaluation (scope, exclusions, separate result)
      completeness.py  # declaration completeness: detection status + verified-requirement coverage, never "missing"
      pipeline.py      # OCR -> declarations -> product identification -> standard candidates -> compliance
      db.py            # Milestone 9: PostgreSQL engine/session (DATABASE_URL)
      records.py       # Milestone 9: saved inspections + officer review models and workflow
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
    migrations/            # Alembic migrations (0001_inspection_records, 0002_escalation)
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
      test_compliance.py   # compliance rules, aggregation policy, grounding, traceability
      test_multiside.py    # multi-side packages: per-image provenance, duplicates/conflicts, failed sides
      test_why_completeness.py # why PASS/FAIL/REVIEW + declaration completeness, never "legally missing"
      test_coverage.py     # Milestone 7: product applicability, coverage matrix, junk-name rejection, real labels
      test_hardening.py    # Milestone 7 hardening: coverage classes, domains, IS/email normalization, brand != product
      test_legal_metrology.py # Milestone 8: Legal Metrology sources, rules, applicability, BIS separation, UI contract
      test_inspection_records.py # Milestone 9/10: migrations, persistence, escalation states, officer review, stats (PostgreSQL)
      test_escalation.py   # Milestone 10: every escalation reason, resolve-or-escalate decision, determinism
      test_report.py       # Milestone 11: PDF report content, honesty, escaping, read-only endpoint (PostgreSQL)
      test_hallmark_inspection.py # Milestone 12: HUID / purity extraction, untrusted text, escalation, report
      test_hallmark_enhancement.py # M19: components, vision fusion, user HUID, no authentication state
      test_copilot.py      # Milestone 13: provider, grounding, injection defence, withheld answers, independence
      test_copilot_context.py # M20: feature contexts, evidence vocabulary, lab/hallmark/cert safety, language
      test_product_context.py # M21: cross-feature composition, applicability, provenance, trust boundary
      test_standards_coverage.py # Milestone 14: standard provenance, product→standard retrieval, no invented rules
      test_vision_fusion.py # Milestone 15: vision adapter, scrubbing, OCR/vision fusion, graceful failure
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


Milestone 16 (certification journey & scheme guidance): a user can go from "what standard applies to my
product?" to "what certification process do I follow?" to "what do I need to do next?" — all of it
retrieved, never decided. `app/certification_journey.py` is deterministic and calls NO model: every
sentence a journey shows is a WORD-FOR-WORD QUOTE from a verified knowledge record plus that record's
official BIS URL; MetrIQ only chooses which quotes are relevant and what order they go in. **How a scheme
is established** — two independent readings of verified text, never a guess: (1) PROVENANCE — a standard
record transcribed from BIS's own "Products under Compulsory Certification" listing carries that listing
in `document_name`, so being on the Scheme I listing IS the statement that the route is Scheme I; (2) a
`certification` record whose text names that standard number and states a scheme (the packaged-water
record says "Licences are granted under Scheme I"). Agreement, or either alone, establishes the route;
disagreement is reported as a conflict and drops the journey to PARTIAL — MetrIQ does not choose; neither
-> `INSUFFICIENT` and the documented "verified certification information is not currently available"
message, with the official source still offered. Statuses: `VERIFIED` (one standard confidently
identified, a route established, every documented step present) / `PARTIAL` (several candidates, a
conflict, missing steps, or hallmarking — whose jeweller-registration journey MetrIQ does not model) /
`INSUFFICIENT`. `standard_selection` is `CONFIRMED` / `MULTIPLE_CANDIDATES` / `NOT_IDENTIFIED`: several
candidates are never silently resolved into one, and a route is then shown only when EVERY candidate
points at the same scheme ("whichever of them applies"). Retrieval and "Why this result?" are reused
unchanged — `ProductStandardFinder` + `explain_candidate`; no second explanation system. **Knowledge:**
6 new verified `certification` records from official sources checked on 2026-09-19 (bis.gov.in Product
Certification Process / Fee / Apply Online, crsbis.in About CRS) — the Scheme I and Scheme IV guideline
documents BIS publishes, the CRS legal basis and R-number, who may apply to CRS, where BIS publishes its
fees (amounts are never reproduced), and the official application portals. `certification.json` now holds
16 records. One precision fix: the fee record's title/keywords no longer key on the bare token "marking",
which had made it outrank `hallmarking-charges` for "hall-marking charges". **API:** `POST
/certification-guidance` is EXTENDED, not duplicated — it gains `standard_number` and `explain`
(the laboratory endpoint's existing pattern) and returns `journey`; with `explain=false` it is pure
retrieval and needs no LM Studio, so deep links never depend on the local model. **Inspection:**
`InspectionAnalysisOut.certification` carries the journey for the identified standard, built in its own
try/except so a failure returns null and changes no result. **Copilot:** capability
`EXPLAIN_CERTIFICATION` (and the free-text `QUESTION`) receive a `certification_guidance` context section
labelled "NOT a statement that this item ... is certified"; the shared system prompt now forbids saying a
product, manufacturer or item IS certified / holds a licence, and forbids stating a fee, processing time,
required document, testing requirement, validity period or scheme number the evidence does not state.
**Report:** a numbered "Certification guidance" section (product, standard, verification status, scheme,
mark, the journey with each step's quote and source, next steps, limitations, official sources) that
states plainly it is guidance, not the certification status of the physical product; absent guidance
renders nothing. **Frontend:** one shared `components/CertificationJourney.tsx` panel used by the
Certification page and the inspection workspace; Standards cards gain a "Certification journey" link
(`/certification?standard=…`, consumed once, retrieval-only); the copilot chip appears only when the
record carries guidance. No redesign, no new colours. **Coverage, calculated from the real knowledge
base:** 97 verified standards — 90 full guidance, 4 partial (the hallmarking standards), 3 without
sufficient guidance (IS 17526:2021, IS 17803:2022, IS 18140:2023, which came from a product manual, an
advisory and Know Your Standards rather than a scheme listing). By route: Scheme I 70, Scheme II 17,
Scheme IV 3, hallmarking 4. **Nothing else grew:** requirements stay 15 (7 checkable), deterministic
rules stay 7, INSPECTION_SUPPORTED stays 2 — certification guidance is knowledge, not an image rule.
`scripts/check_knowledge.py` prints the certification coverage table. Tests:
`test_certification_journey.py` (110 checks: grounding, quote fidelity, no invented fee / time / document
/ scheme / licence, insufficient and unknown paths, multiple candidates, hallmarking separation, scheme
resolution from verified text only, why-this-result reuse, HTTP contract, copilot grounding, coverage
arithmetic, report honesty). Vision model swapped to `inclusionai/ling-3.0-flash-vl:free` (config only;
`QwenVision` renamed `VisionClient`).


Milestone 17 (multilingual BIS assistant — English, Hindi, Telugu): **the language of
interaction changes, the source of truth does not.** `app/language.py` is the whole layer and it
is deterministic — no model, no network, no new dependency; it imports nothing from retrieval,
OCR, the LLMs or vision (tested). The knowledge base is NOT translated, NOT copied and NOT
re-indexed: there is no second KB and no translation service.

    query -> detect / honour the requested language -> rewrite known terms to canonical English
          -> the EXISTING SearchEngine, unchanged -> the SAME verified records
          -> grounded answer written in the user's language

**Why a rewrite layer at all:** `retrieval/text.normalize` is ASCII-only, so a pure Hindi or
Telugu query reached retrieval as `""` and abstained. The layer runs BEFORE retrieval; the
engine, its scoring, its thresholds and the records are untouched. **Detection** is Unicode
script ranges (Devanagari incl. Extended, Telugu): a real run of an Indian script wins (so
"Electric kettle కి ఏ standard?" is Telugu), a single stray character does not, everything else
is English. **Selection** — an explicit `en`/`hi`/`te` always beats detection; `auto` is the
default; an unknown code falls back to detection rather than erroring. **Aliases** — a small
table (~30 concepts) of Hindi/Telugu spellings for products and BIS terms *that exist in the
verified KB*, applied longest-first; a test asserts every canonical term retrieves something
(except `standard`, which is a retrieval stopword) and that no alias is plain ASCII, so English
queries are never rewritten. A separate `FILLER` set drops romanized Hindi/Telugu question words
("ke liye", "kaunsa", "ku", "emi") from the RETRIEVAL text only — this lifted Hinglish from
`low` to `high` confidence; a test asserts none of them is a KB term. The user's own question is
never modified and is what the model is sent.

**Evidence is identical in every language**: same records, same `IS 367:1993`, same record ids,
same source URLs, same stored English text — Hindi and Telugu kettle queries return the same
best record as English at the same confidence (tail ORDER can differ, because the questions
genuinely differ in wording). **Prompt:** `lang.apply()` appends a clause naming the language and
requiring standard numbers, scheme names, rule/record ids, HUIDs, document names and URLs to be
reproduced exactly, never translated (a title may be glossed *beside* the original). For English
it appends NOTHING, so English behaviour is byte-for-byte unchanged. Abstention and the
empty-question prompt are MetrIQ's own sentences, hard-coded per language — the one place
translated text exists, because MetrIQ is speaking about its own evidence and must do so with no
model running.

**API** (extended, never broken — a request with no `language` behaves exactly as before):
`POST /ask` gains `language` and returns `language` (never `"auto"`) + `matched_concepts`;
`/certification-guidance` and `/laboratory-search` gain the same pair. The certification
journey's own text, quotes and sources stay canonical English — it quotes BIS records. **Frontend:**
`components/LanguagePicker.tsx`, a small inline Auto / English / हिन्दी / తెలుగు segmented control
on the three grounded views. No redesign, no new colours, no UI translation.

**Untouched:** OCR output is raw evidence and is never translated; declarations, product
identification, the vision fusion path, compliance, escalation, the report and the copilot are
not part of this layer. An unknown product abstains in the user's language and never invents a
standard. Tests: `test_multilingual.py` (120 checks, every LLM call stubbed — no quota spent).
Full suite 245 passed. One live OpenRouter call validated the Hindi clause end to end: natural
Hindi prose with `IS 367:1993` and the English document title preserved verbatim.


Milestone 18 (testing laboratory intelligence): **MetrIQ identifies laboratories from verified
laboratory evidence. It does not independently establish a laboratory's current accreditation,
scope, availability, or operational status.**

What existed before: `app/laboratory.py` retrieved BIS *guidance* prose (the Laboratory Recognition
Scheme, where BIS publishes its lists, the LIMS portal) and deliberately **named no laboratory,
because the knowledge base held none** — all 8 `laboratories`/`testing` records are informational.
Milestone 18 fixes the data gap rather than the wording.

**The data is real and official.** `scripts/fetch_lims_laboratories.py` (a BUILD-TIME tool, stdlib
only — `urllib` + `html.parser`, no new dependency, no scraping framework) ingests BIS's own
Laboratory Information Management System listing "IS-wise test facilities in BIS / recognised /
empanelled laboratories" (`lims.bis.gov.in/home/search_is_number/`, public, no login) into
`data/laboratories.json`. **The application never calls LIMS at runtime** — it reads the snapshot.
Coverage, measured: **1,205 records · 245 laboratories · 157 standards as listed · 83 cities**;
**78 of 97** verified KB standards have at least one listed laboratory, 19 have none, and that is
reported rather than padded. Recorded verbatim when present: lab name, OSL code, city, standard as
listed, product as listed, grade/type, recognition validity date, BIS remark. NOT recorded because
LIMS does not print it: address, phone, email, accreditation number, NABL status. Testing charges
are deliberately skipped (they change often and are not needed to find a laboratory).

`app/lab_registry.py` is the deterministic lookup. **A standard -> laboratory relationship exists
ONLY because BIS lists it.** Name, city and "it is a testing laboratory" never establish
capability; they are separate signals that say exactly what they are. Its `StandardKey` is
part/section/edition-aware on purpose — the retrieval layer's `standard_number_key` collapses
`IS 302 (Part 2/Sec 3)` and `(Part 2/Sec 201)` to the same key, which would make an electric-iron
laboratory look like a kettle laboratory. A different EDITION is a different standard, so
IS 14543 (2016)'s 3 laboratories never merge with IS 14543 (2024)'s 27 — `other_editions()`
reports the split instead of hiding it. **No ranking:** ordering is alphabetical and the UI says
so; "best", "recommended", "most suitable" appear nowhere (tested). Validity is
`VALID_AT_SNAPSHOT` / `EXPIRED_AT_SNAPSHOT` / `NOT_STATED` — never "currently valid". A missing
field reads "Not available in the verified MetrIQ record.", never filled in. "No matching verified
laboratory record was found" is stated as a fact about MetrIQ's coverage, **not** about which
laboratories exist.

`app/laboratory.py` extends Phase 7 rather than duplicating it: `find_laboratories()` tries a
given/named standard, then **product -> standard via the EXISTING `ProductStandardFinder`** (no
second classifier; an unconfident mapping is NOT carried forward), then a name/city/product text
lookup. Retrieval finishes **before** any model call, so the LLM never decides relevance; the
prompt now allows naming a laboratory **only** from the supplied `MATCHED LABORATORY RECORDS`
block and forbids inventing accreditation, contacts, status or standards, and forbids ranking.
**API** (extended, not duplicated): `POST /laboratory-search` gains `standard_number` and returns
`laboratories[]` (each with a deterministic `why`: `STANDARD_LISTED` / `PRODUCT_LISTED` /
`NAME_MATCH` / `CITY_MATCH`), `laboratory_standard`, `laboratory_standard_source`,
`other_editions`, `coverage` and `no_match_note`. A pre-existing request shape is unaffected.
**Inspection/report:** `InspectionAnalysisOut.laboratories` and a "Relevant testing laboratories"
report section, both INFORMATIONAL — computed after compliance, never read by it (a test asserts
`compliance.py`, `package_label.py`, `escalation.py`, `completeness.py` and `declarations.py` do
not import `lab_registry`, and that results are byte-identical with and without the registry), and
both state that no listed laboratory tested the item. **Frontend:** `components/LaboratoryResults.tsx`
in the existing `LaboratoriesView` — no redesign. **M17 unchanged:** Hindi and Telugu laboratory
questions reach the same standard and the same laboratories as English (tested live and in CI).
One real bug found and fixed during this milestone: single-word substring matching made "Tell me a
joke" match "InterSTELLar Testing Centre" — token matching is now word-boundary. Tests:
`test_laboratory_intelligence.py` (132 checks, all LLM calls stubbed — no quota spent); three
Phase 7 assertions in `test_laboratory.py` updated where behaviour legitimately changed. Full
suite 258 passed.


Milestone 19 (hallmarking & HUID enhancement): **MetrIQ can identify and explain observable
hallmark/HUID evidence, but it does not authenticate a physical jewellery item's hallmark, HUID,
jeweller registration, or AHC status.** Milestone 12 already built the extraction, the checks and
the untrusted-claim handling; M19 does not duplicate any of it. It adds three things, none of which
can produce an authentication, and makes the safety rule structural rather than a matter of wording:
there is **no AUTHENTIC / VERIFIED / CERTIFIED state for a physical item in any code path** —
`verification_status` is only NOT_VERIFIED / NOT_DETECTED, `overall_status` is always REVIEW, no
check can FAIL, `HUID_AUTHENTICITY` is permanently NOT_SUPPORTED, and the new
`official_verification_required` is always True. A test asserts the outcome vocabulary contains no
authentication word and that seven forbidden sentences ("HUID verified", "the jeweller is
registered", "AHC verified" …) appear nowhere MetrIQ writes.

**Components** — the three marks the verified record `hallmark-components-since-huid` itself
enumerates (BIS logo, purity/fineness, HUID), each DETECTED / NOT_DETECTED / UNCERTAIN /
NOT_SUPPORTED with a deterministic `why` and citing that record. The BIS logo is permanently
NOT_SUPPORTED: it is a graphic and OCR reads text, so reading the letters "BIS" is explicitly
*not* the logo. **"Not detected" is about the PHOTOGRAPH** — the wording never says the article
lacks the mark, and `NO_HUID_DETECTED` is a fixed sentence about the supplied image.

**Vision fusion** reuses the EXISTING Milestone 15 observations (no second pipeline —
`evaluate_hallmark` takes the `vision_observations` the analyzer already produced). Vision answers
ONE question: does the photo look like a precious-metal article? It can never read a mark —
`app/vision.py`'s scrubber already deletes any HUID or IS number — and a test feeds it
"gold ring HUID AB12CD 22K916" to prove no component becomes DETECTED from vision alone.
`SUPPORTS` / `DOES_NOT_SUPPORT` / `INCONCLUSIVE` / `UNAVAILABLE` / `NOT_RUN`; agreement does NOT
upgrade anything, and disagreement with OCR becomes a stated `conflict` plus outcome UNCERTAIN —
MetrIQ picks neither and the OCR evidence is never discarded.

**User-provided HUID** — `huid_reference` is now a form field on `/inspection/analyze` and
`POST /inspections` (omit it and behaviour is exactly as before). It was previously a browser-side
string comparison; it is now recorded in the evidence as `USER_PROVIDED`, preserved verbatim,
normalised only for comparison, and reported MATCHES_OCR_TEXT / DIFFERS_FROM_OCR_TEXT /
NO_OCR_VALUE_TO_COMPARE / MALFORMED. A match changes no status. **Official verification** is quoted
from verified records (BIS Care App) with `performed_by_metriq` permanently False; with the
hallmarking records removed it reports that instructions are not in MetrIQ's evidence set and
invents no URL. A deterministic `why` list explains every observation, written by code, never a model.

**Copilot:** the hallmarking context gains the components, the visual observation (labelled
unverified), the user HUID (labelled a string comparison) and the verification boundary; the shared
system prompt now names the seven forbidden claims and forbids inventing a HUID, a jeweller
registration, an AHC or a hallmarking procedure. **Report:** the existing section keeps its
OBSERVED / VERIFICATION split and gains the component table (with the photo-not-article caveat), a
USER-PROVIDED HUID block and the quoted official guidance. **Domains stay separate:** a HALLMARK
inspection still reports Legal Metrology `NOT_APPLIED`, and `hallmark.py` imports no package-label
or compliance module (tested). The jeweller registration and AHC workflows are deliberately NOT
built. Two real regressions were caught by existing suites and fixed at source: the report glued a
")" onto a source URL, and the records save path bound kwargs unconditionally, breaking a narrower
stub — it now binds only non-default options. Tests: `test_hallmark_enhancement.py` (133 checks,
every LLM call stubbed). Full suite 271 passed.


Milestone 20 (advanced grounded copilot): the copilot becomes CONTEXTUAL — it explains the
deterministic results of the feature pages too, not only a finished inspection — and the verification
MetrIQ runs over what the model wrote is widened. The architecture is unchanged and is the point:
USER -> deterministic retrieval / rules / evidence -> grounded context -> the model -> explanation.
**MetrIQ's copilot explains evidence produced by the deterministic system; it does not independently
establish standards, compliance, laboratory status, certification applicability, or hallmark/HUID
authenticity.** No second LLM abstraction, no new provider, no agent orchestration, no vector search:
`app/openrouter.py` is still the only OpenRouter surface and `app/llm.py` (LM Studio, `/ask`) is
untouched.

**Contexts** — `POST /copilot/explain` now takes exactly ONE of `inspection_id`, `analysis` or (new)
`context`. A feature page sends back the response MetrIQ itself produced; `FeatureContextIn` in
`copilot_api.py` is a WHITELIST (`extra="ignore"`), so only the declared fields ever reach the model.
`build_feature_context(feature, payload)` in `copilot.py` builds the small grounded context —
`STANDARD` (the product -> standard retrieval, reusing the existing deterministic "why this result",
labelled *retrieval confidence is not legal applicability*), `CERTIFICATION` (the journey only — the
LM Studio prose is NOT fed back as evidence) and `LABORATORY` (the BIS LIMS snapshot). Feature
contexts carry no system result, so `system_result` is null and `evidence_scope` is `FEATURE_CONTEXT`.
`FEATURE_CAPABILITIES` fixes which question each context accepts; anything else is 422. The
inspection context gains a `laboratories` section (M18 evidence was previously invisible to the
copilot), and `_journey()` renders the certification journey in one place for both paths.

**New capabilities:** `EXPLAIN_RESULT` ("why this result?" — PASS names the supported checks that
passed, FAIL the rule(s) that failed with their evidence, REVIEW why compliance could not be
established), `WHAT_IS_MISSING`, `EXPLAIN_STANDARD`, `EXPLAIN_LABORATORY`. **`EVIDENCE_VOCABULARY`**
travels with every context and the system prompt repeats it: `NOT_DETECTED` / `UNCERTAIN` /
`UNSUPPORTED` / `NOT_AVAILABLE_IN_KNOWLEDGE_BASE` are four different things and may never be merged
into a generic "missing".

**Guard (deterministic, runs after every reply)** gains three reasons on top of M13's four:
`LABORATORY_STATUS_CLAIM` (accredited / NABL / currently valid / operational / available),
`LABORATORY_RANKING_CLAIM` (best / nearest / recommended / preferred) and `FABRICATED_AMOUNT` (any
currency amount not already in the evidence — this is what stops an invented certification or testing
fee). A sentence can name a laboratory without the word "laboratory", so the lab names MetrIQ actually
sent are read back out of the context (`"lab_name": "..."`) and matched too; an explicit denial
("MetrIQ cannot establish whether it is accredited") is not withheld, because the existing negation
test applies. A withheld answer is replaced by MetrIQ's own sentence — now in the user's language
(`lang.WITHHELD`, the third and last hard-coded translated string set).

**Multilingual (M17 unchanged, extended to the copilot):** `language` on the request, `lang.resolve`
on the officer's own question, `lang.apply` on the system prompt, and `language` + a deterministic
`confidence` (`GROUNDED` / `UNSTRUCTURED` / `WITHHELD` — computed by MetrIQ from what happened to the
answer, never a self-assessment) on the response. The evidence sent is byte-for-byte identical in
every language (tested); English appends nothing, so English behaviour is unchanged.

**Frontend:** no redesign and no new page. `CopilotPanel` gains an optional `context` prop and an
optional `systemResult`, and now appears on Standards, Certification and Laboratories with ONE prompt
chip each plus the existing free-text field; the inspection panel gains "Why this result?", "What
information is missing?" and (only when the record carries laboratory records) "Why were these
laboratories returned?". `InspectionAnalysis` gained the `laboratories` field it had been missing.

**Model config fix found during validation:** `deepseek/deepseek-v4-flash-0731:free` is no longer
served by OpenRouter (HTTP 404). The default and `backend/.env` now point at
`inclusionai/ling-3.0-flash-vl:free`, verified live end to end on 2026-09-20 with ONE laboratory-context
call. The model is still configuration — no caller hardcodes it.

Tests: `test_copilot_context.py` (186 checks, every provider call stubbed — no quota spent): contexts
A-E, why-this-result, what-is-missing and the four states, source preservation, laboratory snapshot
wording, hallmark/HUID safety, certification safety, multilingual, no unsupported facts, provider
failure, malformed / truncated / empty output, the HTTP contract, and the copilot changing nothing.
Full suite 290 passed.


Milestone 21 (cross-feature product intelligence): **MetrIQ connects evidence produced by its existing
deterministic features into a unified product context. The context does not create new evidence and does
not independently verify external facts.** `app/product_context.py` is the whole layer and it is a
COMPOSER: no classifier, no ranking, no rule engine, no model call, no knowledge graph, no new knowledge.
Coverage is unchanged and asserted — 97 verified standards, 15 requirements, 7 deterministic rules,
2 INSPECTION_SUPPORTED.

**The context** carries six sections — PRODUCT / STANDARD / CERTIFICATION / INSPECTION / LABORATORY /
HALLMARKING — each with an explicit availability (`AVAILABLE` = MetrIQ holds evidence · `NOT_AVAILABLE` =
the feature applies but the verified data has nothing · `NOT_APPLICABLE` = it does not apply to this
product · `UNCERTAIN` = the evidence does not settle it), a one-sentence headline, a `detail` dict holding
ONLY keys that exist, `provenance` naming the system that produced the evidence (`USER_DESCRIPTION`,
`OCR_TEXT`, `DECLARATION`, `VISION_OBSERVATION`, `DETERMINISTIC_RETRIEVAL`, `BIS_KNOWLEDGE_BASE`,
`DETERMINISTIC_RULE_ENGINE`, `LABORATORY_SNAPSHOT`, `HALLMARK_OBSERVATION`), its sources and its
limitations. Plus `conflicts` (agreements and disagreements the features recorded — carried word for word,
never resolved) and a deterministic `summary` written from structured data; a model may explain it
afterwards but never produces it.

**Two entry points with different trust properties, documented in the module and tested:**
`build_from_query` is SERVER-DERIVED (the request carries only text; MetrIQ runs its own
`ProductStandardFinder`, `CertificationJourneyService` and `LabRegistry` — `POST /product-context`,
`extra="forbid"`), and `build_from_analysis` composes a FINISHED analysis (from the database, or echoed
back by the browser on the live inspection screen exactly as `/inspection/analyze` produced it — the same
trust model the copilot's live path has always had; never claimed as re-derivation).

**Links, all reusing existing systems:** the standard is whatever `ProductStandardFinder` /
product identification already returned (never reranked; no confident single candidate -> reason code
`STANDARD_NOT_ESTABLISHED`); certification is the M16 journey with ITS OWN limitations carried verbatim
(`INSUFFICIENT` or no journey -> `CERTIFICATION_ROUTE_NOT_AVAILABLE`, never borrowed from a similar
product); inspection is the compliance engine's own output (failed / review / passed / no-verified-rule
rule ids, coverage, escalation — nothing recomputed); laboratories are the M18 snapshot (validity only
`*_AT_SNAPSHOT`, alphabetical, no ranking, no accreditation, no contacts, the un-ingested Group-1 /
Group-2 PDFs disclosed, a missing city never guessed). **Hallmarking relevance is decided by the EXISTING
retrieval engine** — a jewellery standard, or a query whose best verified record is a hallmarking record
("gold ring") — so no jewellery classifier was written; M19's boundaries survive intact (no
authentication, `official_verification_required` always true, overall REVIEW, BIS logo unconfirmable by
OCR, a user HUID is a text comparison). A package never gets hallmarking; jewellery never gets
package-label inspection.

**Where it appears:** `InspectionAnalysisOut.product_context` (composed in the analyzer from parts it
already built — no extra retrieval, isolated so a failure leaves it null, **no migration**: old saved
records simply have none and the composer tolerates every missing key, tested); `POST /product-context`
for a product that has not been inspected; copilot feature context `PRODUCT` with capability
`EXPLAIN_PRODUCT_CONTEXT` ("Summarise everything MetrIQ found") plus the cross-feature questions, reusing
`ProductContextOut` as the request whitelist. Every M20 guard still fires through it (fabricated standard
/ URL / amount, laboratory status and ranking claims) and the M17 language layer is unchanged.

**Frontend:** `components/ProductIntelligence.tsx` — one compact panel in the inspection workspace and on
the Standards page, linking to the existing routes rather than duplicating them; `?standard=` deep links
added to LaboratoriesView and `?q=` to StandardsView, mirroring CertificationView's existing pattern.
**Stale M18 copy fixed:** the Laboratories page no longer says MetrIQ "does not hold individual laboratory
records" — it now describes the verified snapshot, its date and what a listing does not establish.

Tests: `test_product_context.py` (200 checks, every model call stubbed): composition, applicability,
each connection, uncertainty, snapshot and hallmarking safety, conflicts, provenance, the client payload
whitelist, copilot guards and language, unchanged results and coverage, old-record compatibility, the
corrected UI copy, and no unsupported claim. One invariance assertion in `test_vision_fusion.py` now pops
the context's vision diagnostic the way it already pops `product.vision_status`, and asserts the context
reaches the same conclusions with and without vision. Full suite 308 passed.