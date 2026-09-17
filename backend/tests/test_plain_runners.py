"""Make `python -m pytest -q` an authoritative gate for the plain-Python suites.

Most test files in this directory are plain-Python runners: their `check()`
helper prints PASS/FAIL and sets an exit code in `main()`, but the individual
`test_*` functions never `assert`, so pytest would report them as "passed" even
when an internal check fails.

This module closes that gap: it runs every other `tests/test_*.py` file as its
own subprocess (exactly the "authoritative" way they are meant to be run) and
fails if any of them exits non-zero. Running each suite in a fresh process also
keeps their module-global PASS/FAIL counters from contaminating each other.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SELF = Path(__file__).name

RUNNERS = sorted(
    p.name for p in TESTS_DIR.glob("test_*.py") if p.name != SELF
)


@pytest.mark.parametrize("runner", RUNNERS)
def test_plain_runner_passes(runner: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(TESTS_DIR / runner)],
        capture_output=True,
        text=True,
        cwd=TESTS_DIR.parent,  # backend/
    )
    if proc.returncode != 0:
        pytest.fail(
            f"{runner} exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}",
            pytrace=False,
        )


def test_every_runner_is_covered() -> None:
    # Guard against a new suite being added without this file noticing.
    assert RUNNERS, "no plain-Python runners were discovered"
    for name in (
        "test_knowledge.py", "test_retrieval.py", "test_product.py",
        "test_why_this_result.py", "test_certification.py",
        "test_laboratory.py", "test_hallmarking.py", "test_rag.py",
        "test_api_contract.py", "test_llm_adapter.py", "test_legal_metrology.py",
        "test_inspection_records.py",
    ):
        assert name in RUNNERS, f"{name} is missing from the runner sweep"
