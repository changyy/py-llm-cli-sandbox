"""Platform and runtime detection.

The whole point of this layer is to keep OS/arch differences in one place so the
rest of the tool can stay platform-agnostic. The key differences we care about:

- ``host.docker.internal``: built-in on Docker Desktop (macOS/Windows), but on
  Linux it must be injected via ``extra_hosts: host.docker.internal:host-gateway``.
- Launching Claude Code: Unix can ``os.execvp`` (replace the process); Windows has
  no ``exec`` and must spawn a subprocess and forward the exit code.
"""

from __future__ import annotations

import os
import platform as stdlib_platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Inject this on every generated compose file. Required on Linux, harmless on
# Docker Desktop, so the "reach a service on this host" path collapses to one.
HOST_GATEWAY_MAPPING = "host.docker.internal:host-gateway"


@dataclass(frozen=True)
class PlatformInfo:
    os: str  # "darwin" | "linux" | "windows"
    arch: str  # "arm64" | "x86_64" | ...
    is_apple_silicon: bool
    claude_launch: str  # "exec" (unix) | "subprocess" (windows)
    container_runtime: str | None  # "docker" | "podman" | None
    runtime_flavor: str | None  # "docker-desktop" | "orbstack" | "podman" | "docker-engine" | None

    @property
    def supported(self) -> bool:
        return self.os in ("darwin", "linux", "windows")


def _normalize_os(raw: str) -> str:
    raw = raw.lower()
    if raw.startswith("darwin"):
        return "darwin"
    if raw.startswith("win"):
        return "windows"
    if raw.startswith("linux"):
        return "linux"
    return raw


def _detect_runtime() -> tuple[str | None, str | None]:
    """Return (runtime, flavor). Prefers docker, falls back to podman."""
    if shutil.which("docker"):
        flavor = "docker-engine"
        try:
            out = subprocess.run(
                ["docker", "info", "--format", "{{.Name}} {{.OperatingSystem}}"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.lower()
            if "orbstack" in out:
                flavor = "orbstack"
            elif "docker desktop" in out:
                flavor = "docker-desktop"
        except (subprocess.SubprocessError, OSError):
            pass
        return "docker", flavor
    if shutil.which("podman"):
        return "podman", "podman"
    return None, None


def total_ram_gb() -> float | None:
    """Total physical RAM in GB (decimal), or None if it can't be determined."""
    try:  # macOS and Linux
        return round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1e9, 1)
    except (ValueError, OSError, AttributeError):
        pass
    try:  # Windows
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = _MemStatus()
        stat.dwLength = ctypes.sizeof(_MemStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        return round(stat.ullTotalPhys / 1e9, 1)
    except (OSError, AttributeError, ValueError):
        return None


def free_disk_gb(path: str | None = None) -> float | None:
    """Free disk space in GB (decimal) at ``path`` (default: home), or None."""
    try:
        return round(shutil.disk_usage(path or str(Path.home())).free / 1e9, 1)
    except OSError:
        return None


def detect() -> PlatformInfo:
    os_name = _normalize_os(stdlib_platform.system())
    machine = stdlib_platform.machine().lower()
    arch = {"aarch64": "arm64", "amd64": "x86_64"}.get(machine, machine)
    is_apple_silicon = os_name == "darwin" and arch == "arm64"
    claude_launch = "subprocess" if os_name == "windows" else "exec"
    runtime, flavor = _detect_runtime()
    return PlatformInfo(
        os=os_name,
        arch=arch,
        is_apple_silicon=is_apple_silicon,
        claude_launch=claude_launch,
        container_runtime=runtime,
        runtime_flavor=flavor,
    )
