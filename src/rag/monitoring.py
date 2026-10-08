"""Telemetry for the retrieval chain.

Each query writes one JSON line to stdout. On Lambda that line lands in
CloudWatch Logs, where the Grafana dashboard reads it with Logs Insights; no
metrics service is called on the request path. Offline evaluation runs go to
MLflow instead (`log_evaluation`).
"""

from __future__ import annotations

import json
import sys
from typing import Any


def log_query(**fields: Any) -> None:
    """Write one `rag_query` event as a single JSON line."""
    print(json.dumps({"event": "rag_query", **fields}), file=sys.stdout, flush=True)


def log_feedback(**fields: Any) -> None:
    """Write one `rag_feedback` event (a reader's rating of an answer)."""
    print(json.dumps({"event": "rag_feedback", **fields}), file=sys.stdout, flush=True)


def log_evaluation(
    metrics: dict[str, float], params: dict[str, Any], run_name: str = "retrieval-eval"
) -> bool:
    """Record an offline evaluation run in MLflow, if it is installed.

    Returns False when MLflow is missing (the image ships without it), so the
    caller can still print the numbers.
    """
    try:
        import mlflow
    except ImportError:
        return False
    mlflow.set_experiment("document-rag-assistant")
    with mlflow.start_run(run_name=run_name):
        mlflow.log_params(params)
        mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
    return True
