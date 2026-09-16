"""End-to-end checks for the downstream pipeline (app/pipeline.py) and its wiring
into the inspection API.

Plain Python, no test framework. Run:

    cd backend
    ./.venv/bin/python tests/test_pipeline.py

The chana path is exercised with hand-built OCR regions (deterministic, no model,
no OCR engine). One check drives the real ASGI app with a synthesised label
image and only asserts the pipeline runs and never fabricates.
"""

from __future__ import annotations

import io
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.main import app  # noqa: E402
from app.pipeline import run_downstream  # noqa: E402

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


@dataclass
class Region:
    id: str
    text: str
    confidence: float
    bbox: list


CHANA = [
    Region("OCR-001", "PRINCIPAL DISPLAY PANEL", 0.95, [10, 10, 300, 40]),
    Region("OCR-002", "ROASTED MASALA CHANA", 0.96, [10, 50, 320, 90]),
    Region("OCR-003", "(Roasted Bengal gram with spices)", 0.90, [10, 95, 340, 120]),
    Region("OCR-004", "Net Quantity: 200 g", 0.86, [10, 130, 240, 160]),
    Region("OCR-005", "M.R.P. Rs. 45.00 (inclusive of all taxes)", 0.84, [10, 165, 360, 195]),
    Region("OCR-006", "Packed by: SUNRISE FOODS PVT LTD", 0.80, [10, 200, 360, 230]),
    Region("OCR-007", "Plot 14, MIDC Industrial Area, Pune 411019, Maharashtra", 0.78, [10, 235, 420, 265]),
    Region("OCR-008", "Mfg Date: 03/2026", 0.82, [10, 270, 200, 300]),
    Region("OCR-009", "Batch No: SR2026-0342", 0.83, [10, 305, 240, 335]),
    Region("OCR-010", "Best Before: 9 months from date of packaging", 0.80, [10, 340, 380, 370]),
]


def test_chana_end_to_end_deterministic() -> None:
    res = run_downstream(CHANA, llm=None)

    check("declaration stage COMPLETED", res.declaration_stage.status == "COMPLETED",
          res.declaration_stage.status)
    check("product MATCHED", res.product.status == "MATCHED", res.product.reason)
    check("product name comes from the knowledge base",
          res.product.name == "Roasted Bengal Gram", str(res.product.name))
    check("matched standard is IS 18140:2023", res.product.standard_number == "IS 18140:2023")
    check("top candidate is the matched standard",
          res.product.candidates and res.product.candidates[0].standard_number == "IS 18140:2023")
    check("retrieval confidence is a retrieval level", res.product.confidence in {"high", "medium", "low"})

    st = res.stages
    check("stage summary: ocr COMPLETED", st.ocr == "COMPLETED")
    check("stage summary: declaration_extraction COMPLETED", st.declaration_extraction == "COMPLETED")
    check("stage summary: product_identification MATCHED", st.product_identification == "MATCHED")
    check("stage summary: standard_retrieval MATCHED", st.standard_retrieval == "MATCHED")
    check("stage summary: compliance REVIEW (IS 18140 is standard-only)", st.compliance == "REVIEW")
    check("compliance for chana is STANDARD_ONLY, no checks invented",
          res.compliance.coverage_status == "STANDARD_ONLY" and res.compliance.checks == [])
    check("stage summary: officer_review PENDING", st.officer_review == "PENDING")

    # evidence traceability: OCR region -> declaration -> product clue -> standard
    nq = next((d for d in res.declaration_stage.declarations if d.field == "net_quantity"), None)
    check("net_quantity declaration links back to its OCR region",
          nq is not None and nq.source_region_id == "OCR-004" and nq.bbox == [10, 130, 240, 160])
    desc = next((ev for ev in res.product.evidence if ev.clue.kind == "product_description"), None)
    check("product evidence keeps the declaration field and its OCR region",
          desc is not None and desc.clue.declaration_field == "product_description"
          and desc.clue.source_regions == ["OCR-003"])


class _BrokenFinder:
    def __init__(self):
        self.search_engine = self

    @property
    def items(self):
        raise RuntimeError("knowledge base unavailable")

    def find(self, *args, **kwargs):
        raise RuntimeError("knowledge base unavailable")


