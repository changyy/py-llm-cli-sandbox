"""Command-line interface (Typer).

A thin layer over the package: it parses arguments, calls into the modules
(config, compose, docker_ctl, doctor, claude, ollama), and renders output.
``main()`` is the entry point and turns ``SandboxError`` into a clean message.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import typer

from llm_cli_sandbox import __version__
from llm_cli_sandbox import assets as assets_mod
from llm_cli_sandbox import claude as claude_mod
from llm_cli_sandbox import compose as compose_mod
from llm_cli_sandbox import config as config_mod
from llm_cli_sandbox import docker_ctl
from llm_cli_sandbox import doctor as doctor_mod
from llm_cli_sandbox import ollama as ollama_mod
from llm_cli_sandbox import paths
from llm_cli_sandbox import status as status_mod
from llm_cli_sandbox import sysinfo
from llm_cli_sandbox.doctor import Status
from llm_cli_sandbox.errors import SandboxError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Run Claude Code in a Docker sandbox against a switchable LLM endpoint.",
)

_ICON = {Status.OK: "[OK]  ", Status.WARN: "[WARN]", Status.FAIL: "[FAIL]"}


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"llm-cli-sandbox {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Run Claude Code in a Docker sandbox against a switchable LLM endpoint."""


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"llm-cli-sandbox {__version__}")


@app.command()
def platform(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show detected platform and container runtime."""
    info = sysinfo.detect()
    if as_json:
        data = dataclasses.asdict(info)
        data["host_gateway"] = sysinfo.HOST_GATEWAY_MAPPING
        typer.echo(json.dumps(data, indent=2))
        return
    typer.echo(f"os               : {info.os}")
    typer.echo(f"arch             : {info.arch}")
    typer.echo(f"apple silicon    : {info.is_apple_silicon}")
    typer.echo(f"claude launch    : {info.claude_launch}")
    typer.echo(f"container runtime: {info.container_runtime} ({info.runtime_flavor})")
    typer.echo(f"host gateway     : {sysinfo.HOST_GATEWAY_MAPPING}")


@app.command()
def doctor(
    endpoint: str = typer.Option(None, "--endpoint", "-e", help="Endpoint name to probe."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Check the environment and the selected LLM endpoint."""
    cfg = config_mod.load()
    results = doctor_mod.run_all(cfg, endpoint_name=endpoint)
    failed = sum(r.status is Status.FAIL for r in results)
    warned = sum(r.status is Status.WARN for r in results)

    if as_json:
        payload = {
            "checks": [
                {"name": r.name, "status": r.status.value, "detail": r.detail, "fix": r.fix}
                for r in results
            ],
            "summary": {"ok": len(results) - failed - warned, "warn": warned, "fail": failed},
        }
        typer.echo(json.dumps(payload, indent=2))
        if failed:
            raise typer.Exit(code=1)
        return

    for r in results:
        typer.echo(f"{_ICON[r.status]} {r.name:<18} {r.detail}")
        if r.fix and r.status is not Status.OK:
            typer.echo(f"        -> {r.fix}")
    typer.echo("")
    typer.echo(f"summary: {len(results) - failed - warned} ok, {warned} warn, {failed} fail")
    if failed:
        raise typer.Exit(code=1)


def _resolve_endpoint(cfg: config_mod.Config, name: str | None):
    ep = cfg.get_endpoint(name)
    if ep is None:
        typer.echo(f"endpoint {name or cfg.default_endpoint!r} not found in config.")
        typer.echo("Run `llm-cli-sandbox init` to create a default config.")
        raise typer.Exit(code=2)
    return ep


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config."),
) -> None:
    """Detect platform, write config, and extract Docker assets to ~/.llm-cli-sandbox/."""
    if paths.config_path().exists() and not force:
        typer.echo(f"config already exists at {paths.config_path()} (use --force to overwrite)")
        cfg = config_mod.load()
    else:
        cfg = config_mod.default_config()
        config_mod.save(cfg)
        typer.echo(f"wrote config: {paths.config_path()}")
    dest = assets_mod.extract()
    typer.echo(f"extracted assets: {dest}")
    info = sysinfo.detect()
    typer.echo(f"platform: {info.os}/{info.arch}, runtime: {info.container_runtime}")
    typer.echo(f"default endpoint: {cfg.default_endpoint}")
    typer.echo("next: `llm-cli-sandbox doctor`, then `up` / `shell` / `run`.")


