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
  package image — it is shown to the user, never scored);
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

Domains. Knowledge is not interchangeable across inspection contexts. Every
requirement declares a ``domain`` (``PACKAGE_LABEL`` by default); package
inspection only ever applies ``PACKAGE_LABEL`` requirements. A knowledge record
is ``JEWELLERY_HALLMARKING`` when it is in the hallmarking category or its title
is about hallmarks / HUID / jewellery (``knowledge_domain``). A PACKAGE_LABEL
requirement or product link may not rely on such a record or standard, and its
quote may not be about hallmarks or HUID — jewellery facts can never become
package-label rules by accident.

Sources. A requirement's source record belongs to one authority
(``source_authority`` in the knowledge base): ``BIS`` or ``LEGAL_METROLOGY``. The
two are never mixed up:

* a ``STANDARD``-scope requirement (the default) applies to BIS standards
  (``applies_to``) and must quote a BIS record;
* a ``PACKAGED_COMMODITY``-scope requirement applies to pre-packaged
  commodities in general — it has no ``applies_to`` — and must quote a Legal
  Metrology record (e.g. the Legal Metrology (Packaged Commodities) Rules, 2011).

Its ``source_category`` (BIS / LEGAL_METROLOGY) is taken from that record, so a
Legal Metrology requirement is never shown as a BIS requirement.

Legal Metrology applicability. The ``package_scope`` object states when the
packaged-commodity requirements apply at all (Rule 3 of the Packaged Commodities
Rules), with quotes. ``exclusions`` name conditions that are observable on a
package label (e.g. a declared quantity above 25 kg / 25 L, or "not for retail
sale") and are implemented deterministically (``EXCLUSION_TYPES``);
``assumptions`` are applicability conditions a label cannot show (e.g. that the
package is not meant for an industrial consumer) — they are stated with every
result, never assumed silently. A requirement may add its own exclusions (e.g.
food articles, for which Rule 6(1)(a) does not apply). Supporting quotes
(``supporting_sources``) — an amendment, a related sub-rule — are validated the
same way as the main quote.

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
    # Every listed declaration group has reliable evidence. Never FAILs.
    "field_present": {
        "min_ocr_confidence_pass": (0.0, 1.0),
    },
    # A declared value has the form the verified requirement states (``format``).
    "value_format": {
        "min_ocr_confidence_pass": (0.0, 1.0),
        "min_ocr_confidence_fail": (0.0, 1.0),
    },
    # A declared date shows what the verified requirement states (``format``). Never FAILs.
    "date_format": {
        "min_ocr_confidence_pass": (0.0, 1.0),
    },
}

# format -> (rule_type, declaration field it reads). Each rule_type/format pair is data only;
# no engine evaluates it since MetrIQ produces no automatic compliance verdict.
RULE_FORMATS: dict[str, tuple[str, str]] = {
    "retail_sale_price_inclusive_of_taxes_in_indian_currency": ("value_format", "mrp"),
    "net_quantity_in_standard_units": ("value_format", "net_quantity"),
    "month_and_year": ("date_format", "manufacturing_date"),
}

# Source authorities (knowledge-base ``source_authority``).
BIS = "BIS"
LEGAL_METROLOGY = "LEGAL_METROLOGY"

# Requirement scopes.
SCOPE_STANDARD = "STANDARD"  # applies to the BIS standards in ``applies_to``
SCOPE_PACKAGED_COMMODITY = "PACKAGED_COMMODITY"  # applies to pre-packaged commodities in general
SCOPE_AUTHORITY = {SCOPE_STANDARD: BIS, SCOPE_PACKAGED_COMMODITY: LEGAL_METROLOGY}

# Exclusion id -> where it may be used. Data only; MetrIQ does not evaluate exclusions into a verdict.
EXCLUSION_TYPES: dict[str, str] = {
    "NET_QUANTITY_ABOVE_25_KG_OR_25_L": "package",
    "NOT_FOR_RETAIL_SALE_DECLARED": "package",
    "FOOD_ARTICLE_FSSAI_LICENCE": "requirement",
}

