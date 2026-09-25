"""Standard currency: is the edition MetrIQ cites the newest one its evidence shows?

Phase 5. Deterministic, no model, no network. It reads ONE file —
data/standard_archive_index.json, written by the build-time tools
scripts/fetch_standard_titles.py (Phase 4) and scripts/fetch_reaffirmations.py —
and the standard number MetrIQ's own knowledge-base record cites.

This is a statement about MetrIQ's EVIDENCE, never about BIS's catalogue as a
whole. MetrIQ holds no withdrawal data, so nothing here may say or imply that BIS
has taken a standard out of force; a test checks every code path for that word.

It generalises the idea behind ``LabRegistry.other_editions()`` (Milestone 18):
a different edition is a different standard, and staying silent about the
editions MetrIQ knows of would hide what the evidence shows. There, the editions
come from BIS LIMS; here they come from the catalogue index, which Phase 4
already matched on number + part + section. No edition matching happens here.

Signals, strongest first:

1. A REAFFIRMATION statement for the cited edition — BIS's catalogue row, or the
   edition's own cover page ("Indian Standard (Reaffirmed 2021)"). Quoted.
2. BIS's own Know Your Standards catalogue: its edition list. A later edition
   there -> SUPERSEDED_BY; ours being the newest it lists -> ACTIVE.
3. The Public.Resource.Org mirror's edition list (only where BIS's catalogue did
   not resolve the number). A later edition -> SUPERSEDED_BY. Ours being the
   newest the mirror holds is NOT treated as ACTIVE: a mirror snapshot can lag a
   revision, and absence of evidence is not evidence of currency.
4. Anything else -> NOT_ESTABLISHED, used generously.

A reaffirmation does not outrank a LATER edition: "reaffirmed 2021" says the 2016
edition stood in 2021, and a 2024 edition is still later. A reaffirmation dated
AFTER the later edition contradicts it, so that case is NOT_ESTABLISHED.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

INDEX_PATH = Path(__file__).resolve().parents[2] / "data" / "standard_archive_index.json"

ACTIVE = "ACTIVE"
REAFFIRMED = "REAFFIRMED"
SUPERSEDED_BY = "SUPERSEDED_BY"
NOT_ESTABLISHED = "NOT_ESTABLISHED"
STATUSES = (ACTIVE, REAFFIRMED, SUPERSEDED_BY, NOT_ESTABLISHED)

# Which evidence the status rests on — the two signal strengths, kept visible.
BIS_CATALOGUE = "BIS_CATALOGUE"          # BIS's own live index (official)
ARCHIVE_MIRROR = "ARCHIVE_MIRROR"        # third-party mirror edition list
ARCHIVE_DOCUMENT = "ARCHIVE_DOCUMENT"    # the edition's cover page, via the mirror
NO_EVIDENCE = "NONE"

_TRAILING_YEAR = re.compile(r"\s*:\s*((?:19|20)\d{2})\s*$")

_SOURCE_LABEL = {
    BIS_CATALOGUE: "BIS Know Your Standards catalogue (services.bis.gov.in)",
    ARCHIVE_MIRROR: "Public.Resource.Org mirror on the Internet Archive — not a BIS publication",
    ARCHIVE_DOCUMENT: "Cover page of the edition, via the Public.Resource.Org mirror — "
                      "not a BIS publication",
    NO_EVIDENCE: "No edition evidence",
}

BOUNDARY = ("This describes MetrIQ's evidence about editions, read on {date}. It is not a "
            "statement from BIS about the standard's legal status, and MetrIQ holds no "
            "withdrawal data.")


class CurrencyOut(BaseModel):
    """Whether the edition MetrIQ cites is the newest one MetrIQ's evidence shows."""

    status: str = Field(description='"ACTIVE" | "REAFFIRMED" | "SUPERSEDED_BY" | "NOT_ESTABLISHED"')
    label: str = Field(description="Short badge text, written by MetrIQ.")
    statement: str = Field(description="One evidence-worded sentence (or two).")
    cited_edition: str | None = Field(default=None, description="The edition MetrIQ's record cites.")
    later_edition: str | None = Field(default=None, description="SUPERSEDED_BY only.")
    reaffirmed_year: int | None = None
    reaffirmation_quote: str | None = None
    editions: list[str] = Field(default_factory=list,
                                description="Every edition MetrIQ's evidence records, newest first.")
    evidence: str = Field(description='"BIS_CATALOGUE" | "ARCHIVE_MIRROR" | "ARCHIVE_DOCUMENT" | "NONE"')
    official: bool = Field(description="True only when the evidence is BIS's own catalogue.")
    source_label: str
    source_url: str | None = None
    checked_on: str | None = None
    boundary: str


@lru_cache(maxsize=1)
def _index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _entry(standard_number: str) -> tuple[dict | None, bool]:
    """(index entry, whether MetrIQ's year was filled in by Phase 4)."""
    standards = _index()["standards"]
    if standard_number in standards:
        return standards[standard_number], False
    base = _TRAILING_YEAR.sub("", standard_number).strip()
    return standards.get(base), base in standards


def currency_for(standard_number: str | None) -> CurrencyOut | None:
    """None when the number is not one of MetrIQ's verified standards."""
    if not standard_number:
        return None
    entry, year_filled = _entry(standard_number.strip())
    if entry is None:
        return None
    return _assess(standard_number.strip(), entry, year_filled, _index())


