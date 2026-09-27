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