# Coverage of an identified standard (package inspection).
INSPECTION_SUPPORTED = "INSPECTION_SUPPORTED"  # at least one verified, image-checkable package-label requirement
STANDARD_ONLY = "STANDARD_ONLY"  # verified and retrievable, but no image-checkable requirement data (not a failure)
UNSUPPORTED = "UNSUPPORTED"  # cannot currently be mapped to package-label inspection at all

# Evidence / requirement domains.
PACKAGE_LABEL = "PACKAGE_LABEL"
JEWELLERY_HALLMARKING = "JEWELLERY_HALLMARKING"
GENERAL_BIS_INFORMATION = "GENERAL_BIS_INFORMATION"
DOMAINS = (PACKAGE_LABEL, JEWELLERY_HALLMARKING, GENERAL_BIS_INFORMATION)
_RE_HALLMARK = re.compile(r"hallmark|\bhuid\b|jewell", re.IGNORECASE)

# A product -> standard link is only usable when it is verified.
APPLICABILITY_VERIFIED = "VERIFIED"

# Which modelled product the package is, under the identified standard
# (``confirm_product``). Pure requirements-lookup; no rule is run.
PRODUCT_CONFIRMED = "PRODUCT_CONFIRMED"  # the package text names exactly one modelled product
PRODUCT_NOT_MODELLED = "PRODUCT_NOT_MODELLED"  # no product record for this standard (standard-level data only)
PRODUCT_NOT_CONFIRMED = "PRODUCT_NOT_CONFIRMED"  # products are modelled, the package text names none of them
PRODUCT_AMBIGUOUS = "PRODUCT_AMBIGUOUS"  # the package text names more than one modelled product

# Coverage-matrix status of one requirement row.
ROW_SUPPORTED = "SUPPORTED"  # verified requirement with a deterministic rule
ROW_UNSUPPORTED = "UNSUPPORTED"  # verified requirement, no rule can check it from a package image
ROW_NO_REQUIREMENT_DATA = "NO_REQUIREMENT_DATA"  # standard known, no structured requirement data

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class SourceQuote:
    """A word-for-word quote from a verified knowledge-base record."""

    knowledge_id: str
    quote: str


@dataclass(frozen=True)
class Exclusion:
    """An observable condition under which requirements do not apply, with its quotes."""

    id: str  # EXCLUSION_TYPES key
    description: str
    sources: tuple[SourceQuote, ...]


@dataclass(frozen=True)
class PackageScope:
    """When Legal Metrology packaged-commodity requirements apply at all."""

    description: str
    source: SourceQuote
    exclusions: tuple[Exclusion, ...]
    assumptions: tuple[str, ...]  # applicability conditions a package label cannot show
    assumption_sources: tuple[SourceQuote, ...] = ()


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
    domain: str = PACKAGE_LABEL
    scope: str = SCOPE_STANDARD
    source_category: str = BIS  # authority of the source record: BIS | LEGAL_METROLOGY
    reference: str = ""  # e.g. "Rule 6(1)(e)"
    # Declaration groups the rule reads: every group needs one field with evidence.
    declaration_groups: tuple[tuple[str, ...], ...] = ()
    format: str | None = None
    require_same_image: bool = False  # all groups' evidence must be on one photo
    exclusions: tuple[Exclusion, ...] = ()
    supporting_sources: tuple[SourceQuote, ...] = ()
    applicability: str = ""  # who / what the requirement applies to, from its sources

    @property
    def supported(self) -> bool:
        return self.rule_type != NOT_SUPPORTED

    @property
    def fields(self) -> tuple[str, ...]:
        """Every declaration field the rule reads."""
        if self.declaration_groups:
            return tuple(f for group in self.declaration_groups for f in group)
        return (self.declaration_field,) if self.declaration_field else ()


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
    package_scope: PackageScope | None = None

    def for_standard(self, standard_number: str | None) -> list[Requirement]:
        """Every package-label requirement for the standard, whichever product it is limited to.
        Requirements of any other domain are never used by package inspection."""
        if not standard_number:
            return []
        return [r for r in self.requirements
                if r.scope == SCOPE_STANDARD and standard_number in r.applies_to and r.domain == PACKAGE_LABEL]

    def for_package(self) -> list[Requirement]:
        """Legal Metrology package-label requirements for pre-packaged commodities.
        Applicability (scope exclusions, requirement exclusions) is decided per package
        reported for information only; without a valid package scope none are returned."""
        if self.package_scope is None:
            return []
        return [r for r in self.requirements if r.scope == SCOPE_PACKAGED_COMMODITY and r.domain == PACKAGE_LABEL]

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
            INSPECTION_SUPPORTED
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


