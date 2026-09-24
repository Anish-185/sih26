"""Checks for the grounded RAG pipeline (app/rag.py) and the /ask endpoint.

Plain Python, no test framework (matches tests/test_retrieval.py). Run with:

    cd backend
    ./.venv/bin/python tests/test_rag.py

Exit code 0 = all checks passed, 1 = something failed.

The RAG pipeline is: deterministic SearchEngine retrieval -> (if there is
evidence) a single grounded LLM call over ONLY that evidence -> answer + the
retrieved sources. Retrieval is the source of truth; the LLM never runs when
retrieval abstains, and never receives anything but the retrieved BIS context.

These checks run against the real verified knowledge base. The local LLM is
replaced with a fake so the pipeline is deterministic and needs no LM Studio;
no fake BIS facts are introduced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import api as api_module  # noqa: E402
from app.api import AskRequest, _result_to_source, ask_post  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.rag import SYSTEM_PROMPT, BISQuestionAnswerer, _build_context  # noqa: E402
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
    """Stand-in for LocalLLM. Records every call; returns a fixed string."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, *, system_prompt: str, user_prompt: str,
                 temperature: float = 0.1) -> str:
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "temp": temperature}
        )
        return "GROUNDED ANSWER (fake LLM)."


class RaisingLLM:
    """A local model that is unreachable — every call raises LLMError."""

    def generate(self, *, system_prompt: str, user_prompt: str,
                 temperature: float = 0.1) -> str:
        raise LLMError("LM Studio request failed: simulated outage")


ENGINE = SearchEngine()

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge"
KB_STANDARD_NUMBERS = {
    " ".join(r["standard_number"].split()).upper()
    for path in DATA_DIR.glob("*.json")
    for r in json.load(open(path))
    if r.get("standard_number")
}


# ------------------------------------------------ 1. grounded path uses evidence

def test_grounded_answer_is_built_from_retrieved_evidence() -> None:
    llm = FakeLLM()
    answerer = BISQuestionAnswerer(search_engine=ENGINE, llm=llm)

    out = answerer.ask("What is HUID?")
    check("grounded: answer is the LLM answer", out.answer.startswith("GROUNDED"))
    check("grounded: LLM was called exactly once", len(llm.calls) == 1)
    check("grounded: retrieved sources are preserved on the answer",
          len(out.results) >= 1)

    call = llm.calls[0]
    check("grounded: the shared SYSTEM_PROMPT was used",
          call["system"] == SYSTEM_PROMPT)
    check("grounded: the user prompt carries the BIS evidence block",
          "BIS EVIDENCE:" in call["user"])
    check("grounded: the user prompt instructs 'ONLY the BIS evidence'",
          "ONLY the BIS evidence" in call["user"])

    # Every retrieved source must appear, with its provenance, in what the LLM saw.
    for result in out.results:
        item = result.item
        check(f"grounded: evidence for {item.id} reached the LLM",
              f"ID: {item.id}" in call["user"])
        check(f"grounded: {item.id} verification status reached the LLM",
              f"VERIFICATION STATUS: {item.verification_status}" in call["user"])
    check("grounded: at least one source URL reached the LLM",
          any((r.item.source_url or "") in call["user"]
              for r in out.results if r.item.source_url))


def test_build_context_contains_provenance() -> None:
    outcome = ENGINE.search("hallmarking", limit=3)
    context = _build_context(outcome.results)
    for result in outcome.results:
        item = result.item
        check(f"_build_context includes id for {item.id}", f"ID: {item.id}" in context)
        check(f"_build_context includes title for {item.id}",
              item.title in context)
    check("_build_context labels the source organisation",
          "SOURCE ORGANIZATION:" in context)
    check("_build_context labels the verification status",
          "VERIFICATION STATUS:" in context)


# --------------------------------------------------- 2. abstention: no LLM call

def test_abstains_without_evidence_and_never_calls_the_llm() -> None:
    llm = FakeLLM()
    answerer = BISQuestionAnswerer(search_engine=ENGINE, llm=llm)

    for junk in ("zzzzz qqqqq vvvvv", "asdf qwer zxcv nonsense token", "   "):
        out = answerer.ask(junk)
        check(f"{junk!r}: no sources", out.results == [])
        check(f"{junk!r}: abstention message, not a guess",
              "couldn't find" in out.answer)
    check("abstention: the LLM was never called", llm.calls == [])


def test_low_signal_query_still_abstains() -> None:
    # A query whose retrieval outcome abstains must not reach the LLM.
    llm = FakeLLM()
    answerer = BISQuestionAnswerer(search_engine=ENGINE, llm=llm)
    outcome = ENGINE.search("qwertful nonsensish", limit=5)
    check("retrieval itself abstains on the junk query", outcome.abstained)
    out = answerer.ask("qwertful nonsensish")
    check("answerer abstains too", out.results == [] and "couldn't find" in out.answer)
    check("no LLM call for an abstaining retrieval", llm.calls == [])


# ---------------------------------------- 3. never surfaces an invented standard

def test_nonexistent_standard_number_is_never_returned() -> None:
    llm = FakeLLM()
    answerer = BISQuestionAnswerer(search_engine=ENGINE, llm=llm)

    for q in ("Tell me about IS 99999", "What does IS 40404:2099 cover?",
              "requirements of Indian Standard IS 123456"):
        out = answerer.ask(q)
        for result in out.results:
            sn = result.item.standard_number
            if sn:
                key = " ".join(sn.split()).upper()
                check(f"{q!r}: source {result.item.id} standard {sn} exists in the KB",
                      key in KB_STANDARD_NUMBERS)
        # The fabricated number must never be echoed back as a retrieved standard.
        returned = {(" ".join((r.item.standard_number or "").split()).upper())
                    for r in out.results}
        check(f"{q!r}: fabricated IS number not among retrieved standards",
              "IS 99999" not in returned and "IS 40404:2099" not in returned
              and "IS 123456" not in returned)


