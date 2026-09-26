"""Build-time ingestion of BIS's own "Products under Compulsory Certification" lists.

This is a ONE-OFF tool, not part of the running application. It reads the two
official BIS pages the knowledge base already cites — Scheme I (ISI Mark) and
Scheme II (Compulsory Registration Scheme) — and appends one record per Indian
Standard that is not in `data/knowledge/indian_standards.json` yet.

Three rules it never breaks:

1. Products BIS shows under a "De-notified from compulsory BIS certification"
   heading are SKIPPED. They are no longer under compulsory certification, so
   listing them as though they were would be false.
2. Every record's text is BIS's own wording from the listing. Nothing is
   paraphrased, inferred from a similar product, or generated.
3. Records already in the knowledge base are left exactly as they are. This
   tool only appends.

Usage:  ./.venv/bin/python scripts/fetch_compulsory_certification.py [--dry-run]
        ./.venv/bin/python scripts/fetch_compulsory_certification.py --notifications

``--notifications`` (Phase 9.1) writes ``data/listing_notifications.json`` instead: for
every listed row, the Notification cell VERBATIM, the orders it names (S.O. / G.S.R.
number, date as printed, Gazette link) and flags for a cell that also records a
rescission, withdrawal, suspension or supersession — joined to the knowledge-base
record transcribed from that row by exact number and product wording, never fuzzily.
It is a data snapshot like data/laboratories.json, not a knowledge-base category,
and it never sets a status: the listing names orders, it does not say they are in force.
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
TARGET = ROOT / "data" / "knowledge" / "indian_standards.json"
NOTIFICATIONS = ROOT / "data" / "listing_notifications.json"

SCHEME_I = (
    "https://www.bis.gov.in/product-certification/products-under-compulsory-"
    "certification/scheme-i-mark-scheme/?lang=en"
)
SCHEME_II = (
    "https://www.bis.gov.in/product-certification/products-under-compulsory-"
    "certification/scheme-ii-registration-scheme/?lang=en"
)
DOC_I = "BIS: Products under Compulsory Certification (Scheme I)"
DOC_II = (
    "BIS: Products under Compulsory Certification (Scheme II) "
    "— Compulsory Registration Scheme"
)

# Words that carry no retrieval value on their own.
STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with", "its", "use", "used", "other", "such", "part", "sec",
    "section", "type", "types", "is", "not", "per", "up", "and/or",
}


# --------------------------------------------------------------------- fetching


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------- parsing


def _cells(row_html: str) -> list[tuple[str, int, int, list[tuple[str, str]]]]:
    """Return (text, colspan, rowspan, links) for every cell in one <tr>.
    ``links`` is each (href, link text) inside the cell, verbatim."""
    out: list[tuple[str, int, int, list[tuple[str, str]]]] = []
    for match in re.finditer(r"<t([dh])\b([^>]*)>(.*?)</t\1>", row_html, re.S):
        text = html.unescape(re.sub(r"<[^>]+>", " ", match.group(3)))
        text = re.sub(r"\s+", " ", text).strip()
        span = re.search(r'colspan="?(\d+)', match.group(2))
        rows = re.search(r'rowspan="?(\d+)', match.group(2))
        links = [(html.unescape(href),
                  re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", label))).strip())
                 for href, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', match.group(3), re.S)]
        out.append((text, int(span.group(1)) if span else 1, int(rows.group(1)) if rows else 1, links))
    return out


def _tables(page: str) -> list[str]:
    return re.findall(r"<table.*?</table>", page, re.S)


def _is_denotified(heading: str | None) -> bool:
    return bool(heading) and "de-notified" in heading.lower().replace("denotified", "de-notified")


def parse_scheme_i(page: str) -> list[dict]:
    """Rows of: Sr No. | IS No. | Product | Notification, under a group heading."""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for table in _tables(page)[:1]:
        heading: str | None = None
        notification: str | None = None
        links: list[tuple[str, str]] = []
        span_left = 0           # rows the current Notification cell still covers
        for row_html in re.findall(r"<tr.*?</tr>", table, re.S):
            cells = _cells(row_html)
            if not cells:
                continue
            texts = [c[0] for c in cells]
            if len(cells) == 1 and cells[0][1] > 1:       # a section heading
                heading = texts[0]
                continue
            if texts[:2] == ["Sr No.", "IS No."]:
                continue
            if len(cells) < 3 or not re.match(r"^\d+\.?$", texts[0]):
                continue
            if len(cells) >= 4:
                notification, links, span_left = texts[3] or None, cells[3][3], cells[3][2]
            elif span_left <= 0:            # no cell covers this row: record none
                notification, links = None, []
            span_left -= 1
            number, product = texts[1].strip(), texts[2].strip()
            if not number or not product or _is_denotified(heading):
                continue
            key = (number, product)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "number": number, "product": product,
                "heading": heading, "notification": notification, "links": links,
            })
    return rows


def parse_scheme_ii(page: str) -> list[dict]:
    """Rows of: Sl. No. | IS No. | Title | Product Category | Notification."""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for table in _tables(page):
        notification: str | None = None
        links: list[tuple[str, str]] = []
        span_left = 0
        for row_html in re.findall(r"<tr.*?</tr>", table, re.S):
            cells = _cells(row_html)
            texts = [c[0] for c in cells]
            if len(cells) < 4 or texts[0] in ("Sl. No.", "Sr No."):
                continue
            if not re.match(r"^\d+\.?$", texts[0]):
                continue
            if len(cells) >= 5:
                notification, links, span_left = texts[4] or None, cells[4][3], cells[4][2]
            elif span_left <= 0:
                notification, links = None, []
            span_left -= 1
            number, title, product = (t.strip() for t in texts[1:4])
            if not number or not product:
                continue
            key = (number, product)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "number": number, "title": title, "product": product,
                "notification": notification, "links": links,
            })
    return rows


# ------------------------------------------------------------------- normalising


def clean_number(raw: str) -> str:
    """'IS: 16192 (Part 1)' -> 'IS 16192 (Part 1)';  '10322 (Part 5)' -> 'IS 10322 (Part 5)'."""
    number = re.sub(r"\s+", " ", raw).strip().rstrip(",;")
    number = re.sub(r"^IS\s*:\s*", "IS ", number)
    if not re.match(r"^IS\b", number, re.I):
        number = "IS " + number
    return re.sub(r"^is\b", "IS", number)


def identity(number: str) -> str:
    """A comparison key that keeps parts and sections distinct."""
    key = number.upper().replace("–", "-").replace("—", "-")
    return re.sub(r"[^A-Z0-9]", "", key)


def slug(text: str, limit: int = 90) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return out[:limit].rstrip("-")


def keywords_for(product: str, extra: list[str]) -> list[str]:
    """Search terms taken ONLY from BIS's own wording. No sector guesses, no synonyms."""
    terms: list[str] = []

    def add(term: str) -> None:
        term = re.sub(r"\s+", " ", term).strip(" -–—,.;:()").lower()
        if term and term not in terms and len(term) > 1:
            terms.append(term)

    add(product)
    for phrase in extra:
        add(phrase)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", product):
        if word.lower() not in STOPWORDS:
            add(word)
    return terms[:24]