def confirm_product(product, requirements: RequirementSet):
    """Which modelled product (``RequirementSet.products``) this package is, under
    ``product.standard_number`` — using only the phrases and label text product
    identification already matched. Deterministic containment; no new scoring
    and no rule is run. Returns ``(applicability, confirmed_or_None, candidates)``."""
    standard = product.standard_number
    modelled = requirements.products_for_standard(standard)
    if not modelled:
        return PRODUCT_NOT_MODELLED, None, []
    phrases: list[str] = []
    for ev in product.evidence:
        if ev.match in ("product", "alias"):
            phrases.extend(t for t in (ev.matched_phrase, ev.clue.text, ev.clue.search_text) if t)
    matched = requirements.match_products(standard, phrases)
    if len(matched) == 1:
        return PRODUCT_CONFIRMED, matched[0], matched
    if len(matched) > 1:
        return PRODUCT_AMBIGUOUS, None, matched
    return PRODUCT_NOT_CONFIRMED, None, modelled


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
    errors: list[str] = []
    package_scope = None
    if raw.get("package_scope") is not None:
        package_scope, scope_problems = _parse_package_scope(raw["package_scope"], items)
        errors.extend(f"{p.name}:package_scope: {msg}" for msg in scope_problems)
    standard_items = {
        i.standard_number: i
        for i in knowledge_items
        if i.category == "indian_standards" and i.verification_status == "verified" and i.standard_number
    }
    standards = set(standard_items)

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
        problems = _validate(row, items, standards, seen, products, standard_items, package_scope)
        where = f"{p.name}[{index}]" + (f" (id={row.get('id')})" if isinstance(row, dict) and row.get("id") else "")
        if problems:
            errors.extend(f"{where}: {msg}" for msg in problems)
            continue
        seen.add(row["id"])
        groups = row.get("declaration_fields")
        accepted.append(Requirement(
            id=row["id"],
            applies_to=tuple(row.get("applies_to") or ()),
            description=row["description"].strip(),
            rule_type=row["rule_type"],
            source_knowledge_id=row["source_knowledge_id"],
            source_quote=row["source_quote"],
            declaration_field=row.get("declaration_field"),
            parameters=dict(row.get("parameters") or {}),
            unsupported_reason=(row.get("unsupported_reason") or "").strip(),
            applies_to_products=tuple(row.get("applies_to_products") or ()),
            domain=row.get("domain", PACKAGE_LABEL),
            scope=row.get("scope", SCOPE_STANDARD),
            source_category=_authority(items[row["source_knowledge_id"]]),
            reference=(row.get("reference") or "").strip(),
            declaration_groups=tuple(tuple(g) for g in groups) if groups else (),
            format=row.get("format"),
            require_same_image=bool(row.get("require_same_image", False)),
            exclusions=tuple(_exclusion(e) for e in row.get("exclusions") or ()),
            supporting_sources=tuple(_quotes(row.get("supporting_sources"))),
            applicability=(row.get("applicability") or "").strip(),
        ))
    return RequirementSet(tuple(accepted), tuple(errors), tuple(products.values()), package_scope)


