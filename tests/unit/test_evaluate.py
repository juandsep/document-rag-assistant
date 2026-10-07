"""Unit tests for the offline evaluation's metrics."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "evaluate", Path(__file__).resolve().parents[2] / "scripts" / "evaluate.py"
)
evaluate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluate)


def test_retrieval_scores_at_k():
    scores = evaluate.retrieval_scores(["a", "b", "c"], {"b", "z"}, k=3)
    assert scores == {
        "precision": pytest.approx(1 / 3),
        "recall": 0.5,
        "hit": 1.0,
        "rr": 0.5,
    }


def test_retrieval_scores_with_a_miss():
    scores = evaluate.retrieval_scores(["a", "b"], {"z"}, k=2)
    assert scores == {"precision": 0.0, "recall": 0.0, "hit": 0.0, "rr": 0.0}


def test_unique_docs_keeps_each_document_at_its_best_rank():
    assert evaluate.unique_docs(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_percentile_picks_from_the_sorted_values():
    values = [5.0, 1.0, 3.0, 2.0, 4.0]
    assert evaluate.percentile(values, 50) == 3.0
    assert evaluate.percentile(values, 95) == 5.0


def test_the_question_set_is_well_formed():
    import json

    lines = evaluate.QUESTIONS.read_text().splitlines()
    items = [json.loads(line) for line in lines]
    assert all(item["q"] and isinstance(item["relevant"], list) for item in items)
    corpus = {p.name for p in (evaluate.QUESTIONS.parent / "corpus").iterdir()}
    assert {doc for item in items for doc in item["relevant"]} <= corpus
