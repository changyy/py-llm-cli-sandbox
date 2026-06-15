"""Minimal Ollama REST client for the `models` commands (ollama-type endpoints).

Uses the host-visible base URL of the endpoint. Pull streams NDJSON progress.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator


def _request(method: str, url: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — local/trusted endpoint


def list_models(base: str) -> list[dict]:
    with _request("GET", base.rstrip("/") + "/api/tags") as resp:
        return json.load(resp).get("models", [])


def pull_model(base: str, name: str) -> Iterator[dict]:
    """Stream pull progress as decoded NDJSON dicts."""
    with _request(
        "POST", base.rstrip("/") + "/api/pull", {"model": name, "stream": True}, timeout=3600
    ) as resp:
        for raw in resp:
            raw = raw.strip()
            if raw:
                yield json.loads(raw)


def remove_model(base: str, name: str) -> None:
    with _request("DELETE", base.rstrip("/") + "/api/delete", {"model": name}):
        pass
