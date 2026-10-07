"""Offline evaluation of the retriever, and optionally of the whole chain.

Usage:
    uv run --env-file .env python scripts/evaluate.py [--version V] [--k 3]
        [--chain] [--min-recall 0.8] [--min-decisions 0.9] [--promote]

Reads the labelled questions in eval/questions.jsonl ({"q", "relevant"}; an
empty "relevant" marks a question the corpus cannot answer). Retrieval is
scored at document level: precision@k, recall@k, hit rate@k and MRR over the
answerable questions. With --chain it also asks the full chain and scores
whether it answered the answerable questions and refused the others, with
latency percentiles.

--min-decisions also gates on the share of right answer/refuse decisions (with
--chain). Under GitHub Actions the metrics go to the job summary as a table.

--version evaluates a Qdrant collection that is not serving yet; --promote
moves the alias to it only when recall@k reaches --min-recall. That is the
"switch the serving index after the evaluation passes" step.

The run goes to MLflow when MLFLOW_TRACKING_URI is set (experiment
document-rag-assistant); for the shared server also export
MLFLOW_TRACKING_TOKEN=$(gcloud auth print-identity-token).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from rag import chain
from rag.monitoring import log_evaluation
from rag.retrievers import QdrantRetriever, get_retriever

QUESTIONS = Path(__file__).resolve().parents[1] / "eval" / "questions.jsonl"


def retrieval_scores(ranked: list[str], relevant: set[str], k: int) -> dict:
    """Document-level precision@k, recall@k, hit@k and reciprocal rank."""
    top = ranked[:k]
    hits = [doc for doc in top if doc in relevant]
    first = next((i for i, doc in enumerate(top, start=1) if doc in relevant), 0)
    return {
        "precision": len(hits) / k,
        "recall": len(hits) / len(relevant),
        "hit": float(bool(hits)),
        "rr": 1 / first if first else 0.0,
    }


def unique_docs(doc_ids: list[str]) -> list[str]:
    """Rank documents by their best chunk: a document counts once."""
    return list(dict.fromkeys(doc_ids))


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--version", help="Qdrant collection to evaluate")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--chain", action="store_true", help="also score answers")
    parser.add_argument("--min-recall", type=float, default=0.8)
    parser.add_argument("--min-decisions", type=float, help="with --chain")
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()

    questions = [json.loads(line) for line in QUESTIONS.read_text().splitlines()]
    retriever = QdrantRetriever(alias=args.version) if args.version else get_retriever()
    # Over-fetch chunks so k distinct documents can fill the ranking.
    fetch = args.k * 3

    per_question, decisions, latencies = [], [], []
    for item in questions:
        relevant = set(item["relevant"])
        if relevant:
            hits = retriever.query(item["q"], top_k=fetch)
            ranked = unique_docs([hit.doc_id for hit in hits])
            per_question.append(retrieval_scores(ranked, relevant, args.k))
        if args.chain:
            started = time.perf_counter()
            result = chain.answer(item["q"], top_k=args.k, retriever=retriever)
            latencies.append((time.perf_counter() - started) * 1000)
            expected = "ok" if relevant else "insufficient_context"
            decisions.append(result.status == expected)
            mark = "ok " if decisions[-1] else "BAD"
            print(f"  [{mark}] {result.status:<20} {item['q']}")

    n = len(per_question)
    metrics = {
        f"precision_at_{args.k}": sum(s["precision"] for s in per_question) / n,
        f"recall_at_{args.k}": sum(s["recall"] for s in per_question) / n,
        f"hit_rate_at_{args.k}": sum(s["hit"] for s in per_question) / n,
        "mrr": sum(s["rr"] for s in per_question) / n,
    }
    if args.chain:
        metrics["answer_decision_accuracy"] = sum(decisions) / len(decisions)
        metrics["latency_p50_ms"] = percentile(latencies, 50)
        metrics["latency_p95_ms"] = percentile(latencies, 95)

    serving = getattr(retriever, "alias", os.getenv("VECTOR_BACKEND", "local"))
    params = {
        "backend": os.getenv("VECTOR_BACKEND", "local"),
        "version": args.version or serving,
        "k": args.k,
        "questions": len(questions),
        "answerable": n,
        "model": os.getenv("OLLAMA_MODEL", "gpt-oss:120b") if args.chain else "-",
    }
    for name, value in metrics.items():
        print(f"{name:>26}: {value:.3f}")
    if os.getenv("MLFLOW_TRACKING_URI"):
        logged = log_evaluation(metrics, params)
        print("MLflow:", "logged" if logged else "not installed (uv sync)")

    gates = {f"recall_at_{args.k}": args.min_recall}
    if args.chain and args.min_decisions is not None:
        gates["answer_decision_accuracy"] = args.min_decisions
    failed = [name for name, floor in gates.items() if metrics[name] < floor]
    passed = not failed
    for name, floor in gates.items():
        verdict = "FAIL" if name in failed else "PASS"
        print(f"{name} >= {floor}: {verdict} ({metrics[name]:.3f})")
    if summary := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as out:
            out.write(f"### Offline evaluation ({'pass' if passed else 'FAIL'})\n\n")
            out.write("| Metric | Value | Gate |\n|---|---|---|\n")
            for name, value in metrics.items():
                gate = f">= {gates[name]}" if name in gates else ""
                out.write(f"| {name} | {value:.3f} | {gate} |\n")
    if args.promote:
        if not (passed and args.version):
            print("not promoted: needs --version and a passing recall")
            return 1
        QdrantRetriever().promote(args.version)
        print(f"promoted {args.version}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
