PROMPT PARA EL SIGUIENTE AGENTE — Sistema Documental RAG (rag) → AWS

CONTEXTO
- Repo: juandsep/document-rag-assistant (trabaja SOLO dentro de esa carpeta).
- Proyecto Python gestionado con `uv` (pyproject.toml + uv.lock). Entry: `uv run rag`.
- Estado actual: scaffolding funcional.
  src/rag/{__init__,api,ingest,retrievers,monitoring,ui}.py · tests/test_rag.py (5 passed) ·
  scripts/index_docs.py · Dockerfile · README.md · PLAN.md · infra/README.md ·
  .github/workflows/ci.yml · pyproject.toml.
- Ya existe chunking funcional (`ingest.chunk_text`) y adaptadores Pinecone/OpenSearch
  como placeholders (`retrievers.py`). La cadena RAG real y el despliegue aún NO están hechos.
- Despliegue objetivo: AWS (ECS Fargate). No toques otros repos.
  Referencia de estructura/CI: the uplift-modeling-pipeline project.

OBJETIVO
Implementar la cadena RAG completa y dejarla desplegable en AWS con CI/CD.

STACK A USAR
- Cómputo: ECS Fargate (servicios `rag-api` y `rag-ui`) detrás de un ALB.
- Imágenes: ECR. Secretos: AWS Secrets Manager. Corpus: S3.
- Vector DB: Pinecone (externo) u OpenSearch Service, seleccionable por VECTOR_BACKEND.
- Observabilidad: CloudWatch Logs + métricas; tracing de la cadena en MLflow.
- LLM: proveedor configurable (OPENAI_API_KEY u otro) vía secreto.
- CI/CD: GitHub Actions con OIDC a AWS (aws-actions/configure-aws-credentials), sin claves estáticas.

TAREAS (en orden)
1. Crea la rama `feat/rag-pipeline` a partir de `dev`.
2. Implementa `src/rag/retrievers.py`: upsert y query reales para Pinecone y OpenSearch
   (embeddings con el proveedor configurado). Selección por `VECTOR_BACKEND`.
3. Implementa la cadena RAG: `src/rag/chain.py` (retriever → prompt → LLM → respuesta con fuentes citadas).
4. Completa `src/rag/api.py`: `POST /query` (Pydantic), `GET /health`, manejo de errores; conecta la cadena y el tracing.
5. Instrumenta `src/rag/monitoring.py` con MLflow: top-k, scores, latencia, tokens; script de evaluación offline (precision@k / recall@k) sobre un set pequeño.
6. Ajusta `src/rag/ui.py` (Streamlit) para consumir la API y mostrar fuentes.
7. Añade deps necesarias con `uv add` (p. ej. openai, sentence-transformers/tiktoken, boto3) y actualiza uv.lock.
8. Infra AWS: reescribe infra/README.md y añade Terraform (provider aws): infra/{main.tf,variables.tf,outputs.tf,terraform.tfvars.example} con ECR, cluster ECS Fargate, task definitions y servicios (api + ui), ALB, Secrets Manager, bucket S3 del corpus, roles IAM.
9. Actualiza .github/workflows/ci.yml: job `test` (uv sync + pytest) y job `deploy` (build → push a ECR → `aws ecs update-service`), deploy solo en push a `dev`.
10. Verifica en local: `uv sync && uv run pytest -q` (verde), `docker build -t rag .` (OK) y `uv run rag` levanta la API (smoke test de `/health`).

REGLAS
- Git flow: ramas topic desde `dev`, PR hacia `dev`; solo `dev` → `main`.
- Cero secretos en el repo: Secrets Manager + OIDC federado.
- Documentación en español; código/comentarios en inglés.
- Entrega final: lista de archivos cambiados + comandos ejecutados y su salida real (sin inventar resultados).

CRITERIO DE ACEPTACIÓN
- `POST /query` devuelve respuesta con las fuentes recuperadas; `/health` responde 200.
- Trazas de la cadena visibles en MLflow y evaluación offline ejecutable.
- Tests en verde y `docker build` OK.
- Terraform AWS pasa `terraform validate`; workflows referencian ECR + ECS Fargate con OIDC.
