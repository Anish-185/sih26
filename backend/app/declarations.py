"""Deterministic declaration extraction.

Turns raw OCR regions into structured package declarations (``net_quantity``,
``mrp``, ``batch_number`` …). No LLM: this is regex and keyword parsing over the
OCR text, which is treated purely as data.

Every searched field comes back exactly once, with one of three states:

* ``DETECTED``     — a value was read, with the OCR region(s) it came from.
* ``UNCERTAIN``    — something was found but cannot be trusted as-is (low OCR
                     confidence, conflicting values, a label with no readable
                     value, a weak heuristic). ``reason`` says why.
* ``NOT_DETECTED`` — the field was searched for and no OCR text matched.

"Not detected" only means the OCR text did not contain it. It says nothing about
whether the declaration is legally required or legally missing.

Evidence: every DETECTED / UNCERTAIN field keeps ``source_regions`` (the OCR
region ids), the joined ``raw_text`` of those regions, their union ``bbox``, the
``image_id`` / ``source_images`` / ``source_sides`` they were read from, and the
lowest OCR confidence among them.

Multi-side packages: regions from several photos of one package are extracted
together. A label and a value are only joined inside the same photo. When the
same field is read more than once, ``observations`` keeps every reading and
``consistency`` says whether they agree (``DUPLICATE``) or not (``CONFLICT`` —
the value is withheld and the field is UNCERTAIN). Nothing is chosen silently.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Protocol

DETECTED = "DETECTED"
UNCERTAIN = "UNCERTAIN"
NOT_DETECTED = "NOT_DETECTED"

# A source region read below this OCR confidence makes its field UNCERTAIN.
LOW_OCR_CONFIDENCE = 0.6
# A region counts as "reliable text" if it has at least this confidence and a
# few letters/digits. With no reliable region the stage is NO_RELIABLE_TEXT.
RELIABLE_TEXT_CONFIDENCE = 0.5


class RegionLike(Protocol):
    id: str
    text: str
    confidence: float
    bbox: list[int]


@dataclass(frozen=True)
class Declaration:
    field: str
    label: str
    status: str  # DETECTED | UNCERTAIN | NOT_DETECTED
    value: str | None
    raw_text: str  # the OCR text of the source regions, verbatim
    source_regions: list[str]
    bbox: list[int] | None  # union of the source regions' boxes
    image_id: str | None
    ocr_confidence: float | None  # lowest OCR confidence of the source regions
    method: str  # how it was found: "regex" | "keyword" | "heuristic"
    extraction_method: str = "deterministic"
    unit: str | None = None
    numeric_value: float | None = None
    note: str = ""
    reason: str = ""  # why UNCERTAIN / NOT_DETECTED
    source_images: list[str] = field(default_factory=list)  # every image the regions came from
    source_sides: list[str] = field(default_factory=list)  # package side of each source image
    consistency: str = ""  # "SINGLE" | "DUPLICATE" | "CONFLICT" ("" when not detected)
    observations: list["Observation"] = field(default_factory=list)  # each reading, when > 1

    @property
    def source_region_id(self) -> str | None:
        return self.source_regions[0] if self.source_regions else None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    """One reading of a field on the package, kept when a field is read more than once."""

    value: str | None
    source_regions: list[str]
    source_images: list[str]
    source_sides: list[str]
    ocr_confidence: float


@dataclass(frozen=True)
class DeclarationStage:
    status: str  # "COMPLETED" | "PARTIAL" | "REVIEW" | "NO_RELIABLE_TEXT"
    fields: list[Declaration]  # every searched field, in FIELDS order
    principal_display_panel: bool
    notes: list[str] = field(default_factory=list)

    @property
    def declarations(self) -> list[Declaration]:
        """Fields with evidence (DETECTED or UNCERTAIN)."""
        return [d for d in self.fields if d.status != NOT_DETECTED]

    @property
    def found_fields(self) -> list[str]:
        return [d.field for d in self.fields if d.status == DETECTED]

    @property
    def missing_fields(self) -> list[str]:
        return [d.field for d in self.fields if d.status == NOT_DETECTED]


# field -> (label, method used to search for it). Order = display order.
FIELDS: dict[str, tuple[str, str]] = {
    "product_name": ("Product name", "heuristic"),
    "brand": ("Brand", "regex"),
    "product_description": ("Product description", "regex"),
    "net_quantity": ("Net quantity", "regex"),
    "mrp": ("MRP", "regex"),
    "manufacturer": ("Manufacturer", "keyword"),
    "packer": ("Packer", "keyword"),
    "importer": ("Importer", "keyword"),
    "manufacturer_address": ("Address", "heuristic"),
    "manufacturing_date": ("Manufacturing / packing date", "regex"),
    "batch_number": ("Batch / lot number", "regex"),
    "best_before": ("Best before", "regex"),
    "expiry_date": ("Expiry / use by", "regex"),
    "licence_number": ("Licence / registration number", "regex"),
    "standard_number": ("Indian Standard number (as printed)", "regex"),
    "fssai_license": ("FSSAI licence (food safety — not a BIS standard)", "regex"),
    "consumer_care": ("Consumer care email", "regex"),
    "toll_free": ("Consumer care phone", "regex"),
}
FIELD_LABELS: dict[str, str] = {k: v[0] for k, v in FIELDS.items()}

# Fields that decide COMPLETED vs PARTIAL. The three identity fields count once.
_IDENTITY_FIELDS = ("manufacturer", "packer", "importer")
_CORE_FIELDS = ("product_name", "net_quantity", "mrp")

_UNIT_CANON = {
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "mg": "mg",
    "ml": "ml", "milliliter": "ml", "millilitre": "ml",
    "l": "L", "ltr": "L", "litre": "L", "liter": "L", "litres": "L", "liters": "L",
    # "N" is the Legal Metrology unit for a count of articles.
    "n": "N", "u": "N", "pcs": "N", "pc": "N", "piece": "N", "pieces": "N",
}
_UNITS = r"(kgs?|kilograms?|grams?|gms?|gm|g|mg|ml|milli(?:litre|liter)|ltr|litres?|liters?|l|pcs|pc|pieces?|n|u)"


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- api


def extract_declarations(regions: Iterable[RegionLike]) -> DeclarationStage:
    regions = [r for r in regions if r is not None and isinstance(getattr(r, "text", None), str)]
    notes: list[str] = []

    if not has_reliable_text(regions):
        why = "No OCR text to extract declarations from." if not regions else (
            "OCR text is too sparse or too low-confidence to extract declarations from."
        )
        return DeclarationStage(
            status="NO_RELIABLE_TEXT",
            fields=[_not_detected(f, why) for f in FIELDS],
            principal_display_panel=False,
            notes=[why],
        )

    found: dict[str, Declaration] = {}
    for name, extractor in _EXTRACTORS:
        try:
            decl = extractor(regions)
        except Exception as exc:  # noqa: BLE001 — one bad field must not kill the stage
            notes.append(f"{name}: {exc}")
            decl = None
        if decl is not None:
            found[name] = decl

    # product_name last: it is a heuristic over "leftover" prominent text, so it
    # needs to know which regions a labelled field already claimed.
    claimed = {rid for d in found.values() for rid in d.source_regions}
    try:
        name = _product_name(regions, claimed)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"product_name: {exc}")
        name = None
    if name is not None:
        found["product_name"] = name

    fields = [found.get(f) or _not_detected(f, "No OCR text matched this field.") for f in FIELDS]

    detected = {d.field for d in fields if d.status == DETECTED}
    core_hits = sum(1 for f in _CORE_FIELDS if f in detected) + (
        1 if any(f in detected for f in _IDENTITY_FIELDS) else 0
    )
    if core_hits >= 3:
        status = "COMPLETED"
    elif any(d.status != NOT_DETECTED for d in fields):
        status = "PARTIAL"
    else:
        status = "REVIEW"
        notes.append("No recognisable declaration fields were found in the OCR text.")

    return DeclarationStage(
        status=status,
        fields=fields,
        principal_display_panel=_has_pdp(regions),
        notes=notes,
    )


def has_reliable_text(regions) -> bool:
    """At least one region read with reasonable confidence and a few letters/digits."""
    return any(
        _conf(r) >= RELIABLE_TEXT_CONFIDENCE and len(re.findall(r"[A-Za-z0-9]", r.text or "")) >= 2
        for r in regions
    )


# ------------------------------------------------------------- evidence helpers


def _conf(region) -> float:
    try:
        return float(region.confidence)
    except (TypeError, ValueError):
        return 0.0


def _not_detected(field_name: str, reason: str) -> Declaration:
    label, method = FIELDS[field_name]
    return Declaration(
        field=field_name, label=label, status=NOT_DETECTED, value=None, raw_text="",
        source_regions=[], bbox=None, image_id=None, ocr_confidence=None,
        method=method, reason=reason,
    )


def _union_bbox(regions) -> list[int] | None:
    boxes = [list(r.bbox) for r in regions if getattr(r, "bbox", None) is not None]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


@dataclass
class _Cand:
    """One candidate reading of a field, before conflicts are resolved."""

    regions: list
    value: str | None
    key: object = None  # what "same value" means for conflict checks
    unit: str | None = None
    numeric_value: float | None = None
    note: str = ""
    uncertain: str = ""  # non-empty => UNCERTAIN with this reason


def _build(
    field_name: str,
    cand: _Cand,
    method: str | None = None,
    consistency: str = "SINGLE",
    observations: tuple = (),
) -> Declaration:
    label, default_method = FIELDS[field_name]
    lowest = min(_conf(r) for r in cand.regions)
    status, reason = DETECTED, ""
    if cand.uncertain:
        status, reason = UNCERTAIN, cand.uncertain
    elif lowest < LOW_OCR_CONFIDENCE:
        status = UNCERTAIN
        reason = f"OCR read the source text with low confidence ({round(lowest * 100)}%)."
    images = _distinct_attr(cand.regions, "image_id")
    return Declaration(
        field=field_name,
        label=label,
        status=status,
        value=cand.value.strip() if cand.value else None,
        raw_text=" ".join(r.text.strip() for r in cand.regions),
        source_regions=[r.id for r in cand.regions],
        bbox=_union_bbox(cand.regions),
        image_id=images[0] if images else None,
        ocr_confidence=round(lowest, 4),
        method=method or default_method,
        unit=cand.unit,
        numeric_value=cand.numeric_value,
        note=cand.note,
        reason=reason,
        source_images=images,
        source_sides=_distinct_attr(cand.regions, "side"),
        consistency=consistency,
        observations=list(observations),
    )


def _distinct_attr(regions, name: str) -> list[str]:
    out: list[str] = []
    for r in regions:
        value = getattr(r, name, None)
        if value and value not in out:
            out.append(value)
    return out


def _where(regions) -> str:
    """'BACK I2-OCR-007' — side (when known) and region id, for reasons."""
    return ", ".join(
        f"{getattr(r, 'side')} {r.id}" if getattr(r, "side", None) else r.id for r in regions
    )


def _observation(cand: "_Cand") -> Observation:
    return Observation(
        value=cand.value,
        source_regions=[r.id for r in cand.regions],
        source_images=_distinct_attr(cand.regions, "image_id"),
        source_sides=_distinct_attr(cand.regions, "side"),
        ocr_confidence=round(min(_conf(r) for r in cand.regions), 4),
    )


def _resolve(field_name: str, cands: list[_Cand], method: str | None = None) -> Declaration | None:
    """Pick the field's reading from all candidates.

    One distinct value -> that value, linked to every region that showed it.
    Several distinct values -> UNCERTAIN, value withheld, every source kept.
    """
    if not cands:
        return None
    keys: dict[object, list[_Cand]] = {}
    for c in cands:
        keys.setdefault(c.key if c.key is not None else (c.value or "").lower(), []).append(c)

    observations = tuple(_observation(c) for c in cands) if len(cands) > 1 else ()

    if len(keys) == 1:
        group = next(iter(keys.values()))
        first = group[0]
        merged: list = []
        for c in group:
            merged.extend(r for r in c.regions if r not in merged)
        uncertain = next((c.uncertain for c in group if c.uncertain), "")
        return _build(field_name, _Cand(
            regions=merged, value=first.value, unit=first.unit,
            numeric_value=first.numeric_value, note=first.note, uncertain=uncertain,
        ), method, consistency="DUPLICATE" if len(cands) > 1 else "SINGLE", observations=observations)

    readings = "; ".join(
        f"{g[0].value} ({'; '.join(_where(c.regions) for c in g)})" for g in keys.values()
    )
    all_regions: list = []
    for c in cands:
        all_regions.extend(r for r in c.regions if r not in all_regions)
    return _build(field_name, _Cand(
        regions=all_regions, value=None,
        uncertain=f"Different values found on the package: {readings}.",
    ), method, consistency="CONFLICT", observations=observations)


def _label_only(field_name: str, regions, label: re.Pattern, what: str) -> Declaration | None:
    """A field's label is present but no value could be read next to it.

    Only counts when nothing but punctuation follows the label in its box —
    "lotNo.145/146OldPardiNaka" (an OCR-clipped "Plot No.") is not a batch label.
    """
    for r in regions:
        m = label.search(r.text)
        if m and re.fullmatch(r"[\s:.\-#()]*", r.text[m.end():]):
            return _build(field_name, _Cand(
                regions=[r], value=None,
                uncertain=f"Found the '{what}' label but could not read a value next to it.",
            ))
    return None


def _adjacent(a, b) -> bool:
    """True when b sits right after a on the label: same line to the right, or
    directly below with a small gap."""
    if getattr(a, "bbox", None) is None or getattr(b, "bbox", None) is None:
        return False
    if getattr(a, "image_id", None) != getattr(b, "image_id", None):
        return False  # boxes on different photos are never next to each other
    ax1, ay1, ax2, ay2 = a.bbox
    bx1, by1, bx2, by2 = b.bbox
    h = max(1, min(ay2 - ay1, by2 - by1))
    same_line = min(ay2, by2) - max(ay1, by1) >= 0.5 * h and bx1 >= ax1
    below = 0 <= by1 - ay2 <= 1.2 * h and min(ax2, bx2) > max(ax1, bx1)
    return same_line or below


@dataclass
class _Hit:
    regions: list
    match: re.Match
    index: int  # reading-order index of the first region


def _hits(regions, pattern: re.Pattern, valid=lambda m: True) -> list[_Hit]:
    """All matches of ``pattern``: first inside single regions, then across two
    adjacent regions (OCR often splits "MRP" and "₹20" into separate boxes).
    A two-region match must actually span the join."""
    out: list[_Hit] = []
    matched: set[int] = set()
    for i, r in enumerate(regions):
        for m in pattern.finditer(r.text):
            if valid(m):
                out.append(_Hit([r], m, i))
                matched.add(i)
    for i in range(len(regions) - 1):
        a, b = regions[i], regions[i + 1]
        if i in matched or i + 1 in matched or not _adjacent(a, b):
            continue
        left = a.text.rstrip()
        text = f"{left} {b.text.strip()}"
        for m in pattern.finditer(text):
            if m.start() < len(left) < m.end() and valid(m):
                out.append(_Hit([a, b], m, i))
    out.sort(key=lambda h: h.index)
    return out


# --------------------------------------------------------------- field extractors
#
# Each takes the region list (reading order) and returns a Declaration or None.

_MRP_LABEL = r"(?:\bm\s*\.?\s*r\s*\.?\s*p\b\.?|\bmaximum\s+retail\s+price\b)"
_RE_MRP = re.compile(
    _MRP_LABEL + r"\s*(?:\((?:incl|inclusive)[^)]*\))?\s*[:\-]?\s*"
    r"(?:rs\.?|inr|₹|rupees)?\s*(\d+(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)
_RE_MRP_LABEL = re.compile(_MRP_LABEL, re.IGNORECASE)
_RE_PRICE_BARE = re.compile(r"(?:₹|\brs\.?)\s*(\d+(?:[.,]\d{1,2})?)", re.IGNORECASE)
_RE_INCL_TAX = re.compile(r"incl(?:\.|usive)?\s*of\s*all\s*taxes", re.IGNORECASE)


def _mrp(regions):
    def cand(hit: _Hit, uncertain: str = "") -> _Cand:
        raw = hit.match.group(1)
        val = _num(raw)
        text = " ".join(r.text for r in hit.regions)
        return _Cand(
            regions=hit.regions, value=f"₹{raw}", key=val, unit="INR", numeric_value=val,
            note="inclusive of all taxes" if _RE_INCL_TAX.search(text) else "",
            uncertain=uncertain,
        )

    labelled = [cand(h) for h in _hits(regions, _RE_MRP)]
    if labelled:
        return _resolve("mrp", labelled)
    label_only = _label_only("mrp", regions, _RE_MRP_LABEL, "MRP")
    if label_only:
        return label_only
    bare = [cand(h, "A price was found without an 'MRP' label.")
            for h in _hits(regions, _RE_PRICE_BARE)]
    return _resolve("mrp", bare)


_NET_LABEL = r"\bnet\s*(?:quantity|qty|wt|weight|contents?|vol(?:ume)?)\b\.?"
_RE_NET_QTY = re.compile(
    _NET_LABEL + r"\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*" + _UNITS + r"\b",
    re.IGNORECASE,
)
_RE_NET_LABEL = re.compile(_NET_LABEL, re.IGNORECASE)
_RE_NUTRITION = re.compile(r"nutrition|serving", re.IGNORECASE)
_RE_QTY_ALONE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*" + _UNITS + r"\s*$", re.IGNORECASE)


def _qty_cand(hit: _Hit, uncertain: str = "") -> _Cand:
    raw_num, raw_unit = hit.match.group(1), hit.match.group(2).lower()
    unit = _UNIT_CANON.get(raw_unit, raw_unit)
    val = _num(raw_num)
    return _Cand(regions=hit.regions, value=f"{raw_num} {unit}", key=(val, unit),
                 unit=unit, numeric_value=val, uncertain=uncertain)


def _net_quantity(regions):
    labelled = [_qty_cand(h) for h in _hits(regions, _RE_NET_QTY)]
    if labelled:
        return _resolve("net_quantity", labelled)
    label_only = _label_only("net_quantity", regions, _RE_NET_LABEL, "Net quantity")
    if label_only:
        return label_only
    if any(_RE_NUTRITION.search(r.text) for r in regions):
        return None  # lone quantities next to a nutrition table are serving sizes
    bare = [_qty_cand(h, "A quantity was printed without a 'Net quantity' label.")
            for h in _hits(regions, _RE_QTY_ALONE)]
    return _resolve("net_quantity", bare)


_RE_PARTY = re.compile(
    r"\b(manufactured\s*(?:&|and)\s*packed|manufactured|mfd\.?|mfg\.?|produced|"
    r"marketed|packed|imported)\s*by\b\s*[:\-]?\s*(.*)",
    re.IGNORECASE,
)


def _party_name(raw: str) -> str:
    who = raw.strip(" :.-")
    # Stop where the address starts.
    who = re.split(r"\s{2,}|,\s*(?=plot|no\.|\d)|\s+plot\s+\d|\s+\d{1,4}[/,-]", who, flags=re.I)[0]
    return who.strip(" :.-,")


def _parties(regions) -> dict[str, list[_Cand]]:
    out: dict[str, list[_Cand]] = {"manufacturer": [], "packer": [], "importer": []}
    valid = lambda m: len(re.findall(r"[A-Za-z]", _party_name(m.group(2)))) >= 2  # noqa: E731
    for hit in _hits(regions, _RE_PARTY, valid=valid):
        verb = re.sub(r"\s+", " ", hit.match.group(1).lower())
        name = _party_name(hit.match.group(2))
        c = _Cand(regions=hit.regions, value=name, note=f"declared as '{verb} by'")
        if verb.startswith("imported"):
            out["importer"].append(c)
        elif verb.startswith("packed"):
            out["packer"].append(c)
        elif verb.startswith("marketed"):
            c.uncertain = "The label says 'marketed by' — a marketer is not necessarily the manufacturer."
            out["manufacturer"].append(c)
        else:
            out["manufacturer"].append(c)
    return out


def _manufacturer(regions):
    return _resolve("manufacturer", _parties(regions)["manufacturer"])


def _packer(regions):
    return _resolve("packer", _parties(regions)["packer"])


def _importer(regions):
    return _resolve("importer", _parties(regions)["importer"])


_RE_PIN = re.compile(r"\b(\d{6})\b")
_STATES = (
    "andhra pradesh|arunachal|assam|bihar|chhattisgarh|goa|gujarat|haryana|himachal|"
    "jharkhand|karnataka|kerala|madhya pradesh|maharashtra|manipur|meghalaya|mizoram|"
    "nagaland|odisha|orissa|punjab|rajasthan|sikkim|tamil nadu|telangana|tripura|"
    "uttar pradesh|uttarakhand|west bengal|delhi|puducherry|chandigarh|jammu"
)
_RE_STATE = re.compile(_STATES, re.IGNORECASE)
_RE_ADDRESS_TOKENS = re.compile(
    r"\b(road|rd|street|plot|lane|nagar|industrial|area|estate|midc|gidc|sipcot|sector|phase|dist)\b",
    re.IGNORECASE,
)


def _manufacturer_address(regions):
    cands = [
        _Cand(regions=[r], value=r.text.strip(), key=re.sub(r"\W+", "", r.text.lower()),
              note="line with a 6-digit PIN code and address words")
        for r in regions
        if _RE_PIN.search(r.text) and "," in r.text
        and (_RE_STATE.search(r.text) or _RE_ADDRESS_TOKENS.search(r.text))
    ]
    return _resolve("manufacturer_address", cands)


_DATE = (
    r"(?<!\d)(\d{1,2}[/\-.]\d{1,2}[/\-.](?:\d{4}|\d{2})|\d{1,2}[/\-.]\d{4}|\d{1,2}[/\-.]\d{2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s/\-.,]*(?:\d{4}|\d{2}))(?!\d)"
)
# Full words ("packaging") only count with "date"/"on" — a bare "PACKAGING" can be
# the second line of a wrapped "DATE OF / PACKAGING" label sitting beside a
# different row's value (seen on a real pack, where it grabbed the expiry date).
_MFG_LABEL = (
    r"(?:\bdate\s*of\s*(?:manufacture|mfg|packing|packaging)\b"
    r"|\b(?:manufacturing|packing|packaging)\s*(?:date|dt)\b"
    r"|\b(?:mfg|mfd|pkd)\b\.?\s*(?:date|dt|on)?\b"
    r"|\bmanufactured\s+on\b|\bpacked\s+on\b)"
)
_RE_MFG_DATE = re.compile(_MFG_LABEL + r"\.?\s*[:\-]?\s*" + _DATE, re.IGNORECASE)
_RE_MFG_LABEL = re.compile(
    r"\b(?:mfg|mfd|pkd)\.?\s*(?:date|dt)\b|\b(?:manufacturing|packing|packaging)\s+date\b"
    r"|\bdate\s+of\s+(?:manufacture|packing|packaging)\b",
    re.IGNORECASE,
)


def _date_cands(regions, pattern: re.Pattern) -> list[_Cand]:
    out = []
    for h in _hits(regions, pattern):
        raw = h.match.group(h.match.lastindex).strip()
        out.append(_Cand(regions=h.regions, value=raw, key=re.sub(r"[\s/\-.,]+", "/", raw.lower())))
    return out


def _manufacturing_date(regions):
    cands = _date_cands(regions, _RE_MFG_DATE)
    if cands:
        return _resolve("manufacturing_date", cands)
    return _label_only("manufacturing_date", regions, _RE_MFG_LABEL, "Manufacturing date")


_BATCH_LABEL = r"(?:\b(?:batch|lot)\s*(?:no|number|code)?\b\.?|\bb\.\s*no\b\.?)"
_RE_BATCH = re.compile(
    _BATCH_LABEL + r"\s*[:\-#]?\s*((?=[A-Z0-9\-/]*\d)[A-Z0-9][A-Z0-9\-/]{2,})",
    re.IGNORECASE,
)
_RE_BATCH_LABEL = re.compile(_BATCH_LABEL, re.IGNORECASE)


def _looks_like_code(value: str) -> bool:
    # Batch codes are short codes, not words: "Plot No. 145/146 Old Pardi Naka"
    # read as "lotNo.145/146OldPardiNaka" must not become a batch number.
    return len(value) <= 20 and not re.search(r"[a-z]{4,}", value)


def _batch_number(regions):
    cands = [
        _Cand(regions=h.regions, value=h.match.group(1).strip(" .-/"),
              key=h.match.group(1).strip(" .-/").upper())
        for h in _hits(regions, _RE_BATCH, valid=lambda m: _looks_like_code(m.group(1).strip(" .-/")))
    ]
    if cands:
        return _resolve("batch_number", cands)
    return _label_only("batch_number", regions, _RE_BATCH_LABEL, "Batch")


_BEST_LABEL = r"\b(?:best\s*before|consume\s*before|best\s*if\s*used\s*before)\b"
_RE_BEST_BEFORE = re.compile(
    _BEST_LABEL + r"\s*(?:use\b)?\.?\s*[:\-]?\s*"
    r"(" + _DATE + r"|\d+\s*(?:days?|weeks?|months?|years?)\b[^;|]{0,60})",
    re.IGNORECASE,
)
_RE_BEST_LABEL = re.compile(_BEST_LABEL, re.IGNORECASE)


def _best_before(regions):
    cands = [
        _Cand(regions=h.regions, value=h.match.group(1).strip(" .:-"),
              key=re.sub(r"\s+", " ", h.match.group(1).strip(" .:-").lower()))
        for h in _hits(regions, _RE_BEST_BEFORE)
    ]
    if cands:
        return _resolve("best_before", cands)
    return _label_only("best_before", regions, _RE_BEST_LABEL, "Best before")


_EXP_LABEL = r"(?:\bexpiry(?:\s*d?ate)?|\bexp\b\.?(?:\s*date)?|\buse\s*by\b|\bexpires?\b(?:\s*on)?)"
_RE_EXPIRY = re.compile(_EXP_LABEL + r"\s*(?:date|dt)?\.?\s*[:\-]?\s*" + _DATE, re.IGNORECASE)
_RE_EXP_LABEL = re.compile(r"\bexpiry(?:\s*d?ate)?|\bexp\.?\s*date\b|\buse\s*by\b", re.IGNORECASE)


def _expiry_date(regions):
    cands = _date_cands(regions, _RE_EXPIRY)
    if cands:
        return _resolve("expiry_date", cands)
    return _label_only("expiry_date", regions, _RE_EXP_LABEL, "Expiry")


# "IS" is matched case-sensitively so ordinary words ("this is") do not match.
_RE_STANDARD = re.compile(
    r"(?<![A-Za-z])I\s?\.?\s?S(?![A-Za-z])\.?\s*[:\-]?\s*(\d{3,5})"
    r"(?:\s*\(\s*[Pp](?:ar)?t\.?\s*[-:]?\s*(\d{1,2})\s*\))?"
    r"(?:\s*[:\-]\s*((?:19|20)\d{2}))?"
    r"(?![\d%])(?!\s*(?:%|kgs?\b|g\b|gm\b|mg\b|ml\b|l\b|ltr\b))"
)


def _standard_number(regions):
    cands = []
    for h in _hits(regions, _RE_STANDARD):
        number, part, year = h.match.group(1), h.match.group(2), h.match.group(3)
        value = f"IS {number}" + (f" (Part {part})" if part else "") + (f":{year}" if year else "")
        short = len(number) == 3 and not year and not part
        cands.append(_Cand(
            regions=h.regions, value=value, key=value,
            note="Standard number as printed on the label — read from OCR, not verified against BIS.",
            uncertain=("A short number after 'IS' could be ordinary text rather than a standard."
                       if short else ""),
        ))
    if not cands:
        return None
    distinct: list[_Cand] = []
    for c in cands:  # several different IS numbers on one label is normal
        if all(c.value != d.value for d in distinct):
            distinct.append(c)
    if len(distinct) == 1:
        return _resolve("standard_number", cands)
    regions_all: list = []
    for c in cands:
        regions_all.extend(r for r in c.regions if r not in regions_all)
    return _build("standard_number", _Cand(
        regions=regions_all, value=", ".join(c.value for c in distinct),
        note=distinct[0].note,
        uncertain=next((c.uncertain for c in distinct if c.uncertain), ""),
    ))


# No leading \b: OCR often joins it to the previous word ("ISI MarkedCM/L-1234567").
_RE_CML = re.compile(r"CM\s*/\s*L\s*[-:]?\s*(\d{7,10})\b", re.IGNORECASE)
_RE_REG = re.compile(
    r"\b(?:reg(?:istration)?|regn)\b\.?\s*(?:no|number)\b\.?\s*[:\-]?\s*([A-Z]{1,3}-?\d{6,}|\d{6,})",
    re.IGNORECASE,
)
_RE_LIC = re.compile(
    r"\blic(?:ence|ense)?\b\.?\s*(?:no|number)\b\.?\s*[:\-]?\s*((?=[A-Z0-9/\-]*\d)[A-Z0-9][A-Z0-9/\-]{4,})",
    re.IGNORECASE,
)
_RE_FSSAI_WORD = re.compile(r"f\.?\s*s\.?\s*s\.?\s*a\.?\s*i", re.IGNORECASE)


def _licence_number(regions):
    cml = [_Cand(regions=h.regions, value=f"CM/L-{h.match.group(1)}",
                 note="BIS licence number format (CM/L) as printed — not verified.")
           for h in _hits(regions, _RE_CML)]
    if cml:
        return _resolve("licence_number", cml)
    reg = [_Cand(regions=h.regions, value=h.match.group(1).upper(),
                 note="Registration number as printed — not verified.")
           for h in _hits(regions, _RE_REG)]
    if reg:
        return _resolve("licence_number", reg)
    lic = [_Cand(regions=h.regions, value=h.match.group(1).upper(),
                 uncertain="A licence number was found but the issuing authority is not stated.")
           for h in _hits(regions, _RE_LIC)
           if not any(_RE_FSSAI_WORD.search(r.text) for r in h.regions)]  # FSSAI has its own field
    return _resolve("licence_number", lic)


_RE_BRAND = re.compile(r"\bbrand(?:\s*name)?\s*[:\-]\s*([A-Za-z0-9][^,;|]{1,40})", re.IGNORECASE)
_RE_TRADEMARK = re.compile(r"([A-Za-z][A-Za-z0-9&'.\- ]{1,30}?)\s*[®™]")


def _brand(regions):
    labelled = [_Cand(regions=h.regions, value=h.match.group(1).strip(),
                      note="labelled 'Brand' on the package")
                for h in _hits(regions, _RE_BRAND)]
    if labelled:
        return _resolve("brand", labelled)
    marked = [_Cand(regions=h.regions, value=h.match.group(1).strip(), note="name marked with ® or ™")
              for h in _hits(regions, _RE_TRADEMARK)]
    return _resolve("brand", marked)


_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


_RE_EMAIL_TLD = re.compile(r"^(.+?\.(?:com|in|org|net|co\.in|gov\.in|info|biz|example))[a-z]+$", re.IGNORECASE)


def _consumer_care(regions):
    cands = []
    for h in _hits(regions, _RE_EMAIL):
        email, note = h.match.group(0), ""
        m = _RE_EMAIL_TLD.match(email)
        if m:  # OCR joined the next words: "haldirams.comandfor"
            email, note = m.group(1), f"OCR joined text after the address ('{email}'); trimmed at the domain ending."
        cands.append(_Cand(regions=h.regions, value=email, key=email.lower(), note=note))
    return _resolve("consumer_care", cands)


_RE_TOLLFREE = re.compile(
    r"(?:toll\s*free|customer\s*care|helpline|consumer\s*care)\D{0,12}"
    r"(1\s?800[\s\-]?\d{2,4}[\s\-]?\d{3,4}|\d{3,5}[\s\-]?\d{3,4}[\s\-]?\d{3,4})",
    re.IGNORECASE,
)
_RE_1800 = re.compile(r"\b(1\s?800[\s\-]?\d{2,4}[\s\-]?\d{3,4})\b")


def _toll_free(regions):
    for pattern in (_RE_TOLLFREE, _RE_1800):
        cands = [_Cand(regions=h.regions, value=re.sub(r"\s+", " ", h.match.group(1)).strip(),
                       key=re.sub(r"\D", "", h.match.group(1)))
                 for h in _hits(regions, pattern)]
        if cands:
            return _resolve("toll_free", cands)
    return None


_RE_FSSAI = re.compile(
    r"(?:fssai|f\.?\s*s\.?\s*s\.?\s*a\.?\s*i\.?)\D{0,20}(\d[\d\s]{11,16}\d)",
    re.IGNORECASE,
)


def _fssai_license(regions):
    cands = []
    for h in _hits(regions, _RE_FSSAI):
        digits = re.sub(r"\D", "", h.match.group(1))
        if len(digits) >= 12:
            cands.append(_Cand(
                regions=h.regions, value=digits, key=digits,
                note="FSSAI food-safety licence — a food regulator ID, NOT an Indian Standard",
            ))
    return _resolve("fssai_license", cands)


_RE_PDP = re.compile(r"principal\s*display\s*panel|principal\s*display", re.IGNORECASE)


def _has_pdp(regions) -> bool:
    for r in regions:
        squashed = re.sub(r"\s+", "", r.text).lower()
        if "principaldisplay" in squashed or _RE_PDP.search(r.text):
            return True
    return False


_RE_PARENS = re.compile(r"^\s*\((.+)\)\s*$")


def _product_description(regions):
    cands = []
    for r in regions:
        m = _RE_PARENS.match(r.text)
        if m and len(m.group(1).split()) >= 2:
            cands.append(_Cand(regions=[r], value=m.group(1).strip()))
    return _resolve("product_description", cands)


_LABEL_WORDS = re.compile(
    r"\b(net|quantity|qty|mrp|price|batch|lot|mfg|mfd|pkd|packed|manufactured|marketed|imported|"
    r"best before|use by|expiry|exp|fssai|consumer|toll|care|licence|license|lic|reg|date|address|"
    r"brand|ingredients?|nutrit\w*|information|serving|servings|calories|energy|daily value|"
    r"storage|store|allergens?|contains|rda|recommended|dietary|keep|clean|recycle|"
    r"protein|carbohydrates?|fat|sugars?|sodium|cholesterol|fib(?:re|er)|kcal|extra|offer|"
    r"www\.|http|@|display panel)\b",
    re.IGNORECASE,
)
# The product name must be printed noticeably larger than the typical line.
_NAME_MIN_HEIGHT_RATIO = 1.25
_NAME_MIN_MARGIN = 1.15


def _text_size(region) -> int:
    x1, y1, x2, y2 = region.bbox
    return min(x2 - x1, y2 - y1)


def _product_name(regions, claimed_region_ids: set[str]):
    """The product name, chosen separately on each photo (text size is only
    comparable within one photo), then merged like any other field."""
    by_image: dict[object, list] = {}
    for r in regions:
        by_image.setdefault(getattr(r, "image_id", None), []).append(r)
    cands = [c for group in by_image.values() if (c := _product_name_on_image(group, claimed_region_ids))]
    return _resolve("product_name", cands)


def _product_name_on_image(regions, claimed_region_ids: set[str]) -> _Cand | None:
    """Heuristic: the most prominent line that is not a labelled field.

    Prominence = text size relative to the median line, preferring earlier and
    mostly-uppercase lines. Text size is the box's shorter side, so a line
    printed vertically (common on bottle labels) is not mistaken for huge text. DETECTED only when that line is clearly
    larger than the rest; otherwise UNCERTAIN with the reason recorded.
    """
    heights = sorted(_text_size(r) for r in regions if getattr(r, "bbox", None) is not None)
    median_h = heights[len(heights) // 2] if heights else 0

    candidates = []
    for i, r in enumerate(regions):
        t = r.text.strip()
        if not t or r.id in claimed_region_ids:
            continue
        squashed = re.sub(r"\s+", "", t).lower()
        if "principaldisplay" in squashed or _RE_PDP.search(t):
            continue
        if _LABEL_WORDS.search(t) or _RE_PARENS.match(t) or re.search(r"\d{3,}|[,%]", t):
            continue
        words = re.findall(r"[A-Za-z][A-Za-z&'-]*", t)
        if not (1 <= len(words) <= 6):
            continue
        letters = re.sub(r"[^A-Za-z]", "", t)
        if len(letters) < 4:
            continue
        upper_ratio = sum(c.isupper() for c in letters) / len(letters)
        h = _text_size(r) if getattr(r, "bbox", None) is not None else 0
        size = h / median_h if median_h else 1.0
        if median_h and size < _NAME_MIN_HEIGHT_RATIO:
            continue  # not printed noticeably larger than typical text — not offered
        score = size + 0.3 * upper_ratio - 0.02 * i
        candidates.append((score, size, r, t, len(words)))

    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[0])
    _, size, r, t, word_count = candidates[0]
    runner_up = candidates[1][1] if len(candidates) > 1 else 0.0

    uncertain = ""
    if not median_h:
        uncertain = "No text sizes available, so the product name cannot be told apart from other lines."
    elif runner_up and size < runner_up * _NAME_MIN_MARGIN:
        uncertain = f"Another unlabelled line is printed at a similar size ('{candidates[1][3]}')."
    elif word_count == 1:
        uncertain = "The most prominent line is a single word — it could be the brand rather than the product name."

    value = t.title() if t.isupper() else t
    return _Cand(
        regions=[r], value=value, key=re.sub(r"\W+", "", value.lower()), uncertain=uncertain,
        note="most prominent unlabelled line on the panel",
    )


_EXTRACTORS = (
    ("brand", _brand),
    ("product_description", _product_description),
    ("net_quantity", _net_quantity),
    ("mrp", _mrp),
    ("manufacturer", _manufacturer),
    ("packer", _packer),
    ("importer", _importer),
    ("manufacturer_address", _manufacturer_address),
    ("manufacturing_date", _manufacturing_date),
    ("batch_number", _batch_number),
    ("best_before", _best_before),
    ("expiry_date", _expiry_date),
    ("licence_number", _licence_number),
    ("standard_number", _standard_number),
    ("fssai_license", _fssai_license),
    ("consumer_care", _consumer_care),
    ("toll_free", _toll_free),
)
