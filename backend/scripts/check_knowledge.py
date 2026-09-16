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
from app.requirements import SUPPORTED_FOR_INSPECTION, load_requirements  # noqa: E402


def check_requirements(argv: list[str]) -> int:
    knowledge_dir = Path(argv[0]) if argv else DEFAULT_KNOWLEDGE_DIR
    items = load_knowledge_base(knowledge_dir).items
    requirements = load_requirements(items)

    print("\nInspection requirements (data/inspection_requirements.json):")
    supported = sum(r.supported for r in requirements.requirements)
    print(f"  accepted               {len(requirements.requirements)} "
          f"({supported} checkable, {len(requirements.requirements) - supported} not_supported)")

    standards = sorted({i.standard_number for i in items if i.category == "indian_standards"})
    covered = [s for s in standards if requirements.coverage(s) == SUPPORTED_FOR_INSPECTION]
    print(f"\nInspection coverage: {len(covered)} of {len(standards)} standards")
    for s in covered:
        ids = ", ".join(r.id for r in requirements.for_standard(s))
        print(f"  SUPPORTED_FOR_INSPECTION  {s:24} {ids}")
    print(f"  STANDARD_ONLY             {len(standards) - len(covered)} others")

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
