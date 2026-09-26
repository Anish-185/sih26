"""Sampling, conformity and test-method clauses of ONE standard (Phase 10).

The problem statement asks for "sampling frequencies, acceptance parameters, and
required test equipment". MetrIQ answers by QUOTING the clauses of a standard it holds
text for — it never summarises them and never computes a frequency. This module is a
deterministic selector over ``clauses.clauses_for(number)``: no search index, no model,
no network. A clause enters a group ONLY by its own words, and it may enter several.

HEADING. A clause has a heading when the first line after its clause number is short
(at most 8 words) and title-like: every word of four or more letters starts with a
capital ("9 SAMPLING", "F-1.4 Criteria for Conformity", "F-1.3.4 Referee Sample").
Otherwise the first line is the start of the clause's prose ("5.2.2 Coliform, bacteria
shall be absent…") and the clause has no heading. Everything after the clause number
is the clause's TEXT, heading included.

THE RULES (case-insensitive, whole words, line breaks read as spaces; ``matched``
records which one fired):

  SAMPLING
    heading contains: sampl…  (sample, samples, sampling)
    text contains:    "sampling" · "sample size" · "at random" · "referee sample" ·
                      "test sample(s)" · "samples shall be drawn / taken / selected" ·
                      "selected / drawn / taken from a / the / each lot" · "size of the lot" ·
                      "lot size"
    — the bare word "sample" in text is NOT enough: "absent in any 250 ml sample" is a
      requirement, not a sampling clause.

  CRITERIA_FOR_CONFORMITY
    heading contains: conformity · criteria · acceptance
    text contains:    "criteria for conformity" · "criteria of conformity" ·
                      "declared as conforming" · "declared as not conforming" ·
                      "considered as conforming" · "acceptance" · "shall be rejected" ·
                      "shall be accepted"

  TEST_METHODS  (rule R, chosen — see RULE_COUNTS in the Phase 10 report)
    heading contains: test · tests · testing · method(s) · apparatus · equipment ·
                      procedure
    OR text references a method-of-test annex or standard:
                      "method(s) of test" · "method(s) given/described/prescribed/
                      specified in Annex … / IS …" · "tested in accordance with / as per /
                      according to … (Annex | IS)" · "test(s) given/described/prescribed
                      in Annex … / IS …" · "apparatus" · "test equipment"
    The bare word "test" or "tested" in text is NOT enough on its own.

TABLES. Phase 7 cut tables out of clause text and left MetrIQ's own sentence pointing to
the PDF page. A grouped clause keeps that sentence, so the user is sent to the right
page; a table is never reconstructed. INCOMPLETENESS. The groups show only the clauses
MetrIQ could read reliably; the count Phase 7 withheld per standard is read from
data/clause_ingest_report.md, the ingester's own output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app import clauses
from app import language as lang
from app.knowledge.loader import load_knowledge_base
from app.knowledge.schema import KnowledgeItem

SAMPLING = "SAMPLING"
CRITERIA = "CRITERIA_FOR_CONFORMITY"
TEST_METHODS = "TEST_METHODS"
GROUPS = (SAMPLING, CRITERIA, TEST_METHODS)

CLAUSE_TEXT = "CLAUSE_TEXT"          # MetrIQ holds clause text for this standard
IDENTITY_ONLY = "IDENTITY_ONLY"      # MetrIQ holds the standard's identity, not its text
UNKNOWN_STANDARD = "UNKNOWN_STANDARD"  # not a standard in the knowledge base

REPORT = Path(__file__).resolve().parents[2] / "data" / "clause_ingest_report.md"


def _words(*phrases: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b", re.IGNORECASE)


HEADING_RULES = {
    SAMPLING: _words(r"sampl\w*"),
    CRITERIA: _words("conformity", "criteria", "acceptance"),
    TEST_METHODS: _words("test", "tests", "testing", r"methods?", "apparatus", "equipment", "procedure"),
}
TEXT_RULES = {
    SAMPLING: _words("sampling", "sample size", "at random", "referee sample", r"test samples?",
                     r"samples? (?:shall|should) be (?:drawn|taken|selected)",
                     r"(?:selected|drawn|taken) from (?:a|the|each) lot", "size of the lot", "lot size"),
    CRITERIA: _words("criteria for conformity", "criteria of conformity", "declared as conforming",
                     "declared as not conforming", "considered as conforming", "acceptance",
                     "shall be rejected", "shall be accepted"),
    TEST_METHODS: _words(r"methods? of tests?",
                         r"(?:methods?|tests?) (?:as )?(?:given|described|prescribed|specified|laid down) in\s+(?:\w+\s+){0,3}?(?:annex|IS)",
                         r"tested (?:in accordance with|as per|according to)\s+(?:\w+\s+){0,5}?(?:annex|IS)",
                         "apparatus", "test equipment"),
}
# Rule W, measured for comparison only: any test word anywhere.
_ANY_TEST_WORD = _words("test", "tests", "tested", "testing")

_TITLE_WORD = re.compile(r"[A-Za-z]{4,}")


def split_clause(item: KnowledgeItem) -> tuple[str, str]:
    """(heading or "", text after the clause number). Heading per the module docstring."""
    body = item.content.partition("\n\nMetrIQ note:")[0]
    label = clauses.label_of(item)
    text = body[len(label):].strip() if body.startswith(label) else body.strip()
    first = text.split("\n", 1)[0].strip()
    words = _TITLE_WORD.findall(first)
    has_more = "\n" in text
    is_heading = (has_more and first and len(first.split()) <= 8 and words
                  and all(w[0].isupper() for w in words))
    return (first if is_heading else ""), text


def _matches(group: str, heading: str, text: str) -> list[str]:
    """Why a clause is in a group: 'heading: <word>' / 'text: <phrase>'. Empty = not in it."""
    found = []
    text = re.sub(r"\s+", " ", text)          # OCR breaks lines anywhere
    if heading and (m := HEADING_RULES[group].search(heading)):
        found.append(f"heading: {m.group(0)}")
    if m := TEXT_RULES[group].search(text):
        found.append(f"text: {m.group(0)}")
    return found


def rule_counts(standard_number: str) -> dict[str, int]:
    """TEST_METHODS under each candidate rule, for the report: H = a test word in the
    heading only; R = H or a method-of-test reference in the text (chosen); W = any test
    word anywhere (the noise ceiling)."""
    h = r = w = 0
    for item in clauses.clauses_for(standard_number):
        heading, text = split_clause(item)
        text = re.sub(r"\s+", " ", text)
        in_h = bool(heading and HEADING_RULES[TEST_METHODS].search(heading))
        h += in_h
        r += in_h or bool(TEXT_RULES[TEST_METHODS].search(text))
        w += bool(_ANY_TEST_WORD.search(text))
    return {"H": h, "R": r, "W": w}


# ------------------------------------------------------------------ withheld counts


@lru_cache(maxsize=1)
def _ingest_report() -> dict[str, dict]:
    """Per standard: {withheld, dropped: [(label, reason)]} from Phase 7's report."""
    if not REPORT.exists():
        return {}
    text = REPORT.read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    for row in re.finditer(r"^\| (IS [^|]+?) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|", text, re.M):
        number, _parsed, _kept, dropped, _heading_only, duplicates = row.groups()
        out[number] = {"withheld": int(dropped) + int(duplicates), "dropped": []}
    for line in re.finditer(r"^- (IS .+?) clause (\S+): (.+)$", text, re.M):
        if line.group(1) in out:
            out[line.group(1)]["dropped"].append((line.group(2), line.group(3)))
    return out


