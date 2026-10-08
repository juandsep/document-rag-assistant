"""Unit tests for the RAG chain, with a fake retriever and a fake model."""

import json

import pytest

from rag import chain
from rag.api import load_secrets
from rag.retrievers import Retrieved

PASSAGES = [
    Retrieved("refunds.txt", "Refunds are accepted for 30 days.", 0.87),
    Retrieved("shipping.txt", "Shipping takes 3 to 5 days.", 0.84),
]


class FakeRetriever:
    def __init__(self, passages=PASSAGES, error=None):
        self.passages, self.error = passages, error

    def query(self, text, top_k=5):
        if self.error:
            raise self.error
        return self.passages[:top_k]


def test_answer_returns_only_the_cited_passages_and_prompts_from_them():
    seen = {}

    def chat(messages):
        seen["messages"] = messages
        return chain.Reply(
            "You have 30 days [1].", prompt_tokens=120, completion_tokens=9
        )

    result = chain.answer(
        "How long for a refund?", retriever=FakeRetriever(), chat=chat
    )

    assert result.status == "ok"
    assert result.text == "You have 30 days [1]."
    assert (result.prompt_tokens, result.completion_tokens) == (120, 9)
    assert len(result.passages) == 2 and result.retrieval_ms >= 0
    assert [s.doc_id for s in result.sources] == ["refunds.txt"]
    user = seen["messages"][1]["content"]
    assert "[1] (refunds.txt)" in user and "[2] (shipping.txt)" in user
    assert "How long for a refund?" in user
    assert user.endswith("Write the whole reply in English.")


def test_answer_reads_full_width_citations():
    result = chain.answer(
        "q", retriever=FakeRetriever(), chat=lambda m: chain.Reply("No【1】.")
    )
    assert result.text == "No[1]."
    assert [s.doc_id for s in result.sources] == ["refunds.txt"]


def test_answer_without_citations_keeps_every_passage():
    result = chain.answer(
        "q", retriever=FakeRetriever(), chat=lambda m: chain.Reply("30 days.")
    )
    assert len(result.sources) == 2


def test_answer_reports_insufficient_context_instead_of_improvising():
    reply = f"{chain.NO_CONTEXT}: Los documentos no lo cubren."
    result = chain.answer(
        "¿Quién es el CEO?",
        retriever=FakeRetriever(),
        chat=lambda m: chain.Reply(reply),
    )
    assert result.status == "insufficient_context"
    assert result.text == "Los documentos no lo cubren."
    assert result.sources == []


def test_a_bare_no_context_reply_falls_back_to_the_default_message():
    result = chain.answer(
        "q", retriever=FakeRetriever(), chat=lambda m: chain.Reply(chain.NO_CONTEXT)
    )
    assert result.text == chain.INSUFFICIENT


def test_answer_with_no_passages_never_calls_the_model():
    def chat(messages):
        raise AssertionError("the model must not be called without passages")

    result = chain.answer("q", retriever=FakeRetriever(passages=[]), chat=chat)
    assert result.status == "insufficient_context"


def test_answer_keeps_the_evidence_when_the_model_is_down():
    def chat(messages):
        raise TimeoutError("timed out")

    result = chain.answer("q", retriever=FakeRetriever(), chat=chat)
    assert result.status == "llm_unavailable"
    assert len(result.sources) == 2


def test_answer_raises_retrieval_error_when_the_store_is_down():
    with pytest.raises(chain.RetrievalError):
        chain.answer("q", retriever=FakeRetriever(error=ConnectionError("down")))


def test_load_secrets_fills_missing_keys_and_skips_placeholders(monkeypatch):
    class FakeSSM:
        def get_parameter(self, Name, WithDecryption):
            assert (Name, WithDecryption) == ("/rag/app", True)
            value = {"QDRANT_API_KEY": "q", "OLLAMA_API_KEY": "REPLACE_ME", "X": "kept"}
            return {"Parameter": {"Value": json.dumps(value)}}

    monkeypatch.setenv("APP_SECRET_PARAMETER", "/rag/app")
    monkeypatch.setenv("X", "from-env")
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    load_secrets(FakeSSM())

    import os

    assert os.environ["QDRANT_API_KEY"] == "q"
    assert "OLLAMA_API_KEY" not in os.environ
    assert os.environ["X"] == "from-env"


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("How long is the warranty on a laptop?", "English"),
        ("Do you ship to Argentina?", "English"),
        ("¿Cuánto tarda el envío?", "Spanish"),
        ("Puedo pagar en cuotas con débito", "Spanish"),
        ("Quien es el gerente", "Spanish"),
    ],
)
def test_question_language(question, language):
    assert chain.question_language(question) == language


def _streamer(*pieces, error=None):
    def chat_stream(messages):
        yield from pieces
        if error:
            raise error
        yield chain.Reply("".join(pieces), 50, 7)

    return chat_stream


def test_stream_answer_yields_the_text_then_the_answer():
    items = list(
        chain.stream_answer(
            "q", PASSAGES, 12.0, _streamer("You have ", "30 days【1】.")
        )
    )

    assert items[:-1] == ["You have ", "30 days[1]."]
    final = items[-1]
    assert final.text == "You have 30 days[1]." and final.status == "ok"
    assert [s.doc_id for s in final.sources] == ["refunds.txt"]
    assert (final.retrieval_ms, final.prompt_tokens) == (12.0, 50)


def test_stream_answer_never_shows_a_refusal_marker():
    items = list(
        chain.stream_answer(
            "q", PASSAGES, 0, _streamer("NO_", "CONTEXT: ", "Not covered.")
        )
    )

    assert len(items) == 1
    assert items[0].status == "insufficient_context" and items[0].text == "Not covered."


def test_stream_answer_keeps_the_passages_when_the_model_fails():
    items = list(
        chain.stream_answer(
            "q", PASSAGES, 0, _streamer("You ", error=TimeoutError("slow"))
        )
    )

    assert items[0] == "You "
    assert items[-1].status == "llm_unavailable" and len(items[-1].sources) == 2


def test_stream_answer_without_passages_refuses_at_once():
    def never(messages):
        raise AssertionError("no passages, no model call")

    [final] = chain.stream_answer("q", [], 0, never)
    assert final.status == "insufficient_context"
