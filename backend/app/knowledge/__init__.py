"""BIS knowledge base: schema and loader.

The knowledge base is the source of truth for BIS information. Every item must be
traceable to an official source (or be clearly marked as a non-official sample).

Phase 2A only defines the structure, validation, and a loader. Retrieval, RAG, and
the LLM come later and are expected to depend on this package.
"""

from app.knowledge.schema import (
    Category,
    KnowledgeItem,
    SourceAuthority,
    VerificationStatus,
)
from app.knowledge.loader import LoadResult, LoadError, load_knowledge_base

__all__ = [
    "Category",
    "KnowledgeItem",
    "SourceAuthority",
    "VerificationStatus",
    "LoadResult",
    "LoadError",
    "load_knowledge_base",
]
