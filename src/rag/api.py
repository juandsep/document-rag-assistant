"""FastAPI service for the document RAG assistant."""

from __future__ import annotations

import functools
import hmac
import json
import os
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
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
    yield


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate /query behind the `API_KEY` secret when one is configured.

    The Function URL is public so a browser-hosted UI can call it; the key
    keeps strangers from spending model time. Local runs without `API_KEY`
    stay open, but a deployed function without one refuses rather than
    serving the world.
    """
    expected = os.getenv("API_KEY")
    if not expected:
        if os.getenv("APP_SECRET_PARAMETER"):
            raise HTTPException(503, "The API key is not configured.")
        return
    if not (x_api_key and hmac.compare_digest(x_api_key, expected)):
        raise HTTPException(401, "Missing or wrong X-API-Key header.")


# ponytail: per-process memory. With 2 reserved Lambda executions the real
# ceiling is up to twice the limit, and idle client entries are only pruned
# when that client calls again; a shared store (DynamoDB) would make it exact.
_recent: dict[str, deque[float]] = {}


def rate_limit(request: Request) -> None:
    """Allow `RATE_LIMIT_PER_MINUTE` queries per client IP (0 disables it).

    The Streamlit demo reaches the API from its host's address, so this also
    caps the public demo as a whole; the UI adds a per-visitor limit on top.
    """
    limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
    if limit <= 0:
        return
    forwarded = request.headers.get("x-forwarded-for", "")
    client = forwarded.split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    now = time.monotonic()
    calls = _recent.setdefault(client, deque())
    while calls and now - calls[0] >= 60:
        calls.popleft()
    if len(calls) >= limit:
        monitoring.log_query(status="rate_limited")
        retry = int(60 - (now - calls[0])) + 1
        raise HTTPException(
            429,
            "Too many questions; try again in a minute.",
            headers={"Retry-After": str(retry)},
        )
    calls.append(now)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


@functools.cache
def _retriever() -> Retriever:
    # One client per process, reused across requests.
    return get_retriever()


app = FastAPI(title="Document RAG Assistant", version="1.1.0", lifespan=lifespan)


class QueryRequest(BaseModel):
    """A business question plus how many passages to retrieve."""

    q: str = Field(min_length=1, description="Question to answer")
    top_k: int = Field(default=5, ge=1, le=50, description="Passages to retrieve")


class Source(BaseModel):
    """A retrieved passage backing part of the answer."""

    doc_id: str
    text: str
    score: float
    page: int | None = None


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


@app.post(
    "/query",
    response_model=QueryResponse,
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
)
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
            Source(doc_id=s.doc_id, text=s.text, score=s.score, page=s.page)
            for s in result.sources
        ],
        status=result.status,
    )
