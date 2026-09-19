"""BIS testing laboratories: a verified snapshot, and deterministic lookup over it.

    standard  ->  the laboratories BIS's own LIMS lists for that standard
    product   ->  (existing ProductStandardFinder)  ->  standard  ->  laboratories

The data is a snapshot of BIS's Laboratory Information Management System
("IS-wise test facilities in BIS / recognised / empanelled laboratories"),
ingested by ``scripts/fetch_lims_laboratories.py`` into ``data/laboratories.json``.
Nothing here calls the network: the application reads the snapshot.

What makes a laboratory relevant to a standard is that BIS ITSELF LISTS IT
against that standard. Relevance is never inferred from a laboratory's name,
its city, or the fact that it is a testing laboratory — those can only ever be
extra signals ON a record that already matched a standard, or a plain name/city
lookup the user explicitly asked for.

Deliberately NOT done here:

* No ranking. Results are ordered alphabetically by laboratory name, which is
  neutral. MetrIQ does not have the evidence to call one laboratory better,
  more suitable or recommended than another, so it does not order by score.
* No accreditation claim. The snapshot says a laboratory is listed in LIMS for
  a standard. It does not say the laboratory is NABL accredited, and MetrIQ
  never says so.
* No current status. A snapshot has a date. MetrIQ reports the recognition
  validity date LIMS printed and whether it had passed AS AT THE SNAPSHOT, and
  says plainly that current scope and availability must be confirmed with the
  laboratory.
* No field is ever invented. A value the snapshot does not contain is reported
  as not available in the record.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "laboratories.json"

NOT_AVAILABLE = "Not available in the verified MetrIQ record."

CURRENTNESS_NOTE = (
    "Confirm current scope, availability and contact details with the laboratory "
    "before arranging testing."
)
SNAPSHOT_NOTE = (
    "MetrIQ identifies laboratories from verified laboratory evidence. It does not "
    "independently establish a laboratory's current accreditation, scope, availability "
    "or operational status."
)
NO_MATCH = (
    "No matching verified laboratory record was found in MetrIQ's knowledge base. "
    "That is a statement about MetrIQ's coverage, not about which laboratories exist — "
    "use the official BIS list of recognised / empanelled laboratories and the BIS LIMS "
    "portal for the complete and current picture."
)

# Recognition validity, as at the snapshot date. Never "currently valid".
VALID_AT_SNAPSHOT = "VALID_AT_SNAPSHOT"
EXPIRED_AT_SNAPSHOT = "EXPIRED_AT_SNAPSHOT"
VALIDITY_UNKNOWN = "NOT_STATED"

# Why a record was returned. Only signals that actually occurred are attached.
STANDARD_LISTED = "STANDARD_LISTED"
PRODUCT_LISTED = "PRODUCT_LISTED"
NAME_MATCH = "NAME_MATCH"
CITY_MATCH = "CITY_MATCH"


# ------------------------------------------------------- standard identity

_PART = re.compile(r"\bpart\s*([0-9]+)", re.I)
_SEC = re.compile(r"\b(?:sec|section)\s*([0-9]+)", re.I)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_DOC = re.compile(r"\bIS\s*/?\s*(?:IEC\s*)?[:\-]?\s*([0-9]{1,6})", re.I)


@dataclass(frozen=True)
class StandardKey:
    """A standard's identity, precise enough that parts never collide.

    ``standard_number_key`` in the retrieval layer reduces both
    "IS 302 (Part 2/Sec 3)" and "IS 302 (Part 2/Sec 201)" to ("302", "") — fine
    for ranking a search, but it would make an electric-iron laboratory look
    like a kettle laboratory here. Part and section are therefore part of the
    key, and a mismatch in either means NOT the same standard.
    """

    doc: str
    part: str = ""
    section: str = ""
    year: str = ""

    def matches(self, other: "StandardKey") -> bool:
        if self.doc != other.doc or self.part != other.part or self.section != other.section:
            return False
        # BIS lists a standard with or without its year. Differing years are a
        # different edition and do not match; a missing year on either side is
        # the same standard as listed.
        return not (self.year and other.year) or self.year == other.year


def standard_key(text: str | None) -> StandardKey | None:
    """'IS 367:1993' and 'IS 367 (1993)' -> the same key. None when no number."""
    if not text:
        return None
    doc = _DOC.search(text)
    if not doc:
        return None
    part = _PART.search(text)
    section = _SEC.search(text)
    year = _YEAR.search(text)
    return StandardKey(
        doc=doc.group(1),
        part=part.group(1) if part else "",
        section=section.group(1) if section else "",
        year=year.group(0) if year else "",
    )


# --------------------------------------------------------------- records


@dataclass(frozen=True)
class LabRecord:
    """One laboratory, as BIS LIMS listed it for one Indian Standard."""

    lab_name: str
    osl_code: str
    city: str | None
    standard_as_listed: str
    product_as_listed: str
    grade_or_type: str | None
    validity_date: str | None
    remark: str | None
    source_url: str
    source_organization: str
    document_name: str
    retrieved_on: str

    @property
    def key(self) -> StandardKey | None:
        return standard_key(self.standard_as_listed)

    def validity(self, today: date | None = None) -> tuple[str, str | None]:
        """(status, ISO date). Always 'as at the snapshot', never 'currently'."""
        if not self.validity_date:
            return VALIDITY_UNKNOWN, None
        try:
            parsed = datetime.strptime(self.validity_date.strip(), "%d %b, %Y").date()
        except ValueError:
            return VALIDITY_UNKNOWN, None
        reference = today or date.today()
        status = VALID_AT_SNAPSHOT if parsed >= reference else EXPIRED_AT_SNAPSHOT
        return status, parsed.isoformat()


@dataclass(frozen=True)
class WhyLaboratory:
    """Deterministic 'Why this result?' for one laboratory record.

    Built only from what actually matched. Never a judgement about quality:
    there is no "best", "recommended" or "most suitable" laboratory here.
    """

    signals: list[str]
    summary: str


@dataclass(frozen=True)
class LabMatch:
    record: LabRecord
    why: WhyLaboratory
    matched_standard: str | None = None


@dataclass(frozen=True)
class LabRegistry:
    """The loaded snapshot. Deterministic, read-only, no network."""

    records: list[LabRecord] = field(default_factory=list)
    source: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    # ---------------------------------------------------------- coverage

    @property
    def standards_covered(self) -> set[str]:
        return {r.standard_as_listed for r in self.records}

    @property
    def laboratory_names(self) -> set[str]:
        return {r.lab_name for r in self.records}

    def coverage(self) -> dict:
        cities = {r.city for r in self.records if r.city}
        return {
            "records": len(self.records),
            "laboratories": len(self.laboratory_names),
            "standards": len(self.standards_covered),
            "with_city": sum(1 for r in self.records if r.city),
            "with_validity_date": sum(1 for r in self.records if r.validity_date),
            "retrieved_on": self.source.get("retrieved_on"),
            "cities": sorted(cities),
        }

    def covers_standard(self, standard_number: str | None) -> bool:
        return bool(self.for_standard(standard_number))

    def other_editions(self, standard_number: str | None) -> list[str]:
        """Other editions of the SAME standard that LIMS lists separately.

        BIS lists, for example, both "IS 14543 (2016)" and "IS 14543 (2024)".
        A different edition is a different standard, so it never joins the
        matched results — but staying silent about it would make MetrIQ's
        coverage look smaller than BIS's listing actually is, so it is reported.
        """
        wanted = standard_key(standard_number)
        if wanted is None:
            return []
        out: list[str] = []
        for record in self.records:
            key = record.key
            if key is None or key.doc != wanted.doc:
                continue
            if key.part != wanted.part or key.section != wanted.section:
                continue
            if key.matches(wanted):
                continue
            if record.standard_as_listed not in out:
                out.append(record.standard_as_listed)
        return sorted(out)

    # ----------------------------------------------------------- lookup

    def for_standard(self, standard_number: str | None) -> list[LabMatch]:
        """Laboratories BIS LIMS explicitly lists against this standard.

        The ONLY way a standard -> laboratory relationship is established.
        """
        wanted = standard_key(standard_number)
        if wanted is None:
            return []
        out: list[LabMatch] = []
        for record in self.records:
            key = record.key
            if key is None or not key.matches(wanted):
                continue
            out.append(LabMatch(
                record=record,
                matched_standard=record.standard_as_listed,
                why=WhyLaboratory(
                    signals=[STANDARD_LISTED],
                    summary=(
                        f"Relevant because the verified BIS LIMS record explicitly lists "
                        f"{record.standard_as_listed} for this laboratory."
                    ),
                ),
            ))
        return _ordered(out)

    def search(self, query: str = "", standard_number: str | None = None) -> list[LabMatch]:
        """Deterministic search by standard, laboratory name, city or product text.

        A standard match is a capability statement by BIS. A name or city match
        is NOT: it only says the text matched, and the summary says exactly that.
        """
        text = (query or "").strip()
        if standard_number:
            matches = self.for_standard(standard_number)
            return _ordered([_add_text_signals(m, text) for m in matches]) if text else matches

        if not text:
            return []

        # A standard named in the query is the strongest thing we can honour.
        named = standard_key(text)
        if named is not None:
            matches = self.for_standard(text)
            if matches:
                return matches

        needle = _norm(text)
        if len(needle) < 3:
            return []
        # "laboratories in Noida" must find Noida, so the query's own words are
        # tried too — but only words long enough to be a name or a place, and
        # never the filler words that would match everything.
        tokens = [w for w in needle.split() if len(w) >= 4 and w not in _QUERY_NOISE]

        def hit(field: str | None) -> str | None:
            """The term that actually matched, so the explanation can name it.

            A single query word must match a WHOLE word. Substring matching
            makes "Tell me a joke" find "InterSTELLar Testing Centre", which is
            exactly the false relevance this module exists to prevent. The full
            phrase may still match as a substring, because that is the user
            quoting a name ("TUV Rheinland").
            """
            if not field:
                return None
            value = _norm(field)
            if len(needle.split()) > 1 and needle in value:
                return text.strip()
            words = set(value.split())
            for token in tokens:
                if token in words:
                    return token
            if len(tokens) == 1 and tokens[0] == needle and needle in words:
                return text.strip()
            return None

        out: list[LabMatch] = []
        seen: set[tuple[str, str]] = set()
        for record in self.records:
            signals: list[str] = []
            name_term = hit(record.lab_name)
            city_term = hit(record.city)
            if name_term:
                signals.append(NAME_MATCH)
            if city_term:
                signals.append(CITY_MATCH)
            if needle in _norm(record.product_as_listed):
                signals.append(PRODUCT_LISTED)
            if not signals:
                continue
            # A standard-driven hit is per (laboratory, standard); a name or
            # city hit is about the laboratory itself, so it appears once.
            identity = ((record.lab_name, record.standard_as_listed)
                        if PRODUCT_LISTED in signals else (record.lab_name, ""))
            if identity in seen:
                continue
            seen.add(identity)
            out.append(LabMatch(
                record=record,
                matched_standard=record.standard_as_listed if PRODUCT_LISTED in signals else None,
                why=WhyLaboratory(
                    signals=signals,
                    summary=_summary(record, signals, name_term or city_term or text),
                ),
            ))
        return _ordered(out)


# Words that appear in a laboratory question but say nothing about WHICH
# laboratory. Matching on them would return the whole snapshot.
_QUERY_NOISE = frozenset({
    "lab", "labs", "laboratory", "laboratories", "test", "tests", "testing",
    "where", "which", "what", "near", "list", "find", "show", "please",
    "india", "indian", "standard", "standards", "bis", "recognised",
    "recognized", "empanelled", "accredited", "centre", "center", "product",
    "products", "from", "with", "that", "this", "have", "there", "about",
})


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _ordered(matches: list[LabMatch]) -> list[LabMatch]:
    """Alphabetical by laboratory name, then by the standard as listed.

    Deliberately NOT a relevance ranking — MetrIQ has no evidence that would
    justify putting one listed laboratory above another.
    """
    return sorted(matches, key=lambda m: (m.record.lab_name.lower(), m.record.standard_as_listed))


def _add_text_signals(match: LabMatch, text: str) -> LabMatch:
    needle = _norm(text)
    signals = list(match.why.signals)
    if needle and len(needle) >= 3:
        if needle in _norm(match.record.lab_name) and NAME_MATCH not in signals:
            signals.append(NAME_MATCH)
        if match.record.city and needle in _norm(match.record.city) and CITY_MATCH not in signals:
            signals.append(CITY_MATCH)
    if signals == match.why.signals:
        return match
    return LabMatch(record=match.record, matched_standard=match.matched_standard,
                    why=WhyLaboratory(signals=signals, summary=_summary(match.record, signals, text)))


def _summary(record: LabRecord, signals: list[str], query: str) -> str:
    parts: list[str] = []
    if STANDARD_LISTED in signals or PRODUCT_LISTED in signals:
        parts.append(
            f"the verified BIS LIMS record explicitly lists {record.standard_as_listed} "
            f"for this laboratory"
        )
    if NAME_MATCH in signals:
        parts.append(f"the laboratory's name matches \"{query.strip()}\"")
    if CITY_MATCH in signals and record.city:
        parts.append(f"the laboratory is listed in {record.city}")
    if not parts:
        return "Returned from the verified BIS LIMS snapshot."
    body = parts[0] if len(parts) == 1 else ", and ".join([", ".join(parts[:-1]), parts[-1]])
    return f"Relevant because {body}."


# ----------------------------------------------------------------- loading


def load_laboratories(path: Path | None = None) -> LabRegistry:
    """Read the snapshot. A malformed file yields an EMPTY registry plus errors —
    never a partially-guessed one, and never an exception that breaks a request."""
    source_path = path or DATA_FILE
    if not source_path.exists():
        return LabRegistry(errors=[f"laboratory snapshot not found: {source_path}"])
    try:
        payload = json.loads(source_path.read_text())
    except (OSError, ValueError) as exc:
        return LabRegistry(errors=[f"laboratory snapshot could not be read: {exc}"])

    if not isinstance(payload, dict) or not isinstance(payload.get("laboratories"), list):
        return LabRegistry(errors=["laboratory snapshot has no 'laboratories' list"])

    required = ("lab_name", "standard_as_listed", "source_url")
    records: list[LabRecord] = []
    errors: list[str] = []
    for index, raw in enumerate(payload["laboratories"]):
        if not isinstance(raw, dict):
            errors.append(f"record {index}: not an object")
            continue
        missing = [f for f in required if not (raw.get(f) or "").strip()]
        if missing:
            errors.append(f"record {index}: missing {', '.join(missing)}")
            continue
        records.append(LabRecord(
            lab_name=raw["lab_name"].strip(),
            osl_code=(raw.get("osl_code") or "").strip(),
            city=(raw.get("city") or None),
            standard_as_listed=raw["standard_as_listed"].strip(),
            product_as_listed=(raw.get("product_as_listed") or "").strip(),
            grade_or_type=raw.get("grade_or_type") or None,
            validity_date=raw.get("validity_date") or None,
            remark=raw.get("remark") or None,
            source_url=raw["source_url"].strip(),
            source_organization=(raw.get("source_organization")
                                 or "Bureau of Indian Standards (BIS)").strip(),
            document_name=(raw.get("document_name") or "BIS LIMS").strip(),
            retrieved_on=(raw.get("retrieved_on") or "").strip(),
        ))
    return LabRegistry(records=records, source=payload.get("source") or {}, errors=errors)
