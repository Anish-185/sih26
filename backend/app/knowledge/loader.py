"""Load and validate the knowledge base (BIS + Legal Metrology) from JSON files on disk.

Layout (one file per category):

    data/knowledge/
        bis_general.json
        indian_standards.json
        certification.json
        testing.json
        laboratories.json
        hallmarking.json
        consumer_information.json
        faqs.json
        legal_metrology.json   (Legal Metrology texts — source_authority LEGAL_METROLOGY)

Each file holds a JSON array of knowledge items. The filename must match the
`category` field of every item inside it.

Checks performed: schema validation (required fields, field formats, verified-item
traceability, indian_standards needs a standard_number), plus loader-level checks
for invalid JSON, category/file mismatch, duplicate ids, and duplicate standard
numbers within the indian_standards category.

Run as a script to validate everything:

    python -m app.knowledge.loader
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.knowledge.schema import Category, KnowledgeItem

# data/knowledge/ at the repo root (this file is backend/app/knowledge/loader.py).
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge"


@dataclass
class LoadError:
    """One problem found while loading. Points at exactly where it happened."""

    file: str
    index: int | None  # position in the JSON array, or None for file-level problems
    item_id: str | None
    message: str

    def __str__(self) -> str:
        where = self.file
        if self.index is not None:
            where += f"[{self.index}]"
        if self.item_id:
            where += f" (id={self.item_id})"
        return f"{where}: {self.message}"


@dataclass
class LoadResult:
    """Outcome of a load: the valid items plus every problem found."""

    items: list[KnowledgeItem] = field(default_factory=list)
    errors: list[LoadError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {c.value: 0 for c in Category}
        for item in self.items:
            counts[item.category] += 1
        return counts


def _expected_files(knowledge_dir: Path) -> list[Path]:
    return [knowledge_dir / f"{c.value}.json" for c in Category]


def load_knowledge_base(knowledge_dir: Path | None = None) -> LoadResult:
    """Load every category file, validate each item, and collect all errors.

    This never raises for bad data: problems are returned in `result.errors` so the
    caller (or the retrieval layer later) can decide what to do.
    """

    knowledge_dir = knowledge_dir or DEFAULT_KNOWLEDGE_DIR
    result = LoadResult()
    seen_ids: dict[str, str] = {}  # id -> file it first appeared in
    # normalised standard_number -> id that first defined it, for indian_standards only
    seen_standards: dict[str, str] = {}

    if not knowledge_dir.is_dir():
        result.errors.append(
            LoadError(str(knowledge_dir), None, None, "knowledge directory not found")
        )
        return result

    for path in _expected_files(knowledge_dir):
        category = path.stem
        rel = path.name

        if not path.exists():
            result.errors.append(
                LoadError(rel, None, None, "expected category file is missing")
            )
            continue

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result.errors.append(LoadError(rel, None, None, f"invalid JSON: {exc}"))
            continue

        if not isinstance(raw, list):
            result.errors.append(
                LoadError(rel, None, None, "file must contain a JSON array of items")
            )
            continue

        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                result.errors.append(
                    LoadError(rel, i, None, "item must be a JSON object")
                )
                continue

            entry_id = entry.get("id")

            try:
                item = KnowledgeItem.model_validate(entry)
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(p) for p in err["loc"]) or "(item)"
                    result.errors.append(
                        LoadError(rel, i, entry_id, f"{loc}: {err['msg']}")
                    )
                continue

            if item.category != category:
                result.errors.append(
                    LoadError(
                        rel,
                        i,
                        item.id,
                        f"category '{item.category}' does not match file '{rel}'",
                    )
                )
                continue

            if item.id in seen_ids:
                result.errors.append(
                    LoadError(
                        rel,
                        i,
                        item.id,
                        f"duplicate id (already defined in {seen_ids[item.id]})",
                    )
                )
                continue

            # In the indian_standards category, each standard number must appear
            # once. (Other categories may *reference* the same standard, so we only
            # de-duplicate here.)
            if item.category == Category.INDIAN_STANDARDS.value and item.standard_number:
                key = " ".join(item.standard_number.split()).upper()
                if key in seen_standards:
                    result.errors.append(
                        LoadError(
                            rel,
                            i,
                            item.id,
                            f"duplicate standard_number '{item.standard_number}' "
                            f"(already defined by id '{seen_standards[key]}')",
                        )
                    )
                    continue
                seen_standards[key] = item.id

            seen_ids[item.id] = rel
            result.items.append(item)

    return result


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    knowledge_dir = Path(argv[0]) if argv else DEFAULT_KNOWLEDGE_DIR

    print(f"Loading knowledge base from: {knowledge_dir}")
    result = load_knowledge_base(knowledge_dir)

    print(f"\nValid items: {len(result.items)}")
    for category, count in result.by_category().items():
        print(f"  {category:22} {count}")

    status_counts: dict[str, int] = {}
    missing_traceability: list[str] = []
    for item in result.items:
        status_counts[item.verification_status] = (
            status_counts.get(item.verification_status, 0) + 1
        )
        if item.verification_status == "verified" and not (
            item.source_url and item.last_verified
        ):
            missing_traceability.append(item.id)

    print("\nVerification status:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status:22} {count}")

    standards = sorted(
        {i.standard_number for i in result.items if i.standard_number}
    )
    print(f"\nDistinct standard numbers referenced: {len(standards)}")

    if missing_traceability:
        print("\nWARNING: verified items missing source_url/last_verified:")
        for item_id in missing_traceability:
            print(f"  - {item_id}")

    if result.errors:
        print(f"\nErrors: {len(result.errors)}")
        for err in result.errors:
            print(f"  - {err}")
        print("\nFAILED: knowledge base has problems.")
        return 1

    print("\nOK: knowledge base is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
