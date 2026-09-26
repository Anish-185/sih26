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
| 14 | OCR -> declarations -> product -> Indian Standard |

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
engine covers only verified requirements. Run: backend on :8000, then
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
product name. The remaining work is verified requirement data.

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

Milestone 9 (persisted inspections + history): saved inspections live in PostgreSQL
(`DATABASE_URL`, default `postgresql+psycopg:///metriq`) through SQLAlchemy (`app/db.py`,
`app/records.py`) with an Alembic migration (`backend/migrations`, `alembic upgrade head`).
Tables: `inspections` (system result: `bis_result`, `legal_metrology_result`, combined
`system_result` — FAIL if either FAILs, PASS only if both PASS, else REVIEW — `system_reasons`,
product fields, `sides`, full `analysis` JSONB) and `inspection_images` (photo bytes per upload
position). Triggers reject any update of the system columns or stored photos, so a saved record is
immutable. *(M22 removed the human review workflow this milestone had added: the officer status,
decision, result, note and review timestamps. The columns migration 0001/0002 created are simply no
longer mapped — legacy rows load and are ignored, and no migration was needed.)* `app/records_api.py`: `POST /inspections` (multipart
photos only — the backend re-runs the analysis itself; any other form field → 422),
`GET /inspections` (`?escalated=`), `GET /inspections/stats`, `GET /inspections/{id}`,
`GET /inspections/{id}/images/{index}` (404 unknown, 422 malformed id, 503 database down).
Legal Metrology / BIS aggregation is unchanged: REVIEW stays REVIEW and the UI explains it.
Frontend: Inspection gains "Save inspection"; `/history` (real records), `/history/:id`
(`RecordView`: the fixed system result panel and the exported inspection `Workspace` over the stored
photos and saved analysis), Dashboard counts from `/inspections/stats`. `frontend/src/mocks.tsx` is gone — no placeholder data remains. Tests:
`test_inspection_records.py` (61 checks; needs the `metriq_test` database, refuses any database not
named `*_test`). Full suite 169 passed.

Milestone 10 (resolution assessment): `app/escalation.py` `assess(analysis_json)` decides
deterministically whether the system can resolve an inspection from the photographed evidence, from the
finished analysis only (no model, changes no result). Reasons, each with `code` / `label` / `source`
(OCR, PRODUCT, BIS, LEGAL_METROLOGY, PIPELINE) / `message` / `source_regions` / `checks`:
PIPELINE_ERROR, IMAGES_UNREADABLE, IMAGE_QUALITY_LOW, PRODUCT_NOT_IDENTIFIED, MULTIPLE_CANDIDATES,
PRODUCT_NOT_CONFIRMED, NO_VERIFIED_STANDARD, HALLMARK_NOT_VERIFIABLE (HUID / hallmark text or a
hallmarking standard — never verified), CONFLICTING_DECLARATIONS, OCR_UNCERTAIN, MISSING_EVIDENCE,
REQUIREMENT_NOT_CHECKABLE, PACKAGE_SCOPE_EXCLUSION, SYSTEM_RESULT_REVIEW. REQUIREMENT_NOT_CHECKABLE does
not block a FAIL (it cannot overturn clear evidence); every other reason escalates. An assessment error
escalates. `InspectionAnalysisOut.escalation` carries it (`/inspection/analyze`). Saved inspections:
migration `0002_escalation` adds `escalation_required` + `escalation_reasons` (protected by the
immutability trigger). Existing rows are backfilled with the same `assess`; stats gain `escalated`.
Frontend: `ResolutionPanel` (records.tsx) — deterministic rules → system result → was everything
established from the photos? → final system result, or the list of what MetrIQ could not establish,
with clickable evidence-linked reasons — in the live workspace and the saved inspection; History
"Resolution" and "Not established" columns; Dashboard "Resolved by system". *(M22: the officer queue
and decision this milestone fed were removed; the assessment itself, its reasons and its evidence
links are unchanged.)*
With the current verified data every real inspection escalates (no standard has every requirement
checkable). Tests: `test_escalation.py` (27), `test_inspection_records.py` (77, incl. 0002 backfill).

