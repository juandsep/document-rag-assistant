# Architecture

## Request path

```
POST /query { q }
      │
      ▼
  embed(q) ──▶ Vector DB (Pinecone / OpenSearch) ──▶ top-k chunks
      │
      ▼
  prompt(chunks, q) ──▶ LLM ──▶ answer + cited sources
      │
      ▼
  MLflow trace (top-k ids, scores, latency, tokens)
```

1. The query is embedded with the same model used at index time — a mismatch
   between the two is the most common cause of silently bad retrieval.
2. The retriever returns the top-k passages together with their scores.
3. The prompt is built **only** from those passages; the model is instructed to
   answer from the context and to say so when the context is insufficient.
4. The response carries the source chunks, so a reader can verify every claim.

## Indexing

```
documents ──▶ load ──▶ chunk ──▶ embed ──▶ upsert (index vN)
```

Chunking is a sliding window (`ingest.chunk_text`) so adjacent passages overlap
and a fact split across a boundary is still retrievable.

Reindexing writes a **new** index version; the serving index is switched only
after the evaluation passes.

## Evaluation

`monitoring.py` logs per-query traces to MLflow. On top of those, an offline
evaluation runs precision@k and recall@k over a labelled question set, which is
what turns "the answers feel better" into a number attached to a pull request.

## Failure behaviour

- **Vector DB unavailable** — `/query` fails fast with `503`; answering without
  retrieval would produce uncited claims.
- **No passages above the similarity threshold** — the service returns "not
  enough context" rather than letting the model improvise.
- **LLM unavailable** — the retrieved passages are returned with the error, so
  the caller still gets the evidence.

## Deployment

ECS Fargate runs two services behind one ALB: `rag-api` (FastAPI) and `rag-ui`
(Streamlit). The corpus lives in S3; credentials come from Secrets Manager
through the task role. The image is built from `docker/Dockerfile` and pushed to ECR.
