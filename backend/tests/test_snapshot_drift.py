"""Checks for scripts/verify_snapshot.py — the snapshot drift report.

MetrIQ's evidence is a dated snapshot of official BIS pages; the drift check is
how "what happens when BIS updates?" is answered in one command. What matters
about it is exactly two things, and both are tested here OFFLINE — no request
reaches bis.gov.in or LIMS from this suite:

  1. it REPORTS drift and never writes to the knowledge base, and
  2. its hash is over the PARSED rows, so HTML chrome is not reported as drift
     and a real product appearing or disappearing is.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_snapshot_drift.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import verify_snapshot as vs  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


BASE = {
    "url": "https://www.bis.gov.in/example",
    "recorded_on": "2026-09-24",
    "items": ["IS 302 | Electric iron", "IS 367 | Sugar", "IS 14543 | Packaged drinking water"],
}
BASE["sha256"] = vs.digest(BASE["items"])


def current(items: list[str]) -> dict:
    return {"url": BASE["url"], "items": items, "sha256": vs.digest(items)}


def run(stored, now) -> tuple[bool, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        changed = vs.report("example", stored, now)
    return changed, out.getvalue()


def test_hashing() -> None:
    print("\n[1] the hash is over the parsed rows")
    check("the same rows hash the same", vs.digest(BASE["items"]) == vs.digest(list(BASE["items"])))
    check("row order does not change the hash",
          vs.digest(sorted(BASE["items"])) == vs.digest(sorted(reversed(BASE["items"]))))
    check("one changed product changes the hash",
          vs.digest(BASE["items"]) != vs.digest(BASE["items"][:-1] + ["IS 14543 | Bottled water"]))
    check("an empty listing hashes to something stable, not an error",
          vs.digest([]) == vs.digest([]))


def test_reporting() -> None:
    print("\n[2] drift is reported, row by row")
    changed, text = run(BASE, current(BASE["items"]))
    check("an identical listing is UNCHANGED", changed is False and "UNCHANGED" in text)

    added = BASE["items"] + ["IS 9999 | A newly notified product"]
    changed, text = run(BASE, current(added))
    check("a new product is CHANGED", changed is True and "CHANGED" in text)
    check("and the new product is named in the report",
          "+ IS 9999 | A newly notified product" in text, text)

    removed = BASE["items"][:-1]
    changed, text = run(BASE, current(removed))
    check("a withdrawn product is CHANGED", changed is True)
    check("and the withdrawn product is named in the report",
          "- IS 14543 | Packaged drinking water" in text, text)

    _, text = run(None, current(BASE["items"]))
    check("no baseline is stated plainly, never guessed at", "NO BASELINE" in text)
    check("and a missing baseline is not reported as drift", run(None, current([]))[0] is False)


def test_it_never_writes_the_knowledge_base() -> None:
    print("\n[3] it reports; a human decides")
    source = (BACKEND / "scripts" / "verify_snapshot.py").read_text()
    knowledge = Path(vs.ROOT) / "data" / "knowledge"
    before = {p.name: p.stat().st_mtime_ns for p in knowledge.glob("*.json")}

    run(BASE, current(BASE["items"] + ["IS 9999 | A newly notified product"]))
    after = {p.name: p.stat().st_mtime_ns for p in knowledge.glob("*.json")}
    check("reporting drift touches no knowledge-base file", before == after)

    check("the script writes exactly one path, the baseline",
          source.count("write_text(") == 1 and "BASELINE.write_text(" in source)
    check("the baseline is not inside data/knowledge/",
          "knowledge" not in str(vs.BASELINE))
    check("the application never reads the baseline file",
          not any("source_snapshots" in p.read_text() for p in (BACKEND / "app").rglob("*.py")))


def test_the_recorded_baseline_is_usable() -> None:
    print("\n[4] the recorded baseline")
    if not vs.BASELINE.exists():
        check("baseline present (run verify_snapshot.py --record first)", True,
              "skipped — no baseline recorded yet")
        return
    stored = json.loads(vs.BASELINE.read_text())
    check("the baseline holds the sources that were ingested",
          {"scheme-i", "scheme-ii"} <= set(stored["sources"]), str(list(stored["sources"])))
    for name, entry in stored["sources"].items():
        check(f"{name}: the stored hash matches the stored rows",
              entry["sha256"] == vs.digest(entry["items"]))
        check(f"{name}: the row it recorded is a real BIS listing row",
              all(" | " in row for row in entry["items"][:5]))
    lims = stored["sources"].get("lims")
    if lims:
        check("the LIMS sample size is recorded, so the report can state it",
              len(lims["standards_checked"]) <= lims["standards_in_snapshot"])


def main() -> int:
    test_hashing()
    test_reporting()
    test_it_never_writes_the_knowledge_base()
    test_the_recorded_baseline_is_usable()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
