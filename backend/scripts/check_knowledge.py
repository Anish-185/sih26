"""Validate the knowledge base (BIS + Legal Metrology) and the inspection requirements, and print a report.

Usage:

    cd backend
    ./.venv/bin/python scripts/check_knowledge.py [path/to/knowledge/dir]
    ./.venv/bin/python scripts/check_knowledge.py --json    # machine-readable coverage

Exit code 0 = valid, 1 = problems found.

The report answers the question the assistant exists for: for each product BIS
names, which Indian Standard applies, where that came from, and how far MetrIQ
can go with it — retrieval and explanation only (STANDARD_ONLY), or also
deterministic image checks (INSPECTION_SUPPORTED).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.loader import DEFAULT_KNOWLEDGE_DIR, load_knowledge_base, main  # noqa: E402
from app.certification_journey import SCHEME_NAMES, certification_coverage
from app.standard_currency import distribution  # noqa: E402
from app.requirements import (  # noqa: E402
    INSPECTION_SUPPORTED,
    STANDARD_ONLY,
    UNSUPPORTED,
    coverage_by_standard,
    coverage_matrix,
    coverage_totals,
    load_requirements,
    package_requirement_rows,
)



def _product_rows(items, requirements) -> list[dict]:
    """One row per verified standard: the product BIS names, and what MetrIQ can do.

    Everything is read from the knowledge base and the requirement data — nothing
    is counted that is not backed by a record.
    """
    coverage = {c.standard_number: c for c in coverage_by_standard(items, requirements)}
    rows = []
    for item in items:
        if item.category != "indian_standards":
            continue
        cov = coverage.get(item.standard_number)
        product = item.title.split(" — ", 1)[1] if " — " in item.title else item.title
        group = (item.reference or "").split(";")[-1].strip() or "—"
        rows.append({
            "category": group,
            "product": product,
            "standard": item.standard_number,
            "source": item.document_name or "",
            "source_url": item.source_url or "",
            "last_verified": str(item.last_verified) if item.last_verified else "",
            "requirements": cov.verified_requirements if cov else 0,
            "image_checkable_requirements": cov.deterministic_rules if cov else 0,
            "rules": cov.deterministic_rules if cov else 0,
            "status": cov.coverage_status if cov else UNSUPPORTED,
        })
    return sorted(rows, key=lambda r: (r["category"], r["product"]))


def print_product_coverage(items, requirements) -> None:
    rows = _product_rows(items, requirements)
    print("\nProduct -> Standard coverage (what the assistant can answer)")
    print(f"  {'CATEGORY':<34} {'PRODUCT':<52} {'STANDARD':<30} {'REQ':>3} {'IMG':>3} {'RULES':>5}  STATUS")
    for row in rows:
        print(f"  {row['category'][:33]:<34} {row['product'][:51]:<52} {row['standard'][:29]:<30} "
              f"{row['requirements']:>3} {row['image_checkable_requirements']:>3} {row['rules']:>5}  {row['status']}")
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    print(f"  {len(rows)} products with a verified standard — "
          + ", ".join(f"{n} {s}" for s, n in sorted(by_status.items())))


def check_requirements(argv: list[str]) -> int:
    knowledge_dir = Path(argv[0]) if argv else DEFAULT_KNOWLEDGE_DIR
    items = load_knowledge_base(knowledge_dir).items
    requirements = load_requirements(items)

    print_product_coverage(items, requirements)

    print("\nInspection requirements (data/inspection_requirements.json):")
    supported = sum(r.supported for r in requirements.requirements)
    print(f"  accepted               {len(requirements.requirements)} "
          f"({supported} checkable, {len(requirements.requirements) - supported} not_supported)")

    print(f"  products               {len(requirements.products)} modelled "
          f"({', '.join(p.name for p in requirements.products) or 'none'})")

    by_standard = coverage_by_standard(items, requirements)
    counts = {status: sum(c.coverage_status == status for c in by_standard)
              for status in (INSPECTION_SUPPORTED, STANDARD_ONLY, UNSUPPORTED)}
    print(f"\nBIS inspection coverage (package-label inspection) — total BIS standards: {len(by_standard)}")
    print(f"  Inspection-supported: {counts[INSPECTION_SUPPORTED]}")
    print(f"  Standard-only:        {counts[STANDARD_ONLY]}  (verified and retrievable; not a failure)")
    print(f"  Unsupported:          {counts[UNSUPPORTED]}")
    for c in by_standard:
        product = ", ".join(c.products) or c.title.split(" — ", 1)[-1] + " (product not modelled)"
        print(f"\n  {c.standard_number}")
        print(f"    Product / category: {product}")
        print(f"    Source:             {c.source_document}")
        print(f"    Requirements: {c.verified_requirements}   Rules: {c.deterministic_rules}   "
              f"Coverage: {c.coverage_status}")
        print(f"    Reason: {c.reason}")

    print("\nCoverage matrix rows with requirement data (product | standard | requirement | rule | status):")
    for r in coverage_matrix(items, requirements):
        if r.requirement_id:
            print(f"  {r.product_name or '(any product)'} | {r.standard_number} | {r.requirement_id} | "
                  f"{r.rule_type} | {r.status}")

    scope = requirements.package_scope
    print("\nLegal Metrology package-label requirements (source: Legal Metrology, Department of Consumer Affairs)")
    print(f"  Scope: {scope.description if scope else 'NO VALID package_scope'}")
    for e in scope.exclusions if scope else ():
        print(f"  Exclusion (observable): {e.id} — {e.description}")
    for a in scope.assumptions if scope else ():
        print(f"  Assumption (not observable): {a}")
    for row in package_requirement_rows(requirements):
        excl = f"  excluded when: {', '.join(row.exclusions)}" if row.exclusions else ""
        print(f"  {row.reference:24} {row.requirement_id:40} {row.rule_type:16} {row.status}{excl}")

    t = coverage_totals(items, requirements)
    print("\nCoverage summary (BIS standards and Legal Metrology requirements are separate sources)")
    print(f"  Total BIS standards:                    {t.bis_standards}")
    print(f"  Inspection-supported BIS standards:     {t.bis_inspection_supported}")
    print(f"  Standard-only BIS standards:            {t.bis_standard_only}")
    print(f"  Unsupported BIS standards:              {t.bis_unsupported}")
    print(f"  BIS package-label requirements:         {t.bis_requirements} ({t.bis_rules} checkable)")
    print(f"  Legal Metrology requirements:           {t.legal_metrology_requirements}")
    print(f"  Legal Metrology checkable rules:        {t.legal_metrology_rules} "
          f"({t.legal_metrology_not_checkable} not checkable from an image)")
    print(f"  Total package-label checkable requirements: {t.package_label_checkable_requirements}")
    print(f"  Total deterministic rules:              {t.deterministic_rules} "
          f"(rule types: {', '.join(t.rule_types)})")

    # Milestone 16 — certification guidance is knowledge coverage, not a rule.
    c = certification_coverage(items)
    print("\nCertification guidance coverage (verified BIS standards)")
    print(f"  Total verified standards:               {c.total_standards}")
    print(f"  With full certification guidance:       {c.verified}")
    print(f"  With partial certification guidance:    {c.partial}")
    print(f"  Without sufficient guidance:            {c.insufficient}")
    for scheme, count in sorted(c.by_scheme.items()):
        print(f"    {SCHEME_NAMES[scheme]:56} {count}")

    # Phase 5 — edition currency: a statement about MetrIQ's evidence, not BIS's catalogue.
    numbers = [i.standard_number for i in items if i.category == "indian_standards" and i.standard_number]
    print("\nEdition currency (is the cited edition the newest one MetrIQ's evidence shows?)")
    for status, count in distribution(numbers).items():
        print(f"  {status:<40} {count}")

    if requirements.errors:
        print(f"\nRequirement errors: {len(requirements.errors)}")
        for err in requirements.errors:
            print(f"  - {err}")
        print("\nFAILED: inspection requirements have problems.")
        return 1
    print("\nOK: inspection requirements are grounded in verified records.")
    return 0


def emit_json(argv: list[str]) -> int:
    """Machine-readable coverage: the same rows, plus the totals."""
    knowledge_dir = Path(argv[0]) if argv else DEFAULT_KNOWLEDGE_DIR
    items = load_knowledge_base(knowledge_dir).items
    requirements = load_requirements(items)
    totals = coverage_totals(items, requirements)
    print(json.dumps({
        "generated_from": str(knowledge_dir),
        "totals": totals.__dict__,
        "products": _product_rows(items, requirements),
        "legal_metrology_requirements": [r.__dict__ for r in package_requirement_rows(requirements)],
        "errors": list(requirements.errors),
    }, indent=1, default=str))
    return 1 if requirements.errors else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--json"]
    if "--json" in sys.argv[1:]:
        raise SystemExit(emit_json(args))
    status = main(args)
    raise SystemExit(status or check_requirements(args))
