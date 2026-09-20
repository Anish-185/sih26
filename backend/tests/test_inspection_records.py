"""Checks for Milestone 9 — persisted inspections and the officer review.

Needs PostgreSQL. Uses TEST_DATABASE_URL (default: the local ``metriq_test``
database) and refuses any database whose name does not end in ``_test``,
because it drops and re-creates the schema through the Alembic migration.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_inspection_records.py

Exit 0 = all checks passed, 1 = something failed.

Milestone 10 adds escalation: an inspection the system resolved is saved as
NOT_REQUIRED (never queued, no review possible); every other one goes to the
officer queue as PENDING. Migration 0002 is tested by backfilling rows saved
under migration 0001.

Package photos are analysed by the real pipeline; most use a stubbed OCR engine
(controlled text) so results are deterministic, and one uses the real local OCR
engine on a sample label. No LM Studio / OpenRouter.
"""

from __future__ import annotations

import copy
import io
import json
import os
import sys
import warnings
from pathlib import Path

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg:///metriq_test")
os.environ["DATABASE_URL"] = TEST_URL
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.api import get_product_finder  # noqa: E402
from app.db import get_engine, get_session  # noqa: E402
from app.escalation import assess  # noqa: E402
from app.inspection import EscalationOut, InspectionAnalysisOut, InspectionAnalyzer  # noqa: E402
from app.inspection_api import get_analyzer  # noqa: E402
from app.main import app  # noqa: E402
from app.ocr import RawRegion  # noqa: E402

PASS = 0
FAIL = 0
BACKEND = Path(__file__).resolve().parents[1]
SAMPLES = BACKEND.parent / "samples" / "ocr-labels"
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


def png(width: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, 400), "white").save(buf, format="PNG")
    return buf.getvalue()


def raw(*texts):
    out, y = [], 20
    for i, t in enumerate(texts):
        h = 50 if i == 0 else 25
        out.append(RawRegion(t, 0.95, (10, y, 10 + 10 * len(t), y + h),
                             [[10, y], [10 + 10 * len(t), y], [10 + 10 * len(t), y + h], [10, y + h]]))
        y += h + 15
    return out


class Engine:
    """Stub OCR: the text returned depends on the image width."""

    def __init__(self, by_width):
        self.by_width = by_width

    def __call__(self, arr):
        return list(self.by_width[arr.shape[1]]), 0.01


KETTLE_FULL = raw("ELECTRIC KETTLE", "Product name: Electric Kettle", "MRP ₹899.00 (Inclusive of all taxes)",
                  "Net Quantity: 1 N", "Mfg. Date: 02/2026", "Manufactured by: Thermopot Appliances Pvt Ltd",
                  "Address: Plot 12, Baddi Industrial Area, Solan 173205, Himachal Pradesh",
                  "Consumer care: 1800-300-7788", "Email: care@thermopot.example")
DOZEN = raw("ELECTRIC KETTLE", "Product name: Electric Kettle", "Net Quantity: 1 dozen")
FRONT, BACK = raw("ELECTRIC KETTLE", "MRP ₹899.00 (Inclusive of all taxes)"), raw("Net Quantity: 1 N")
W_REVIEW, W_FAIL, W_FRONT, W_BACK = 811, 812, 813, 814
STUB = InspectionAnalyzer(
    ocr_engine=Engine({W_REVIEW: KETTLE_FULL, W_FAIL: DOZEN, W_FRONT: FRONT, W_BACK: BACK}),
    product_finder=get_product_finder(),
)


def resolved(data: dict, bis="PASS", lm="PASS") -> dict:
    """A real analysis with its results set to a fully resolved state. The verified data has no
    standard whose every requirement is checkable, so this is the only way to show a resolved case."""
    d = copy.deepcopy(data)
    d["compliance"].update(overall_status=bis, coverage_status="INSPECTION_SUPPORTED", reason_code="ALL_CHECKS_PASSED")
    d["package_label"].update(overall_status=lm, reason_code="ALL_CHECKS_PASSED")
    d["package_label"]["checks"] = [c for c in d["package_label"]["checks"] if c["result"] != "NOT_SUPPORTED"]
    for img in d["images"]:
        if img.get("quality"):
            img["quality"].update(is_low_quality=False, notes=[])
    d["escalation"] = assess(d)
    return d


