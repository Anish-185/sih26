"""Record every reaffirmation statement MetrIQ can find for the editions it cites.

    ./.venv/bin/python scripts/fetch_reaffirmations.py

A BUILD-TIME tool (stdlib only), like fetch_standard_titles.py, whose index and
on-disk cache it reuses. The application never calls BIS or the archive at
runtime. It annotates data/standard_archive_index.json in place and adds nothing
else: no status is computed here (app/standard_currency.py does that), and the
knowledge base is never touched.

Two sources of the same fact — "this edition was reaffirmed in YYYY":

1. BIS's own catalogue row carries `reaffirm_year`. Phase 4's cache already holds
   those rows, so this costs no request. "0" is BIS stating nothing, not "never".
2. The document's own cover page. The Public.Resource.Org mirror holds scans whose
   first page prints "Indian Standard (Reaffirmed 2021)". Only the first 4 KB of the
   OCR text is fetched (an HTTP Range request) and only a statement on that page is
   accepted. The mirror is third-party and is labelled so wherever this is shown.

Only the edition MetrIQ's record CITES is looked up: a reaffirmation of some other
edition says nothing about ours.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

import fetch_standard_titles as ft

FIRST_PAGE_BYTES = 4000
# Only the phrase itself is quoted: the rest of that OCR line is often the Hindi
# half of the bilingual cover read as Latin noise ("TRATA WAh (Reaffirmed 2018)").
_REAFFIRMED = re.compile(r"\(?\s*reaffirmed\s*[-–:]?\s*((?:19|20)\d{2})\s*\)?", re.I)
_CITED_YEAR = re.compile(r":\s*((?:19|20)\d{2})\s*$")


def _get(url: str, first_bytes: int | None = None) -> bytes | None:
    headers = {"User-Agent": ft.BROWSER}
    if first_bytes:
        headers["Range"] = f"bytes=0-{first_bytes}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                    timeout=ft.TIMEOUT) as response:
            return response.read()
    except Exception:
        return None


def _first_page(identifier: str) -> dict | None:
    """The cover-page text of one mirror item, or None when it has none."""
    raw = _get(f"https://archive.org/metadata/{identifier}/files")
    if raw is None:
        return None          # not cached: a transient failure is retried next run
    files = json.loads(raw).get("result") or []
    # Amendments are filed as z<number>Amd... — the edition's own text is not.
    texts = [f["name"] for f in files
             if f["name"].endswith("_djvu.txt") and not f["name"].startswith("z")]
    if not texts:
        return {"identifier": identifier, "text": None}
    url = f"https://archive.org/download/{identifier}/{urllib.parse.quote(texts[0])}"
    body = _get(url, FIRST_PAGE_BYTES)
    if body is None:
        return None
    return {"identifier": identifier, "url": url,
            "text": body.decode("utf-8", "replace")[:FIRST_PAGE_BYTES]}


def cited_editions() -> dict[str, int]:
    """index key -> the edition year MetrIQ's knowledge-base record cites."""
    index = json.loads(ft.INDEX.read_text())["standards"]
    out: dict[str, int] = {}
    for record in json.loads(ft.KB.read_text()):
        number = record.get("standard_number") or ""
        year = _CITED_YEAR.search(number)
        key = number if number in index else _CITED_YEAR.sub("", number).strip()
        if year and key in index:
            out[key] = int(year.group(1))
    return out


def annotate() -> dict:
    index = json.loads(ft.INDEX.read_text())
    cited = cited_editions()
    found = {"bis_catalogue": 0, "archive_document": 0, "documents_read": 0}
    for key, entry in index["standards"].items():
        entry.pop("reaffirmation", None)
        year = cited.get(key)
        if entry["method"] == "NOT_FOUND" or year is None:
            continue

        # 1. BIS's own catalogue row (Phase 4 cache; the catalogue is never called).
        if entry["source_route"] == "bis":
            bis = ft.resolve_bis(entry["parsed"], catalogue=None)
            by_id = {e["identifier"]: e.get("reaffirmed") for e in bis["editions"]}
            for edition in entry["editions"]:
                edition["reaffirmed"] = by_id.get(edition["identifier"])
            stated = [e for e in entry["editions"] if e["year"] == year and e.get("reaffirmed")]
            if stated:
                entry["reaffirmation"] = {
                    "year": stated[0]["reaffirmed"], "edition_year": year,
                    "source": "bis_catalogue",
                    "quote": f"reaffirm_year: {stated[0]['reaffirmed']}",
                    "url": index["sources"]["bis"]["url"]}
                found["bis_catalogue"] += 1
                continue

        # 2. The cited edition's own cover page, from the mirror.
        for stem in ft.archive_identifiers(entry["parsed"]):
            identifier = f"{stem}.{year}"
            page = ft.cached(f"doc-{identifier}", lambda: _first_page(identifier))
            if not page or not page.get("text"):
                continue
            found["documents_read"] += 1
            # A cover can list several reaffirmations; the latest one is the statement.
            matches = [m for m in _REAFFIRMED.finditer(page["text"]) if int(m.group(1)) >= year]
            match = max(matches, key=lambda m: int(m.group(1)), default=None)
            if match:
                entry["reaffirmation"] = {
                    "year": int(match.group(1)), "edition_year": year,
                    "source": "archive_document",
                    "quote": " ".join(match.group(0).split()),
                    "url": ft.ARCHIVE_ITEM + identifier}
                found["archive_document"] += 1
            break
    ft.INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    return found


if __name__ == "__main__":
    counts = annotate()
    print(f"  cover pages read from the mirror : {counts['documents_read']}")
    print(f"  reaffirmed, per BIS's catalogue  : {counts['bis_catalogue']}")
    print(f"  reaffirmed, per the cover page   : {counts['archive_document']}")
    sys.exit(0)
