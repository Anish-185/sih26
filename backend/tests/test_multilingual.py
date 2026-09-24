"""Checks for Milestone 17 — multilingual BIS assistant (English, Hindi, Telugu).

The whole point of this milestone is that the LANGUAGE OF INTERACTION changes
and the SOURCE OF TRUTH does not. These checks lock that down:

  detection    deterministic script detection, no model, no network
  selection    an explicit language always beats detection; "auto" detects
  aliases      a small table maps known Hindi / Telugu product and BIS terms to
               their canonical English, and every canonical term it maps to
               actually retrieves something from the verified knowledge base
  same answer  a Hindi or Telugu query retrieves the SAME verified record, with
               the same standard number, record id and source URL, as the
               equivalent English query
  no invention an unknown product in any language abstains — it never produces
               a standard
  regression   existing English behaviour is byte-for-byte unchanged, including
               the system prompt the model receives
  isolation    the knowledge base, the retrieval normalizer and OCR are untouched

Every LLM call is stubbed — this suite spends no OpenRouter or LM Studio quota
and needs neither running.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_multilingual.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

import app.api as api_module  # noqa: E402
from app import language as lang  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.main import app  # noqa: E402
from app.rag import SYSTEM_PROMPT, BISQuestionAnswerer  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402
from app.retrieval.text import normalize  # noqa: E402

PASS = 0
FAIL = 0

ENGINE = SearchEngine()
CLIENT = TestClient(app)

# Equivalent questions, one per language. Same product, same intent.
KETTLE = {
    lang.EN: "Which Indian Standard applies to electric kettles?",
    lang.HI: "इलेक्ट्रिक केतली के लिए कौन सा मानक है?",
    lang.TE: "ఎలక్ట్రిక్ కెటిల్‌కు ఏ ప్రమాణం వర్తిస్తుంది?",
}
HINGLISH = "Electric kettle ke liye kaunsa BIS standard hai?"
TANGLISH = "Electric kettle కి ఏ BIS standard వర్తిస్తుంది?"


def indic(text: str) -> bool:
    """True when the text actually contains Devanagari or Telugu.

    The right question for "was this translated?" — the knowledge base
    legitimately contains the rupee sign, em-dashes and curly quotes, so
    ``isascii()`` would be a false alarm.
    """
    counts = lang.script_counts(text or "")
    return counts[lang.HI] > 0 or counts[lang.TE] > 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


class FakeLLM:
    """Stands in for the local LLM. Spends nothing; records what it was sent."""

    def __init__(self, reply: str = "GROUNDED ANSWER") -> None:
        self.reply = reply
        self.system_prompts: list[str] = []
        self.user_prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str,
                 temperature: float = 0.1, max_tokens: int = 400) -> str:
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        return self.reply


class RaisingLLM:
    def generate(self, **_kw) -> str:
        raise LLMError("could not reach LM Studio (ConnectError)")


def answerer(llm=None) -> tuple[BISQuestionAnswerer, FakeLLM]:
    fake = llm or FakeLLM()
    return BISQuestionAnswerer(search_engine=ENGINE, llm=fake), fake


def ask_http(question: str, language: str | None = None, llm=None) -> dict:
    """Drive the real ASGI app with the LLM stubbed out."""
    fake = llm or FakeLLM()
    real = api_module.get_answerer()
    saved = real.llm
    real.llm = fake
    try:
        body: dict = {"question": question}
        if language is not None:
            body["language"] = language
        response = CLIENT.post("/ask", json=body)
        return {"status": response.status_code, "body": response.json(), "llm": fake}
    finally:
        real.llm = saved


# --------------------------------------------------------- 1. detection


def test_language_detection() -> None:
    print("\n[1] deterministic language detection")

    check("English is detected", lang.detect(KETTLE[lang.EN]) == lang.EN)
    check("Hindi (Devanagari) is detected", lang.detect(KETTLE[lang.HI]) == lang.HI)
    check("Telugu is detected", lang.detect(KETTLE[lang.TE]) == lang.TE)

    check("empty text is English", lang.detect("") == lang.EN)
    check("a bare standard number is English", lang.detect("IS 367:1993") == lang.EN)
    check("digits and punctuation are English", lang.detect("1786 / 2008 — ?") == lang.EN)

    # Mixed text: a real run of an Indian script wins, conservatively.
    check("Hinglish (romanized Hindi) is English — there is no Devanagari",
          lang.detect(HINGLISH) == lang.EN)
    check("English product name + Telugu question is Telugu", lang.detect(TANGLISH) == lang.TE)
    check("mostly English with a Hindi phrase is Hindi",
          lang.detect("What standard applies to इलेक्ट्रिक केतली?") == lang.HI)
    check("a single stray Indic character is not a language",
          lang.detect("BIS standard क") == lang.EN)

    counts = lang.script_counts("इलेक्ट्रिक kettle ఎలక్ట్రిక్")
    check("script counting sees both scripts", counts[lang.HI] > 0 and counts[lang.TE] > 0)
    check("the larger script wins a genuinely mixed query",
          lang.detect("इलेक्ट्रिक केतली मानक ఏ") == lang.HI)

    check("detection needs no model and no network — it is a pure function",
          lang.detect(KETTLE[lang.HI]) == lang.detect(KETTLE[lang.HI]) == lang.HI)


# --------------------------------------------------------- 2. selection


def test_language_selection() -> None:
    print("\n[2] explicit language selection beats detection")

    for code in (lang.EN, lang.HI, lang.TE):
        check(f"language={code} is honoured on an English query",
              lang.resolve(KETTLE[lang.EN], code) == code)
        check(f"language={code} is honoured on a Hindi query",
              lang.resolve(KETTLE[lang.HI], code) == code)

    check("auto detects Hindi", lang.resolve(KETTLE[lang.HI], lang.AUTO) == lang.HI)
    check("auto detects Telugu", lang.resolve(KETTLE[lang.TE], lang.AUTO) == lang.TE)
    check("auto detects English", lang.resolve(KETTLE[lang.EN], lang.AUTO) == lang.EN)
    check("a missing language behaves as auto", lang.resolve(KETTLE[lang.TE], None) == lang.TE)
    check("an empty language behaves as auto", lang.resolve(KETTLE[lang.HI], "") == lang.HI)
    check("case and padding are tolerated", lang.resolve(KETTLE[lang.EN], "  HI ") == lang.HI)
    check("an unsupported code falls back to detection, never an error",
          lang.resolve(KETTLE[lang.TE], "fr") == lang.TE)

    check("selecting Hindi answers Hindi even when the query is English",
          answerer()[0].ask(KETTLE[lang.EN], language=lang.HI).language == lang.HI)
    check("selecting English answers English even when the query is Telugu",
          answerer()[0].ask(KETTLE[lang.TE], language=lang.EN).language == lang.EN)


# --------------------------------------------------------- 3. aliases


def test_retrieval_aliases() -> None:
    print("\n[3] the alias table maps onto the real knowledge base")

    # Every canonical PRODUCT term must actually retrieve something, or the
    # table has drifted away from the knowledge base. BIS vocabulary words
    # ("standard", "certification") are deliberately retrieval stopwords — they
    # appear in nearly every record and carry no ranking signal — so they are
    # mapped for the reader's sake, not to retrieve on their own.
    from app.retrieval.text import STOPWORDS

    empty = [
        canonical for canonical in lang.ALIASES
        if canonical not in STOPWORDS and not ENGINE.search(canonical, limit=1).results
    ]
    check("every canonical term retrieves verified evidence, unless it is a stopword",
          not empty, "; ".join(empty[:4]))
    check("'standard' retrieves nothing because it IS a retrieval stopword",
          "standard" in STOPWORDS and not ENGINE.search("standard", limit=1).results)

    check("the table stays small and maintainable", len(lang.ALIASES) <= 40, str(len(lang.ALIASES)))

    # No alias may be a bare English word already meaningful to retrieval — that
    # would rewrite English queries.
    ascii_aliases = [
        a for aliases in lang.ALIASES.values() for a in aliases if a.isascii()
    ]
    check("no alias is plain ASCII — aliases are non-English spellings only",
          not ascii_aliases, "; ".join(ascii_aliases[:3]))

    # Filler words must not be real knowledge-base terms.
    vocabulary = set()
    for item in ENGINE.items:
        vocabulary.update(normalize(item.title).split())
        for keyword in item.keywords:
            vocabulary.update(normalize(keyword).split())
    clashes = sorted(lang.FILLER & vocabulary)
    check("no filler word is a term in the knowledge base", not clashes, "; ".join(clashes[:4]))

    hindi = lang.normalize_query(KETTLE[lang.HI])
    check("a Hindi kettle query maps to the canonical concept",
          "electric kettle" in hindi.concepts, str(hindi.concepts))
    telugu = lang.normalize_query(KETTLE[lang.TE])
    check("a Telugu kettle query maps to the canonical concept",
          "electric kettle" in telugu.concepts, str(telugu.concepts))
    check("both also map the BIS word for 'standard'",
          "standard" in hindi.concepts and "standard" in telugu.concepts)

    # Longest alias first: the specific phrase must win over the short one.
    check("a longer alias wins over a shorter one inside it",
          lang.normalize_query("इलेक्ट्रिक केतली").query.strip() == "electric kettle")

    check("Hinglish filler words are dropped for retrieval",
          set(lang.normalize_query(HINGLISH).dropped) >= {"ke", "liye", "kaunsa", "hai"},
          str(lang.normalize_query(HINGLISH).dropped))
    check("but the user's own question is never modified",
          lang.normalize_query(HINGLISH).original == HINGLISH)

    untouched = lang.normalize_query(KETTLE[lang.EN])
    check("an English query is passed through unchanged",
          untouched.query == KETTLE[lang.EN] and not untouched.changed)

    unknown = lang.normalize_query("ఇది ఒక తెలియని వస్తువు")
    check("an untranslatable query still reaches retrieval, never emptied",
          unknown.query.strip() != "")


# --------------------------------------------------------- 4. same evidence


def test_same_evidence_in_every_language() -> None:
    print("\n[4] every language retrieves the SAME verified evidence")

    results = {}
    for code, question in KETTLE.items():
        service, _ = answerer()
        results[code] = service.ask(question, language=lang.AUTO)

    english = results[lang.EN]
    baseline = [r.item.id for r in english.results]
    check("the English query retrieves evidence", len(baseline) > 0)

    # The same records, and the same best record. Tail ORDER may differ because
    # the questions genuinely differ in wording ("Which Indian Standard applies
    # to…" vs the rewritten Hindi) — that is retrieval doing its normal job on
    # different text, not the language layer changing the evidence.
    for code in (lang.HI, lang.TE):
        got = [r.item.id for r in results[code].results]
        check(f"{code} retrieves the same set of records as English",
              set(got) == set(baseline), f"{sorted(set(got) ^ set(baseline))}")
        check(f"{code} identifies the same best record as English",
              got[0] == baseline[0], f"{got[0]} vs {baseline[0]}")

    numbers = {code: r.results[0].item.standard_number for code, r in results.items()}
    check("the same standard number in all three languages",
          len(set(numbers.values())) == 1, str(numbers))
    check("and it is the real kettle standard", numbers[lang.EN] == "IS 367:1993", str(numbers))

    urls = {code: r.results[0].item.source_url for code, r in results.items()}
    check("the source URL is identical and untranslated", len(set(urls.values())) == 1)
    check("the source URL is still the official BIS one",
          "bis.gov.in" in (urls[lang.HI] or ""), str(urls[lang.HI]))

    contents = {code: r.results[0].item.content for code, r in results.items()}
    check("the stored evidence text is byte-for-byte identical in every language",
          len(set(contents.values())) == 1)
    check("and it was never translated into the query's script",
          not any(indic(text) for text in contents.values()))

    check("each answer reports its own language",
          [results[c].language for c in (lang.EN, lang.HI, lang.TE)] == [lang.EN, lang.HI, lang.TE])

    # Mixed-language queries reach the same record.
    for label, query in (("Hinglish", HINGLISH), ("Telugu + English", TANGLISH)):
        service, _ = answerer()
        out = service.ask(query)
        top = out.results[0].item.standard_number if out.results else None
        check(f"a {label} query reaches the same standard", top == "IS 367:1993", str(top))

    # A second concept, to prove it is not one hard-coded product.
    service, _ = answerer()
    gold = service.ask("सोने की हॉलमार्किंग के बारे में बताइए")
    check("a Hindi hallmarking query retrieves hallmarking evidence",
          gold.results and any("hallmark" in r.item.id for r in gold.results),
          str([r.item.id for r in gold.results[:2]]))


# --------------------------------------------------------- 5. no invention


def test_no_invented_standards() -> None:
    print("\n[5] an unknown product abstains in every language")

    known = {i.standard_number for i in ENGINE.items if i.standard_number}
    unknown = {
        lang.EN: "Which standard applies to a zzqq flurbwidget?",
        lang.HI: "ज़क्वि फ्लर्बविजेट के लिए कौन सा मानक है?",
        lang.TE: "జ్క్వి ఫ్లర్బ్‌విడ్జెట్‌కు ఏ ప్రమాణం వర్తిస్తుంది?",
    }
    for code, question in unknown.items():
        service, fake = answerer()
        out = service.ask(question)
        invented = [r.item.standard_number for r in out.results
                    if r.item.standard_number and r.item.standard_number not in known]
        check(f"{code}: no standard outside the knowledge base is returned",
              not invented, str(invented[:2]))
        if not out.results:
            check(f"{code}: abstention makes no LLM call", fake.system_prompts == [])
            check(f"{code}: the abstention message is in that language",
                  out.answer == lang.insufficient(out.language), out.answer[:40])

    check("the Hindi abstention message is actually Devanagari",
          lang.detect(lang.insufficient(lang.HI)) == lang.HI)
    check("the Telugu abstention message is actually Telugu",
          lang.detect(lang.insufficient(lang.TE)) == lang.TE)
    check("the abstention message preserves the BIS name",
          all("BIS" in lang.insufficient(c) for c in lang.SUPPORTED))


# --------------------------------------------------------- 6. the prompt


def test_the_model_is_told_the_language() -> None:
    print("\n[6] the language instruction reaches the LLM adapter")

    service, fake = answerer()
    service.ask(KETTLE[lang.EN])
    check("English adds nothing to the system prompt — unchanged behaviour",
          fake.system_prompts[0] == SYSTEM_PROMPT)

    for code, name in ((lang.HI, "Hindi"), (lang.TE, "Telugu")):
        service, fake = answerer()
        service.ask(KETTLE[lang.EN], language=code)
        prompt = fake.system_prompts[0]
        check(f"{code}: the prompt names the language", f"LANGUAGE OF THE ANSWER: {name}" in prompt)
        check(f"{code}: it still carries every original grounding rule",
              SYSTEM_PROMPT.strip() in prompt)
        check(f"{code}: identifiers are ordered preserved, not translated",
              "never translated" in prompt and "IS 367:1993" in prompt)
        check(f"{code}: insufficiency must still be stated, in that language",
              "does not answer the question" in prompt)

    # The model receives the user's ORIGINAL question, not the rewritten one.
    service, fake = answerer()
    service.ask(KETTLE[lang.HI])
    check("the model is sent the question exactly as the user wrote it",
          KETTLE[lang.HI] in fake.user_prompts[0])
    check("the evidence in the prompt is the canonical English record",
          "IS 367" in fake.user_prompts[0] and "SOURCE URL:" in fake.user_prompts[0])

    check("instruction() is empty for English", lang.instruction(lang.EN) == "")
    check("apply() is a no-op for English",
          lang.apply(SYSTEM_PROMPT, lang.EN) == SYSTEM_PROMPT)


# ----------------------------------- 6b. the RETURNED ANSWER is in that language
#
# The above only proves the right instruction reaches the model. This proves
# the plumbing that carries the model's reply back to the user does not lose,
# translate or re-English it — using a stub whose reply genuinely varies by
# language (real Hindi/Telugu Unicode text), not a fixed English string. This
# does NOT prove a live deployed model actually obeys the instruction — no
# OpenRouter call is made anywhere in this suite — it proves that IF the model
# writes Hindi/Telugu, that is exactly what reaches the HTTP response.

_CANNED = {
    lang.EN: "This is the answer, in English, grounded in the retrieved BIS evidence for IS 367:1993.",
    lang.HI: "यह उत्तर हिंदी में है, IS 367:1993 के लिए प्राप्त BIS साक्ष्य पर आधारित है।",
    lang.TE: "ఈ సమాధానం తెలుగులో ఉంది, IS 367:1993 కోసం పొందిన BIS ఆధారాలపై ఆధారపడి ఉంది।",
}


class LanguageAwareLLM:
    """Returns a reply actually written in whatever language the system prompt
    instructs — proving the response-language plumbing, not the model's own
    compliance (no live call is ever made)."""

    def generate(self, *, system_prompt: str, user_prompt: str,
                 temperature: float = 0.1, max_tokens: int = 400) -> str:
        for code, name in ((lang.HI, "Hindi"), (lang.TE, "Telugu")):
            if f"LANGUAGE OF THE ANSWER: {name}" in system_prompt:
                return _CANNED[code]
        return _CANNED[lang.EN]


def test_the_returned_answer_is_actually_in_the_requested_language() -> None:
    print("\n[6b] the answer text itself — not just the prompt — is in the requested language")

    for code in (lang.EN, lang.HI, lang.TE):
        out = ask_http(KETTLE[lang.EN], language=code, llm=LanguageAwareLLM())
        answer = out["body"]["answer"]
        check(f"/ask {code}: the response reports the requested language",
              out["body"]["language"] == code)
        check(f"/ask {code}: the ANSWER TEXT is actually in that script",
              lang.detect(answer) == code, answer)

    # Certification's explain=true path goes through the same lang.apply()
    # pattern; verify its answer text the same way.
    real = api_module.get_certification_service()
    saved = real.llm
    real.llm = LanguageAwareLLM()
    try:
        for code in (lang.EN, lang.HI, lang.TE):
            res = CLIENT.post("/certification-guidance", json={
                "question": "electric kettle certification", "explain": True, "language": code,
            })
            check(f"/certification-guidance {code}: 200", res.status_code == 200, res.text[:200])
            body = res.json()
            check(f"/certification-guidance {code}: the response reports the requested language",
                  body["language"] == code)
            check(f"/certification-guidance {code}: the ANSWER TEXT is actually in that script",
                  lang.detect(body["answer"]) == code, body["answer"])
    finally:
        real.llm = saved


# --------------------------------------------------------- 7. HTTP contract


def test_http_contract() -> None:
    print("\n[7] /ask stays backward compatible and reports the language")

    # An existing client sends no language field at all.
    legacy = ask_http(KETTLE[lang.EN])
    check("a request with no language field still works", legacy["status"] == 200)
    check("and is answered in English", legacy["body"]["language"] == lang.EN)
    check("every pre-existing field is still present",
          {"question", "answer", "grounded", "source_count", "sources"} <= set(legacy["body"]))
    check("its system prompt is byte-for-byte the pre-milestone one",
          legacy["llm"].system_prompts[0] == SYSTEM_PROMPT)

    for code in (lang.HI, lang.TE):
        out = ask_http(KETTLE[lang.EN], language=code)
        check(f"language={code} is accepted over HTTP", out["status"] == 200)
        check(f"language={code} is echoed back", out["body"]["language"] == code)

    auto = ask_http(KETTLE[lang.TE], language="auto")
    check("auto over HTTP resolves to the detected language", auto["body"]["language"] == lang.TE)
    check("the response never echoes 'auto'", auto["body"]["language"] in lang.SUPPORTED)
    check("matched concepts are reported",
          "electric kettle" in auto["body"]["matched_concepts"],
          str(auto["body"]["matched_concepts"]))

    body = auto["body"]
    check("sources carry the untranslated standard number",
          body["sources"][0]["standard_number"] == "IS 367:1993")
    check("sources carry the untranslated record id and URL",
          not indic(body["sources"][0]["id"])
          and "bis.gov.in" in (body["sources"][0]["source_url"] or ""))

    bad = CLIENT.post("/ask", json={"question": "x", "language": 5})
    check("a non-string language is rejected with 422", bad.status_code == 422, str(bad.status_code))

    unknown_code = ask_http(KETTLE[lang.HI], language="xx")
    check("an unknown language code falls back to detection, not an error",
          unknown_code["status"] == 200 and unknown_code["body"]["language"] == lang.HI)

    empty = CLIENT.post("/ask", json={"question": "", "language": "hi"})
    check("an empty question is answered in the requested language",
          empty.status_code == 200 and empty.json()["language"] == lang.HI)
    check("and that prompt is in Devanagari",
          lang.detect(empty.json()["answer"]) == lang.HI)

    # An LLM outage falls back to the retrieved evidence — in the user's language
    # (Phase 1, Part C). Never a fabricated answer, and never a dead end.
    real = api_module.get_answerer()
    saved = real.llm
    real.llm = RaisingLLM()
    try:
        down = CLIENT.post("/ask", json={"question": KETTLE[lang.HI], "language": "hi"})
    finally:
        real.llm = saved
    body = down.json()
    check("an LLM outage returns the evidence, never a fabricated answer",
          down.status_code == 200 and body["explained"] is False, str(down.status_code))
    check("and MetrIQ explains the fallback in the requested language",
          body["language"] == lang.HI and lang.EVIDENCE_ONLY[lang.HI] in body["answer"])


# --------------------------------------------------------- 8. other routes


def test_other_grounded_routes() -> None:
    print("\n[8] certification and laboratory accept a language too")

    hindi = CLIENT.post("/certification-guidance",
                        json={"question": "इलेक्ट्रिक केतली के लिए प्रमाणन", "explain": False})
    english = CLIENT.post("/certification-guidance",
                          json={"question": "electric kettle certification", "explain": False})
    check("a Hindi certification query is accepted", hindi.status_code == 200)
    check("and reports Hindi", hindi.json()["language"] == lang.HI)
    check("and reaches the same standard as the English query",
          hindi.json()["journey"]["standard_number"] == english.json()["journey"]["standard_number"]
          == "IS 367:1993")
    check("the journey's own text stays canonical, never translated",
          not indic(hindi.json()["journey"]["scheme"]["name"]))
    check("the journey's evidence quotes stay canonical, never translated",
          not any(indic(e["quote"])
                  for s in hindi.json()["journey"]["steps"] for e in s["evidence"]))

    lab = CLIENT.post("/laboratory-search",
                      json={"query": "सीमेंट परीक्षण प्रयोगशाला", "explain": False})
    check("a Hindi laboratory query is accepted", lab.status_code == 200)
    check("and reports Hindi", lab.json()["language"] == lang.HI)
    check("and retrieves evidence rather than abstaining", lab.json()["source_count"] > 0,
          str(lab.json()["source_count"]))

    legacy = CLIENT.post("/laboratory-search", json={"query": "cement testing", "explain": False})
    check("a laboratory request with no language still works", legacy.status_code == 200)
    check("and defaults to English", legacy.json()["language"] == lang.EN)


# --------------------------------------------------------- 9. isolation


def test_nothing_else_changed() -> None:
    print("\n[9] the knowledge base, retrieval and OCR are untouched")

    check("the retrieval normalizer is still ASCII-only and unchanged",
          normalize("What is HUID???") == "what is huid")
    check("and still drops non-ASCII entirely — the language layer runs before it",
          normalize("इलेक्ट्रिक केतली") == "")

    translated = [i.id for i in ENGINE.items if indic(i.content) or indic(i.title)]
    check("no knowledge record was translated into Hindi or Telugu",
          not translated, "; ".join(translated[:3]))
    check("no translated copy of the knowledge base exists",
          not (Path(__file__).resolve().parents[2] / "data" / "knowledge_hi").exists())

    # The language module must not reach into retrieval, OCR or the models.
    source = (Path(__file__).resolve().parents[1] / "app" / "language.py").read_text()
    for forbidden in ("import httpx", "from app.ocr", "from app.llm", "from app.openrouter",
                      "from app.vision", "import requests"):
        check(f"the language layer does not use {forbidden!r}", forbidden not in source)

    # OCR evidence is never language-processed.
    ocr_source = (Path(__file__).resolve().parents[1] / "app" / "ocr.py").read_text()
    decl_source = (Path(__file__).resolve().parents[1] / "app" / "declarations.py").read_text()
    check("OCR does not import the language layer", "app.language" not in ocr_source)
    check("declaration extraction does not import the language layer",
          "app.language" not in decl_source)

    # Product identification and the vision fusion path are untouched.
    pid = (Path(__file__).resolve().parents[1] / "app" / "product_identification.py").read_text()
    check("product identification does not import the language layer", "app.language" not in pid)


def main() -> int:
    test_language_detection()
    test_language_selection()
    test_retrieval_aliases()
    test_same_evidence_in_every_language()
    test_no_invented_standards()
    test_the_model_is_told_the_language()
    test_the_returned_answer_is_actually_in_the_requested_language()
    test_http_contract()
    test_other_grounded_routes()
    test_nothing_else_changed()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
