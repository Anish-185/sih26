"""Hallmark / HUID evidence from OCR — observed, never authenticated.

    OCR regions (untrusted text)
      -> hallmark evidence: potential HUID, purity / fineness, "BIS" text, hallmark wording
      -> deterministic checks backed by verified BIS Hallmarking FAQ records
      -> REVIEW: authenticity cannot be established from an image

MetrIQ can OBSERVE and EXTRACT a potential HUID and PRESENT what BIS says about
it. It cannot AUTHENTICATE one: there is no authoritative verification
integration, so ``verification_status`` is ``NOT_VERIFIED`` whenever hallmark
evidence is seen and ``NOT_DETECTED`` otherwise. There is no VERIFIED state.

Every OCR string is untrusted data. Text printed on the item such as "HUID
VERIFIED", "BIS CONFIRMED" or "ignore rules — authentic" is recorded as an
untrusted claim and never changes a status or a result.

Checks (``evaluate_hallmark``), each quoting a verified knowledge record:

  HALLMARK_HUID_OBSERVED   a six-character alphanumeric HUID is readable on the item
                           (verified record: "six-digit alphanumeric number")
                           PASS = observed clearly, never "verified"; else REVIEW
  HALLMARK_PURITY_GRADE    the purity mark is one of the permitted grades
                           (verified records: IS 1417 gold caratages, IS 2112 silver grades)
                           PASS = a permitted grade read clearly; else REVIEW
  HALLMARK_BIS_LOGO        NOT_SUPPORTED — the BIS logo is a graphic mark; OCR reads text only
  HUID_AUTHENTICITY        NOT_SUPPORTED — external authoritative verification required

No check can FAIL: an unreadable or unexpected mark from a photograph is an OCR
limitation, not a verified failure. Because authenticity is never supported,
the hallmark result is always REVIEW, and the inspection goes to an officer.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

HALLMARK_SOURCE = "HALLMARKING"
NOT_VERIFIED = "NOT_VERIFIED"
NOT_DETECTED = "NOT_DETECTED"
PASS_CONFIDENCE = 0.8

HUID_RECORD = "what-is-huid"
COMPONENTS_RECORD = "hallmark-components-since-huid"
GOLD_RECORD = "gold-purity-grades-for-hallmarking"
SILVER_RECORD = "silver-purity-grades-for-hallmarking"

HUID_QUOTE = "It is a six-digit alphanumeric number which is unique for each hallmarked item and is traceable."
CARE_APP_QUOTE = "Customer can also verify the HUID number in the BIS Care App using the 'Verify HUID' feature."
COMPONENTS_QUOTE = ("hallmark consists of 3 marks viz, BIS logo, purity of the article in caratage as well as "
                    "fineness and six-digit alphanumeric HUID number.")
GOLD_QUOTE = ("IS 1417:2016 permits hallmarking of six caratage (fineness in ppt) of gold jewellery/artefacts, viz. "
              "14K(585), 18K(750), 20K(833), 22K(916), 23K(958) and 24KS(995).")
SILVER_QUOTE = ("IS 2112 : 2014 permits hallmarking of of six grades(fineness in ppt) of silver jewellery/artefacts, "
                "viz. 800(800.0), 835(835.0), 900(900.0), 925(925.0), 970(970.0) and 990(990.0)")

NOT_VERIFIED_NOTE = (
    "Not verified. MetrIQ has no authoritative HUID verification: image evidence alone cannot authenticate a "
    "HUID, a hallmark or the article. External authoritative verification is required — BIS says a HUID can be "
    "checked in the BIS Care App ('Verify HUID')."
)

_RE_HUID_LABEL = re.compile(r"\bH\s*U\s*I\s*D\b\s*(?:no\.?|number|#)?\s*[:\-.]?\s*([A-Za-z0-9]{1,12})?", re.IGNORECASE)
_RE_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{6})(?![A-Za-z0-9])")
_RE_GOLD_PAIR = re.compile(r"(?<![0-9])(\d{2})\s*K[TS]?\s*[-/ ]?\s*(\d{3})(?![0-9])", re.IGNORECASE)
_RE_CARAT = re.compile(r"(?<![0-9A-Za-z])(\d{2})\s*(?:K|KT|carat)(?![A-Za-z0-9])", re.IGNORECASE)
_RE_SILVER = re.compile(r"(?<![0-9])(\d{3})(?![0-9])")
_RE_SILVER_CONTEXT = re.compile(r"\bsilver\b|\bsterling\b|\bAg\b", re.IGNORECASE)
_RE_BIS = re.compile(r"\bBIS\b")
_RE_HALLMARK_WORD = re.compile(r"hall\s*mark", re.IGNORECASE)
_RE_CLAIM = re.compile(
    r"\b(verified|verify|authentic(?:ated|ity)?|genuine|certified|confirmed|approved|guaranteed|original)\b",
    re.IGNORECASE,
)
_RE_GRADE_GOLD = re.compile(r"(\d{2})KS?\((\d{3})\)")
_RE_GRADE_SILVER = re.compile(r"(\d{3})\((\d{3})\.0\)")


# ------------------------------------------------------------------ models


class HallmarkObservation(BaseModel):
    """One piece of hallmark evidence read by OCR (untrusted text, linked to its region)."""

    kind: str = Field(description='"HUID" | "PURITY" | "BIS_TEXT" | "HALLMARK_TEXT" | "UNTRUSTED_CLAIM"')
    value: str | None
    raw_text: str
    source_regions: list[str]
    image_id: str | None = None
    side: str | None = None
    bbox: list[int] | None = None
    ocr_confidence: float
    method: str = Field(description='"labelled" | "pattern" | "keyword" — how it was found')
    status: str = Field(description='"DETECTED" | "UNCERTAIN"')
    note: str = ""


class HallmarkSource(BaseModel):
    knowledge_id: str
    title: str
    quote: str
    source_url: str | None
    document_name: str | None = None
    last_verified: str | None = None


class HallmarkCheck(BaseModel):
    rule_id: str
    requirement: str
    result: str = Field(description='"PASS" | "REVIEW" | "NOT_SUPPORTED" — never FAIL')
    reason_code: str
    reason: str
    observed_value: str | None = None
    source_regions: list[str] = Field(default_factory=list)
    source: HallmarkSource | None = None


class HuidEvidence(BaseModel):
    status: str = Field(description='"DETECTED" | "UNCERTAIN" | "MULTIPLE" | "NOT_DETECTED"')
    value: str | None = Field(description="The potential HUID as read — only when exactly one clear candidate exists.")
    candidates: list[HallmarkObservation] = Field(default_factory=list)
    reason: str


class PurityEvidence(BaseModel):
    status: str = Field(description='"DETECTED" | "UNCERTAIN" | "CONFLICT" | "NOT_DETECTED"')
    metal: str | None = Field(default=None, description='"GOLD" | "SILVER" when the mark says so')
    caratage: str | None = None
    fineness: str | None = None
    permitted_grade: bool | None = Field(default=None, description="In the verified permitted-grade list.")
    candidates: list[HallmarkObservation] = Field(default_factory=list)
    reason: str


class HallmarkOut(BaseModel):
    """Hallmark evidence OBSERVED in the photos. Never an authentication."""

    detected: bool
    verification_status: str = Field(description='"NOT_VERIFIED" when hallmark evidence is seen, else "NOT_DETECTED"')
    verification_note: str
    overall_status: str = Field(description='"REVIEW" — authenticity cannot be established from an image')
    reason_code: str
    reason: str
    huid: HuidEvidence
    purity: PurityEvidence
    bis_text: list[HallmarkObservation] = Field(default_factory=list)
    hallmark_text: list[HallmarkObservation] = Field(default_factory=list)
    untrusted_claims: list[HallmarkObservation] = Field(default_factory=list)
    checks: list[HallmarkCheck] = Field(default_factory=list)
    sources: list[HallmarkSource] = Field(default_factory=list)


# ------------------------------------------------------------------ extraction


def _obs(region, kind: str, value: str | None, method: str, status: str, note: str = "") -> HallmarkObservation:
    bbox = getattr(region, "bbox", None)
    return HallmarkObservation(
        kind=kind, value=value, raw_text=region.text, source_regions=[region.id],
        image_id=getattr(region, "image_id", None), side=getattr(region, "side", None),
        bbox=list(bbox) if bbox is not None else None, ocr_confidence=round(float(region.confidence), 4),
        method=method, status=status, note=note,
    )


def _source(items: dict, knowledge_id: str, quote: str) -> HallmarkSource | None:
    """A source only when the verified record really contains the quote."""
    item = items.get(knowledge_id)
    if item is None or item.verification_status != "verified" or quote not in item.content:
        return None
    return HallmarkSource(
        knowledge_id=item.id, title=item.title, quote=quote, source_url=item.source_url,
        document_name=item.document_name, last_verified=item.last_verified.isoformat() if item.last_verified else None,
    )


def _grades(source: HallmarkSource | None, pattern: re.Pattern) -> dict[str, str]:
    return {a: b for a, b in pattern.findall(source.quote)} if source else {}


def _huid(regions) -> tuple[list[HallmarkObservation], list[HallmarkObservation]]:
    """(labelled candidates, unlabelled pattern candidates)."""
    labelled, pattern = [], []
    for r in regions:
        text = r.text or ""
        for m in _RE_HUID_LABEL.finditer(text):
            value = (m.group(1) or "").upper()
            if value.isalpha() and (len(value) != 6 or _RE_CLAIM.fullmatch(value)):
                continue  # prose after the word HUID ("HUID VERIFIED", "HUID IS ..."), not a code
            low = float(r.confidence) < PASS_CONFIDENCE
            if len(value) == 6 and re.search(r"[A-Z]", value) and re.search(r"\d", value):
                labelled.append(_obs(r, "HUID", value, "labelled", "UNCERTAIN" if low else "DETECTED",
                                     "Read with low OCR confidence." if low else ""))
            elif len(value) == 6 and value.isalnum():
                labelled.append(_obs(r, "HUID", value, "labelled", "UNCERTAIN",
                                     "Six characters, but not a mix of letters and digits — possibly an OCR misread."))
            else:
                labelled.append(_obs(r, "HUID", value or None, "labelled", "UNCERTAIN",
                                     f"A HUID label was read, but the value next to it "
                                     f"{'is missing' if not value else f'has {len(value)} characters, not six'}."))
        if _RE_HUID_LABEL.search(text):
            continue
        for m in _RE_TOKEN.finditer(text):
            token = m.group(1).upper()
            if not (re.search(r"[A-Z]", token) and re.search(r"\d", token)) or _RE_GOLD_PAIR.fullmatch(token):
                continue
            pattern.append(_obs(r, "HUID", token, "pattern", "UNCERTAIN",
                                "Six alphanumeric characters without a HUID label — may be a HUID or other text."))
    return labelled, pattern


def _purity(regions, gold: dict[str, str], silver: dict[str, str]) -> list[HallmarkObservation]:
    found = []
    for r in regions:
        text = r.text or ""
        low = float(r.confidence) < PASS_CONFIDENCE
        for m in _RE_GOLD_PAIR.finditer(text):
            carat, fine = f"{m.group(1)}K", m.group(2)
            found.append(_obs(r, "PURITY", f"{carat} {fine}", "pattern", "UNCERTAIN" if low else "DETECTED",
                              "gold caratage and fineness"))
        if not _RE_GOLD_PAIR.search(text):
            for m in _RE_CARAT.finditer(text):
                found.append(_obs(r, "PURITY", f"{m.group(1)}K", "pattern", "UNCERTAIN",
                                  "caratage without fineness"))
        if _RE_SILVER_CONTEXT.search(text):
            for m in _RE_SILVER.finditer(text):
                if m.group(1) in silver:
                    found.append(_obs(r, "PURITY", m.group(1), "pattern", "UNCERTAIN" if low else "DETECTED",
                                      "silver fineness"))
    return found


def _purity_evidence(found: list[HallmarkObservation], gold: dict[str, str], silver: dict[str, str]) -> PurityEvidence:
    if not found:
        return PurityEvidence(status="NOT_DETECTED", reason="No purity / fineness mark was read in the OCR text.")
    values = {o.value for o in found}
    if len(values) > 1:
        return PurityEvidence(status="CONFLICT", candidates=found,
                              reason=f"Different purity marks were read: {', '.join(sorted(values))}.")
    o = found[0]
    low = " — read with low OCR confidence, so it is not relied on" if o.status == "UNCERTAIN" else ""
    parts = (o.value or "").split()
    if o.note == "silver fineness":
        permitted = parts[0] in silver
        return PurityEvidence(status=o.status, metal="SILVER", fineness=parts[0], permitted_grade=permitted,
                              candidates=found, reason=f"Silver fineness {parts[0]} read{low}.")
    carat = parts[0]
    fine = parts[1] if len(parts) > 1 else None
    number = carat.rstrip("K")
    if fine is None:
        return PurityEvidence(status="UNCERTAIN", metal="GOLD", caratage=carat, candidates=found,
                              permitted_grade=None, reason=f"Caratage {carat} read without its fineness number.")
    expected = gold.get(number)
    if expected is not None and expected != fine:
        return PurityEvidence(status="CONFLICT", metal="GOLD", caratage=carat, fineness=fine, permitted_grade=False,
                              candidates=found,
                              reason=f"{carat} was read with fineness {fine}, but BIS lists {carat} as {expected}.")
    return PurityEvidence(status=o.status, metal="GOLD", caratage=carat, fineness=fine,
                          permitted_grade=expected == fine, candidates=found,
                          reason=f"Gold caratage {carat} and fineness {fine} read{low}.")


def _huid_evidence(labelled, pattern) -> HuidEvidence:
    clear = [o for o in labelled if o.status == "DETECTED"]
    values = {o.value for o in labelled if o.value} | ({o.value for o in pattern} if not labelled else set())
    if len(values) > 1:
        return HuidEvidence(status="MULTIPLE", value=None, candidates=labelled + pattern,
                            reason=f"Multiple potential HUID values were read ({', '.join(sorted(values))}); "
                                   "none is selected.")
    if clear:
        return HuidEvidence(status="DETECTED", value=clear[0].value, candidates=labelled,
                            reason=f"Potential HUID {clear[0].value} detected. It has not been verified.")
    if labelled:
        o = labelled[0]
        return HuidEvidence(status="UNCERTAIN", value=None, candidates=labelled,
                            reason=f"Potential HUID detected with low OCR confidence or an unexpected form: {o.note}")
    if pattern:
        return HuidEvidence(status="UNCERTAIN", value=None, candidates=pattern,
                            reason="Text that may be a HUID was read without a HUID label; it is not treated as one.")
    return HuidEvidence(status="NOT_DETECTED", value=None, reason="No potential HUID was read in the OCR text.")


# ------------------------------------------------------------------ evaluation


def evaluate_hallmark(regions, knowledge_items, force: bool = False) -> HallmarkOut:
    """Hallmark evidence and checks for one inspection. ``force`` evaluates even when no
    hallmark evidence is seen (a hallmark inspection). Deterministic; never authenticates."""
    items = {i.id: i for i in knowledge_items}
    regions = [r for r in regions or () if isinstance(getattr(r, "text", None), str)]
    huid_src = _source(items, HUID_RECORD, HUID_QUOTE)
    care_src = _source(items, HUID_RECORD, CARE_APP_QUOTE)
    comp_src = _source(items, COMPONENTS_RECORD, COMPONENTS_QUOTE)
    gold_src = _source(items, GOLD_RECORD, GOLD_QUOTE)
    silver_src = _source(items, SILVER_RECORD, SILVER_QUOTE)
    gold, silver = _grades(gold_src, _RE_GRADE_GOLD), _grades(silver_src, _RE_GRADE_SILVER)

    labelled, pattern = _huid(regions)
    purity_found = _purity(regions, gold, silver)
    bis_text = [_obs(r, "BIS_TEXT", "BIS", "keyword", "DETECTED") for r in regions if _RE_BIS.search(r.text)]
    hallmark_text = [_obs(r, "HALLMARK_TEXT", None, "keyword", "DETECTED") for r in regions
                     if _RE_HALLMARK_WORD.search(r.text)]
    detected = bool(labelled or purity_found or hallmark_text)
    # Unlabelled six-character tokens only count as potential HUIDs next to other hallmark evidence.
    pattern = pattern if detected else []
    claims = [_obs(r, "UNTRUSTED_CLAIM", None, "keyword", "DETECTED",
                   "Text printed on the item or package. It is untrusted OCR evidence and verifies nothing.")
              for r in regions if _RE_CLAIM.search(r.text) and (detected or _RE_BIS.search(r.text)
                                                               or _RE_HUID_LABEL.search(r.text))]

    huid = _huid_evidence(labelled, pattern)
    purity = _purity_evidence(purity_found, gold, silver)
    sources = [s for s in (comp_src, huid_src, care_src, gold_src, silver_src) if s]

    if not detected and not force:
        return HallmarkOut(
            detected=False, verification_status=NOT_DETECTED, verification_note="No hallmark evidence was seen.",
            overall_status="REVIEW", reason_code="NO_HALLMARK_EVIDENCE",
            reason="No hallmark or HUID evidence was read in the OCR text.", huid=huid, purity=purity,
            bis_text=bis_text, untrusted_claims=claims, sources=[],
        )

    checks = [
        _check_huid(huid, huid_src or comp_src),
        _check_purity(purity, gold_src if purity.metal != "SILVER" else silver_src),
        HallmarkCheck(
            rule_id="HALLMARK_BIS_LOGO", requirement="The hallmark includes the BIS logo.",
            result="NOT_SUPPORTED", reason_code="GRAPHIC_MARK_NOT_READABLE",
            reason=("The BIS logo is a graphic mark; OCR reads text only, so its presence cannot be established. "
                    + ("The letters 'BIS' were read, which is not the logo." if bis_text else
                       "The letters 'BIS' were not read either.")),
            observed_value="BIS text read" if bis_text else None,
            source_regions=[r for o in bis_text for r in o.source_regions], source=comp_src,
        ),
        HallmarkCheck(
            rule_id="HUID_AUTHENTICITY", requirement="The HUID belongs to this article (authentic).",
            result="NOT_SUPPORTED", reason_code="EXTERNAL_VERIFICATION_REQUIRED",
            reason=("External authoritative HUID verification required. MetrIQ cannot authenticate a HUID from an "
                    "image; an officer must verify it with an authoritative source such as the BIS Care App."),
            observed_value=huid.value, source=care_src,
        ),
    ]
    if detected:
        reason = ("Hallmark evidence was observed, but authenticity cannot be established from the uploaded image"
                  + (f" — potential HUID {huid.value} detected, not verified." if huid.value else ".")
                  + " An officer must verify the article.")
        code = "AUTHENTICATION_NOT_ESTABLISHED"
    else:
        reason = "No hallmark or HUID evidence was read in the OCR text of this hallmark inspection."
        code = "NO_HALLMARK_EVIDENCE"
    return HallmarkOut(
        detected=detected, verification_status=NOT_VERIFIED if detected else NOT_DETECTED,
        verification_note=NOT_VERIFIED_NOTE if detected else "No hallmark evidence was seen.",
        overall_status="REVIEW", reason_code=code, reason=reason, huid=huid, purity=purity, bis_text=bis_text,
        hallmark_text=hallmark_text, untrusted_claims=claims, checks=checks, sources=sources,
    )


def _check_huid(huid: HuidEvidence, source: HallmarkSource | None) -> HallmarkCheck:
    requirement = "A six-character alphanumeric HUID is readable on the article (observed, not verified)."
    regions = [r for o in huid.candidates for r in o.source_regions]
    if source is None:
        return HallmarkCheck(rule_id="HALLMARK_HUID_OBSERVED", requirement=requirement, result="NOT_SUPPORTED",
                             reason_code="NO_VERIFIED_SOURCE", reason="No verified record states the HUID format.",
                             source_regions=regions)
    if huid.status == "DETECTED":
        return HallmarkCheck(rule_id="HALLMARK_HUID_OBSERVED", requirement=requirement, result="PASS",
                             reason_code="HUID_OBSERVED",
                             reason=f"Potential HUID {huid.value} is readable in the six-character alphanumeric "
                                    "form BIS describes. This is an observation only — it is not verified.",
                             observed_value=huid.value, source_regions=regions, source=source)
    code = {"MULTIPLE": "HUID_MULTIPLE_CANDIDATES", "UNCERTAIN": "HUID_UNCERTAIN"}.get(huid.status, "HUID_NOT_DETECTED")
    reason = huid.reason if huid.status != "NOT_DETECTED" else (
        "No potential HUID was read. It may be too small, worn, or on a part that was not photographed — this is "
        "not a finding that the article has no HUID.")
    return HallmarkCheck(rule_id="HALLMARK_HUID_OBSERVED", requirement=requirement, result="REVIEW",
                         reason_code=code, reason=reason, source_regions=regions, source=source)


def _check_purity(purity: PurityEvidence, source: HallmarkSource | None) -> HallmarkCheck:
    requirement = "The purity mark is a grade BIS permits for hallmarking."
    regions = [r for o in purity.candidates for r in o.source_regions]
    observed = " ".join(x for x in (purity.caratage, purity.fineness) if x) or None
    if source is None:
        return HallmarkCheck(rule_id="HALLMARK_PURITY_GRADE", requirement=requirement, result="NOT_SUPPORTED",
                             reason_code="NO_VERIFIED_SOURCE", reason="No verified record lists the permitted grades.",
                             observed_value=observed, source_regions=regions)
    if purity.status == "DETECTED" and purity.permitted_grade:
        return HallmarkCheck(rule_id="HALLMARK_PURITY_GRADE", requirement=requirement, result="PASS",
                             reason_code="PERMITTED_GRADE_OBSERVED",
                             reason=f"{purity.reason} It is a permitted grade in the verified BIS list. This says "
                                    "what is marked, not what the metal actually is.",
                             observed_value=observed, source_regions=regions, source=source)
    if purity.status == "DETECTED":
        reason = (f"{purity.reason} It is not in the verified permitted-grade list — possibly an OCR misread; "
                  "an officer must check the mark.")
        code = "GRADE_NOT_IN_VERIFIED_LIST"
    else:
        code = {"CONFLICT": "PURITY_CONFLICT", "UNCERTAIN": "PURITY_UNCERTAIN"}.get(purity.status, "PURITY_NOT_DETECTED")
        reason = purity.reason if purity.status != "NOT_DETECTED" else (
            "No purity mark was read. This is not a finding that the article has none.")
    return HallmarkCheck(rule_id="HALLMARK_PURITY_GRADE", requirement=requirement, result="REVIEW",
                         reason_code=code, reason=reason, observed_value=observed, source_regions=regions,
                         source=source)