Milestone 11 (evidence-backed inspection reports): `app/report.py` renders a PDF (ReportLab platypus,
new dependency `reportlab`) from the persisted record only — `build_story(record_json, images, generated_at)`
returns the flowables, `render_report` builds the PDF with "page X / Y" chrome. No DB writes, no
recomputation, no model. Fonts: Noto Sans Regular/Medium/Bold + Noto Sans Mono in `app/report_fonts/`
(SIL OFL 1.1, `OFL.txt`) — they cover the rupee sign. Sections: header (ID, saved / generated in IST,
status) · 02 summary (product or "Not identified", brand, manufacturer/packer/importer, category or "Not
established", sides, AUTOMATED SYSTEM RESULT and RESOLUTION boxes side by side) · 03 stored photos with
OCR boxes drawn on an in-memory copy (only sides that exist) · 04 OCR evidence (field | value | confidence |
side + region + raw text, region table capped at 60) · 05 declarations with stored statuses (NOT_DETECTED is
not "legally missing") · 06 BIS standard evidence (identified / candidate, why this result, source) or
"No verified BIS standard was identified by the automated retrieval process." · 07 Legal Metrology
requirements (checkable vs not checkable from an image, status, source + URL per requirement) · 08
compliance table (NOT_SUPPORTED shown as UNSUPPORTED, never PASS) · 09 automated system result with
every reason a point could not be established, uncertain / conflicting declarations, unsupported checks ·
10 only the sources stored with the evidence. *(M22 removed the human-review and final-outcome sections;
every result in the report is the deterministic system's own.)* All stored text is XML-escaped. Endpoint `GET /inspections/{id}/report.pdf`
(422 malformed id, 404 unknown, 503 database down; session rolled back, never committed). Frontend:
"View report" (`RecordView` header) — `LinkButton external` to the PDF URL. Tests: `test_report.py` (35:
PASS / FAIL / REVIEW, no human decision, honesty, multi-side, escaping, stored-only URLs, endpoint
read-only with no LLM / recompute calls).

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
the saved records, HUID reference field = text comparison only). Sample `synth_hallmark-closeup.png`. Tests:
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
complete `answer` and evidence entries are recovered and the user is told it was cut short, so raw
JSON is never shown. `app/copilot_api.py`: `GET /copilot/status` (configured flag, model,
remaining free budget, capabilities — no key) and `POST /copilot/explain` (strict body: exactly one of
`inspection_id` or `analysis`, one of nine capabilities, optional question/rule_id; 422 on anything else,
404 unknown id, 429 on a free-tier limit, 503 otherwise). Read-only: the session is rolled back and never
committed, nothing is recomputed, and the copilot imports no pipeline module. Frontend:
`features/CopilotPanel.tsx` — a panel, not a chat: prompt chips, one text field, the answer with its
evidence, limitations and the sources stored with the evidence, the deterministic result shown beside it,
and the free budget in the footer; in the inspection workspace and on the saved-record page
(`hideCopilot` keeps it in one place there). One request per user action; nothing is ever called
automatically. Tests: `test_copilot.py` (204 checks, every provider call stubbed — no tokens spent) plus
copilot read-only checks in `test_inspection_records.py`. With no key configured, or with OpenRouter down,
every result, check, source, escalation and PDF report is unchanged.


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
evidence but vision has some → REVIEW, `method: vision_assisted`, needs manual confirmation; photos of
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
on the user's own question, `lang.apply` on the system prompt, and `language` + a deterministic
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

Milestone 22 — FINAL (evidence graph + removal of the human review workflow). Two parts.

**Part 0 — the officer / human review workflow is gone.** It was not part of SIH26107, so MetrIQ no
longer has one. Removed: the officer status (`NOT_REQUIRED` / `PENDING` / `IN_REVIEW` / `COMPLETED`),
the officer decision (`ACCEPT_SYSTEM_RESULT` / `OVERRIDE` / `MANUAL_REVIEW`), the officer result, the
officer note, the review timestamps, `final_result`, `POST /inspections/{id}/review`, the
`?officer_status=` filter, the review-queue page and route, the officer panel on the saved record, the
officer report sections (10 "Officer review" and 11 "Final outcome"), the officer stats and dashboard
block, and the `officer_review` pipeline stage. **What KEPT is the deterministic result:** PASS / FAIL /
REVIEW are still produced by `app/compliance.py`, `app/package_label.py` and `app/hallmark.py` and
combined by `app.escalation.system_result` — those are SYSTEM results and every one of them is intact.
The M10 assessment stays too, reworded from "does this go to an officer" to "could the deterministic
system establish every applicable requirement from the photos": the field names (`escalation_required`,
`escalation_reasons`), the 14 reason codes and their evidence links are unchanged, so no API or database
shape broke. **No migration:** `app/records.py` simply stopped mapping the officer columns, so a database
migrated earlier keeps them, new rows take their defaults, and legacy rows load with those fields ignored
(tested). `GET /inspections` gained `?escalated=true|false` in place of the status filter. Renames:
`ReviewView.tsx` → `RecordView.tsx` (the saved-record page, same route `/history/:id`),
`EscalationPanel` → `ResolutionPanel`, `OfficerStatusMark` → `ResolutionMark`. One guard was made more
precise while validating: `_AUTHENTICATION` in `app/copilot.py` treated "the verified record /
requirement / rule / source" as an authentication claim and withheld honest answers; a negative lookahead
now excludes MetrIQ's own knowledge-base vocabulary, while every real claim ("the HUID is verified", "the
item is authentic") is still withheld. Regression suite: `test_no_review_workflow.py` (23 checks — greps
the shipped backend, frontend and docs for the removed vocabulary, walks the live OpenAPI route table, and
re-asserts deterministic PASS / FAIL / REVIEW).

**Part 1 — the evidence graph.** `app/evidence_graph.py` answers one question — *how did MetrIQ arrive at
this result?* — by PROJECTING a finished analysis (or a finished product context) onto nodes and edges.
**The MetrIQ evidence graph visualizes relationships already established by the deterministic evidence
pipeline. It does not independently infer standards, compliance, authenticity, laboratory validity, or
certification applicability.** It calls no model, runs no retrieval, evaluates no rule and reaches no
conclusion: every label, status and quote is copied from the analysis, and an edge exists only where that
analysis already links the two things. Nothing downstream imports it (asserted), so deleting it changes no
result. No graph database, no Neo4j — a serializable in-memory projection.

*13 node types:* `PRODUCT`, `OCR_EVIDENCE`, `DECLARATION`, `VISION_OBSERVATION`, `STANDARD`,
`CERTIFICATION`, `REQUIREMENT`, `RULE`, `SYSTEM_RESULT`, `LABORATORY`, `HALLMARK_OBSERVATION`,
`HUID_OBSERVATION`, `SOURCE`. Limitations are not a node type: they ride on the node they belong to and on
the graph, so a boundary is always attached to the thing it bounds. *10 edge types:* `IDENTIFIED_FROM`,
`SUPPORTED_BY`, `MATCHED_TO`, `EXPLAINS`, `REQUIRES`, `CHECKED_BY`, `RESULTED_IN`, `SOURCED_FROM`,
`RELATED_TO`, `OBSERVED_IN` — each carrying a deterministic `explanation` written from the evidence
(the `MATCHED_TO` edge quotes the existing M9 "why this result", not a new one). Every node carries
`provenance` from the same vocabulary M21 uses (`USER_DESCRIPTION`, `OCR_TEXT`, `DECLARATION`,
`VISION_OBSERVATION`, `DETERMINISTIC_RETRIEVAL`, `BIS_KNOWLEDGE_BASE`, `LEGAL_METROLOGY_KNOWLEDGE`,
`DETERMINISTIC_RULE_ENGINE`, `LABORATORY_SNAPSHOT`, `HALLMARK_OBSERVATION`) and a `layer` (0 evidence →
7 source) so a view can lay it out without knowing the types.

*The inspection graph:* declaration `--OBSERVED_IN-->` OCR region · product `--IDENTIFIED_FROM-->`
declaration / OCR region, `--SUPPORTED_BY-->` visual observation · product `--MATCHED_TO-->` standard ·
standard `--SOURCED_FROM-->` verified record, `--REQUIRES-->` requirement, `--RELATED_TO-->` certification
route and laboratory listing · requirement `--CHECKED_BY-->` rule · rule `--SUPPORTED_BY-->` the evidence
it read and `--RESULTED_IN-->` the system result. The result node carries the combination policy and, when
the case is unresolved, the reason labels — never a verdict of its own. `NOT_SUPPORTED` rules say plainly
they are neither a pass nor a failure. *The certification graph* is the M16 journey, or an explicit
`NOT_AVAILABLE` node with its own message when the verified records do not establish a route — never an
inferred one. *The laboratory graph* is the M18 snapshot: validity only `VALID_AT_SNAPSHOT` /
`EXPIRED_AT_SNAPSHOT` / `NOT_STATED`, alphabetical, no ranking, no accreditation / NABL / contacts, the
un-ingested Group-1 / Group-2 PDFs disclosed. *The hallmarking graph* is M19's: an observation node and a
HUID observation node whose authenticity is `NOT_ESTABLISHED`, no node type or status that could
authenticate an item, `HUID_AUTHENTICITY` permanently `NOT_SUPPORTED`, an uncertain purity left uncertain,
the BIS logo unconfirmable by OCR, and a printed "HUID VERIFIED" kept as untrusted OCR evidence.
*The query path* begins `PRODUCT → NOT_IDENTIFIED` and says a typed description is not evidence about a
physical item; it then shows the verified standard that was actually retrieved, and no OCR, declaration,
rule or result node at all.