# -------------------------------------------------------------------- generating


BODY = (
    'BIS lists this product under compulsory certification, {scheme}, against the '
    'standard "{number}". The BIS list describes the product as: "{described}". '
    "This record carries BIS's own product description from the \"Products under "
    'Compulsory Certification" list, not the verbatim catalogue title of the '
    "standard; the full technical scope was not read from the standard itself. "
    "Being listed means BIS certification applies to the product — it is not a "
    "statement about any particular item."
)


def shorten(text: str, limit: int) -> str:
    """Trim a very long BIS product name for the title. The full wording stays in content."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" -–—,.;:")
    return cut + " …"


def record(number: str, title_product: str, described: str, scheme: str,
           url: str, document: str, reference: str, keywords: list[str],
           verified_on: str) -> dict:
    heading = shorten(title_product, 200 - len(number) - 3)
    return {
        "id": slug(f"{number} {heading}"),
        "title": f"{number} — {heading}",
        "category": "indian_standards",
        "content": BODY.format(scheme=scheme, number=number, described=described),
        "keywords": keywords,
        "standard_number": number,
        "source_organization": "Bureau of Indian Standards (BIS)",
        "source_url": url,
        "document_name": document,
        "reference": reference,
        "verification_status": "verified",
        "last_verified": verified_on,
    }


def build(dry_run: bool = False) -> int:
    existing = json.loads(TARGET.read_text(encoding="utf-8"))
    known = {identity(item["standard_number"]) for item in existing}
    known_ids = {item["id"] for item in existing}
    today = dt.date.today().isoformat()

    print(f"knowledge base: {len(existing)} standards already recorded")
    print("fetching BIS Scheme I …", flush=True)
    rows_i = parse_scheme_i(fetch(SCHEME_I))
    print("fetching BIS Scheme II …", flush=True)
    rows_ii = parse_scheme_ii(fetch(SCHEME_II))
    print(f"  Scheme I : {len(rows_i)} listed products (de-notified rows skipped)")
    print(f"  Scheme II: {len(rows_ii)} listed products")

    added: list[dict] = []

    # --- Scheme I: one product per row.
    for row in rows_i:
        number = clean_number(row["number"])
        key = identity(number)
        if key in known:
            continue
        known.add(key)
        heading = (row["heading"] or "").strip()
        reference = DOC_I + (f"; {heading}" if heading else "")
        item = record(
            number, row["product"], row["product"], "Scheme I (ISI Mark)",
            SCHEME_I, DOC_I, reference,
            keywords_for(row["product"], []), today,
        )
        added.append(item)

    # --- Scheme II: BIS lists several notified products against one standard.
    grouped: dict[str, list[dict]] = {}
    for row in rows_ii:
        grouped.setdefault(clean_number(row["number"]), []).append(row)
    for number, rows in grouped.items():
        key = identity(number)
        if key in known:
            continue
        known.add(key)
        products = []
        for row in rows:
            if row["product"] not in products:
                products.append(row["product"])
        standard_title = rows[0]["title"] or products[0]
        described = "; ".join(products)
        item = record(
            number, standard_title, described,
            "Scheme II (Compulsory Registration Scheme)",
            SCHEME_II, DOC_II, DOC_II,
            keywords_for(standard_title, products), today,
        )
        added.append(item)

    # --- ids must be unique across the whole category.
    for item in added:
        base = item["id"]
        suffix = 2
        while item["id"] in known_ids:
            item["id"] = f"{base}-{suffix}"
            suffix += 1
        known_ids.add(item["id"])

    print(f"\nnew standards to add: {len(added)}")
    print(f"knowledge base would hold: {len(existing) + len(added)}")
    if dry_run:
        print("(dry run — nothing written)")
        return 0

    TARGET.write_text(
        json.dumps(existing + added, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"written: {TARGET.relative_to(ROOT)}")
    return 0


# ------------------------------------------------------- Phase 9.1: Notification column

# "S.O. No. 191(E)", "SO 516(E)", "S.O.1246 (E)", "G.S.R. 759(E)", "GSR-NO-759(E)".
_ORDER_NO = re.compile(r"\b(S\.?\s*O|G\.?\s*S\.?\s*R)\.?\s*(?:No\.?\s*)?(\d+)\s*\(\s*E\s*\)", re.I)
_DATE = (r"(\d{1,2}(?:st|nd|rd|th)?\s*[A-Za-z]+\.?,?\s*\d{4}"
         r"|\d{1,2}[./-]\d{1,2}[./-]\d{4})")
_ORDER_DATE = re.compile(r"\b(?:dated|dt)\.?\s*" + _DATE, re.I)
# A date printed straight after the order number, with or without "dated":
# "(S.O. No. 3858 (E) 27/10/2020)", "(S.O. 2332(E), 24th May, 2023)".
_DATE_AFTER = re.compile(r"\s*[,(]?\s*(?:(?:dated|dt)\.?\s*)?" + _DATE, re.I)
FLAGS = {
    "RESCISSION": re.compile(r"\brescind|\brescission", re.I),
    "WITHDRAWAL": re.compile(r"\bwithdraw", re.I),
    "SUSPENSION": re.compile(r"\bsuspen", re.I),
    "SUPERSESSION": re.compile(r"\bsuperseded\b", re.I),
}


def order_number(text: str) -> str | None:
    """'S.O. No. 191(E)' -> 'S.O. 191(E)'; 'GSR 759(E)' -> 'G.S.R. 759(E)'."""
    found = _ORDER_NO.search(text or "")
    if not found:
        return None
    kind = "S.O." if found.group(1).upper().replace(".", "").replace(" ", "") == "SO" else "G.S.R."
    return f"{kind} {found.group(2)}(E)"


def _date_of(text: str) -> str | None:
    """The date as printed: right after the order number, else after "dated"."""
    found = _ORDER_NO.search(text)
    after = _DATE_AFTER.match(text, found.end()) if found else None
    date = after or _ORDER_DATE.search(text)
    return date.group(1) if date else None


def orders_in(cell: str, links: list[tuple[str, str]]) -> list[dict]:
    """Each order the cell names: one per link (its text verbatim), then any order
    number printed in the cell without a link. Date as printed, or null."""
    out: list[dict] = []
    for href, label in links:
        out.append({"text": label, "url": href, "number": order_number(label), "date": _date_of(label)})
    linked = {o["number"] for o in out if o["number"]}
    for match in _ORDER_NO.finditer(cell):
        number = order_number(match.group(0))
        if number not in linked:
            out.append({"text": match.group(0), "url": None, "number": number,
                        "date": _date_of(cell[match.start():match.end() + 40])})
            linked.add(number)
    return out


_DESCRIBED = re.compile(r'The BIS list describes the product as: "(.+?)"')
_DESCRIPTION = re.compile(r'BIS product description: "(.+?)"')
_QUOTED_NUMBER = re.compile(r'against the standard "([^"]+)"')


def _record_keys(item: dict) -> list[tuple[str, str, str]]:
    """(scheme, listing number, product) for the row(s) a record was transcribed from,
    read from the record's own text. Scheme II records hold several products."""
    doc = item.get("document_name") or ""
    scheme = "II" if "(Scheme II)" in doc else "I" if "(Scheme I)" in doc else None
    if scheme is None:
        return []
    quoted = _QUOTED_NUMBER.search(item["content"])
    number = quoted.group(1) if quoted else item["standard_number"]
    described = _DESCRIBED.search(item["content"]) or _DESCRIPTION.search(item["content"])
    if not described:
        return []
    products = described.group(1).split("; ") if scheme == "II" else [described.group(1)]
    return [(scheme, number, product) for product in products]


