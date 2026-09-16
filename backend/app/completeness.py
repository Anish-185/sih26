"""Declaration completeness for one inspected package.

For every declaration field MetrIQ searches for, report two separate facts:

* ``status`` — what the OCR evidence shows, straight from declaration
  extraction: DETECTED, UNCERTAIN (low confidence, a label with no readable
  value, or CONFLICT between photos) or NOT_DETECTED.
* ``requirement_coverage`` — what MetrIQ knows about whether the field is
  required: ``VERIFIED_REQUIREMENT`` when a verified, checkable requirement for
  the identified standard uses this field, otherwise ``NOT_ESTABLISHED``.

NOT_DETECTED only ever means "not found in the OCR text of the uploaded
photos". It is never reported as legally missing: no verified requirement in
the knowledge base currently says any declaration field must appear, and even
where one does, the compliance check — not this view — decides the result.
When some photos could not be read, a field not found elsewhere is marked as
undeterminable for those photos. Deterministic; no model involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.declarations import DETECTED, NOT_DETECTED, UNCERTAIN, DeclarationStage
from app.requirements import RequirementSet

VERIFIED_REQUIREMENT = "VERIFIED_REQUIREMENT"
NOT_ESTABLISHED = "NOT_ESTABLISHED"


@dataclass(frozen=True)
class CompletenessItem:
    field: str
    label: str
    status: str  # DETECTED | UNCERTAIN | NOT_DETECTED
    conflict: bool
    value: str | None
    statement: str  # factual, never "missing"
    requirement_coverage: str  # VERIFIED_REQUIREMENT | NOT_ESTABLISHED
    requirement_ids: list[str]
    source_sides: list[str]
    source_images: list[str]
    source_regions: list[str]
    raw_text: str
    ocr_confidence: float | None


@dataclass(frozen=True)
class DeclarationCompleteness:
    standard_number: str | None
    items: list[CompletenessItem]
    detected: int
    uncertain: int
    not_detected: int
    conflicts: int
    with_verified_requirement: int
    unreadable_images: list[str] = field(default_factory=list)
    note: str = (
        "Detection status describes the OCR evidence from the uploaded photos only. "
        "\"Not detected\" only means it was not found in these photos; it is not a finding about the "
        "package and not a legal determination."
    )


def _where(sides: list[str], regions: list[str]) -> str:
    named = [s for s in sides if s and s != "UNKNOWN"]
    regions_text = ", ".join(regions)
    return f"{' + '.join(named)} ({regions_text})" if named else regions_text


def declaration_completeness(
    declarations: DeclarationStage,
    requirements: RequirementSet,
    standard_number: str | None,
    unreadable_images: list[str] | tuple = (),
) -> DeclarationCompleteness:
    unreadable = list(unreadable_images)
    required_by: dict[str, list[str]] = {}
    for req in requirements.for_standard(standard_number):
        if req.supported and req.declaration_field:
            required_by.setdefault(req.declaration_field, []).append(req.id)

    items: list[CompletenessItem] = []
    for d in declarations.fields:
        conflict = d.consistency == "CONFLICT"
        if d.status == DETECTED:
            statement = f"Detected on {_where(d.source_sides, d.source_regions)}."
            if d.consistency == "DUPLICATE":
                statement = f"Detected with the same value on {_where(d.source_sides, d.source_regions)}."
        elif conflict:
            readings = "; ".join(
                f"{o.value} on {_where(o.source_sides, o.source_regions)}" for o in d.observations
            )
            statement = f"Conflicting values across the package ({readings}); no value was chosen."
        elif d.status == UNCERTAIN:
            statement = f"Uncertain: {d.reason}"
        else:
            statement = "Not detected in the OCR text of the uploaded images."
            if unreadable:
                statement += (
                    f" {', '.join(unreadable)} gave no usable OCR evidence, so it cannot be "
                    "determined whether it appears there."
                )

        ids = required_by.get(d.field, [])
        items.append(CompletenessItem(
            field=d.field, label=d.label, status=d.status, conflict=conflict, value=d.value,
            statement=statement,
            requirement_coverage=VERIFIED_REQUIREMENT if ids else NOT_ESTABLISHED,
            requirement_ids=list(ids),
            source_sides=list(d.source_sides), source_images=list(d.source_images),
            source_regions=list(d.source_regions), raw_text=d.raw_text, ocr_confidence=d.ocr_confidence,
        ))

    return DeclarationCompleteness(
        standard_number=standard_number,
        items=items,
        detected=sum(i.status == DETECTED for i in items),
        uncertain=sum(i.status == UNCERTAIN for i in items),
        not_detected=sum(i.status == NOT_DETECTED for i in items),
        conflicts=sum(i.conflict for i in items),
        with_verified_requirement=sum(i.requirement_coverage == VERIFIED_REQUIREMENT for i in items),
        unreadable_images=unreadable,
    )
