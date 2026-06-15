"""Dynamic generation of the compose file, litellm config, and Claude Code env.

The selected endpoint drives everything:

- whether a litellm gateway service is emitted at all (ollama / openai-compat
  need it; anthropic does not),
- the ``ANTHROPIC_BASE_URL`` Claude Code is pointed at (gateway vs endpoint,
  in-container vs host),
- the litellm model routing (ollama_chat/... vs openai/...).

``host.docker.internal:host-gateway`` is injected on every service so a
host-local endpoint is reachable identically on Linux and Docker Desktop.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from llm_cli_sandbox import paths
from llm_cli_sandbox.config import Config, Endpoint
from llm_cli_sandbox.sysinfo import HOST_GATEWAY_MAPPING

PROJECT_NAME = "llm-cli-sandbox"
IMAGE_TAG = "llm-cli-sandbox:latest"
GATEWAY_INTERNAL_PORT = 4000


def gateway_url(cfg: Config, *, from_container: bool) -> str:
    """Where the litellm gateway is reachable."""
    if from_container:
        return f"http://litellm:{GATEWAY_INTERNAL_PORT}"
    return f"http://127.0.0.1:{cfg.gateway.port}"


def claude_base_url(cfg: Config, ep: Endpoint, *, from_container: bool) -> str:
    """The ANTHROPIC_BASE_URL Claude Code should use for this endpoint."""
    if ep.needs_gateway:
        return gateway_url(cfg, from_container=from_container)
    # Anthropic-native endpoint: point Claude Code straight at it.
    return ep.base_url(from_container=from_container)


def claude_env(cfg: Config, ep: Endpoint, *, from_container: bool) -> dict[str, str]:
    """Environment for launching Claude Code against this endpoint.

    Uses ANTHROPIC_AUTH_TOKEN (not API_KEY): a gateway needs the bearer token,
    and API_KEY would trigger the login flow that stalls interactive sessions.
    """
    env = {
        "ANTHROPIC_BASE_URL": claude_base_url(cfg, ep, from_container=from_container),
        "ANTHROPIC_AUTH_TOKEN": "sandbox",
        "MAX_THINKING_TOKENS": "0",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }
    if ep.model:
        env["ANTHROPIC_MODEL"] = ep.model
        env["ANTHROPIC_SMALL_FAST_MODEL"] = ep.model
    return env


def gen_litellm_config(ep: Endpoint) -> dict:
    """litellm model_list routing the gateway to this endpoint.

    A ``claude-*`` wildcard alias is included so Claude Code's default model IDs
    resolve without overriding ANTHROPIC_MODEL.
    """
    api_base = ep.base_url(from_container=True)
    model = ep.model or "local-model"
    if ep.type == "ollama":
        provider_model = f"ollama_chat/{model}"
        params_extra: dict = {"api_base": api_base}
    elif ep.type == "openai-compat":
        provider_model = f"openai/{model}"
        # litellm requires a key for the openai provider; the gateway is local.
        params_extra = {"api_base": api_base, "api_key": "sk-noop"}
    else:
        raise ValueError(f"endpoint type {ep.type!r} does not use a gateway")

    def entry(name: str) -> dict:
        return {
            "model_name": name,
            "litellm_params": {
                "model": provider_model,
                **params_extra,
                # Local models often reject thinking/reasoning params.
                "additional_drop_params": ["thinking", "reasoning_effort"],
            },
        }

    return {
        "model_list": [entry(model), entry("claude-*")],
        "litellm_settings": {"drop_params": True},
    }


def build_compose(cfg: Config, ep: Endpoint, workspace: Path) -> dict:
    """Build the compose document for this config + endpoint."""
    sandbox_service = {
        "build": {
            "context": str(paths.assets_dir()),
            "dockerfile": "Dockerfile",
            "args": {"USER_NAME": cfg.sandbox.user},
        },
        "image": IMAGE_TAG,
        "container_name": f"{PROJECT_NAME}-sandbox",
        "working_dir": "/workspace",
        "volumes": [f"{workspace}:/workspace"],
        "extra_hosts": [HOST_GATEWAY_MAPPING],
        "environment": claude_env(cfg, ep, from_container=True),
        "stdin_open": True,
        "tty": True,
    }

    services = {"sandbox": sandbox_service}

    if ep.needs_gateway:
        services["litellm"] = {
            "image": cfg.gateway.image,
            "container_name": f"{PROJECT_NAME}-litellm",
            "volumes": [f"{paths.litellm_config_path()}:/app/config.yaml:ro"],
            "command": ["--config", "/app/config.yaml", "--port", str(GATEWAY_INTERNAL_PORT)],
            "ports": [f"{cfg.gateway.port}:{GATEWAY_INTERNAL_PORT}"],
            "extra_hosts": [HOST_GATEWAY_MAPPING],
            "restart": "unless-stopped",
        }
        sandbox_service["depends_on"] = ["litellm"]

    return {"services": services}


def write_generated(cfg: Config, ep: Endpoint, workspace: Path) -> dict[str, Path]:
    """Write compose + litellm config to the config dir. Returns written paths."""
    paths.config_dir().mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    compose_path = paths.compose_path()
    compose_path.write_text(yaml.safe_dump(build_compose(cfg, ep, workspace), sort_keys=False))
    written["compose"] = compose_path

    if ep.needs_gateway:
        litellm_path = paths.litellm_config_path()
        litellm_path.write_text(yaml.safe_dump(gen_litellm_config(ep), sort_keys=False))
        written["litellm"] = litellm_path

    return written
