## Phase 4 — Every standard resolved to its real catalogue identity (2026-09-25)

The knowledge base held BIS's PRODUCT wording from the compulsory-certification listings but
not the standards' own catalogue titles. Phase 4 adds them, and records where each title's text
came from.

**SOURCE PROVENANCE IS A PARAMETER, NOT A CONSTANT.** BIS *sells* these standards, and the
ministry that owns BIS proposed this problem statement, so `scripts/fetch_standard_titles.py`
takes `--source bis | archive`, every index entry and every enriched record carries its route,
and the UI shows it. Mirrored text is never presented as coming from bis.gov.in.

**The BIS route goes further than expected: all the way, anonymously.** BIS's Know Your
Standards page drives an Elasticsearch endpoint
(`…/knowyourstandards/Elasticsearch/getsearchAjax`) that answers with **no login and no
credentials** — it needs a session cookie from one page fetch plus browser `Referer` / `Origin`
/ `Content-Type` headers (without them it is a flat 403, which is what makes it look closed),
and the POST field is `search`, not `txt_search`. It returns structured rows: `vc_doc_num`,
`is_part`, `is_sec`, `is_year`, `identical_is` and the full title. It is also CURRENT — it
reports IS 14543:**2024** where our listing-derived record says 2016. **Where it stops:**
metadata is all of it. Downloading the standard DOCUMENT's text needs a logged-in BIS session,
and this tool does not attempt it; nothing in this phase required it, because titles, parts,
years and editions all come from the catalogue search. It is, however, slow — roughly four
responses a minute — so the full run takes about two hours and the on-disk cache
(`backend/.cache/`, gitignored) makes a re-run instant.

**The archive route validated the brief's own measurement.** Public.Resource.Org's mirror
(identifiers `gov.in.is.*`, 22,025 items, confirmed) resolved **71.7% by exact identifier** —
the brief predicted ~72%. Redirects must be followed or the download returns 0 bytes, as warned.
The mirror is inconsistent about the ISO/IEC infix (`IS/ISO 6742-2` is `gov.in.is.iso.6742.2.*`
but `IS/ISO 9994` is `gov.in.is.9994.*`), so both shapes are tried rather than guessed.

**One real matching bug, caught and fixed rather than accepted.** Archive's query language makes
`gov.in.is.302.2.*` match `gov.in.is.302.2.21.2018`, so `IS 302-2:26` "resolved" to Section 21 —
a different standard. A wildcard hit is now accepted only when what follows the stem is a bare
four-digit year (`_segments_match`). That moved 3 entries from WILDCARD to NOT_FOUND, which is
the correct direction: the brief said to stop rather than loosen matching, and this tightened it.

**Results.** `data/standard_archive_index.json` covers all 505. BIS primary, archive consulted
only where BIS could not resolve, merged by `scripts/merge_standard_index.py`:

| route | EXACT | WILDCARD | NOT_FOUND | resolved |
|---|---:|---:|---:|---:|
| BIS catalogue alone | 295 (58.4%) | 183 (36.2%) | 27 (5.3%) | 478 |
| Archive alone | 362 (71.7%) | 109 (21.6%) | 34 (6.7%) | 471 |
| **merged (shipped)** | **306 (60.6%)** | **186 (36.8%)** | **13 (2.6%)** | **492 (97.4%)** |

(The two routes mean different things by EXACT: for the archive it is an exact identifier hit;
for BIS it is that the year in our number matched an edition BIS lists.)

**Enrichment** (`scripts/enrich_standard_titles.py`) adds, never replaces: 492 catalogue titles
appended to `content` under a `Catalogue title:` label plus a provenance sentence naming the
route; `source_url` is untouched, so the BIS listing page stays the primary source. The existing
sentence "this record carries BIS's own product description … not the verbatim catalogue title"
was rewritten, because it stopped being true once both are present — the listing names the
notified PRODUCT, the catalogue names the STANDARD, and the record now says so. **63 years were
filled in** where the source offered exactly one edition. **10 were refused** because several
editions exist and choosing one would invent a fact: IS 302 (Part 2/Sec 3) [2007, 2024],
IS 12615 [2018, 2026], IS 16102 (Part 1) [2012, 2026], IS 12640 (Part 2) [2011, 2016],
IS 6452 [1989, 2026], IS 8042 [1988, 2015], IS 16242 (Part 1) [2014, 2025],
IS 10322 (Part 5/Sec 1) [2012, 2026], IS 5175 [2022, 2026], IS 15392 [2003, 2019]. Every edition
found is recorded in the index for a later phase. `schema.py` is unchanged; a title over 200
characters is truncated in `title` and kept in full in `content`.

**17 titles are flagged as damaged and kept exactly as returned.** The damage is in BIS's own
catalogue — IS 16192 (Part 3) holds `â€"` where an em dash belongs, double-encoded at source
(verified against the raw bytes; it is not a decoding error here). They are labelled "the text
looks damaged and has NOT been corrected". An earlier version of the detector flagged 28 by
treating en and em dashes as corruption; it now allows ordinary typographic punctuation and
matches mojibake signatures instead.

**13 standards remain unresolved by both routes** and were left untouched, not guessed: IS 16046,
IS 8828, IS 302-2:26, IS 60669-2-1: 2008, IS 1989 (Part.2): 1986, IS 17043 (Part-1): 2024, the
four IS 18471/18480 dual-numbered ISO adoptions, IS 12933 (Part 1)+(Part 2) and IS 16077, whose
`standard_number` fields contain TWO standards each, and IS 10322 (Part 5)Section 9: 2017.

**API and UI:** `ProductStandardResultOut.catalogue` carries `{title, source_route,
source_label, official, title_suspect}`, parsed back out of `content` so there is one source of
truth and no schema change. The Standards card shows the catalogue title beneath the product
heading with a `BIS catalogue` / `third-party mirror` marker, and says plainly when a title was
returned damaged.

**Phase 2 harness re-run: the numbers did not move** — recall@1 85.6%, recall@5 98.1%, abstention
24.4%, false-match 13.4%, identical to the Phase 3 baseline. A first run appeared to drop to
79.8% / 92.3%, but every one of those 6 regressions was a stale expectation: the query set's
`bis_listing` entries derive their expected answer from the knowledge base, and 63 numbers had
just gained a year. Re-deriving the set (its documented rule) restored every figure; one
hand-written literal (`IS 16333 (Part-3)` → `IS 16333 (Part-3):2022`) was updated for the same
reason. The single genuine change is internal: "cement standard" moved from rank 2 to rank 3,
still inside the top 5.

**Seven existing suites broke on the same thing and were made year-tolerant, not re-pinned.**
`test_product.py`, `test_why_this_result.py`, `test_standards_coverage.py` and
`test_product_identification.py` asserted literal standard numbers ("IS 14625", "IS 8144",
"IS 269") that BIS's listings write without a year. Phase 4 established those editions, so the
literals went stale. Each comparison now ignores a trailing `:YYYY` — "IS 14625" and
"IS 14625:2015" are the same standard with its edition now known — rather than being bumped to a
new literal that would go stale again the next time an edition is resolved. Two Phase 2/3 suites
needed the opposite treatment: the eval harness's matching stays STRICT (an edition year is part
of a standard's identity, and loosening a measurement tool to make it pass would be exactly the
self-grading the harness exists to avoid), so the hand-typed expectations in `eval_retrieval.py`
were updated to the now-established numbers instead. Every metric came out identical.

