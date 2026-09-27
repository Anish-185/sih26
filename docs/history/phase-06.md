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

