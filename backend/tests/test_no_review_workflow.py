"""Checks that the human review ("officer") workflow AND the automatic
PASS / FAIL / REVIEW compliance verdict are both gone.

What was removed: the separate human decision layer (an officer status, an
officer decision, an officer result, an officer note, the review queue and its
API/UI/report sections) AND, in the final hardening pass, the deterministic
legal-compliance engine itself (``app.compliance`` / ``app.package_label``, the
``bis_result`` / ``legal_metrology_result`` / ``system_result`` columns and
API fields, the evidence graph's RULE / SYSTEM_RESULT nodes). MetrIQ now
reports evidence and verified knowledge, and whether it could establish that
evidence chain (``escalation_required`` / ``escalation_reasons``) — never a
legal or compliance judgment.

This runner is a structural guard: it greps the shipped source (backend app,
frontend src, docs) for the removed vocabulary, walks the live FastAPI route
table, and checks the deterministic evidence pipeline still works end to end.

No database, no LM Studio, no OpenRouter.

Plain Python, no test framework (matches the other runners). Run:

    cd backend
    ./.venv/bin/python tests/test_no_review_workflow.py

Exit 0 = all checks passed, 1 = something failed.
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from app.escalation import REASONS  # noqa: E402
from app.main import app  # noqa: E402

PASS = 0
FAIL_COUNT = 0
BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
FRONTEND = REPO / "frontend" / "src"

# Identifiers and phrases the removed workflow owned. "officer" on its own is not
# enough: official BIS text quoted in the knowledge base mentions "BIS
# surveillance officers", and that quote must stay verbatim.
FORBIDDEN = re.compile(
    r"officer_status|officer_decision|officer_result|officer_note|officer_review"
    r"|OfficerStatus|OfficerDecision|OfficerReviewPanel|ReviewQueueView|reviewInspection"
    r"|ACCEPT_SYSTEM_RESULT|NOT_REQUIRED|IN_REVIEW"
    r"|officer (review|decision|result|note|status|queue|verification|confirmation)"
    r"|final officer|officer final",
    re.IGNORECASE,
)


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL_COUNT
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def sources(root: Path, *suffixes: str) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.suffix in suffixes and p.is_file()
                  and "node_modules" not in p.parts and "__pycache__" not in p.parts)


# Prose that documents the REMOVAL is not the workflow coming back — the milestone
# log has to be able to say what M22 took out. Checked per paragraph, because such
# a list spans several lines.
_REMOVAL_NOTE = re.compile(r"\bM22\b|\bremoved\b|\bno longer\b|\bis gone\b", re.IGNORECASE)


def offenders(paths, prose: bool = False) -> list[str]:
    out = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        skip: set[int] = set()
        if prose:
            line_no = 1
            for para in text.split("\n\n"):
                lines = para.count("\n") + 1
                if _REMOVAL_NOTE.search(para):
                    skip.update(range(line_no, line_no + lines))
                line_no += lines + 1
        for i, line in enumerate(text.splitlines(), 1):
            if i not in skip and FORBIDDEN.search(line) and not _REMOVAL_NOTE.search(line):
                out.append(f"{p.relative_to(REPO)}:{i}: {line.strip()[:100]}")
    return out


# ------------------------------------------------------------------ A-D: removed


def step_backend_source() -> None:
    print("\nA. the backend carries no review workflow")
    bad = offenders(sources(BACKEND / "app", ".py"))
    check("no officer/review-workflow identifier or phrase in backend/app", not bad, "; ".join(bad[:4]))
    check("app.records exposes no review functions",
          not any(hasattr(__import__("app.records", fromlist=["x"]), n)
                  for n in ("apply_review", "ReviewAction", "ReviewError", "final_result",
                            "OFFICER_STATUSES", "OFFICER_DECISIONS", "OFFICER_TRANSITIONS", "NOTE_MAX")))
    from app.records import InspectionRecord
    columns = {c.name for c in InspectionRecord.__table__.columns}
    check("the mapped inspection row has no officer / review column",
          not [c for c in columns if "officer" in c or c.startswith("review_")], str(sorted(columns)))
    check("the mapped inspection row has no compliance-verdict column",
          not {"system_result", "bis_result", "legal_metrology_result", "system_reasons"} & columns, str(sorted(columns)))
    check("but it still stores the resolution assessment",
          {"escalation_required", "escalation_reasons"} <= columns)
    from app.records_api import InspectionRecordOut, InspectionStatsOut
    fields = set(InspectionRecordOut.model_fields) | set(InspectionStatsOut.model_fields)
    check("the API response models carry no officer / decision field",
          not [f for f in fields if "officer" in f or f in ("decisions", "final_result")], str(sorted(fields)))
    check("the API response models carry no compliance-verdict field",
          not {"system_result", "bis_result", "legal_metrology_result", "system_reasons"} & fields, str(sorted(fields)))


def step_no_review_api() -> None:
    print("\nB. no review endpoint exists")
    # The OpenAPI schema is the authoritative route table (routers are included lazily).
    spec = app.openapi()["paths"]
    paths = sorted(spec)
    check("no route path mentions a review", not [p for p in paths if "review" in p.lower()], str(paths))
    check("POST /inspections/{id}/review is not registered",
          "post" not in spec.get("/inspections/{inspection_id}/review", {}))
    check("the endpoints the product needs are all still registered",
          {"/search", "/ask", "/product-standard", "/certification-guidance", "/laboratory-search",
           "/product-context", "/inspection/analyze", "/inspection/ocr", "/inspection/coverage",
           "/inspections", "/inspections/{inspection_id}",
           "/inspections/{inspection_id}/report.pdf", "/copilot/explain", "/copilot/status"} <= set(paths),
          str(paths))


def step_no_review_ui() -> None:
    print("\nC. no review workflow in the frontend")
    files = sources(FRONTEND, ".ts", ".tsx")
    bad = offenders(files)
    check("no officer/review-workflow identifier or phrase in frontend/src", not bad, "; ".join(bad[:4]))
    names = {p.name for p in files}
    check("the review queue screen is gone", "ReviewQueueView.tsx" not in names and "ReviewView.tsx" not in names)
    check("the saved-inspection screen is still there", "RecordView.tsx" in names)
    main = (FRONTEND / "main.tsx").read_text()
    check("no /review route is registered", '"review"' not in main and "ReviewQueueView" not in main)
    check("history and the saved record are still routed",
          '"history"' in main and '"history/:inspectionId"' in main)
    nav = (FRONTEND / "components" / "layout.tsx").read_text()
    check("the navigation has no Review entry", '{ to: "/review"' not in nav)
    check("the navigation still has Inspection, Standards, Certification, Laboratories, Hallmarking, History",
          all(f'to: "/{p}"' in nav for p in
              ("inspection", "standards", "certification", "laboratories", "hallmarking", "history")))


def step_no_officer_results() -> None:
    print("\nD. no officer PASS / FAIL / REVIEW anywhere")
    docs = [REPO / "README.md", REPO / "CLAUDE.md", REPO / "frontend" / "README.md"]
    bad = offenders([d for d in docs if d.exists()], prose=True)
    check("the documentation describes no review workflow", not bad, "; ".join(bad[:4]))
    body = "\n".join(p.read_text(encoding="utf-8") for p in sources(BACKEND / "app", ".py"))
    check("no code path produces a result attributed to a human",
          not re.search(r"(officer|reviewer|inspector)[ _-]?(result|verdict|decision)", body, re.I))


# ------------------------------------------------------------------ E-G: kept


def step_no_compliance_verdict() -> None:
    print("\nE/F/G. no automatic PASS / FAIL / REVIEW compliance verdict remains")
    import importlib
    import sys as _sys

    check("app.compliance no longer exists", "app.compliance" not in _sys.modules)
    for name in ("app.compliance", "app.package_label"):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            ok = True
        else:
            ok = False
        check(f"{name} cannot be imported", ok)
    check("escalation no longer produces a combined system_result",
          "system_result" not in REASONS and "SYSTEM_RESULT_REVIEW" not in REASONS
          and "REQUIREMENT_NOT_CHECKABLE" not in REASONS)
    check("escalation reasons are all evidence-only, no verdict-combination codes",
          set(REASONS) == {"PIPELINE_ERROR", "IMAGES_UNREADABLE", "IMAGE_QUALITY_LOW", "PRODUCT_NOT_IDENTIFIED",
                           "MULTIPLE_CANDIDATES", "PRODUCT_NOT_CONFIRMED", "NO_VERIFIED_STANDARD",
                           "HALLMARK_NOT_VERIFIABLE", "CONFLICTING_DECLARATIONS", "OCR_UNCERTAIN",
                           "MISSING_EVIDENCE"}, str(sorted(REASONS)))
    from app.inspection import EscalationOut, InspectionAnalysisOut, PipelineStagesOut
    check("the pipeline stage summary has no human-review stage and no compliance stage",
          "officer_review" not in PipelineStagesOut.model_fields
          and not {"compliance", "package_label"} & set(PipelineStagesOut.model_fields)
          and {"ocr", "declaration_extraction", "product_identification"} <= set(PipelineStagesOut.model_fields))
    check("the escalation response carries no combined system_result",
          "system_result" not in EscalationOut.model_fields and "required" in EscalationOut.model_fields)
    check("InspectionAnalysisOut carries no compliance / package_label section",
          not {"compliance", "package_label"} & set(InspectionAnalysisOut.model_fields))
    from app.evidence_graph import EDGE_TYPES, NODE_TYPES
    check("the evidence graph has no RULE / SYSTEM_RESULT node type",
          not {"RULE", "SYSTEM_RESULT"} & set(NODE_TYPES), str(NODE_TYPES))
    check("the evidence graph has no CHECKED_BY / RESULTED_IN edge type",
          not {"CHECKED_BY", "RESULTED_IN"} & set(EDGE_TYPES), str(EDGE_TYPES))


def main() -> int:
    step_backend_source()
    step_no_review_api()
    step_no_review_ui()
    step_no_officer_results()
    step_no_compliance_verdict()
    print(f"\n{PASS} passed, {FAIL_COUNT} failed")
    return 1 if FAIL_COUNT else 0


if __name__ == "__main__":
    sys.exit(main())
