import json

from typer.testing import CliRunner

from llm_cli_sandbox.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "llm-cli-sandbox" in result.stdout


def test_platform_json():
    result = runner.invoke(app, ["platform", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "os" in data and "arch" in data and "host_gateway" in data


def test_doctor_json_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    # Keep the update check hermetic (no real PyPI call during tests).
    from llm_cli_sandbox import update as update_mod

    monkeypatch.setattr(update_mod, "latest_version", lambda *a, **k: None)
    result = runner.invoke(app, ["doctor", "--json"])
    # Exit code depends on the environment (docker may be absent in CI); the
    # contract we assert is a well-formed JSON document.
    data = json.loads(result.stdout)
    assert "checks" in data and "summary" in data
    assert all("name" in c and "status" in c for c in data["checks"])


def test_endpoints_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    assert runner.invoke(app, ["init"]).exit_code == 0

    add = runner.invoke(
        app,
        ["endpoints", "add", "lan", "--type", "openai-compat",
         "--url", "http://10.0.0.5:8000/v1", "-m", "qwen", "--use"],
    )
    assert add.exit_code == 0

    listing = runner.invoke(app, ["endpoints", "list"])
    assert "lan" in listing.stdout and "local-ollama" in listing.stdout

    assert runner.invoke(app, ["endpoints", "use", "local-ollama"]).exit_code == 0
    assert runner.invoke(app, ["endpoints", "rm", "lan"]).exit_code == 0
    assert "lan" not in runner.invoke(app, ["endpoints", "list"]).stdout


def test_endpoints_add_rejects_bad_type(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["endpoints", "add", "x", "--type", "bogus"])
    assert result.exit_code != 0


def test_quickstart_shows_examples():
    result = runner.invoke(app, ["quickstart"])
    assert result.exit_code == 0
    assert "lcs shell" in result.stdout and "models use" in result.stdout


def test_models_use_sets_endpoint_model(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    from llm_cli_sandbox import ollama as ollama_mod

    monkeypatch.setattr(ollama_mod, "model_installed", lambda *a, **k: True)
    result = runner.invoke(app, ["models", "use", "qwen2.5-coder:7b"])
    assert result.exit_code == 0
    assert "installed" in result.stdout
    from llm_cli_sandbox.config import load

    assert load().get_endpoint().model == "qwen2.5-coder:7b"


def test_models_use_offers_pull_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    from llm_cli_sandbox import ollama as ollama_mod

    pulled = {}
    monkeypatch.setattr(ollama_mod, "model_installed", lambda *a, **k: False)

    def fake_pull(base, name):
        pulled["name"] = name
        return iter([{"status": "success"}])

    monkeypatch.setattr(ollama_mod, "pull_model", fake_pull)
    # --pull skips the prompt and pulls the missing model (chained action).
    result = runner.invoke(app, ["models", "use", "qwen2.5-coder:7b", "--pull"])
    assert result.exit_code == 0
    assert pulled["name"] == "qwen2.5-coder:7b"


def test_models_use_unreachable_is_non_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    from llm_cli_sandbox import ollama as ollama_mod

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(ollama_mod, "model_installed", boom)
    result = runner.invoke(app, ["models", "use", "qwen2.5-coder:7b"])
    assert result.exit_code == 0
    assert "could not reach" in result.stdout


def test_preflight_blocks_missing_model(monkeypatch):
    from llm_cli_sandbox import cli
    from llm_cli_sandbox import ollama as ollama_mod
    from llm_cli_sandbox.config import default_config

    ep = default_config().get_endpoint()  # ollama, has a model
    monkeypatch.setattr(ollama_mod, "model_installed", lambda *a, **k: False)
    import typer

    try:
        cli._preflight_model(ep)
    except typer.Exit as exc:
        assert exc.exit_code == 2
    else:
        raise AssertionError("expected preflight to block")

    monkeypatch.setattr(ollama_mod, "model_installed", lambda *a, **k: True)
    cli._preflight_model(ep)  # installed -> no raise

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(ollama_mod, "model_installed", boom)
    cli._preflight_model(ep)  # unreachable -> do not block


def test_models_use_rejects_non_ollama(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    runner.invoke(
        app,
        ["endpoints", "add", "prox", "--type", "anthropic",
         "--url", "https://proxy.internal", "--use"],
    )
    result = runner.invoke(app, ["models", "use", "whatever"])
    assert result.exit_code != 0
    assert "ollama-type" in result.stdout


def test_models_catalog_lists_recommendations(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    # Endpoint is unreachable in tests; catalog still prints the shortlist.
    result = runner.invoke(app, ["models", "catalog"])
    assert result.exit_code == 0
    assert "qwen2.5-coder:7b" in result.stdout
    assert "gpt-oss:20b" in result.stdout
    assert "tools" in result.stdout  # capability column/legend
    assert "RAM" in result.stdout  # hardware column
    assert "drives Claude Code" in result.stdout


def test_models_use_warns_on_insufficient_ram(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    from llm_cli_sandbox import ollama as ollama_mod, sysinfo

    monkeypatch.setattr(ollama_mod, "model_installed", lambda *a, **k: True)
    monkeypatch.setattr(sysinfo, "total_ram_gb", lambda: 4.0)
    result = runner.invoke(app, ["models", "use", "gpt-oss:20b"])  # suggests ~16 GB
    assert result.exit_code == 0
    assert "swapping" in result.stdout


def test_litellm_config_change_detection(tmp_path, monkeypatch):
    # Reproduces the `models use` bug: the running litellm gateway only reads its
    # config at startup, so a changed config must force a recreate. Detection is
    # against the "applied" marker (what the gateway loaded), not the live file.
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    from llm_cli_sandbox import cli
    from llm_cli_sandbox.config import default_config

    ep = default_config().get_endpoint()  # ollama, gpt-oss:20b
    assert cli._litellm_config_changed(ep) is True  # no applied marker yet

    cli._mark_litellm_applied(ep)
    assert cli._litellm_config_changed(ep) is False  # gateway has this config

    ep.model = "qwen2.5-coder:7b"
    assert cli._litellm_config_changed(ep) is True  # model switched -> recreate

    cli._mark_litellm_applied(ep)  # gateway recreated with the new model
    assert cli._litellm_config_changed(ep) is False


def _patch_ping(monkeypatch, *, gateway_running=True, direct="pong", gateway="pong", load_s=0.1,
                tool_use=True, gateway_stale=False):
    from llm_cli_sandbox import cli as cli_mod, docker_ctl, ollama as ollama_mod, probe as probe_mod

    monkeypatch.setattr(
        ollama_mod, "chat",
        lambda *a, **k: ollama_mod.ChatResult(
            reply=direct, load_seconds=load_s, eval_seconds=0.1, total_seconds=load_s + 0.1, eval_count=3
        ),
    )
    monkeypatch.setattr(ollama_mod, "loaded_model_names", lambda *a, **k: set())
    monkeypatch.setattr(probe_mod, "anthropic_messages", lambda *a, **k: gateway)
    monkeypatch.setattr(probe_mod, "anthropic_tool_call", lambda *a, **k: tool_use)
    monkeypatch.setattr(docker_ctl, "container_running", lambda *a, **k: gateway_running)
    monkeypatch.setattr(cli_mod, "_litellm_config_changed", lambda ep: gateway_stale)


def test_ping_reports_both_layers(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    _patch_ping(monkeypatch, direct="pong-d", gateway="pong-g")
    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 0
    assert "direct" in result.stdout and "pong-d" in result.stdout
    assert "gateway" in result.stdout and "pong-g" in result.stdout
    assert "tools" in result.stdout
    assert "READY" in result.stdout


def test_ping_tool_failure_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    _patch_ping(monkeypatch, tool_use=False)
    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 1
    assert "tools" in result.stdout
    assert "NOT OK" in result.stdout
    assert "gpt-oss" in result.stdout  # switch-model hint


def test_ping_flags_stale_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    _patch_ping(monkeypatch, gateway_stale=True)
    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 1
    assert "older config" in result.stdout and "lcs up" in result.stdout
    assert "NOT OK" in result.stdout


def test_ping_no_tools_skips_the_check(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    _patch_ping(monkeypatch, tool_use=False)  # would fail, but skipped
    result = runner.invoke(app, ["ping", "--no-tools"])
    assert result.exit_code == 0
    assert "READY" in result.stdout
    assert "tools" not in result.stdout


def test_ping_fails_when_gateway_down(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    _patch_ping(monkeypatch, gateway_running=False)
    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 1
    assert "gateway not running" in result.stdout
    assert "NOT OK" in result.stdout


def test_ping_gateway_error_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    from llm_cli_sandbox import docker_ctl, probe as probe_mod

    _patch_ping(monkeypatch, gateway_running=True)

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(probe_mod, "anthropic_messages", boom)
    monkeypatch.setattr(docker_ctl, "container_running", lambda *a, **k: True)
    result = runner.invoke(app, ["ping", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ready"] is False
    gw = [c for c in data["checks"] if c["name"] == "gateway"][0]
    assert gw["ok"] is False


def test_ping_flags_slow_model_load(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    _patch_ping(monkeypatch, load_s=39.8)
    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 0
    assert "load 39.8s" in result.stdout
    assert "[cold]" in result.stdout  # loaded_model_names patched to empty set
    assert "model load, not generation" in result.stdout


def test_home_override_isolates_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    assert (tmp_path / "config.toml").exists()
    assert (tmp_path / "assets" / "Dockerfile").exists()
