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

Product-specific applicability. Coverage is modelled as

    PRODUCT -> STANDARD -> APPLICABLE REQUIREMENTS -> DETERMINISTIC RULES -> EVIDENCE

The optional ``products`` list names inspectable products. Each product links to
the standard(s) it falls under; a link is only accepted with a word-for-word
quote from a verified record (``applicability_status`` must be ``VERIFIED``),
and every alias must be a phrase of that standard's knowledge-base title or
keywords, so aliases are never invented. A requirement may be limited to some
products with ``applies_to_products``; without it, it applies to every product
under its standards. A standard with no product record is still usable at the
standard level.

``coverage_matrix`` turns all of this into rows
(standard | product | requirement | rule | evidence | status) so MetrIQ can say
exactly what it can and cannot inspect — derived from the data, never kept by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.declarations import FIELDS as DECLARATION_FIELDS
from app.product_identification import _contains, _tokens

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

# A product -> standard link is only usable when it is verified.
APPLICABILITY_VERIFIED = "VERIFIED"

# Coverage-matrix status of one requirement row.
ROW_SUPPORTED = "SUPPORTED"  # verified requirement with a deterministic rule
ROW_UNSUPPORTED = "UNSUPPORTED"  # verified requirement, no rule can check it from a package image
ROW_NO_REQUIREMENT_DATA = "NO_REQUIREMENT_DATA"  # standard known, no structured requirement data

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
    applies_to_products: tuple[str, ...] = ()  # empty = every product under its standards

    @property
    def supported(self) -> bool:
        return self.rule_type != NOT_SUPPORTED


@dataclass(frozen=True)
class StandardLink:
    """Verified evidence that a product falls under a standard."""

    standard_number: str
    applicability_status: str  # VERIFIED
    source_knowledge_id: str
    source_quote: str


@dataclass(frozen=True)
class InspectionProduct:
    id: str
    name: str
    aliases: tuple[str, ...]
    category: str
    standards: tuple[StandardLink, ...]

    def link(self, standard_number: str | None) -> StandardLink | None:
        return next((s for s in self.standards if s.standard_number == standard_number), None)


@dataclass(frozen=True)
class RequirementSet:
    requirements: tuple[Requirement, ...]
    errors: tuple[str, ...]
    products: tuple[InspectionProduct, ...] = ()

    def for_standard(self, standard_number: str | None) -> list[Requirement]:
        """Every requirement for the standard, whichever product it is limited to."""
        if not standard_number:
            return []
        return [r for r in self.requirements if standard_number in r.applies_to]

    def products_for_standard(self, standard_number: str | None) -> list[InspectionProduct]:
        return [p for p in self.products if p.link(standard_number)]

    def for_product(self, standard_number: str | None, product_id: str | None) -> list[Requirement]:
        """Requirements that apply to this product under this standard.

        Standard-wide requirements always apply; product-limited ones only when
        that product was confirmed (``product_id``)."""
        return [
            r for r in self.for_standard(standard_number)
            if not r.applies_to_products or (product_id is not None and product_id in r.applies_to_products)
        ]

    def coverage(self, standard_number: str | None, product_id: str | None = None) -> str:
        return (
            SUPPORTED_FOR_INSPECTION
            if any(r.supported for r in self.for_product(standard_number, product_id))
            else STANDARD_ONLY
        )

    def match_products(self, standard_number: str | None, phrases: list[str]) -> list[InspectionProduct]:
        """Products under the standard whose name or an alias appears in ``phrases``
        (package evidence text). Deterministic phrase containment, no scoring."""
        token_lists = [_tokens(p) for p in phrases if p]
        return [
            p for p in self.products_for_standard(standard_number)
            if any(_contains(tuple(_tokens(a)), toks) for a in (p.name, *p.aliases) for toks in token_lists)
        ]


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
    product_rows = raw.get("products", [])
    if not isinstance(product_rows, list):
        return RequirementSet((), (f"{p.name}: 'products' must be a list",))

    items = {i.id: i for i in knowledge_items}
    standard_items = {
        i.standard_number: i
        for i in knowledge_items
        if i.category == "indian_standards" and i.verification_status == "verified" and i.standard_number
    }
    standards = set(standard_items)

    errors: list[str] = []
    products: dict[str, InspectionProduct] = {}
    for index, row in enumerate(product_rows):
        problems = _validate_product(row, items, standard_items, products)
        where = f"{p.name}:products[{index}]" + (f" (id={row.get('id')})" if isinstance(row, dict) and row.get("id") else "")
        if problems:
            errors.extend(f"{where}: {msg}" for msg in problems)
            continue
        products[row["id"]] = InspectionProduct(
            id=row["id"], name=row["name"].strip(), aliases=tuple(a.strip() for a in row["aliases"]),
            category=row["category"].strip(),
            standards=tuple(
                StandardLink(standard_number=l["standard_number"], applicability_status=l["applicability_status"],
                             source_knowledge_id=l["source_knowledge_id"], source_quote=l["source_quote"])
                for l in row["standards"]
            ),
        )

    accepted: list[Requirement] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        problems = _validate(row, items, standards, seen, products)
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
            applies_to_products=tuple(row.get("applies_to_products") or ()),
        ))
    return RequirementSet(tuple(accepted), tuple(errors), tuple(products.values()))


