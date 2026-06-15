"""Thin wrappers around `docker compose`, driving the generated compose file.

We shell out to the CLI (rather than docker-py) so behavior matches what a user
would run by hand and stays robust across daemon/runtime versions. Failures
surface as ``SandboxError`` (clean one-line message) rather than raw tracebacks.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from pathlib import Path

from llm_cli_sandbox import paths
from llm_cli_sandbox.compose import IMAGE_TAG, PROJECT_NAME
from llm_cli_sandbox.errors import SandboxError


def docker_available() -> bool:
    return shutil.which("docker") is not None


def require_docker() -> None:
    if not docker_available():
        raise SandboxError(
            "docker not found on PATH",
            exit_code=127,
            hint="Install Docker Desktop, OrbStack, or Podman.",
        )


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _compose(args: list[str], *, compose_file: Path | None = None) -> int:
    require_docker()
    compose_file = compose_file or paths.compose_path()
    cmd = ["docker", "compose", "-p", PROJECT_NAME, "-f", str(compose_file), *args]
    return subprocess.run(cmd).returncode


def image_exists(tag: str = IMAGE_TAG) -> bool:
    try:
        return (
            subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0
        )
    except (FileNotFoundError, OSError):
        return False


def container_running(name: str) -> bool:
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", f"name={name}", "--filter", "status=running", "-q"],
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, OSError):
        return False
    return bool(out)


GATEWAY_CONTAINER = f"{PROJECT_NAME}-litellm"


def ensure_gateway_port_free(port: int) -> None:
    """Raise if the gateway port is held by something that is not our own gateway."""
    if port_in_use(port) and not container_running(GATEWAY_CONTAINER):
        raise SandboxError(
            f"host port {port} is already in use by another process",
            hint=f"stop whatever holds it, or change [gateway.litellm] port in the config. "
            f"(lsof -nP -iTCP:{port} -sTCP:LISTEN)",
        )


def build(service: str | None = None) -> None:
    code = _compose(["build", *([service] if service else [])])
    if code != 0:
        raise SandboxError(
            "failed to build the sandbox image",
            exit_code=code,
            hint="re-run with `docker compose build` for full output, or check disk/network.",
        )


def up_gateway(wait: bool = True) -> None:
    args = ["up", "-d"]
    if wait:
        args.append("--wait")
    args.append("litellm")
    code = _compose(args)
    if code != 0:
        raise SandboxError(
            "failed to start the litellm gateway",
            exit_code=code,
            hint="run `llm-cli-sandbox doctor` to check the gateway port and endpoint.",
        )


def down() -> int:
    return _compose(["down"])


def ps() -> int:
    return _compose(["ps"])


def run_sandbox(extra: list[str] | None = None, *, service_cmd: list[str] | None = None) -> int:
    """`docker compose run --rm sandbox [cmd...]` — interactive by default."""
    args = ["run", "--rm", *(extra or []), "sandbox", *(service_cmd or [])]
    return _compose(args)