def _authority(item) -> str:
    return getattr(item, "source_authority", BIS) or BIS


def _quotes(rows) -> list[SourceQuote]:
    return [SourceQuote(knowledge_id=r["source_knowledge_id"], quote=r["source_quote"]) for r in rows or ()]


def _exclusion(row) -> Exclusion:
    return Exclusion(id=row["id"], description=row["description"].strip(), sources=tuple(_quotes(row["sources"])))


def _quote_list_problems(rows, items, authority: str, what: str) -> list[str]:
    """Validate a list of {source_knowledge_id, source_quote} from records of ``authority``."""
    if not isinstance(rows, list) or not rows:
        return [f"{what} must list at least one source quote"]
    problems: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            problems.append(f"{what}: a source quote must be an object")
            continue
        kid = row.get("source_knowledge_id")
        found = _quote_problems(kid, row.get("source_quote"), items)
        problems.extend(f"{what}: {m}" for m in found)
        if not found and _authority(items[kid]) != authority:
            problems.append(f"{what}: source '{kid}' is not a {authority} record")
    return problems


def _exclusion_problems(rows, items, kind: str) -> list[str]:
    if not isinstance(rows, list):
        return ["exclusions must be a list"]
    problems: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            problems.append("an exclusion must be an object")
            continue
        eid = row.get("id")
        if EXCLUSION_TYPES.get(eid) != kind:
            problems.append(f"exclusion '{eid}' is not an implemented {kind} exclusion")
        if not isinstance(row.get("description"), str) or len(row["description"].strip()) < 10:
            problems.append(f"exclusion '{eid}' needs a description")
        problems.extend(_quote_list_problems(row.get("sources"), items, LEGAL_METROLOGY, f"exclusion '{eid}'"))
    return problems


def _parse_package_scope(row, items) -> tuple[PackageScope | None, list[str]]:
    """The Legal Metrology package scope. Returns (None, problems) when invalid."""
    if not isinstance(row, dict):
        return None, ["package_scope must be an object"]
    problems: list[str] = []
    if not isinstance(row.get("description"), str) or len(row["description"].strip()) < 10:
        problems.append("description is required")
    problems.extend(_quote_list_problems(
        [{"source_knowledge_id": row.get("source_knowledge_id"), "source_quote": row.get("source_quote")}],
        items, LEGAL_METROLOGY, "scope source"))
    problems.extend(_exclusion_problems(row.get("exclusions", []), items, "package"))
    assumptions = row.get("assumptions", [])
    if not isinstance(assumptions, list) or not all(isinstance(a, str) and a.strip() for a in assumptions):
        problems.append("assumptions must be a list of statements")
    if row.get("assumption_sources"):
        problems.extend(_quote_list_problems(row["assumption_sources"], items, LEGAL_METROLOGY, "assumption source"))
    if problems:
        return None, problems
    return PackageScope(
        description=row["description"].strip(),
        source=SourceQuote(row["source_knowledge_id"], row["source_quote"]),
        exclusions=tuple(_exclusion(e) for e in row.get("exclusions", [])),
        assumptions=tuple(a.strip() for a in assumptions),
        assumption_sources=tuple(_quotes(row.get("assumption_sources"))),
    ), []


def knowledge_domain(item) -> str:
    """JEWELLERY_HALLMARKING for hallmarking records and standards, else GENERAL_BIS_INFORMATION.
    Deterministic, from the record's category and title only."""
    if item.category == "hallmarking" or _RE_HALLMARK.search(item.title):
        return JEWELLERY_HALLMARKING
    return GENERAL_BIS_INFORMATION


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
        if knowledge_domain(item) == JEWELLERY_HALLMARKING:
            problems.append(f"standard '{number}' is a jewellery hallmarking standard, not a package-label product")
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


