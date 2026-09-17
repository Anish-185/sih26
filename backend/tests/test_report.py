"""Checks for Milestone 11 — evidence-backed inspection reports (PDF).

The report is an audit trail of a persisted inspection: it must show exactly what
is stored — system result, escalation, officer review, evidence, sources — never
merge the system result with the officer's decision, never invent anything, and
never change the record. Content is checked on the report's flowables
(``app.report.build_story``); rendering is checked on real PDF bytes.

Needs PostgreSQL for the endpoint checks (TEST_DATABASE_URL, default the local
``metriq_test`` database, migrated to head here). No LM Studio / OpenRouter.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_report.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import copy
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

import app.compliance as compliance_module  # noqa: E402
import app.escalation as escalation_module  # noqa: E402
import app.package_label as package_label_module  # noqa: E402
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


KETTLE = ["ELECTRIC KETTLE", "Product name: Electric Kettle", "MRP ₹899.00 (Inclusive of all taxes)",
          "Net Quantity: 1 N", "Mfg. Date: 02/2026", "Manufactured by: Thermopot Appliances Pvt Ltd",
          "Address: Plot 12, Baddi Industrial Area, Solan 173205, Himachal Pradesh",
          "Consumer care: 1800-300-7788", "Email: care@thermopot.example"]
INJECTION = "<b>Brand</b><font size=40 color=red>X</font> & <para>"
W_KETTLE, W_FRONT, W_BACK, W_NOTHING = 961, 962, 963, 964
STUB = InspectionAnalyzer(ocr_engine=Engine({
    W_KETTLE: raw(*KETTLE),
    W_FRONT: raw("ELECTRIC KETTLE", "Product name: Electric Kettle", INJECTION),
    W_BACK: raw("MRP ₹899.00 (Inclusive of all taxes)", "Net Quantity: 1 N"),
    W_NOTHING: raw("SUNSHINE", "Best quality since 1990"),
}), product_finder=get_product_finder())


def analysis(*sides) -> dict:
    out = STUB.analyze_package([PackageUpload(photo(w), f"{s.lower()}.png", s) for w, s in sides])
    return out.model_dump(mode="json")


def record(an: dict, officer_status="PENDING", decision=None, officer_result=None, note=None) -> dict:
    """A stored-record JSON (InspectionRecordOut shape) for an analysis, as the API would return it."""
    esc = assess(an)
    bis, lm = an["compliance"]["overall_status"], an["package_label"]["overall_status"]
    final = None
    if officer_status == "NOT_REQUIRED":
        final = esc["system_result"]
    elif officer_status == "COMPLETED":
        final = {"ACCEPT_SYSTEM_RESULT": esc["system_result"], "OVERRIDE": officer_result}.get(decision, "MANUAL_REVIEW")
    matched = an["product"]["status"] == "MATCHED"
    return {
        "inspection_id": "INS-20260917-ABC123", "created_at": "2026-09-17T10:00:00+00:00",
        "product_status": an["product"]["status"], "product_name": an["product"]["name"] if matched else None,
        "product_category": (an["compliance"].get("coverage") or {}).get("product_category"),
        "standard_number": an["product"]["standard_number"] if matched else None,
        "bis_result": bis, "legal_metrology_result": lm, "system_result": esc["system_result"],
        "escalation_required": esc["required"], "escalation_reasons": esc["reasons"],
        "officer_status": officer_status, "officer_decision": decision, "officer_result": officer_result,
        "final_result": final,
        "review_started_at": "2026-09-17T10:05:00+00:00" if officer_status in ("IN_REVIEW", "COMPLETED") else None,
        "review_completed_at": "2026-09-17T10:09:00+00:00" if officer_status == "COMPLETED" else None,
        "image_count": len(an["images"]), "sides": [i["side"] for i in an["images"]],
        "system_reasons": [
            {"source": "BIS", "result": bis, "reason_code": an["compliance"]["reason_code"], "reason": an["compliance"]["reason"]},
            {"source": "LEGAL_METROLOGY", "result": lm, "reason_code": an["package_label"]["reason_code"],
             "reason": an["package_label"]["reason"]},
        ],
        "officer_note": note,
        "images": [{"index": i["index"], "image_id": i["image_id"], "side": i["side"], "filename": i["filename"],
                    "content_type": "image/png", "url": f"/inspections/INS-20260917-ABC123/images/{i['index']}"}
                   for i in an["images"]],
        "analysis": an,
    }


def resolved(an: dict, bis="PASS", lm="PASS") -> dict:
    """Results set to a resolved state — the verified data has no fully checkable standard."""
    d = copy.deepcopy(an)
    d["compliance"].update(overall_status=bis, coverage_status="INSPECTION_SUPPORTED",
                           reason_code="ALL_CHECKS_PASSED" if bis == "PASS" else "SUPPORTED_CHECK_FAILED")
    d["package_label"].update(overall_status=lm,
                              reason_code="ALL_CHECKS_PASSED" if lm == "PASS" else "SUPPORTED_CHECK_FAILED")
    d["package_label"]["checks"] = [c for c in d["package_label"]["checks"] if c["result"] != "NOT_SUPPORTED"]
    if lm == "FAIL":
        d["package_label"]["checks"][0].update(result="FAIL", reason_code="VALUE_FORMAT_INVALID",
                                                reason="Stated as a dozen (Rule 13(4)).")
    return d


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


def step_results() -> None:
    print("\nPASS / FAIL / REVIEW")
    base = analysis((W_KETTLE, "FRONT"))
    for label, an in (("PASS", resolved(base)), ("FAIL", resolved(base, lm="FAIL")), ("REVIEW", base)):
        rec = record(an, officer_status="NOT_REQUIRED" if label != "REVIEW" else "PENDING")
        pdf = render_report(rec, {1: photo(W_KETTLE)}, NOW)
        body, _, _ = story(rec, {1: photo(W_KETTLE)})
        system = section(body, "AUTOMATED SYSTEM RESULT", "OFFICER FINAL DECISION")
        check(f"{label} report renders a PDF", pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
              and len(pdf) > 5000)
        check(f"{label} report shows the stored system result", rec["system_result"] == label and label in system,
              system[:120])
    fail_rec = record(resolved(base, lm="FAIL"), officer_status="NOT_REQUIRED")
    body, _, _ = story(fail_rec)
    check("FAIL report shows the failing rule and its reason",
          "FAIL" in section(body, "Compliance results", "Automated system result")
          and "Stated as a dozen (Rule 13(4))." in body)


def step_officer() -> None:
    print("\nsystem result vs officer decision")
    an = analysis((W_KETTLE, "FRONT"))
    rec = record(an, "COMPLETED", "OVERRIDE", "PASS", "Verified against physical package.")
    body, _, _ = story(rec)
    final = section(body, "Final outcome", "Evidence and sources")
    check("7 officer-reviewed report shows the officer decision and result",
          "Override" in final and "OFFICER RESULT" in final and "PASS" in final)
    check("8 system result and officer decision appear as separate fields",
          "SYSTEM RESULT" in final and "REVIEW" in final.split("OFFICER FINAL DECISION")[0]
          and "OFFICER FINAL DECISION" in final)
    check("9 officer note appears", body.count("Verified against physical package.") >= 2)
    check("the report never shows an officer name or identity",
          "no officer identity is recorded" in body and not re.search(r"(officer|reviewed) by\b", body, re.I))

    accepted = record(an, "COMPLETED", "ACCEPT_SYSTEM_RESULT")
    body, _, _ = story(accepted)
    final = section(body, "Final outcome", "Evidence and sources")
    check("accepted: both the REVIEW system result and 'Accept system result' are shown",
          "Accept system result" in final and "REVIEW" in final and "No note recorded" in final)

    pending = record(an, "PENDING")
    body, _, _ = story(pending)
    officer = section(body, "Officer review", "Final outcome")
    check("10 pending review: shown as pending, no decision, no approval implied",
          "Pending officer review" in officer and "No officer has approved" in officer
          and "Override" not in body and "Accept system result" not in body
          and "Not final until the officer review is completed" in body)
    resolved_rec = record(resolved(an), "NOT_REQUIRED")
    body, _, _ = story(resolved_rec)
    check("10 not escalated: the report says officer review was not required",
          "Officer review was not required" in body and "The system result is final." in body)


def step_honesty() -> None:
    print("\nmissing data is reported honestly")
    an = analysis((W_NOTHING, "FRONT"))
    body, _, _ = story(record(an))
    check("11 product not identified is stated, not invented",
          "Not identified" in body and "product identification needs review" in body)
    check("12 no verified BIS standard is stated explicitly",
          "No verified BIS standard was identified by the automated retrieval process." in body
          and "No verified standard identified" in body)
    check("category not established is stated", "Not established" in body)

    kettle = analysis((W_KETTLE, "FRONT"))
    body, _, _ = story(record(kettle))
    comp = section(body, "Compliance results", "Automated system result")
    lm_checks = [c for c in kettle["package_label"]["checks"] if c["result"] == "NOT_SUPPORTED"]
    check("13 unsupported Legal Metrology checks stay UNSUPPORTED, never PASS",
          lm_checks and comp.count("UNSUPPORTED") >= len(lm_checks)
          and "Not checkable from an image" in body and kettle["package_label"]["overall_status"] == "REVIEW"
          and "never counted as PASS" in comp)
    decl = section(body, "Declarations", "BIS standard evidence")
    statuses = {f["status"] for f in kettle["declaration_stage"]["fields"]}
    check("15 declarations keep their stored statuses (DETECTED / UNCERTAIN / NOT_DETECTED)",
          all(s in decl for s in statuses) and "NOT_DETECTED" in statuses
          and "not a finding that the declaration is legally missing" in decl, str(statuses))
    check("15 an UNSUPPORTED result keeps its label in the report", "UNSUPPORTED" in comp)


def step_images_and_escaping() -> None:
    print("\nmulti-side photos and stored text")
    an = analysis((W_FRONT, "FRONT"), (W_BACK, "BACK"))
    rec = record(an)
    images = {1: photo(W_FRONT), 2: photo(W_BACK)}
    body, texts, imgs = story(rec, images)
    photos = section(body, "Package photos", "OCR evidence")
    check("14 every stored side is included with its label, and no other side",
          len(imgs) == 2 and "FRONT · image 1" in photos and "BACK · image 2" in photos
          and not any(s in photos for s in ("LEFT", "RIGHT", "TOP", "BOTTOM")), photos[:200])
    check("14 OCR evidence names the side each region came from", "FRONT image: I1-OCR" in body
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
    an = analysis((W_KETTLE, "FRONT"))
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
    shown = set(re.findall(r"https?://[^\s<]+", body))
    check("19 every URL in the report comes from the stored evidence",
          shown and shown <= stored, str(shown - stored))
    check("19 the Legal Metrology sources are listed", any("consumeraffairs.gov.in" in u for u in shown))


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
    client.post(f"/inspections/{iid}/review", json={"action": "START"})
    client.post(f"/inspections/{iid}/review", json={"action": "COMPLETE", "decision": "MANUAL_REVIEW",
                                                    "note": "Physical package check required."})
    before = snapshot(iid)

    calls = []

    def forbidden(name):
        def fn(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name} must not be called while generating a report")
        return fn

    patches = [(httpx, "post"), (escalation_module, "assess"), (records_module, "assess_escalation"),
               (records_module, "create_inspection"), (compliance_module, "evaluate_compliance"),
               (package_label_module, "evaluate_package_label"), (pipeline_module, "run_downstream")]
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
    check("1 endpoint returns application/pdf", r.status_code == 200 and r.headers["content-type"] == "application/pdf",
          f"{r.status_code} {r.headers.get('content-type')} {r.text[:200] if r.status_code != 200 else ''}")
    check("2 a saved inspection produces a PDF report", r.content.startswith(b"%PDF") and len(r.content) > 5000
          and f"metriq-report-{iid}.pdf" in r.headers.get("content-disposition", ""))
    check("17 report generation made no LLM / HTTP call", "httpx.post" not in calls)
    check("18 report generation recomputed no compliance, package label, pipeline or escalation",
          not calls and not analyze_calls, str(calls))
    check("16 report generation left the database record and stored photos unchanged", snapshot(iid) == before)
    check("18 compliance results in the record are unchanged",
          client.get(f"/inspections/{iid}").json()["system_result"] == saved.json()["system_result"])

    check("3 unknown inspection -> 404", client.get("/inspections/INS-20000101-FFFFFF/report.pdf").status_code == 404)
    check("3 malformed inspection id -> 422", client.get("/inspections/bad-id/report.pdf").status_code == 422)
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
    step_results()
    step_officer()
    step_honesty()
    step_images_and_escaping()
    step_sources()
    step_endpoint()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
