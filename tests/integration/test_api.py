"""Integration tests for the RAG API, wired to fakes instead of services."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from rag import api, chain
from rag.retrievers import Retrieved

client = TestClient(api.app)


class FakeRetriever:
    def __init__(self, error=None):
        self.error = error

    def query(self, text, top_k=5):
        if self.error:
            raise self.error
        return [Retrieved("refunds.txt", "Refunds are accepted for 30 days.", 0.87)]


@pytest.fixture
def wired(monkeypatch):
    def wire(retriever, reply="You have 30 days [1]."):
        monkeypatch.setattr(api, "_retriever", lambda: retriever)
        monkeypatch.setattr(
            chain, "ollama_chat", lambda messages: chain.Reply(reply, 100, 8)
        )

    return wire


def test_health_reports_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_answers_with_its_sources_and_logs_one_line(wired, capsys):
    wired(FakeRetriever())
    response = client.post("/query", json={"q": "What is the return policy?"})

    [line] = [ln for ln in capsys.readouterr().out.splitlines() if "rag_query" in ln]
    event = json.loads(line)
    assert event["status"] == "ok" and event["top_score"] == 0.87
    assert (event["prompt_tokens"], event["completion_tokens"]) == (100, 8)
    assert {"latency_ms", "retrieval_ms", "generation_ms", "model"} <= event.keys()
    assert event["query_id"] == response.json()["query_id"]

    assert response.status_code == 200
    body = response.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body.pop("query_id"))
    assert body == {
        "answer": "You have 30 days [1].",
        "sources": [
            {
                "doc_id": "refunds.txt",
                "text": "Refunds are accepted for 30 days.",
                "score": 0.87,
                "page": None,
            }
        ],
        "status": "ok",
    }


def test_query_maps_a_vector_store_outage_to_503(wired, capsys):
    wired(FakeRetriever(error=ConnectionError("down")))
    assert client.post("/query", json={"q": "hi"}).status_code == 503
    assert '"status": "retrieval_error"' in capsys.readouterr().out


def test_query_rejects_an_empty_question():
    assert client.post("/query", json={"q": ""}).status_code == 422


def test_query_rejects_an_out_of_range_top_k():
    assert client.post("/query", json={"q": "hi", "top_k": 0}).status_code == 422


def test_query_demands_the_api_key_when_one_is_set(wired, monkeypatch):
    wired(FakeRetriever())
    monkeypatch.setenv("API_KEY", "s3cret")

    assert client.post("/query", json={"q": "hi"}).status_code == 401
    wrong = {"X-API-Key": "nope"}
    assert client.post("/query", json={"q": "hi"}, headers=wrong).status_code == 401
    right = {"X-API-Key": "s3cret"}
    assert client.post("/query", json={"q": "hi"}, headers=right).status_code == 200
    assert client.get("/health").status_code == 200


def test_a_deployed_function_without_a_key_refuses(wired, monkeypatch):
    wired(FakeRetriever())
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("APP_SECRET_PARAMETER", "/rag/app")
    assert client.post("/query", json={"q": "hi"}).status_code == 503


def test_query_is_rate_limited_per_client(wired, monkeypatch):
    wired(FakeRetriever())
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setattr(api, "_recent", {})
    first = {"X-Forwarded-For": "203.0.113.7"}
    other = {"X-Forwarded-For": "198.51.100.9"}

    codes = [
        client.post("/query", json={"q": "hi"}, headers=first).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    limited = client.post("/query", json={"q": "hi"}, headers=first)
    assert int(limited.headers["Retry-After"]) <= 61
    assert client.post("/query", json={"q": "hi"}, headers=other).status_code == 200


def test_feedback_is_logged_against_its_query(wired, capsys):
    wired(FakeRetriever())
    query_id = client.post("/query", json={"q": "hi"}).json()["query_id"]
    capsys.readouterr()

    response = client.post("/feedback", json={"query_id": query_id, "rating": "down"})

    assert response.status_code == 204
    [line] = [ln for ln in capsys.readouterr().out.splitlines() if "rag_feedback" in ln]
    assert json.loads(line) == {
        "event": "rag_feedback",
        "query_id": query_id,
        "rating": "down",
    }


@pytest.mark.parametrize(
    "payload",
    [{"query_id": "x" * 32, "rating": "up"}, {"query_id": "a" * 32, "rating": "meh"}],
)
def test_feedback_rejects_bad_ids_and_ratings(payload):
    assert client.post("/feedback", json=payload).status_code == 422


def test_feedback_needs_the_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    payload = {"query_id": "a" * 32, "rating": "up"}
    assert client.post("/feedback", json=payload).status_code == 401
