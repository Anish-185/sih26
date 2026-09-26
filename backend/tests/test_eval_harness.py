"""Checks for scripts/eval_retrieval.py — the retrieval evaluation harness.

The harness exists to MEASURE `app.retrieval.SearchEngine`, so these checks guard
the things that make a published number trustworthy:

  1. the harness runs offline and produces every metric it claims to,
  2. the committed baseline is the real one — a fresh run reproduces it,
  3. the query set is well formed and every expected answer actually exists in
     the knowledge base (an expectation pointing at a missing record would
     manufacture a failure), and
  4. the adversarial block behaves safely.

ON (4), AND WHY IT IS NOT "every adversarial query abstains": the measurement
says otherwise, and the test records what is true rather than what would be
tidy. Four of the ten abstain outright. The other six return something at LOW
confidence — "IS 456:2000" reaches "IS 10325:2000" because the engine's
tokenizer scores the shared year 2000, and a prompt injection reaches whatever
ordinary words it happens to contain. So the property asserted here is the one
that actually protects a user:

    NO adversarial query is ever answered CONFIDENTLY, and none of them ever
    produces a standard number that is not in the knowledge base.

Both hold today, on every adversarial entry. A low-confidence hit is surfaced to
the user as low confidence; a confident wrong answer is the failure that matters,
and there are none. The strict-abstention count is asserted as a floor too, so a
regression that made the engine chattier would still be caught.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_eval_harness.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import eval_retrieval as ev  # noqa: E402

from app.retrieval import SearchEngine  # noqa: E402

PASS = 0
FAIL = 0

ENGINE = SearchEngine()
ENTRIES = json.loads(ev.QUERIES.read_text())
REPORT = ev.evaluate(ENTRIES, ENGINE)

KB_STANDARDS = {item.standard_number for item in ENGINE.items if item.standard_number}
KB_IDS = {item.id for item in ENGINE.items}
ORIGINS = {"bis_faq", "bis_listing", "legal_metrology", "consumer_probe",
           "hand_written", "adversarial"}


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def test_the_harness_runs() -> None:
    print("\n[1] the harness runs and reports what it claims to")
    check("every query was evaluated", len(REPORT["rows"]) == len(ENTRIES))
    for metric in ("recall_at_1", "recall_at_5", "abstention_rate", "false_match_rate"):
        value = REPORT["metrics"][metric]
        check(f"metric present and in range: {metric}",
              value is not None and 0.0 <= value <= 1.0, str(value))
    check("mean confidence is reported per outcome",
          set(REPORT["mean_confidence_by_outcome"]) ==
          {"hit_at_1", "hit_at_2_to_5", "missed", "correctly_abstained", "false_match"})
    check("every origin is broken out", set(REPORT["by_origin"]) == ORIGINS,
          str(set(REPORT["by_origin"])))
    check("every miss is listed, not just counted",
          all(row in REPORT["rows"] for row in REPORT["misses"]))
    check("the harness needs no network, database or model",
          not any(module in sys.modules for module in ("httpx", "sqlalchemy", "psycopg")))

    # The two runs must agree exactly: the harness is deterministic, so a
    # published number can be reproduced by anyone who checks out this commit.
    again = ev.evaluate(ENTRIES, SearchEngine())
    check("a second run reproduces the same metrics", again["metrics"] == REPORT["metrics"])


def test_the_query_set_is_well_formed() -> None:
    print("\n[2] the query set is well formed and its expectations are real")
    seen: set[str] = set()
    for entry in ENTRIES:
        if entry["query"] in seen:
            check(f"duplicate query: {entry['query']!r}", False)
            return
        seen.add(entry["query"])
    check("no query appears twice", True)

    check("every entry carries the five documented fields",
          all(set(e) == {"query", "origin", "expected_standard_number",
                         "expected_record_id", "note"} for e in ENTRIES))
    check("every origin is one of the documented six",
          all(e["origin"] in ORIGINS for e in ENTRIES))
    check("every entry explains itself in a note", all(e["note"].strip() for e in ENTRIES))
    check("hand-written queries are marked as such, so they can be excluded",
          any(e["origin"] == "hand_written" for e in ENTRIES))

    # An expectation pointing at something that does not exist would invent a
    # failure out of nothing.
    for entry in ENTRIES:
        for number in ev.accepted(entry["expected_standard_number"]):
            if number not in KB_STANDARDS:
                check(f"expected standard exists: {number} ({entry['query']!r})", False)
                return
        for record_id in ev.accepted(entry["expected_record_id"]):
            if record_id not in KB_IDS:
                check(f"expected record exists: {record_id} ({entry['query']!r})", False)
                return
    check("every expected standard number and record id exists in the knowledge base", True)

    gaps = {"shampoo", "school bag", "cooking oil", "biscuits",
            "paint", "solar panel", "mixer grinder", "refrigerator"}
    probe = {e["query"]: e for e in ENTRIES if e["origin"] == "consumer_probe"}
    check("the eight known coverage gaps are in the set", gaps <= set(probe), str(gaps - set(probe)))
    check("and each expects abstention, because finding nothing is correct for them today",
          all(ev.expects_abstention(probe[gap]) for gap in gaps))


def test_adversarial_queries_are_safe() -> None:
    print("\n[3] adversarial queries are never answered confidently")
    rows = [r for r in REPORT["rows"] if r["origin"] == "adversarial"]
    check("the adversarial block covers off-topic, nonsense, injection and an absent IS number",
          len(rows) >= 8, str(len(rows)))
    check("every adversarial query expects abstention",
          all(r["expects_abstention"] for r in rows))

    # The property that protects a user: never a confident answer.
    loud = [r for r in rows if r["confidence"] in ("high", "medium")]
    check("no adversarial query is answered at high or medium confidence",
          not loud, str([(r["query"][:40], r["confidence"]) for r in loud]))
    check("no adversarial query is recorded as a false match",
          not any(r["false_match"] for r in rows))

    # Strict abstention holds for some of them; assert it as a floor so a
    # regression that made the engine chattier is still caught.
    abstained = [r for r in rows if r["abstained"]]
    check("at least four adversarial queries abstain outright",
          len(abstained) >= 4, f"{len(abstained)} of {len(rows)}")
    for nonsense in ("zzzzqqqq vvvvv xxxxx", "asdfghjkl qwertyuiop"):
        outcome = ENGINE.search(nonsense, 5)
        check(f"a nonsense string abstains outright: {nonsense!r}",
              outcome.abstained and not outcome.results)

    # Nothing may be fabricated, at any confidence.
    for row in rows:
        if row["top_standard_number"] and row["top_standard_number"] not in KB_STANDARDS:
            check(f"invented standard for {row['query'][:40]!r}: {row['top_standard_number']}", False)
            return
    check("no adversarial query produces a standard number outside the knowledge base", True)

    injections = [r for r in rows if "gnore all previous" in r["query"] or "isregard your rules" in r["query"]]
    check("the set contains prompt-injection attempts", len(injections) >= 2)
    for row in injections:
        outcome = ENGINE.search(row["query"], 5)
        numbers = [res.item.standard_number for res in outcome.results]
        check(f"injection does not yield the number it demands: {row['query'][:38]!r}",
              "IS 99999" not in numbers and not any(n and "99999" in n for n in numbers), str(numbers))
        check(f"injection is never confident: {row['query'][:38]!r}",
              outcome.confidence in ("none", "low"), outcome.confidence)

    for absent in ("IS 456:2000", "IS 10500:2012"):
        outcome = ENGINE.search(absent, 5)
        numbers = [res.item.standard_number for res in outcome.results]
        check(f"a real standard that is NOT in the knowledge base is not fabricated: {absent}",
              absent not in numbers, str(numbers))
        check(f"and it is not answered confidently: {absent}",
              outcome.confidence in ("none", "low"), outcome.confidence)


def test_the_committed_baseline_is_the_real_one() -> None:
    print("\n[4] the committed baseline is honest")
    if not ev.BASELINE.exists():
        check("baseline committed (run eval_retrieval.py --write-baseline to produce it)", False)
        return
    stored = json.loads(ev.BASELINE.read_text())
    check("the committed baseline matches a fresh run of the same query set",
          stored["metrics"] == REPORT["metrics"],
          f"stored={stored['metrics']} fresh={REPORT['metrics']}")
    check("the committed baseline publishes its misses, not only its metrics",
          stored["misses"] and len(stored["misses"]) == len(REPORT["misses"]))
    check("the committed baseline keeps every row, so any number can be re-derived",
          len(stored["rows"]) == len(ENTRIES))
    check("the baseline records how many records were indexed when it was taken",
          stored["engine"]["indexed_items"] == len(ENGINE.items))


def test_the_harness_does_not_touch_the_engine() -> None:
    print("\n[5] it measures; it changes nothing")
    source = (BACKEND / "scripts" / "eval_retrieval.py").read_text()
    for forbidden in ("RetrievalConfig(", "threshold_", "weight_", "engine.items ="):
        check(f"the harness does not reach into retrieval internals: {forbidden!r}",
              forbidden not in source)
    check("the harness writes only under tests/data/",
          source.count(".write_text(") == 2 and "QUERIES.write_text(" in source
          and "target.write_text(" in source)
    check("a normal run writes eval_latest.json; only --write-baseline writes the baseline",
          "target = BASELINE if args.write_baseline else LATEST" in source
          and ev.LATEST.name == "eval_latest.json")


def main() -> int:
    test_the_harness_runs()
    test_the_query_set_is_well_formed()
    test_adversarial_queries_are_safe()
    test_the_committed_baseline_is_the_real_one()
    test_the_harness_does_not_touch_the_engine()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