def test_one_failed_stage_does_not_crash_the_rest() -> None:
    # Not a product in the knowledge base, no model: declarations still parse,
    # product identification degrades to REVIEW and invents nothing.
    regions = [
        Region("OCR-001", "WIDGET PACK", 0.9, [0, 0, 1, 1]),
        Region("OCR-002", "Net Quantity: 12 pcs", 0.8, [0, 2, 1, 3]),
        Region("OCR-003", "M.R.P. Rs. 300", 0.8, [0, 4, 1, 5]),
        Region("OCR-004", "Packed by: ACME WIDGETS PVT LTD", 0.8, [0, 6, 1, 7]),
    ]
    res = run_downstream(regions, llm=None)
    check("declarations still parsed", res.declaration_stage.status in {"COMPLETED", "PARTIAL"},
          res.declaration_stage.status)
    check("unknown product -> REVIEW", res.product.status == "REVIEW")
    check("REVIEW -> no product or standard invented",
          res.product.name is None and res.product.standard_number is None and res.product.candidates == [])

    broken = run_downstream(CHANA, llm=None, finder=_BrokenFinder())
    check("retrieval failure -> product REVIEW with reason",
          broken.product.status == "REVIEW" and "knowledge base unavailable" in broken.product.reason)
    check("retrieval failure -> declarations still returned",
          broken.declaration_stage.status == "COMPLETED")


def test_no_regions_all_review() -> None:
    res = run_downstream([], llm=None)
    check("no regions -> declaration NO_RELIABLE_TEXT",
          res.declaration_stage.status == "NO_RELIABLE_TEXT")
    check("no regions -> product REVIEW", res.product.status == "REVIEW")
    check("no regions -> no standard candidates", res.product.candidates == [])


def _chana_label_png() -> bytes:
    img = Image.new("RGB", (760, 520), "#ece8dc")
    d = ImageDraw.Draw(img)
    lines = [
        "PRINCIPAL DISPLAY PANEL",
        "ROASTED BENGAL GRAM",
        "Net Quantity: 200 g",
        "M.R.P. Rs. 45.00",
        "Packed by: SUNRISE FOODS PVT LTD",
        "Batch No: SR2026-0342",
    ]
    y = 30
    for ln in lines:
        d.text((30, y), ln, fill="black")
        d.text((31, y), ln, fill="black")
        y += 70
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_http_contract_runs_pipeline() -> None:
    client = TestClient(app)
    resp = client.post(
        "/inspection/analyze",
        files={"image": ("chana.png", _chana_label_png(), "image/png")},
    )
    check("POST /inspection/analyze -> 200", resp.status_code == 200, resp.text[:200])
    body = resp.json()
    for key in ("declaration_stage", "product", "standards", "retrieval_note", "pipeline"):
        check(f"response has '{key}'", key in body)
    check("old Phase 14 keys are gone",
          "classification" not in body and "standard_match" not in body)
    check("pipeline.ocr COMPLETED", body["pipeline"]["ocr"] == "COMPLETED")
    check("declaration_extraction is a known state",
          body["pipeline"]["declaration_extraction"] in {"COMPLETED", "PARTIAL", "REVIEW", "NO_RELIABLE_TEXT"})
    check("standard_retrieval is a known state",
          body["pipeline"]["standard_retrieval"] in {"MATCHED", "REVIEW"})
    check("retrieval note says it is not a compliance decision",
          "not a compliance" in body["retrieval_note"])
    # never fabricated
    product = body["product"]
    if product["status"] == "REVIEW":
        check("REVIEW product carries no name or standard",
              product["name"] is None and product["standard_number"] is None)
    else:
        check("MATCHED product's standard is the top verified candidate",
              body["standards"] and body["standards"][0]["standard_number"] == product["standard_number"]
              and body["standards"][0]["verification_status"] == "verified")
    for cand in body["standards"]:
        check(f"{cand['standard_number']} keeps why + reasons + source",
              cand["why"]["summary"] and cand["reasons"] and cand["source_url"])
    fields = body["declaration_stage"]["fields"]
    check("declarations with evidence keep their source regions",
          all(d["source_regions"] and d["source_region_id"] == d["source_regions"][0]
              for d in fields if d["status"] != "NOT_DETECTED"))
    check("NOT_DETECTED fields carry no value or evidence",
          all(d["value"] is None and d["source_regions"] == []
              for d in fields if d["status"] == "NOT_DETECTED"))


def main() -> int:
    print("downstream pipeline")
    for fn in (
        test_chana_end_to_end_deterministic,
        test_one_failed_stage_does_not_crash_the_rest,
        test_no_regions_all_review,
        test_http_contract_runs_pipeline,
    ):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