class ResolvedAnalyzer:
    """The real stubbed pipeline, with its results set to a state the system can resolve."""

    def analyze_package(self, uploads):
        data = resolved(STUB.analyze_package(uploads).model_dump(mode="json"))
        return InspectionAnalysisOut.model_validate(data)


def save(*widths_sides, extra: dict | None = None):
    files = [("images", (f"{side.lower()}.png", png(w), "image/png")) for w, side in widths_sides]
    data = {"sides": [side for _, side in widths_sides], **(extra or {})}
    return client.post("/inspections", files=files, data=data)


def review(inspection_id, **body):
    return client.post(f"/inspections/{inspection_id}/review", json=body)


# ------------------------------------------------------------------ database


def reset_database() -> None:
    name = make_url(TEST_URL).database or ""
    if not name.endswith("_test"):
        print(f"Refusing to reset database '{name}': the test database name must end in '_test'.")
        sys.exit(1)
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        print(f"PostgreSQL test database unavailable at {TEST_URL}: {exc.__class__.__name__}.\n"
              "Create it with:  createdb metriq_test   (see README: Inspection database)")
        sys.exit(1)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.downgrade(cfg, "base")
    tables = set(inspect(get_engine()).get_table_names())
    check("migration: downgrade to base removes the tables", not {"inspections", "inspection_images"} & tables)
    migrate_existing_rows(cfg)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    get_engine().dispose()
    tables = set(inspect(get_engine()).get_table_names())
    check("migration: a fresh database is created from the migration",
          {"inspections", "inspection_images", "alembic_version"} <= tables, str(tables))


def migrate_existing_rows(cfg) -> None:
    """Rows saved under migration 0001 are assessed and given an escalation by 0002."""
    print("\nmigration 0002 backfills existing inspections")
    command.upgrade(cfg, "0001_inspection_records")
    from PIL import Image as _Image  # noqa: F401 — photos are not needed for these rows
    escalated = STUB.analyze_package([_upload(W_REVIEW)]).model_dump(mode="json")
    escalated.pop("escalation", None)
    clean = resolved(escalated)
    clean.pop("escalation")
    rows = [("INS-20000101-0000A1", clean, "PENDING"), ("INS-20000101-0000A2", escalated, "PENDING"),
            ("INS-20000101-0000A3", clean, "COMPLETED")]
    with get_engine().begin() as conn:
        for iid, analysis, status in rows:
            done = status == "COMPLETED"
            conn.execute(text(
                "INSERT INTO inspections (inspection_id, product_status, bis_result, legal_metrology_result, "
                "system_result, system_reasons, sides, analysis, officer_status, officer_decision, review_started_at, "
                "review_completed_at) VALUES (:i, 'MATCHED', :b, :l, :s, '[]', '[\"FRONT\"]', CAST(:a AS jsonb), "
                ":st, :d, CASE WHEN :done THEN now() END, CASE WHEN :done THEN now() END)"),
                {"i": iid, "b": analysis["compliance"]["overall_status"], "l": analysis["package_label"]["overall_status"],
                 "s": assess(analysis)["system_result"], "a": json.dumps(analysis), "st": status,
                 "d": "ACCEPT_SYSTEM_RESULT" if done else None, "done": done})
    command.upgrade(cfg, "head")
    get_engine().dispose()
    with get_engine().connect() as conn:
        got = {r[0]: r[1:] for r in conn.execute(text(
            "SELECT inspection_id, officer_status, escalation_required, escalation_reasons FROM inspections"))}
    check("0002: an unreviewed inspection the system can resolve becomes NOT_REQUIRED",
          got["INS-20000101-0000A1"][:2] == ("NOT_REQUIRED", False) and got["INS-20000101-0000A1"][2] == [], str(got.get("INS-20000101-0000A1")))
    check("0002: an unresolved inspection stays PENDING with its reasons",
          got["INS-20000101-0000A2"][:2] == ("PENDING", True) and got["INS-20000101-0000A2"][2] == assess(escalated)["reasons"])
    check("0002: an inspection an officer already reviewed keeps its review",
          got["INS-20000101-0000A3"][0] == "COMPLETED")
    command.downgrade(cfg, "0001_inspection_records")
    with get_engine().connect() as conn:
        statuses = {r[0] for r in conn.execute(text("SELECT officer_status FROM inspections"))}
    check("0002 downgrade: NOT_REQUIRED returns to PENDING and the escalation columns are removed",
          "NOT_REQUIRED" not in statuses and "escalation_required" not in
          {c["name"] for c in inspect(get_engine()).get_columns("inspections")})


