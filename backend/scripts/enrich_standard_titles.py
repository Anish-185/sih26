"""Add the real catalogue identity to each standards record, without losing anything.

    ./.venv/bin/python scripts/enrich_standard_titles.py [--dry-run]

Reads `data/standard_archive_index.json` (written by fetch_standard_titles.py) and
enriches `data/knowledge/indian_standards.json` in place. A BUILD-TIME tool.

WHAT IT ADDS, AND WHAT IT REFUSES TO TOUCH
==========================================
Every existing record already carries BIS's own product description from a
"Products under Compulsory Certification" listing. That description and the
catalogue title are BOTH true and they say DIFFERENT things: the listing names
the notified PRODUCT, the catalogue names the STANDARD. So the catalogue title is
ADDED, never substituted, and the record's existing sentence about the listing's
wording is rewritten to stay honest now that both are present.

  * `content` gains a labelled "Catalogue title" sentence naming the source route.
  * `content` gains a provenance line saying which route the title came from.
    Mirrored text is never presented as coming from bis.gov.in.
  * `source_url` is UNCHANGED — the BIS listing page stays the primary source.
  * The year is filled into `standard_number` ONLY when the source offers exactly
    one edition. With several editions MetrIQ does not choose: the number stays as
    it is and the editions live in the index for a later phase.
  * `title` is capped at the schema's 200 characters; the full catalogue title
    always goes into `content`, so nothing is lost by truncating.
  * A title the source returned garbled is recorded and labelled as unverified
    text, never repaired.

Nothing verified is deleted or overwritten. Re-running is safe: a record that
already carries the catalogue block is skipped.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
KB = ROOT / "data" / "knowledge" / "indian_standards.json"
INDEX = ROOT / "data" / "standard_archive_index.json"

MARKER = "Catalogue title"
TITLE_MAX = 200

# The sentence every listing-derived record carries today. It says the record has
# only the listing's wording — which stops being true once the catalogue title is
# added, so it is replaced rather than left to mislead.
OLD_CAVEAT = ("This record carries BIS's own product description from the \"Products "
              "under Compulsory Certification\" list, not the verbatim catalogue title "
              "of the standard; the full technical scope was not read from the standard "
              "itself.")
NEW_CAVEAT = ("This record carries BIS's own product description from the \"Products "
              "under Compulsory Certification\" list AND the standard's catalogue title, "
              "which are different things: the listing names the notified product, the "
              "catalogue names the standard. The full technical scope was not read from "
              "the standard itself.")

ROUTE_PROVENANCE = {
    "bis": ("Catalogue title source: BIS's own Know Your Standards catalogue "
            "(services.bis.gov.in), read without a login. The standard document itself "
            "is sold by BIS and its text was not obtained."),
    "archive": ("Catalogue title source: the Public.Resource.Org public-safety MIRROR of "
                "the Indian Standards on the Internet Archive ({identifier}) — a "
                "third-party mirror, NOT a BIS publication. BIS sells these standards."),
}


def enrich(dry_run: bool = False) -> int:
    index = json.loads(INDEX.read_text())
    records = json.loads(KB.read_text())
    entries = index["standards"]

    added = skipped = years_filled = refused = garbled = missing = 0
    refusals: list[tuple[str, list[int]]] = []

    for record in records:
        number = record.get("standard_number")
        entry = entries.get(number) if number else None
        if not entry or entry["method"] == "NOT_FOUND" or not entry.get("title"):
            missing += 1
            continue
        if MARKER in record["content"]:
            skipped += 1
            continue

        title = entry["title"].strip()
        route = entry.get("source_route", index.get("source_route", "bis"))
        suspect = entry.get("title_suspect")

        label = (f"{MARKER} (recorded as the source returned it; the text looks damaged "
                 f"and has NOT been corrected)" if suspect else MARKER)
        provenance = ROUTE_PROVENANCE[route].format(identifier=entry.get("identifier") or "")

        block = f' {label}: "{title}". {provenance}'
        content = record["content"]
        if OLD_CAVEAT in content:
            content = content.replace(OLD_CAVEAT, NEW_CAVEAT, 1)
        record["content"] = content.rstrip() + block
        added += 1
        garbled += bool(suspect)

        # Fill the year only when the source is unambiguous.
        parsed_year = entry["parsed"].get("year")
        years = sorted({e["year"] for e in entry["editions"] if e.get("year")})
        if parsed_year is None and len(years) == 1:
            record["standard_number"] = _with_year(number, years[0])
            record["title"] = _retitle(record["title"], number, record["standard_number"])
            years_filled += 1
        elif parsed_year is None and len(years) > 1:
            refused += 1
            refusals.append((number, years))

        if len(record["title"]) > TITLE_MAX:
            record["title"] = record["title"][:TITLE_MAX - 1].rstrip() + "…"

    print(f"  catalogue titles added : {added}")
    print(f"  already enriched       : {skipped}")
    print(f"  no catalogue entry     : {missing}")
    print(f"  years filled in        : {years_filled}")
    print(f"  years REFUSED (several editions): {refused}")
    print(f"  titles flagged garbled : {garbled}")
    if refusals:
        print("\n  refused to choose an edition for:")
        for number, years in refusals[:20]:
            print(f"    {number:<34} editions {years}")
        if len(refusals) > 20:
            print(f"    … and {len(refusals) - 20} more")

    if dry_run:
        print("\n  (dry run — nothing written)")
        return 0
    KB.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    print(f"\n  written: {KB.relative_to(ROOT)}")
    return 0


def _with_year(number: str, year: int) -> str:
    """"IS 1180 (Part 1)" + 2014 -> "IS 1180 (Part 1):2014"."""
    return f"{number.rstrip().rstrip(':')}:{year}"


def _retitle(title: str, old_number: str, new_number: str) -> str:
    """Keep the record title in step when the number gains a year."""
    return title.replace(old_number, new_number, 1) if old_number in title else title


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    sys.exit(enrich(parser.parse_args().dry_run))
