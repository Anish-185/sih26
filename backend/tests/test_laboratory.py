"""Checks for Phase 7 BIS-recognized laboratory search.

Plain Python, no test framework (matches tests/test_retrieval.py). Run with:

    cd backend
    ./.venv/bin/python tests/test_laboratory.py

Exit code 0 = all checks passed, 1 = something failed.

Runs against the real verified knowledge base in data/knowledge/. The local LLM
is replaced with a small fake so the grounded path can be tested without LM
Studio; no fake BIS facts are introduced.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import search_get  # noqa: E402
from app.certification import CertificationGuidanceService  # noqa: E402
from app.laboratory import (  # noqa: E402
    INSUFFICIENT_EVIDENCE_ANSWER,
    LAB_CATEGORIES,
    LaboratorySearchService,
)
from app.product import ProductStandardFinder  # noqa: E402
from app.rag import BISQuestionAnswerer  # noqa: E402
from app.retrieval import SearchEngine  # noqa: E402

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
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, *, system_prompt: str, user_prompt: str,
                 temperature: float = 0.1) -> str:
        self.calls.append({"system": system_prompt, "user": user_prompt})
        return "GROUNDED ANSWER (fake LLM, evidence supplied)."


ENGINE = SearchEngine()


def make_service() -> tuple[LaboratorySearchService, FakeLLM]:
    llm = FakeLLM()
    return LaboratorySearchService(search_engine=ENGINE, llm=llm), llm


# ---------------------------------------------------------------- 1. grounded

def test_grounded_laboratory_search() -> None:
    service, llm = make_service()

    out = service.search("BIS recognised laboratory for testing steel")
    check("lab query: grounded", out.grounded)
    check("lab query: LLM was called once", len(llm.calls) == 1)
    check("lab query: answer is the LLM answer", out.answer.startswith("GROUNDED"))
    check("lab query: confidence not none",
          out.confidence in {"low", "medium", "high"})
    check("lab query: has sources", len(out.sources) >= 2)
    check("lab query: every source is lab/testing evidence",
          all(s.item.category in LAB_CATEGORIES for s in out.sources))
    check("lab query: every source carries provenance",
          all(s.item.source_url for s in out.sources))
    check("lab query: note points to LIMS", "lims.bis.gov.in" in out.note)
    # Milestone 18: MetrIQ now holds verified laboratory records, so naming is
    # allowed — but ONLY from the records the application supplied. The rule the
    # prompt must carry is therefore "nothing outside the supplied records",
    # which is the same guarantee expressed against a bigger evidence base.
    system = " ".join(llm.calls[0]["system"].split())
    check("lab query: system prompt forbids inventing lab names",
          "Do NOT invent laboratory names" in system)
    check("lab query: system prompt allows naming only supplied records",
          "ONLY if it appears in the MATCHED LABORATORY RECORDS" in system)


def test_is_wise_context() -> None:
    service, _ = make_service()
    out = service.search("which BIS lab can test IS 1786")
    check("IS-wise: grounded", out.grounded)
    check("IS-wise: standard context is IS 1786",
          out.standard_context is not None and "1786" in out.standard_context)


# ------------------------------------------------------ 2. deterministic (no LLM)

def test_explain_false_skips_llm() -> None:
    service, llm = make_service()
    out = service.search("NABL accredited laboratory list", explain=False)
    check("explain=False: grounded", out.grounded)
    check("explain=False: LLM NOT called", llm.calls == [])
    check("explain=False: answer built from evidence titles",
          "Related official BIS guidance:" in out.answer)
    check("explain=False: still notes no lab records", "lims.bis.gov.in" in out.answer)


# ----------------------------------------------------- 3. insufficient / abstain

def test_insufficient_evidence_abstains() -> None:
    service, llm = make_service()

    for q in ("What is the capital of France?", "Tell me a joke about cricket"):
        out = service.search(q)
        check(f"{q!r}: not grounded", not out.grounded)
        check(f"{q!r}: exact abstention answer",
              out.answer == INSUFFICIENT_EVIDENCE_ANSWER)
        check(f"{q!r}: confidence none", out.confidence == "none")
        check(f"{q!r}: no sources", out.sources == [])
    check("off-topic never calls the LLM", llm.calls == [])


# ------------------------------------------------------------------ 4. empty

def test_empty_input() -> None:
    service, llm = make_service()
    for value in ("", "   ", "\n\t"):
        out = service.search(value)
        check(f"empty {value!r}: not grounded", not out.grounded)
        check(f"empty {value!r}: confidence none", out.confidence == "none")
        check(f"empty {value!r}: no sources", out.sources == [])
        check(f"empty {value!r}: note is 'empty query'", out.note == "empty query")
    check("empty input never calls the LLM", llm.calls == [])


# ---------------------------------------- 5. no individual laboratory is invented

def test_no_laboratory_is_named() -> None:
    service, _ = make_service()
    # Every retrievable source is a verified meta-record; the KB holds no
    # per-laboratory records, so no source can be an individual lab.
    for q in ("find a laboratory to test my LED lamp",
              "assaying and hallmarking centre",
              "where do I get my product tested by BIS"):
        out = service.search(q, explain=False)
        for s in out.sources:
            check(f"{q!r}: source {s.item.id} is verified",
                  s.item.verification_status == "verified")
            check(f"{q!r}: source {s.item.id} is not an indian_standards record",
                  s.item.category in LAB_CATEGORIES)


# --------------------------------------------- 6. existing functionality intact

def test_existing_functionality_preserved() -> None:
    # /search
    resp = search_get(q="what is huid", limit=3)
    check("/search still works", resp.results and resp.results[0].id == "what-is-huid")

    # /ask pipeline (deterministic parts + fake LLM)
    answerer = BISQuestionAnswerer(search_engine=ENGINE, llm=FakeLLM())
    check("/ask still grounds", answerer.ask("what is huid").answer.startswith("GROUNDED"))
    check("/ask still abstains", answerer.ask("zzzz qqqq").results == [])

    # Product -> Standard
    finder = ProductStandardFinder(ENGINE)
    check("product->standard still works",
          "IS 17526:2021" in
          [r.item.standard_number for r in finder.find("stainless steel water bottle").results])
    check("product->standard still abstains",
          not finder.find("plastic garden chair").grounded)

    # Certification guidance
    cert = CertificationGuidanceService(
        search_engine=ENGINE, product_finder=finder, llm=FakeLLM()
    )
    check("certification still grounds",
          cert.guide("What is the BIS certification process?").grounded)
    check("certification still abstains",
          not cert.guide("Do I need approval to sell handmade wooden toys?").grounded)


def main() -> int:
    test_grounded_laboratory_search()
    test_is_wise_context()
    test_explain_false_skips_llm()
    test_insufficient_evidence_abstains()
    test_empty_input()
    test_no_laboratory_is_named()
    test_existing_functionality_preserved()

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
