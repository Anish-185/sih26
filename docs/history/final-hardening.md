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

