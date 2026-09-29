"""Monitorización de la cadena de recuperación con MLflow.

Registra, por cada consulta: top-k recuperado, scores, latencia y relevancia
(cuando exista feedback). Placeholder degradable: si MLflow no está configurado,
las funciones no fallan y solo emiten warnings.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Iterator

_DEFAULT_URI = os.getenv("MLFLOW_TRACKING_URI", "")


def _mlflow():
    try:
        import mlflow
    except ImportError:  # pragma: no cover
        return None
    if _DEFAULT_URI:
        mlflow.set_tracking_uri(_DEFAULT_URI)
    return mlflow


@contextmanager
def trace_query(name: str = "rag_query") -> Iterator[dict]:
    """Context manager que mide latencia y permite acumular métricas.

    Uso:
        with trace_query() as t:
            ...
            t["top_k"] = 5
    """
    started = time.perf_counter()
    payload: dict = {}
    try:
        yield payload
    finally:
        payload["latency_ms"] = (time.perf_counter() - started) * 1000
        mlflow = _mlflow()
        if mlflow is not None:
            with mlflow.start_run(run_name=name, nested=True):
                mlflow.log_metrics(
                    {k: float(v) for k, v in payload.items() if isinstance(v, (int, float))}
                )


def log_retrieval(metrics: dict[str, float], params: dict | None = None) -> None:
    """Registra métricas de una recuperación (p. ej. recall@k, precision@k)."""
    mlflow = _mlflow()
    if mlflow is None:
        return
    with mlflow.start_run(run_name="retrieval_eval"):
        if params:
            mlflow.log_params(params)
        mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
