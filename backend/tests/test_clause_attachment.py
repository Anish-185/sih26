"""Phase 8: clause evidence attached to answers (citation-only design).

Retrieval decides which standard; clauses are only ATTACHED to a confident answer
about a standard retrieval already found. Covered here, every model call stubbed:

  * attachment only when confident; the cap (3 per standard, 6 in total);
  * never on an abstention or a coverage boundary;
  * an inherited follow-up attaches clauses through the same path;
  * the model sees each clause labelled as OCR with its reference exactly as stored;
  * the clause guard in both directions, for /ask and the copilot;
  * fallback_reason for every path;
  * the reworded EVIDENCE_ONLY in all three languages;
  * "why this result?" at clause level and identity level; the report's OCR label.

    cd backend
    ./.venv/bin/python tests/test_clause_attachment.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import api as api_module  # noqa: E402
from app import clauses  # noqa: E402
from app import language as lang  # noqa: E402
from app import product as product_module  # noqa: E402
from app.api import AskRequest, ask_post  # noqa: E402
from app.copilot import CopilotAnswer, guard  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.openrouter import CopilotUnavailable  # noqa: E402
from app.product import ProductStandardFinder, explain_candidate  # noqa: E402
from app.rag import BISQuestionAnswerer, render_evidence  # noqa: E402
from app.report import _text_held  # noqa: E402
from app.retrieval import SearchEngine  # noqa: E402

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


class ReplyLLM:
    """Returns a fixed reply and remembers the prompts it was given."""

    def __init__(self, reply: str = "A grounded answer.") -> None:
        self.reply, self.prompts = reply, []

    def generate(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.1, **_) -> str:
        self.prompts.append((system_prompt, user_prompt))
        return self.reply


class RaisingLLM:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def generate(self, **_) -> str:
        raise self.exc


ENGINE = SearchEngine()


def answerer(llm) -> BISQuestionAnswerer:
    return BISQuestionAnswerer(ENGINE, llm)


def test_attached_only_when_confident() -> None:
    llm = ReplyLLM()
    ans = answerer(llm).ask("sampling for packaged drinking water")
    top = ENGINE.search("sampling for packaged drinking water").confidence
    check("a confident answer about a clause-level standard gets clauses", top in ("high", "medium")
          and len(ans.clauses) > 0, f"{top}, {len(ans.clauses)}")
    retrieved = {r.item.standard_number for r in ans.results}
    check("every attached clause belongs to a standard retrieval already returned",
          all(c.standard_number in retrieved for c in ans.clauses))
    check("clauses are never in the retrieved results themselves",
          all(r.item.category != "standard_clauses" for r in ans.results))
    prompt = llm.prompts[0][1]
    check("the model sees the OCR label", clauses.OCR_LABEL in prompt)
    check("…and each clause's reference exactly as stored",
          all(f"REFERENCE: {c.reference}" in prompt for c in ans.clauses))
    check("the system prompt extends the standard-number rule to clauses and pages",
          "clause\n   numbers and page references" in llm.prompts[0][0]
          and "never state a numeric limit" in llm.prompts[0][0])

    baseline = json.loads((BACKEND / "tests" / "data" / "eval_baseline.json").read_text())
    low = [r["query"] for r in baseline["rows"] if r["confidence"] == "low"]
    attached = [q for q in low if answerer(ReplyLLM()).ask(q).clauses]
    check(f"no clauses on any of the {len(low)} low-confidence eval queries", low and not attached, str(attached[:3]))


def test_cap() -> None:
    results = ENGINE.search("cement", limit=10).results
    got = clauses.attach(results, "cement")
    per = {}
    for c in got:
        per[c.standard_number] = per.get(c.standard_number, 0) + 1
    check("at most 6 clauses in total", 0 < len(got) <= 6, str(len(got)))
    check("at most 3 per standard", all(n <= 3 for n in per.values()), str(per))
    check("the cap spans several standards when several are clause-level", len(per) >= 2, str(per))
    check("a smaller cap is honoured", len(clauses.attach(results, "cement", per_standard=1, total=2)) <= 2)


def test_no_attachment_on_abstention_or_boundary() -> None:
    for query in ["shampoo", "what is the capital of France"]:
        ans = answerer(ReplyLLM()).ask(query)
        check(f"{query!r}: no clauses on an abstention / boundary",
              not ans.clauses and not ans.results and ans.boundary is not None)
    finder = ProductStandardFinder(ENGINE)
    solar = finder.find("solar panel")
    check("Product -> Standard: weak matches under a boundary get no explanation and no clauses",
          solar.boundary is not None and solar.boundary.weak_matches and not solar.explanations)
    # /ask answers "solar panel" at MEDIUM on the single word "solar" (the Phase 2
    # finding). Retrieval confidence alone must not be enough to quote a clause.
    check("/ask: a medium single-word match is confident by retrieval …",
          ENGINE.search("solar panel").confidence in ("high", "medium"))
    original = clauses.rank_within
    clauses_seen = []
    clauses.rank_within = lambda number, query, limit=None: clauses_seen.append(number) or original(number, query, limit)
    try:
        ans = answerer(ReplyLLM()).ask("solar panel")
    finally:
        clauses.rank_within = original
    check("… but no standard is even looked up for clauses, because none was confidently identified",
          not ans.clauses and not clauses_seen, str(clauses_seen))
    named = answerer(ReplyLLM()).ask("what does IS 17153:2019 cover")
    check("a confident question naming a clause-level standard by number gets its clauses",
          named.clauses and all(c.standard_number == "IS 17153:2019" for c in named.clauses))
    check("…but the same question at LOW retrieval confidence gets none",
          ENGINE.search("what does IS 17153 cover").confidence == "low"
          and not answerer(ReplyLLM()).ask("what does IS 17153 cover").clauses)


def test_inherited_context_attaches_clauses() -> None:
    qa = answerer(ReplyLLM())
    first = qa.ask("which standard applies to packaged drinking water?")
    check("the first question resolves a context", first.context is not None)
    follow = qa.ask("is it mandatory?", context_product=first.context.product if first.context else None)
    check("the follow-up inherits the product", follow.inherited is not None, str(follow.inherited))
    check("…and gets clauses through the same path", len(follow.clauses) > 0)
    check("…only from the standards its own retrieval returned",
          all(c.standard_number in {r.item.standard_number for r in follow.results} for c in follow.clauses))


def test_guard_both_directions() -> None:
    invented = answerer(ReplyLLM("Clause 5.9.9 of IS 14543:2016 sets the limit.")).ask(
        "sampling for packaged drinking water")
    check("/ask: an invented 'clause 5.9.9' is withheld",
          not invented.explained and invented.fallback_reason == "GUARD:UNSUPPORTED_CLAUSE")
    check("…and MetrIQ's own evidence text replaces it", lang.EVIDENCE_ONLY[lang.EN] in invented.answer)
    quantity = answerer(ReplyLLM("A bottle may hold 1.5 litres; a pack may weigh 9.1 kg.")).ask(
        "sampling for packaged drinking water")
    check("/ask: '1.5 litres' / '9.1 kg' with no clause marker passes",
          quantity.explained and quantity.fallback_reason == "MODEL")
    real = answerer(ReplyLLM()).ask("sampling for packaged drinking water")
    label = clauses.label_of(real.clauses[0]) if real.clauses else "?"
    supplied = answerer(ReplyLLM(f"See clause {label}.")).ask("sampling for packaged drinking water")
    check("/ask: citing a clause that was supplied passes", supplied.fallback_reason == "MODEL", label)

    context = "REFERENCE: Clause 9, PDF page 14\n9 SAMPLING\nsee 5.2.1 to 5.2.9 and Annex B"
    bad = guard(CopilotAnswer(answer="Clause 5.9.9 requires it."), context)
    check("copilot: an invented clause is withheld", bad.withheld and bad.withheld_reason == "FABRICATED_CLAUSE")
    for text in ["It holds 1.5 litres.", "It weighs 9.1 kg.", "See clause 9 and Annex B.", "given in 5.2.3"]:
        ok = guard(CopilotAnswer(answer=text), context)
        check(f"copilot: {text!r} passes", not ok.withheld, ok.withheld_reason)
    check("copilot: an unsupplied Annex is withheld",
          guard(CopilotAnswer(answer="Annex D says so."), context).withheld)
    check("a bare '9' elsewhere in the context does not license 'clause 7'",
          clauses.unsupported_citations("clause 7", "Price Group 7") == {"7"})


def _standard(number: str):
    return next(i for i in ENGINE._items if i.category == "indian_standards" and i.standard_number == number)


def test_residual_ranking() -> None:
    water = _standard("IS 14543:2016")
    residual = clauses.residual_query(water, "sampling for packaged drinking water")
    check("residual: the words that identified the standard are removed", residual == "sampling", residual)
    got = clauses.attach([r for r in ENGINE.search("sampling for packaged drinking water").results
                          if r.item.standard_number == "IS 14543:2016"], "sampling for packaged drinking water")
    check("residual: 'sampling' ranks clause 9 SAMPLING first on IS 14543:2016",
          got and clauses.label_of(got[0]) == "9", [clauses.label_of(c) for c in got])
    for query in ["packaged drinking water", "IS 14543:2016", "tell me about IS 14543:2016"]:
        got = clauses.attach([r for r in ENGINE.search(query).results
                              if r.item.standard_number == "IS 14543:2016"], query)
        check(f"residual: {query!r} attaches the SCOPE clause only",
              [clauses.label_of(c) for c in got] == ["1"], [clauses.label_of(c) for c in got])
    marking = "what are the marking requirements under IS 14543:2016"
    check("residual: process words drop, a word naming this standard's own section heading stays",
          clauses.residual_query(water, marking) == "marking", clauses.residual_query(water, marking))
    got = clauses.attach([r for r in ENGINE.search(marking).results
                          if r.item.standard_number == "IS 14543:2016"], marking)
    check("residual: the IS 14543 marking question attaches only marking clauses",
          [clauses.label_of(c) for c in got] == ["7.3", "8"], [clauses.label_of(c) for c in got])
    kettle = answerer(ReplyLLM()).ask("marking on an electric kettle")
    check("residual: 'marking on an electric kettle' ranks clause 8 MARKING first",
          kettle.clauses and clauses.label_of(kettle.clauses[0]) == "8",
          [clauses.label_of(c) for c in kettle.clauses])
    check("residual: 'mandatory' is a process word, not a clause", clauses.residual_query(water, "is it mandatory") == "")
    check("rank_within is still a plain ranker over the whole query",
          clauses.label_of(clauses.rank_within("IS 14543:2016", "sampling for packaged drinking water")[0].item) != "9")


def test_guard_edges() -> None:
    context = ("REFERENCE: Clause 9, PDF page 14\n9 SAMPLING\nsee 5.2.1 to 5.2.9 and Annex F, F-1.4 applies\n"
               "REFERENCE: Clause F-1, PDF page 19")
    for text in ["Use M-20 concrete.", "Class B-1 insulation is required.", "A Type A-2 plug.",
                 "See F-1.4.", "clauses 5.2.1 to 5.2.9", "clause 5.2.1-5.2.9", "Annex F-1 describes it."]:
        check(f"guard: {text!r} passes", not clauses.unsupported_citations(text, context),
              str(clauses.unsupported_citations(text, context)))
    check("guard: an invented 'F-9.9' is withheld", clauses.unsupported_citations("See F-9.9.", context) == {"F-9.9"})
    for text in ["clauses 5.2.1 to 5.2.99", "clause 5.2.1-5.2.77", "clauses 5.2.77 to 5.2.9"]:
        check(f"guard: a range with an invented end is withheld: {text!r}",
              len(clauses.unsupported_citations(text, context)) == 1)
    check("guard: Hindi 'अनुबंध D' (Annex D, not supplied) is withheld",
          clauses.unsupported_citations("अनुबंध D देखें", context) == {"Annex D"})
    check("guard: Hindi 'अनुबंध F' (supplied) passes", not clauses.unsupported_citations("अनुबंध F में", context))
    check("guard: अनुबंध meaning 'contract' is not a citation",
          not clauses.unsupported_citations("यह अनुबंध दोनों पक्षों के बीच है", context))
    q = "sampling for packaged drinking water"
    check("/ask: 'M-20 concrete' reaches the user",
          answerer(ReplyLLM("Use M-20 concrete for the plinth.")).ask(q).fallback_reason == "MODEL")
    check("/ask: an invented 'F-9.9' is withheld",
          answerer(ReplyLLM("F-9.9 sets the method.")).ask(q).fallback_reason == "GUARD:UNSUPPORTED_CLAUSE")
    check("/ask: a range with an invented end is withheld",
          answerer(ReplyLLM("See clauses 9 to 9.7.")).ask(q).fallback_reason == "GUARD:UNSUPPORTED_CLAUSE")
    check("copilot: 'Class B-1' passes, 'F-9.9' is withheld",
          not guard(CopilotAnswer(answer="Class B-1 insulation."), context).withheld
          and guard(CopilotAnswer(answer="F-9.9 applies."), context).withheld)


def test_fallback_reason_values() -> None:
    q = "sampling for packaged drinking water"
    cases = {
        "MODEL": ReplyLLM(),
        "RATE_LIMITED": RaisingLLM(CopilotUnavailable("RATE_LIMITED")),
        "NOT_CONFIGURED": RaisingLLM(CopilotUnavailable("NOT_CONFIGURED")),
        "PROVIDER_ERROR": RaisingLLM(LLMError("down")),
        "GUARD:WITHDRAWAL_CLAIM": ReplyLLM("IS 14543:2016 has been withdrawn."),
    }
    for expected, llm in cases.items():
        got = answerer(llm).ask(q).fallback_reason
        check(f"fallback_reason {expected}", got == expected, got)
    check("a daily limit reports RATE_LIMITED",
          answerer(RaisingLLM(CopilotUnavailable("DAILY_LIMIT"))).ask(q).fallback_reason == "RATE_LIMITED")
    check("fallback_reason ABSTAINED", answerer(ReplyLLM()).ask("shampoo").fallback_reason == "ABSTAINED")

    original = api_module.get_answerer
    api_module.get_answerer = lambda: answerer(RaisingLLM(LLMError("down")))
    try:
        body = ask_post(AskRequest(question=q))
        check("/ask carries fallback_reason and the attached clauses",
              body.fallback_reason == "PROVIDER_ERROR" and len(body.clauses) > 0
              and all(c.ocr_label == clauses.OCR_LABEL for c in body.clauses))
        check("/ask: an empty question says so", ask_post(AskRequest(question=" ")).fallback_reason == "EMPTY_QUESTION")
    finally:
        api_module.get_answerer = original


def test_evidence_only_wording() -> None:
    for code in (lang.EN, lang.HI, lang.TE):
        text = lang.EVIDENCE_ONLY[code]
        check(f"{code}: EVIDENCE_ONLY mentions OCR clause text", "OCR" in text)
    check("en: it no longer calls every record verified BIS records",
          "verified BIS records" not in lang.EVIDENCE_ONLY[lang.EN]
          and "Records marked verified" in lang.EVIDENCE_ONLY[lang.EN])
    check("hi: it separates verified records from OCR clause text",
          "'सत्यापित' चिह्नित" in lang.EVIDENCE_ONLY[lang.HI] and "खंड" in lang.EVIDENCE_ONLY[lang.HI])
    check("te: it separates verified records from OCR clause text",
          "'ధృవీకరించబడింది'" in lang.EVIDENCE_ONLY[lang.TE] and "క్లాజ్" in lang.EVIDENCE_ONLY[lang.TE])
    results = ENGINE.search("sampling for packaged drinking water").results
    attached = clauses.attach(results, "sampling for packaged drinking water")
    rendered = render_evidence(results, lang.EN, attached)
    check("the fallback renders attached clauses with the OCR label and their reference",
          attached and clauses.OCR_LABEL in rendered and all(c.reference in rendered for c in attached))


def test_why_this_result() -> None:
    finder = ProductStandardFinder(ENGINE)
    water = next(r for r in finder.find("packaged drinking water").results
                 if r.item.standard_number == "IS 14543:2016")
    why = explain_candidate(water)
    check("IS 14543:2016 is clause-level with its scope quoted",
          why.text_level == "CLAUSE" and why.scope and clauses.label_of(why.scope[0]) == "1")
    check("…verbatim from the record", why.scope[0].content.startswith("1 SCOPE"))
    led = next(r for r in finder.find("self-ballasted LED lamp").results
               if r.item.standard_number == "IS 16102 (Part 1)")
    why = explain_candidate(led)
    check("IS 16102 (Part 1) is identity-level and says so",
          why.text_level == "IDENTITY" and not why.scope and "identity" in why.text_note
          and "not its text" in why.text_note)
    original = product_module.clauses_module.scope_of
    product_module.clauses_module.scope_of = lambda number: []
    try:
        why = explain_candidate(water)
        check("clause records but no scope clause: said plainly",
              why.text_level == "CLAUSE" and "not its scope clause" in why.text_note)
    finally:
        product_module.clauses_module.scope_of = original
    check("candidate selection is unchanged by the explanation",
          [r.item.id for r in finder.find("packaged drinking water").results]
          == [r.item.id for r in ProductStandardFinder(ENGINE).find("packaged drinking water").results])
    rows = _text_held({"text_note": "note", "scope": [api_module.clause_out(c).model_dump()
                                                      for c in clauses.scope_of("IS 14543:2016")]})
    check("the report prints the OCR label with every scope clause",
          len(rows) == 2 and "OCR text from a scanned BIS document" in rows[1][1])


def main() -> int:
    test_attached_only_when_confident()
    test_cap()
    test_no_attachment_on_abstention_or_boundary()
    test_inherited_context_attaches_clauses()
    test_guard_both_directions()
    test_residual_ranking()
    test_guard_edges()
    test_fallback_reason_values()
    test_evidence_only_wording()
    test_why_this_result()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
