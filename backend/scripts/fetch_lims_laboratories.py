"""One-off ingestion: BIS LIMS "IS-wise test facilities" -> data/laboratories.json.

This is a BUILD-TIME tool, not application code. MetrIQ never calls LIMS at
runtime: the application reads the snapshot this script writes. Standard library
only — no scraping framework, no new dependency.

Source (official, public, no login):

    https://lims.bis.gov.in/home/search_is_number/

BIS's own Laboratory Information Management System answers "which BIS,
recognised or empanelled laboratory can test against this Indian Standard?".
That IS the standard -> laboratory relationship; nothing here is inferred.

What is recorded, verbatim and only when present: the laboratory's name as BIS
writes it, its OSL code, the Indian Standard as LIMS states it, the product
description LIMS states, the recognition validity date, and LIMS's remark. What
is NOT recorded: anything the page does not contain — no address, no phone, no
email, no accreditation claim, no operational status. Testing charges are
deliberately skipped: they change often and are not needed to find a laboratory.

Run:

    ./.venv/bin/python scripts/fetch_lims_laboratories.py            # all KB standards
    ./.venv/bin/python scripts/fetch_lims_laboratories.py 367 14543  # specific ones
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval.engine import SearchEngine  # noqa: E402

BASE = "https://lims.bis.gov.in/home/search_is_number/"
SOURCE_PAGE = "https://www.bis.gov.in/laboratorys/list-of-bis-recognized-lab/?lang=en"
OUT = Path(__file__).resolve().parents[2] / "data" / "laboratories.json"
DELAY = 1.5  # be a polite guest on a government portal
TIMEOUT = 60

EXPECTED_HEADER = ["S.No.", "Lab Name", "Osl Code", "Indian Standard No.", "Product"]


class _Rows(HTMLParser):
    """Top-level rows of the OUTERMOST table. The charges column nests its own
    table, so depth tracking is what keeps a sub-row from becoming a lab."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._celldepth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
        elif tag == "tr" and self.depth == 1:
            self._row = []
        elif tag in ("td", "th"):
            if self.depth == 1 and self._celldepth == 0 and self._row is not None:
                self._cell = []
            if self._cell is not None:
                self._celldepth += 1

    def handle_endtag(self, tag):
        if tag == "table":
            self.depth -= 1
        elif tag in ("td", "th") and self._cell is not None:
            self._celldepth -= 1
            if self._celldepth == 0 and self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()))
                self._cell = None
        elif tag == "tr" and self.depth == 1 and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def fetch(doc_no: str) -> list[list[str]]:
    query = urllib.parse.urlencode({
        "lab__lab_name__icontains": "",
        "is_number__doc_no": doc_no,
        "is_number__part": "",
        "is_number__section": "",
        "is_number__year": "",
        "is_title": "",
    })
    request = urllib.request.Request(f"{BASE}?{query}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read().decode("utf-8", "replace")
    parser = _Rows()
    parser.feed(body)
    return parser.rows


# "TUV Rheinland (India) Pvt. Ltd (6126126), Bengaluru" -> city "Bengaluru".
# Only the trailing comma-separated fragment, and only when it looks like a
# place name. Anything else leaves the city unset rather than guessing.
_CITY = re.compile(r",\s*([A-Za-z][A-Za-z .\-]{2,40})$")
_CODE_IN_NAME = re.compile(r"\s*\((\d{5,10})\)")


def parse_rows(rows: list[list[str]], doc_no: str, retrieved: str) -> list[dict]:
    if not rows:
        return []
    header = rows[0]
    if header[:5] != EXPECTED_HEADER:
        raise SystemExit(f"LIMS table layout changed for IS {doc_no}: {header[:5]}")
    index = {name: i for i, name in enumerate(header)}

    out: list[dict] = []
    for row in rows[1:]:
        if len(row) != len(header) or not row[0].strip().isdigit():
            continue  # not a laboratory row; never guessed at

        def cell(name: str) -> str:
            value = row[index[name]].strip() if name in index else ""
            return "" if value in {"-", "--", "—"} else value

        name = cell("Lab Name")
        standard = cell("Indian Standard No.")
        if not name or not standard:
            continue  # the two fields that make a record meaningful

        city_match = _CITY.search(name)
        record = {
            "lab_name": name,
            "osl_code": cell("Osl Code"),
            "city": city_match.group(1).strip() if city_match else None,
            "standard_as_listed": standard,
            "product_as_listed": cell("Product"),
            "grade_or_type": cell("Grade / Type / Size / Designation etc.") or None,
            "validity_date": cell("Validity Date") or None,
            "remark": cell("Remark") or None,
            "source_url": BASE,
            "source_organization": "Bureau of Indian Standards (BIS)",
            "document_name": "BIS LIMS: IS-wise test facilities in BIS / recognised / empanelled laboratories",
            "retrieved_on": retrieved,
        }
        out.append(record)
    return out


def main(argv: list[str]) -> int:
    retrieved = date.today().isoformat()
    if argv:
        doc_numbers = argv
    else:
        engine = SearchEngine()
        numbers: list[str] = []
        for item in engine.items:
            if item.category != "indian_standards" or not item.standard_number:
                continue
            match = re.search(r"(\d{2,6})", item.standard_number)
            if match and match.group(1) not in numbers:
                numbers.append(match.group(1))
        doc_numbers = numbers

    records: list[dict] = []
    empty: list[str] = []
    for i, doc_no in enumerate(doc_numbers, 1):
        try:
            found = parse_rows(fetch(doc_no), doc_no, retrieved)
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 — report and continue; never invent a row
            print(f"  [{i}/{len(doc_numbers)}] IS {doc_no}: FETCH FAILED ({exc.__class__.__name__})")
            continue
        if found:
            records.extend(found)
        else:
            empty.append(doc_no)
        print(f"  [{i}/{len(doc_numbers)}] IS {doc_no}: {len(found)} laboratory record(s)")
        time.sleep(DELAY)

    payload = {
        "source": {
            "organization": "Bureau of Indian Standards (BIS)",
            "portal": "BIS Laboratory Information Management System (LIMS)",
            "url": BASE,
            "listing_page": SOURCE_PAGE,
            "retrieved_on": retrieved,
            "note": (
                "Snapshot of BIS's own IS-wise test-facility listing, taken on the date above. "
                "It is not a live feed. MetrIQ does not independently establish a laboratory's "
                "current recognition, scope, availability or operational status."
            ),
        },
        "laboratories": records,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{len(records)} records across {len({r['lab_name'] for r in records})} laboratories "
          f"and {len({r['standard_as_listed'] for r in records})} standards -> {OUT}")
    print(f"standards with no LIMS facility listed: {len(empty)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
