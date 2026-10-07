"""Streamlit interface for the document RAG assistant.

Run it with:
    uv run streamlit run src/rag/ui.py
"""

from __future__ import annotations

import os

import requests
import streamlit as st

API_URL = os.getenv("RAG_API_URL", "http://localhost:8000")

st.set_page_config(page_title="Document RAG Assistant", page_icon="📚")
st.title("Document RAG Assistant")
st.caption("Answers are generated from the indexed corpus and cite their sources.")

question = st.text_input("Question", placeholder="What is the return policy?")
top_k = st.slider("Passages to retrieve", min_value=1, max_value=20, value=5)

if st.button("Ask") and question:
    try:
        response = requests.post(
            f"{API_URL}/query",
            json={"q": question, "top_k": top_k},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()

        status = payload.get("status", "ok")
        if status == "insufficient_context":
            st.warning(payload.get("answer", ""))
        elif status == "llm_unavailable":
            st.error(payload.get("answer", ""))
        else:
            st.markdown(payload.get("answer", ""))
        sources = payload.get("sources") or []
        if sources:
            with st.expander(f"Sources ({len(sources)})"):
                for source in sources:
                    st.markdown(
                        f"**{source['doc_id']}** — score {source['score']:.3f}\n\n"
                        f"{source['text']}"
                    )
        else:
            st.info("No passages were retrieved for this question.")
    except Exception as exc:  # noqa: BLE001 - surface any failure to the operator
        st.error(f"Query failed: {exc}")