def _upload(width):
    from app.inspection import PackageUpload
    return PackageUpload(png(width), "front.png", "FRONT")


def step_empty() -> None:
    print("\nempty database")
    r = client.get("/inspections")
    check("21 empty history works", r.status_code == 200 and r.json() == {"items": [], "total": 0}, r.text)
    r = client.get("/inspections", params={"officer_status": ["PENDING", "IN_REVIEW"]})
    check("22 empty review queue works", r.status_code == 200 and r.json()["total"] == 0)
    s = client.get("/inspections/stats").json()
    check("dashboard statistics are all 0 with no data",
          s["total"] == 0 and all(v == 0 for k in ("system", "bis", "legal_metrology", "officer", "decisions")
                                  for v in s[k].values()), str(s))


def step_create_and_read() -> dict:
    print("\ncreate, persist, retrieve")
    app.dependency_overrides[get_analyzer] = lambda: STUB
    r = save((W_REVIEW, "FRONT"))
    check("1 create inspection -> 201", r.status_code == 201, r.text[:300])
    rec = r.json()
    check("the backend computed the result: BIS REVIEW, Legal Metrology REVIEW -> system REVIEW",
          (rec["bis_result"], rec["legal_metrology_result"], rec["system_result"]) == ("REVIEW", "REVIEW", "REVIEW"))
    check("an unresolved inspection is escalated with its reasons",
          rec["escalation_required"] is True and rec["escalation_reasons"]
          and rec["escalation_reasons"] == rec["analysis"]["escalation"]["reasons"]
          and "REQUIREMENT_NOT_CHECKABLE" in {x["code"] for x in rec["escalation_reasons"]})
    check("new inspection is PENDING with no decision",
          rec["officer_status"] == "PENDING" and rec["officer_decision"] is None and rec["final_result"] is None
          and rec["review_started_at"] is None)
    check("product information is stored", rec["product_status"] == "MATCHED" and rec["product_name"]
          and rec["standard_number"] == "IS 367:1993", f"{rec['product_name']} {rec['standard_number']}")

    got = client.get(f"/inspections/{rec['inspection_id']}")
    body = got.json()
    check("2/3 inspection persists and is retrieved by id", got.status_code == 200
          and body["inspection_id"] == rec["inspection_id"])
    check("5 system result persists", body["system_result"] == "REVIEW")
    check("6 system reasons persist, one per evidence system",
          [x["source"] for x in body["system_reasons"]] == ["BIS", "LEGAL_METROLOGY"]
          and all(x["reason"] and x["reason_code"] for x in body["system_reasons"]))
    checks = body["analysis"]["package_label"]["checks"]
    mrp = next(c for c in checks if c["rule_id"] == "lm-retail-sale-price-declared")
    check("7 evidence persists: check result, OCR region, confidence, bbox, side and source",
          mrp["result"] == "PASS" and mrp["evidence"][0]["source_regions"] and mrp["evidence"][0]["bbox"]
          and mrp["evidence"][0]["ocr_confidence"] and mrp["evidence"][0]["source_sides"] == ["FRONT"]
          and mrp["source"]["source_authority"] == "LEGAL_METROLOGY", str(mrp["evidence"]))
    check("7 declarations and OCR regions persist",
          body["analysis"]["declaration_stage"]["fields"] and body["analysis"]["ocr"]["regions"]
          and body["analysis"] == rec["analysis"])
    img = client.get(body["images"][0]["url"])
    check("7 the package photo is stored byte for byte", img.status_code == 200
          and img.content == png(W_REVIEW) and img.headers["content-type"] == "image/png")
    check("stored image metadata keeps side and upload order",
          body["images"][0]["side"] == "FRONT" and body["images"][0]["index"] == 1)
    return body


