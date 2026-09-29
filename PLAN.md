# PLAN — Sistema Documental RAG

Objetivo: asistente de consultas de negocio sobre corpus documental, con recuperación vectorial, monitorización de la cadena y UI.

## Fases

- [x] **F0 · Fundaciones** — repo git, proyecto `uv`, lock, `pytest`, CI base.
- [ ] **F1 · Ingesta** — `ingest.py`: carga de documentos, chunking, metadatos, deduplicación.
- [ ] **F2 · Vector store** — `retrievers.py`: adaptadores Pinecone y OpenSearch (create/upsert/query), seleccionados por `VECTOR_BACKEND`.
- [ ] **F3 · Cadena RAG** — retriever + prompt + LLM; respuesta con citas/fuentes.
- [ ] **F4 · API** — `api.py`: `POST /query`, `/health`; validación con Pydantic.
- [ ] **F5 · Monitorización** — `monitoring.py`: trazas MLflow (top‑k, latencia, relevancia, uso de tokens), evaluación offline del retriever.
- [ ] **F6 · UI** — `ui.py`: Streamlit (chat + fuentes); alternativa Gradio.
- [ ] **F7 · CI/CD y despliegue** — GitHub Actions (lint/test/build) → contenedor → ECS/Cloud Run.

## Métricas de éxito

- Precision@k / recall@k del retriever por encima del umbral acordado.
- Latencia extremo a extremo p95 < 3 s.
- Trazabilidad completa: cada respuesta enlaza a los documentos fuente recuperados.

## Referencia

Estructura, CI y convenciones basadas en `../portfolio/uplift-modeling-pipeline`.
