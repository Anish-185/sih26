"""Checks for Phase 6 BIS certification guidance.

Plain Python, no test framework (matches tests/test_retrieval.py). Run with:

    cd backend
    ./.venv/bin/python tests/test_certification.py

Exit code 0 = all checks passed, 1 = something failed.

Runs against the real verified knowledge base in data/knowledge/. The local LLM
is replaced with a small fake so the grounded path can be tested without LM
Studio; no fake BIS facts are introduced (the evidence is always real).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.certification import (  # noqa: E402
    INSUFFICIENT_EVIDENCE_ANSWER,
    CertificationGuidanceService,
)
from app.product import ProductStandardFinder  # noqa: E402
from app.rag import BISQuestionAnswerer  # noqa: E402
from app.retrieval import SearchEngine  # noqa: E402
from app.api import search_get  # noqa: E402

_passed = 0
_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))


class FakeLLM:
    """Stand-in for LocalLLM. Records calls; returns a fixed string."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, *, system_prompt: str, user_prompt: str,
                 temperature: float = 0.1) -> str:
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "temp": temperature}
        )
        return "GROUNDED ANSWER (fake LLM, evidence supplied)."


ENGINE = SearchEngine()


def make_service() -> tuple[CertificationGuidanceService, FakeLLM]:
    llm = FakeLLM()
    service = CertificationGuidanceService(
        search_engine=ENGINE,
        product_finder=ProductStandardFinder(ENGINE),
        llm=llm,
    )
    return service, llm


# ---------------------------------------------------------------- 1. grounded

def test_grounded_certification_guidance() -> None:
    service, llm = make_service()

    out = service.guide(
        "How do I get BIS certification for packaged drinking water?"
    )
    check("packaged water: grounded", out.grounded)
    check("packaged water: LLM was called", len(llm.calls) == 1)
    check("packaged water: answer is the LLM answer", out.answer.startswith("GROUNDED"))
    check("packaged water: confidence is not none",
          out.confidence in {"low", "medium", "high"})
    check("packaged water: has sources", len(out.sources) >= 2)
    check("packaged water: every source carries provenance",
          all(s.item.source_url for s in out.sources))
    check("packaged water: evidence given to the LLM",
          "BIS EVIDENCE:" in llm.calls[0]["user"])

    # A product-specific certification question should identify the product.
    service2, _ = make_service()
    out2 = service2.guide(
        "How do I get BIS certification for a stainless steel water bottle?"
    )
    check("stainless steel bottle: grounded", out2.grounded)
    # IS 17803's title says "Potable Water Bottles (Copper, Stainless Steel,
    # Aluminium)" -- a full-title match -- so it is the identified product,
    # ahead of IS 17526 (whose own title never says "water"; see test_product.py).
    check("stainless steel bottle: product context is IS 17803",
          out2.product_context is not None and "17803" in out2.product_context)

    # The "process" question is answerable from the certification category alone.
    service3, _ = make_service()
    out3 = service3.guide("What is the BIS certification process?")
    check("process question: grounded", out3.grounded)
    check("process question: note flags missing product context",
          out3.product_context is None and "general BIS certification" in out3.note)


# ------------------------------------------------------- 2. insufficient / abstain

def test_insufficient_evidence_abstains() -> None:
    service, llm = make_service()

    out = service.guide("Do I need approval to sell handmade wooden toys?")
    check("unsupported product: not grounded", not out.grounded)
    check("unsupported product: exact abstention answer",
          out.answer == INSUFFICIENT_EVIDENCE_ANSWER)
    check("unsupported product: confidence none", out.confidence == "none")
    check("unsupported product: LLM NOT called", llm.calls == [])
    check("unsupported product: note explains why",
          "not enough certification-specific" in out.note)

    service2, llm2 = make_service()
    out2 = service2.guide("What is the capital of France?")
    check("off-topic: not grounded", not out2.grounded)
    check("off-topic: LLM NOT called", llm2.calls == [])
    check("off-topic: no sources", out2.sources == [])


# ------------------------------------------------------------------ 3. empty input

def test_empty_input() -> None:
    service, llm = make_service()

    for value in ("", "   ", "\n\t"):
        out = service.guide(value)
        check(f"empty {value!r}: not grounded", not out.grounded)
        check(f"empty {value!r}: confidence none", out.confidence == "none")
        check(f"empty {value!r}: no sources", out.sources == [])
        check(f"empty {value!r}: note is 'empty question'", out.note == "empty question")
    check("empty input never calls the LLM", llm.calls == [])


# --------------------------------------------- 4. Product -> Standard unchanged

def test_product_to_standard_still_works() -> None:
    finder = ProductStandardFinder(ENGINE)

    out = finder.find("stainless steel water bottle")
    check("P->S: stainless steel water bottle still grounded", out.grounded)
    check("P->S: still returns IS 17526:2021",
          "IS 17526:2021" in [r.item.standard_number for r in out.results])

    check("P->S: LED lamp still -> IS 16102",
          "IS 16102 (Part 1)" in
          [r.item.standard_number for r in finder.find("LED lamp").results])
    check("P->S: uncovered product still abstains",
          not finder.find("plastic garden chair").grounded)


# ------------------------------------------------- 5. /ask and /search unchanged

def test_ask_and_search_still_work() -> None:
    # /search (no LLM needed).
    resp = search_get(q="what is huid", limit=3)
    check("/search still returns results", resp.count >= 1)
    check("/search top result is what-is-huid", resp.results[0].id == "what-is-huid")
    check("/search still abstains on junk", search_get(q="zzzzz qqqqq").abstained)

    # /ask pipeline (deterministic parts), with the fake LLM.
    answerer = BISQuestionAnswerer(search_engine=ENGINE, llm=FakeLLM())
    grounded = answerer.ask("what is huid")
    check("/ask returns the grounded answer", grounded.answer.startswith("GROUNDED"))
    check("/ask keeps its retrieved sources", len(grounded.results) >= 1)

    abstained = answerer.ask("zzzzz qqqqq nonsense")
    check("/ask abstains with no context", abstained.results == [])
    check("/ask abstention message", "couldn't find" in abstained.answer)


def main() -> int:
    test_grounded_certification_guidance()
    test_insufficient_evidence_abstains()
    test_empty_input()
    test_product_to_standard_still_works()
    test_ask_and_search_still_work()

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
