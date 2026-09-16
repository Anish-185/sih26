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
    text = "\n".join(r.text for r in CHANA)
    res = run_downstream(CHANA, text, llm=None)

    check("declaration stage COMPLETED", res.declaration_stage.status == "COMPLETED",
          res.declaration_stage.status)
    check("classification CLASSIFIED", res.classification.status == "CLASSIFIED")
    check("normalized product is Roasted Bengal Gram",
          res.classification.normalized_product == "Roasted Bengal Gram")
    check("standard MATCHED", res.standard_match.status == "MATCHED", res.standard_match.status)
    check("matched standard is IS 18140:2023",
          res.standard_match.standard is not None
          and res.standard_match.standard.standard_number == "IS 18140:2023")
    check("standard confidence is a real score",
          0.0 < res.standard_match.confidence <= 1.0, str(res.standard_match.confidence))

    st = res.stages
    check("stage summary: ocr COMPLETED", st.ocr == "COMPLETED")
    check("stage summary: declaration_extraction COMPLETED", st.declaration_extraction == "COMPLETED")
    check("stage summary: product_classification CLASSIFIED", st.product_classification == "CLASSIFIED")
    check("stage summary: standard_lookup MATCHED", st.standard_lookup == "MATCHED")
    check("stage summary: legal_metrology NEXT", st.legal_metrology == "NEXT")
    check("stage summary: officer_review PENDING", st.officer_review == "PENDING")

    # evidence traceability: image -> ocr region -> declaration
    nq = next((d for d in res.declaration_stage.declarations if d.field == "net_quantity"), None)
    check("net_quantity declaration links back to its OCR region",
          nq is not None and nq.source_region_id == "OCR-004" and nq.bbox == [10, 130, 240, 160])


def test_one_failed_stage_does_not_crash_the_rest() -> None:
    # OCR text present but not a classifiable product and no model available:
    # declarations still parse, classification + standard degrade to REVIEW.
    regions = [
        Region("OCR-001", "WIDGET PACK", 0.9, [0, 0, 1, 1]),
        Region("OCR-002", "Net Quantity: 12 pcs", 0.8, [0, 2, 1, 3]),
        Region("OCR-003", "M.R.P. Rs. 300", 0.8, [0, 4, 1, 5]),
        Region("OCR-004", "Packed by: ACME WIDGETS PVT LTD", 0.8, [0, 6, 1, 7]),
    ]
    res = run_downstream(regions, "\n".join(r.text for r in regions), llm=None)
    check("declarations still parsed", res.declaration_stage.status in {"COMPLETED", "PARTIAL"},
          res.declaration_stage.status)
    check("classification REVIEW (no rule, no model)", res.classification.status == "REVIEW")
    check("standard REVIEW", res.standard_match.status == "REVIEW")
    check("standard REVIEW -> no standard invented", res.standard_match.standard is None)


def test_no_regions_all_review() -> None:
    res = run_downstream([], "", llm=None)
    check("no regions -> declaration NO_RELIABLE_TEXT",
          res.declaration_stage.status == "NO_RELIABLE_TEXT")
    check("no regions -> classification REVIEW", res.classification.status == "REVIEW")
    check("no regions -> standard REVIEW", res.standard_match.status == "REVIEW")


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
    for key in ("declaration_stage", "classification", "standard_match", "pipeline"):
        check(f"response has '{key}'", key in body)
    check("pipeline.ocr COMPLETED", body["pipeline"]["ocr"] == "COMPLETED")
    check("declaration_extraction is a known state",
          body["pipeline"]["declaration_extraction"] in {"COMPLETED", "PARTIAL", "REVIEW", "NO_RELIABLE_TEXT"})
    check("standard_lookup is a known state",
          body["pipeline"]["standard_lookup"] in {"MATCHED", "REVIEW"})
    # never fabricated
    sm = body["standard_match"]
    if sm["status"] == "REVIEW":
        check("REVIEW standard_match carries no standard", sm["standard"] is None)
    else:
        check("MATCHED standard_match carries a verified BIS standard",
              sm["standard"] and sm["standard"]["source"] == "BIS"
              and sm["standard"]["number"].startswith("IS "))
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
