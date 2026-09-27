## Phase UI-1 — A two-pane chat page for asking questions (2026-09-27)

`/chat` (`frontend/src/features/ChatView.tsx`) is the one place to ask MetrIQ a question: the
conversation on the left (about 40%), the evidence for the SELECTED answer on the right (about 60%),
open by default. `/ask` redirects to `/chat` and `features/AskView.tsx` is gone; Hallmarking keeps
`components/AskPanel.tsx` unchanged. **No backend change**: every turn is one `POST /ask`; the previous
answer's Phase 6 `context` object is sent with the next question exactly as the old chip did, held only in
page state (each turn keeps the context it was sent with, so Retry resends it; Clear / an answer with no
context / New conversation reset it; New conversation drops an answer still in flight).

The newest answer is selected automatically; clicking an earlier answer selects it (accent left border).
The evidence panel renders that answer's `/ask` response: identified standards linked to their Passport
(`/standard?number=`), clauses via `ClauseText`, sources, `CoverageBoundary` on an abstention, the
evidence-only label, and `fallback_reason`. `/ask` carries no why-this-result, QCO or listing orders, so the
page makes one read-only `POST /product-standard` call for the answer's context product and shows only the
standards that context already named, labelled "Why this result · Product → Standard for '…'".
A 429 / 503 / timeout is a short "MetrIQ is busy" message with Retry — never a raw error. Phone width
stacks the panes with the evidence under each answer (open for the newest). Checks: pytest 394 passed,
eval identical to the baseline, `tsc --noEmit` clean, build succeeds. The 429/503 path and the browser
behaviour were not exercised by a test; the user opened the page and asked for the commit.

## Phase UI-1.1 — Printable Standard Passport; LED fallback diagnosed (2026-09-27)

**Downloadable Passport.** A "Download PDF" button on the Passport calls `window.print()`; no backend,
no dependency, no ReportLab change. A `beforeprint` handler opens every closed `<details>` inside
`.passport` (Requirements, the listing's Notification cell, …) and `afterprint` closes them again, so the
browser's own Print works too; `index.css` adds a print stylesheet (`::details-content` fallback, buttons
hidden, external source links print their URL, no break after a heading, `li` and clauses kept whole);
the top navigation and site footer are `print:hidden`; the evidence graph is replaced in print by one
sentence saying it is on the live page; a print-only footer line names the standard and the print date.
Headless-Chrome print of IS 14543:2016 (68 pages: all 11 sections, 125 requirement clauses expanded, 154
OCR labels, 153 archive URLs) and IS 16102 (Part 1) (18 pages: every identity-only sentence, the
Notification cell verbatim, 25 laboratories) checked by reading the PDF text.

**The LED "is it mandatory?" fallback — diagnosed as case (c); CLOSED, see the resolution below.** Three live runs of
the LED conversation: Q2 is `GUARD:UNTIED_QCO_CLAIM` every time. It is not the CRO being read as a QCO
(the guard reads only the answer, and "(Requirements for Compulsory Registration) Order" does not match
`_QCO`), and the model does not call the LED order a QCO: it repeats the general BIS FAQ sentence
("compulsory only if a product is covered by a Quality Control Order") beside LED bulbs and then says the
evidence does not confirm a QCO for them. The guard is doing its Phase 6.1 job. Recommended fix: an /ask
prompt rule — with a product in play and no supplied record tying a QCO to it, do not mention QCOs; if
the listing names a Compulsory Registration Order, answer from that, attributed to BIS's listing — guard
unchanged.

**Resolution — LED fallback closed.** Three changes in `app/rag.py`, guard untouched:
(1) SYSTEM_PROMPT rule 12 — with a product in play and no supplied QCO record or QCO-naming listing
order for it, do not mention Quality Control Orders at all; if a listing order names a Compulsory
Registration Order, name it as printed and attribute it to BIS's listing; a CRO is never a QCO.
(2) `qco_tied()` factored out of `untied_qco_claim` (same rule, one place). (3) When a product is in play
and `qco_tied` is false, the records that mention QCOs only in general (the "when is certification
mandatory?" FAQ) are left out of the evidence shown to the MODEL — retrieval, the returned sources, the
evidence-only fallback and every guard (which still read the full context) are unchanged. Measured live:
rule 12 alone gave MODEL on 2 of 3 runs; adding a per-request "do not mention QCOs" line made it worse
(1 of 3 — the model restated the instruction as a QCO sentence), so that line was dropped; with the
context filter, 3 of 3 runs returned MODEL, each naming the Electronics & Information Technology Goods
(Requirements for Compulsory Registration) Order, 2012, attributed to BIS's Scheme II listing, with no
QCO mention. Three further runs hit OpenRouter's free per-minute limit (RATE_LIMITED — not a guard
result); no raw answer since the change mentioned a QCO. Tests: `test_conversation_context.py` gains
[9] — a CRO answer passes, calling LED lamps' order a QCO (written out or "QCO") is still withheld as
`GUARD:UNTIED_QCO_CLAIM`, the FAQ record is still a returned source but not in the model's evidence, the
CRO listing order still is, and with no product in play QCO records reach the model as before; every
Phase 6.1 case unchanged. pytest 395 passed, eval identical to the baseline.
