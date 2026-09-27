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

