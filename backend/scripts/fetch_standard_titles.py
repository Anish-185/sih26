"""Resolve every Indian Standard in the knowledge base to its real catalogue identity.

    ./.venv/bin/python scripts/fetch_standard_titles.py --source bis
    ./.venv/bin/python scripts/fetch_standard_titles.py --source archive
    ./.venv/bin/python scripts/fetch_standard_titles.py --source bis --enrich

A BUILD-TIME tool, not application code. The running application never calls
either source; it reads what this writes. Standard library only.

SOURCE PROVENANCE — WHY THIS IS A PARAMETER AND NOT A CONSTANT
==============================================================
BIS SELLS these standards (the documents carry a Price Group), and the ministry
that owns BIS proposed this problem statement. So the route the text came from is
recorded on every record and shown in the UI. Mirrored text is NEVER presented as
though it came from bis.gov.in.

  --source bis      BIS's own Know Your Standards catalogue on services.bis.gov.in.
                    OFFICIAL and PRIMARY. Measured: the catalogue search endpoint
                    answers anonymously — no login, no credentials — and returns
                    structured records (number, part, section, year, full title,
                    identical ISO/IEC standard). It is a live search of BIS's own
                    catalogue, so it is also CURRENT: it shows IS 14543:2024 where
                    our listing-derived record says 2016.
                    WHERE IT STOPS: at the metadata. Downloading the document TEXT
                    from BIS requires a logged-in session, and this tool does not
                    attempt it. Titles, parts, years and editions do not.

  --source archive  Public.Resource.Org's public-safety mirror on the Internet
                    Archive, identifiers gov.in.is.* (22,025 items, verified).
                    A FALLBACK, and disclosed as one wherever it is used.

Neither route's text replaces BIS's own product description in a record. Both are
true and they say different things: the listing describes the notified PRODUCT,
the catalogue title names the STANDARD.

WHAT IT REFUSES TO DO
=====================
Where our standard_number carries no year and the source offers MORE THAN ONE
edition, the year is NOT filled in. Picking one would be inventing a fact about
which edition applies. Those standards keep their number as-is and every edition
found is recorded in the index.

Titles are recorded exactly as the source returns them. A garbled one is flagged
(`title_suspect`) and kept; it is never "cleaned up", because a cleaned title is
a title nobody published.
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.cookiejar
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
KB = ROOT / "data" / "knowledge" / "indian_standards.json"
INDEX = ROOT / "data" / "standard_archive_index.json"
CACHE = pathlib.Path(__file__).resolve().parents[1] / ".cache" / "standard_titles"

BIS_BASE = "https://www.services.bis.gov.in/php/BIS_2.0/bisconnect/knowyourstandards/"
BIS_PAGE = BIS_BASE + "Indian_standards/isdetails/"
BIS_SEARCH = BIS_BASE + "Elasticsearch/getsearchAjax"
ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
ARCHIVE_ITEM = "https://archive.org/details/"

DELAY = 0.3          # be a polite guest on both hosts
TIMEOUT = 45
BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"


# ------------------------------------------------------------------ parsing


PART = re.compile(r"part[\s\-]*(\d+)", re.I)
SEC = re.compile(r"(?:sec(?:tion)?)[\s\-]*(\d+)", re.I)


def parse_number(raw: str) -> dict:
    """"IS 302 (Part 2/Sec 9):2008" -> {number: 302, parts: [2, 9], year: 2008}.

    Handles every shape in the knowledge base: "IS 17634: 2022",
    "IS 15844(Part-2): 2023", "IS/IEC 62368 (Part 1)", "IS 1180 (Part 1)",
    "IS 302 (Part 2): Section 15: 2009", "IS/ISO 6742-2:2015".
    """
    text = raw.strip()
    prefix = "IS"
    found_prefix = re.match(r"(IS(?:/[A-Z]+)*)", text, re.I)
    if found_prefix:
        prefix = found_prefix.group(1).upper()

    # A second standard number glued on ("... IS/IEC 61730 -1 IS/IEC 61730 -2")
    # is a compound listing. Only the first is resolved; the rest is recorded.
    body = text[len(found_prefix.group(1)):] if found_prefix else text

    number_match = re.search(r"(\d{2,6})", body)
    if not number_match:
        return {"prefix": prefix, "number": None, "parts": [], "year": None, "raw": raw}
    number = number_match.group(1)
    rest = body[number_match.end():]

    parts = [int(p) for p in PART.findall(text)]
    parts += [int(s) for s in SEC.findall(text)]

    # "IS/ISO 6742-2:2015" and "IS 302-2-25" — parts are a dash chain, not a
    # "(Part n)". Take every segment, not just the first.
    if not parts:
        dashed = re.match(r"((?:\s*-\s*\d+)+)", rest)
        if dashed:
            parts = [int(d) for d in re.findall(r"\d+", dashed.group(1))]

    # The year is a 4-digit 19xx/20xx that is not the document number itself.
    years = [int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", text)
             if y != number]
    return {
        "prefix": prefix,
        "number": number,
        "parts": parts,
        "year": years[-1] if years else None,
        "raw": raw,
    }


# ------------------------------------------------------------------- cache


def cache_path(key: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", key)[:150]
    return CACHE / f"{safe}.json"


def cached(key: str, produce):
    """Disk cache, so a re-run does not re-fetch. Failures are NOT cached."""
    path = cache_path(key)
    if path.exists():
        return json.loads(path.read_text())
    value = produce()
    if value is not None:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False))
        time.sleep(DELAY)
    return value


# ------------------------------------------------------------ archive route


def archive_query(query: str) -> list[dict] | None:
    params = [("q", query), ("rows", 50), ("page", 1), ("output", "json"),
              ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "year")]
    url = f"{ARCHIVE_SEARCH}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER})
    try:
        # Redirects must be followed: a request that does not returns 0 bytes.
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)["response"]["docs"]
    except Exception:
        return None


def archive_identifiers(parsed: dict) -> list[str]:
    """Identifier candidates, most specific first.

    The mirror is not consistent about the ISO/IEC infix — IS/ISO 6742-2 is
    gov.in.is.iso.6742.2.1985 but IS/ISO 9994 is gov.in.is.9994.1981 — so both
    shapes are tried rather than guessed at.
    """
    number, parts = parsed["number"], parsed["parts"]
    if not number:
        return []
    stems = [f"gov.in.is.{number}"]
    for infix in ("iso", "iec"):
        if infix in parsed["prefix"].lower():
            stems.insert(0, f"gov.in.is.{infix}.{number}")
    suffix = "".join(f".{p}" for p in parts)
    return [stem + suffix for stem in stems]


def resolve_archive(parsed: dict) -> dict:
    for stem in archive_identifiers(parsed):
        if parsed["year"]:
            exact = f"{stem}.{parsed['year']}"
            docs = cached(f"arch-{exact}", lambda: archive_query(f"identifier:{exact}"))
            if docs:
                return _archive_result(docs, "EXACT", exact)
        docs = cached(f"arch-w-{stem}", lambda: archive_query(f"identifier:{stem}.*"))
        exact_parts = [d for d in docs or [] if _segments_match(d["identifier"], stem)]
        if exact_parts:
            return _archive_result(exact_parts, "WILDCARD", stem + ".*")
    return {"method": "NOT_FOUND", "identifier": None, "title": None,
            "editions": [], "query": archive_identifiers(parsed)[:1]}


def _archive_result(docs: list[dict], method: str, query: str) -> dict:
    editions = sorted(
        ({"identifier": d["identifier"],
          "title": (d.get("title") or "").strip(),
          "year": _year_of(d["identifier"])} for d in docs),
        key=lambda e: (e["year"] or 0),
        reverse=True,
    )
    newest = editions[0]
    return {
        "method": method,
        "identifier": newest["identifier"],
        "title": newest["title"],
        "editions": editions,
        "query": query,
        "text_url": ARCHIVE_ITEM + newest["identifier"],
    }


def _segments_match(identifier: str, stem: str) -> bool:
    """The wildcard may only add a YEAR, never another part or section.

    `gov.in.is.302.2.*` matches gov.in.is.302.2.21.2018 in Archive's query
    language, but Sec 21 is a different standard from the one asked for. So a
    hit counts only when what follows the stem is a bare 4-digit year.
    """
    if not identifier.startswith(stem + "."):
        return False
    return bool(re.fullmatch(r"(?:19|20)\d{2}", identifier[len(stem) + 1:]))


def _year_of(identifier: str) -> int | None:
    found = re.search(r"\.((?:19|20)\d{2})$", identifier)
    return int(found.group(1)) if found else None


# ---------------------------------------------------------------- BIS route


class BISCatalogue:
    """BIS's own Know Your Standards search. Anonymous; no credentials."""

    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.headers = {
            "User-Agent": BROWSER,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BIS_PAGE,
            "Origin": "https://www.services.bis.gov.in",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        self.ready = False

    def open_session(self) -> bool:
        """Fetch the page once for its cookies. Needed before the search answers."""
        try:
            request = urllib.request.Request(BIS_PAGE, headers={"User-Agent": BROWSER})
            self.opener.open(request, timeout=TIMEOUT).read()
            self.ready = True
        except Exception as exc:  # noqa: BLE001 — a portal being down is not a result
            print(f"  BIS session could not be opened: {exc.__class__.__name__}: {exc}")
            self.ready = False
        return self.ready

    def search(self, number: str) -> list[dict] | None:
        data = urllib.parse.urlencode({"search": number, "type": 1, "wh": "0"}).encode()
        request = urllib.request.Request(BIS_SEARCH, data=data, headers=self.headers)
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                rows = json.load(response)
        except Exception:
            return None
        return rows if isinstance(rows, list) else None


def resolve_bis(parsed: dict, catalogue: BISCatalogue) -> dict:
    """Match on document number + part + section exactly.

    The endpoint is a fuzzy prefix search — "367" also returns 3675, 3677, 3678 —
    so a row is only accepted when BIS's own structured fields agree with ours.
    """
    number, parts = parsed["number"], parsed["parts"]
    if not number:
        return _not_found(number)
    rows = cached(f"bis-{number}", lambda: catalogue.search(number))
    if rows is None:
        return _not_found(number, note="the BIS catalogue did not answer")
    if rows and rows[0].get("id") == "nothingmatch":
        return _not_found(number)

    want_part = str(parts[0]) if parts else ""
    want_sec = str(parts[1]) if len(parts) > 1 else ""
    matches = [
        row for row in rows
        if row.get("vc_doc_num") == number
        and (row.get("is_part") or "") == want_part
        and (row.get("is_sec") or "") == want_sec
    ]
    if not matches:
        return _not_found(number)

    editions = sorted(
        ({"identifier": f"IS {number}" + "".join(f" (Part {p})" for p in parts)
                        + (f":{row.get('is_year')}" if row.get("is_year") else ""),
          "title": _bis_title(row),
          "year": int(row["is_year"]) if str(row.get("is_year", "")).isdigit() else None,
          "bis_is_id": row.get("is_id"),
          "identical_is": (row.get("identical_is") or "").strip() or None}
         for row in matches),
        key=lambda e: (e["year"] or 0), reverse=True,
    )
    exact = [e for e in editions if parsed["year"] and e["year"] == parsed["year"]]
    chosen = exact[0] if exact else editions[0]
    return {
        "method": "EXACT" if exact else "WILDCARD",
        "identifier": chosen["identifier"],
        "title": chosen["title"],
        "editions": editions,
        "query": f"BIS catalogue search: {number}",
        "text_url": None,   # the document itself needs a logged-in BIS session
    }


# BIS writes "<number>[ (Part n)][:YYYY] (<TITLE>)" and the TITLE itself may
# contain brackets — "(ISO 20345 : 2021, MOD) (Third Revision)". So the title is
# everything between the FIRST bracket after the year and the final bracket.
_BIS_NAME = re.compile(r"^\s*IS[^(]*?(?:\([^()]*\))?[^(]*?:\s*\d{4}\s*\((?P<title>.*)\)\s*$", re.S)


def _bis_title(row: dict) -> str:
    """Pull the catalogue title out of BIS's search result `name`."""
    name = (row.get("name") or "").strip()
    found = _BIS_NAME.match(name)
    if found:
        return found.group("title").strip()
    # No year in the name: take the outermost trailing parenthetical if there is one.
    if name.endswith(")") and "(" in name:
        return name[name.index("(") + 1:-1].strip() or name
    return name


def _not_found(number, note: str = "") -> dict:
    return {"method": "NOT_FOUND", "identifier": None, "title": None,
            "editions": [], "query": number, "note": note}


# --------------------------------------------------------------- suspicion


# Mojibake signatures: UTF-8 bytes that were stored after being read as cp1252.
# BIS's own catalogue contains these (verified: IS 16192 Part 3 holds "â€”" where
# an em dash belongs), so they are flagged as damaged SOURCE text, never repaired.
_MOJIBAKE = ("â€", "Ã¢", "Â ", "ï¿½")


def looks_garbled(title: str) -> bool:
    """A title the source returned damaged. Flagged, never repaired."""
    if not title or len(title) < 6:
        return True
    # Some mirror items carry the identifier in place of a title.
    if title.lower().startswith("gov.in.is."):
        return True
    if any(marker in title for marker in _MOJIBAKE):
        return True
    letters = sum(c.isalpha() for c in title)
    if letters < len(title) * 0.5:
        return True
    # Latin text plus ordinary typographic punctuation is fine: en and em dashes,
    # curly quotes and ellipses are how BIS actually writes its titles.
    return bool(re.search(r"[^\x20-\x7E\u00A0-\u024F\u2000-\u206F]", title))


# ------------------------------------------------------------------- build


def build(source: str, limit: int | None) -> dict:
    records = json.loads(KB.read_text())
    if limit:
        records = records[:limit]

    catalogue = BISCatalogue()
    if source == "bis" and not catalogue.open_session():
        print("  continuing anyway; every standard will be recorded NOT_FOUND")

    entries: dict[str, dict] = {}
    for i, record in enumerate(records, 1):
        number = record.get("standard_number")
        if not number or number in entries:
            continue
        parsed = parse_number(number)
        result = (resolve_bis(parsed, catalogue) if source == "bis"
                  else resolve_archive(parsed))
        result["standard_number"] = number
        result["parsed"] = parsed
        result["source_route"] = source
        result["title_suspect"] = bool(result["title"]) and looks_garbled(result["title"])
        entries[number] = result
        if i % 50 == 0 or i == len(records):
            done = sum(1 for e in entries.values() if e["method"] != "NOT_FOUND")
            print(f"  [{i}/{len(records)}] resolved {done}/{len(entries)}")

    counts = {"EXACT": 0, "WILDCARD": 0, "NOT_FOUND": 0}
    for entry in entries.values():
        counts[entry["method"]] += 1

    return {
        "generated_on": dt.date.today().isoformat(),
        "source_route": source,
        "source": _source_block(source),
        "counts": counts,
        "total": len(entries),
        "standards": entries,
    }


def _source_block(source: str) -> dict:
    if source == "bis":
        return {
            "route": "bis",
            "organization": "Bureau of Indian Standards (BIS)",
            "name": "BIS Know Your Standards catalogue",
            "url": BIS_PAGE,
            "official": True,
            "note": ("Catalogue metadata read from BIS's own Know Your Standards search, "
                     "which answers without a login. Titles, parts, sections, years and "
                     "editions come from BIS directly. The STANDARD DOCUMENT itself is sold "
                     "by BIS and its text was not downloaded."),
        }
    return {
        "route": "archive",
        "organization": "Public.Resource.Org, via the Internet Archive",
        "name": "Public-safety mirror of the Indian Standards (identifiers gov.in.is.*)",
        "url": "https://archive.org/details/gov.in.is.14543.2016",
        "official": False,
        "note": ("A third-party public-safety MIRROR, not a BIS publication. Used as a "
                 "fallback and always disclosed as such. BIS sells these standards; text "
                 "obtained this way must never be presented as coming from bis.gov.in."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("bis", "archive"), default="bis",
                        help="bis = BIS's own catalogue (official, primary); "
                             "archive = Public.Resource.Org mirror (fallback)")
    parser.add_argument("--limit", type=int, default=None, help="first N records only")
    parser.add_argument("--out", default=None, help="write the index somewhere else")
    args = parser.parse_args(argv)

    print(f"Resolving standards via --source {args.source}")
    index = build(args.source, args.limit)
    out = pathlib.Path(args.out) if args.out else INDEX
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")

    counts, total = index["counts"], index["total"]
    print(f"\n  {total} standards")
    for method in ("EXACT", "WILDCARD", "NOT_FOUND"):
        share = counts[method] / total * 100 if total else 0
        print(f"    {method:<10} {counts[method]:4}  ({share:.1f}%)")
    suspect = sum(1 for e in index["standards"].values() if e["title_suspect"])
    print(f"    titles flagged as garbled: {suspect}")
    print(f"  written: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
