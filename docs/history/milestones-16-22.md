# Milestones 16–22 (moved verbatim from CLAUDE.md)

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


