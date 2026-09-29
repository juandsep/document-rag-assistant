# Infra — RAG (Terraform)

Provisiona los recursos para el servicio RAG:

- **ECS Fargate** (o Cloud Run): servicio `rag-api` + `rag-ui`.
- **ECR / Artifact Registry**: imágenes.
- **Secretos**: `PINECONE_API_KEY`, `OPENSEARCH_*`, `OPENAI_API_KEY`, `MLFLOW_TRACKING_URI`.
- **Networking**: ALB + target groups para la API y la UI.

Nota: la base vectorial (Pinecone o OpenSearch) se gestiona fuera de este módulo;
aquí solo se referencian sus endpoints vía variables.
