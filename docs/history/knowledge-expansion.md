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