@app.command()
def up(endpoint: str = typer.Option(None, "--endpoint", "-e")) -> None:
    """Start the gateway service for the selected endpoint (if it needs one)."""
    cfg = config_mod.load()
    ep = _resolve_endpoint(cfg, endpoint)
    if not paths.config_path().exists():
        typer.echo("no config yet — run `llm-cli-sandbox init` first.")
        raise typer.Exit(code=2)
    assets_mod.extract()
    workspace = Path.cwd()
    written = compose_mod.write_generated(cfg, ep, workspace)
    typer.echo(f"generated: {', '.join(str(p) for p in written.values())}")
    if not ep.needs_gateway:
        typer.echo(f"endpoint {ep.name!r} is Anthropic-native — no gateway needed.")
        return
    docker_ctl.ensure_gateway_port_free(cfg.gateway.port)
    typer.echo(f"starting litellm gateway on host port {cfg.gateway.port} ...")
    docker_ctl.up_gateway()
    typer.echo(f"gateway up: http://127.0.0.1:{cfg.gateway.port}")


@app.command()
def down() -> None:
    """Stop the gateway service and remove the project's containers/network."""
    if not paths.compose_path().exists():
        typer.echo("nothing to stop (no generated compose file).")
        return
    raise typer.Exit(code=docker_ctl.down())


def _yn(value: bool | None) -> str:
    return {True: "yes", False: "no", None: "n/a"}[value]


@app.command()
def status(
    endpoint: str = typer.Option(None, "--endpoint", "-e"),
    as_json: bool = typer.Option(False, "--json", help="Emit a machine-readable readiness snapshot."),
) -> None:
    """Report environment readiness for launching against the selected endpoint.

    With --json, exits non-zero when not ready (useful as a CI/scripting gate).
    """
    cfg = config_mod.load()
    snap = status_mod.snapshot(cfg, endpoint)

    if as_json:
        typer.echo(json.dumps(snap, indent=2))
        raise typer.Exit(code=0 if snap["ready"] else 1)

    ep = snap["endpoint"]
    typer.echo(f"config    : exists={_yn(snap['config']['exists'])} ({snap['config']['path']})")
    typer.echo(f"docker    : available={_yn(snap['docker']['available'])}")
    typer.echo(f"image     : built={_yn(snap['image']['built'])} ({snap['image']['tag']})")
    typer.echo(f"compose   : generated={_yn(snap['compose']['generated'])}")
    if ep:
        typer.echo(f"endpoint  : {ep['name']} [{ep['type']}] reachable={_yn(ep['reachable'])}")
        typer.echo(f"            {ep['detail']}")
    else:
        typer.echo("endpoint  : (none configured — run `init`)")
    gw = snap["gateway"]
    if gw and gw["needed"]:
        typer.echo(f"gateway   : running={_yn(gw['running'])} ({gw['url']})")
    elif gw:
        typer.echo("gateway   : not needed (anthropic-native endpoint)")
    typer.echo("")
    if snap["ready"]:
        typer.echo("READY — `run` will work against this endpoint.")
    else:
        typer.echo(f"NOT READY — missing: {', '.join(snap['missing'])}")


