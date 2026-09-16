"""Checks for the inspection OCR pipeline (app/ocr.py, app/inspection.py,
app/inspection_api.py).

Plain Python, no test framework (matches tests/test_api_contract.py). Run:

    cd backend
    ./.venv/bin/python tests/test_inspection_ocr.py

Exit 0 = all checks passed, 1 = something failed.

These run the real local OCR engine on synthesised label images, so the first
run loads the ONNX models (a few hundred ms). No network, no paid service.
"""

from __future__ import annotations

import io
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.inspection import InspectionAnalyzer, ImageError  # noqa: E402
from app.main import app  # noqa: E402

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


def _label_png(lines: list[str], size=(720, 480)) -> bytes:
    """A high-contrast synthetic label — big black text on white."""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        draw.text((40, y), line, fill="black")
        # draw again offset by 1px to fake a bolder stroke for the tiny font
        draw.text((41, y), line, fill="black")
        y += 90
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


ANALYZER = InspectionAnalyzer()
CLIENT = TestClient(app)


def test_multi_region_ocr() -> None:
    data = _label_png(
        ["NET QUANTITY 1000 ml", "MRP Rs 999", "ABC INDUSTRIES PVT LTD"]
    )
    result = ANALYZER.analyze(data, "label.png")

    check("image dimensions echoed", result.image.width == 720 and result.image.height == 480)
    check("image format is PNG", result.image.format == "PNG")
    check("quality metrics present", result.quality.brightness > 0 and result.quality.contrast > 0)
    check("ocr engine recorded", "PP-OCR" in result.ocr.engine or "ONNX" in result.ocr.engine)
    check(
        "found multiple regions",
        result.ocr.region_count >= 2,
        f"got {result.ocr.region_count}",
    )
    check("region_count matches list", result.ocr.region_count == len(result.ocr.regions))

    joined = result.ocr.text.lower()
    check("recognised '1000'", "1000" in joined, joined)
    check("recognised '999'", "999" in joined, joined)

    for reg in result.ocr.regions:
        x1, y1, x2, y2 = reg.bbox
        check(
            f"{reg.id} bbox is ordered and in-bounds",
            0 <= x1 < x2 <= result.image.width and 0 <= y1 < y2 <= result.image.height,
            str(reg.bbox),
        )
        check(f"{reg.id} confidence in [0,1]", 0.0 <= reg.confidence <= 1.0)
        check(f"{reg.id} id format", reg.id.startswith("OCR-"))
        check(f"{reg.id} polygon has 4 points", len(reg.polygon) == 4)
        check(f"{reg.id} text is non-empty", reg.text.strip() != "")

    check("mean_confidence sane", 0.0 < result.ocr.mean_confidence <= 1.0)
    check("duration recorded", result.ocr.duration_ms >= 0)


def test_no_text_returns_empty_not_fake() -> None:
    blank = Image.new("RGB", (400, 300), "white")
    buf = io.BytesIO()
    blank.save(buf, format="PNG")
    result = ANALYZER.analyze(buf.getvalue(), "blank.png")

    check("blank image -> zero regions", result.ocr.region_count == 0)
    check("blank image -> empty text", result.ocr.text == "")
    check("blank image -> mean_confidence 0", result.ocr.mean_confidence == 0.0)
    check(
        "blank image -> explanatory note, no invented data",
        any("no legible text" in n.lower() for n in result.notes),
    )
    # Phase 14: downstream stages must degrade to REVIEW, never fabricate.
    check("blank image -> declaration stage NO_RELIABLE_TEXT",
          result.declaration_stage.status == "NO_RELIABLE_TEXT")
    check("blank image -> no declarations invented",
          all(f.status == "NOT_DETECTED" and f.value is None
              for f in result.declaration_stage.fields))
    check("blank image -> product REVIEW", result.product.status == "REVIEW")
    check("blank image -> no product invented", result.product.name is None)
    check("blank image -> no standard candidates invented", result.standards == [])
    check("blank image -> pipeline summary present, ocr COMPLETED",
          result.pipeline.ocr == "COMPLETED"
          and result.pipeline.compliance == "REVIEW"
          and result.compliance.coverage_status == "NO_STANDARD")


def test_rejects_non_image_bytes() -> None:
    try:
        ANALYZER.analyze(b"this is definitely not an image", "note.txt")
        check("non-image bytes raise ImageError", False, "no error raised")
    except ImageError:
        check("non-image bytes raise ImageError", True)


def test_rejects_tiny_image() -> None:
    tiny = Image.new("RGB", (20, 20), "white")
    buf = io.BytesIO()
    tiny.save(buf, format="PNG")
    try:
        ANALYZER.analyze(buf.getvalue(), "tiny.png")
        check("tiny image raises ImageError", False)
    except ImageError:
        check("tiny image raises ImageError", True)


def test_http_contract() -> None:
    data = _label_png(["PACKED WATER 500 ml", "BATCH B42"])
    resp = CLIENT.post(
        "/inspection/analyze",
        files={"image": ("water.png", data, "image/png")},
    )
    check("POST /inspection/analyze -> 200", resp.status_code == 200, resp.text[:200])
    body = resp.json()
    check("response has inspection_id", isinstance(body.get("inspection_id"), str))
    check("response has ocr.regions list", isinstance(body["ocr"]["regions"], list))
    check("response has quality block", "blur_score" in body["quality"])
    check(
        "at least one region with a bbox of 4 ints",
        body["ocr"]["region_count"] == 0
        or (len(body["ocr"]["regions"][0]["bbox"]) == 4),
    )

    bad = CLIENT.post(
        "/inspection/analyze",
        files={"image": ("note.txt", b"hello world", "text/plain")},
    )
    check("non-image upload -> 4xx", 400 <= bad.status_code < 500, str(bad.status_code))

    missing = CLIENT.post("/inspection/analyze")
    check("missing file -> 422", missing.status_code == 422, str(missing.status_code))


def main() -> int:
    print("inspection OCR pipeline")
    for fn in (
        test_multi_region_ocr,
        test_no_text_returns_empty_not_fake,
        test_rejects_non_image_bytes,
        test_rejects_tiny_image,
        test_http_contract,
    ):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
