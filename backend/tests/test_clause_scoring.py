"""Checks for scripts/score_clause_candidates.py — Phase 7 step 1, offline.

What matters: a heading is accepted only when it continues the clause numbering,
table notes numbered "1 … 5" cannot hijack it, an annex ends the clause before it,
and the scorer writes only its report (never the knowledge base).

    cd backend
    ./.venv/bin/python tests/test_clause_scoring.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import score_clause_candidates as sc  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


TEXT = """1 SCOPE
This standard covers packaged water.
1 The safety requirements are specified elsewhere.
2 The performance requirements are specified elsewhere.
2 REFERENCES
The standards in Annex A apply.
2.1 Terms apply.
3. MARKING
3.1 Each container shall be marked.
ANNEX A
Annex text that belongs to no clause.
A-1 GENERAL
A-1.1 Annex clause text.
""".splitlines()


def main() -> int:
    numbers = [(c["space"], c["number"]) for c in sc.clauses(TEXT)]
    check("sequence follows the clause numbering",
          numbers == [("", (1,)), ("", (2,)), ("", (2, 1)), ("", (3,)), ("", (3, 1)),
                      ("A", (1,)), ("A", (1, 1))], str(numbers))
    first = sc.clauses(TEXT)[0]
    check("table notes '1 The …' stay inside the scope body", len(first["body"]) == 4)
    last_main = [c for c in sc.clauses(TEXT) if c["number"] == (3, 1)][0]
    check("an ANNEX heading ends the clause before it", last_main["body"] == ["3.1 Each container shall be marked."])
    check("old-style '3. MARKING' is accepted and marked as dotted",
          [c["dot"] for c in sc.clauses(TEXT) if c["number"] == (3,)] == [True])
    check("successor: child, sibling and ancestor's sibling only",
          sc.successor((5, 2), (5, 2, 1)) and sc.successor((5, 2), (5, 3)) and sc.successor((5, 2), (6,))
          and not sc.successor((5, 2), (5, 4)) and not sc.successor((5, 2), (1,)))
    source = (BACKEND / "scripts" / "score_clause_candidates.py").read_text()
    check("the scorer writes only its report", source.count("write_text(") == 1
          and "REPORT.write_text" in source)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