*API:* `POST /evidence-graph` (`app/graph_api.py`), strict body with exactly one of `inspection_id`
(server-derived from the stored analysis; read-only, the session is rolled back and never committed),
`analysis` or `product_context`. The trust model is M21's, restated not changed: the two client-echoed
forms reuse `InspectionAnalysisOut` / `ProductContextOut` AS the whitelist, the request carries no node,
edge, label or status field at all, and a node smuggled inside an analysis never reaches the graph
(tested). Anything else → 422; unknown id → 404; database down → 503. *Copilot:* capability
`EXPLAIN_EVIDENCE_GRAPH` and an `evidence_graph` context section (compact: nodes, `a --EDGE--> b:
explanation` lines, limitations) for both the inspection path and the `PRODUCT` feature context; the
shared system prompt now forbids deriving a standard, requirement, authentication or result from a path
through a graph. Every M20 guard still fires. *Report:* deliberately unchanged — the PDF already carries
the underlying evidence sections, and the graph is a UI explainability layer.

*Frontend:* `components/EvidenceGraph.tsx` (read-only: layered rows, a node click showing the node's
evidence, provenance, source link and its relationships with their explanations, clicking an OCR node
lights its box on the photograph, "Focus on the path" and a collapsible "what this graph does not
establish") plus `components/EvidenceGraphSection.tsx` (loads it once; a failure removes nothing from the
page). It appears in the inspection workspace (live and saved) and on the Standards page under the product
context. No redesign, no new route, no new colour, no canvas — the layer rows are the small-screen
vertical chain. `?q=` and `?standard=` deep links are untouched.

Tests: `test_evidence_graph.py` (171 checks, every model call stubbed — no quota spent): generation from
both entry points, determinism, the full chain, provenance and stored-only URLs, PASS / FAIL / REVIEW
graphs, unsupported coverage, laboratory snapshot wording, hallmarking safety, no HUID verification node,
uncertain purity, an absent certification route, query-path uncertainty, the client whitelist and
malformed-payload rejection, the copilot receiving only graph evidence, deep links, analyses saved before
this milestone, the report and the M21 context unchanged, and the UI shape. Coverage is unchanged and
asserted: 97 verified standards, 15 requirements, 7 deterministic rules, 2 INSPECTION_SUPPORTED.

Final architecture: PRODUCT → EVIDENCE → DETERMINISTIC ANALYSIS → SYSTEM RESULT → EVIDENCE GRAPH →
OPTIONAL GROUNDED COPILOT. **M22 is the last milestone. Do not start another.**


## Final Hardening Pass (supersedes M22's compliance-verdict architecture)

M22 kept the deterministic PASS/FAIL/REVIEW compliance engine on purpose and called that
architecture final — only the human officer-review layer on top of it was removed. A later,
explicit instruction supersedes that decision: MetrIQ is not an automated legal-compliance judge.
It stops at evidence and verified BIS/Legal-Metrology **knowledge**, never a pass/fail/review
verdict. Separately, Certification and Hallmarking question-answering had to stop depending on the
local LM Studio (Qwen3-4B) model and move onto the same OpenRouter architecture the copilot
already used.

**The compliance engine is deleted, not hidden.** `app/compliance.py` (the BIS rule engine) and
`app/package_label.py` (its Legal Metrology sibling, which reused the BIS engine's internals
directly) are gone from the repository, along with `test_compliance.py` and `test_legal_metrology.py`.
`app/requirements.py` — pure knowledge: which products link to which standards, which verified
requirements apply, the coverage matrix — is untouched; it never depended on the rule engine, and it
is now what the evidence graph's `REQUIREMENT` nodes and the PDF report's requirement sections read
directly, as knowledge, never as a check result. The flow is now strictly evidence-first: OCR →
declarations → product identification → verified standard retrieval → requirement knowledge (never a
verdict) → certification / laboratory / hallmarking knowledge → grounded explanation → evidence graph
/ report. `app/pipeline.py` no longer has a compliance or package-label stage at all.

**`app/escalation.py` is rewritten**, not trimmed. `system_result()`/`system_results()` and the
verdict-only reasons (`SYSTEM_RESULT_REVIEW`, `REQUIREMENT_NOT_CHECKABLE`, `PACKAGE_SCOPE_EXCLUSION`)
are gone. `assess()` now returns `{"required": bool, "reasons": [...]}` — MetrIQ's own assessment of
whether it could establish the product/standard/evidence chain from the photographs, re-sourced from
product identification and `app/requirements.py` directly instead of a compliance verdict. It is
never a legal or compliance judgment; `escalation_required` means only "at least one part of the
evidence chain could not be established from the photos."

**Persistence:** `bis_result`, `legal_metrology_result`, `system_result` and `system_reasons` are no
longer mapped or written by `app/records.py`. Unlike the officer-review columns M22 already left
unmapped (which were nullable), these four were `NOT NULL` with `CHECK` constraints, so a genuinely
new migration was required — not a gratuitous schema rewrite, the minimum needed to let an insert
omit them: `migrations/versions/0003_drop_compliance_verdicts.py` drops `NOT NULL` on all four
columns and nothing else (no column drop, no trigger change, no data rewrite; the immutability
trigger is left exactly as it was, since it only fires on `UPDATE` and these columns are simply never
written going forward — the same "legacy column stays physically present, unmapped" precedent M22
established). `records_api.py`'s `statistics()` no longer computes PASS/FAIL/REVIEW counts; it
reports `{total, escalated, resolved}`.

**Evidence graph and report.** `app/evidence_graph.py`'s `NODE_TYPES` loses `RULE` and
`SYSTEM_RESULT`; `EDGE_TYPES` loses `CHECKED_BY` and `RESULTED_IN` — that vocabulary was exactly the
verdict-projection machinery. `STANDARD --REQUIRES--> REQUIREMENT` is unchanged (it was always
knowledge, sourced from `app/requirements.py`, never a rule result). Hallmarking's own checks
(`HALLMARK_HUID_OBSERVED`, `HUID_AUTHENTICITY`, etc. — never PASS/FAIL, always REVIEW, an M19
invariant untouched by this pass) no longer get wrapped in a `RULE` node; they project directly as
`HALLMARK_OBSERVATION`/`HUID_OBSERVATION` nodes, which already carried the right observed/
not-verified semantics. `app/report.py` drops the `_compliance`/`_system_result` sections and the
PASS/FAIL/REVIEW outcome box entirely; the former BIS and Legal Metrology check-table sections now
present the identified standard's requirements as quoted, sourced **knowledge**, explicitly never a
check table; the old system-result section is now "What MetrIQ could establish from the evidence,"
built from `escalation.reasons` alone.

