"""Milestone 22 — HTTP layer for the evidence graph.

    POST /evidence-graph   -> EvidenceGraphOut

Strict body, exactly ONE evidence source (anything else is 422):

    {"inspection_id": "INS-…"}   SERVER-DERIVED — the saved analysis is read from
                                 the database and projected. Read-only: the
                                 session is rolled back and never committed.
    {"analysis": {...}}          the analysis currently on screen, exactly as
                                 /inspection/analyze produced it. Client-echoed —
                                 the SAME trust model the copilot's live path has
                                 always had, and no more: ``InspectionAnalysisOut``
                                 IS the whitelist, so an unexpected field is
                                 dropped before it can reach the projection and a
                                 malformed one is a 422.
    {"product_context": {...}}   MetrIQ's own product context, exactly as
                                 POST /product-context returned it (whitelisted
                                 the same way).

A client cannot create graph nodes or edges: the request carries no node, edge,
label or status field at all. Everything in the response is projected from the
evidence MetrIQ itself produced, and the graph is read-only — no endpoint writes
one, and nothing downstream reads one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.evidence_graph import EvidenceGraphOut, build_from_analysis, build_from_context, graph_out
from app.inspection import InspectionAnalysisOut
from app.product_context import ProductContextOut
from app.records import INSPECTION_ID_PATTERN, get_inspection

router = APIRouter(tags=["evidence-graph"])

_DB_UNAVAILABLE = "The inspection database is unavailable. Check that PostgreSQL is running and migrated."


class GraphRequest(BaseModel):
    """Strict: exactly one evidence source, and no field that could carry a node or an edge."""

    model_config = ConfigDict(extra="forbid")

    inspection_id: str | None = Field(default=None, description="A saved inspection to project.")
    analysis: InspectionAnalysisOut | None = Field(
        default=None, description="The analysis currently on screen, exactly as /inspection/analyze returned it."
    )
    product_context: ProductContextOut | None = Field(
        default=None, description="A product context, exactly as POST /product-context returned it."
    )

    def chosen(self) -> str:
        given = [name for name in ("inspection_id", "analysis", "product_context") if getattr(self, name)]
        if len(given) != 1:
            raise HTTPException(
                status_code=422,
                detail="Send exactly one of inspection_id, analysis or product_context.",
            )
        return given[0]


@router.post("/evidence-graph", response_model=EvidenceGraphOut)
def evidence_graph(body: GraphRequest, session: Session = Depends(get_session)) -> EvidenceGraphOut:
    """Project existing evidence onto a graph. Deterministic, read-only, no model."""
    source = body.chosen()

    if source == "product_context":
        return graph_out(build_from_context(body.product_context.model_dump(mode="json")))

    if source == "analysis":
        return graph_out(build_from_analysis(body.analysis.model_dump(mode="json")))

    if not INSPECTION_ID_PATTERN.match(body.inspection_id or ""):
        raise HTTPException(status_code=422,
                            detail=f"'{body.inspection_id}' is not a valid inspection id (INS-YYYYMMDD-XXXXXX).")
    try:
        record = get_inspection(session, body.inspection_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Inspection {body.inspection_id} was not found.")
        analysis = dict(record.analysis)
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from exc
    finally:
        session.rollback()  # read-only: nothing is ever persisted by building a graph
    return graph_out(build_from_analysis(analysis))
