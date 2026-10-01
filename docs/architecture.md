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

Lambda runs the API as a container image, reached through a Function URL:
HTTPS and a public hostname with no load balancer, and no bill while nobody
asks anything. The image is built from `docker/Dockerfile` and pushed to ECR;
the Lambda Web Adapter inside it serves the same FastAPI app that runs locally.

The corpus lives in S3 and the credentials in Secrets Manager, read by the
function role — not injected as environment variables. `reserved_concurrency`
caps how much a reachable URL can spend.

Streamlit is not deployed: it needs a long-lived websocket server, which a
Function URL does not provide. It runs locally against the deployed API.

The chat model is Ollama's HTTP API, reachable from the function over the
internet; embeddings come from the same endpoint, so the image carries no
model weights. If a corpus outgrows an embedded index, `VECTOR_BACKEND`
switches the retriever to Qdrant, Pinecone or OpenSearch without touching the
chain.