def step_list_and_queue(rec: dict) -> None:
    print("\nhistory and review queue")
    r = client.get("/inspections").json()
    check("4/14 history lists the real inspection", r["total"] == 1 and r["items"][0]["inspection_id"] == rec["inspection_id"])
    check("history rows carry the columns the UI shows, without the full analysis",
          {"product_name", "standard_number", "system_result", "officer_status", "final_result", "created_at"}
          <= set(r["items"][0]) and "analysis" not in r["items"][0])
    q = client.get("/inspections", params={"officer_status": ["PENDING", "IN_REVIEW"]}).json()
    check("15 review queue contains the pending inspection", [i["inspection_id"] for i in q["items"]] == [rec["inspection_id"]])


def step_review_accept(rec: dict) -> None:
    print("\nofficer review: accept")
    iid = rec["inspection_id"]
    r = review(iid, action="COMPLETE", decision="ACCEPT_SYSTEM_RESULT")
    check("18 COMPLETE before START -> 409", r.status_code == 409, r.text)
    r = review(iid, action="START")
    body = r.json()
    check("8 officer review starts -> IN_REVIEW with review_started_at", r.status_code == 200
          and body["officer_status"] == "IN_REVIEW" and body["review_started_at"])
    check("18 START twice -> 409", review(iid, action="START").status_code == 409)
    queue = client.get("/inspections", params={"officer_status": ["PENDING", "IN_REVIEW"]}).json()
    check("an inspection in review stays in the review queue", queue["total"] == 1)
    r = review(iid, action="COMPLETE", decision="ACCEPT_SYSTEM_RESULT", officer_result="PASS")
    check("ACCEPT with an officer result -> 422", r.status_code == 422, r.text)
    r = review(iid, action="COMPLETE", decision="ACCEPT_SYSTEM_RESULT", note="Verified against physical package.")
    body = r.json()
    check("9 officer accepts the system result", r.status_code == 200 and body["officer_status"] == "COMPLETED"
          and body["officer_decision"] == "ACCEPT_SYSTEM_RESULT" and body["final_result"] == "REVIEW"
          and body["officer_result"] is None)
    check("11 officer note is stored", body["officer_note"] == "Verified against physical package.")
    check("18 a second decision on a completed review -> 409 (duplicate review)",
          review(iid, action="COMPLETE", decision="MANUAL_REVIEW", note="again").status_code == 409)
    again = client.get(f"/inspections/{iid}").json()
    check("13 review timestamps persist and are ordered",
          again["review_started_at"] and again["review_completed_at"]
          and again["review_started_at"] <= again["review_completed_at"] and again["created_at"] <= again["review_started_at"])
    check("system result and analysis are unchanged by the review",
          again["system_result"] == "REVIEW" and again["analysis"] == rec["analysis"])
    queue = client.get("/inspections", params={"officer_status": ["PENDING", "IN_REVIEW"]}).json()
    check("16 completed inspection leaves the pending queue", queue["total"] == 0)


def step_review_override() -> None:
    print("\nofficer review: override")
    r = save((W_FAIL, "BACK"))
    rec = r.json()
    iid = rec["inspection_id"]
    check("a dozen on the label -> Legal Metrology FAIL -> system FAIL",
          r.status_code == 201 and rec["legal_metrology_result"] == "FAIL" and rec["system_result"] == "FAIL")
    review(iid, action="START")
    check("OVERRIDE without a result -> 422",
          review(iid, action="COMPLETE", decision="OVERRIDE", note="x").status_code == 422)
    check("OVERRIDE to the same result as the system -> 422",
          review(iid, action="COMPLETE", decision="OVERRIDE", officer_result="FAIL", note="same").status_code == 422)
    check("OVERRIDE without a note -> 422",
          review(iid, action="COMPLETE", decision="OVERRIDE", officer_result="PASS").status_code == 422)
    check("unknown decision -> 422", review(iid, action="COMPLETE", decision="APPROVE").status_code == 422)
    check("note over the limit -> 422",
          review(iid, action="COMPLETE", decision="MANUAL_REVIEW", note="n" * 2001).status_code == 422)
    check("unknown action -> 422", review(iid, action="REOPEN").status_code == 422)
    r = review(iid, action="COMPLETE", decision="OVERRIDE", officer_result="REVIEW",
               note="Package image partially obscured; physical package checked.")
    body = r.json()
    check("10 officer overrides the system result", r.status_code == 200 and body["officer_decision"] == "OVERRIDE"
          and body["officer_result"] == "REVIEW" and body["final_result"] == "REVIEW")
    again = client.get(f"/inspections/{iid}").json()
    check("12 system result remains FAIL after the override",
          again["system_result"] == "FAIL" and again["legal_metrology_result"] == "FAIL"
          and again["system_reasons"] == rec["system_reasons"] and again["analysis"] == rec["analysis"])