def _validate(row, items, standards, seen, products=None, standards_by_number=None, package_scope=None) -> list[str]:
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

    scope = row.get("scope", SCOPE_STANDARD)
    applies_to = row.get("applies_to")
    if scope not in SCOPE_AUTHORITY:
        problems.append(f"scope '{scope}' must be one of {', '.join(SCOPE_AUTHORITY)}")
    elif scope == SCOPE_STANDARD:
        if not isinstance(applies_to, list) or not applies_to:
            problems.append("applies_to must list at least one standard number")
        else:
            for number in applies_to:
                if number not in standards:
                    problems.append(f"applies_to '{number}' is not a verified standard in the knowledge base")
    else:
        # A packaged-commodity requirement is not tied to any BIS standard or product.
        if applies_to or row.get("applies_to_products"):
            problems.append("a PACKAGED_COMMODITY requirement must not set applies_to or applies_to_products")
        if package_scope is None:
            problems.append("a PACKAGED_COMMODITY requirement needs a valid package_scope")
        if not isinstance(row.get("reference"), str) or not row["reference"].strip():
            problems.append("a PACKAGED_COMMODITY requirement needs a reference (rule / clause)")
        if row.get("exclusions") is not None:
            problems.extend(_exclusion_problems(row["exclusions"], items, "requirement"))

    quote_problems = _quote_problems(row.get("source_knowledge_id"), row.get("source_quote"), items)
    problems.extend(quote_problems)
    expected_authority = SCOPE_AUTHORITY.get(scope)
    if not quote_problems and expected_authority and _authority(items[row["source_knowledge_id"]]) != expected_authority:
        problems.append(
            f"source '{row['source_knowledge_id']}' is not a {expected_authority} record; a {scope} requirement "
            f"must quote {expected_authority} evidence"
        )
    if row.get("supporting_sources") is not None and expected_authority:
        problems.extend(_quote_list_problems(row["supporting_sources"], items, expected_authority, "supporting source"))

    domain = row.get("domain", PACKAGE_LABEL)
    if domain not in DOMAINS:
        problems.append(f"domain '{domain}' must be one of {', '.join(DOMAINS)}")
    elif domain == PACKAGE_LABEL:
        # Jewellery hallmark / HUID facts must never become package-label rules.
        source = items.get(row.get("source_knowledge_id"))
        if source is not None and knowledge_domain(source) == JEWELLERY_HALLMARKING:
            problems.append(f"source '{source.id}' is jewellery hallmarking evidence, not package-label evidence")
        elif isinstance(row.get("source_quote"), str) and _RE_HALLMARK.search(row["source_quote"]):
            problems.append("source_quote is about hallmarks / HUID, not package-label evidence")
        for number in applies_to if isinstance(applies_to, list) else []:
            item = standards_by_number.get(number) if standards_by_number else None
            if item is not None and knowledge_domain(item) == JEWELLERY_HALLMARKING:
                problems.append(f"applies_to '{number}' is a jewellery hallmarking standard, not a package-label product")

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
        groups = row.get("declaration_fields")
        if groups is not None:
            if rule_type != "field_present":
                problems.append("declaration_fields (groups) is only used by field_present; use declaration_field")
            elif (not isinstance(groups, list) or not groups
                  or not all(isinstance(g, list) and g and all(f in DECLARATION_FIELDS for f in g) for g in groups)):
                problems.append("declaration_fields must be a list of non-empty lists of declaration fields")
        elif row.get("declaration_field") not in DECLARATION_FIELDS:
            problems.append(f"declaration_field '{row.get('declaration_field')}' is not a declaration field")
        if rule_type in ("value_format", "date_format"):
            fmt = row.get("format")
            if RULE_FORMATS.get(fmt, (None,))[0] != rule_type:
                problems.append(f"format '{fmt}' is not implemented for rule '{rule_type}'")
            elif RULE_FORMATS[fmt][1] != row.get("declaration_field"):
                problems.append(f"format '{fmt}' reads declaration field '{RULE_FORMATS[fmt][1]}'")
        elif row.get("format") is not None:
            problems.append(f"rule '{rule_type}' does not take a format")
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
    standard_coverage: str  # INSPECTION_SUPPORTED | STANDARD_ONLY | UNSUPPORTED