# ------------------------------------------------- 4. /ask API contract mapping

def test_ask_post_maps_sources_and_flags() -> None:
    answerer = BISQuestionAnswerer(search_engine=ENGINE, llm=FakeLLM())
    grounded = answerer.ask("What is HUID and how can a consumer verify it?")

    sources = [_result_to_source(r) for r in grounded.results]
    check("ask_post mapping: source_count matches results",
          len(sources) == len(grounded.results) and len(sources) >= 1)
    check("ask_post mapping: verification_status preserved",
          all(s.verification_status == r.item.verification_status
              for s, r in zip(sources, grounded.results)))
    check("ask_post mapping: standard_number preserved (or None)",
          all(s.standard_number == r.item.standard_number
              for s, r in zip(sources, grounded.results)))

    empty = ask_post(AskRequest(question=""))
    check("ask_post: empty question is not grounded",
          not empty.grounded and empty.source_count == 0 and empty.sources == [])
    check("ask_post: empty question does not raise", isinstance(empty.answer, str))

    whitespace = ask_post(AskRequest(question="   \n\t  "))
    check("ask_post: whitespace-only question is not grounded",
          not whitespace.grounded and whitespace.sources == [])


# ------------------------------- 5. /ask falls back to evidence on an LLM outage

def test_ask_post_returns_the_evidence_when_the_model_is_unavailable() -> None:
    """Phase 1, Part C. Retrieval already succeeded, so a provider outage must
    degrade the prose, never the evidence — and never white-screen a demo."""
    from app import language as lang

    original = api_module.get_answerer
    api_module.get_answerer = lambda: BISQuestionAnswerer(
        search_engine=ENGINE, llm=RaisingLLM()
    )
    try:
        down = ask_post(AskRequest(question="What is HUID?"))
        check("ask_post: an LLM outage is answered, not refused", down.grounded)
        check("ask_post: the outage is labelled, not hidden", down.explained is False)
        check("ask_post: the retrieved sources are still returned",
              down.source_count > 0 and len(down.sources) == down.source_count)
        check("ask_post: MetrIQ says the answer carries no AI explanation",
              lang.EVIDENCE_ONLY[lang.EN] in down.answer)
        check("ask_post: the evidence itself is in the answer",
              any(source.title in down.answer for source in down.sources))
        check("ask_post: every source is named with its BIS organization",
              all(source.source_organization in down.answer for source in down.sources))

        hindi = ask_post(AskRequest(question="What is HUID?", language="hi"))
        check("ask_post: the fallback respects the language layer",
              lang.EVIDENCE_ONLY[lang.HI] in hindi.answer and hindi.language == lang.HI)

        # An abstaining question never reaches the LLM: the abstention stands.
        abstain = ask_post(AskRequest(question="zzzz qqqq vvvv nonsense"))
        check("ask_post: abstention still works during an LLM outage",
              not abstain.grounded and abstain.sources == []
              and abstain.explained is True)
    finally:
        api_module.get_answerer = original


def test_the_evidence_fallback_invents_nothing() -> None:
    """Every line is MetrIQ's own fixed sentence or a field copied from a record."""
    from app import language as lang
    from app.rag import render_evidence

    results = ENGINE.search("hallmarking", 3).results
    rendered = render_evidence(results, lang.EN)
    allowed = {lang.EVIDENCE_ONLY[lang.EN]}
    for result in results:
        item = result.item
        allowed |= {item.title, item.content, item.source_organization}
        for optional in (item.standard_number, item.document_name, item.source_url):
            if optional:
                allowed.add(optional)

    leftover = rendered
    for fragment in sorted(allowed, key=len, reverse=True):
        leftover = leftover.replace(fragment, " ")
    # Only the numbering, the em dash and the separators MetrIQ writes itself.
    check("render_evidence: nothing but record text and MetrIQ's own punctuation",
          set(leftover) <= set("0123456789. \n—·"), repr(leftover[:200]))
    check("render_evidence: no evidence means no prose", render_evidence([], lang.EN)
          == lang.EVIDENCE_ONLY[lang.EN])


# ------------------------------------------------ 6. system prompt trust rules

def test_system_prompt_enforces_grounding() -> None:
    lowered = SYSTEM_PROMPT.lower()
    check("system prompt: answer only from supplied context",
          "only using the bis context" in lowered)
    check("system prompt: do not use pretrained knowledge as evidence",
          "pretrained knowledge" in lowered)
    check("system prompt: do not invent standards / numbers / fees",
          "do not invent" in lowered)
    check("system prompt: say so when context is insufficient",
          "insufficient" in lowered)
    check("system prompt: no final legal / enforcement decision",
          "legal or enforcement decision" in lowered)


def main() -> int:
    test_grounded_answer_is_built_from_retrieved_evidence()
    test_build_context_contains_provenance()
    test_abstains_without_evidence_and_never_calls_the_llm()
    test_low_signal_query_still_abstains()
    test_nonexistent_standard_number_is_never_returned()
    test_ask_post_maps_sources_and_flags()
    test_ask_post_returns_the_evidence_when_the_model_is_unavailable()
    test_the_evidence_fallback_invents_nothing()
    test_system_prompt_enforces_grounding()

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