def _quote_problems(knowledge_id, quote, items) -> list[str]:
    source = items.get(knowledge_id)
    if source is None:
        return [f"source_knowledge_id '{knowledge_id}' is not in the knowledge base"]
    if source.verification_status != "verified":
        return [f"source '{source.id}' is not a verified record"]
    if not isinstance(quote, str) or len(quote.strip()) < 20:
        return ["source_quote must quote the source record"]
    if quote not in source.content:
        return [f"source_quote does not appear word for word in '{source.id}'"]
    return []


def _validate_product(row, items, standard_items, products) -> list[str]:
    if not isinstance(row, dict):
        return ["product must be an object"]
    problems: list[str] = []
    pid = row.get("id")
    if not isinstance(pid, str) or not _ID_PATTERN.match(pid):
        problems.append("id must be a lowercase slug")
    elif pid in products:
        problems.append("duplicate product id")
    for key in ("name", "category"):
        if not isinstance(row.get(key), str) or len(row[key].strip()) < 3:
            problems.append(f"{key} is required")
    aliases = row.get("aliases")
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
        problems.append("aliases must be a list of phrases")
        aliases = []

    links = row.get("standards")
    if not isinstance(links, list) or not links:
        return problems + ["standards must list at least one verified standard link"]
    for link in links:
        if not isinstance(link, dict):
            problems.append("a standard link must be an object")
            continue
        number = link.get("standard_number")
        item = standard_items.get(number)
        if item is None:
            problems.append(f"standard '{number}' is not a verified standard in the knowledge base")
            continue
        if link.get("applicability_status") != APPLICABILITY_VERIFIED:
            problems.append(f"applicability_status for '{number}' must be {APPLICABILITY_VERIFIED}")
        problems.extend(f"link to '{number}': {m}" for m in
                        _quote_problems(link.get("source_knowledge_id"), link.get("source_quote"), items))
        # Aliases must come from the standard record itself — never invented.
        record_phrases = [tuple(_tokens(t)) for t in (item.title, *item.keywords)]
        for alias in aliases:
            if not any(_contains(tuple(_tokens(alias)), list(ph)) for ph in record_phrases):
                problems.append(f"alias '{alias}' is not a phrase of the title or keywords of '{number}'")
    return problems


