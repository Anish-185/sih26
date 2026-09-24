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


def _cells(row_html: str) -> list[tuple[str, int]]:
    """Return (text, colspan) for every cell in one <tr>."""
    out: list[tuple[str, int]] = []
    for match in re.finditer(r"<t([dh])\b([^>]*)>(.*?)</t\1>", row_html, re.S):
        text = html.unescape(re.sub(r"<[^>]+>", " ", match.group(3)))
        text = re.sub(r"\s+", " ", text).strip()
        span = re.search(r'colspan="(\d+)"', match.group(2))
        out.append((text, int(span.group(1)) if span else 1))
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
            if len(cells) >= 4 and texts[3]:
                notification = texts[3]
            number, product = texts[1].strip(), texts[2].strip()
            if not number or not product or _is_denotified(heading):
                continue
            key = (number, product)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "number": number, "product": product,
                "heading": heading, "notification": notification,
            })
    return rows


def parse_scheme_ii(page: str) -> list[dict]:
    """Rows of: Sl. No. | IS No. | Title | Product Category | Notification."""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for table in _tables(page):
        notification: str | None = None
        for row_html in re.findall(r"<tr.*?</tr>", table, re.S):
            cells = _cells(row_html)
            texts = [c[0] for c in cells]
            if len(cells) < 4 or texts[0] in ("Sl. No.", "Sr No."):
                continue
            if not re.match(r"^\d+\.?$", texts[0]):
                continue
            if len(cells) >= 5 and texts[4]:
                notification = texts[4]
            number, title, product = (t.strip() for t in texts[1:4])
            if not number or not product:
                continue
            key = (number, product)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "number": number, "title": title, "product": product,
                "notification": notification,
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    sys.exit(build(parser.parse_args().dry_run))
