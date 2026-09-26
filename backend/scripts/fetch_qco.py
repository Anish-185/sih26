"""One-off ingestion: BIS "Upcoming QCOs" table -> data/knowledge/quality_control_orders.json.

This is a BUILD-TIME tool, not application code. MetrIQ never calls bis.gov.in at
runtime: the application reads the snapshot this script writes. Standard library
only — urllib + regex, the same pattern as fetch_lims_laboratories.py and
fetch_compulsory_certification.py.

Source (official, public, no login):

    https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/?lang=en

    Sr. No. | Ministry/Department | Product | Indian Standard | Enforcement date

Every cell is transcribed VERBATIM — the IS number exactly as printed (with or
without "IS ", with its own spacing), the enforcement date exactly as printed. Nothing
is corrected: an IS number that does not match MetrIQ's knowledge base is reported as
a mismatch by app/qco.py, never fixed here.

What this table is and is not: it lists orders DUE FOR IMPLEMENTATION, each with a
future enforcement date as of the day it was read. It does not state that any order is
in force, so no record written here can ever make MetrIQ say one is. One row (IS 302
(Part 1)) spans 90 further product rows beneath it; those product names are kept, in
BIS's order, inside that row's record. Any link a row gives is recorded, never
fetched — on the snapshot read for this phase no row gave one.

Run:

    ./.venv/bin/python scripts/fetch_qco.py            # fetch and write
    ./.venv/bin/python scripts/fetch_qco.py --dry-run  # fetch and print only
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGET = ROOT / "data" / "knowledge" / "quality_control_orders.json"

UPCOMING = "https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/?lang=en"
DOC_UPCOMING = "BIS: Upcoming QCOs – notified and due for implementation"
HEADER = ["Sr. No.", "Ministry/ Department", "Product", "Indian Standard", "Enforcement date"]


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def _text(cell_html: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell_html))).strip()


def parse_upcoming(page: str) -> list[dict]:
    """One dict per numbered row. A single-cell row beneath a rowspan row is one more
    product of that row (BIS's IS 302 (Part 1) row lists 90 appliances this way)."""
    tables = re.findall(r"<table.*?</table>", page, re.S)
    if len(tables) != 1:
        raise ValueError(f"expected one table on the QCO page, found {len(tables)}")
    rows: list[dict] = []
    header_seen = False
    for row_html in re.findall(r"<tr.*?</tr>", tables[0], re.S):
        cells = [_text(c) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, re.S)]
        links = re.findall(r'<a[^>]+href="([^"]+)"', row_html)
        if cells == HEADER:
            header_seen = True
            continue
        if len(cells) == 5 and re.fullmatch(r"\d+", cells[0]):
            sr, ministry, product, number, date = cells
            rows.append({"sr": sr, "ministry": ministry, "product": product, "number": number,
                         "date": date, "listed_products": [], "links": links})
        elif len(cells) == 1 and cells[0] and rows:
            rows[-1]["listed_products"].append(cells[0])
            rows[-1]["links"] += links
        elif any(cells):
            raise ValueError(f"unrecognised row on the QCO page: {cells}")
    if not header_seen:
        raise ValueError("the QCO table header changed; re-check the page before ingesting")
    return rows


def slug(text: str, limit: int = 60) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:limit].strip("-")


def record(row: dict, read_on: str) -> dict:
    lines = [
        f"Sr. No.: {row['sr']}",
        f"Ministry/Department: {row['ministry']}",
        f"Product: {row['product']}",
        f"Indian Standard: {row['number']}",
        f"Enforcement date: {row['date']}",
    ]
    if row["listed_products"]:
        lines.append("Products listed under this row: " + "; ".join(row["listed_products"]))
    lines.append("Link given for this row: " + (" ".join(row["links"]) or "none"))
    note = (f"MetrIQ note: this is one row of BIS's table \"Upcoming QCOs – notified and due "
            f"for implementation\", transcribed verbatim on {read_on}. The Quality Control "
            f"Order is issued by the ministry or department named; BIS publishes the table. "
            f"The table lists orders due for implementation — it does not state that an order "
            f"is in force, and enforcement dates are often deferred.")
    title = f"Quality Control Order (upcoming): {row['product']}"
    return {
        "id": f"qco-upcoming-{row['sr']}-{slug(row['product'])}",
        "title": title if len(title) <= 200 else title[:197] + "...",
        "category": "quality_control_orders",
        "content": "\n".join(lines) + "\n\n" + note,
        "standard_number": row["number"],
        "source_authority": "QUALITY_CONTROL_ORDER",
        "source_organization": (f"Bureau of Indian Standards (BIS), publisher of the table; "
                                f"order issued by {row['ministry']}"),
        "source_url": UPCOMING,
        "document_name": DOC_UPCOMING,
        "reference": f"Sr. No. {row['sr']}",
        "verification_status": "verified",
        "last_verified": read_on,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    read_on = dt.date.today().isoformat()
    rows = parse_upcoming(fetch(UPCOMING))
    records = [record(row, read_on) for row in rows]
    print(f"{len(rows)} rows; {sum(len(r['listed_products']) for r in rows)} listed sub-products; "
          f"{sum(bool(r['links']) for r in rows)} rows give a link")
    if args.dry_run:
        for r in rows:
            print(f"  {r['sr']:>3}  {r['number']:<42} {r['date']:<20} {r['product'][:50]}")
        return 0
    TARGET.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
    print(f"written: {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
