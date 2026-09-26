"""Phase 7, steps 2-3: turn the approved standards' mirrored text into clause records.

    cd backend/scripts && ../.venv/bin/python fetch_standard_clauses.py

A BUILD-TIME tool (stdlib only). It reuses score_clause_candidates.py — its fetch
helpers, cache, heading sequence and readability test — and adds only what an
ingest needs: pages, table cutting, per-clause noise and the records themselves.
Writes data/knowledge/standard_clauses.json and data/clause_ingest_report.md.
The application never calls the archive at runtime.

Honesty rules, enforced here:
  * Only the standards marked SHIP in data/clause_candidate_scores.md, and only the
    edition MetrIQ's record cites.
  * Text is reproduced as OCR read it. Nothing is corrected. A clause with too much
    noise, or a number whose digits are mixed with O / o / l / I, is dropped whole.
  * Table and figure cells are cut out and replaced by MetrIQ's own sentence (D3).
  * Parsing stops at the back matter, so bound-in amendment sheets never enter a
    clause; amendment slips before clause 1 are outside the clauses anyway (D5).
  * Pages: djvu.xml leaf N is PDF page N + 1 (verified against three PDFs), checked
    per item by leaf count == PDF page count. A bare "page N" is only ever a printed
    page from _page_numbers.json (D2).
  * A clause number seen twice in one standard is a parsing error: both are dropped (D6).
"""

from __future__ import annotations

import collections
import difflib
import html
import json
import re
import sys
import urllib.parse

import fetch_standard_titles as ft
import score_clause_candidates as sc
from fetch_reaffirmations import _get

OUT = sc.KNOWLEDGE_DIR / "standard_clauses.json"
REPORT = ft.ROOT / "data" / "clause_ingest_report.md"
SCORES = ft.ROOT / "data" / "clause_candidate_scores.md"
ORGANIZATION = "Public.Resource.Org / Internet Archive (BIS document)"

MAX_NOISE = 0.10          # a clause is dropped when more than 10% of its prose lines are unreadable
MIN_CLAUSES = 5           # a standard left with fewer clean clauses is dropped
CELL_RUN = 4              # this many table-cell lines close together is a table (or figure)

CAPTION = re.compile(r"^(Table|TABLE|Fig\.?|FIG\.?|Figure|FIGURE)\s+\d+")
LIST_ITEM = re.compile(r"^[a-z]\)")
# A table ROW read as one line: BIS numbers table rows i), ii) … (its lettered lists skip "i)").
ROMAN_ROW = re.compile(r"^\(?[ivxl]+\)\s")
# Standard references are prose, not table numbers: "IS 5887 (Part 7)", "IS 3025 (Part 2)".
IS_REF = re.compile(r"\bIS\s*[:]?\s*\d+(\s*\((Part|Sec)[^)]*\))*(\s*[:]\s*\d{4})?")
NUMBERED_ROW = re.compile(r"^\d+\)\s")
MIN_MAX = re.compile(r"\b(Min|Max)\b")
# A table's own notes, directly under it: "NOTE — …", "NOTES", "1 Approved methods …".
TABLE_NOTE = re.compile(r"^(NOTES?\b|\d+\s+[A-Z])")
SUSPECT = re.compile(r"^(?=.*\d)(?=.*[OolI])[0-9OolI.,]+$")
# A token carrying Cyrillic or Greek letters: OCR read Latin text, a unit or a number as another alphabet ("К№/т").
FOREIGN = re.compile(r"[\u0370-\u03ff\u0400-\u04ff№]")
# Two columns read as one line: another clause's number sits mid-line ("… selected from H-1.3 The falling …").
MERGED = re.compile(r"\S\s+(?:[A-Z]-)?\d+(?:\.\d+)+\s+[A-Z][a-z]")


# ---------------------------------------------------------------------- fetching


def approved() -> list[str]:
    return [line.split("|")[1].strip() for line in SCORES.read_text().splitlines()
            if "**SHIP**" in line]


