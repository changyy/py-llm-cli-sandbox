"""Functional generation probe over the Anthropic Messages API.

Used to exercise the litellm gateway (or an anthropic-native endpoint) the same
way Claude Code does — a real round-trip that reads a reply, not just a TCP
check. Kept separate from the Ollama client because it speaks Anthropic, not
Ollama, and targets the gateway rather than the model directly.
"""

from __future__ import annotations

import json
import os
import urllib.request


_PROBE_TOOL = {
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "input_schema": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}


def _post_messages(base_url: str, payload: dict, timeout: int) -> dict:
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "sandbox")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — gateway/trusted
        return json.load(resp)


def anthropic_tool_call(base_url: str, model: str, *, timeout: int = 120) -> bool:
    """Send a request that should trigger a tool call and report whether the
    reply contains a structured ``tool_use`` block.

    This is the capability Claude Code depends on: a model that answers in plain
    text (even valid JSON) instead of a ``tool_use`` block can't drive it.
    Raises ``OSError``/``ValueError`` on transport/parse failure.
    """
    data = _post_messages(
        base_url,
        {
            "model": model,
            "max_tokens": 256,
            "tools": [_PROBE_TOOL],
            "messages": [
                {"role": "user", "content": "What is the weather in Tokyo? Use the get_weather tool."}
            ],
        },
        timeout,
    )
    return any(b.get("type") == "tool_use" for b in data.get("content", []))


def anthropic_messages(
    base_url: str,
    model: str,
    *,
    prompt: str = "Reply with the single word: pong",
    max_tokens: int = 32,
    timeout: int = 120,
) -> str:
    """POST one Anthropic Messages request and return the concatenated text reply.

    Auth uses ``ANTHROPIC_AUTH_TOKEN`` (defaulting to ``sandbox``, matching what
    the sandbox launches Claude Code with). Raises ``OSError`` (incl.
    ``HTTPError``) on failure and ``ValueError`` on a malformed response.
    """
    data = _post_messages(
        base_url,
        {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
        timeout,
    )
    blocks = data.get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