def step_security() -> None:
    print("\nclient cannot set or change the system result")
    r = save((W_FRONT, "FRONT"), (W_BACK, "BACK"), extra={"system_result": "PASS"})
    check("19 POST /inspections with a system_result field -> 422, nothing saved",
          r.status_code == 422 and "system_result" in r.text and client.get("/inspections").json()["total"] == 2, r.text)
    r = save((W_FRONT, "FRONT"), (W_BACK, "BACK"))
    rec = r.json()
    iid = rec["inspection_id"]
    check("multi-side package saves every photo with its side",
          r.status_code == 201 and [(i["index"], i["side"]) for i in rec["images"]] == [(1, "FRONT"), (2, "BACK")]
          and rec["sides"] == ["FRONT", "BACK"])
    check("multi-side evidence keeps per-photo region ids",
          any(reg["id"].startswith("I2-") for reg in rec["analysis"]["ocr"]["regions"]))
    r = review(iid, action="START", system_result="PASS")
    check("19 review body with system_result -> 422", r.status_code == 422, r.text)
    r = review(iid, action="COMPLETE", decision="ACCEPT_SYSTEM_RESULT", bis_result="PASS")
    check("19 review body with bis_result -> 422", r.status_code == 422)
    check("19 system result still unchanged", client.get(f"/inspections/{iid}").json()["system_result"] == rec["system_result"])

    Session = sessionmaker(bind=get_engine())
    with Session() as s:
        try:
            s.execute(text("UPDATE inspections SET system_result = 'PASS' WHERE inspection_id = :i"), {"i": iid})
            s.commit()
            blocked = False
        except DBAPIError:
            s.rollback()
            blocked = True
    check("19 the database itself rejects changing a saved system result", blocked)
    with Session() as s:
        try:
            s.execute(text("UPDATE inspection_images SET data = 'x' WHERE position = 1"))
            s.commit()
            blocked = False
        except DBAPIError:
            s.rollback()
            blocked = True
    check("stored photos cannot be altered", blocked)
    with Session() as s:
        s.execute(text("UPDATE inspections SET officer_note = NULL WHERE inspection_id = :i"), {"i": iid})
        s.commit()
    check("officer columns remain writable (the trigger protects only system columns)", True)


def step_not_required() -> None:
    print("\nresolved by the system: no officer review")
    app.dependency_overrides[get_analyzer] = lambda: ResolvedAnalyzer()
    r = save((W_REVIEW, "FRONT"))
    rec = r.json()
    iid = rec["inspection_id"]
    app.dependency_overrides[get_analyzer] = lambda: STUB
    check("a resolved inspection is saved as NOT_REQUIRED with no escalation reasons",
          r.status_code == 201 and rec["system_result"] == "PASS" and rec["escalation_required"] is False
          and rec["escalation_reasons"] == [] and rec["officer_status"] == "NOT_REQUIRED", r.text[:300])
    check("its final result is the system result", rec["final_result"] == "PASS" and rec["officer_decision"] is None)
    queue = client.get("/inspections", params={"officer_status": ["PENDING", "IN_REVIEW"]}).json()
    check("a resolved inspection never enters the officer queue", iid not in {i["inspection_id"] for i in queue["items"]})
    history = client.get("/inspections").json()
    check("a resolved inspection is in history", iid in {i["inspection_id"] for i in history["items"]})
    r = review(iid, action="START")
    check("starting a review of a resolved inspection -> 409", r.status_code == 409 and "not escalated" in r.text, r.text)
    check("recording a decision on a resolved inspection -> 409",
          review(iid, action="COMPLETE", decision="OVERRIDE", officer_result="FAIL", note="x").status_code == 409)
    Session = sessionmaker(bind=get_engine())
    for sql, name in (("UPDATE inspections SET officer_status = 'PENDING' WHERE inspection_id = :i",
                       "the database refuses to move a resolved inspection into the queue"),
                      ("UPDATE inspections SET escalation_required = true WHERE inspection_id = :i",
                       "the database refuses to change a saved escalation decision"),
                      ("UPDATE inspections SET escalation_reasons = '[]' WHERE inspection_id = :i",
                       "the database refuses to change saved escalation reasons")):
        with Session() as sess:
            try:
                target = iid if "escalation_reasons" not in sql else client.get("/inspections").json()["items"][-1]["inspection_id"]
                sess.execute(text(sql), {"i": target})
                sess.commit()
                blocked = False
            except DBAPIError:
                sess.rollback()
                blocked = True
        check(name, blocked)
    check("the resolved inspection is unchanged", client.get(f"/inspections/{iid}").json()["officer_status"] == "NOT_REQUIRED")