**Certification and Hallmarking are pinned to OpenRouter, not LM Studio.** Hallmarking has no
dedicated endpoint — `HallmarkingView.tsx` calls the same `POST /ask` every general BIS question
uses — so there is no way to move only "Hallmarking's" model without moving `/ask` itself.
`app/api.py` gains `get_grounded_llm()`, a cached `OpenRouterLLM` factory reading a new env var,
`OPENROUTER_GROUNDED_MODEL` (default `inclusionai/ling-3.0-flash-vl:free`) — deliberately
**independent** of the copilot's own `OPENROUTER_MODEL`, even though the two happen to share a value
today (the copilot's `OPENROUTER_MODEL` was itself repointed at the same Ling model in M20 after
DeepSeek started 404ing on OpenRouter — "the DeepSeek copilot" has been running Ling for a while;
`OPENROUTER_GROUNDED_MODEL` exists so Certification/Hallmarking are pinned on their own terms, not by
coincidence). `get_answerer()` (`/ask`) and `get_certification_service()` (`/certification-guidance`,
`explain=true`) both construct their LLM through `get_grounded_llm()` now — never `LocalLLM`.
`app/certification_journey.py` (the deterministic scheme/step quote-assembly) still calls no model at
all, unaffected. **`app/llm.py`/LM Studio remains in active use in exactly two places, and only
two:** the inspection pipeline's product-identification fallback (`inspection_api.py`,
`LocalLLM(timeout=45)`) and Laboratory search's `explain=true` path (`app/laboratory.py`,
`api.py::get_laboratory_service()`) — the user's instructions named only Certification and
Hallmarking for the provider swap, so Laboratory search was deliberately left as-is. The copilot
(`app/copilot.py`) already used `OpenRouterLLM` exclusively before this pass and is unaffected beyond
losing the `bis_compliance`/`legal_metrology` context sections and the verdict-contradiction guard
(replaced with an unconditional one: MetrIQ produces no compliance verdict at all now, so any
PASS/FAIL/compliant claim in a generated answer is fabricated by definition, not just a possible
contradiction — `FABRICATED_VERDICT`).

**Frontend:** the BIS compliance table, the Legal Metrology / package-label table, the
`DownstreamPanel` rows for those two pipeline stages, and every `system_result` badge (inspection
workspace, saved-record page, history list, dashboard tiles, the copilot panel) are gone.
`ResolutionPanel` (`features/records.tsx`) is rebuilt around `escalation.required`/`escalation.reasons`
alone — what MetrIQ could or could not establish from the photographs, never a verdict badge.
Dashboard stats read the new `{total, escalated, resolved}` shape. `RecordView.tsx`'s
`SystemResultPanel` is gone outright (fully redundant with `ResolutionPanel` once there is no verdict
to show separately). `EvidenceGraph.tsx` drops `RULE`/`SYSTEM_RESULT` from its node-type labels and
layer/chain ordering.

