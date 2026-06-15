"""Single source of truth for on-disk locations.

Everything the tool writes lives under one base directory — by default
``~/.llm-cli-sandbox/``, overridable via the ``LLM_CLI_SANDBOX_HOME`` environment
variable (useful for tests and for relocating state).

These are functions, not module constants, so the location is resolved at call
time. That keeps the package free of import-time filesystem decisions and lets a
test point the whole tool at a temp directory by setting one env var.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_HOME = "LLM_CLI_SANDBOX_HOME"
DEFAULT_DIRNAME = ".llm-cli-sandbox"


def config_dir() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_DIRNAME


def config_path() -> Path:
    return config_dir() / "config.toml"


def assets_dir() -> Path:
    return config_dir() / "assets"


def compose_path() -> Path:
    return config_dir() / "docker-compose.yml"


def litellm_config_path() -> Path:
    return config_dir() / "litellm.config.yaml"
