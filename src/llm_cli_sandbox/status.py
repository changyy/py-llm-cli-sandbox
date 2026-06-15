"""Runtime readiness snapshot.

Assembles a machine-readable picture of whether everything needed to launch
Claude Code is in place: config present, docker available, sandbox image built,
the selected endpoint reachable, and (when required) the gateway running. The
``ready`` flag is the AND of the parts that actually matter for the chosen
endpoint — scripts/CI can gate on it.
"""

from __future__ import annotations

from llm_cli_sandbox import compose, docker_ctl, paths
from llm_cli_sandbox.config import Config
from llm_cli_sandbox.doctor import Status, check_endpoint


def snapshot(cfg: Config, endpoint_name: str | None = None) -> dict:
    ep = cfg.get_endpoint(endpoint_name)
    docker_ok = docker_ctl.docker_available()

    snap: dict = {
        "config": {"exists": paths.config_path().exists(), "path": str(paths.config_path())},
        "docker": {"available": docker_ok},
        "compose": {"generated": paths.compose_path().exists()},
        "image": {
            "tag": compose.IMAGE_TAG,
            "built": docker_ctl.image_exists() if docker_ok else False,
        },
        "endpoint": None,
        "gateway": None,
        "ready": False,
        "missing": [],
    }

    if ep is None:
        snap["missing"].append("endpoint")
        return snap

    ep_check = check_endpoint(ep)
    reachable = ep_check.status is Status.OK
    snap["endpoint"] = {
        "name": ep.name,
        "type": ep.type,
        "needs_gateway": ep.needs_gateway,
        "reachable": reachable,
        "detail": ep_check.detail,
    }

    gateway_ok = True
    if ep.needs_gateway:
        running = docker_ctl.container_running(docker_ctl.GATEWAY_CONTAINER) if docker_ok else False
        gateway_ok = running
        snap["gateway"] = {
            "needed": True,
            "running": running,
            "port": cfg.gateway.port,
            "url": f"http://127.0.0.1:{cfg.gateway.port}",
        }
    else:
        snap["gateway"] = {"needed": False, "running": None}

    # Compute what's missing for a launch against this endpoint.
    missing = snap["missing"]
    if not docker_ok:
        missing.append("docker")
    if not snap["image"]["built"]:
        missing.append("image")
    if not reachable:
        missing.append("endpoint-reachable")
    if ep.needs_gateway and not gateway_ok:
        missing.append("gateway")

    snap["ready"] = not missing
    return snap
