"""Merge the BIS and archive resolutions into one index: BIS primary, archive fallback.

    ./.venv/bin/python scripts/merge_standard_index.py BIS.json ARCHIVE.json [--out PATH]

BIS's own catalogue is the primary source and always wins. The Public.Resource.Org
mirror is consulted ONLY for standards BIS's catalogue did not resolve, and every
entry keeps its own `source_route`, so a mirrored title can never be mistaken for
a BIS one downstream.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
INDEX = ROOT / "data" / "standard_archive_index.json"


def merge(bis_path: pathlib.Path, archive_path: pathlib.Path, out: pathlib.Path) -> int:
    bis = json.loads(bis_path.read_text())
    archive = json.loads(archive_path.read_text())

    standards: dict[str, dict] = {}
    filled = 0
    for number, entry in bis["standards"].items():
        fallback = archive["standards"].get(number)
        if entry["method"] == "NOT_FOUND" and fallback and fallback["method"] != "NOT_FOUND":
            entry = dict(fallback)
            entry["fallback_reason"] = (
                "BIS's own catalogue did not resolve this number; the title below comes "
                "from the Public.Resource.Org mirror and is labelled as such everywhere."
            )
            filled += 1
        standards[number] = entry

    counts = {"EXACT": 0, "WILDCARD": 0, "NOT_FOUND": 0}
    routes = {"bis": 0, "archive": 0}
    for entry in standards.values():
        counts[entry["method"]] += 1
        if entry["method"] != "NOT_FOUND":
            routes[entry["source_route"]] += 1

    merged = {
        "generated_on": dt.date.today().isoformat(),
        "source_route": "bis+archive",
        "sources": {"bis": bis["source"], "archive": archive["source"]},
        "policy": ("BIS's own Know Your Standards catalogue is the primary source and "
                   "always wins. The Public.Resource.Org mirror is used only where BIS's "
                   "catalogue did not resolve the number, and every entry records the "
                   "route its title came from. Mirrored text is never presented as a BIS "
                   "publication."),
        "counts": counts,
        "resolved_by_route": routes,
        "filled_from_archive": filled,
        "total": len(standards),
        "standards": standards,
    }
    out.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")

    print(f"  {len(standards)} standards")
    for method in ("EXACT", "WILDCARD", "NOT_FOUND"):
        print(f"    {method:<10} {counts[method]:4}  ({counts[method] / len(standards) * 100:.1f}%)")
    print(f"  resolved by BIS catalogue : {routes['bis']}")
    print(f"  resolved by archive mirror: {routes['archive']} (BIS could not)")
    print(f"  written: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bis")
    parser.add_argument("archive")
    parser.add_argument("--out", default=str(INDEX))
    args = parser.parse_args()
    sys.exit(merge(pathlib.Path(args.bis), pathlib.Path(args.archive),
                   pathlib.Path(args.out)))
