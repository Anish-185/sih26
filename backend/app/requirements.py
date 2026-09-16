"""Verified inspection requirements: load, validate, and report coverage.

Requirements live in ``data/inspection_requirements.json`` — data, not code, so
adding a verified requirement for a new standard needs no engine change.

A requirement is only accepted when it is grounded in the knowledge base:

* ``source_knowledge_id`` names a ``verified`` record in ``data/knowledge/``;
* ``source_quote`` appears word for word in that record's content;
* every ``applies_to`` entry is the exact ``standard_number`` of a verified
  ``indian_standards`` record;
* ``rule_type`` is a rule the engine implements (``RULE_TYPES``) or
  ``"not_supported"`` (a verified requirement that cannot be checked from a
  package image — it is shown to the officer, never scored);
* a checkable rule names a real declaration field and valid parameters.

Anything else is rejected with an error and never reaches the engine.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.declarations import FIELDS as DECLARATION_FIELDS

DEFAULT_REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "data" / "inspection_requirements.json"

NOT_SUPPORTED = "not_supported"

# rule_type -> {parameter name: (min, max)}. Only rules the engine implements.
RULE_TYPES: dict[str, dict[str, tuple[float, float]]] = {
    "printed_standard_number": {
        "min_ocr_confidence_pass": (0.0, 1.0),
        "min_ocr_confidence_fail": (0.0, 1.0),
    },
}

# Coverage of an identified standard.
SUPPORTED_FOR_INSPECTION = "SUPPORTED_FOR_INSPECTION"  # at least one checkable requirement
STANDARD_ONLY = "STANDARD_ONLY"  # known standard, no checkable requirement

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Requirement:
    id: str
    applies_to: tuple[str, ...]
    description: str
    rule_type: str
    source_knowledge_id: str
    source_quote: str
    declaration_field: str | None = None
    parameters: dict = field(default_factory=dict)
    unsupported_reason: str = ""

    @property
    def supported(self) -> bool:
        return self.rule_type != NOT_SUPPORTED


@dataclass(frozen=True)
class RequirementSet:
    requirements: tuple[Requirement, ...]
    errors: tuple[str, ...]

    def for_standard(self, standard_number: str | None) -> list[Requirement]:
        if not standard_number:
            return []
        return [r for r in self.requirements if standard_number in r.applies_to]

    def coverage(self, standard_number: str | None) -> str:
        return (
            SUPPORTED_FOR_INSPECTION
            if any(r.supported for r in self.for_standard(standard_number))
            else STANDARD_ONLY
        )


def load_requirements(knowledge_items, path: Path | str | None = None) -> RequirementSet:
    """Load requirements and keep only those grounded in ``knowledge_items``."""
    p = Path(path) if path else DEFAULT_REQUIREMENTS_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return RequirementSet((), (f"{p.name}: file not found",))
    except json.JSONDecodeError as exc:
        return RequirementSet((), (f"{p.name}: invalid JSON ({exc})",))

    rows = raw.get("requirements") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return RequirementSet((), (f"{p.name}: expected a 'requirements' list",))

    items = {i.id: i for i in knowledge_items}
    standards = {
        i.standard_number
        for i in knowledge_items
        if i.category == "indian_standards" and i.verification_status == "verified" and i.standard_number
    }

    accepted: list[Requirement] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        problems = _validate(row, items, standards, seen)
        where = f"{p.name}[{index}]" + (f" (id={row.get('id')})" if isinstance(row, dict) and row.get("id") else "")
        if problems:
            errors.extend(f"{where}: {msg}" for msg in problems)
            continue
        seen.add(row["id"])
        accepted.append(Requirement(
            id=row["id"],
            applies_to=tuple(row["applies_to"]),
            description=row["description"].strip(),
            rule_type=row["rule_type"],
            source_knowledge_id=row["source_knowledge_id"],
            source_quote=row["source_quote"],
            declaration_field=row.get("declaration_field"),
            parameters=dict(row.get("parameters") or {}),
            unsupported_reason=(row.get("unsupported_reason") or "").strip(),
        ))
    return RequirementSet(tuple(accepted), tuple(errors))


def _validate(row, items, standards, seen) -> list[str]:
    if not isinstance(row, dict):
        return ["requirement must be an object"]
    problems: list[str] = []

    rid = row.get("id")
    if not isinstance(rid, str) or not _ID_PATTERN.match(rid):
        problems.append("id must be a lowercase slug")
    elif rid in seen:
        problems.append("duplicate id")

    if not isinstance(row.get("description"), str) or len(row["description"].strip()) < 10:
        problems.append("description is required")

    applies_to = row.get("applies_to")
    if not isinstance(applies_to, list) or not applies_to:
        problems.append("applies_to must list at least one standard number")
    else:
        for number in applies_to:
            if number not in standards:
                problems.append(f"applies_to '{number}' is not a verified standard in the knowledge base")

    source = items.get(row.get("source_knowledge_id"))
    quote = row.get("source_quote")
    if source is None:
        problems.append(f"source_knowledge_id '{row.get('source_knowledge_id')}' is not in the knowledge base")
    elif source.verification_status != "verified":
        problems.append(f"source '{source.id}' is not a verified record")
    elif not isinstance(quote, str) or len(quote.strip()) < 20:
        problems.append("source_quote must quote the source record")
    elif quote not in source.content:
        problems.append(f"source_quote does not appear word for word in '{source.id}'")

    rule_type = row.get("rule_type")
    if rule_type == NOT_SUPPORTED:
        if not isinstance(row.get("unsupported_reason"), str) or not row["unsupported_reason"].strip():
            problems.append("a not_supported requirement needs an unsupported_reason")
    elif rule_type in RULE_TYPES:
        if row.get("declaration_field") not in DECLARATION_FIELDS:
            problems.append(f"declaration_field '{row.get('declaration_field')}' is not a declaration field")
        params = row.get("parameters") or {}
        allowed = RULE_TYPES[rule_type]
        if not isinstance(params, dict):
            problems.append("parameters must be an object")
        else:
            for name, value in params.items():
                if name not in allowed:
                    problems.append(f"unknown parameter '{name}' for rule '{rule_type}'")
                elif not isinstance(value, (int, float)) or not allowed[name][0] <= value <= allowed[name][1]:
                    problems.append(f"parameter '{name}' is out of range")
    else:
        problems.append(f"rule_type '{rule_type}' is not implemented")
    return problems
