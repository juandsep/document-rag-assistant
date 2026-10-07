"""Integration tests for the RAG API, wired to fakes instead of services."""

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
        monkeypatch.setattr(chain, "ollama_chat", lambda messages: reply)

    return wire


def test_health_reports_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_answers_with_its_sources(wired):
    wired(FakeRetriever())
    response = client.post("/query", json={"q": "What is the return policy?"})

    assert response.status_code == 200
    assert response.json() == {
        "answer": "You have 30 days [1].",
        "sources": [
            {
                "doc_id": "refunds.txt",
                "text": "Refunds are accepted for 30 days.",
                "score": 0.87,
            }
        ],
        "status": "ok",
    }


def test_query_maps_a_vector_store_outage_to_503(wired):
    wired(FakeRetriever(error=ConnectionError("down")))
    assert client.post("/query", json={"q": "hi"}).status_code == 503


def test_query_rejects_an_empty_question():
    assert client.post("/query", json={"q": ""}).status_code == 422


def test_query_rejects_an_out_of_range_top_k():
    assert client.post("/query", json={"q": "hi", "top_k": 0}).status_code == 422
