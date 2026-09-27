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

