"""Minimal Ollama REST client for the `models` commands (ollama-type endpoints).

Uses the host-visible base URL of the endpoint. Pull streams NDJSON progress.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass

# Curated starting points for `models catalog`. Ollama exposes no "popular"
# API, so this is a hand-maintained shortlist. Each entry is
# (name, storage, ram_gb, tool_use, note): ``storage`` is the download/disk size,
# ``ram_gb`` a rough minimum RAM to run it without heavy swapping. ``tool_use``
# is the deciding capability for Claude Code — it is entirely tool-driven, so a
# model that can't emit structured tool calls can't drive it, however good it is
# at chat/code. Tool-capable models are listed first.
RECOMMENDED_MODELS: list[tuple[str, str, int, bool, str]] = [
    ("gpt-oss:20b", "~14 GB", 16, True, "agentic/tool use; solid Claude Code default"),
    ("llama3.1:8b", "~4.7 GB", 8, True, "general; tool calling, light footprint"),
    ("qwen3:8b", "~5 GB", 8, True, "general; tool calling"),
    ("mistral-nemo:12b", "~7 GB", 12, True, "general; tool calling"),
    ("llama3.3:70b", "~43 GB", 48, True, "high quality; needs lots of RAM/VRAM"),
    ("qwen2.5-coder:7b", "~4.7 GB", 8, False, "strong at code, but NO tool calls"),
    ("qwen2.5-coder:32b", "~20 GB", 24, False, "strong at code, but NO tool calls"),
]


def recommended_ram(name: str) -> int | None:
    """Rough minimum RAM (GB) for a catalog model, or None if not in the list."""
    for n, _storage, ram, _tools, _note in RECOMMENDED_MODELS:
        if n == name:
            return ram
    return None


def tool_capability(name: str) -> bool | None:
    """Whether a catalog model emits tool calls; None if not in the list."""
    for n, _storage, _ram, tools, _note in RECOMMENDED_MODELS:
        if n == name:
            return tools
    return None


def _request(method: str, url: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — local/trusted endpoint


def list_models(base: str) -> list[dict]:
    with _request("GET", base.rstrip("/") + "/api/tags") as resp:
        return json.load(resp).get("models", [])


def model_installed(base: str, name: str) -> bool:
    """Whether ``name`` resolves to a model installed on the endpoint.

    Matches the exact tag; if ``name`` carries no tag, also accepts
    ``<name>:latest``. Raises ``OSError`` if the endpoint can't be reached, so
    the caller can distinguish "not installed" from "couldn't check".
    """
    installed = {m.get("name", "") for m in list_models(base)}
    if name in installed:
        return True
    return ":" not in name and f"{name}:latest" in installed


@dataclass
class ChatResult:
    """A chat reply plus Ollama's own timing breakdown (seconds).

    ``load_seconds`` is time spent loading the model into memory — separated out
    so a slow first call (cold start) is distinguishable from slow generation.
    """

    reply: str
    load_seconds: float
    eval_seconds: float
    total_seconds: float
    eval_count: int


def chat(
    base: str,
    model: str,
    prompt: str = "Reply with the single word: pong",
    *,
    num_predict: int = 32,
    timeout: int = 120,
) -> ChatResult:
    """Send one non-streamed chat turn and return the reply with timings.

    A functional probe (does the model actually generate?), distinct from a
    reachability check. Raises ``OSError`` if the endpoint can't be reached.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_predict": num_predict},
    }
    with _request("POST", base.rstrip("/") + "/api/chat", payload, timeout=timeout) as resp:
        data = json.load(resp)
    ns = 1e9
    return ChatResult(
        reply=data.get("message", {}).get("content", "").strip(),
        load_seconds=round(data.get("load_duration", 0) / ns, 2),
        eval_seconds=round(data.get("eval_duration", 0) / ns, 2),
        total_seconds=round(data.get("total_duration", 0) / ns, 2),
        eval_count=data.get("eval_count", 0) or 0,
    )


def loaded_model_names(base: str) -> set[str]:
    """Names of models currently resident in memory (``/api/ps``)."""
    with _request("GET", base.rstrip("/") + "/api/ps") as resp:
        return {m.get("name", "") for m in json.load(resp).get("models", [])}


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
