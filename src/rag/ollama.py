"""The one HTTP client for Ollama's API, local or Ollama Cloud."""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Iterator
from typing import Any


def _request(path: str, body: dict[str, Any]) -> urllib.request.Request:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key := os.getenv("OLLAMA_API_KEY"):
        headers["Authorization"] = f"Bearer {api_key}"
    return urllib.request.Request(
        f"{base_url}{path}", data=json.dumps(body).encode(), headers=headers
    )


def post(path: str, body: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
    """POST `body` to `OLLAMA_BASE_URL` + `path`, with the bearer key if set."""
    with urllib.request.urlopen(_request(path, body), timeout=timeout) as response:
        return json.load(response)


def post_stream(
    path: str, body: dict[str, Any], timeout: float = 60
) -> Iterator[dict[str, Any]]:
    """POST with `"stream": true` and yield each NDJSON line Ollama sends."""
    with urllib.request.urlopen(_request(path, body), timeout=timeout) as response:
        for line in response:
            if line.strip():
                yield json.loads(line)
