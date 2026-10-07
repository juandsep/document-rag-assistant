"""The one HTTP client for Ollama's API, local or Ollama Cloud."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def post(path: str, body: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
    """POST `body` to `OLLAMA_BASE_URL` + `path`, with the bearer key if set."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key := os.getenv("OLLAMA_API_KEY"):
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url}{path}", data=json.dumps(body).encode(), headers=headers
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)
