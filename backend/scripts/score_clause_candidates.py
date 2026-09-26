"""Phase 7, step 1: MEASURE which standards' mirrored text is good enough to parse into clauses.

    cd backend/scripts && ../.venv/bin/python score_clause_candidates.py

A BUILD-TIME tool (stdlib only), like fetch_standard_titles.py, whose index and
on-disk cache it reuses. It ingests NOTHING: it writes one report,
data/clause_candidate_scores.md, and never touches the knowledge base.

Candidates (about 60): the demo path, every standard the Phase 2 eval set's
consumer_probe and hand_written queries expect, then BIS-listing standards picked
evenly across cited years so old scans are measured too. Only standards that are in
the knowledge base can be candidates.

Per candidate, and only for the edition MetrIQ's record CITES (never another one):
  * the mirror item gov.in.is.<number>.<cited year> and its main OCR text
    (<name>_djvu.txt; files starting with "z" are separate amendment documents),
  * headings matched by the step-3 rule  ^\\d+(\\.\\d+)*\\s+[A-Z]  and annex  ^[A-Z]-\\d+...,
  * CLEAN clauses: a heading that continues the numbering of the previous accepted one
    (child, sibling or an ancestor's next sibling), whose heading and body are readable,
  * unreadable lines — most tokens are not words seen in the knowledge base or in at
    least 3 of the candidate documents (bilingual cover noise lands here),
  * whether clause 1 is SCOPE with a readable body,
  * suspect numbers — a digit run mixed with O / o / l / I, which must never become a
    clean number,
  * amendment documents (separate "z...Amd" files) and amendment sheets bound into the
    base scan ("AMENDMENT NO. n"),
  * whether _page_numbers.json maps leaves to printed pages at all.
"""

from __future__ import annotations

import collections
import json
import re
import sys
import urllib.parse
from pathlib import Path

import fetch_standard_titles as ft
from fetch_reaffirmations import _get

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.standard_currency import currency_for  # noqa: E402

KNOWLEDGE_DIR = ft.ROOT / "data" / "knowledge"
EVAL = Path(__file__).resolve().parents[1] / "tests" / "data" / "eval_queries.json"
REPORT = ft.ROOT / "data" / "clause_candidate_scores.md"

DEMO = ["IS 14543:2016", "IS 13428:2005", "IS 367:1993", "IS 16102 (Part 1)",
        "IS 16103 (Part 1): 2012", "IS 15885 (Part 2/Sec 13):2012", "IS 17153:2019",
        "IS 2347:2017", "IS 4151: 2015", "IS 1417:2016", "IS 2112:2014"]
# Named in the Phase 7 brief as old scans; checked against the knowledge base, not assumed.
BRIEF_OLD = ["IS 2476", "IS 740", "IS 8870:1978"]
TARGET = 60

MIN_CLEAN = 5
MAX_UNREADABLE_IN_CLAUSES = 0.10
# A clause body longer than this has almost always swallowed the clauses after a heading the
# OCR garbled ("I.l" for "1.1"): ingesting it would file later text under the wrong number.
MAX_CLAUSE_LINES = 120
MAX_COLLAPSED = 0.15

# The step-3 rule, plus an optional dot after the number: pre-1990 standards write "1. SCOPE".
# Rows that depend on the dot are marked, because the brief's literal rule would miss them.
HEADING = re.compile(r"^(\d+(?:\.\d+)*)(\.?)\s+([A-Z].*)$")
ANNEX = re.compile(r"^([A-Z])-(\d+(?:\.\d+)*)(\.?)\s+([A-Z].*)$")
SCOPE = re.compile(r"(?i)^1\.?\s+scope\b")
# An annex or appendix heading ends the clause before it; otherwise that clause swallows the annex.
BOUNDARY = re.compile(r"^(ANNEX|APPENDIX)\s+[A-Z]\b")
BACK_MATTER = re.compile(r"(?i)^(bis is a statutory|bureau of indian standards is a statutory"
                         r"|amendment no\.?\s*\d|headquarters\s*:|regional offices)")
AMENDMENT_SHEET = re.compile(r"(?i)^\s*amendment no\.?\s*(\d+)\b")
WORD = re.compile(r"[A-Za-z]{3,}")
YEAR = re.compile(r":\s*((?:19|20)\d{2})\s*$")


def cached_json(key, url):
    def fetch():
        raw = _get(url)
        return None if raw is None else json.loads(raw)
    return ft.cached(key, fetch)


def cached_text(key, url):
    def fetch():
        raw = _get(url)
        return None if raw is None else {"text": raw.decode("utf-8", "replace")}
    value = ft.cached(key, fetch)
    return value["text"] if value else None


