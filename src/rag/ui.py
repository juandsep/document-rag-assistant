"""Streamlit interface for the document RAG assistant.

Run it locally against a local or deployed API:
    RAG_API_URL=<url> RAG_API_KEY=<key> uv run streamlit run src/rag/ui.py

The same file is the app on Streamlit Community Cloud (entrypoint
src/rag/ui.py, dependencies in src/rag/requirements.txt, RAG_API_URL and
RAG_API_KEY as root-level secrets, which it exposes as environment variables).
"""

from __future__ import annotations

import os
import time

import requests
import streamlit as st

API_URL = os.getenv("RAG_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("RAG_API_KEY", "")
REPO = "https://github.com/juandsep/document-rag-assistant"
DIAGRAM = (
    "https://raw.githubusercontent.com/juandsep/document-rag-assistant/main/"
    "docs/diagrams/architecture.png"
)

EXAMPLES = [
    "¿Cuántos días tengo para devolver un producto?",
    "Can I pay in installments with a debit card?",
    "¿La garantía cubre daños por humedad?",
    "Can I return something 45 days after delivery?",
    "¿Cuánto cuesta el NR-2210?",
    "What is the minimum wholesale order?",
    "Who is the CEO of Norte Retail?",
]

# What the demo corpus holds; the documents live in eval/corpus/.
CORPUS = [
    ("devoluciones.txt", "Spanish", "Returns: 30-day window, exclusions, refunds"),
    ("envios.txt", "Spanish", "Shipping in Colombia: times, costs, express"),
    (
        "envios-internacionales.md",
        "English",
        "Shipping abroad: 4 countries, flat fee, customs",
    ),
    ("garantia.txt", "Spanish", "Warranty: 12 months electronics, 24 furniture"),
    ("catalogo.docx", "Spanish", "Catalog table: SKU codes, prices, warranty"),
    ("instalacion.pdf", "Spanish", "Assembly service: cities, prices, scheduling"),
    ("mayoristas.pdf", "English", "Wholesale (2 pages): minimums, discounts, net 30"),
    ("tarjetas-regalo.md", "Spanish", "Gift cards: values, 12-month validity, no cash"),
    ("igualacion-precios.txt", "Spanish", "Price matching: conditions, 7-day window"),
    ("pagos.txt", "English", "Payments: cards, PSE, Nequi, installments, invoices"),
    ("soporte.txt", "English", "Support: hours, phone line, response times"),
    ("seguridad-cuenta.txt", "English", "Account security: 2FA, resets, fraud"),
    ("privacidad.txt", "English", "Privacy: where data lives, retention, deletion"),
    (
        "preguntas-frecuentes.md",
        "Spanish/English",
        "FAQ: address changes, cancellations, VAT",
    ),
]

st.set_page_config(page_title="Document RAG Assistant", page_icon="📚", layout="wide")

with st.sidebar:
    st.header("About")
    st.markdown(
        "A question-answering service over a company's documents. It retrieves "
        "the relevant passages first, answers **only** from them, cites each "
        "claim, and says so when the documents do not cover the question "
        "instead of guessing."
    )
    st.markdown(
        "**Runs on** AWS Lambda (API) · Qdrant Cloud (search) · Ollama Cloud "
        "`gpt-oss:120b` (answers) · Streamlit Community Cloud (this page). "
        "About $0.05/month while idle."
    )
    st.markdown(
        f"[Code and docs]({REPO}) · "
        f"[Architecture]({REPO}/blob/main/docs/architecture.md)"
    )
    st.caption(
        "The first question after a quiet spell takes a few seconds while the "
        "API wakes up."
    )

st.title("Document RAG Assistant")
st.caption(
    "Ask about the policies of Norte Retail, a fictional store, in Spanish or "
    "English. Every answer shows the passages it came from."
)

ask_tab, how_tab, corpus_tab = st.tabs(["Ask", "How it works", "Demo corpus"])

with ask_tab:
    example = st.selectbox("Try an example", ["", *EXAMPLES])
    question = st.text_input("Question", value=example, placeholder=EXAMPLES[0])
    top_k = st.slider(
        "Passages to retrieve",
        min_value=1,
        max_value=10,
        value=5,
        help="How many passages the search hands to the model.",
    )

    if st.button("Ask", type="primary") and question:
        try:
            with st.spinner("Searching the documents and writing the answer…"):
                started = time.perf_counter()
                response = requests.post(
                    f"{API_URL}/query",
                    json={"q": question, "top_k": top_k},
                    headers={"X-API-Key": API_KEY} if API_KEY else {},
                    timeout=60,
                )
                elapsed = time.perf_counter() - started
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the operator
            st.error(f"Query failed: {exc}")
        else:
            status = payload.get("status", "ok")
            answer = payload.get("answer", "")
            sources = payload.get("sources") or []
            if status == "insufficient_context":
                st.warning(answer)
                st.caption(
                    "The documents do not cover this, so the assistant refused "
                    "rather than invent an answer."
                )
            elif status == "llm_unavailable":
                st.error(answer)
            else:
                st.markdown(answer)

            col_time, col_sources, col_status = st.columns(3)
            col_time.metric("Response time", f"{elapsed:.1f} s")
            col_sources.metric("Sources cited", len(sources))
            col_status.metric("Status", status.replace("_", " "))

            if sources:
                st.subheader("Sources")
                for source in sources:
                    page = f", page {source['page']}" if source.get("page") else ""
                    with st.expander(
                        f"{source['doc_id']}{page} · score {source['score']:.3f}"
                    ):
                        st.write(source["text"])

with how_tab:
    st.image(
        DIAGRAM,
        caption="Only the API runs in AWS; search, model and UI are free tiers.",
    )
    st.markdown(
        """
1. **Retrieve.** Qdrant embeds the question with the same multilingual model
   that embedded the documents and returns the closest passages.
2. **Generate.** The model receives only those passages, numbered, with rules:
   cite every claim as `[n]`, answer in the question's language, and say the
   documents do not cover it when they don't.
3. **Answer.** The page shows the answer, the passages it cited and a status:
   answered, refused for lack of context, or model unavailable.
4. **Measure.** Each question leaves one log line (latency, scores, tokens)
   that feeds a monitoring dashboard.
"""
    )
    st.subheader("Does retrieval help?")
    st.markdown(
        "The same model, asked the same 56 labelled questions with and without "
        "the documents:"
    )
    st.table(
        {
            "Result": [
                "Correct answers",
                "Invented answers",
                "Refused although answerable",
            ],
            "With retrieval": ["100%", "0%", "0%"],
            "Model alone": ["19%", "5%", "75%"],
        }
    )
    st.caption(
        "Alone, the model cannot know a fictional store's policies: it mostly "
        "refuses and sometimes guesses. Retrieval costs about 0.3 s per question."
    )

with corpus_tab:
    st.markdown(
        "Fourteen documents of **Norte Retail**, a store made up for this demo: "
        "plain text, Markdown, a Word catalog with a product table and two PDFs, "
        "in Spanish and English. Questions work in either language."
    )
    st.table(
        {
            "Document": [doc for doc, _, _ in CORPUS],
            "Language": [lang for _, lang, _ in CORPUS],
            "Covers": [topics for _, _, topics in CORPUS],
        }
    )
    st.markdown(
        "**It should answer:** returns, shipping and customs, product prices by "
        "SKU, assembly, wholesale terms, gift cards, price matching, payments, "
        "support, account security and privacy.\n\n"
        "**It should refuse:** who runs the company, revenue, staff, founding "
        "date, physical stores, loyalty programs, a mobile app, Black Friday "
        "deals. None of that is in the documents."
    )
