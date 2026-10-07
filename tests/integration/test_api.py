"""Integration tests for the RAG API, wired to fakes instead of services."""

import json

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

    assert response.status_code == 200
    assert response.json() == {
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
