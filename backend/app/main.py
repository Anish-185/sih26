"""FastAPI application entry point.

Exposes:
  - GET /health         liveness check
  - GET/POST /search    deterministic lexical retrieval over the BIS knowledge base

The LLM / RAG layer is added in a later phase.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as search_router
from app.inspection_api import router as inspection_router
from app.records_api import router as records_router

app = FastAPI(
    title="BIS Assistant API",
    description="Evidence-backed AI assistant for Indian Standards and BIS services.",
    version="0.2.0",
)

# The frontend (added in a later phase) will run on a different port during
# development, so allow local origins to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness check. Returns 200 with a small JSON body when the API is up."""
    return {"status": "ok", "service": "bis-assistant-api", "version": "0.2.0"}


app.include_router(search_router)
app.include_router(inspection_router)
app.include_router(records_router)