def _assess(number: str, entry: dict, year_filled: bool, index: dict) -> CurrencyOut:
    base = _TRAILING_YEAR.sub("", number).strip()
    cited_match = _TRAILING_YEAR.search(number)
    cited = int(cited_match.group(1)) if cited_match else None
    route = BIS_CATALOGUE if entry.get("source_route") == "bis" else ARCHIVE_MIRROR
    source = index["sources"].get(entry.get("source_route") or "", {})
    editions = sorted({e["year"] for e in entry.get("editions", []) if e.get("year")}, reverse=True)
    named = [f"{base}:{year}" for year in editions]
    identical = {e["year"]: e.get("identical_is") for e in entry.get("editions", [])}
    reaff = entry.get("reaffirmation") or {}
    date = index.get("generated_on")

    def out(status, label, statement, evidence=route, **extra) -> CurrencyOut:
        return CurrencyOut(
            status=status, label=label, statement=statement,
            cited_edition=number if cited else None, editions=named,
            evidence=evidence, official=evidence == BIS_CATALOGUE,
            source_label=_SOURCE_LABEL[evidence],
            source_url=extra.pop("source_url", source.get("url") if evidence != NO_EVIDENCE else None),
            checked_on=date, boundary=BOUNDARY.format(date=date), **extra)

    if entry.get("method") == "NOT_FOUND" or not editions:
        return out(NOT_ESTABLISHED, "Currency not established",
                   "Neither BIS's catalogue nor the mirror resolved this number, so MetrIQ "
                   "has no edition evidence for it.", evidence=NO_EVIDENCE)

    if cited is None:
        return out(NOT_ESTABLISHED, "Currency not established",
                   f"MetrIQ's record does not say which edition it cites — BIS's certification "
                   f"listing names {base} without a year — and MetrIQ's evidence records "
                   f"{len(named)} edition{'s' if len(named) > 1 else ''} ({', '.join(named)}). "
                   f"Which of them the listing refers to is not established.")

    later = [year for year in editions if year > cited]
    if later:
        newest = later[0]
        where = "BIS's own catalogue" if route == BIS_CATALOGUE else "the Public.Resource.Org mirror"
        if reaff and reaff["year"] > newest:
            return out(NOT_ESTABLISHED, "Currency not established",
                       f"{where.capitalize()} lists a later edition, {base}:{newest}, but "
                       f"{number} records a reaffirmation in {reaff['year']}, after it. The "
                       f"evidence disagrees, and MetrIQ does not choose.")
        also = f" (identical to {identical[newest]})" if identical.get(newest) else ""
        note = (f" {number} itself was reaffirmed in {reaff['year']}, before that later "
                f"edition." if reaff else "")
        return out(SUPERSEDED_BY, f"Later edition: {base}:{newest}",
                   f"MetrIQ's verified evidence shows a later edition than the one this record "
                   f"cites: {where} lists {base}:{newest}{also}.{note}",
                   later_edition=f"{base}:{newest}",
                   reaffirmed_year=reaff.get("year"), reaffirmation_quote=reaff.get("quote"))

    if reaff:
        doc = reaff["source"] == "archive_document"
        said = (f'The cover page of {number} reads "{reaff["quote"]}"' if doc else
                f"BIS's catalogue records that {number} was reaffirmed in {reaff['year']}")
        return out(REAFFIRMED, f"Reaffirmed {reaff['year']}",
                   f"{said}, and MetrIQ's evidence shows no later edition.",
                   evidence=ARCHIVE_DOCUMENT if doc else BIS_CATALOGUE,
                   reaffirmed_year=reaff["year"], reaffirmation_quote=reaff["quote"],
                   source_url=reaff.get("url"))

    if cited not in editions:
        return out(NOT_ESTABLISHED, "Currency not established",
                   f"MetrIQ's record cites {number}, which is not among the editions its "
                   f"evidence records ({', '.join(named)}), so currency is not established.")

    if route == ARCHIVE_MIRROR:
        return out(NOT_ESTABLISHED, "Currency not established",
                   f"Only the Public.Resource.Org mirror resolved this number. It holds no later "
                   f"edition than {number}, but a mirror snapshot can lag a revision, so MetrIQ "
                   f"does not treat that absence as evidence that {number} is current.")

    filled = (f" MetrIQ took the year from that same catalogue, because BIS's certification "
              f"listing names {base} without one." if year_filled else "")
    return out(ACTIVE, "Newest edition BIS lists",
               f"BIS's own catalogue, read on {date}, lists {number} as the newest edition of "
               f"this standard.{filled} A revision published after that reading would not "
               f"show here.")


# MetrIQ holds no withdrawal data. Model-written prose is re-read for this word
# and replaced with MetrIQ's own deterministic text when it appears, so no code
# path — including the optional LLM explanations — can say it about a standard.
_WITHDRAWN = re.compile(r"\bwithdrawn\b", re.IGNORECASE)


def mentions_withdrawal(text: str | None) -> bool:
    return bool(_WITHDRAWN.search(text or ""))


def distribution(standard_numbers) -> dict[str, int]:
    """Status counts over a set of standard numbers (coverage reports, tests)."""
    counts = dict.fromkeys(STATUSES, 0)
    for number in standard_numbers:
        currency = currency_for(number)
        if currency is not None:
            counts[currency.status] += 1
    return counts
