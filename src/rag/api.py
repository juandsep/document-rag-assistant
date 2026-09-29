"""FastAPI service for the document RAG assistant."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Document RAG Assistant", version="0.1.0")


class QueryRequest(BaseModel):
    """A business question plus how many passages to retrieve."""

    q: str = Field(min_length=1, description="Question to answer")
    top_k: int = Field(default=5, ge=1, le=50, description="Passages to retrieve")


class Source(BaseModel):
    """A retrieved passage backing part of the answer."""

    doc_id: str
    text: str
    score: float


class QueryResponse(BaseModel):
    """The generated answer and the sources it was built from."""

    answer: str
    sources: list[Source] = []


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe used by the container healthcheck."""
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
async def query(payload: QueryRequest) -> QueryResponse:
    """Answer `payload.q` from the indexed corpus, citing the sources.

    Placeholder: the retrieval chain lands in phase F3.
    """
    # TODO: retriever.get_retriever().query(payload.q, top_k=payload.top_k)
    #       -> prompt -> LLM -> QueryResponse(answer=..., sources=...)
    return QueryResponse(answer="This is a stub response.", sources=[])
