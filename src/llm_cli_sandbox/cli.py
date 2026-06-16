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
from llm_cli_sandbox import probe as probe_mod
from llm_cli_sandbox import status as status_mod
from llm_cli_sandbox import sysinfo
from llm_cli_sandbox import update as update_mod
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


_QUICKSTART = """\
llm-cli-sandbox — common workflows  (aliases: lcs / llm-cli)

Setup
  lcs init                      # write config + extract Docker assets
  lcs doctor                    # check docker, endpoint, auth  (--json for CI)
  lcs up                        # start the litellm gateway (if the endpoint needs one)
  lcs status                    # is everything ready to launch?
  lcs ping                      # send a tiny prompt; does the model actually reply?

Work inside the sandbox
  lcs shell                     # drop into the sandbox container (cwd -> /workspace)
  lcs shell -w ~/code/my-app    # mount a specific workspace

Run Claude Code  (its args go after `--`)
  lcs run -- -p "hello"              # on the host, via the gateway
  lcs run --in-container -- -p "hi"  # inside the sandbox (non-root)

Switch endpoint / model
  lcs endpoints list
  lcs endpoints add lan --type openai-compat --url http://10.0.0.5:8000/v1 -m qwen --use
  lcs endpoints use local-ollama
  lcs models catalog            # common models (marks installed ones)
  lcs models pull qwen2.5-coder:7b
  lcs models use  qwen2.5-coder:7b   # set the model this endpoint uses
"""


@app.command()
def quickstart() -> None:
    """Print a typical end-to-end workflow with copy-pasteable examples."""
    typer.echo(_QUICKSTART)


def _update_from(source: str, *, yes: bool) -> None:
    """Install from a chosen source (local path / wheel / git URL) via pip.

    This DOES modify the environment, so it confirms first unless --yes.
    """
    target = "(unknown)"
    if update_mod.classify_source(source) == "local":
        path = Path(source).expanduser().resolve()
        err = update_mod.local_source_error(path)
        if err:
            typer.echo(f"cannot install from {source!r}: {err}")
            raise typer.Exit(code=2)
        source = str(path)
        target = update_mod.local_source_version(path) or "(unknown)"

    argv = update_mod.install_argv(source)
    typer.echo(f"current: {__version__}")
    typer.echo(f"target : {target}  [from {source}]")
    typer.echo(f"will run: {' '.join(argv)}")
    if not yes and not typer.confirm("proceed?", default=False):
        typer.echo("aborted.")
        raise typer.Exit(code=1)
    rc = update_mod.run_install(source)
    if rc == 0:
        typer.echo("\nupdated — re-run your command to use the new version.")
    raise typer.Exit(code=rc)