@dataclass(frozen=True)
class StandardCoverage:
    """Per-standard summary: what MetrIQ can currently inspect for it, and why."""

    standard_number: str
    knowledge_id: str
    title: str
    domain: str  # GENERAL_BIS_INFORMATION | JEWELLERY_HALLMARKING
    products: list[str]  # modelled product names (empty = not modelled)
    certification_route: str | None  # as recorded in the KB: "Scheme I (ISI Mark)" | "Scheme II (CRS registration)"
    source_document: str | None
    source_url: str | None
    verified_requirements: int  # package-label requirements
    deterministic_rules: int  # of those, checkable from package text
    unsupported_requirements: int
    requirement_ids: list[str]
    coverage_status: str  # INSPECTION_SUPPORTED | STANDARD_ONLY | UNSUPPORTED
    reason: str


def certification_route(item) -> str | None:
    """The certification route the knowledge-base record itself states — reported, never a rule."""
    keywords = set(item.keywords)
    if keywords & {"crs", "compulsory registration"} or "Compulsory Registration Scheme" in item.content:
        return "Scheme II (CRS registration)"
    if "compulsory certification" in keywords or "ISI Mark" in item.content:
        return "Scheme I (ISI Mark)"
    return None


def standard_coverage(item, requirements: RequirementSet) -> tuple[str, str]:
    """(coverage_status, reason) for one verified standard record. Deterministic."""
    std = item.standard_number
    if knowledge_domain(item) == JEWELLERY_HALLMARKING:
        return UNSUPPORTED, (
            "Jewellery hallmarking / assaying standard. Its verified facts (hallmark marks, HUID, purity "
            "grades) describe marks on jewellery, not package labels, so package-label inspection does not apply."
        )
    reqs = requirements.for_standard(std)
    rules = [r for r in reqs if r.supported]
    if rules:
        return INSPECTION_SUPPORTED, (
            f"{len(rules)} of {len(reqs)} verified package-label requirement(s) can be checked from package "
            f"text ({', '.join(r.id for r in rules)})."
        )
    route = certification_route(item)
    route_note = (
        f" The knowledge base records its certification route as {route}; that is not checkable from "
        "package text and is not encoded as a rule." if route else ""
    )
    if reqs:
        return STANDARD_ONLY, (
            f"{len(reqs)} verified requirement(s) ({', '.join(r.id for r in reqs)}), none checkable from a "
            f"package image.{route_note}"
        )
    return STANDARD_ONLY, f"No verified image-checkable requirement data.{route_note}"


def _standard_records(knowledge_items):
    return [
        i for i in knowledge_items
        if i.category == "indian_standards" and i.verification_status == "verified" and i.standard_number
    ]


def coverage_matrix(knowledge_items, requirements: RequirementSet) -> list[CoverageRow]:
    rows: list[CoverageRow] = []
    for item in _standard_records(knowledge_items):
        std = item.standard_number
        status, _ = standard_coverage(item, requirements)
        base = dict(standard_number=std, standard_knowledge_id=item.id, standard_title=item.title)
        products = requirements.products_for_standard(std) or [None]
        for product in products:
            reqs = requirements.for_product(std, product.id if product else None)
            who = dict(
                product_id=product.id if product else None,
                product_name=product.name if product else None,
                product_category=product.category if product else None,
                applicability_source=product.link(std).source_knowledge_id if product else None,
            )
            if not reqs:
                rows.append(CoverageRow(**base, **who, requirement_id=None, requirement=None, rule_type=None,
                                        declaration_field=None, requirement_source=None,
                                        status=ROW_NO_REQUIREMENT_DATA, standard_coverage=status))
            for r in reqs:
                rows.append(CoverageRow(
                    **base, **who, requirement_id=r.id, requirement=r.description, rule_type=r.rule_type,
                    declaration_field=r.declaration_field, requirement_source=r.source_knowledge_id,
                    status=ROW_SUPPORTED if r.supported else ROW_UNSUPPORTED, standard_coverage=status,
                ))
    return rows


