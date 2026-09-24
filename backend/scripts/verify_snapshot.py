"""Has BIS changed the pages MetrIQ's knowledge base was built from?

MetrIQ's evidence is a dated SNAPSHOT of official BIS pages, not a live feed —
the application never calls bis.gov.in or LIMS at runtime. That is deliberate:
a demo does not depend on a government portal being up, and every answer can be
traced to a fixed, reviewable record. The cost of a snapshot is drift, and this
script is the answer to it:

    ./.venv/bin/python scripts/verify_snapshot.py

It re-fetches each ingested source page, parses it with the SAME parsers that
built the knowledge base, hashes the parsed rows with sha256, and REPORTS the
difference against the stored baseline — which rows appeared, which disappeared,
and whether anything moved at all.

It NEVER writes to the knowledge base. Drift is reported; a human reads the
report and decides what, if anything, to re-ingest. `--record` updates the
stored baseline and nothing else.

    --record            store the current state as the new baseline
    --source NAME       check one source only (scheme-i, scheme-ii, lims)
    --lims-standards N  how many standards to re-query on LIMS (default 5, 0 skips)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fetch_compulsory_certification as cc  # noqa: E402
import fetch_lims_laboratories as lims  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASELINE = ROOT / "data" / "source_snapshots.json"
LABS = ROOT / "data" / "laboratories.json"


def digest(items: list[str]) -> str:
    """sha256 over the parsed rows — not the raw HTML, which changes on every
    request (nonces, banners, build ids) and would report drift that isn't."""
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ probing


def probe_scheme(name: str, url: str, parse) -> dict:
    rows = parse(cc.fetch(url))
    items = sorted(f"{cc.clean_number(r['number'])} | {r['product']}" for r in rows)
    return {"url": url, "items": items, "sha256": digest(items)}


def probe_lims(count: int) -> dict:
    """Re-query LIMS for the first `count` standards the stored snapshot holds.

    LIMS answers one standard per request, so checking all of them is a long
    crawl. The report states exactly how many were checked — a sample is only
    honest if its size is on the page.
    """
    snapshot = json.loads(LABS.read_text())
    # The document number only — the first digit run. "IS 269:2015" -> "269",
    # matching how fetch_lims_laboratories.py queries LIMS.
    numbers: list[str] = []
    for record in snapshot["laboratories"]:
        found = re.search(r"(\d{2,6})", record["standard_as_listed"])
        if found and found.group(1) not in numbers:
            numbers.append(found.group(1))
    checked = numbers[:count]

    items: list[str] = []
    for doc_no in checked:
        for row in lims.parse_rows(lims.fetch(doc_no), doc_no, "probe"):
            items.append(f"IS {doc_no} | {row['standard_as_listed']} | {row['lab_name']}")
    items.sort()
    return {
        "url": lims.BASE,
        "items": items,
        "sha256": digest(items),
        "standards_checked": checked,
        "standards_in_snapshot": len(numbers),
    }


PROBES = {
    "scheme-i": lambda a: probe_scheme("scheme-i", cc.SCHEME_I, cc.parse_scheme_i),
    "scheme-ii": lambda a: probe_scheme("scheme-ii", cc.SCHEME_II, cc.parse_scheme_ii),
    "lims": lambda a: probe_lims(a.lims_standards),
}


# ----------------------------------------------------------------- reporting


def report(name: str, stored: dict | None, current: dict) -> bool:
    """Print one source's drift. Returns True when it changed."""
    print(f"\n  {name}")
    print(f"    {current['url']}")
    if "standards_checked" in current:
        print(f"    checked {len(current['standards_checked'])} of "
              f"{current['standards_in_snapshot']} standards in the stored snapshot "
              f"({', '.join('IS ' + n for n in current['standards_checked']) or 'none'})")
    print(f"    rows now: {len(current['items'])}    sha256: {current['sha256'][:16]}…")

    if stored is None:
        print("    NO BASELINE — run with --record to store this as the baseline.")
        return False

    print(f"    baseline: {len(stored['items'])} rows, recorded {stored['recorded_on']}, "
          f"sha256 {stored['sha256'][:16]}…")
    if stored["sha256"] == current["sha256"]:
        print("    UNCHANGED")
        return False

    before, after = set(stored["items"]), set(current["items"])
    added, removed = sorted(after - before), sorted(before - after)
    print(f"    CHANGED — {len(added)} added, {len(removed)} removed")
    for label, rows in (("+", added), ("-", removed)):
        for row in rows[:20]:
            print(f"      {label} {row}")
        if len(rows) > 20:
            print(f"      … and {len(rows) - 20} more")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true",
                        help="store the current state as the new baseline")
    parser.add_argument("--source", choices=sorted(PROBES), action="append",
                        help="check one source only (repeatable)")
    parser.add_argument("--lims-standards", type=int, default=5,
                        help="how many standards to re-query on LIMS (0 skips LIMS)")
    args = parser.parse_args(argv)

    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {"sources": {}}
    names = args.source or sorted(PROBES)
    if args.lims_standards <= 0 and not args.source:
        names = [n for n in names if n != "lims"]

    print("MetrIQ snapshot drift check")
    print("BIS pages the knowledge base was built from, re-fetched and compared.")
    print("This reports drift. It never updates the knowledge base.")

    changed, failed = [], []
    for name in names:
        try:
            current = PROBES[name](args)
        except Exception as exc:  # noqa: BLE001 — a portal being down is not drift
            failed.append(name)
            print(f"\n  {name}\n    COULD NOT BE CHECKED: {exc.__class__.__name__}: {exc}")
            continue
        if report(name, baseline["sources"].get(name), current):
            changed.append(name)
        if args.record:
            current["recorded_on"] = dt.date.today().isoformat()
            baseline["sources"][name] = current

    print("\n  ---")
    print(f"  checked {len(names) - len(failed)} source(s); "
          f"{len(changed)} changed, {len(failed)} unreachable")
    if changed:
        print("  A human decides what to re-ingest. Nothing was written to the "
              "knowledge base.")

    if args.record:
        baseline["note"] = (
            "Baseline hashes of the official BIS pages the MetrIQ knowledge base was "
            "built from. Written only by scripts/verify_snapshot.py --record. The "
            "application never reads this file and never fetches these pages at runtime."
        )
        BASELINE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n")
        print(f"  baseline recorded: {BASELINE.relative_to(ROOT)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
