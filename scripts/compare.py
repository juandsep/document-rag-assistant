"""RAG against the same model without retrieval, on the labelled questions.

Usage:
    uv run --env-file .env python scripts/compare.py [--k 5] [--baseline-model M]

Every question in eval/questions.jsonl goes twice through the LLM: once
through the chain (retrieved passages, citations) and once alone, told it may
say it does not know. An LLM judge grades each answer to an answerable
question against its reference answer: correct, incorrect or refused. For
the questions the corpus cannot answer, refusing is the right outcome and any
answer is a hallucination.

Both runs go to MLflow when MLFLOW_TRACKING_URI is set (see evaluate.py).

The judge is independent of the model it grades: DeepSeek's API
(`DEEPSEEK_MODEL`, default `deepseek-flash`) when DEEPSEEK_API_KEY is set.
Without the key it falls back to the answering model grading itself, and
says so, because that is a bias: read the per-question verdicts then.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from rag import chain
from rag.monitoring import log_evaluation
from rag.retrievers import get_retriever

QUESTIONS = Path(__file__).resolve().parents[1] / "eval" / "questions.jsonl"

BASELINE_PROMPT = f"""You answer customer questions about Norte Retail, a store.
- If you do not know the answer, reply with {chain.NO_CONTEXT}: followed by one \
short sentence saying so, in the question's language.
- Reply in the language of the question. Be brief."""

JUDGE_PROMPT = """You grade an answer to a customer question against the \
reference answer taken from the company's documents. Reply with one word:
correct - it states the reference's key facts (wording may differ, harmless \
extra detail is fine)
incorrect - it contradicts the reference, misses its key fact or invents facts
refused - it declines or says it does not know
Grade the facts only: the answer's language and length do not matter, and a \
correct key fact without the reference's secondary details is correct."""


def with_model(model: str | None, call: Callable[[], chain.Reply]) -> chain.Reply:
    """Run `call` with OLLAMA_MODEL temporarily set to `model`."""
    previous = os.environ.get("OLLAMA_MODEL")
    if model:
        os.environ["OLLAMA_MODEL"] = model
    try:
        return call()
    finally:
        if previous is None:
            os.environ.pop("OLLAMA_MODEL", None)
        else:
            os.environ["OLLAMA_MODEL"] = previous


def deepseek_chat(messages: list[dict[str, str]]) -> chain.Reply:
    """One chat turn with DeepSeek's OpenAI-compatible API, temperature 0."""
    body = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "messages": messages,
        "temperature": 0,
    }
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    usage = payload.get("usage", {})
    return chain.Reply(
        payload["choices"][0]["message"]["content"],
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )


def judge_chat() -> tuple[Callable[[list[dict[str, str]]], chain.Reply], str]:
    """The judge and its name: DeepSeek when keyed, else the answering model."""
    if os.getenv("DEEPSEEK_API_KEY"):
        return deepseek_chat, os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    print("warning: DEEPSEEK_API_KEY unset; the answering model judges itself")
    return chain.ollama_chat, os.getenv("OLLAMA_MODEL", "gpt-oss:120b")


def judge(
    question: str,
    reference: str,
    answer: str,
    chat: Callable[[list[dict[str, str]]], chain.Reply] | None = None,
) -> str:
    """correct | incorrect | refused, as graded by `chat` (the judge)."""
    reply = (chat or chain.ollama_chat)(
        [
            {"role": "system", "content": JUDGE_PROMPT},
            {
                "role": "user",
                "content": f"Question: {question}\nReference: {reference}\n"
                f"Answer: {answer}",
            },
        ]
    ).text.lower()
    return next(
        (v for v in ("incorrect", "correct", "refused") if v in reply), "incorrect"
    )


def verdict(item: dict, text: str, refused: bool, chat=None) -> str:
    """Grade one answer; unanswerable questions need no judge."""
    if not item["relevant"]:
        return "refused" if refused else "hallucinated"
    if refused:
        return "refused"
    return judge(item["q"], item["answer"], text, chat)


def summarize(rows: list[dict]) -> dict[str, float]:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    wrong = [r for r in rows if r["verdict"] in ("incorrect", "hallucinated")]
    latencies = sorted(r["ms"] for r in rows)
    return {
        "accuracy": sum(r["verdict"] == "correct" for r in answerable)
        / len(answerable),
        "refusal_rate_answerable": sum(r["verdict"] == "refused" for r in answerable)
        / len(answerable),
        "abstention_unanswerable": sum(r["verdict"] == "refused" for r in unanswerable)
        / len(unanswerable),
        "hallucination_rate": len(wrong) / len(rows),
        "latency_p50_ms": latencies[len(latencies) // 2],
        "latency_p95_ms": latencies[
            min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))
        ],
        "prompt_tokens_avg": sum(r["tokens"] for r in rows) / len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--k", type=int, default=5, help="passages for the RAG side")
    parser.add_argument(
        "--baseline-model", help="model without retrieval (default: OLLAMA_MODEL)"
    )
    args = parser.parse_args()

    questions = [json.loads(line) for line in QUESTIONS.read_text().splitlines()]
    retriever = get_retriever()
    grader, judge_name = judge_chat()
    runs: dict[str, list[dict]] = {"rag": [], "baseline": []}

    for item in questions:
        started = time.perf_counter()
        result = chain.answer(item["q"], top_k=args.k, retriever=retriever)
        rag_ms = (time.perf_counter() - started) * 1000
        refused = result.status == "insufficient_context"
        runs["rag"].append(
            {
                "answerable": bool(item["relevant"]),
                "ms": rag_ms,
                "tokens": result.prompt_tokens,
                "text": result.text,
                "verdict": verdict(item, result.text, refused, grader),
            }
        )

        started = time.perf_counter()
        reply = with_model(
            args.baseline_model,
            lambda q=item["q"]: chain.ollama_chat(
                [
                    {"role": "system", "content": BASELINE_PROMPT},
                    {"role": "user", "content": q},
                ]
            ),
        )
        base_ms = (time.perf_counter() - started) * 1000
        text = reply.text.strip()
        refused = chain.NO_CONTEXT in text
        runs["baseline"].append(
            {
                "answerable": bool(item["relevant"]),
                "ms": base_ms,
                "tokens": reply.prompt_tokens,
                "text": text,
                "verdict": verdict(item, text, refused, grader),
            }
        )
        print(
            f"  rag={runs['rag'][-1]['verdict']:<12} baseline={runs['baseline'][-1]['verdict']:<12} {item['q']}"
        )

    model = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")
    summaries = {mode: summarize(rows) for mode, rows in runs.items()}
    print(f"\n{'metric':>26}  {'rag':>9}  {'baseline':>9}")
    for name in summaries["rag"]:
        print(
            f"{name:>26}  {summaries['rag'][name]:>9.3f}  {summaries['baseline'][name]:>9.3f}"
        )

    if os.getenv("MLFLOW_TRACKING_URI"):
        for mode, metrics in summaries.items():
            params = {
                "mode": mode,
                "model": (args.baseline_model or model)
                if mode == "baseline"
                else model,
                "k": args.k if mode == "rag" else 0,
                "questions": len(questions),
                "judge": judge_name,
            }
            log_evaluation(metrics, params, run_name=f"compare-{mode}")
        print("MLflow: logged rag and baseline runs")


if __name__ == "__main__":
    main()
