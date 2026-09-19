"""Grounded BIS question answering.

Retrieval remains deterministic and is performed by SearchEngine.
The LLM only receives the retrieved BIS context.

Milestone 17 — the answer can be written in English, Hindi or Telugu. The
language layer (``app/language.py``) sits AROUND this pipeline, never inside it:
it rewrites known non-English product and BIS terms into canonical English
before retrieval, and appends a language clause to the system prompt afterwards.
The knowledge base, the retrieval engine, its scoring and the evidence objects
are untouched — the language of interaction changes, the source of truth does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app import language as lang
from app.llm import LocalLLM
from app.retrieval import RetrievalResult, SearchEngine


SYSTEM_PROMPT = """You are the BIS Assistant for an evidence-backed Indian
Standards information system.

Rules:
1. Answer ONLY using the BIS context supplied by the application.
2. Do not use pretrained knowledge as evidence.
3. Do not invent standards, clauses, requirements, dates, numbers, fees,
   procedures, or legal claims.
4. If the supplied context is insufficient, say so clearly.
5. Do not make a final legal or enforcement decision.
6. Do not claim to verify, authenticate, or state the status of a specific
   physical item (for example a particular article's HUID, hallmark, licence, or
   BIS registration). Explain what the evidence says and point the user to the
   official BIS tool or page. Never output a HUID or similar identifier that is
   not present in the supplied context.
7. Keep the answer concise and directly address the user's question.
"""


@dataclass(frozen=True)
class GroundedAnswer:
    answer: str
    results: list[RetrievalResult]
    # Milestone 17: the language the answer is written in ("en" / "hi" / "te"),
    # after an explicit request or deterministic detection.
    language: str = lang.EN
    # The canonical English terms the query's non-English wording was mapped to
    # for retrieval. Empty when nothing needed rewriting.
    concepts: list[str] = field(default_factory=list)


def _build_context(results: list[RetrievalResult]) -> str:
    blocks: list[str] = []

    for index, result in enumerate(results, start=1):
        item = result.item

        blocks.append(
            f"""SOURCE {index}
ID: {item.id}
TITLE: {item.title}
CATEGORY: {item.category}
STANDARD: {item.standard_number or "N/A"}

CONTENT:
{item.content}

SOURCE ORGANIZATION: {item.source_organization}
DOCUMENT: {item.document_name or "N/A"}
REFERENCE: {item.reference or "N/A"}
VERIFICATION STATUS: {item.verification_status}
SOURCE URL: {item.source_url or "N/A"}
"""
        )

    return "\n---\n".join(blocks)


class BISQuestionAnswerer:
    """Deterministic retrieval followed by grounded local generation."""

    def __init__(
        self,
        search_engine: SearchEngine,
        llm: LocalLLM,
        retrieval_limit: int = 5,
    ) -> None:
        self.search_engine = search_engine
        self.llm = llm
        self.retrieval_limit = retrieval_limit

    def ask(self, question: str, language: str = lang.AUTO) -> GroundedAnswer:
        # The language to answer in. An explicit choice wins; "auto" detects the
        # script. This never affects which evidence is retrieved.
        answer_language = lang.resolve(question, language)

        # Retrieval sees known Hindi / Telugu terms rewritten to their canonical
        # English, because the retrieval normalizer is ASCII-only. Everything
        # else reaches retrieval exactly as the user typed it.
        normalized = lang.normalize_query(question)

        outcome = self.search_engine.search(
            normalized.query,
            limit=self.retrieval_limit,
        )

        # Retrieval abstention means the LLM receives no context.
        if outcome.abstained or not outcome.results:
            return GroundedAnswer(
                answer=lang.insufficient(answer_language),
                results=[],
                language=answer_language,
                concepts=normalized.concepts,
            )

        context = _build_context(outcome.results)

        # The model sees the question exactly as the user wrote it — the
        # rewritten form is for retrieval only.
        user_prompt = f"""Answer the user's question using ONLY the BIS evidence
below.

USER QUESTION:
{question}

BIS EVIDENCE:
{context}

Give a concise answer grounded in the supplied evidence.
"""

        answer = self.llm.generate(
            # Adds nothing for English, so English behaviour is unchanged.
            system_prompt=lang.apply(SYSTEM_PROMPT, answer_language),
            user_prompt=user_prompt,
            temperature=0.1,
        )

        return GroundedAnswer(
            answer=answer,
            results=outcome.results,
            language=answer_language,
            concepts=normalized.concepts,
        )