def step_errors() -> None:
    print("\nerrors")
    check("17 malformed inspection id -> 422", client.get("/inspections/not-an-id").status_code == 422)
    check("17 unknown inspection id -> 404", client.get("/inspections/INS-20000101-ABCDEF").status_code == 404)
    check("17 review of an unknown inspection -> 404",
          review("INS-20000101-ABCDEF", action="START").status_code == 404)
    iid = client.get("/inspections").json()["items"][0]["inspection_id"]
    check("missing stored image -> 404", client.get(f"/inspections/{iid}/images/9").status_code == 404)
    check("malformed review body -> 422",
          client.post(f"/inspections/{iid}/review", content=b"{not json", headers={"content-type": "application/json"}).status_code == 422)
    check("POST /inspections without photos -> 422", client.post("/inspections", data={}).status_code == 422)
    check("invalid officer_status filter -> 422",
          client.get("/inspections", params={"officer_status": "DONE"}).status_code == 422)

    broken = sessionmaker(bind=create_engine("postgresql+psycopg://metriq@127.0.0.1:1/none",
                                             connect_args={"connect_timeout": 2}))

    def broken_session():
        s = broken()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = broken_session
    r = client.get("/inspections")
    check("database failure -> 503 with a useful message", r.status_code == 503 and "PostgreSQL" in r.text, r.text)
    check("database failure on stats -> 503", client.get("/inspections/stats").status_code == 503)
    app.dependency_overrides.pop(get_session)


def step_stats() -> None:
    print("\ndashboard statistics")
    s = client.get("/inspections/stats").json()
    with get_engine().connect() as conn:
        system = dict(conn.execute(text("SELECT system_result, count(*) FROM inspections GROUP BY 1")).all())
        officer = dict(conn.execute(text("SELECT officer_status, count(*) FROM inspections GROUP BY 1")).all())
        total = conn.execute(text("SELECT count(*) FROM inspections")).scalar()
    check("20 statistics equal the database counts",
          s["total"] == total and all(s["system"][k] == system.get(k, 0) for k in ("PASS", "FAIL", "REVIEW"))
          and all(s["officer"][k] == officer.get(k, 0) for k in ("NOT_REQUIRED", "PENDING", "IN_REVIEW", "COMPLETED")),
          str(s))
    check("escalated counts every inspection the system could not resolve",
          s["escalated"] == s["total"] - s["officer"]["NOT_REQUIRED"] and s["officer"]["NOT_REQUIRED"] == 1)
    check("system results and officer states are counted separately",
          sum(s["system"].values()) == s["total"] == sum(s["officer"].values())
          and s["officer"]["COMPLETED"] == 2 and s["decisions"]["OVERRIDE"] == 1
          and s["decisions"]["ACCEPT_SYSTEM_RESULT"] == 1)


def step_real_ocr() -> None:
    print("\nreal OCR engine end to end")
    app.dependency_overrides.pop(get_analyzer, None)
    path = SAMPLES / "synth_electric-kettle.png"
    with path.open("rb") as fh:
        r = client.post("/inspections", files={"image": (path.name, fh, "image/png")}, data={"side": "FRONT"})
    rec = r.json()
    checks = {c["rule_id"]: c["result"] for c in rec.get("analysis", {}).get("package_label", {}).get("checks", [])}
    check("real label: saved with product, standard and six passing Legal Metrology checks",
          r.status_code == 201 and rec["standard_number"] == "IS 367:1993"
          and sum(v == "PASS" for v in checks.values()) == 6 and rec["system_result"] == "REVIEW", str(checks))
    check("real label: stored photo is returned unchanged",
          client.get(rec["images"][0]["url"]).content == path.read_bytes())


