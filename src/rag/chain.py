"""The RAG chain: retrieve passages, answer only from them, cite them.

The model sees nothing but the numbered passages and the question. It cites
each claim as [n], and when the passages do not hold the answer it says so
instead of improvising. The sources returned are the passages it cited.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from rag import ollama
from rag.retrievers import Retrieved, Retriever, get_retriever

Chat = Callable[[list[dict[str, str]]], str]

NO_CONTEXT = "NO_CONTEXT"

SYSTEM_PROMPT = f"""You answer business questions using only the numbered \
passages you are given.
- Cite every claim with the number of the passage it comes from, like [1].
- If the passages do not contain the answer, reply with exactly {NO_CONTEXT} \
and nothing else. Never answer from your own knowledge.
- Answer in the language of the question, briefly."""

INSUFFICIENT = "The indexed documents do not contain enough information to answer this."


class RetrievalError(RuntimeError):
    """The vector store could not be queried."""


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[Retrieved]
    # ok | insufficient_context | llm_unavailable
    status: str = "ok"


def ollama_chat(messages: list[dict[str, str]]) -> str:
    """One non-streaming chat turn with `OLLAMA_MODEL`, temperature 0."""
    body = {
        "model": os.getenv("OLLAMA_MODEL", "gpt-oss:20b"),
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }
    return ollama.post("/api/chat", body)["message"]["content"]


def _prompt(question: str, passages: list[Retrieved]) -> list[dict[str, str]]:
    context = "\n\n".join(
        f"[{n}] ({p.doc_id}) {p.text}" for n, p in enumerate(passages, start=1)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Passages:\n{context}\n\nQuestion: {question}"},
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
    try:
        passages = (retriever or get_retriever()).query(question, top_k=top_k)
    except Exception as exc:
        raise RetrievalError(str(exc)) from exc
    if not passages:
        return Answer(INSUFFICIENT, [], "insufficient_context")

    try:
        reply = chat(_prompt(question, passages)).strip()
    except Exception as exc:  # noqa: BLE001 - the passages are still evidence
        return Answer(
            f"The language model is unavailable: {exc}", passages, "llm_unavailable"
        )

    if NO_CONTEXT in reply:
        return Answer(INSUFFICIENT, passages, "insufficient_context")
    return Answer(reply, _cited(reply, passages))