@app.command()
def update(
    from_source: str = typer.Option(
        None, "--from",
        help="Install from a local path, wheel/sdist, or git URL instead of checking PyPI.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt for --from."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Check PyPI for a newer release, or install from a chosen --from source.

    Without --from this is read-only: it shows the upgrade command for the
    detected install method (pip / pipx / editable). With --from it installs from
    the given source after confirmation.
    """
    if from_source:
        _update_from(from_source, yes=yes)
        return

    latest = update_mod.latest_version()
    newer = bool(latest and update_mod.is_newer(latest))
    hint = update_mod.upgrade_hint()

    if as_json:
        typer.echo(json.dumps(
            {"current": __version__, "latest": latest, "update_available": newer, "upgrade": hint},
            indent=2,
        ))
        return

    typer.echo(f"current: {__version__}")
    if latest is None:
        typer.echo("latest : (could not reach PyPI/GitHub — offline?)")
        return
    typer.echo(f"latest : {latest}")
    if newer:
        typer.echo(f"\nA newer version is available. Upgrade with:\n  {hint}")
    else:
        typer.echo("\nYou are on the latest version.")


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
    _preflight_model(ep)
    assets_mod.extract()
    workspace = Path.cwd()
    recreate = _litellm_config_changed(ep)
    written = compose_mod.write_generated(cfg, ep, workspace)
    typer.echo(f"generated: {', '.join(str(p) for p in written.values())}")
    if not ep.needs_gateway:
        typer.echo(f"endpoint {ep.name!r} is Anthropic-native — no gateway needed.")
        return
    docker_ctl.ensure_gateway_port_free(cfg.gateway.port)
    verb = "recreating" if recreate else "starting"
    typer.echo(f"{verb} litellm gateway on host port {cfg.gateway.port} ...")
    docker_ctl.up_gateway(force_recreate=recreate)
    _mark_litellm_applied(ep)
    typer.echo(f"gateway up: http://127.0.0.1:{cfg.gateway.port}")


@app.command()
def down() -> None:
    """Stop the gateway service and remove the project's containers/network."""
    if not paths.compose_path().exists():
        typer.echo("nothing to stop (no generated compose file).")
        return
    rc = docker_ctl.down()
    paths.litellm_applied_path().unlink(missing_ok=True)  # gateway gone; forget its config
    raise typer.Exit(code=rc)


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


def _describe_probe_error(exc: Exception) -> str:
    import urllib.error

    if isinstance(exc, urllib.error.HTTPError):
        body = exc.read().decode(errors="replace").strip().replace("\n", " ")
        return f"HTTP {exc.code}: {body[:160]}"
    return str(getattr(exc, "reason", exc))


def _trunc(text: str, n: int = 80) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


@app.command()
def ping(
    endpoint: str = typer.Option(None, "--endpoint", "-e"),
    no_tools: bool = typer.Option(False, "--no-tools", help="Skip the tool-calling check."),
    as_json: bool = typer.Option(False, "--json", help="Emit a machine-readable report."),
) -> None:
    """Send a tiny prompt and report the reply — a functional round-trip.

    On top of `doctor`/`status` (which check reachability), this confirms the
    model actually works for Claude Code: a `direct` hit to the model, the
    `gateway` path Claude Code uses, and a `tools` check that the model returns a
    structured tool_use (which Claude Code requires — `--no-tools` to skip).
    Exits non-zero if the path Claude would use fails.
    """
    import time

    cfg = config_mod.load()
    ep = _resolve_endpoint(cfg, endpoint)
    checks: list[dict] = []

    def timed(name: str, fn) -> None:
        t0 = time.perf_counter()
        try:
            reply = fn()
            checks.append(
                {"name": name, "ok": True, "seconds": round(time.perf_counter() - t0, 2), "reply": reply}
            )
        except (OSError, ValueError) as exc:
            checks.append(
                {"name": name, "ok": False, "seconds": round(time.perf_counter() - t0, 2),
                 "error": _describe_probe_error(exc)}
            )

    if not ep.model and ep.type != "anthropic":
        typer.echo(f"endpoint {ep.name!r} has no model set — `lcs models use <name>` first.")
        raise typer.Exit(code=2)

    # 1. Direct to the model (ollama only) — isolates model from gateway and
    # reports Ollama's own load-vs-generate split so a cold start is obvious.
    if ep.type == "ollama":
        base = ep.base_url(from_container=False)
        try:
            cold = ep.model not in ollama_mod.loaded_model_names(base)
        except OSError:
            cold = None
        t0 = time.perf_counter()
        try:
            r = ollama_mod.chat(base, ep.model)
            checks.append({
                "name": "direct", "ok": True, "seconds": round(time.perf_counter() - t0, 2),
                "reply": r.reply, "load_seconds": r.load_seconds, "gen_seconds": r.eval_seconds,
                "cold": cold,
            })
        except (OSError, ValueError) as exc:
            checks.append({"name": "direct", "ok": False,
                           "seconds": round(time.perf_counter() - t0, 2),
                           "error": _describe_probe_error(exc)})

    # 2. The path Claude Code actually uses.
    if ep.needs_gateway:
        primary = "gateway"
        probe_url = compose_mod.gateway_url(cfg, from_container=False)
        if not docker_ctl.container_running(docker_ctl.GATEWAY_CONTAINER):
            checks.append({"name": "gateway", "ok": False, "error": "gateway not running (run `lcs up`)"})
        elif _litellm_config_changed(ep):
            checks.append({"name": "gateway", "ok": False,
                           "error": "running an older config — run `lcs up` to reload it for this model"})
        else:
            timed("gateway", lambda: probe_mod.anthropic_messages(probe_url, ep.model))
    else:
        primary = "endpoint"
        probe_url = ep.base_url(from_container=False)
        timed("endpoint", lambda: probe_mod.anthropic_messages(probe_url, ep.model or ""))

    primary_ok = any(c["name"] == primary and c["ok"] for c in checks)

    # 3. Tool-calling — Claude Code is tool-driven; a model that replies in text
    # instead of a tool_use block can't drive it. Only worth testing if the path
    # itself works.
    if not no_tools and primary_ok:
        t0 = time.perf_counter()
        try:
            used = probe_mod.anthropic_tool_call(probe_url, ep.model or "")
            checks.append({
                "name": "tools", "ok": used, "seconds": round(time.perf_counter() - t0, 2),
                "detail": "tool_use returned" if used else "replied with text, not a tool_use block",
            })
        except (OSError, ValueError) as exc:
            checks.append({"name": "tools", "ok": False, "seconds": round(time.perf_counter() - t0, 2),
                           "error": _describe_probe_error(exc)})

    tools_check = next((c for c in checks if c["name"] == "tools"), None)
    ready = primary_ok and (no_tools or (tools_check is not None and tools_check["ok"]))

    if as_json:
        typer.echo(json.dumps(
            {"endpoint": ep.name, "type": ep.type, "model": ep.model, "checks": checks, "ready": ready},
            indent=2,
        ))
        raise typer.Exit(code=0 if ready else 1)

    _COLD = {True: " [cold]", False: " [loaded]", None: ""}
    typer.echo(f"endpoint : {ep.name} [{ep.type}] {ep.base_url(from_container=False)}")
    typer.echo(f"model    : {ep.model or '(default)'}")
    for c in checks:
        if not c["ok"]:
            secs = f" ({c['seconds']}s)" if "seconds" in c else ""
            typer.echo(f"{c['name']:<9}: FAIL{secs} {c.get('error') or c.get('detail', '')}")
        elif "load_seconds" in c:  # ollama direct: show load-vs-generate split
            timing = f"load {c['load_seconds']}s + gen {c['gen_seconds']}s"
            typer.echo(f"{c['name']:<9}: OK ({timing}){_COLD[c['cold']]} \"{_trunc(c['reply'])}\"")
        elif "detail" in c:  # tools check
            typer.echo(f"{c['name']:<9}: OK ({c['seconds']}s) {c['detail']}")
        else:
            typer.echo(f"{c['name']:<9}: OK ({c['seconds']}s) \"{_trunc(c['reply'])}\"")
    typer.echo("")
    slow = next((c for c in checks if c.get("ok") and c.get("load_seconds", 0) > 5), None)
    if slow:
        typer.echo(
            f"note: {slow['load_seconds']}s of that was model load, not generation — "
            "keep it warm (OLLAMA_KEEP_ALIVE) or check memory pressure."
        )
    if tools_check and not tools_check["ok"] and "error" not in tools_check:
        typer.echo(
            "note: model returns tool calls as text, not tool_use — Claude Code can't drive it. "
            "Try a tool-calling model, e.g. `lcs models use gpt-oss:20b`."
        )
    typer.echo("READY" if ready else "NOT OK")
    if not ready:
        raise typer.Exit(code=1)


def _resolve_workspace(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve()


def _litellm_config_changed(ep) -> bool:
    """True if the desired gateway config differs from what the running gateway
    last loaded (so the container must be recreated, not just `up -d`).

    litellm reads its config only at startup, so comparing against the *applied*
    marker — not the live config file, which `write_generated` may have already
    overwritten — is what catches a pending change (e.g. after `models use`). A
    missing marker counts as changed, which also recovers a gateway started
    before this tracking existed.
    """
    if not ep.needs_gateway:
        return False
    applied = paths.litellm_applied_path()
    if not applied.exists():
        return True
    return applied.read_text() != compose_mod.render_litellm_config(ep)


def _mark_litellm_applied(ep) -> None:
    """Record the config the gateway now has, after a successful (re)start."""
    if not ep.needs_gateway:
        return
    path = paths.litellm_applied_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compose_mod.render_litellm_config(ep))


def _reload_gateway_if_running(ep) -> None:
    """If the gateway is live and its config drifted, reload it in place.

    Lets `models use` take effect immediately: litellm only reads its config at
    startup, so a model switch otherwise sits stale until the next launch.
    """
    if not (ep.needs_gateway and paths.compose_path().exists()):
        return
    if not docker_ctl.container_running(docker_ctl.GATEWAY_CONTAINER):
        return
    if not _litellm_config_changed(ep):
        return
    paths.litellm_config_path().write_text(compose_mod.render_litellm_config(ep))
    typer.echo("reloading the running gateway with the new model ...")
    docker_ctl.up_gateway(force_recreate=True)
    _mark_litellm_applied(ep)


def _preflight_model(ep) -> None:
    """Fail early if an Ollama endpoint's selected model isn't installed.

    Turns the cryptic gateway-side "no healthy deployments for this model" into
    an actionable message before launch. Best-effort: if the endpoint can't be
    reached we don't block here (reachability is reported by doctor/launch).
    """
    if ep.type != "ollama" or not ep.model:
        return
    base = ep.base_url(from_container=False)
    try:
        present = ollama_mod.model_installed(base, ep.model)
    except OSError:
        return
    if not present:
        typer.echo(f"model {ep.model!r} is not installed on endpoint {ep.name!r} ({base}).")
        typer.echo(f"  -> `lcs models pull {ep.model}`  (or `lcs models use {ep.model} --pull`)")
        raise typer.Exit(code=2)


def _prepare(cfg, ep, workspace: Path, *, ensure_gateway: bool = True) -> None:
    """Extract assets, regenerate compose for this workspace, build image if
    missing, and (optionally) bring the gateway up."""
    if not paths.config_path().exists():
        typer.echo("no config yet — run `llm-cli-sandbox init` first.")
        raise typer.Exit(code=2)
    _preflight_model(ep)
    assets_mod.extract()
    recreate = _litellm_config_changed(ep)
    compose_mod.write_generated(cfg, ep, workspace)
    if not docker_ctl.image_exists():
        typer.echo("building sandbox image (first run, this takes a few minutes) ...")
        docker_ctl.build("sandbox")
    if ensure_gateway and ep.needs_gateway:
        docker_ctl.ensure_gateway_port_free(cfg.gateway.port)
        action = "recreating" if recreate else "ensuring"
        typer.echo(f"{action} litellm gateway (host port {cfg.gateway.port}) ...")
        docker_ctl.up_gateway(force_recreate=recreate)
        _mark_litellm_applied(ep)


@app.command()
def shell(
    workspace: str = typer.Option(".", "--workspace", "-w"),
    endpoint: str = typer.Option(None, "--endpoint", "-e"),
) -> None:
    """Enter the sandbox container (interactive bash) for the selected endpoint.

    This is "work in place inside Docker": the workspace is mounted at
    /workspace and you get a non-root shell. Example: `lcs shell -w ~/code/app`.
    """
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
    """List installed models, flagging tool-calling support for known ones."""
    base = _ollama_base(endpoint)
    try:
        models = ollama_mod.list_models(base)
    except OSError as exc:
        typer.echo(f"could not reach {base}: {exc}")
        raise typer.Exit(code=1) from exc
    if not models:
        typer.echo("(no models — see `lcs models catalog` for recommendations)")
        return
    for m in models:
        name = m.get("name", "?")
        size_gb = m.get("size", 0) / 1e9
        cap = ollama_mod.tool_capability(name)
        tools = {True: "  tools ✓", False: "  tools -", None: ""}[cap]
        typer.echo(f"  {name:<28} {size_gb:5.1f} GB{tools}")
    typer.echo("")
    typer.echo("tip: `lcs models catalog` lists recommended tool-calling models + RAM needs.")


@models_app.command("catalog")
def models_catalog(endpoint: str = typer.Option(None, "--endpoint", "-e")) -> None:
    """Show a curated shortlist of common models, flagging tool-calling support.

    `tools` marks models that emit structured tool calls — required for Claude
    Code. Models without it work for plain chat but can't drive Claude Code.
    """
    base = _ollama_base(endpoint)
    installed: set[str] = set()
    try:
        installed = {m.get("name") for m in ollama_mod.list_models(base)}
    except OSError:
        typer.echo(f"(could not reach {base} — install status unknown)\n")

    ram = sysinfo.total_ram_gb()
    disk = sysinfo.free_disk_gb()
    host = []
    if ram:
        host.append(f"{ram:.0f} GB RAM")
    if disk:
        host.append(f"{disk:.0f} GB free disk")
    if host:
        typer.echo(f"host     : {', '.join(host)}")

    typer.echo(f"  {'tools':<5} {'model':<22} {'disk':>8} {'RAM':>6}  note")
    for name, size, ram_need, tool_use, note in ollama_mod.RECOMMENDED_MODELS:
        flag = " ✓ " if tool_use else " - "
        over = "  (> your RAM)" if ram and ram_need > ram else ""
        mark = "  [installed]" if name in installed else ""
        typer.echo(f"  {flag:<5} {name:<22} {size:>8} {ram_need:>4} GB  {note}{mark}{over}")
    typer.echo("")
    typer.echo("'tools ✓' = drives Claude Code (verify a given setup with `lcs ping`).")
    typer.echo("pull one with `lcs models pull <name>`, then `lcs models use <name>`.")


@models_app.command("use")
def models_use(
    name: str,
    endpoint: str = typer.Option(None, "--endpoint", "-e"),
    pull: bool = typer.Option(False, "--pull", help="Pull the model now if it isn't installed."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes to the pull prompt."),
) -> None:
    """Set the model an Ollama-type endpoint should use.

    After saving, it checks whether the model is installed on the endpoint and
    offers to pull it if not (best-effort — silently skips if unreachable).
    """
    cfg = config_mod.load()
    ep = _resolve_endpoint(cfg, endpoint)
    if ep.type != "ollama":
        typer.echo(f"`models use` only works with ollama-type endpoints (got {ep.type!r}).")
        raise typer.Exit(code=2)
    ep.model = name
    config_mod.save(cfg)
    typer.echo(f"endpoint {ep.name!r} now uses model {name!r}")

    # Hardware sanity for a host-local model (the 'slow first load' trap).
    if ep.host in ("host", "localhost", "127.0.0.1"):
        need = ollama_mod.recommended_ram(name)
        have = sysinfo.total_ram_gb()
        if need and have and have < need:
            typer.echo(
                f"⚠ {name} suggests ~{need} GB RAM; this host has {have:.0f} GB — "
                "expect heavy swapping and slow loads."
            )
        if ollama_mod.tool_capability(name) is False:
            typer.echo("⚠ this model does not emit tool calls — Claude Code won't be able to drive it.")

    base = ep.base_url(from_container=False)
    try:
        present = ollama_mod.model_installed(base, name)
    except OSError:
        typer.echo(f"(could not reach {base} to verify — `lcs models pull {name}` when ready)")
        return
    if present:
        typer.echo("✓ model is installed on the endpoint.")
        _reload_gateway_if_running(ep)
        return
    typer.echo(f"! {name} is not installed on the endpoint.")
    if pull or yes or typer.confirm(f"pull {name} now?", default=False):
        _pull_model(base, name)
        _reload_gateway_if_running(ep)
    else:
        typer.echo(f"skipped — pull it later with `lcs models pull {name}`.")


def _pull_model(base: str, name: str) -> None:
    """Stream a model pull, echoing distinct progress states."""
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


@models_app.command("pull")
def models_pull(name: str, endpoint: str = typer.Option(None, "--endpoint", "-e")) -> None:
    """Pull a model onto the endpoint."""
    _pull_model(_ollama_base(endpoint), name)


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