**Multilingual response language: no bug found.** `app/language.py`'s `lang.apply()` already
appended an explicit "write the whole answer in Hindi/Telugu, in natural prose" instruction (not a
bare "answer in Telugu"), and every generation call site (`rag.py`, `certification.py`,
`laboratory.py`, `copilot.py`) already threaded the resolved language through it before this pass —
confirmed by re-reading each call site, not assumed. The one real gap: `test_multilingual.py` stubbed
the LLM to always return one fixed English string, so nothing asserted the *returned answer text* was
actually in the requested script — only that the right instruction was sent. `test_multilingual.py`
gains `test_the_returned_answer_is_actually_in_the_requested_language`, using a stub whose reply
genuinely varies by language (real Hindi/Telugu Unicode text, detected via `lang.py`'s own script
detection) for both `/ask` and `/certification-guidance`. This proves the plumbing carries a
script-correct answer through end to end; it does **not** prove a live deployed model complies with
the instruction — no live OpenRouter call is made anywhere in the suite, by design (matches every
other test file's "no quota spent" convention).

**Knowledge coverage is unchanged** — this was a removal and provider-routing pass, not a
knowledge-base change: 97 verified standards, 15 requirements (7 checkable in principle — that
classification lives in `data/inspection_requirements.json`'s `rule_type` field as knowledge; no
engine executes it anymore), 2 formerly INSPECTION_SUPPORTED standards. `scripts/check_knowledge.py`
still prints these numbers; read them as "what the verified data is annotated with," not as "checks
that run."

**Tests:** `test_compliance.py` and `test_legal_metrology.py` are deleted outright (not gutted —
their entire content was verdict testing with nothing else to salvage). Every other backend test
touched by this pass was rewritten in place for the new shapes. Full backend suite: 304 passed, 0
failed (`cd backend && python -m pytest -q`); all 35 plain-Python runners pass under
`test_plain_runners.py`. Frontend `tsc --noEmit` is clean and `npm run build` succeeds.

Final architecture: PRODUCT → EVIDENCE → OCR / DECLARATIONS / PRODUCT IDENTIFICATION → VERIFIED
STANDARD + REQUIREMENT KNOWLEDGE → CERTIFICATION / LABORATORY / HALLMARKING KNOWLEDGE → EVIDENCE
GRAPH → OPTIONAL GROUNDED EXPLANATION (OpenRouter for `/ask`, Certification and the copilot; LM
Studio only for inspection product-identification and Laboratory search) → REPORT. No step in this
chain produces an automatic PASS/FAIL/REVIEW compliance verdict.

## Knowledge expansion — BIS compulsory-certification lists read in full (2026-09-24)

Not a new milestone: the same Scheme I / Scheme II pages Milestone 14 transcribed by hand were
read **in full**, by a script, into the same schema. **97 → 505 verified Indian Standards**
(161 → 573 records). `backend/scripts/fetch_compulsory_certification.py` is a build-time tool
(stdlib only, `urllib` + regex, no new dependency, same precedent as
`scripts/fetch_lims_laboratories.py`); the application never calls BIS at runtime.

**What it will not do.** Products BIS shows under a *"De-notified from compulsory BIS
certification"* heading are skipped — 218 food rows on the Scheme I page. Listing a de-notified
product as notified would be a false legal claim, so the filter is the first rule in the script and
is stated in its docstring. Every record's `content` carries BIS's own wording from the listing;
nothing is paraphrased or inferred. Keywords are taken **only** from BIS's product name for that
row — no section headings, no invented synonyms — because the Scheme I headings ("Household
Electrical goods", "Cookware, Utensils and Cans…") are exactly the sector guesses M14 banned.
Records already in the knowledge base are never rewritten; the tool only appends.

**Coverage.** Scheme I contributes 421 listed products, Scheme II 75 products across 33 standards
(BIS lists many products against one IS — `IS/IEC 62368 (Part 1)` now carries 43). So **496 of the
769 products** notified under compulsory certification are covered, held as 505 standards. The
remaining ~273 sit in Quality Control Orders outside BIS's two listing pages and were deliberately
not guessed. Laboratory coverage is now **86 of 505** standards with at least one BIS-listed
laboratory (was 78 of 97) — the LIMS snapshot lists labs for a limited set of standards, and the
drop is reported on screen, not hidden.

**Nothing else grew, and that is asserted.** Requirements stay 15, deterministic rules stay 7,
INSPECTION_SUPPORTED stays 2, UNSUPPORTED stays 4; every added standard is STANDARD_ONLY.
Certification guidance resolves for 498 of 505 (Scheme I 461, Scheme II 34, Scheme IV 3,
hallmarking 4).

**Tests: 305 passed, 0 failed.** Four assertions were updated because reality changed, not to make
them pass, and each was verified against BIS's own wording first: `toaster` and `ceiling fan` are
no longer coverage gaps (IS 302 Part 2/Sec 9 "toasters, grills, roasters"; IS 374 "Electric Ceiling
Type Fans") so they moved into the covered-product assertions and were replaced as "unknown
products" by `shampoo` / `school bag`; `test_retrieval`'s nonsense query dropped the word "bicycle"
because BIS lists Reflectors for Bicycles; `test_product_identification` now asserts the invariant
that matters (a plural is never split into word + "s") rather than the old incidental empty string,
since "TREATEDWATER" → "treated water" is a correct evidence-backed repair; `test_product_context`'s
literal count went 97 → 505. Seven of M14's fifteen named coverage gaps are now closed (toaster,
ceiling fan, pressure cooker, helmet, plywood, gas stove, bicycle); eight remain and are still
reported as gaps.

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

## Phase 2 — Retrieval baseline and evaluation harness (2026-09-24)

`backend/scripts/eval_retrieval.py` measures `app.retrieval.SearchEngine` offline — stdlib
only, no LLM, no database, no network — and changes nothing about it (a test greps the harness
for `RetrievalConfig(`, `threshold_`, `weight_` and asserts it writes only under `tests/data/`).
`--json` for machine output, `--derive` to rebuild the query set from its sources.

**The query set is derived, not authored.** A self-authored set with self-chosen expected
answers is grading your own homework, so every expected answer is a pairing BIS, the Department
of Consumer Affairs, or an earlier recorded measurement already made. 149 queries across six
origins, each entry `{query, origin, expected_standard_number, expected_record_id, note}`:
`bis_faq` (14 — every FAQ record's own title), `bis_listing` (72 — BIS's own product wording
quoted inside each standards record as `The BIS list describes the product as: "X"`, kept only
where X maps to exactly ONE standard, sampled every 4th in sorted order), `legal_metrology` (26 —
keyword phrases unique to one record), `consumer_probe` (15 — the queries CLAUDE.md's Milestone
14 section names as that milestone's measured misses; the other 15 of that 30-query probe were
never enumerated and are deliberately NOT reconstructed), `hand_written` (12 — natural consumer
phrasing, marked so it can be excluded from any number) and `adversarial` (10). `--derive`
re-runs the whole derivation so the rules can be checked rather than trusted.

**Two schema decisions the data forced.** `expected_record_id` exists because a FAQ or a Legal
Metrology rule is a correct answer that has no standard number; without it every such query
would have to be mislabelled "should find nothing". And **either expected field may be a LIST**:
BIS lists four helmet standards and eight plywood standards, so "helmet" has four correct
answers and no wrong one among them — collapsing that to one pick would assert a choice BIS does
not make, and collapsing it to null would score a correct answer as a miss. **Abstention is
expected iff both fields are null.**

**Baseline (2026-09-24, 575 indexed records, top-5): recall@1 85.6%, recall@5 98.1%, abstention
rate 24.4%, false-match rate 13.4%.** By origin, recall@1: `bis_listing` 94.4% (100% @5),
`hand_written` 66.7% (91.7% @5), `bis_faq` 50.0% (92.9% @5), `consumer_probe` 100% on its 6
answerable queries. False match is defined as a CONFIDENT (high/medium) answer with the expected
one absent from the top 5 — a correct answer at rank 2 is a ranking weakness that recall@1 vs
recall@5 already measures, and double-counting it as a false match would overstate the harm.
`tests/data/eval_baseline.json` commits every row and every miss; a test asserts the committed
file reproduces on a fresh run, so the published numbers can be re-derived at this commit.

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

Tests: `test_eval_harness.py` (44 checks — the harness runs and is deterministic, the query set
is well formed and every expected standard/record actually exists in the knowledge base, the
adversarial safety properties, the committed baseline reproduces, and the harness never touches
retrieval internals).

## Phase 3 — An informative abstention (2026-09-24)

An unknown product used to produce a dead end. It now produces MetrIQ's own account of its
coverage boundary. **No knowledge-base record, keyword or alias was added** — the gaps are real
and guessing a standard for shampoo is the failure this project exists to prevent.

**The eight "gaps" were re-checked against all 505 records first, and two of them are not gaps.**
Checking only the two BIS listing pages the data came from would have repeated an error the
Phase 2 baseline had already half-caught:

* **refrigerator** — BIS lists "Household Refrigerating Appliances" (IS 17550 (Part 1): 2021) and
  "Freezers" (IS 7872: 2018). Both are in the knowledge base. Retrieval returns nothing because
  the records say *refrigerating* and the consumer says *refrigerator*, and the lexical engine
  does not stem.
* **solar panel** — BIS lists "Crystalline Silicon Terrestrial Photovoltaic (PV) modules"
  (IS 14286) and the thin-film equivalent (IS 16077), both Scheme II. Retrieval returns the solar
  WATER HEATING records instead, because those say *solar* while the PV records say
  *photovoltaic* and never *solar* or *panel*. **Phase 2's baseline note said the listings carry
  only solar water heating — that was wrong**, and the note has been corrected.

The other six (shampoo, school bag, cooking oil, biscuits, paint, mixer grinder) are genuine:
"shampoo", "cosmetic", "soap", "detergent" and "toiletry" appear in **zero** of the 505 records.

**Which makes the obvious message impossible to write.** MetrIQ cannot tell at runtime whether a
product is genuinely absent from BIS's listings or merely listed under wording the query did not
match — so "this product is not on those lists" can never be asserted safely, and the phase's
rule 2 is satisfied instead by stating BOTH possibilities and resolving neither, plus an explicit
"It does NOT mean that no Indian Standard exists for this product." A test asserts that sentence
appears **only** in its negated form, and that the bare claim appears nowhere in any language.

`app/boundary.py` is the whole layer: it counts the coverage figures off the loaded knowledge base
(505 standards = 436 Scheme I + 34 Scheme II + 35 from other official BIS pages, covering 464
listed products, plus 7 Legal Metrology records — a test asserts the parts sum to the whole and
that no figure is hard-coded), then assembles four sentences plus the next step. Every sentence
lives in `language.BOUNDARY` in en / hi / te, the fifth and last hard-coded translated string set
beside INSUFFICIENT, EMPTY_QUESTION, WITHHELD and EVIDENCE_ONLY. **No model is involved** — a test
greps `boundary.py` for `llm`, `openrouter`, `generate(`, `httpx`. The one next step offered is
BIS's own Know Your Standards search, by product name.

**Weak matches (rule 5)** are carried in the boundary, never in `results`: standard number, title,
confidence and the terms that matched, under MetrIQ's own sentence saying it is evidence of what
the search did and that MetrIQ is **not** putting it forward as the answer. "solar panel" surfaces
three solar-water-heating records this way; "shampoo" surfaces none and the block is absent.

Wired into `ProductStandardFinder.find()` (which gained a `language` argument) and the `/ask`
abstention path in `rag.py`; exposed as `boundary` on `ProductStandardResponse` and `AskResponse`,
null whenever there is an answer. Frontend: one shared `components/CoverageBoundary.tsx`, rendered
by the Standards abstention state and by `GroundedAnswer` in place of the bare "Insufficient
verified evidence" callout. No redesign, no new colours — every sentence comes from the backend,
so the browser cannot drift from what MetrIQ verified.

Tests: `test_coverage_boundary.py` (140 checks — counted-not-typed figures, no standard number /
scheme guess / category guess in any of the three languages for all eight products, the
never-say-absent rule, the two vocabulary misses still being vocabulary misses, weak matches never
offered as answers, the HTTP contract, and no model in the path). Three existing suites
(`test_coverage.py`, `test_product_identification.py`, `test_why_completeness.py`) asserted
`/product-standard`'s response keys with an exact set equality, which the new `boundary` field
broke; each now asserts the invariant that actually matters — every original key survives, and
`boundary` is null whenever there is an answer — rather than a literal that would break on the
next extension.

## Phase 4 — Every standard resolved to its real catalogue identity (2026-09-25)

The knowledge base held BIS's PRODUCT wording from the compulsory-certification listings but
not the standards' own catalogue titles. Phase 4 adds them, and records where each title's text
came from.

**SOURCE PROVENANCE IS A PARAMETER, NOT A CONSTANT.** BIS *sells* these standards, and the
ministry that owns BIS proposed this problem statement, so `scripts/fetch_standard_titles.py`
takes `--source bis | archive`, every index entry and every enriched record carries its route,
and the UI shows it. Mirrored text is never presented as coming from bis.gov.in.

**The BIS route goes further than expected: all the way, anonymously.** BIS's Know Your
Standards page drives an Elasticsearch endpoint
(`…/knowyourstandards/Elasticsearch/getsearchAjax`) that answers with **no login and no
credentials** — it needs a session cookie from one page fetch plus browser `Referer` / `Origin`
/ `Content-Type` headers (without them it is a flat 403, which is what makes it look closed),
and the POST field is `search`, not `txt_search`. It returns structured rows: `vc_doc_num`,
`is_part`, `is_sec`, `is_year`, `identical_is` and the full title. It is also CURRENT — it
reports IS 14543:**2024** where our listing-derived record says 2016. **Where it stops:**
metadata is all of it. Downloading the standard DOCUMENT's text needs a logged-in BIS session,
and this tool does not attempt it; nothing in this phase required it, because titles, parts,
years and editions all come from the catalogue search. It is, however, slow — roughly four
responses a minute — so the full run takes about two hours and the on-disk cache
(`backend/.cache/`, gitignored) makes a re-run instant.

**The archive route validated the brief's own measurement.** Public.Resource.Org's mirror
(identifiers `gov.in.is.*`, 22,025 items, confirmed) resolved **71.7% by exact identifier** —
the brief predicted ~72%. Redirects must be followed or the download returns 0 bytes, as warned.
The mirror is inconsistent about the ISO/IEC infix (`IS/ISO 6742-2` is `gov.in.is.iso.6742.2.*`
but `IS/ISO 9994` is `gov.in.is.9994.*`), so both shapes are tried rather than guessed.

**One real matching bug, caught and fixed rather than accepted.** Archive's query language makes
`gov.in.is.302.2.*` match `gov.in.is.302.2.21.2018`, so `IS 302-2:26` "resolved" to Section 21 —
a different standard. A wildcard hit is now accepted only when what follows the stem is a bare
four-digit year (`_segments_match`). That moved 3 entries from WILDCARD to NOT_FOUND, which is
the correct direction: the brief said to stop rather than loosen matching, and this tightened it.

**Results.** `data/standard_archive_index.json` covers all 505. BIS primary, archive consulted
only where BIS could not resolve, merged by `scripts/merge_standard_index.py`:

| route | EXACT | WILDCARD | NOT_FOUND | resolved |
|---|---:|---:|---:|---:|
| BIS catalogue alone | 295 (58.4%) | 183 (36.2%) | 27 (5.3%) | 478 |
| Archive alone | 362 (71.7%) | 109 (21.6%) | 34 (6.7%) | 471 |
| **merged (shipped)** | **306 (60.6%)** | **186 (36.8%)** | **13 (2.6%)** | **492 (97.4%)** |

(The two routes mean different things by EXACT: for the archive it is an exact identifier hit;
for BIS it is that the year in our number matched an edition BIS lists.)

**Enrichment** (`scripts/enrich_standard_titles.py`) adds, never replaces: 492 catalogue titles
appended to `content` under a `Catalogue title:` label plus a provenance sentence naming the
route; `source_url` is untouched, so the BIS listing page stays the primary source. The existing
sentence "this record carries BIS's own product description … not the verbatim catalogue title"
was rewritten, because it stopped being true once both are present — the listing names the
notified PRODUCT, the catalogue names the STANDARD, and the record now says so. **63 years were
filled in** where the source offered exactly one edition. **10 were refused** because several
editions exist and choosing one would invent a fact: IS 302 (Part 2/Sec 3) [2007, 2024],
IS 12615 [2018, 2026], IS 16102 (Part 1) [2012, 2026], IS 12640 (Part 2) [2011, 2016],
IS 6452 [1989, 2026], IS 8042 [1988, 2015], IS 16242 (Part 1) [2014, 2025],
IS 10322 (Part 5/Sec 1) [2012, 2026], IS 5175 [2022, 2026], IS 15392 [2003, 2019]. Every edition
found is recorded in the index for a later phase. `schema.py` is unchanged; a title over 200
characters is truncated in `title` and kept in full in `content`.

**17 titles are flagged as damaged and kept exactly as returned.** The damage is in BIS's own
catalogue — IS 16192 (Part 3) holds `â€"` where an em dash belongs, double-encoded at source
(verified against the raw bytes; it is not a decoding error here). They are labelled "the text
looks damaged and has NOT been corrected". An earlier version of the detector flagged 28 by
treating en and em dashes as corruption; it now allows ordinary typographic punctuation and
matches mojibake signatures instead.

**13 standards remain unresolved by both routes** and were left untouched, not guessed: IS 16046,
IS 8828, IS 302-2:26, IS 60669-2-1: 2008, IS 1989 (Part.2): 1986, IS 17043 (Part-1): 2024, the
four IS 18471/18480 dual-numbered ISO adoptions, IS 12933 (Part 1)+(Part 2) and IS 16077, whose
`standard_number` fields contain TWO standards each, and IS 10322 (Part 5)Section 9: 2017.

**API and UI:** `ProductStandardResultOut.catalogue` carries `{title, source_route,
source_label, official, title_suspect}`, parsed back out of `content` so there is one source of
truth and no schema change. The Standards card shows the catalogue title beneath the product
heading with a `BIS catalogue` / `third-party mirror` marker, and says plainly when a title was
returned damaged.

**Phase 2 harness re-run: the numbers did not move** — recall@1 85.6%, recall@5 98.1%, abstention
24.4%, false-match 13.4%, identical to the Phase 3 baseline. A first run appeared to drop to
79.8% / 92.3%, but every one of those 6 regressions was a stale expectation: the query set's
`bis_listing` entries derive their expected answer from the knowledge base, and 63 numbers had
just gained a year. Re-deriving the set (its documented rule) restored every figure; one
hand-written literal (`IS 16333 (Part-3)` → `IS 16333 (Part-3):2022`) was updated for the same
reason. The single genuine change is internal: "cement standard" moved from rank 2 to rank 3,
still inside the top 5.

**Seven existing suites broke on the same thing and were made year-tolerant, not re-pinned.**
`test_product.py`, `test_why_this_result.py`, `test_standards_coverage.py` and
`test_product_identification.py` asserted literal standard numbers ("IS 14625", "IS 8144",
"IS 269") that BIS's listings write without a year. Phase 4 established those editions, so the
literals went stale. Each comparison now ignores a trailing `:YYYY` — "IS 14625" and
"IS 14625:2015" are the same standard with its edition now known — rather than being bumped to a
new literal that would go stale again the next time an edition is resolved. Two Phase 2/3 suites
needed the opposite treatment: the eval harness's matching stays STRICT (an edition year is part
of a standard's identity, and loosening a measurement tool to make it pass would be exactly the
self-grading the harness exists to avoid), so the hand-typed expectations in `eval_retrieval.py`
were updated to the now-established numbers instead. Every metric came out identical.

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

## Phase 6 — Multi-turn context inheritance (2026-09-25)

"which standard applies to my LED bulb?" → "is it mandatory?" → "where do I get it tested?" now works on
**`POST /ask` only** — the Ask page (and Hallmarking, which shares `AskPanel`) is the one place a user
types a free-form conversation; Standards / Certification / Laboratories are single-purpose pages already
linked by `?standard=`. No router, no intent classifier, no new endpoint, nothing stored server-side.

**Context** (`rag.ConversationContext`: `product`, `standard_numbers` exactly as stored, `category`) is
derived by `BISQuestionAnswerer.resolve_context` from the EXISTING `ProductStandardFinder` — only a
grounded high/medium outcome counts, so an abstention or a coverage boundary (and its weak matches:
"solar panel" → solar water heater) never becomes context. The phrase is the text's own words the top
standard matched in its title/keywords, never a process word. Several standards are carried, never
narrowed; only the product phrase is inherited. **Inheritance** (`_inherit`) is a fixed rule: the question
must contain a referring word (`language.refers_back`) AND, after stopwords, FILLER and
`language.FOLLOW_UP_WORDS` (the BIS process vocabulary — mandatory, tested, licence …, en/hi/te), have NO
word left — any leftover (a known product → the context resets to it; an unknown one like "shampoo"; a
city) means the context is ignored. Native-script leftovers are checked separately because the retrieval
normalizer drops non-ASCII. The echoed product is re-derived, never trusted (`ConversationContextIn`,
`extra="ignore"`, reads only `product`). The inherited retrieval text is the product plus the follow-up
words; the user's question is untouched and the model sees it verbatim with one line naming what it
refers to. The evidence-only fallback uses the same retrieval, so it honours the context.

**Referring words added** (native script — FILLER held only romanized `yeh / iska / uska / ide`, which are
reused, and FILLER itself is unchanged): Hindi `यह ये इस इसे इसका इसकी इसके`, Telugu `ఇది దీని దీనికి దీన్ని అది`;
English `it this that` + phrase `the same`. **Addition D guard** (`rag.unsupported_regulatory_claim`): a
model answer naming a Quality Control Order, a ministry or a year that no retrieved record holds is replaced
by MetrIQ's own evidence text (the knowledge base holds only general QCO records, none per product).

Response: `AskResponse.context` + `inherited`. Frontend: `AskPanel` holds the context, shows "Follow-up
questions can refer to [LED bulb] · Clear" and "Answering about LED bulb, from your previous question".
Tests: `test_conversation_context.py` (41 checks, every model call stubbed).

**Phase 6.1 (grounding fixes found in the live transcript).** `/ask` prompt rules 8–9: a general FAQ /
bis_general statement is never applied to a specific product unless a record names it (compulsory listing
≠ QCO coverage), and a source is described only from its supplied text. Guard `rag.untied_qco_claim`: a
QCO named while a product is in play needs ONE retrieved record that mentions a QCO AND names that product
or one of its standard numbers, else MetrIQ's evidence text replaces the prose. No guard for rule 9 (not
feasible without false positives — see the phase report). `AskPanel` links "Testing laboratories for …" to
`/laboratories?standard=<number as stored>` for one standard, or `/laboratories?q=<product>` for several
(new `?q=` deep link on LaboratoriesView) — never a picked standard.

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

