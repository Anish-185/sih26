"""Checks for Milestone 11 — evidence-backed inspection reports (PDF).

The report is an audit trail of a persisted inspection: it must show exactly what
is stored — the identified standard, verified requirement knowledge, what could
not be established, evidence, sources — never invent anything, and never change
the record. There is no human decision in it, and MetrIQ produces no automatic
PASS/FAIL/REVIEW compliance verdict, so the report contains none. Content is
checked on the report's flowables (``app.report.build_story``); rendering is
checked on real PDF bytes.

Needs PostgreSQL for the endpoint checks (TEST_DATABASE_URL, default the local
``metriq_test`` database, migrated to head here). No LM Studio / OpenRouter.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_report.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg:///metriq_test")
os.environ["DATABASE_URL"] = TEST_URL
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from reportlab.platypus import Image, KeepTogether, Paragraph, Table  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.escalation as escalation_module  # noqa: E402
import app.pipeline as pipeline_module  # noqa: E402
import app.records as records_module  # noqa: E402
import httpx  # noqa: E402
from app.api import get_product_finder  # noqa: E402
from app.db import get_engine, get_session  # noqa: E402
from app.escalation import assess  # noqa: E402
from app.inspection import InspectionAnalyzer, PackageUpload  # noqa: E402
from app.inspection_api import get_analyzer  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import RawRegion  # noqa: E402
from app.report import build_story, render_report  # noqa: E402

PASS = 0
FAIL = 0
BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
client = TestClient(app)


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


# ------------------------------------------------------------------ fixtures


def photo(width: int) -> bytes:
    arr = np.random.default_rng(width).integers(40, 215, (400, width, 3), dtype=np.uint8)
    buf = io.BytesIO()
    PILImage.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def raw(*texts, conf=0.95):
    out, y = [], 20
    for i, t in enumerate(texts):
        h = 50 if i == 0 else 25
        out.append(RawRegion(t, conf, (10, y, 10 + 10 * len(t), y + h),
                             [[10, y], [10 + 10 * len(t), y], [10 + 10 * len(t), y + h], [10, y + h]]))
        y += h + 15
    return out


class Engine:
    def __init__(self, by_width):
        self.by_width = by_width

    def __call__(self, arr):
        return list(self.by_width[arr.shape[1]]), 0.01


# One INSPECTION_SUPPORTED standard (IS 14543:2016 — packaged water) so requirement
# knowledge, sources and a fully-established case are all exercisable; a kettle
# label (STANDARD_ONLY — plenty of standard-level detail, but no modelled
# requirement data) for the general identification/injection/escaping checks;
# and a blank label for the "nothing established" path.
WATER = ["PACKAGED DRINKING WATER", "Product name: Packaged Drinking Water", "IS 14543:2016",
         "MRP ₹20.00 (Inclusive of all taxes)", "Net Quantity: 1 L", "Packed on: 03/2026",
         "Manufactured by: Blue Spring Beverages Pvt Ltd",
         "Address: Plot 9, Hosur Industrial Area, Krishnagiri 635109, Tamil Nadu",
         "Consumer care: 1800-200-4455", "Email: care@bluespring.example"]
KETTLE = ["ELECTRIC KETTLE", "Product name: Electric Kettle", "MRP ₹899.00 (Inclusive of all taxes)",
          "Net Quantity: 1 N", "Mfg. Date: 02/2026", "Manufactured by: Thermopot Appliances Pvt Ltd",
          "Address: Plot 12, Baddi Industrial Area, Solan 173205, Himachal Pradesh",
          "Consumer care: 1800-300-7788", "Email: care@thermopot.example"]
INJECTION = "<b>Brand</b><font size=40 color=red>X</font> & <para>"
W_WATER, W_KETTLE, W_FRONT, W_BACK, W_NOTHING = 960, 961, 962, 963, 964
STUB = InspectionAnalyzer(ocr_engine=Engine({
    W_WATER: raw(*WATER),
    W_KETTLE: raw(*KETTLE),
    W_FRONT: raw("ELECTRIC KETTLE", "Product name: Electric Kettle", INJECTION),
    W_BACK: raw("MRP ₹899.00 (Inclusive of all taxes)", "Net Quantity: 1 N"),
    W_NOTHING: raw("SUNSHINE", "Best quality since 1990"),
}), product_finder=get_product_finder())


def analysis(*sides) -> dict:
    out = STUB.analyze_package([PackageUpload(photo(w), f"{s.lower()}.png", s) for w, s in sides])
    return out.model_dump(mode="json")


def record(an: dict) -> dict:
    """A stored-record JSON (InspectionRecordOut shape) for an analysis, as the API would return it —
    mirrors app.records.create_inspection exactly (no compliance verdict is stored)."""
    esc = assess(an)
    matched = an["product"]["status"] == "MATCHED"
    return {
        "inspection_id": "INS-20260917-ABC123", "created_at": "2026-09-17T10:00:00+00:00",
        "product_status": an["product"]["status"], "product_name": an["product"]["name"] if matched else None,
        "product_category": an["product"].get("modelled_product_category"),
        "standard_number": an["product"]["standard_number"] if matched else None,
        "escalation_required": esc["required"], "escalation_reasons": esc["reasons"],
        "image_count": len(an["images"]), "sides": [i["side"] for i in an["images"]],
        "images": [{"index": i["index"], "image_id": i["image_id"], "side": i["side"], "filename": i["filename"],
                    "content_type": "image/png", "url": f"/inspections/INS-20260917-ABC123/images/{i['index']}"}
                   for i in an["images"]],
        "analysis": an,
    }


def walk(flowables):
    """Every Paragraph text and Image in the report, in order."""
    texts, images = [], []

    def visit(f):
        if isinstance(f, (list, tuple)):
            for x in f:
                visit(x)
        elif isinstance(f, Paragraph):
            texts.append(f.text)
        elif isinstance(f, Image):
            images.append(f)
        elif isinstance(f, Table):
            for row in f._cellvalues:
                for cell in row:
                    visit(cell)
        elif isinstance(f, KeepTogether):
            visit(f._content)

    visit(flowables)
    return texts, images


def plain(texts) -> str:
    return re.sub(r"<[^>]+>", " ", " \n".join(texts)).replace("&amp;", "&")


def story(rec, images=None):
    texts, imgs = walk(build_story(rec, images or {}, NOW))
    return plain(texts), texts, imgs


def section(body: str, start: str, end: str | None) -> str:
    i = body.index(start)
    j = body.index(end, i) if end else len(body)
    return body[i:j]


# ------------------------------------------------------------------ content


def step_no_compliance_verdict() -> None:
    print("\nno automatic PASS/FAIL/REVIEW compliance verdict")
    water = analysis((W_WATER, "FRONT"))
    check("a clean, fully-readable label is established by the deterministic system alone",
          assess(water)["required"] is False, json.dumps(assess(water)["reasons"])[:200])
    established = record(water)
    nothing = record(analysis((W_NOTHING, "FRONT")))
    for label, rec in (("established", established), ("not established", nothing)):
        pdf = render_report(rec, {1: photo(W_WATER)}, NOW)
        check(f"{label}: report renders a PDF", pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
              and len(pdf) > 5000)
    check("no report field is named bis_result, legal_metrology_result, system_result or system_reasons",
          not ({"bis_result", "legal_metrology_result", "system_result", "system_reasons"} & set(established)))
    body, _, _ = story(established)
    check("the header states plainly there is no compliance verdict",
          "contains no automatic PASS/FAIL/REVIEW compliance verdict" in body)
    without_disclaimer = body.replace("contains no automatic PASS/FAIL/REVIEW compliance verdict", "")
    check("outside that one disclaimer sentence, the report never prints PASS, FAIL or REVIEW as a verdict",
          not re.search(r"\bPASS\b|\bFAIL\b|\bREVIEW\b", without_disclaimer))
    check("the identified standard is shown instead of a verdict badge",
          "BIS STANDARD IDENTIFIED" in body and "IS 14543:2016" in section(body, "BIS STANDARD IDENTIFIED", "RESOLUTION"))
    nothing_body, _, _ = story(nothing)
    check("an unidentified product shows 'Not identified', not an invented standard",
          "Not identified" in section(nothing_body, "BIS STANDARD IDENTIFIED", "RESOLUTION"))


def step_requirement_knowledge() -> None:
    print("\nrequirements are shown as verified knowledge, never a check outcome")
    water = analysis((W_WATER, "FRONT"))
    body, _, _ = story(record(water))
    bis = section(body, "BIS standard evidence", "Certification guidance")
    check("the BIS section lists the requirements the standard specifies",
          "Requirements this standard specifies" in bis and "verified knowledge, not a pass/fail check" in bis)
    check("a requirement quotes verified text, with its own source",
          "BIS Certification Mark" in bis or "IS number" in bis, bis[:300])
    lm = section(body, "Legal Metrology evidence", "What MetrIQ could establish")
    check("the Legal Metrology section is requirement knowledge, not a check table",
          "package-label requirements" in lm.lower() and "not bis requirements" in lm.lower()
          and not re.search(r"\bPASS\b|\bFAIL\b", lm))
    resolution = section(body, "What MetrIQ could establish", "Evidence and sources")
    check("requirements with no verified deterministic rule are named in the resolution, never silently dropped",
          "REQUIREMENTS WITH NO VERIFIED DETERMINISTIC RULE" in resolution and "Rule 6" in resolution)
    check("there is no 'Compliance results' section and no 'Automated system result' section at all",
          "Compliance results" not in body and "Automated system result" not in body)


def step_no_human_decision() -> None:
    print("\nthe report records the deterministic system's own evidence only — no human decision")
    water = analysis((W_WATER, "FRONT"))
    rec = record(water)
    body, _, _ = story(rec)
    check("the report carries no human-review workflow at all",
          not re.search(r"officer (review|decision|result|note|status|final)|reviewed by|sign-?off"
                        r"|override|accept system result|manual review", body, re.I), body[:200])
    check("the report has no final-decision section beyond MetrIQ's own evidence",
          "Final outcome" not in body and "Final result" not in body)
    check("a fully-established inspection states the system established it itself",
          "Established by the deterministic system" in body and "nothing further is outstanding" in body)

    nothing = record(analysis((W_NOTHING, "FRONT")))
    body, _, _ = story(nothing)
    check("an unestablished inspection says what could not be established, and decides nothing",
          "Not fully established from the photos alone" in body
          and "verification outside MetrIQ is needed" in body)


def step_honesty() -> None:
    print("\nmissing data is reported honestly")
    an = analysis((W_NOTHING, "FRONT"))
    body, _, _ = story(record(an))
    check("product not identified is stated, not invented",
          "Not identified" in body and "product identification needs review" in body)
    check("no verified BIS standard is stated explicitly",
          "No verified BIS standard was identified by the automated retrieval process." in body
          and "No verified standard identified" in body)
    check("category not established is stated", "Not established" in body)

    kettle = analysis((W_KETTLE, "FRONT"))
    body, _, _ = story(record(kettle))
    check("a standard with no modelled requirement data says so plainly",
          "MetrIQ holds no verified requirement text for this standard." in body)
    resolution = section(body, "What MetrIQ could establish", "Evidence and sources")
    check("Legal Metrology package-label requirements with no deterministic rule are named for a package "
          "with no modelled requirement data",
          "REQUIREMENTS WITH NO VERIFIED DETERMINISTIC RULE" in resolution and "Rule 6" in resolution)
    decl = section(body, "Declarations", "BIS standard evidence")
    statuses = {f["status"] for f in kettle["declaration_stage"]["fields"]}
    check("declarations keep their stored statuses (DETECTED / UNCERTAIN / NOT_DETECTED)",
          all(s in decl for s in statuses) and "NOT_DETECTED" in statuses
          and "not a finding that the declaration is legally missing" in decl, str(statuses))


def step_images_and_escaping() -> None:
    print("\nmulti-side photos and stored text")
    an = analysis((W_FRONT, "FRONT"), (W_BACK, "BACK"))
    rec = record(an)
    images = {1: photo(W_FRONT), 2: photo(W_BACK)}
    body, texts, imgs = story(rec, images)
    photos = section(body, "Package photos", "OCR evidence")
    check("every stored side is included with its label, and no other side",
          len(imgs) == 2 and "FRONT · image 1" in photos and "BACK · image 2" in photos
          and not any(s in photos for s in ("LEFT", "RIGHT", "TOP", "BOTTOM")), photos[:200])
    check("OCR evidence names the side each region came from", "FRONT image: I1-OCR" in body
          and "BACK image: I2-OCR" in body)
    check("a stored photo that cannot be decoded is reported, not invented",
          "could not be decoded" in plain(walk(build_story(rec, {1: b"not an image", 2: photo(W_BACK)}, NOW))[0]))
    check("stored OCR text is escaped: markup in package text is shown literally",
          any("&lt;b&gt;Brand&lt;/b&gt;&lt;font size=40" in t for t in texts)
          and not any("<font size=40" in t for t in texts))
    pdf = render_report(rec, images, NOW)
    check("a label containing markup, ₹ and & still renders", pdf.startswith(b"%PDF") and len(pdf) > 5000)


def step_sources() -> None:
    print("\nsources")
    an = analysis((W_WATER, "FRONT"))
    rec = record(an)
    body, _, _ = story(rec)
    stored = set()

    def urls(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "source_url" and v:
                    stored.add(v)
                urls(v)
        elif isinstance(o, list):
            for v in o:
                urls(v)

    urls(rec)
    # Requirement sources are read live from MetrIQ's own verified knowledge base
    # (they are knowledge, not a stored check result) — still traceable, just not
    # duplicated into the stored analysis JSON.
    stored |= {item.source_url for item in get_product_finder().search_engine.items if item.source_url}
    shown = set(re.findall(r"https?://[^\s<]+", body))
    check("every URL in the report comes from the stored evidence or MetrIQ's verified knowledge base",
          shown and shown <= stored, str(shown - stored))
    check("the Legal Metrology sources are listed", any("consumeraffairs.gov.in" in u for u in shown))


# ------------------------------------------------------------------ endpoint


def migrate() -> None:
    name = make_url(TEST_URL).database or ""
    if not name.endswith("_test"):
        print(f"Refusing to use database '{name}': the test database name must end in '_test'.")
        sys.exit(1)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    get_engine().dispose()


def snapshot(iid: str):
    with get_engine().connect() as conn:
        row = conn.execute(text("SELECT to_jsonb(i) FROM inspections i WHERE inspection_id = :i"), {"i": iid}).scalar()
        imgs = conn.execute(text("SELECT position, md5(data) FROM inspection_images im JOIN inspections i "
                                 "ON i.id = im.inspection_pk WHERE i.inspection_id = :i ORDER BY position"),
                            {"i": iid}).all()
    return json.dumps(row, sort_keys=True), [tuple(r) for r in imgs]


def step_endpoint() -> None:
    print("\nGET /inspections/{id}/report.pdf")
    migrate()
    app.dependency_overrides[get_analyzer] = lambda: STUB
    files = [("images", ("front.png", photo(W_FRONT), "image/png")), ("images", ("back.png", photo(W_BACK), "image/png"))]
    saved = client.post("/inspections", files=files, data={"sides": ["FRONT", "BACK"]})
    iid = saved.json()["inspection_id"]
    before = snapshot(iid)

    calls = []

    def forbidden(name):
        def fn(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name} must not be called while generating a report")
        return fn

    patches = [(httpx, "post"), (escalation_module, "assess"), (records_module, "assess_escalation"),
               (records_module, "create_inspection"), (pipeline_module, "run_downstream")]
    originals = [(m, n, getattr(m, n)) for m, n in patches]
    for m, n in patches:
        setattr(m, n, forbidden(f"{m.__name__}.{n}"))
    analyze_calls = []
    app.dependency_overrides[get_analyzer] = lambda: analyze_calls.append(1) or STUB
    try:
        r = client.get(f"/inspections/{iid}/report.pdf")
    finally:
        for m, n, fn in originals:
            setattr(m, n, fn)
    check("endpoint returns application/pdf", r.status_code == 200 and r.headers["content-type"] == "application/pdf",
          f"{r.status_code} {r.headers.get('content-type')} {r.text[:200] if r.status_code != 200 else ''}")
    check("a saved inspection produces a PDF report", r.content.startswith(b"%PDF") and len(r.content) > 5000
          and f"metriq-report-{iid}.pdf" in r.headers.get("content-disposition", ""))
    check("report generation made no LLM / HTTP call", "httpx.post" not in calls)
    check("report generation recomputed no escalation or pipeline result",
          not calls and not analyze_calls, str(calls))
    check("report generation left the database record and stored photos unchanged", snapshot(iid) == before)
    check("the saved inspection's escalation is unchanged by generating a report",
          client.get(f"/inspections/{iid}").json()["escalation_required"] == saved.json()["escalation_required"])

    check("unknown inspection -> 404", client.get("/inspections/INS-20000101-FFFFFF/report.pdf").status_code == 404)
    check("malformed inspection id -> 422", client.get("/inspections/bad-id/report.pdf").status_code == 422)
    broken = sessionmaker(bind=create_engine("postgresql+psycopg://metriq@127.0.0.1:1/none",
                                             connect_args={"connect_timeout": 2}))

    def broken_session():
        s = broken()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = broken_session
    check("database unavailable -> 503", client.get(f"/inspections/{iid}/report.pdf").status_code == 503)
    app.dependency_overrides.clear()


def main() -> int:
    step_no_compliance_verdict()
    step_requirement_knowledge()
    step_no_human_decision()
    step_honesty()
    step_images_and_escaping()
    step_sources()
    step_endpoint()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
