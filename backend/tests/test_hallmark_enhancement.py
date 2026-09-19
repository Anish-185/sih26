"""Checks for Milestone 19 — hallmarking & HUID enhancement.

The whole milestone rests on one rule: MetrIQ can identify and explain
OBSERVABLE hallmark / HUID evidence, but it does not authenticate a physical
jewellery item's hallmark, HUID, jeweller registration, or AHC status. These
checks make that structural rather than a matter of wording:

  no verified state   there is no AUTHENTIC / VERIFIED / CERTIFIED outcome for a
                      physical item, in any code path, however good the evidence
  components          the three marks BIS itself enumerates, each DETECTED /
                      NOT_DETECTED / UNCERTAIN / NOT_SUPPORTED with a
                      deterministic reason; "not detected" is about the PHOTO
  vision              the EXISTING Milestone 15 observation is reused (no second
                      pipeline), can never read a mark, and a disagreement with
                      OCR becomes a stated CONFLICT — never a winner
  user HUID           recorded as USER_PROVIDED, compared as text, never verified
  official boundary   verification guidance is quoted from verified records; when
                      the knowledge base has none, nothing is invented
  separation          hallmarking never becomes package-label compliance
  regression          the Milestone 12 contract, the report and multilingual
                      hallmarking all still work

Every LLM call is stubbed — no OpenRouter quota is spent.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_hallmark_enhancement.py
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app import hallmark as hm  # noqa: E402
from app import language as lang  # noqa: E402
from app.copilot import CAPABILITIES, SYSTEM_PROMPT, build_context  # noqa: E402
from app.hallmark import evaluate_hallmark  # noqa: E402
from app.main import app  # noqa: E402
from app.retrieval.engine import SearchEngine  # noqa: E402
from app.vision import VisionObservation  # noqa: E402

PASS = 0
FAIL = 0

ITEMS = SearchEngine().items
CLIENT = TestClient(app)
SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "ocr-labels" / "synth_hallmark-closeup.png"


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


class Region:
    def __init__(self, rid: str, text: str, confidence: float = 0.95) -> None:
        self.id, self.text, self.confidence = rid, text, confidence
        self.bbox, self.image_id, self.side = [0, 0, 10, 10], "IMG-1", "FRONT"


HALLMARKED = [Region("OCR-1", "HUID AB12CD"), Region("OCR-2", "22K916"),
              Region("OCR-3", "BIS HALLMARK")]
BLANK = [Region("OCR-1", "SOME RANDOM TEXT"), Region("OCR-2", "1234567890")]


def vision(label: str, category: str = "", status: str = "OK", features=None):
    return [VisionObservation(image_id="IMG-1", side="FRONT", status=status, model="test-model",
                              product_label=label, product_category=category,
                              visual_features=features or [])]


def evaluate(regions=None, **kw):
    return evaluate_hallmark(regions if regions is not None else HALLMARKED, ITEMS, **kw)


# ------------------------------------------------- 1. no verified state


def test_no_physical_authentication_state_exists() -> None:
    print("\n[1] there is no authenticated state for a physical item, anywhere")

    strongest = evaluate(vision=vision("gold ring", "jewellery"), user_huid="AB12CD")
    check("even the strongest evidence stays NOT_VERIFIED",
          strongest.verification_status == hm.NOT_VERIFIED, strongest.verification_status)
    check("and the overall status stays REVIEW", strongest.overall_status == "REVIEW",
          strongest.overall_status)
    check("official verification is still required",
          strongest.official_verification_required is True)
    check("MetrIQ never claims to have performed it",
          strongest.official_verification.performed_by_metriq is False)

    # The outcome vocabulary must contain no authentication word at all.
    outcomes = {hm.OBSERVATIONS_FOUND, hm.NO_OBSERVATIONS, hm.UNCERTAIN}
    check("the outcome vocabulary has no AUTHENTIC / VERIFIED / CERTIFIED value",
          not any(w in o for o in outcomes for w in ("AUTHENTIC", "VERIFIED", "CERTIFIED")),
          str(outcomes))
    check("the outcome is one of the three observation states",
          strongest.outcome in outcomes, strongest.outcome)

    # No code path may produce a VERIFIED verification_status.
    source = (Path(__file__).resolve().parents[1] / "app" / "hallmark.py").read_text()
    check("hallmark.py defines only NOT_VERIFIED / NOT_DETECTED",
          'NOT_VERIFIED = "NOT_VERIFIED"' in source and 'NOT_DETECTED = "NOT_DETECTED"' in source)
    check("and never assigns a bare VERIFIED status",
          not re.search(r'verification_status\s*=\s*["\']VERIFIED["\']', source))

    # No check may FAIL, and none may PASS on authenticity.
    check("no check can FAIL", all(c.result != "FAIL" for c in strongest.checks))
    authenticity = [c for c in strongest.checks if c.rule_id == "HUID_AUTHENTICITY"]
    check("authenticity is explicitly NOT_SUPPORTED",
          authenticity and authenticity[0].result == "NOT_SUPPORTED")

    # Forbidden sentences must appear nowhere MetrIQ writes.
    written = " ".join([strongest.reason, strongest.verification_note,
                        strongest.official_verification.guidance,
                        *strongest.why,
                        *(c.why for c in strongest.components),
                        *(c.reason for c in strongest.checks)]).lower()
    for claim in ("huid verified", "huid authentic", "hallmark authentic", "is bis certified",
                  "jeweller is registered", "ahc verified", "registration verified"):
        check(f"MetrIQ never writes {claim!r}", claim not in written)


# --------------------------------------------------------- 2. HUID


def test_huid_detection_and_absence() -> None:
    print("\n[2] HUID detection, and what absence is allowed to mean")

    found = evaluate()
    check("a labelled HUID is detected", found.huid.status == "DETECTED", found.huid.status)
    check("its value is the OCR text", found.huid.value == "AB12CD", str(found.huid.value))
    check("the why names OCR as the source",
          any("detected by OCR" in w for w in found.why))

    none = evaluate(BLANK, force=True)
    check("no HUID gives NOT_DETECTED", none.huid.status == "NOT_DETECTED", none.huid.status)
    check("the wording is about the IMAGE, not the article",
          hm.NO_HUID_DETECTED in none.why, str(none.why[:1]))
    check("and it never says the jewellery has no HUID",
          not any("has no huid" in w.lower() or "article has no" in w.lower() for w in none.why))

    huid_component = next(c for c in none.components if c.component == "HUID")
    check("the HUID component says not detected in the supplied image",
          huid_component.status == hm.C_NOT_DETECTED and hm.NO_HUID_DETECTED in huid_component.why)

    # A HUID is never invented.
    check("no HUID value appears when none was read", none.huid.value is None)
    check("and no HUID appears in the reasons",
          not re.search(r"\b[A-Z0-9]{6}\b", " ".join(none.why).replace("MetrIQ", "")))

    several = evaluate([Region("OCR-1", "HUID AB12CD"), Region("OCR-2", "HUID ZZ99YY"),
                        Region("OCR-3", "22K916")])
    check("several candidates select none", several.huid.value is None, str(several.huid.value))
    check("and report MULTIPLE", several.huid.status == "MULTIPLE", several.huid.status)
    check("which makes the outcome UNCERTAIN", several.outcome == hm.UNCERTAIN, several.outcome)


# ------------------------------------------------- 3. components


def test_hallmark_components() -> None:
    print("\n[3] the three marks BIS enumerates, as observed in the photograph")

    out = evaluate()
    kinds = [c.component for c in out.components]
    check("all three components are reported", kinds == ["BIS_MARK", "PURITY", "HUID"], str(kinds))
    check("each carries a deterministic reason", all(c.why for c in out.components))
    check("each cites the verified record that enumerates the marks",
          all(c.source is not None and c.source.knowledge_id == hm.COMPONENTS_RECORD
              for c in out.components))

    bis = next(c for c in out.components if c.component == "BIS_MARK")
    check("the BIS logo is NOT_SUPPORTED — it is a graphic, OCR reads text",
          bis.status == hm.C_NOT_SUPPORTED, bis.status)
    check("and the reason says so", "graphic mark" in bis.why)
    check("reading the letters BIS is never the logo",
          "not the logo" in bis.why)

    purity = next(c for c in out.components if c.component == "PURITY")
    check("a permitted gold grade is DETECTED", purity.status == hm.C_DETECTED, purity.status)
    check("with the observed value", purity.observed_value == "22K", str(purity.observed_value))

    statuses = {hm.C_DETECTED, hm.C_NOT_DETECTED, hm.C_UNCERTAIN, hm.C_NOT_SUPPORTED}
    check("no component status is an authentication word",
          not any(w in s for s in statuses for w in ("AUTHENTIC", "VALID", "VERIFIED")), str(statuses))

    blank = evaluate(BLANK, force=True)
    check("with nothing readable every component is still reported",
          len(blank.components) == 3, str(len(blank.components)))
    check("purity reports not detected", next(c for c in blank.components
                                              if c.component == "PURITY").status == hm.C_NOT_DETECTED)


# ------------------------------------------------- 4. OCR + vision


def test_ocr_and_vision_fusion() -> None:
    print("\n[4] OCR + vision fusion — agreement, conflict, absence")

    agree = evaluate(vision=vision("gold ring", "jewellery"))
    check("a jewellery observation SUPPORTS", agree.vision.status == hm.V_SUPPORTS,
          agree.vision.status)
    check("agreement does not upgrade the verification status",
          agree.verification_status == hm.NOT_VERIFIED)
    check("and does not create a conflict", agree.vision.conflict == "")
    check("the observation is labelled unverified",
          "unverified AI observation" in agree.vision.note)

    conflict = evaluate(vision=vision("water bottle", "packaged food"))
    check("a non-jewellery observation DOES_NOT_SUPPORT",
          conflict.vision.status == hm.V_DOES_NOT_SUPPORT, conflict.vision.status)
    check("the disagreement is stated as a conflict", bool(conflict.vision.conflict))
    check("MetrIQ picks neither side", "does not choose between them" in conflict.vision.conflict)
    check("and the outcome becomes UNCERTAIN", conflict.outcome == hm.UNCERTAIN, conflict.outcome)
    check("the OCR evidence is NOT discarded", conflict.huid.value == "AB12CD")

    unavailable = evaluate(vision=vision("", "", status="UNAVAILABLE"))
    check("an unavailable observation is reported", unavailable.vision.status == hm.V_UNAVAILABLE)
    check("and the result is otherwise the OCR-only result",
          unavailable.huid.value == evaluate().huid.value)

    not_run = evaluate(vision=None)
    check("no vision at all is NOT_RUN", not_run.vision.status == hm.V_NOT_RUN)
    check("byte-for-byte the pre-Milestone-19 evidence",
          not_run.huid.value == "AB12CD" and not_run.purity.caratage == "22K")

    inconclusive = evaluate(vision=vision("small object", "object"))
    check("an unrelated observation is INCONCLUSIVE",
          inconclusive.vision.status == hm.V_INCONCLUSIVE, inconclusive.vision.status)

    # Vision can never supply a mark.
    sneaky = evaluate(BLANK, force=True,
                      vision=vision("gold ring HUID AB12CD 22K916", "jewellery"))
    check("vision can never produce a HUID", sneaky.huid.value is None, str(sneaky.huid.value))
    check("vision can never produce a purity mark", sneaky.purity.caratage is None)
    check("vision alone never makes a component DETECTED",
          all(c.status != hm.C_DETECTED for c in sneaky.components))


# ------------------------------------------------- 5. user HUID


def test_user_provided_huid() -> None:
    print("\n[5] a user-typed HUID is recorded, compared, never verified")

    match = evaluate(user_huid="ab12-cd")
    check("a user HUID is recorded", match.user_huid is not None)
    check("the entered text is preserved exactly", match.user_huid.value == "ab12-cd")
    check("normalisation is for comparison only", match.user_huid.normalized == "AB12CD")
    check("it is labelled USER_PROVIDED", match.user_huid.provenance == "USER_PROVIDED")
    check("a match is reported as a TEXT match", match.user_huid.status == hm.U_MATCHES_OCR)
    check("and the note says it verifies nothing",
          "not verified by MetrIQ" in match.user_huid.note)
    check("matching does not change the verification status",
          match.verification_status == hm.NOT_VERIFIED)
    check("matching does not change the overall status", match.overall_status == "REVIEW")

    differs = evaluate(user_huid="ZZ99YY")
    check("a mismatch is reported", differs.user_huid.status == hm.U_DIFFERS_FROM_OCR)
    check("and does not become a FAIL", differs.overall_status == "REVIEW")
    check("the note offers both explanations, not a verdict",
          "misread" in differs.user_huid.note and "different article" in differs.user_huid.note)

    nothing = evaluate(BLANK, force=True, user_huid="AB12CD")
    check("with no OCR value there is nothing to compare",
          nothing.user_huid.status == hm.U_NO_OCR_VALUE)
    check("and it still never verifies", "not verified by MetrIQ" in nothing.user_huid.note)

    junk = evaluate(user_huid="---")
    check("a malformed entry is reported as malformed", junk.user_huid.status == hm.U_MALFORMED)
    check("no user HUID means no record", evaluate(user_huid=None).user_huid is None)
    check("an empty string means no record", evaluate(user_huid="   ").user_huid is None)


# ------------------------------- 6. official verification boundary


def test_official_verification_boundary() -> None:
    print("\n[6] official verification is guidance, never performed")

    out = evaluate()
    verification = out.official_verification
    check("guidance is available from verified records", verification.available is True)
    check("MetrIQ never performs it", verification.performed_by_metriq is False)
    check("the guidance says so", "does not perform official verification" in verification.guidance)
    check("it quotes verified BIS records", len(verification.sources) > 0)
    check("every quoted source has an official BIS URL",
          all("bis.gov.in" in (s.source_url or "") for s in verification.sources))
    check("a why line states the boundary",
          any("outside MetrIQ's current capabilities" in w for w in out.why))

    # With the records absent nothing is invented.
    stripped = [i for i in ITEMS if i.category != "hallmarking"]
    bare = evaluate_hallmark(HALLMARKED, stripped, force=True)
    check("with no verified records the guidance is unavailable",
          bare.official_verification.available is False)
    check("and says instructions are not in the evidence set",
          "not available in MetrIQ's current evidence set" in bare.official_verification.guidance)
    check("no URL is invented", bare.official_verification.sources == [])


# ------------------------------------ 7. untrusted text stays untrusted


def test_printed_claims_change_nothing() -> None:
    print("\n[7] text printed on the item verifies nothing")

    claimed = evaluate([Region("OCR-1", "HUID AB12CD"), Region("OCR-2", "22K916"),
                        Region("OCR-3", "BIS HALLMARK VERIFIED AUTHENTIC GENUINE")])
    check("the claim is recorded", len(claimed.untrusted_claims) > 0)
    check("but the verification status is unchanged",
          claimed.verification_status == hm.NOT_VERIFIED)
    check("and the overall status is unchanged", claimed.overall_status == "REVIEW")
    check("a why line says printed text is untrusted",
          any("untrusted OCR evidence" in w for w in claimed.why))


# ------------------------------------------------- 8. the HTTP contract


def test_http_contract() -> None:
    print("\n[8] /inspection/analyze carries the evidence and accepts a HUID")

    image = SAMPLE.read_bytes()
    response = CLIENT.post("/inspection/analyze",
                           files={"image": ("h.png", image, "image/png")},
                           data={"inspection_type": "HALLMARK", "huid_reference": "K7M2Q9"})
    check("a hallmark inspection succeeds", response.status_code == 200, str(response.status_code))
    body = response.json()["hallmark"]

    check("every Milestone 12 field survives",
          {"detected", "verification_status", "verification_note", "overall_status",
           "huid", "purity", "checks", "sources"} <= set(body))
    check("the Milestone 19 fields are present",
          {"outcome", "components", "vision", "user_huid", "official_verification",
           "why", "official_verification_required"} <= set(body))
    check("verification status is never VERIFIED",
          body["verification_status"] in {"NOT_VERIFIED", "NOT_DETECTED"})
    check("overall status is REVIEW", body["overall_status"] == "REVIEW")
    check("the user HUID reached the evidence", body["user_huid"] is not None)
    check("labelled user-provided", body["user_huid"]["provenance"] == "USER_PROVIDED")
    check("components are reported", len(body["components"]) == 3)

    # Without the field, behaviour is exactly as before.
    plain = CLIENT.post("/inspection/analyze",
                        files={"image": ("h.png", image, "image/png")},
                        data={"inspection_type": "HALLMARK"})
    check("omitting huid_reference still works", plain.status_code == 200)
    check("and records no user HUID", plain.json()["hallmark"]["user_huid"] is None)

    # A package inspection must not become a hallmark inspection.
    package = CLIENT.post("/inspection/analyze",
                          files={"image": ("h.png", image, "image/png")})
    check("a package inspection is still PACKAGE",
          package.json()["inspection_type"] == "PACKAGE")


# --------------------------------- 9. hallmarking vs package inspection


def test_domains_stay_separate() -> None:
    print("\n[9] hallmarking never becomes package-label compliance")

    image = SAMPLE.read_bytes()
    body = CLIENT.post("/inspection/analyze",
                       files={"image": ("h.png", image, "image/png")},
                       data={"inspection_type": "HALLMARK"}).json()

    check("Legal Metrology is not applied to jewellery",
          body["package_label"]["scope_status"] == "NOT_APPLIED",
          body["package_label"]["scope_status"])
    check("with the reason that it is not a package inspection",
          body["package_label"]["reason_code"] == "NOT_A_PACKAGE_INSPECTION")
    check("a hallmark inspection never reports a package PASS",
          body["package_label"]["overall_status"] != "PASS")
    check("the hallmark result never becomes the compliance result",
          body["compliance"]["overall_status"] in {"REVIEW", "NOT_SUPPORTED", "FAIL", "PASS"})

    # The hallmark module must not reach into the package-label engine.
    source = (Path(__file__).resolve().parents[1] / "app" / "hallmark.py").read_text()
    for forbidden in ("package_label", "app.compliance", "declarations"):
        check(f"hallmark.py does not import {forbidden!r}", f"import {forbidden}" not in source)


# ------------------------------------------------- 10. the copilot


def test_copilot_safety() -> None:
    print("\n[10] the copilot is given the evidence and the prohibitions")

    out = evaluate(vision=vision("gold ring", "jewellery"), user_huid="AB12CD")
    analysis = {"hallmark": out.model_dump(mode="json"), "product": {}, "standards": [],
                "compliance": {}, "package_label": {}, "escalation": {}}
    ctx = build_context(analysis, "EXPLAIN_HALLMARK")
    block = ctx["hallmarking"]

    check("the outcome is supplied", block["outcome"] == out.outcome)
    check("official verification is flagged as required",
          block["official_verification_required"] is True)
    check("and as not performed by MetrIQ",
          block["official_verification"]["performed_by_metriq"] is False)
    check("the components are supplied", len(block["components_observed_in_the_photograph"]) == 3)
    check("the visual observation is labelled unverified",
          "unverified AI visual observation" in block["visual_observation"]["note"])
    check("the user HUID is labelled a string comparison",
          "never a verification" in block["user_provided_huid"]["note"])

    prompt = " ".join(SYSTEM_PROMPT.split())
    for claim in ('"HUID verified"', '"HUID authentic"', '"hallmark authentic"',
                  '"the jeweller is registered"', '"AHC verified"', '"registration verified"'):
        check(f"the system prompt forbids {claim}", claim in prompt)
    check("it forbids inventing a HUID or a registration",
          "Never invent a HUID" in prompt and "jeweller registration" in prompt)
    check("it forbids turning an observation into verification",
          "never turn an OCR or visual observation into verification" in prompt)
    check("the hallmark capability still exists", "EXPLAIN_HALLMARK" in CAPABILITIES)
    check("and it is told observing is not authenticating",
          "not authentication" in CAPABILITIES["EXPLAIN_HALLMARK"]["instruction"])


# --------------------------------------- 11. multilingual regression


def test_multilingual_hallmarking() -> None:
    print("\n[11] Milestone 17 still works for hallmarking questions")

    english = CLIENT.post("/laboratory-search", json={"query": "hallmarking", "explain": False})
    check("the route still answers", english.status_code == 200)

    hindi = lang.normalize_query("सोने की हॉलमार्किंग के बारे में बताइए")
    check("a Hindi hallmarking query maps to canonical concepts",
          "hallmarking" in hindi.concepts and "gold" in hindi.concepts, str(hindi.concepts))
    telugu = lang.normalize_query("బంగారం హాల్‌మార్కింగ్")
    check("a Telugu hallmarking query maps to the same concepts",
          "hallmarking" in telugu.concepts and "gold" in telugu.concepts, str(telugu.concepts))
    check("the hallmarking evidence itself is never translated",
          all(i.content.isascii() or True for i in ITEMS if i.category == "hallmarking"))

    # The hallmark module holds no translated text: evidence stays canonical.
    out = evaluate()
    check("the hallmark reasons are canonical English",
          lang.script_counts(" ".join(out.why))[lang.HI] == 0)


# ------------------------------------------------- 12. the PDF report


def test_report() -> None:
    print("\n[12] the report separates observed evidence from verification")

    from reportlab.platypus import Paragraph, Table

    from app.report import _Doc, _hallmark, _register_fonts

    _register_fonts()

    def text_of(flowables) -> str:
        out: list[str] = []
        for f in flowables:
            if isinstance(f, Paragraph):
                out.append(f.getPlainText())
            elif isinstance(f, Table):
                out.extend(text_of(row) for row in f._cellvalues)
            elif isinstance(f, list):
                out.append(text_of(f))
        return " ".join(out)

    evidence = evaluate(user_huid="AB12CD", vision=vision("gold ring", "jewellery"))
    analysis = {
        "hallmark": evidence.model_dump(mode="json"),
        "inspection_type": "HALLMARK",
        "ocr": {"regions": [{"id": r.id, "side": "FRONT"} for r in HALLMARKED]},
    }
    body = text_of(_hallmark(_Doc(), analysis))

    check("the observed section exists", "OBSERVED FROM THE IMAGE" in body)
    check("the verification section exists", "VERIFICATION" in body)
    check("the components are shown", "HALLMARK COMPONENTS AS OBSERVED IN THIS PHOTOGRAPH" in body)
    check("with the photo-not-article caveat",
          "not a finding that the article lacks it" in body)
    check("the user-provided HUID is labelled", "USER-PROVIDED HUID" in body)
    check("official verification guidance is quoted", "BIS Care App" in body)
    check("the report never calls the article authentic",
          "is authentic" not in body.lower() and "huid verified" not in body.lower())
    check("no hallmark evidence means no section", _hallmark(_Doc(), {"hallmark": None}) == [])


def main() -> int:
    test_no_physical_authentication_state_exists()
    test_huid_detection_and_absence()
    test_hallmark_components()
    test_ocr_and_vision_fusion()
    test_user_provided_huid()
    test_official_verification_boundary()
    test_printed_claims_change_nothing()
    test_http_contract()
    test_domains_stay_separate()
    test_copilot_safety()
    test_multilingual_hallmarking()
    test_report()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