# ------------------------------------------------------------------ result


@dataclass(frozen=True)
class GroupedClause:
    item: KnowledgeItem
    heading: str
    matched: list[str]


@dataclass
class ClauseGroups:
    standard_number: str
    status: str
    message: str
    completeness: str = ""
    withheld: int | None = None
    withheld_clauses: list[tuple[str, str]] = field(default_factory=list)
    groups: dict[str, list[GroupedClause]] = field(default_factory=dict)
    clause_count: int = 0


@lru_cache(maxsize=1)
def _known_standards() -> frozenset[str]:
    return frozenset(i.standard_number for i in load_knowledge_base().items
                     if i.category == "indian_standards" and i.standard_number)


def groups_for(standard_number: str, language: str = lang.EN) -> ClauseGroups:
    """The three groups for one standard, the number exactly as stored."""
    text = lang.clause_groups(language)
    if standard_number not in _known_standards():
        return ClauseGroups(standard_number, UNKNOWN_STANDARD, text["unknown"])
    items = clauses.clauses_for(standard_number)
    if not items:
        return ClauseGroups(standard_number, IDENTITY_ONLY, text["identity_only"])
    grouped: dict[str, list[GroupedClause]] = {g: [] for g in GROUPS}
    for item in items:
        heading, body = split_clause(item)
        for group in GROUPS:
            if found := _matches(group, heading, body):
                grouped[group].append(GroupedClause(item, heading, found))
    known = _ingest_report().get(standard_number)
    if known is None:
        completeness = text["incomplete_unknown"]
    else:
        completeness = text["incomplete_count"].format(count=known["withheld"])
    return ClauseGroups(
        standard_number, CLAUSE_TEXT, text["clause_text"], completeness,
        withheld=known["withheld"] if known else None,
        withheld_clauses=known["dropped"] if known else [],
        groups=grouped, clause_count=len(items))