# ------------------------------------------------------------------ candidates


def candidates(kb_numbers: set[str]) -> tuple[list[str], list[str]]:
    queries = json.loads(EVAL.read_text())

    def expected(origins):
        out = []
        for q in queries:
            if q["origin"] in origins:
                e = q["expected_standard_number"]
                out += e if isinstance(e, list) else [e] if e else []
        return out

    chosen, missing = [], []
    for n in DEMO + BRIEF_OLD + sorted(set(expected({"consumer_probe", "hand_written"}))):
        if n not in kb_numbers:
            missing.append(n)
        elif n not in chosen:
            chosen.append(n)
    # Fill with BIS-listing standards spread evenly over cited years (a spread of eras).
    listing = sorted({n for n in expected({"bis_listing"}) if n in kb_numbers and n not in chosen},
                     key=lambda n: (int(YEAR.search(n).group(1)) if YEAR.search(n) else 0, n))
    need = max(0, TARGET - len(chosen))
    if need and listing:
        step = len(listing) / need
        chosen += [listing[int(i * step)] for i in range(min(need, len(listing)))]
    return chosen, missing


# ------------------------------------------------------------------- measuring


def tokens(line):
    return [w.lower() for w in WORD.findall(line)]


def unreadable(line, known):
    words = tokens(line)
    if len(words) >= 2:
        return sum(w in known for w in words) / len(words) < 0.5
    junk = sum(not (c.isalnum() or c.isspace() or c in ".,;:()/%-'\"") for c in line)
    return len(line) >= 5 and junk / len(line) > 0.3


def successor(prev, cur):
    """cur continues prev: its first child, its sibling, or an ancestor's next sibling."""
    if prev is None:
        return cur in ((0,), (1,))
    if cur == prev + (1,):
        return True
    return any(cur == prev[:k] + (prev[k] + 1,) for k in range(len(prev)))


def clauses(lines):
    """Accepted headings in document order, each with its body lines.

    A top-level heading (depth 1) must be written in capitals, as BIS writes them
    ("2 REFERENCES", "B-1 FIELD OF APPLICATION"): table notes are numbered "1 … 5"
    too, and without this they hijack the numbering.
    """
    found, last = [], {}
    for i, line in enumerate(lines):
        m, a = HEADING.match(line), ANNEX.match(line)
        if m:
            space, number, dot, title = "", m.group(1), m.group(2), m.group(3)
        elif a:
            space, number, dot, title = a.group(1), a.group(2), a.group(3), a.group(4)
        else:
            continue
        number = tuple(map(int, number.split(".")))
        letters = [c for c in title if c.isalpha()]
        first = title.split()[0]
        capitals = (len(first) >= 3 and first.isupper()) or sum(c.isupper() for c in letters) >= 0.8 * len(letters)
        if len(number) == 1 and not capitals:
            continue
        prev = last.get(space)
        ok = number == (1,) if space and prev is None else successor(prev, number)
        if ok:
            last[space] = number
            found.append({"space": space, "number": number, "dot": bool(dot), "title": title, "start": i})
    stops = [i for i, line in enumerate(lines) if BOUNDARY.match(line)]
    for c, nxt in zip(found, found[1:] + [None]):
        end = nxt["start"] if nxt else len(lines)
        end = min([s for s in stops if c["start"] < s < end] + [end])
        c["body"] = lines[c["start"]:end]
    return found