## Phase 8 — Clause evidence attached to answers (2026-09-26)

Retrieval is unchanged (eval harness identical to `eval_baseline.json` on every row). Clauses are
ATTACHED after retrieval, never retrieved: `/ask` (`app/rag.py`) calls `clauses.attach()` — which uses
`rank_within(<standard_number as stored>, <retrieval text>)`, non-zero scores only, at most 3 per
standard and 6 in total — only when retrieval confidence is high/medium AND only for standards that
Product -> Standard confidently identified (`resolve_context`) or that the question names by number. The
second gate exists because "solar panel" is a MEDIUM /ask answer on the single word "solar": retrieval
confidence alone must not be enough to quote a clause. Never on an abstention or a boundary; an inherited
follow-up attaches through the same path. The model gets each clause labelled as OCR with its reference
exactly as stored; SYSTEM_PROMPT rule 3 and the language clause now cover clause numbers and page
references, and forbid stating an OCR numeric limit as confirmed.

**Guard:** `clauses.unsupported_citations()` — a clause counts as cited only with a marker ("clause",
"cl.", "Annex X", annex-style "F-1.4"), never a bare dotted number (quantities). It is supported only by a
marked citation in the context, a heading line, or (dotted/annex labels only) a cross-reference token. /ask
falls back to evidence-only (`GUARD:UNSUPPORTED_CLAUSE`); the copilot withholds (`FABRICATED_CLAUSE`).
**`fallback_reason`** on `AskResponse` (+ server log): MODEL | ABSTAINED | EMPTY_QUESTION | RATE_LIMITED |
NOT_CONFIGURED | PROVIDER_ERROR | GUARD:<rule>; shown as "Path" in GroundedAnswer's assessment column.
**EVIDENCE_ONLY** (en/hi/te) now separates verified records from OCR clause text; the fallback renders
attached clauses with the OCR label and reference. **Why this result:** `WhyThisResult` gains
`text_level` (CLAUSE | IDENTITY), `text_note` and `scope` (the held clause 1 / 1.x records, verbatim);
candidate selection untouched. **UI:** one shared `components/ClauseText.tsx` carries the fixed OCR label
(`clauses.OCR_LABEL`) everywhere clause text appears (GroundedAnswer, Standards "why this result"); the PDF
report's standard section prints the text level and scope with the same label. Links open the archive item
with "PDF page N" as text — a page-specific link was NOT verified (no browser was available), so none is
used. Known weakness, not tuned: `rank_within` lets product words outrank the asked-about word
("sampling for packaged drinking water" attaches 3.2 / 5.3 / 5.4, not 9 SAMPLING). Tests:
`test_clause_attachment.py`.

