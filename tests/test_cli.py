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


def test_home_override_isolates_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    assert (tmp_path / "config.toml").exists()
    assert (tmp_path / "assets" / "Dockerfile").exists()