def step_copilot_is_read_only() -> None:
    """Milestone 13: an explanation of a saved inspection must not touch the row."""
    print("\nthe copilot explains a saved inspection without changing it")
    import json as _json

    from app.copilot import InspectionCopilot
    from app.copilot_api import get_copilot

    r = save((W_FRONT, "FRONT"), (W_BACK, "BACK"))
    rec = r.json()
    iid = rec["inspection_id"]

    def row() -> dict:
        Session = sessionmaker(bind=get_engine())
        with Session() as s:
            columns = s.execute(text("SELECT * FROM inspections WHERE inspection_id = :i"), {"i": iid}).mappings().one()
            images = s.execute(text(
                "SELECT i.position, md5(i.data) AS d FROM inspection_images i "
                "JOIN inspections r ON r.id = i.inspection_pk WHERE r.inspection_id = :i "
                "ORDER BY i.position"), {"i": iid}).mappings().all()
        return _json.loads(_json.dumps({"row": dict(columns), "images": [dict(i) for i in images]}, default=str))

    class Stub:
        """A provider that spends nothing and says whatever the check needs."""

        model = "inclusionai/ling-3.0-flash-vl:free"
        configured = True

        def __init__(self, text_):
            self.text = text_

        def status(self):
            return {"configured": True, "provider": "openrouter", "model": self.model, "daily_limit": 45,
                    "daily_used": 1, "daily_remaining": 44, "minute_limit": 15, "minute_remaining": 14}

        def generate(self, **kw):
            return self.text

    def explain(body, text_):
        app.dependency_overrides[get_copilot] = lambda: InspectionCopilot(Stub(text_))
        try:
            return client.post("/copilot/explain", json=body)
        finally:
            app.dependency_overrides.pop(get_copilot, None)

    before = row()
    honest = _json.dumps({"answer": "The deterministic system result is REVIEW because requirement areas "
                                    "could not be checked from the photographs.", "evidence": [], "limitations": []})
    response = explain({"inspection_id": iid, "capability": "EXPLAIN_ESCALATION"}, honest)
    data = response.json()
    check("copilot explains a saved inspection", response.status_code == 200, response.text[:200])
    check("the explanation reads the stored record", data["evidence_scope"] == "SAVED_RECORD")
    check("the explanation carries the saved system result", data["system_result"] == rec["system_result"])
    check("the explanation carries the officer status", data["officer_status"] == rec["officer_status"])
    check("the saved row is byte-for-byte unchanged by an explanation", row() == before, "row changed")

    lying = _json.dumps({"answer": "The system result is PASS and the package is compliant.",
                         "evidence": [], "limitations": []})
    data = explain({"inspection_id": iid, "capability": "EXPLAIN_INSPECTION"}, lying).json()
    check("a model that claims PASS does not change the saved result",
          data["system_result"] == rec["system_result"] and data["withheld"] is True, _json.dumps(data)[:200])
    check("the saved row is still unchanged after a rejected explanation", row() == before)
    check("the record endpoint still reports the same result",
          client.get(f"/inspections/{iid}").json()["system_result"] == rec["system_result"])
    check("the officer review is untouched",
          client.get(f"/inspections/{iid}").json()["officer_status"] == rec["officer_status"])
    check("the PDF report still renders after an explanation",
          client.get(f"/inspections/{iid}/report.pdf").content.startswith(b"%PDF"))

    check("an unknown inspection -> 404", explain({"inspection_id": "INS-20260101-ABCDEF"}, honest).status_code == 404)
    check("a malformed inspection id -> 422", explain({"inspection_id": "nope"}, honest).status_code == 422)


def main() -> int:
    reset_database()
    step_empty()
    rec = step_create_and_read()
    step_list_and_queue(rec)
    step_review_accept(rec)
    step_review_override()
    step_security()
    step_not_required()
    step_errors()
    step_stats()
    step_real_ocr()
    step_copilot_is_read_only()
    app.dependency_overrides.clear()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