def _validate(row, items, standards, seen, products=None) -> list[str]:
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

    problems.extend(_quote_problems(row.get("source_knowledge_id"), row.get("source_quote"), items))

    limited = row.get("applies_to_products")
    if limited is not None:
        if not isinstance(limited, list) or not limited:
            problems.append("applies_to_products must list at least one product id when given")
        else:
            for pid in limited:
                product = (products or {}).get(pid)
                if product is None:
                    problems.append(f"applies_to_products '{pid}' is not a valid product")
                elif isinstance(applies_to, list) and not any(product.link(n) for n in applies_to):
                    problems.append(f"product '{pid}' has no verified link to any standard in applies_to")

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


# ------------------------------------------------------------------ coverage matrix


@dataclass(frozen=True)
class CoverageRow:
    """One line of the coverage matrix: Product | Standard | Requirement | Rule | Evidence | Status."""

    standard_number: str
    standard_knowledge_id: str
    standard_title: str
    product_id: str | None  # None = no product record for this standard yet
    product_name: str | None
    product_category: str | None
    applicability_source: str | None  # knowledge id backing product -> standard
    requirement_id: str | None
    requirement: str | None
    rule_type: str | None  # a deterministic rule, "not_supported", or None
    declaration_field: str | None
    requirement_source: str | None  # knowledge id backing the requirement
    status: str  # SUPPORTED | UNSUPPORTED | NO_REQUIREMENT_DATA
    standard_coverage: str  # SUPPORTED_FOR_INSPECTION | STANDARD_ONLY


@dataclass(frozen=True)
class StandardCoverage:
    """Per-standard summary: what MetrIQ can currently inspect for it."""

    standard_number: str
    knowledge_id: str
    title: str
    products: list[str]  # modelled product names (empty = not modelled)
    verified_requirements: int
    deterministic_rules: int
    unsupported_requirements: int
    inspection_status: str  # SUPPORTED_FOR_INSPECTION | STANDARD_ONLY


def coverage_matrix(knowledge_items, requirements: RequirementSet) -> list[CoverageRow]:
    rows: list[CoverageRow] = []
    for item in knowledge_items:
        if item.category != "indian_standards" or item.verification_status != "verified" or not item.standard_number:
            continue
        std = item.standard_number
        base = dict(standard_number=std, standard_knowledge_id=item.id, standard_title=item.title)
        products = requirements.products_for_standard(std) or [None]
        for product in products:
            reqs = requirements.for_product(std, product.id if product else None)
            coverage = requirements.coverage(std, product.id if product else None)
            who = dict(
                product_id=product.id if product else None,
                product_name=product.name if product else None,
                product_category=product.category if product else None,
                applicability_source=product.link(std).source_knowledge_id if product else None,
            )
            if not reqs:
                rows.append(CoverageRow(**base, **who, requirement_id=None, requirement=None, rule_type=None,
                                        declaration_field=None, requirement_source=None,
                                        status=ROW_NO_REQUIREMENT_DATA, standard_coverage=coverage))
            for r in reqs:
                rows.append(CoverageRow(
                    **base, **who, requirement_id=r.id, requirement=r.description, rule_type=r.rule_type,
                    declaration_field=r.declaration_field, requirement_source=r.source_knowledge_id,
                    status=ROW_SUPPORTED if r.supported else ROW_UNSUPPORTED, standard_coverage=coverage,
                ))
    return rows


def coverage_by_standard(knowledge_items, requirements: RequirementSet) -> list[StandardCoverage]:
    out: list[StandardCoverage] = []
    for item in knowledge_items:
        if item.category != "indian_standards" or item.verification_status != "verified" or not item.standard_number:
            continue
        std = item.standard_number
        reqs = requirements.for_standard(std)
        out.append(StandardCoverage(
            standard_number=std, knowledge_id=item.id, title=item.title,
            products=[p.name for p in requirements.products_for_standard(std)],
            verified_requirements=len(reqs),
            deterministic_rules=sum(r.supported for r in reqs),
            unsupported_requirements=sum(not r.supported for r in reqs),
            inspection_status=(SUPPORTED_FOR_INSPECTION if any(r.supported for r in reqs) else STANDARD_ONLY),
        ))
    return out