def build_notifications() -> int:
    items = json.loads(TARGET.read_text(encoding="utf-8"))
    index: dict[tuple[str, str, str], dict] = {}
    for item in items:
        for key in _record_keys(item):
            index.setdefault(key, item)
    read_on = dt.date.today().isoformat()
    rows_out = []
    for scheme, url, rows in (("I", SCHEME_I, parse_scheme_i(fetch(SCHEME_I))),
                              ("II", SCHEME_II, parse_scheme_ii(fetch(SCHEME_II)))):
        for row in rows:
            cell = row["notification"] or ""
            record = index.get((scheme, clean_number(row["number"]), row["product"]))
            rows_out.append({
                "scheme": scheme, "source_url": url,
                "number_as_printed": row["number"], "product": row["product"],
                "notification": row["notification"],
                "orders": orders_in(cell, row["links"]),
                # The cell's text, each link's text AND each link's file name: BIS
                # often says "rescind" / "suspension" only in the PDF's name.
                "flags": [name for name, rx in FLAGS.items()
                          if rx.search(cell) or any(rx.search(label) or rx.search(href)
                                                    for href, label in row["links"])],
                "record_id": record["id"] if record else None,
                "kb_standard_number": record["standard_number"] if record else None,
            })
    joined = [r for r in rows_out if r["record_id"]]
    NOTIFICATIONS.write_text(json.dumps({
        "note": ("Notification column of BIS's 'Products under Compulsory Certification' Scheme I "
                 "and Scheme II pages, transcribed verbatim by scripts/fetch_compulsory_certification.py "
                 "--notifications. The listing NAMES orders; it does not state that any order is in "
                 "force. A row joins a knowledge-base record only on the exact number and product "
                 "wording that record was transcribed from."),
        "read_on": read_on, "rows": rows_out,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"rows: {len(rows_out)} (Scheme I {sum(r['scheme'] == 'I' for r in rows_out)}, "
          f"Scheme II {sum(r['scheme'] == 'II' for r in rows_out)}); joined {len(joined)}; "
          f"records with a listing order: {len({r['record_id'] for r in joined if r['orders']})}")
    print(f"written: {NOTIFICATIONS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--notifications", action="store_true",
                        help="write data/listing_notifications.json (Phase 9.1)")
    args = parser.parse_args()
    sys.exit(build_notifications() if args.notifications else build(args.dry_run))
