"""HTTP contract checks for the FastAPI app (backend/app/main.py).

Plain Python, no test framework (matches tests/test_retrieval.py). Run with:

    cd backend
    ./.venv/bin/python tests/test_api_contract.py

Exit code 0 = all checks passed, 1 = something failed.

Every other suite calls the route functions or services directly. This one
drives the real ASGI app through fastapi.testclient.TestClient, so it catches
route-wiring regressions, response-model drift, and HTTP status-code behaviour
(200 / 422 / 404 / 503). The grounded endpoints are exercised with a fake local
model so no LM Studio is required; the deterministic endpoints hit the real
verified knowledge base. No fake BIS facts are introduced.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

warnings.filterwarnings("ignore")  # silence the starlette/httpx TestClient notice

from fastapi.testclient import TestClient  # noqa: E402

from app import api as api_module  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.main import app  # noqa: E402
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
        return "GROUNDED ANSWER (fake LLM)."


class RaisingLLM:
    def generate(self, *, system_prompt: str, user_prompt: str,
                 temperature: float = 0.1) -> str:
        raise LLMError("LM Studio request failed: simulated outage")


CLIENT = TestClient(app)
ENGINE = SearchEngine()

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge"
KB_STANDARD_NUMBERS = {
    " ".join(r["standard_number"].split()).upper()
    for path in DATA_DIR.glob("*.json")
    for r in json.load(open(path))
    if r.get("standard_number")
}


# ------------------------------------------------------------------- /health

def test_health() -> None:
    r = CLIENT.get("/health")
    check("/health: 200", r.status_code == 200)
    body = r.json()
    check("/health: reports ok", body.get("status") == "ok")
    check("/health: names the service and a version",
          bool(body.get("service")) and bool(body.get("version")))


# ------------------------------------------------------------------- /search

def test_search_contract() -> None:
    r = CLIENT.get("/search", params={"q": "what is HUID", "limit": 3})
    check("GET /search: 200", r.status_code == 200)
    body = r.json()
    for key in ("query", "normalized_query", "query_terms", "confidence",
                "abstained", "count", "results"):
        check(f"GET /search: response has '{key}'", key in body)
    check("GET /search: at most `limit` results", len(body["results"]) <= 3)
    check("GET /search: not abstained for a real query", body["abstained"] is False)
    if body["results"]:
        first = body["results"][0]
        for key in ("id", "title", "category", "score", "confidence",
                    "matched_terms", "reasons", "verification_status"):
            check(f"GET /search result has '{key}'", key in first)

    r2 = CLIENT.post("/search", json={"query": "IS 1786:2008", "limit": 2})
    check("POST /search: 200", r2.status_code == 200)
    check("POST /search: standard-number query returns a result",
          r2.json()["count"] >= 1)

    r3 = CLIENT.get("/search", params={"q": ""})
    check("GET /search empty: 200 and abstained",
          r3.status_code == 200 and r3.json()["abstained"] is True)

    r4 = CLIENT.post("/search", json={"query": "zzzzz qqqqq vvvvv"})
    check("POST /search junk: abstained, empty results",
          r4.status_code == 200 and r4.json()["abstained"] is True
          and r4.json()["results"] == [])

    r5 = CLIENT.get("/search", params={"q": "cement", "limit": 999})
    check("GET /search: limit above the cap is rejected (422)",
          r5.status_code == 422)


# ---------------------------------------------------------- /product-standard

def test_product_standard_contract() -> None:
    r = CLIENT.post("/product-standard", json={"product": "LED lamp"})
    check("POST /product-standard: 200", r.status_code == 200)
    body = r.json()
    for key in ("product", "results", "grounded", "confidence", "note"):
        check(f"/product-standard: response has '{key}'", key in body)
    check("/product-standard: LED lamp is grounded", body["grounded"] is True)
    top = body["results"][0]
    check("/product-standard: result carries a 'why' block", "why" in top)
    for key in ("standard_number", "strength", "signals", "summary"):
        check(f"/product-standard why has '{key}'", key in top["why"])
    check("/product-standard: raw 'reasons' still present alongside 'why'",
          bool(top.get("reasons")))
    check("/product-standard: why.standard_number matches the result",
          top["why"]["standard_number"] == top["standard_number"])

    # limit bounds (contract: ge=1, le=50)
    check("/product-standard: limit 0 -> 422",
          CLIENT.post("/product-standard",
                      json={"product": "LED lamp", "limit": 0}).status_code == 422)
    check("/product-standard: limit 51 -> 422",
          CLIENT.post("/product-standard",
                      json={"product": "LED lamp", "limit": 51}).status_code == 422)

    # empty / missing product -> 200, not grounded (never a 500)
    for payload in ({}, {"product": ""}, {"product": "   "}):
        rr = CLIENT.post("/product-standard", json=payload)
        check(f"/product-standard {payload}: 200 and not grounded",
              rr.status_code == 200 and rr.json()["grounded"] is False)

    # malformed body
    check("/product-standard: malformed JSON -> 422",
          CLIENT.post("/product-standard", content="{ not json",
                      headers={"content-type": "application/json"}).status_code == 422)


def test_product_standard_never_invents_a_standard_number() -> None:
    # Adversarial sweep: whatever comes back, every standard number must be real.
    queries = [
        "stainless steel water bottle", "LED lamp", "electric iron",
        "packaged drinking water", "cement", "gold jewellery hallmark",
        "microwave oven", "laptop charger", "car tyre", "feeding bottle",
        "quantum flux capacitor", "plastic garden chair", "wooden toy",
        "artisanal cheese", "IS 99999 mystery product",
    ]
    for q in queries:
        body = CLIENT.post("/product-standard", json={"product": q}).json()
        for result in body["results"]:
            key = " ".join(result["standard_number"].split()).upper()
            check(f"{q!r}: returned standard {result['standard_number']} exists in the KB",
                  key in KB_STANDARD_NUMBERS)
        if not body["results"]:
            check(f"{q!r}: no evidence -> not grounded, empty results",
                  body["grounded"] is False)


# ------------------------------------------------------------ /ask (grounded)

def _swap_answerer(llm) -> object:
    original = api_module.get_answerer
    api_module.get_answerer = lambda: BISQuestionAnswerer(
        search_engine=ENGINE, llm=llm
    )
    return original


def test_ask_contract() -> None:
    # empty question needs no model
    r0 = CLIENT.post("/ask", json={"question": ""})
    check("/ask empty: 200, not grounded, no sources",
          r0.status_code == 200 and r0.json()["grounded"] is False
          and r0.json()["sources"] == [])
    check("/ask: missing 'question' key still 200 (defaults to empty)",
          CLIENT.post("/ask", json={}).status_code == 200)

    original = _swap_answerer(FakeLLM())
    try:
        r = CLIENT.post("/ask", json={"question": "What is HUID?"})
        check("/ask grounded: 200", r.status_code == 200)
        body = r.json()
        for key in ("question", "answer", "grounded", "source_count", "sources"):
            check(f"/ask: response has '{key}'", key in body)
        check("/ask grounded: grounded True with sources",
              body["grounded"] is True and body["source_count"] >= 1)
        check("/ask grounded: source_count matches sources length",
              body["source_count"] == len(body["sources"]))
        src = body["sources"][0]
        for key in ("id", "title", "category", "verification_status",
                    "source_organization"):
            check(f"/ask source has '{key}'", key in src)

        rj = CLIENT.post("/ask", json={"question": "zzzz qqqq vvvv nonsense"})
        check("/ask junk: 200, not grounded, no sources",
              rj.status_code == 200 and rj.json()["grounded"] is False
              and rj.json()["sources"] == [])
    finally:
        api_module.get_answerer = original


def test_ask_returns_503_on_model_outage() -> None:
    original = _swap_answerer(RaisingLLM())
    try:
        r = CLIENT.post("/ask", json={"question": "What is HUID?"})
        check("/ask during outage: 503", r.status_code == 503)
        check("/ask during outage: detail is a clean, provider-neutral message",
              "Explanation service unavailable" in r.json().get("detail", ""))
        # an abstaining question never reaches the model -> still 200
        r2 = CLIENT.post("/ask", json={"question": "zzzz qqqq vvvv nonsense"})
        check("/ask abstention survives an outage: 200, not grounded",
              r2.status_code == 200 and r2.json()["grounded"] is False)
    finally:
        api_module.get_answerer = original


# --------------------------------------- /certification-guidance, /laboratory-search

def test_grounded_surface_empty_input_contracts() -> None:
    r = CLIENT.post("/certification-guidance", json={"question": ""})
    check("/certification-guidance empty: 200, not grounded, note set",
          r.status_code == 200 and r.json()["grounded"] is False
          and r.json()["note"] == "empty question")
    check("/certification-guidance: missing key -> still 200",
          CLIENT.post("/certification-guidance", json={}).status_code == 200)

    r2 = CLIENT.post("/laboratory-search", json={"query": ""})
    check("/laboratory-search empty: 200, not grounded",
          r2.status_code == 200 and r2.json()["grounded"] is False
          and r2.json()["note"] == "empty query")

    # explain=false is fully deterministic — no model, no monkeypatch needed.
    r3 = CLIENT.post("/laboratory-search",
                     json={"query": "BIS recognised laboratory for testing steel",
                           "explain": False})
    check("/laboratory-search explain=false: 200 and grounded",
          r3.status_code == 200 and r3.json()["grounded"] is True)
    check("/laboratory-search: note points to the official LIMS portal",
          "lims" in r3.json()["note"].lower())
    r4 = CLIENT.post("/laboratory-search",
                     json={"query": "zzz qqq vvv", "explain": False})
    check("/laboratory-search junk explain=false: 200, not grounded, no sources",
          r4.status_code == 200 and r4.json()["grounded"] is False
          and r4.json()["sources"] == [])


# ------------------------------------------------------------------- routing

def test_routing() -> None:
    check("unknown route -> 404", CLIENT.get("/does-not-exist").status_code == 404)
    check("wrong method on /ask -> 405",
          CLIENT.get("/ask").status_code == 405)
    paths = set(CLIENT.get("/openapi.json").json()["paths"])
    for p in ("/health", "/search", "/ask", "/product-standard",
              "/certification-guidance", "/laboratory-search"):
        check(f"openapi advertises {p}", p in paths)


def main() -> int:
    test_health()
    test_search_contract()
    test_product_standard_contract()
    test_product_standard_never_invents_a_standard_number()
    test_ask_contract()
    test_ask_returns_503_on_model_outage()
    test_grounded_surface_empty_input_contracts()
    test_routing()

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
