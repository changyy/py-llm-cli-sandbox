"""Launch Claude Code on the host against the selected endpoint.

Host mode replaces the current process (``execvpe``) on Unix; Windows has no
``exec`` so it spawns a subprocess and forwards the exit code. In-container mode
is handled by docker_ctl (the env is baked into the generated compose file).
"""

from __future__ import annotations

import os
import shutil
import subprocess

from llm_cli_sandbox import compose
from llm_cli_sandbox import sysinfo as plat
from llm_cli_sandbox.config import Config, Endpoint


def find_claude() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    candidate = os.path.expanduser("~/.local/bin/claude")
    return candidate if os.path.exists(candidate) else None


def build_host_env(cfg: Config, ep: Endpoint) -> dict[str, str]:
    env = dict(os.environ)
    # API_KEY would trigger the Anthropic login flow and stall interactive
    # sessions; the gateway path uses AUTH_TOKEN only.
    env.pop("ANTHROPIC_API_KEY", None)
    env.update(compose.claude_env(cfg, ep, from_container=False))
    return env


def launch_host(cfg: Config, ep: Endpoint, args: list[str]) -> int:
    """Run host `claude` with endpoint env. Returns exit code (Windows) or does
    not return (Unix exec replaces the process)."""
    claude = find_claude()
    if not claude:
        raise FileNotFoundError(
            "claude CLI not found on host. Install: curl -fsSL https://claude.ai/install.sh | bash"
        )
    env = build_host_env(cfg, ep)
    argv = [claude, *args]
    if plat.detect().claude_launch == "exec":
        os.execvpe(claude, argv, env)  # noqa: S606 — intentional process replacement
        return 0  # unreachable
    return subprocess.run(argv, env=env).returncode
