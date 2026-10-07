"""Streamlit interface for the document RAG assistant.

Run it locally against a local or deployed API:
    RAG_API_URL=<url> RAG_API_KEY=<key> uv run streamlit run src/rag/ui.py

The same file is the app on Streamlit Community Cloud (entrypoint
src/rag/ui.py, dependencies in src/rag/requirements.txt, RAG_API_URL and
RAG_API_KEY as root-level secrets, which it exposes as environment variables).
"""

from __future__ import annotations

import os

import requests
import streamlit as st

API_URL = os.getenv("RAG_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("RAG_API_KEY", "")

EXAMPLES = [
    "¿Cuántos días tengo para devolver un producto?",
    "Can I pay in installments with a debit card?",
    "¿La garantía cubre daños por humedad?",
    "Who is the CEO of Norte Retail?",
]

st.set_page_config(page_title="Document RAG Assistant", page_icon="📚")
st.title("Document RAG Assistant")
st.caption(
    "Answers come only from the indexed documents and cite them. The demo "
    "corpus is the policy handbook of Norte Retail, a fictional store: returns, "
    "shipping, warranty, support, payments and privacy. Ask in Spanish or English."
)

example = st.selectbox("Try an example", ["", *EXAMPLES])
question = st.text_input("Question", value=example, placeholder=EXAMPLES[0])
top_k = st.slider("Passages to retrieve", min_value=1, max_value=10, value=5)

if st.button("Ask", type="primary") and question:
    try:
        with st.spinner("Retrieving and answering…"):
            response = requests.post(
                f"{API_URL}/query",
                json={"q": question, "top_k": top_k},
                headers={"X-API-Key": API_KEY} if API_KEY else {},
                timeout=60,
            )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - surface any failure to the operator
        st.error(f"Query failed: {exc}")
    else:
        status = payload.get("status", "ok")
        answer = payload.get("answer", "")
        if status == "insufficient_context":
            st.warning(answer)
        elif status == "llm_unavailable":
            st.error(answer)
        else:
            st.markdown(answer)

        sources = payload.get("sources") or []
        if sources:
            st.subheader(f"Sources ({len(sources)})")
            for source in sources:
                page = f", page {source['page']}" if source.get("page") else ""
                with st.expander(
                    f"{source['doc_id']}{page} · score {source['score']:.3f}"
                ):
                    st.write(source["text"])
        elif status == "ok":
            st.info("No passages were retrieved for this question.")