**Phase 8.1 (within-standard ranking + guard edges).** `clauses.residual_query(standard, query)`:
once a standard is chosen, the query minus stopwords, FILLER, `FOLLOW_UP_WORDS` and every word of
that standard's own record (title, keywords, document name, number) — except a process word that is
a word of one of that standard's MAIN-BODY section headings ("8 MARKING", "21 TESTS"; annex headings
don't count), which names a clause there. `attach` ranks on the residual; an empty residual, or one
that matches no clause ("tell me about …"), attaches the scope clause only. `rank_within` unchanged;
caps and confidence gates unchanged; eval identical. `FOLLOW_UP_WORDS` gained `requirements` (the
singular was already there). Guard: annex-style labels need a dot (`F-1.4`; "M-20", "Class B-1",
"Type A-2" pass), `Annex F-1` still counts, a range cites both ends. Live hi/te answers wrote
"Clause 9" in English every time; the one native marker seen was Hindi `अनुबंध F` (Annex F) —
added, only before an annex letter, because अनुबंध also means "contract".

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

## Phase 9.1 — Orders named by BIS's listing, IN_FORCE, and a plural fix (2026-09-26)

**Rename.** The QCO status `NOTIFIED` is now `IN_FORCE` everywhere (code, tests, frontend, en/hi/te
labels): BIS's own page title uses "notified" to mean "published in the Gazette", the opposite of our
meaning. Still 0 standards: no BIS source states an order is in force.

