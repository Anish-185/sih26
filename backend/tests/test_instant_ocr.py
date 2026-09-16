"""Checks for Instant OCR (POST /inspection/ocr, InspectionAnalyzer.ocr).

Instant OCR is the raw evidence layer: IMAGE -> OCR -> regions, plus the
deterministic declarations read from those regions. It must not need the local
model, retrieval, product classification, standards or rules.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_instant_ocr.py

Exit 0 = all checks passed, 1 = something failed.

Most checks use a stand-in OCR engine so they are fast and exact. The
integration checks at the top run the real local engine on a synthesised label
and a real sample JPEG. No network, no paid service.
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

import app.inspection as inspection  # noqa: E402
import app.llm as llm  # noqa: E402
from app.inspection import MAX_BYTES, ImageError, InspectionAnalyzer  # noqa: E402
from app.inspection_api import get_ocr_analyzer  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import OcrError, RawRegion  # noqa: E402

PASS = 0
FAIL = 0

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "ocr-labels"
# Instant OCR may carry deterministic declarations, but never these:
DOWNSTREAM_KEYS = {"classification", "standard_match", "pipeline"}


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def _png(size=(720, 480), lines: list[str] | None = None) -> bytes:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    y = 40
    for line in lines or []:
        draw.text((40, y), line, fill="black")
        draw.text((41, y), line, fill="black")
        y += 90
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _stub_engine(regions: list[RawRegion]):
    calls: list[tuple[int, int]] = []

    def engine(arr):
        calls.append((arr.shape[1], arr.shape[0]))  # (w, h) the engine saw
        return list(regions), 0.012

    engine.calls = calls
    return engine


def _raising_engine(exc: Exception):
    def engine(arr):
        raise exc

    return engine


CLIENT = TestClient(app)


# --------------------------------------------------------------------------
# Integration — the real local engine
# --------------------------------------------------------------------------

def test_real_engine_http() -> None:
    data = _png(lines=["NET QUANTITY 1000 ml", "MRP Rs 999", "BATCH AP26001"])
    resp = CLIENT.post("/inspection/ocr", files={"image": ("label.png", data, "image/png")})
    check("POST /inspection/ocr -> 200", resp.status_code == 200, resp.text[:200])
    body = resp.json()

    check("status COMPLETED", body["status"] == "COMPLETED", body.get("status"))
    check("no downstream fields in Instant OCR",
          not (DOWNSTREAM_KEYS & body.keys()), str(body.keys()))
    check("image dimensions echoed",
          body["image"]["width"] == 720 and body["image"]["height"] == 480)
    check("image_id present", body["image"]["image_id"].startswith("IMG-"))

    ocr = body["ocr"]
    check("found several regions", ocr["region_count"] >= 2, str(ocr["region_count"]))
    check("region_count matches list", ocr["region_count"] == len(ocr["regions"]))
    check("raw text is the joined region text",
          ocr["text"] == "\n".join(r["text"] for r in ocr["regions"]))
    check("recognised '1000'", "1000" in ocr["text"], ocr["text"])
    check("recognised '999'", "999" in ocr["text"], ocr["text"])
    check("mean confidence in (0,1]", 0.0 < ocr["mean_confidence"] <= 1.0)
    check("engine recorded", "PP-OCR" in ocr["engine"])

    ids = [r["id"] for r in ocr["regions"]]
    check("region ids unique", len(ids) == len(set(ids)))
    for r in ocr["regions"]:
        x1, y1, x2, y2 = r["bbox"]
        check(f"{r['id']} carries image_id", r["image_id"] == body["image"]["image_id"])
        check(f"{r['id']} bbox ordered and in-bounds",
              0 <= x1 < x2 <= 720 and 0 <= y1 < y2 <= 480, str(r["bbox"]))
        check(f"{r['id']} confidence in [0,1]", 0.0 <= r["confidence"] <= 1.0)
        check(f"{r['id']} text non-empty", r["text"].strip() != "")

    # Same bytes -> same image_id and same regions, in both endpoints.
    again = CLIENT.post("/inspection/ocr", files={"image": ("x.png", data, "image/png")}).json()
    check("image_id stable for same bytes",
          again["image"]["image_id"] == body["image"]["image_id"])
    check("region ids + text stable across runs",
          [(r["id"], r["text"]) for r in again["ocr"]["regions"]]
          == [(r["id"], r["text"]) for r in ocr["regions"]])
    analyzed = CLIENT.post(
        "/inspection/analyze", files={"image": ("label.png", data, "image/png")}
    ).json()
    check("/analyze reuses the same image_id",
          analyzed["image"]["image_id"] == body["image"]["image_id"])
    check("/analyze reuses the same OCR regions",
          analyzed["ocr"]["regions"] == ocr["regions"])


def test_real_sample_jpeg() -> None:
    path = SAMPLES / "synth_photo-angled.jpg"
    if not path.exists():
        check("sample JPEG present", False, str(path))
        return
    resp = CLIENT.post(
        "/inspection/ocr", files={"image": (path.name, path.read_bytes(), "image/jpeg")}
    )
    check("sample JPEG -> 200", resp.status_code == 200, resp.text[:200])
    body = resp.json()
    check("sample JPEG format", body["image"]["format"] == "JPEG")
    check("sample JPEG has regions", body["ocr"]["region_count"] >= 5,
          str(body["ocr"]["region_count"]))
    check("sample JPEG text mentions the product",
          "chana" in body["ocr"]["text"].lower(), body["ocr"]["text"][:200])


# --------------------------------------------------------------------------
# Stubbed engine — exact, fast
# --------------------------------------------------------------------------

def test_passthrough_no_fabrication() -> None:
    raw = [
        RawRegion("AQUA PURE", 0.97, (10, 10, 200, 40), [[10, 10], [200, 10], [200, 40], [10, 40]]),
        RawRegion("MRP ₹20", 0.912345, (10, 60, 120, 90), [[10, 60], [120, 60], [120, 90], [10, 90]]),
    ]
    result = InspectionAnalyzer(ocr_engine=_stub_engine(raw)).ocr(_png(), "w.png")

    check("stub: status COMPLETED", result.status == "COMPLETED")
    check("stub: exactly the engine's regions",
          [r.text for r in result.ocr.regions] == ["AQUA PURE", "MRP ₹20"])
    check("stub: text is not rewritten", result.ocr.text == "AQUA PURE\nMRP ₹20")
    check("stub: ids in order", [r.id for r in result.ocr.regions] == ["OCR-001", "OCR-002"])
    check("stub: bbox preserved", result.ocr.regions[0].bbox == [10, 10, 200, 40])
    check("stub: polygon preserved", len(result.ocr.regions[0].polygon) == 4)
    check("stub: confidence rounded to 4dp", result.ocr.regions[1].confidence == 0.9123)
    check("stub: mean confidence", result.ocr.mean_confidence == round((0.97 + 0.9123) / 2, 4))
    check("stub: duration from engine", result.ocr.duration_ms == 12)

    fields = {f.field: f for f in result.declaration_stage.fields}
    mrp = fields["mrp"]
    check("stub: MRP declaration read from OCR", mrp.status == "DETECTED" and mrp.value == "₹20",
          f"{mrp.status} {mrp.value}")
    check("stub: MRP linked to its OCR region", mrp.source_regions == ["OCR-002"])
    check("stub: MRP keeps the region's image_id", mrp.image_id == result.image.image_id)
    check("stub: MRP carries the region's OCR confidence", mrp.ocr_confidence == 0.9123)
    check("stub: no value outside the OCR text is invented",
          all(f.value is None or f.raw_text for f in result.declaration_stage.fields))


def test_declaration_failure_keeps_ocr() -> None:
    original = inspection.extract_declarations

    def broken(regions):
        raise RuntimeError("extractor bug")

    inspection.extract_declarations = broken
    try:
        raw = [RawRegion("MRP ₹20", 0.9, (10, 10, 120, 40), [[10, 10], [120, 10], [120, 40], [10, 40]])]
        result = InspectionAnalyzer(ocr_engine=_stub_engine(raw)).ocr(_png(), "w.png")
    finally:
        inspection.extract_declarations = original
    check("extractor failure: OCR still returned", result.ocr.text == "MRP ₹20")
    check("extractor failure: stage REVIEW, no fields",
          result.declaration_stage.status == "REVIEW" and result.declaration_stage.fields == [])
    check("extractor failure: noted", any("extractor bug" in n for n in result.notes))


def test_large_image_boxes_mapped_back() -> None:
    # 4000px long side -> engine sees 2000px (scale 0.5); boxes must come back
    # in source pixels so the overlay lines up with the original image.
    raw = [RawRegion("NET QTY 1 L", 0.9, (100, 50, 300, 80),
                     [[100, 50], [300, 50], [300, 80], [100, 80]])]
    engine = _stub_engine(raw)
    result = InspectionAnalyzer(ocr_engine=engine).ocr(_png(size=(4000, 1000)), "big.png")
    check("large: engine saw downscaled image", engine.calls == [(2000, 500)], str(engine.calls))
    check("large: bbox scaled to source px",
          result.ocr.regions[0].bbox == [200, 100, 600, 160], str(result.ocr.regions[0].bbox))
    check("large: polygon scaled to source px",
          result.ocr.regions[0].polygon[1] == [600, 100])
    check("large: reported size is the original", (result.image.width, result.image.height) == (4000, 1000))


def test_no_text_is_honest() -> None:
    result = InspectionAnalyzer(ocr_engine=_stub_engine([])).ocr(_png(), "blank.png")
    check("empty: status NO_TEXT", result.status == "NO_TEXT")
    check("empty: zero regions", result.ocr.region_count == 0 and result.ocr.regions == [])
    check("empty: empty text", result.ocr.text == "")
    check("empty: mean confidence 0", result.ocr.mean_confidence == 0.0)
    check("empty: explanatory note",
          any("no legible text" in n.lower() for n in result.notes))
    check("empty: declarations NO_RELIABLE_TEXT",
          result.declaration_stage.status == "NO_RELIABLE_TEXT")
    check("empty: every field NOT_DETECTED, nothing invented",
          all(f.status == "NOT_DETECTED" and f.value is None
              for f in result.declaration_stage.fields))


def test_engine_failure() -> None:
    try:
        InspectionAnalyzer(ocr_engine=_raising_engine(OcrError("engine crashed"))).ocr(_png(), "a.png")
        check("OcrError propagates", False, "no error raised")
    except OcrError as exc:
        check("OcrError propagates", "engine crashed" in str(exc))

    try:
        InspectionAnalyzer(ocr_engine=_raising_engine(ValueError("boom"))).ocr(_png(), "a.png")
        check("unexpected engine error -> OcrError", False, "no error raised")
    except OcrError as exc:
        check("unexpected engine error -> OcrError", "boom" in str(exc))

    app.dependency_overrides[get_ocr_analyzer] = lambda: InspectionAnalyzer(
        ocr_engine=_raising_engine(OcrError("engine crashed"))
    )
    try:
        resp = CLIENT.post("/inspection/ocr", files={"image": ("a.png", _png(), "image/png")})
    finally:
        app.dependency_overrides.clear()
    check("HTTP: engine failure -> 503", resp.status_code == 503, str(resp.status_code))
    check("HTTP: failure detail is clear", "OCR unavailable" in resp.json().get("detail", ""))
    check("HTTP: no regions returned on failure", "ocr" not in resp.json())


def test_independent_of_model_and_pipeline() -> None:
    """Instant OCR must work with the LLM and downstream pipeline unusable."""
    original_downstream = inspection.run_downstream
    original_init = llm.LocalLLM.__init__

    def forbidden(*args, **kwargs):
        raise AssertionError("Instant OCR must not touch this")

    inspection.run_downstream = forbidden
    llm.LocalLLM.__init__ = forbidden
    raw = [RawRegion("BATCH AP26001", 0.95, (5, 5, 150, 30), [[5, 5], [150, 5], [150, 30], [5, 30]])]
    app.dependency_overrides[get_ocr_analyzer] = lambda: InspectionAnalyzer(
        ocr_engine=_stub_engine(raw)
    )
    try:
        resp = CLIENT.post("/inspection/ocr", files={"image": ("a.png", _png(), "image/png")})
        get_ocr_analyzer.cache_clear()
        real_dep = get_ocr_analyzer()  # the production factory, with LocalLLM unusable
    finally:
        inspection.run_downstream = original_downstream
        llm.LocalLLM.__init__ = original_init
        app.dependency_overrides.clear()
        get_ocr_analyzer.cache_clear()

    check("works with model + pipeline disabled", resp.status_code == 200, resp.text[:200])
    check("returns the OCR text", resp.json()["ocr"]["text"] == "BATCH AP26001")
    check("production OCR analyzer builds without the model", real_dep._llm is None)


# --------------------------------------------------------------------------
# Upload validation
# --------------------------------------------------------------------------

def test_upload_validation() -> None:
    analyzer = InspectionAnalyzer(ocr_engine=_raising_engine(AssertionError("should not run")))
    for name, data in (("empty bytes", b""), ("non-image bytes", b"not an image at all")):
        try:
            analyzer.ocr(data, "x.png")
            check(f"{name} -> ImageError", False, "no error raised")
        except ImageError:
            check(f"{name} -> ImageError", True)

    tiny = _png(size=(20, 20))
    try:
        analyzer.ocr(tiny, "tiny.png")
        check("tiny image -> ImageError", False)
    except ImageError:
        check("tiny image -> ImageError", True)

    def post(files=None):
        return CLIENT.post("/inspection/ocr", files=files)

    r = post({"image": ("empty.png", b"", "image/png")})
    check("HTTP empty upload -> 422", r.status_code == 422, str(r.status_code))
    r = post({"image": ("fake.png", b"garbage bytes", "image/png")})
    check("HTTP malformed image -> 422", r.status_code == 422, str(r.status_code))
    check("HTTP malformed detail is readable", "image" in r.json()["detail"].lower())
    r = post({"image": ("note.txt", b"hello", "text/plain")})
    check("HTTP non-image content type -> 415", r.status_code == 415, str(r.status_code))
    r = post({"image": ("huge.jpg", b"\xff" * (MAX_BYTES + 1), "image/jpeg")})
    check("HTTP oversize -> 413", r.status_code == 413, str(r.status_code))
    r = post({"image": ("tiny.png", tiny, "image/png")})
    check("HTTP tiny image -> 422", r.status_code == 422, str(r.status_code))
    r = CLIENT.post("/inspection/ocr")
    check("HTTP missing file -> 422", r.status_code == 422, str(r.status_code))


def main() -> int:
    print("instant OCR (/inspection/ocr)")
    for fn in (
        test_real_engine_http,
        test_real_sample_jpeg,
        test_passthrough_no_fabrication,
        test_large_image_boxes_mapped_back,
        test_declaration_failure_keeps_ocr,
        test_no_text_is_honest,
        test_engine_failure,
        test_independent_of_model_and_pipeline,
        test_upload_validation,
    ):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
