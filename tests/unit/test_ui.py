"""Tests for the Streamlit UI, run headless with Streamlit's AppTest."""

from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

UI = str(Path(__file__).resolve().parents[2] / "src" / "rag" / "ui.py")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.fixture
def api(monkeypatch):
    calls = []

    def respond_with(payload):
        def post(url, json, headers, timeout):
            calls.append({"url": url, "json": json, "headers": headers})
            return FakeResponse(payload)

        monkeypatch.setattr(requests, "post", post)
        return calls

    return respond_with


def ask(question):
    app = AppTest.from_file(UI, default_timeout=30)
    app.run()
    app.text_input[0].input(question)
    app.button[0].click()
    return app.run()


def test_an_answer_shows_with_its_cited_sources(api, monkeypatch):
    monkeypatch.setenv("RAG_API_KEY", "k")
    calls = api(
        {
            "answer": "Hasta 30 días [1].",
            "status": "ok",
            "sources": [
                {"doc_id": "terminos.pdf", "text": "…", "score": 0.87, "page": 2}
            ],
        }
    )

    app = ask("¿Cuántos días tengo?")

    assert "Hasta 30 días [1]." in [m.value for m in app.markdown]
    assert app.expander[0].label == "terminos.pdf, page 2 · score 0.870"
    assert calls[0]["json"] == {"q": "¿Cuántos días tengo?", "top_k": 5}
    assert calls[0]["headers"] == {"X-API-Key": "k"}
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Sources cited"] == "1" and metrics["Status"] == "ok"


def test_a_refusal_shows_as_a_warning_without_sources(api):
    api(
        {
            "answer": "Los documentos no lo cubren.",
            "status": "insufficient_context",
            "sources": [],
        }
    )

    app = ask("¿Quién es el CEO?")

    assert [w.value for w in app.warning] == ["Los documentos no lo cubren."]
    assert not app.expander


def test_an_api_failure_shows_an_error(monkeypatch):
    def post(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", post)

    app = ask("hi")

    assert "refused" in app.error[0].value


def test_the_page_explains_itself_before_any_question():
    app = AppTest.from_file(UI, default_timeout=30)
    app.run()

    assert [tab.label for tab in app.tabs] == ["Ask", "How it works", "Demo corpus"]
    assert app.sidebar.header[0].value == "About"
    corpus = app.table[1].value
    assert len(corpus) == 6 and set(corpus["Language"]) == {"Spanish", "English"}