def measure(text, known, number_digits, year):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Clauses start at "1 SCOPE": before it sit the mirror's Right-To-Information preface,
    # the bilingual cover, the foreword and — in some scans — amendment slips.
    anchor = next((i for i, ln in enumerate(lines) if SCOPE.match(ln)), 0)
    back = next((i for i, ln in enumerate(lines) if i > anchor and BACK_MATTER.match(ln)), len(lines))
    front, body_lines = lines[:anchor], lines[anchor:back]

    found = clauses(body_lines)
    clean = []
    for c in found:
        c["bad"] = sum(unreadable(ln, known) for ln in c["body"])
        if (not unreadable(c["title"], known) and c["bad"] / len(c["body"]) <= 0.2
                and len(c["body"]) <= MAX_CLAUSE_LINES):
            clean.append(c)
    in_clauses = [ln for c in found for ln in c["body"]]
    # The scope is clause 1 with everything under it (1.1, 1.2 …) up to clause 2.
    scope_lines = [ln for c in found if c["space"] == "" and c["number"][0] == 1 for ln in c["body"]]
    scope_ok = bool(found and found[0]["number"] == (1,) and found[0]["title"].upper().startswith("SCOPE")
                    and sum(w in known for ln in scope_lines for w in tokens(ln)) >= 8)
    suspect = sum(
        1 for ln in in_clauses for tok in ln.split()
        for t in [tok.strip(".,;:()[]")]
        if any(ch.isdigit() for ch in t) and set(t) <= set("0123456789.,OolI") and set(t) & set("OolI"))
    cover = "\n".join(front[:400]) if anchor else text[:12000]
    edition_on_cover = bool(re.search(rf"\b{number_digits}\b[^\n]{{0,40}}?\b{year}\b", cover))
    literal = re.compile(r"^\d+(\.\d+)*\s+[A-Z]|^[A-Z]-\d+(\.\d+)*\s+[A-Z]")
    return {
        "headings": sum(bool(literal.match(ln)) for ln in body_lines),
        "dotted": sum(c["dot"] for c in clean),
        "clean": len(clean),
        "unreadable": sum(unreadable(ln, known) for ln in lines),
        "unreadable_in_clauses": sum(c["bad"] for c in found),
        "clause_lines": len(in_clauses),
        "tables": sum(bool(re.match(r"^Table\s+\d+", ln)) for ln in in_clauses),
        "collapsed": sum(len(c["body"]) for c in found if len(c["body"]) > MAX_CLAUSE_LINES),
        "scope": scope_ok,
        "suspect_numbers": suspect,
        "amendment_sheets": len({m.group(1) for ln in lines if (m := AMENDMENT_SHEET.match(ln))}),
        "edition_on_cover": edition_on_cover,
    }


# ----------------------------------------------------------------------- items


def fetch_item(number: str, index: dict) -> dict:
    """The cited edition's mirror item, or a NOT_FOUND reason."""
    year = YEAR.search(number)
    entry = index.get(number) or index.get(YEAR.sub("", number).strip())
    if entry is None or entry["parsed"]["number"] is None:
        return {"not_found": "not in the Phase 4 index"}
    if not year:
        return {"not_found": "MetrIQ's record cites no edition year, so there is no edition to fetch"}
    year = int(year.group(1))
    for stem in ft.archive_identifiers(entry["parsed"]):
        identifier = f"{stem}.{year}"
        files = cached_json(f"files-{identifier}", f"https://archive.org/metadata/{identifier}/files")
        files = (files or {}).get("result") or []
        if not files:
            continue
        names = [f["name"] for f in files]
        texts = [n for n in names if n.endswith("_djvu.txt") and not n.startswith("z")]
        amendments = {n.split("_")[0].rsplit(".", 1)[0] for n in names
                      if n.startswith("z") and "amd" in n.lower() and n.endswith(".pdf")}
        if not texts:
            return {"identifier": identifier, "not_found": "mirror item has no OCR text for this edition"}
        base = texts[0][: -len("_djvu.txt")]
        quote = urllib.parse.quote
        text = cached_text(f"text-{identifier}",
                           f"https://archive.org/download/{identifier}/{quote(texts[0])}")
        pages = None
        if f"{base}_page_numbers.json" in names:
            pages = cached_json(f"pages-{identifier}",
                                f"https://archive.org/download/{identifier}/{quote(base)}_page_numbers.json")
        mapped = sum(1 for p in (pages or {}).get("pages", []) if p.get("pageNumber"))
        leaves = len((pages or {}).get("pages", []))
        return {"identifier": identifier, "year": year, "text": text, "amendment_docs": len(amendments),
                "extra_texts": len(texts) - 1, "mapped": mapped, "leaves": leaves,
                "digits": entry["parsed"]["number"]}
    return {"not_found": f"no mirror item for the cited edition ({year})"}


def decide(m: dict) -> tuple[str, str]:
    ratio = m["unreadable_in_clauses"] / max(1, m["clause_lines"])
    if not m["edition_on_cover"]:
        return "DROP", "cover does not print the cited number and year — edition not confirmed"
    if m["clean"] < MIN_CLEAN:
        return "DROP", f"only {m['clean']} clean clauses (< {MIN_CLEAN})"
    collapsed = m["collapsed"] / max(1, m["clause_lines"])
    if collapsed > MAX_COLLAPSED:
        return "DROP", (f"{collapsed:.0%} of clause text sits in clauses over {MAX_CLAUSE_LINES} lines "
                        "— missed headings or floating tables, text would land under the wrong clause")
    if not m["scope"]:
        return "DROP", "scope clause did not parse"
    if ratio > MAX_UNREADABLE_IN_CLAUSES:
        return "DROP", f"{ratio:.0%} of clause lines unreadable (> {MAX_UNREADABLE_IN_CLAUSES:.0%})"
    dot = (f"; {m['dotted']} of them written '1. SCOPE'-style — needs the step-3 rule to allow a dot"
           if m["dotted"] else "")
    return "SHIP", f"{m['clean']} clean clauses, scope parsed, {ratio:.1%} clause lines unreadable{dot}"


