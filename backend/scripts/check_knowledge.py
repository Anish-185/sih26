"""Validate the BIS knowledge base and the inspection requirements, and print a report.

Usage:

    cd backend
    ./.venv/bin/python scripts/check_knowledge.py [path/to/knowledge/dir]

Exit code 0 = valid, 1 = problems found.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.loader import DEFAULT_KNOWLEDGE_DIR, load_knowledge_base, main  # noqa: E402
from app.requirements import (  # noqa: E402
    SUPPORTED_FOR_INSPECTION,
    coverage_by_standard,
    coverage_matrix,
    load_requirements,
)


def check_requirements(argv: list[str]) -> int:
    knowledge_dir = Path(argv[0]) if argv else DEFAULT_KNOWLEDGE_DIR
    items = load_knowledge_base(knowledge_dir).items
    requirements = load_requirements(items)

    print("\nInspection requirements (data/inspection_requirements.json):")
    supported = sum(r.supported for r in requirements.requirements)
    print(f"  accepted               {len(requirements.requirements)} "
          f"({supported} checkable, {len(requirements.requirements) - supported} not_supported)")

    print(f"  products               {len(requirements.products)} modelled "
          f"({', '.join(p.name for p in requirements.products) or 'none'})")

    by_standard = coverage_by_standard(items, requirements)
    covered = [c for c in by_standard if c.inspection_status == SUPPORTED_FOR_INSPECTION]
    print(f"\nInspection coverage: {len(covered)} of {len(by_standard)} standards supported for inspection")
    print(f"  {'STANDARD':30} {'PRODUCT / CATEGORY':46} {'REQS':>4} {'RULES':>5}  STATUS")
    for c in by_standard:
        product = ", ".join(c.products) or c.title.split(" — ", 1)[-1] + " (product not modelled)"
        print(f"  {c.standard_number:30} {product[:46]:46} {c.verified_requirements:>4} "
              f"{c.deterministic_rules:>5}  {c.inspection_status}")

    print("\nCoverage matrix rows with requirement data (product | standard | requirement | rule | status):")
    for r in coverage_matrix(items, requirements):
        if r.requirement_id:
            print(f"  {r.product_name or '(any product)'} | {r.standard_number} | {r.requirement_id} | "
                  f"{r.rule_type} | {r.status}")

    if requirements.errors:
        print(f"\nRequirement errors: {len(requirements.errors)}")
        for err in requirements.errors:
            print(f"  - {err}")
        print("\nFAILED: inspection requirements have problems.")
        return 1
    print("\nOK: inspection requirements are grounded in verified records.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    status = main(args)
    raise SystemExit(status or check_requirements(args))