def coverage_by_standard(knowledge_items, requirements: RequirementSet) -> list[StandardCoverage]:
    out: list[StandardCoverage] = []
    for item in _standard_records(knowledge_items):
        std = item.standard_number
        reqs = requirements.for_standard(std)
        status, reason = standard_coverage(item, requirements)
        out.append(StandardCoverage(
            standard_number=std, knowledge_id=item.id, title=item.title, domain=knowledge_domain(item),
            products=[p.name for p in requirements.products_for_standard(std)],
            certification_route=certification_route(item),
            source_document=item.document_name, source_url=item.source_url,
            verified_requirements=len(reqs),
            deterministic_rules=sum(r.supported for r in reqs),
            unsupported_requirements=sum(not r.supported for r in reqs),
            requirement_ids=[r.id for r in reqs],
            coverage_status=status, reason=reason,
        ))
    return out


# ------------------------------------------------------- coverage across sources


@dataclass(frozen=True)
class PackageRequirementRow:
    """One Legal Metrology packaged-commodity requirement in the coverage report."""

    requirement_id: str
    reference: str
    requirement: str
    rule_type: str
    format: str | None
    declaration_fields: list[str]
    exclusions: list[str]
    applicability: str
    source_category: str
    source_knowledge_id: str
    status: str  # SUPPORTED | UNSUPPORTED


@dataclass(frozen=True)
class CoverageTotals:
    """BIS standards and Legal Metrology requirements are different knowledge sources —
    they are counted separately and never added up as "standards"."""

    bis_standards: int
    bis_inspection_supported: int
    bis_standard_only: int
    bis_unsupported: int
    bis_requirements: int  # package-label requirements tied to BIS standards
    bis_rules: int  # of those, deterministically checkable
    legal_metrology_requirements: int
    legal_metrology_rules: int
    legal_metrology_not_checkable: int
    package_label_checkable_requirements: int  # BIS + Legal Metrology
    deterministic_rules: int  # one rule per checkable requirement
    rule_types: list[str]  # distinct rule implementations in use


def package_requirement_rows(requirements: RequirementSet) -> list[PackageRequirementRow]:
    return [
        PackageRequirementRow(
            requirement_id=r.id, reference=r.reference, requirement=r.description, rule_type=r.rule_type,
            format=r.format, declaration_fields=list(r.fields), exclusions=[e.id for e in r.exclusions],
            applicability=r.applicability, source_category=r.source_category,
            source_knowledge_id=r.source_knowledge_id,
            status=ROW_SUPPORTED if r.supported else ROW_UNSUPPORTED,
        )
        for r in requirements.for_package()
    ]


def coverage_totals(knowledge_items, requirements: RequirementSet) -> CoverageTotals:
    standards = coverage_by_standard(knowledge_items, requirements)
    count = lambda status: sum(c.coverage_status == status for c in standards)  # noqa: E731
    bis = [r for r in requirements.requirements if r.scope == SCOPE_STANDARD and r.domain == PACKAGE_LABEL]
    lm = requirements.for_package()
    checkable = [r for r in (*bis, *lm) if r.supported]
    return CoverageTotals(
        bis_standards=len(standards),
        bis_inspection_supported=count(INSPECTION_SUPPORTED),
        bis_standard_only=count(STANDARD_ONLY),
        bis_unsupported=count(UNSUPPORTED),
        bis_requirements=len(bis),
        bis_rules=sum(r.supported for r in bis),
        legal_metrology_requirements=len(lm),
        legal_metrology_rules=sum(r.supported for r in lm),
        legal_metrology_not_checkable=sum(not r.supported for r in lm),
        package_label_checkable_requirements=len(checkable),
        deterministic_rules=len(checkable),
        rule_types=sorted({r.rule_type for r in checkable}),
    )
