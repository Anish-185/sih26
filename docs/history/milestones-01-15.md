# First revision: Phases 6–14 recaps and inspection Milestones 1–15 (moved verbatim from CLAUDE.md)

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