def _resolve_workspace(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve()


def _prepare(cfg, ep, workspace: Path, *, ensure_gateway: bool = True) -> None:
    """Extract assets, regenerate compose for this workspace, build image if
    missing, and (optionally) bring the gateway up."""
    if not paths.config_path().exists():
        typer.echo("no config yet — run `llm-cli-sandbox init` first.")
        raise typer.Exit(code=2)
    assets_mod.extract()
    compose_mod.write_generated(cfg, ep, workspace)
    if not docker_ctl.image_exists():
        typer.echo("building sandbox image (first run, this takes a few minutes) ...")
        docker_ctl.build("sandbox")
    if ensure_gateway and ep.needs_gateway:
        docker_ctl.ensure_gateway_port_free(cfg.gateway.port)
        typer.echo(f"ensuring litellm gateway is up (host port {cfg.gateway.port}) ...")
        docker_ctl.up_gateway()


@app.command()
def shell(
    workspace: str = typer.Option(".", "--workspace", "-w"),
    endpoint: str = typer.Option(None, "--endpoint", "-e"),
) -> None:
    """Enter the sandbox container (interactive bash) for the selected endpoint."""
    cfg = config_mod.load()
    ep = _resolve_endpoint(cfg, endpoint)
    ws = _resolve_workspace(workspace)
    _prepare(cfg, ep, ws)
    typer.echo(f"entering sandbox: {ws} -> /workspace (endpoint: {ep.name})")
    raise typer.Exit(code=docker_ctl.run_sandbox())


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(
    ctx: typer.Context,
    workspace: str = typer.Option(".", "--workspace", "-w"),
    endpoint: str = typer.Option(None, "--endpoint", "-e"),
    in_container: bool = typer.Option(
        False, "--in-container", help="Run Claude Code inside the sandbox instead of on the host."
    ),
) -> None:
    """Launch Claude Code against the selected endpoint.

    Pass Claude Code arguments after `--`, e.g. `lcs run -- -p "hello"`.
    """
    cfg = config_mod.load()
    ep = _resolve_endpoint(cfg, endpoint)
    claude_args = ctx.args

    if in_container:
        ws = _resolve_workspace(workspace)
        _prepare(cfg, ep, ws)
        typer.echo(f"running claude in sandbox: {ws} -> /workspace (endpoint: {ep.name})")
        raise typer.Exit(code=docker_ctl.run_sandbox(service_cmd=["claude", *claude_args]))

    # Host mode: ensure the gateway is up, then hand off to host claude.
    if ep.needs_gateway:
        _prepare(cfg, ep, _resolve_workspace(workspace), ensure_gateway=True)
    try:
        rc = claude_mod.launch_host(cfg, ep, claude_args)
    except FileNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=127) from exc
    raise typer.Exit(code=rc)


# --- endpoints ---------------------------------------------------------------

endpoints_app = typer.Typer(help="Manage LLM endpoint profiles.", no_args_is_help=True)
app.add_typer(endpoints_app, name="endpoints")

_VALID_TYPES = ("ollama", "openai-compat", "anthropic")


@endpoints_app.command("list")
def endpoints_list() -> None:
    """List configured endpoints."""
    cfg = config_mod.load()
    if not cfg.endpoints:
        typer.echo("(no endpoints configured — run `init`)")
        return
    for name, ep in cfg.endpoints.items():
        mark = "*" if name == cfg.default_endpoint else " "
        target = ep.url or f"{ep.host}:{ep.port}"
        gw = "gateway" if ep.needs_gateway else "direct"
        typer.echo(f" {mark} {name:<16} {ep.type:<14} {target:<28} [{gw}] model={ep.model or '-'}")


@endpoints_app.command("add")
def endpoints_add(
    name: str,
    type: str = typer.Option(..., "--type", "-t", help="ollama | openai-compat | anthropic"),
    url: str = typer.Option(None, "--url", help="Base URL (required for openai-compat/anthropic)."),
    host: str = typer.Option("host", "--host", help="Ollama host ('host' -> host.docker.internal)."),
    port: int = typer.Option(11434, "--port"),
    model: str = typer.Option(None, "--model", "-m"),
    use: bool = typer.Option(False, "--use", help="Also set as the default endpoint."),
) -> None:
    """Add or update an endpoint profile."""
    if type not in _VALID_TYPES:
        typer.echo(f"invalid --type {type!r}; choose one of: {', '.join(_VALID_TYPES)}")
        raise typer.Exit(code=2)
    if type in ("openai-compat", "anthropic") and not url:
        typer.echo(f"--url is required for type {type!r}")
        raise typer.Exit(code=2)
    cfg = config_mod.load()
    cfg.endpoints[name] = config_mod.Endpoint(
        name=name, type=type, host=host, port=port, url=url, model=model
    )
    if use or not cfg.endpoints:
        cfg.default_endpoint = name
    config_mod.save(cfg)
    typer.echo(f"saved endpoint {name!r} ({type}){' [default]' if cfg.default_endpoint == name else ''}")


