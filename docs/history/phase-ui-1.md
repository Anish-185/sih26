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