**Listing Notification column — evidence, not status.** `fetch_compulsory_certification.py
--notifications` (same fetch, same parsers — they now also capture each cell's links and honour the
Notification cell's rowspan, so a stale cell cannot leak into the next group; the script has no cache,
deliberately, since `verify_snapshot.py` reuses its `fetch`) writes `data/listing_notifications.json`: per
listed row the Notification cell VERBATIM, each order it names (S.O. / G.S.R. number, date as printed —
with or without "dated" — and Gazette link) and flags RESCISSION / WITHDRAWAL / SUSPENSION / SUPERSESSION,
read from the cell text, the link text AND the link's file name (BIS often says "Rescind" only there).
496 rows (Scheme I 421, Scheme II 75); a row joins a record only on the exact listing number and product
wording that record's own text quotes — 435 join, 61 do not (mostly Milestone 14's hand-transcribed
records, e.g. `IS/IEC 62368: Part 1: 2023` × 43 products and `IS 269` vs `IS 269:2015`; listed by the
tests, never forced). 434 standards have a listing order; 53 joined records' cells are flagged (27
RESCISSION — footwear, Cotton Bales; 26 SUPERSESSION — LED luminaires). `qco.orders_named_by_listing()`
(exact number as stored) and `listing_orders_for()` (MetrIQ's sentences, `language.LISTING` en/hi/te —
the seventh translated set): "BIS's Scheme I listing names these orders for …", a flagged cell adds
"MetrIQ quotes the cell and does not interpret it, and does not say which of these orders, if any,
applies", and every block ends "It does not state that an order is in force". `status_for` never reads
it. `/ask` attaches it by the clause/QCO rule, shows the cell verbatim, and `untied_qco_claim` accepts it
as the tie; new guard `qco.unsupported_order_numbers` withholds an S.O. / G.S.R. number absent from the
context (`GUARD:UNSUPPORTED_ORDER_NUMBER`); the regulatory-term guard now reads BIS's "(Quality Control)
Order" as "quality control order". `listing_orders` sits beside `qco` on the Standards card
(`components/ListingOrders.tsx`), the journey, inspection candidates and the PDF report. Prompt rule 11:
attribute QCO / order statements to their source. The drift check still hashes number + product only, so
a change to a Notification cell alone is not reported as drift.

**Plural fix, accepted.** The rule existed twice: `product_identification._tokens` (phrase gate, QCO
boundary) and `retrieval.engine._contains_word` (retrieval). Both now treat -ches/-shes/-xes/-sses
plurals as "-es" (the engine also tries -zes, alongside the old "-s" form, so nothing that matched stops
matching; the phrase rule leaves -zes alone because "sizes" -> "siz" would break "size"). The engine's
singular -> "-es" direction covers -ch/-sh/-x/-z but NOT -ss: with it, "What is the BIS certification
process?" matched IS 16655 (welding clothing "for … allied processes") at HIGH confidence —
`test_certification.py` caught it, the eval set has no such query. Ceiling: a singular "mattress" still
finds nothing (only "mattresses" reaches IS 16014), as before the fix. Affected
record words: latches, punches, switches, wrenches, boxes, mattresses, processes. Eval: identical to
`eval_baseline.json` on every metric and row (baseline not rewritten). "pipe wrench" now retrieves
IS 4003 (Part 1) and (Part 2) at high confidence. Tests: `test_listing_orders.py`.

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
