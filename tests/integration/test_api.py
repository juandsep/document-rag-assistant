"""Integration tests for the RAG API (no external services required)."""

from fastapi.testclient import TestClient

from rag.api import app

client = TestClient(app)


def test_health_reports_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_returns_an_answer_and_a_sources_list():
    response = client.post("/query", json={"q": "What is the return policy?"})
    assert response.status_code == 200

    payload = response.json()
    assert isinstance(payload["answer"], str)
    assert isinstance(payload["sources"], list)


def test_query_rejects_an_empty_question():
    assert client.post("/query", json={"q": ""}).status_code == 422


def test_query_rejects_an_out_of_range_top_k():
    assert client.post("/query", json={"q": "hi", "top_k": 0}).status_code == 422