def main() -> int:
    kb = [r for f in sorted(KNOWLEDGE_DIR.glob("*.json")) for r in json.loads(f.read_text())]
    kb_numbers = {r["standard_number"] for r in kb if r.get("category") == "indian_standards"}
    chosen, missing = candidates(kb_numbers)
    index = json.loads(ft.INDEX.read_text())["standards"]
    items = {n: fetch_item(n, index) for n in chosen}

    # Vocabulary: every word in the knowledge base, plus words that recur across documents.
    known = {w for r in kb for w in tokens(r.get("title", "") + " " + r.get("content", ""))}
    df = collections.Counter(w for it in items.values() if it.get("text")
                             for w in set(tokens(it["text"])))
    known |= {w for w, c in df.items() if c >= 3}

    rows = []
    for n in chosen:
        it = items[n]
        status = (currency_for(n).status if currency_for(n) else "—")
        row = {"standard": n, "phase5": status, "identifier": it.get("identifier")}
        if it.get("not_found") or not it.get("text"):
            row.update(decision="NOT_FOUND", reason=it.get("not_found") or "OCR text could not be fetched")
        else:
            m = measure(it["text"], known, it["digits"], it["year"])
            row.update(m, amendment_docs=it["amendment_docs"], extra_texts=it["extra_texts"],
                       page_map=f"{it['mapped']}/{it['leaves']}" if it["leaves"] else "none")
            row["decision"], row["reason"] = decide(m)
        rows.append(row)
    write_report(rows, missing)
    for r in rows:
        print(f"{r['decision']:9} {r['standard']:34} {r['reason']}")
    print(f"\nSHIP {sum(r['decision'] == 'SHIP' for r in rows)} · "
          f"DROP {sum(r['decision'] == 'DROP' for r in rows)} · "
          f"NOT_FOUND {sum(r['decision'] == 'NOT_FOUND' for r in rows)} · "
          f"not in the knowledge base: {', '.join(missing) or 'none'}")
    return 0


def write_report(rows, missing) -> None:
    head = ("| Standard (as cited) | Phase 5 | Mirror item | Headings matched | Clean clauses | "
            "Unreadable lines (in clauses / total) | Scope parsed | Suspect numbers | "
            "Amendments (separate docs / sheets in base scan) | Tables inside clause text | Page map (leaves with a printed page) | "
            "Decision | Reason |")
    out = [
        "# Phase 7 step 1 — clause-text candidate scores",
        "",
        "Generated by `backend/scripts/score_clause_candidates.py` (build-time, stdlib only). "
        "Text is the Public.Resource.Org mirror on the Internet Archive — never a BIS publication. "
        "Only the edition MetrIQ's record cites is fetched; a missing edition is NOT_FOUND, never "
        "substituted. Nothing here is ingested.",
        "",
        f"Rules: SHIP needs ≥ {MIN_CLEAN} clean clauses, clause 1 = SCOPE with a readable body, "
        f"≤ {MAX_UNREADABLE_IN_CLAUSES:.0%} unreadable lines inside clause text, and the cover "
        "printing the cited number and year. A clean clause is a heading matched by "
        "`^\\d+(\\.\\d+)*\\s+[A-Z]` (or annex `^[A-Z]-\\d+…`) that continues the numbering of the "
        "previous accepted heading, with a readable heading and ≤ 20% unreadable body lines. "
        "A page map of 0/N means `_page_numbers.json` exists but maps no leaf: every page would be "
        "\"page not established\".",
        "",
        f"Demo-list / brief standards not in the knowledge base: {', '.join(missing) or 'none'}.",
        "",
        head,
        "|" + "---|" * (head.count("|") - 1),
    ]
    for r in rows:
        if r["decision"] == "NOT_FOUND":
            cells = [r["standard"], r["phase5"], r.get("identifier") or "—"] + ["—"] * 8
        else:
            cells = [r["standard"], r["phase5"], r["identifier"], str(r["headings"]), str(r["clean"]),
                     f"{r['unreadable_in_clauses']} / {r['unreadable']}", "yes" if r["scope"] else "no",
                     str(r["suspect_numbers"]), f"{r['amendment_docs']} / {r['amendment_sheets']}", str(r["tables"]),
                     r["page_map"]]
        out.append("| " + " | ".join(cells + [f"**{r['decision']}**", r["reason"]]) + " |")
    REPORT.write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    sys.exit(main())
