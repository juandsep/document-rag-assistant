"""Interfaz Streamlit para consultas al asistente RAG.

Ejecutar:
    uv run streamlit run src/rag/ui.py
"""

from __future__ import annotations

import os

import requests
import streamlit as st

API_URL = os.getenv("RAG_API_URL", "http://localhost:8000")

st.set_page_config(page_title="RAG — Consultas de negocio", page_icon="📚")
st.title("Asistente documental (RAG)")

query = st.text_input("Consulta", placeholder="¿Cuál es la política de devoluciones?")
if st.button("Buscar") and query:
    try:
        resp = requests.get(f"{API_URL}/query", params={"q": query}, timeout=30)
        resp.raise_for_status()
        st.json(resp.json())
    except Exception as exc:  # noqa: BLE001
        st.error(f"Error consultando la API: {exc}")
