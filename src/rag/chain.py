"""The RAG chain: retrieve passages, answer only from them, cite them.

The model sees nothing but the numbered passages and the question. It cites
each claim as [n], and when the passages do not hold the answer it says so
instead of improvising. The sources returned are the passages it cited.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from rag import ollama
from rag.ingest import language
from rag.retrievers import Retrieved, Retriever, get_retriever


@dataclass(frozen=True)
class Reply:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


Chat = Callable[[list[dict[str, str]]], Reply]

NO_CONTEXT = "NO_CONTEXT"

SYSTEM_PROMPT = f"""You answer business questions using only the numbered \
passages you are given.
Rules:
1. Reply in the language the QUESTION is written in, never in the passages' \
language when they differ. Translate what you use.
2. Answer whenever the passages state the answer or let you deduce it. A rule \
answers questions about cases it covers: "returns accepted up to 30 days" \
answers "can I return after 45 days?" with a no, citing that passage.
3. Cite every claim with its passage number, like [1].
4. Only when no passage is about the question's topic, reply {NO_CONTEXT}: \
followed by one short sentence in the question's language saying the \
documents do not cover it.
5. Never use knowledge from outside the passages. Be brief."""


def question_language(question: str) -> str:
    """The language to answer in, named explicitly in the prompt.

    Over Spanish passages, gpt-oss answered English questions in Spanish half
    of the time when only told to follow the question's language (6/12);
    naming it gave 18/18.
    """
    return language(question)


INSUFFICIENT = "The indexed documents do not contain enough information to answer this."


class RetrievalError(RuntimeError):
    """The vector store could not be queried."""


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[Retrieved]
    # ok | insufficient_context | llm_unavailable
    status: str = "ok"
    # What the per-query log line reports (see monitoring.log_query).
    passages: list[Retrieved] = field(default_factory=list)
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


def ollama_chat(messages: list[dict[str, str]]) -> Reply:
    """One non-streaming chat turn with `OLLAMA_MODEL`, temperature 0."""
    body = {
        "model": os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }
    response = ollama.post("/api/chat", body)
    return Reply(
        response["message"]["content"],
        response.get("prompt_eval_count", 0),
        response.get("eval_count", 0),
    )


def _prompt(question: str, passages: list[Retrieved]) -> list[dict[str, str]]:
    context = "\n\n".join(
        f"[{n}] ({p.doc_id}{f', p. {p.page}' if p.page else ''}) {p.text}"
        for n, p in enumerate(passages, start=1)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Passages:\n{context}\n\nQuestion: {question}\n\n"
            f"Write the whole reply in {question_language(question)}.",
        },
    ]


def _cited(reply: str, passages: list[Retrieved]) -> list[Retrieved]:
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", reply)}
    cited = [p for n, p in enumerate(passages, start=1) if n in numbers]
    # An answer with no parseable citation still came from these passages.
    return cited or passages


def answer(
    question: str,
    top_k: int = 5,
    retriever: Retriever | None = None,
    chat: Chat = ollama_chat,
) -> Answer:
    """Answer `question` from the indexed corpus, citing the passages used."""
    started = time.perf_counter()
    try:
        passages = (retriever or get_retriever()).query(question, top_k=top_k)
    except Exception as exc:
        raise RetrievalError(str(exc)) from exc
    retrieved = time.perf_counter()
    timing = {"passages": passages, "retrieval_ms": (retrieved - started) * 1000}
    if not passages:
        return Answer(INSUFFICIENT, [], "insufficient_context", **timing)

    try:
        reply = chat(_prompt(question, passages))
    except Exception as exc:  # noqa: BLE001 - the passages are still evidence
        return Answer(
            f"The language model is unavailable: {exc}",
            passages,
            "llm_unavailable",
            **timing,
            generation_ms=(time.perf_counter() - retrieved) * 1000,
        )
    usage = {
        **timing,
        "generation_ms": (time.perf_counter() - retrieved) * 1000,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
    }
    # gpt-oss sometimes cites with full-width brackets; normalize to [n].
    text = reply.text.strip().replace("【", "[").replace("】", "]")

    if NO_CONTEXT in text:
        # Nothing backs a refusal, so no sources; keep the model's sentence,
        # which is in the question's language.
        sentence = text.split(NO_CONTEXT, 1)[1].lstrip(" :").strip()
        return Answer(sentence or INSUFFICIENT, [], "insufficient_context", **usage)
    return Answer(text, _cited(text, passages), **usage)