@endpoints_app.command("rm")
def endpoints_rm(name: str) -> None:
    """Remove an endpoint profile."""
    cfg = config_mod.load()
    if name not in cfg.endpoints:
        typer.echo(f"endpoint {name!r} not found")
        raise typer.Exit(code=2)
    del cfg.endpoints[name]
    config_mod.save(cfg)
    typer.echo(f"removed endpoint {name!r}")


@endpoints_app.command("use")
def endpoints_use(name: str) -> None:
    """Set the default endpoint."""
    cfg = config_mod.load()
    if name not in cfg.endpoints:
        typer.echo(f"endpoint {name!r} not found")
        raise typer.Exit(code=2)
    cfg.default_endpoint = name
    config_mod.save(cfg)
    typer.echo(f"default endpoint is now {name!r}")


# --- models (ollama-type endpoints only) ------------------------------------

models_app = typer.Typer(help="Manage models on an Ollama-type endpoint.", no_args_is_help=True)
app.add_typer(models_app, name="models")


def _ollama_base(endpoint: str | None) -> str:
    cfg = config_mod.load()
    ep = _resolve_endpoint(cfg, endpoint)
    if ep.type != "ollama":
        typer.echo(f"`models` only works with ollama-type endpoints (got {ep.type!r}).")
        raise typer.Exit(code=2)
    return ep.base_url(from_container=False)


@models_app.command("list")
def models_list(endpoint: str = typer.Option(None, "--endpoint", "-e")) -> None:
    """List models available on the endpoint."""
    base = _ollama_base(endpoint)
    try:
        models = ollama_mod.list_models(base)
    except OSError as exc:
        typer.echo(f"could not reach {base}: {exc}")
        raise typer.Exit(code=1) from exc
    if not models:
        typer.echo("(no models)")
        return
    for m in models:
        size_gb = m.get("size", 0) / 1e9
        typer.echo(f"  {m.get('name', '?'):<28} {size_gb:5.1f} GB")


@models_app.command("pull")
def models_pull(name: str, endpoint: str = typer.Option(None, "--endpoint", "-e")) -> None:
    """Pull a model onto the endpoint."""
    base = _ollama_base(endpoint)
    typer.echo(f"pulling {name} from {base} ...")
    last = ""
    try:
        for ev in ollama_mod.pull_model(base, name):
            status = ev.get("status", "")
            if status and status != last:
                typer.echo(f"  {status}")
                last = status
    except OSError as exc:
        typer.echo(f"pull failed: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo("done.")


@models_app.command("rm")
def models_rm(name: str, endpoint: str = typer.Option(None, "--endpoint", "-e")) -> None:
    """Remove a model from the endpoint."""
    base = _ollama_base(endpoint)
    try:
        ollama_mod.remove_model(base, name)
    except OSError as exc:
        typer.echo(f"remove failed: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(f"removed {name}")


def main() -> None:
    """Entry point: run the app, presenting SandboxError cleanly (no traceback)."""
    try:
        app()
    except SandboxError as exc:
        typer.secho(f"error: {exc}", err=True, fg=typer.colors.RED)
        if exc.hint:
            typer.secho(f"hint: {exc.hint}", err=True, fg=typer.colors.YELLOW)
        raise SystemExit(exc.exit_code) from None


if __name__ == "__main__":
    main()
