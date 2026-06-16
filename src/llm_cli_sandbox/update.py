"""Self-update support: detect the latest published version and how to upgrade.

Canonical source is PyPI's JSON API (this is a pip package), with the GitHub
releases API as a fallback when PyPI lags. Conservative by design: this module
NEVER mutates the environment. It reports the latest version and the exact
upgrade command for the detected install method (pip / pipx / editable checkout)
so the user runs it themselves.

Every network path has a short timeout and fails silently (returns ``None``) so
an offline machine never blocks or slows a command.
"""

from __future__ import annotations

import importlib.metadata as _meta
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from llm_cli_sandbox import __version__

PACKAGE = "llm-cli-sandbox"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
GITHUB_URL = "https://api.github.com/repos/changyy/py-llm-cli-sandbox/releases/latest"


def _get_json(url: str, timeout: int = 6):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — trusted hosts
        return json.load(resp)


def latest_version(timeout: int = 6) -> str | None:
    """Latest published version, or ``None`` if it can't be determined (offline)."""
    try:
        return _get_json(PYPI_URL, timeout)["info"]["version"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        pass
    try:
        tag = _get_json(GITHUB_URL, timeout).get("tag_name")
        return tag.lstrip("v") if tag else None
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        return None


def _parse(v: str) -> tuple[int, ...]:
    """Parse a dotted version into a tuple of ints (leading digits per segment)."""
    out: list[int] = []
    for chunk in v.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out)


def is_newer(latest: str, current: str = __version__) -> bool:
    """True if ``latest`` is a strictly newer version than ``current``."""
    try:
        return _parse(latest) > _parse(current)
    except (ValueError, AttributeError):
        return latest != current


def _is_editable() -> bool:
    """True if the installed package is an editable (``pip install -e .``) checkout."""
    try:
        raw = _meta.distribution(PACKAGE).read_text("direct_url.json")
    except (_meta.PackageNotFoundError, OSError):
        return False
    if not raw:
        return False
    try:
        return bool(json.loads(raw).get("dir_info", {}).get("editable"))
    except ValueError:
        return False


def is_pipx_install() -> bool:
    """Whether this package appears to be managed by pipx."""
    return "pipx" in sys.prefix.lower() or bool(os.environ.get("PIPX_HOME"))


def upgrade_hint() -> str:
    """Best-effort upgrade command for how this install was set up.

    Conservative: a string for the user to run, never executed here.
    """
    if _is_editable():
        return "git pull  (editable/development checkout — pull the repo, no pip needed)"
    if is_pipx_install():
        return f"pipx upgrade {PACKAGE}"
    return f"{sys.executable} -m pip install -U {PACKAGE}"


# --- install from a chosen source (--from) -----------------------------------

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def classify_source(source: str) -> str:
    """``'url'`` for VCS/remote sources pip can fetch on its own, else ``'local'``."""
    if source.startswith("git+") or "://" in source:
        return "url"
    return "local"


def local_source_error(path: Path) -> str | None:
    """Why ``path`` is not a valid local source for this package, or ``None`` if it is.

    A wheel/sdist file is accepted as-is (pip validates it). A directory must be a
    source checkout whose ``pyproject.toml`` declares this package.
    """
    if not path.exists():
        return f"path does not exist: {path}"
    if path.is_file():
        return None
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return f"no pyproject.toml under {path} (not a source checkout?)"
    try:
        data = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return f"could not read {pyproject}: {exc}"
    name = data.get("project", {}).get("name")
    if name != PACKAGE:
        return f"{pyproject} is for package {name!r}, not {PACKAGE!r}"
    return None


def local_source_version(path: Path) -> str | None:
    """Best-effort version of a local source directory (``None`` if unknown)."""
    init = path / "src" / "llm_cli_sandbox" / "__init__.py"
    if not init.is_file():
        return None
    m = _VERSION_RE.search(init.read_text())
    return m.group(1) if m else None


def install_argv(source: str) -> list[str]:
    """Command to (re)install this package from ``source``.

    Uses ``pipx install --force`` when pipx-managed (``pipx upgrade`` can't take
    an arbitrary source, so force-install is the supported way to replace from a
    local path / wheel / git URL). Falls back to pip into the running
    interpreter otherwise — which also targets the pipx venv if pipx's own CLI
    isn't on PATH. ``source`` (dir / wheel / git URL) is accepted by both.
    """
    if is_pipx_install() and shutil.which("pipx"):
        return ["pipx", "install", "--force", source]
    return [sys.executable, "-m", "pip", "install", "--upgrade", source]


def run_install(source: str) -> int:
    """Run the pip install and return its exit code. This DOES mutate the env."""
    return subprocess.run(install_argv(source)).returncode  # noqa: S603 — argv, no shell
