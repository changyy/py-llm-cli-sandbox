"""Packaged Docker assets and their extraction to the user config dir.

The Dockerfile and entrypoint ship inside the package; ``init`` copies them to
``~/.llm-cli-sandbox/assets/`` so users can read and tweak them, and so the
generated compose file has a real build context on disk.
"""

from __future__ import annotations

import importlib.resources as resources
import shutil
from pathlib import Path

from llm_cli_sandbox import paths

ASSET_FILES = ("Dockerfile", "entrypoint.sh")


def extract(dest: Path | None = None) -> Path:
    """Copy packaged assets to ``dest`` (overwriting). Returns the dest dir."""
    dest = dest or paths.assets_dir()
    dest.mkdir(parents=True, exist_ok=True)
    pkg_assets = resources.files("llm_cli_sandbox") / "assets"
    for name in ASSET_FILES:
        src = pkg_assets / name
        (dest / name).write_text(src.read_text())
    # Keep entrypoint executable for clarity (compose builds COPY+chmod anyway).
    shutil.os.chmod(dest / "entrypoint.sh", 0o755)
    return dest
