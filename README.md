# Document RAG Assistant · Sistema Documental (Retrieval-Augmented Generation)

> Asistente que responde **preguntas de negocio** sobre un corpus documental: recupera los pasajes relevantes con una **base de datos vectorial**, genera la respuesta **citando las fuentes** y **monitoriza toda la cadena de recuperación en MLflow**.

---

## El problema

El conocimiento de negocio vive disperso en PDFs, wikis, contratos y tickets. Buscar en ese corpus es lento y las respuestas de un LLM sin contexto **alucinan**: no hay forma de saber de dónde salió lo que afirma, ni de medir si la recuperación está mejorando o degradando.

## La solución

Un pipeline **RAG** que separa las dos mitades del problema y las hace medibles por separado:

1. **Recuperación** — los documentos se trocean (`chunking`), se embeben y se indexan en una **base vectorial** (Pinecone u OpenSearch). Cada consulta recupera los *top-k* pasajes más similares.
2. **Generación** — el LLM responde **solo con el contexto recuperado** y devuelve las **fuentes** de cada afirmación.
3. **Monitorización** — cada consulta deja traza en **MLflow**: top-k recuperado, scores de similitud, latencia y uso de tokens. Sobre eso se ejecuta una **evaluación offline** (precision@k / recall@k) para saber si un cambio de retriever, de *chunking* o de embedding mejora o empeora.

Con el retriever instrumentado, un cambio en el corpus o en el modelo deja de ser una apuesta: se mide.

## Arquitectura

```
documentos ──▶ ingesta + chunking ──▶ embeddings ──▶ Vector DB (Pinecone / OpenSearch)
                                                          │
consulta ──▶ POST /query ──▶ retriever (top-k) ──▶ LLM ──▶ respuesta + fuentes citadas
                  │                │
                  └──── trazas ────┴──▶ MLflow (top-k, scores, latencia, tokens)
                                          │
                                          └──▶ evaluación offline (precision@k / recall@k)
                                                          │
                                    UI Streamlit ◀────────┘
```

## Stack

| Capa | Tecnología |
|---|---|
| API | FastAPI + Uvicorn |
| Vector DB | Pinecone **o** OpenSearch (seleccionable por `VECTOR_BACKEND`) |
| Ingesta | chunking propio + embeddings (`sentence-transformers` / proveedor) |
| Generación | LLM configurable (proveedor vía secreto) |
| Monitorización | MLflow (trazas de la cadena + evaluación del retriever) |
| UI | Streamlit (alternativa: Gradio) |
| Despliegue | AWS ECS Fargate + ALB, imágenes en ECR, corpus en S3 |
| Secretos | AWS Secrets Manager (auth OIDC federada en CI) |
| Observabilidad | CloudWatch Logs + métricas |
| Gestión de entorno | **uv** (`pyproject.toml` + `uv.lock`) |
| Tests | pytest |

## Estado del proyecto

Roadmap detallado en [`PLAN.md`](./PLAN.md).

- [x] **F0** · Fundaciones: repo, proyecto `uv`, lock, tests, CI base
- [x] Chunking funcional (`ingest.chunk_text`) + adaptadores Pinecone/OpenSearch (esqueleto)
- [ ] **F1** · Ingesta: carga multi-formato, metadatos, deduplicación
- [ ] **F2** · Vector store: upsert y query reales (Pinecone + OpenSearch)
- [ ] **F3** · Cadena RAG: retriever → prompt → LLM → respuesta con fuentes
- [ ] **F4** · API: `POST /query`, `GET /health`, validación Pydantic
- [ ] **F5** · Monitorización MLflow + evaluación offline del retriever
- [ ] **F6** · UI Streamlit (chat + fuentes)
- [ ] **F7** · CI/CD y despliegue en AWS (ECR + ECS Fargate + ALB)

## Estructura

```
document-rag-assistant/
├─ src/rag/
│   ├─ __init__.py     # entrypoint (`rag` console script)
│   ├─ api.py          # FastAPI: /query, /health
│   ├─ ingest.py       # carga, limpieza y chunking
│   ├─ retrievers.py   # adaptadores Pinecone / OpenSearch
│   ├─ monitoring.py   # trazas MLflow de la cadena de recuperación
│   └─ ui.py           # interfaz Streamlit
├─ tests/              # pytest
├─ scripts/            # index_docs.py (indexado/reindexado)
├─ infra/              # Terraform (aws): ECR, ECS Fargate, ALB, Secrets Manager, S3
├─ .github/workflows/  # CI + deploy
├─ Dockerfile
├─ PLAN.md
└─ pyproject.toml      # dependencias gestionadas con uv
```

## Quickstart

```bash
git clone https://github.com/juandsep/document-rag-assistant.git
cd document-rag-assistant

uv sync                # crea .venv desde uv.lock
uv run pytest -q       # tests
uv run rag             # levanta la API en http://localhost:8000
```

Consultar:

```bash
curl -X POST "http://localhost:8000/query" -H "Content-Type: application/json" \
     -d '{"q": "¿Cuál es la política de devoluciones?"}'
```

Indexar un corpus e interactuar con la UI:

```bash
uv run python scripts/index_docs.py ./docs
uv run streamlit run src/rag/ui.py
```

## Configuración

| Variable | Descripción |
|---|---|
| `VECTOR_BACKEND` | `pinecone` \| `opensearch` |
| `PINECONE_API_KEY` / `PINECONE_INDEX` | credenciales Pinecone |
| `OPENSEARCH_HOST` / `OPENSEARCH_INDEX` | endpoint OpenSearch |
| `MLFLOW_TRACKING_URI` | backend de tracking |
| `LLM_PROVIDER` / `OPENAI_API_KEY` | proveedor LLM y credencial |
| `RAG_API_URL` | URL de la API consumida por la UI |

## Despliegue

`docker build -t document-rag-assistant .` → push a **ECR** → `aws ecs update-service` (servicios `rag-api` y `rag-ui` tras un ALB).
Terraform e instrucciones en [`infra/`](./infra/README.md); pipeline en `.github/workflows/`.

## Métricas de éxito

- precision@k / recall@k del retriever por encima del umbral acordado.
- Latencia extremo a extremo p95 < 3 s.
- Trazabilidad completa: cada respuesta enlaza a los documentos fuente recuperados.

## Referencias

Estructura, CI y convenciones alineadas con el pipeline de referencia `uplift-modeling-pipeline`.

---

**Stack:** Python 3.11 · uv · FastAPI · Pinecone/OpenSearch · MLflow · Streamlit · AWS ECS Fargate · GitHub Actions
