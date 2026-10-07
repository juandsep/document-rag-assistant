"""FastAPI service for the document RAG assistant."""

from __future__ import annotations

import functools
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from rag import chain, monitoring
from rag.retrievers import Retriever, get_retriever


def load_secrets(ssm: Any = None) -> None:
    """Copy the keys of the `APP_SECRET_PARAMETER` SecureString into the env.

    Only on Lambda, where the variable is set; local runs read `.env`. Values
    already in the environment and unfilled placeholders are left alone.
    """
    name = os.getenv("APP_SECRET_PARAMETER")
    if not name:
        return
    if ssm is None:
        import boto3

        ssm = boto3.client("ssm")
    value = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    for key, secret in json.loads(value).items():
        if secret and secret != "REPLACE_ME":
            os.environ.setdefault(key, secret)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    load_secrets()
    # Importing qdrant_client takes ~2.5 s. Paying it here, before /health
    # answers and Lambda routes traffic, keeps it off the first query.
    try:
        getattr(_retriever(), "client", None)
    except Exception as exc:  # noqa: BLE001 - a missing config fails on /query
        print(f"retriever warm-up skipped: {exc!r}", flush=True)
    yield


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


@functools.cache
def _retriever() -> Retriever:
    # One client per process, reused across requests.
    return get_retriever()


app = FastAPI(title="Document RAG Assistant", version="0.1.0", lifespan=lifespan)


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
    status: str = Field(
        default="ok",
        description="ok | insufficient_context | llm_unavailable",
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe used by the container healthcheck."""
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(payload: QueryRequest) -> QueryResponse:
    """Answer `payload.q` from the indexed corpus, citing the sources.

    A sync handler on purpose: retrieval and generation block on HTTP, so
    FastAPI runs it in its threadpool instead of stalling the event loop.
    """
    started = time.perf_counter()
    try:
        result = chain.answer(
            payload.q,
            top_k=payload.top_k,
            retriever=_retriever(),
            chat=chain.ollama_chat,
        )
    except chain.RetrievalError as exc:
        monitoring.log_query(status="retrieval_error", latency_ms=_ms(started))
        # Answering without retrieval would produce uncited claims.
        raise HTTPException(503, "The vector store is unavailable.") from exc
    monitoring.log_query(
        status=result.status,
        latency_ms=_ms(started),
        retrieval_ms=round(result.retrieval_ms, 1),
        generation_ms=round(result.generation_ms, 1),
        top_k=payload.top_k,
        top_score=round(max((p.score for p in result.passages), default=0.0), 4),
        passages=len(result.passages),
        sources=len(result.sources),
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
    )
    return QueryResponse(
        answer=result.text,
        sources=[
            Source(doc_id=s.doc_id, text=s.text, score=s.score) for s in result.sources
        ],
        status=result.status,
    )