def xml_lines(item: dict) -> dict | None:
    """Every OCR line of djvu.xml with its leaf (0-based), plus the leaf count."""
    name = f"{item['base']}_djvu.xml"
    if name not in item["names"]:
        return None

    def fetch():
        raw = _get(f"https://archive.org/download/{item['identifier']}/{urllib.parse.quote(name)}")
        if raw is None:
            return None
        objects = raw.decode("utf-8", "replace").split("<OBJECT")[1:]
        lines = []
        for leaf, obj in enumerate(objects):
            for line in re.findall(r"<LINE>(.*?)</LINE>", obj, re.S):
                words = [html.unescape(w) for w in re.findall(r"<WORD[^>]*>(.*?)</WORD>", line, re.S)]
                text = " ".join(" ".join(words).split())
                if text:
                    lines.append([leaf, text])
        return {"leaves": len(objects), "lines": lines}
    return ft.cached(f"xml-{item['identifier']}", fetch)


def pdf_pages(item: dict) -> int | None:
    name = f"{item['base']}.pdf"
    if name not in item["names"]:
        return None

    def fetch():
        raw = _get(f"https://archive.org/download/{item['identifier']}/{urllib.parse.quote(name)}")
        return None if raw is None else {"pages": len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", raw))}
    value = ft.cached(f"pdfpages-{item['identifier']}", fetch)
    return value["pages"] if value else None


def leaf_of_lines(lines: list[str], xml: dict | None) -> list[int | None]:
    """The leaf each text line sits on, where the alignment with djvu.xml settles it."""
    leaves: list[int | None] = [None] * len(lines)
    if not xml:
        return leaves
    norm = [" ".join(ln.split()) for ln in lines]
    matcher = difflib.SequenceMatcher(None, norm, [t for _, t in xml["lines"]], autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            leaves[block.a + k] = xml["lines"][block.b + k][0]
    return leaves


# ----------------------------------------------------------------------- clauses


def is_cell(line: str) -> bool:
    """A table/figure cell as djvu.txt writes it: a short line that is not a list item or sentence."""
    numbers = sum(any(ch.isdigit() for ch in tok) for tok in IS_REF.sub("", line).split()[1:])
    if numbers >= 3:
        return True                          # "Orton/°C, Min 12/1340 19/1540 35/1785"
    if (LIST_ITEM.match(line) or NUMBERED_ROW.match(line)) and (numbers >= 2 or MIN_MAX.search(line)):
        return True                          # "a) ALO, per cent, Min 45.0 65.0 78" — a lettered table row
    if ROMAN_ROW.match(line):
        # Cutting a prose roman list only hides text behind a pointer to the PDF; keeping a
        # table row risks a misaligned limit. So every roman-numbered line is a row.
        return True
    words = line.split()
    if len(words) > 4 or LIST_ITEM.match(line):
        return False
    return any(c.isdigit() for c in line) or not line.endswith((".", ";", ":", ","))


def table_spans(lines: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, kind) of every table or figure: a caption and/or a run of cells.

    Cells separated by at most two other lines belong to one run. A caption opens a
    span even when fewer cells follow, because a captioned table is a table.
    """
    spans, i = [], 0
    while i < len(lines):
        caption = bool(CAPTION.match(lines[i]))
        if not caption and not is_cell(lines[i]):
            i += 1
            continue
        j, cells, last = i, 0, i
        while j < len(lines) and j - last <= 3:
            if is_cell(lines[j]) or (j == i and caption):
                cells += 1
                last = j
            j += 1
        if caption or cells >= CELL_RUN:
            # The table's notes go with it, including a note's wrapped continuation lines.
            while last + 1 < len(lines) and (
                    TABLE_NOTE.match(lines[last + 1])
                    or (TABLE_NOTE.match(lines[last]) or lines[last][:1].islower())
                    and lines[last + 1][:1].islower() and not LIST_ITEM.match(lines[last + 1])):
                last += 1
            kind = "figure" if lines[i].upper().startswith("FIG") else "table"
            spans.append((i, last + 1, kind))
            i = last + 1
        else:
            i += 1
    return spans


def page_reference(leaves: list[int], ok: bool, printed: dict) -> tuple[str | None, str | None]:
    """(reference suffix, the PDF page(s) phrase for a table sentence)."""
    if not ok or not leaves:
        return None, None
    lo, hi = min(leaves), max(leaves)
    pdf = f"PDF page {lo + 1}" if lo == hi else f"PDF pages {lo + 1}–{hi + 1}"
    first, last = printed.get(lo), printed.get(hi)
    if first and last:
        page = f"page {first}" if lo == hi else f"pages {first}–{last}"
        return f"{page} ({pdf})", pdf
    return pdf, pdf


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build(number: str, item: dict, known: set[str], catalogue: str | None) -> tuple[list[dict], dict]:
    lines = [ln.strip() for ln in item["text"].splitlines() if ln.strip()]
    anchor = next((i for i, ln in enumerate(lines) if sc.SCOPE.match(ln)), 0)
    back = next((i for i, ln in enumerate(lines) if i > anchor and sc.BACK_MATTER.match(ln)), len(lines))
    body = lines[anchor:back]

    xml = xml_lines(item)
    pdf = pdf_pages(item)
    pages_ok = bool(xml and pdf and xml["leaves"] == pdf)
    leaves = leaf_of_lines(body, xml)
    header = re.compile(rf"^IS\s*[:]?\s*{item['digits']}\b.*\b(19|20)\d{{2}}\s*$")
    amended = item["amendment_docs"] > 0 or any(sc.AMENDMENT_SHEET.match(ln) for ln in lines)

    stats = collections.Counter()
    dropped, records = [], []
    for c in sc.clauses(body):
        label = (f"{c['space']}-" if c["space"] else "") + ".".join(map(str, c["number"]))
        start = c["start"]
        kept = [(k, ln) for k, ln in enumerate(c["body"], start)
                if not header.match(ln) and not re.fullmatch(r"\d{1,3}", ln)]
        text_lines = [ln for _, ln in kept]
        clause_leaves = [leaves[k] for k, _ in kept if leaves[k] is not None]
        reference, pdf_phrase = page_reference(clause_leaves, pages_ok, item["page_numbers"])

        spans = table_spans(text_lines[1:])      # the heading line itself is never a cell
        out, prose, pos = [text_lines[0]], [text_lines[0]], 0
        for s, e, kind in spans:
            out += text_lines[1 + pos:1 + s]
            prose += text_lines[1 + pos:1 + s]
            span_leaves = [leaves[kept[1 + k][0]] for k in range(s, e) if leaves[kept[1 + k][0]] is not None]
            _, where = page_reference(span_leaves, pages_ok, {})
            out.append(f"[This clause contains a {kind} that MetrIQ does not reproduce, because OCR "
                       f"separates its cells and values could be misaligned. See the source PDF"
                       f"{', ' + where if where else ''}.]")
            pos = e
        out += text_lines[1 + pos:]
        prose += text_lines[1 + pos:]
        stats["tables_cut"] += len(spans)

        noise = sum(sc.unreadable(ln, known) for ln in prose) / len(prose)
        tokens = [tok.strip(".,;:()[]") for ln in prose for tok in ln.split()]
        suspect = [t for t in tokens if SUSPECT.match(t)]
        foreign = [t for t in tokens if FOREIGN.search(t)]
        merged = next((ln for ln in prose[1:] if MERGED.search(ln)), None)
        reason = (f"clause longer than {sc.MAX_CLAUSE_LINES} lines (headings likely missed)"
                  if len(c["body"]) > sc.MAX_CLAUSE_LINES
                  else f"{noise:.0%} of prose lines unreadable" if noise > MAX_NOISE
                  else f"number not read confidently: {suspect[0]!r}" if suspect
                  else f"characters read as another alphabet: {foreign[0]!r}" if foreign
                  else f"two columns merged on one line: {merged[:60]!r}" if merged
                  else None)
        if reason:
            dropped.append((label, reason))
            continue
        if len(out) == 1:
            stats["heading_only"] += 1       # e.g. "4 GRADES": its sub-clauses carry the text
            continue

        content = "\n".join(out)
        content += ("\n\nMetrIQ note: this is the text of " + number + ", clause " + label + ", as read by "
                    "OCR from the Public.Resource.Org mirror on the Internet Archive — a third-party mirror of "
                    "the BIS document, not a BIS publication. It is reproduced as OCR read it, recognition "
                    "errors included; MetrIQ has not corrected it.")
        if amended:
            content += (" This is the base edition's text; published amendments to " + number +
                        " are not incorporated.")
        heading = c["title"]
        title = f"{number} Clause {label} — "
        if len(title + heading) > 200:
            heading = heading[: 199 - len(title)] + "…"
        records.append({
            "id": f"{slug(number)}-clause-{slug(label)}",
            "title": title + heading,
            "category": "standard_clauses",
            "content": content,
            "standard_number": number,
            "source_organization": ORGANIZATION,
            "source_url": ft.ARCHIVE_ITEM + item["identifier"],
            "document_name": catalogue,
            "reference": f"Clause {label}, {reference or 'page not established'}",
            "verification_status": "unverified",
        })

    # D6: the same id twice means the parse went wrong there. Drop every copy.
    counts = collections.Counter(r["id"] for r in records)
    duplicates = sorted(i for i, n in counts.items() if n > 1)
    records = [r for r in records if counts[r["id"]] == 1]
    stats.update(parsed=len(records) + len(dropped) + stats["heading_only"] + sum(counts[i] for i in duplicates),
                 kept=len(records))
    return records, {"dropped": dropped, "duplicates": duplicates, "pages_ok": pages_ok,
                     "leaves": xml["leaves"] if xml else None, "pdf_pages": pdf,
                     "amended": amended, **stats}


def catalogue_title(number: str, index: dict, kb: list[dict]) -> str | None:
    """The cited edition's catalogue title (Phase 4 index first, then the KB record's own)."""
    year = sc.YEAR.search(number)
    entry = index.get(number) or index.get(sc.YEAR.sub("", number).strip()) or {}
    for edition in entry.get("editions", []):
        if year and edition.get("year") == int(year.group(1)) and edition.get("title"):
            return edition["title"]
    for record in kb:
        if record.get("standard_number") == number:
            found = re.search(r'Catalogue title: "([^"]+)"', record["content"])
            if found:
                return found.group(1)
    return None


def main() -> int:
    kb = sc.knowledge()
    index = json.loads(ft.INDEX.read_text())["standards"]
    chosen, _ = sc.candidates({r["standard_number"] for r in kb if r.get("category") == "indian_standards"})
    items = {n: sc.fetch_item(n, index) for n in chosen}
    known = sc.vocabulary(kb, items)       # the same vocabulary step 1 scored with

    all_records, report = [], {}
    for number in approved():
        records, info = build(number, items[number], known, catalogue_title(number, index, kb))
        if len(records) < MIN_CLAUSES:
            info["standard_dropped"] = f"only {len(records)} clean clauses after per-clause drops"
            records = []
        all_records += records
        report[number] = info
    OUT.write_text(json.dumps(all_records, indent=2, ensure_ascii=False) + "\n")
    write_report(report, len(all_records))
    print(f"{len(all_records)} clause records from "
          f"{sum(1 for i in report.values() if not i.get('standard_dropped'))} standards")
    return 0


def write_report(report: dict, total: int) -> None:
    out = [
        "# Phase 7 — clause ingest report",
        "",
        "Generated by `backend/scripts/fetch_standard_clauses.py`. Source text: the Public.Resource.Org "
        "mirror on the Internet Archive, the edition MetrIQ's record cites.",
        "",
        f"Thresholds: a clause is dropped when more than {MAX_NOISE:.0%} of its prose lines (after tables "
        f"are cut) are unreadable, when it runs past {sc.MAX_CLAUSE_LINES} "
        "lines, when any number mixes digits with O / o / l / I, when any token carries Cyrillic/Greek letters, or when a "
        "line carries another clause's number mid-line (two columns merged). A standard left with fewer than "
        f"{MIN_CLAUSES} clean clauses is dropped. The heading line counts as a prose line. A clause number seen twice in one standard drops every copy. A clause "
        "that is only a heading (its sub-clauses carry the text) gets no record of its own.",
        "",
        f"**{total} clause records.**",
        "",
        "| Standard | Parsed | Kept | Dropped | Heading only | Duplicates | Tables/figures cut | Leaves / PDF pages | "
        "Pages | Amendments | Result |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for number, i in report.items():
        out.append(f"| {number} | {i['parsed']} | {i['kept']} | {len(i["dropped"])} | {i["heading_only"]} | {len(i["duplicates"])} | "
                   f"{i['tables_cut']} | {i['leaves']} / {i['pdf_pages']} | "
                   f"{'PDF page cited' if i['pages_ok'] else 'page not established'} | "
                   f"{'yes' if i['amended'] else 'no'} | {i.get('standard_dropped') or 'ingested'} |")
    out += ["", "## Dropped clauses", ""]
    for number, i in report.items():
        for label, reason in i["dropped"]:
            out.append(f"- {number} clause {label}: {reason}")
    out += ["", "## Duplicate clause numbers (every copy dropped)", ""]
    dups = [f"- {n}: {d}" for n, i in report.items() for d in i["duplicates"]]
    out += dups or ["None."]
    REPORT.write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    sys.exit(main())
