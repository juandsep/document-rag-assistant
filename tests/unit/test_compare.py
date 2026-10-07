"""Unit tests for the RAG-vs-baseline scoring."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "compare", Path(__file__).resolve().parents[2] / "scripts" / "compare.py"
)
compare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare)

ANSWERABLE = {"q": "Refund window?", "relevant": ["a.txt"], "answer": "30 days."}
UNANSWERABLE = {"q": "Who is the CEO?", "relevant": [], "answer": ""}


def test_unanswerable_questions_need_no_judge():
    assert compare.verdict(UNANSWERABLE, "", refused=True) == "refused"
    assert compare.verdict(UNANSWERABLE, "Jane Doe.", refused=False) == "hallucinated"


def test_answerable_questions_go_to_the_judge_unless_refused(monkeypatch):
    monkeypatch.setattr(compare, "judge", lambda q, ref, ans: "correct")
    assert compare.verdict(ANSWERABLE, "30 days.", refused=False) == "correct"
    assert compare.verdict(ANSWERABLE, "", refused=True) == "refused"


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("Correct.", "correct"),
        ("INCORRECT", "incorrect"),
        ("refused", "refused"),
        ("?", "incorrect"),
    ],
)
def test_judge_reads_the_verdict_word(monkeypatch, reply, expected):
    monkeypatch.setattr(
        compare.chain, "ollama_chat", lambda messages: compare.chain.Reply(reply)
    )
    assert compare.judge("q", "ref", "ans") == expected


def test_summarize_rates():
    rows = [
        {"answerable": True, "verdict": "correct", "ms": 1.0, "tokens": 10},
        {"answerable": True, "verdict": "refused", "ms": 2.0, "tokens": 10},
        {"answerable": False, "verdict": "hallucinated", "ms": 3.0, "tokens": 10},
        {"answerable": False, "verdict": "refused", "ms": 4.0, "tokens": 10},
    ]
    summary = compare.summarize(rows)
    assert summary["accuracy"] == 0.5
    assert summary["refusal_rate_answerable"] == 0.5
    assert summary["abstention_unanswerable"] == 0.5
    assert summary["hallucination_rate"] == 0.25
