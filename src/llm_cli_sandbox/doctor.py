"""Environment checks.

Each lesson learned the hard way becomes an automated check with a concrete fix
hint: Docker availability, ``host.docker.internal`` resolution per platform,
endpoint reachability (local or remote), gateway port conflicts, and Claude Code
auth sanity (a gateway needs ANTHROPIC_AUTH_TOKEN, not ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum

from llm_cli_sandbox import sysinfo as plat
from llm_cli_sandbox.config import Config, Endpoint


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    fix: str | None = None


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", "not found"
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, "", str(exc)


def _http_ok(url: str, timeout: int = 4) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (local/trusted)
            return 200 <= resp.status < 500, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        # Reachable, just not a 2xx — endpoint is up, which is what we test.
        return True, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, str(getattr(exc, "reason", exc))


# --- individual checks -------------------------------------------------------


def check_python() -> CheckResult:
    v = sys.version_info
    if v >= (3, 11):
        return CheckResult("python", Status.OK, f"Python {v.major}.{v.minor}.{v.micro}")
    return CheckResult(
        "python",
        Status.FAIL,
        f"Python {v.major}.{v.minor} (need >= 3.11)",
        fix="Install Python 3.11+ and reinstall llm-cli-sandbox in that interpreter.",
    )


def check_platform(info: plat.PlatformInfo) -> CheckResult:
    label = f"{info.os}/{info.arch}"
    if info.is_apple_silicon:
        label += " (Apple Silicon)"
    if info.supported:
        return CheckResult("platform", Status.OK, label)
    return CheckResult("platform", Status.WARN, f"{label} — untested platform")


def check_runtime(info: plat.PlatformInfo) -> CheckResult:
    if info.container_runtime is None:
        return CheckResult(
            "container-runtime",
            Status.FAIL,
            "no docker or podman found on PATH",
            fix="Install Docker Desktop, OrbStack, or Podman.",
        )
    return CheckResult(
        "container-runtime",
        Status.OK,
        f"{info.container_runtime} ({info.runtime_flavor})",
    )


def check_daemon(info: plat.PlatformInfo) -> CheckResult:
    if info.container_runtime is None:
        return CheckResult("daemon", Status.FAIL, "no runtime to query", fix="See container-runtime.")
    code, _, err = _run([info.container_runtime, "info", "--format", "{{.ServerVersion}}"])
    if code == 0:
        return CheckResult("daemon", Status.OK, "daemon reachable")
    return CheckResult(
        "daemon",
        Status.FAIL,
        f"daemon not reachable ({err or 'unknown error'})",
        fix="Start Docker Desktop / OrbStack, or `systemctl start docker` on Linux.",
    )


def check_compose(info: plat.PlatformInfo) -> CheckResult:
    if info.container_runtime != "docker":
        return CheckResult(
            "compose",
            Status.WARN,
            "compose check skipped (non-docker runtime)",
        )
    code, out, _ = _run(["docker", "compose", "version", "--short"])
    if code == 0 and out:
        return CheckResult("compose", Status.OK, f"docker compose v{out}")
    return CheckResult(
        "compose",
        Status.FAIL,
        "docker compose v2 not available",
        fix="Install the Docker Compose v2 plugin (bundled with Docker Desktop/OrbStack).",
    )


def check_claude_cli() -> CheckResult:
    path = shutil.which("claude") or str(
        (os.path.expanduser("~/.local/bin/claude"))
        if os.path.exists(os.path.expanduser("~/.local/bin/claude"))
        else ""
    )
    if path:
        return CheckResult("claude-cli", Status.OK, f"found at {path}")
    return CheckResult(
        "claude-cli",
        Status.WARN,
        "claude not found on host (only needed for host mode; the sandbox image ships its own)",
        fix="Install: curl -fsSL https://claude.ai/install.sh | bash",
    )


def check_endpoint(ep: Endpoint | None) -> CheckResult:
    if ep is None:
        return CheckResult(
            "endpoint",
            Status.WARN,
            "no endpoint configured yet",
            fix="Run `llm-cli-sandbox init` (M1) or add one with `endpoints add`.",
        )
    # Probe from the host's point of view (localhost for host-local Ollama).
    base = ep.base_url(from_container=False)
    probe = base.rstrip("/")
    probe += "/api/tags" if ep.type == "ollama" else "/models"
    ok, detail = _http_ok(probe)
    label = f"{ep.name} [{ep.type}] {base}"
    if ok:
        return CheckResult("endpoint", Status.OK, f"{label} reachable ({detail})")
    return CheckResult(
        "endpoint",
        Status.FAIL,
        f"{label} NOT reachable ({detail})",
        fix="Check the endpoint is running and the URL/port is correct. "
        "For remote endpoints, verify network access.",
    )


def check_auth_env() -> CheckResult:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_token = bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if has_key and has_token:
        return CheckResult(
            "auth-env",
            Status.WARN,
            "both ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are set",
            fix="For a gateway, keep ANTHROPIC_AUTH_TOKEN and unset ANTHROPIC_API_KEY "
            "(API_KEY triggers the login flow and stalls interactive sessions).",
        )
    if has_key and not has_token:
        return CheckResult(
            "auth-env",
            Status.WARN,
            "ANTHROPIC_API_KEY set without ANTHROPIC_AUTH_TOKEN",
            fix="For a local/3rd-party gateway use ANTHROPIC_AUTH_TOKEN instead.",
        )
    return CheckResult("auth-env", Status.OK, "no conflicting Anthropic auth env vars")


def run_all(config: Config, endpoint_name: str | None = None) -> list[CheckResult]:
    info = plat.detect()
    ep = config.get_endpoint(endpoint_name)
    return [
        check_python(),
        check_platform(info),
        check_runtime(info),
        check_daemon(info),
        check_compose(info),
        check_claude_cli(),
        check_endpoint(ep),
        check_auth_env(),
    ]
