# RAG — Sistema Documental (Retrieval‑Augmented Generation)

Asistente de consultas de negocio sobre una base documental. Recupera contexto desde una **base de datos vectorial (Pinecone / OpenSearch)**, genera la respuesta y **monitoriza la cadena de recuperación con MLflow**. Interfaz en **Streamlit** (o Gradio) y API con **FastAPI**.

## Arquitectura

```
documentos ──▶ ingesta/chunking ──▶ embeddings ──▶ VectorDB (Pinecone/OpenSearch)
                                                        │
consulta ──▶ FastAPI /query ──▶ retriever ──▶ LLM ──▶ respuesta + fuentes
                   │                  │
                   └── trazas ──▶ MLflow (recuperación, latencias, relevancia)
                                   │
                                   └──▶ UI Streamlit
```

## Estructura

```
rag/
├─ src/rag/
│   ├─ __init__.py     # entrypoint (`rag` console script)
│   ├─ api.py          # FastAPI, endpoint /query
│   ├─ ingest.py       # carga + chunking + embeddings
│   ├─ retrievers.py   # adaptadores Pinecone / OpenSearch
│   ├─ monitoring.py   # trazas MLflow de la cadena de recuperación
│   └─ ui.py           # interfaz Streamlit
├─ tests/              # pytest
├─ scripts/            # indexado inicial, reindexado
├─ docker/             # Dockerfile del servicio / UI
├─ infra/              # IaC (ECS/Cloud Run, secretos)
├─ .github/workflows/  # CI
├─ Dockerfile
└─ pyproject.toml      # deps gestionadas con uv
```

## Quickstart

```bash
cd rag
uv sync                 # instala el entorno (.venv) desde uv.lock
uv run pytest -q        # tests
uv run rag              # levanta la API (uvicorn en :8000)
uv run streamlit run src/rag/ui.py   # UI
```

## Configuración

| Variable | Descripción |
|---|---|
| `VECTOR_BACKEND` | `pinecone` \| `opensearch` |
| `PINECONE_API_KEY` / `PINECONE_INDEX` | credenciales Pinecone |
| `OPENSEARCH_HOST` / `OPENSEARCH_INDEX` | endpoint OpenSearch |
| `MLFLOW_TRACKING_URI` | backend de tracking (compartido con `portfolio-infra/mlflow`) |
| `OPENAI_API_KEY` | proveedor LLM (si aplica) |

## Referencia

Estructura, CI y convenciones basadas en `../portfolio/uplift-modeling-pipeline`.
