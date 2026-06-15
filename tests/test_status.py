import json

from typer.testing import CliRunner

from llm_cli_sandbox import status as status_mod
from llm_cli_sandbox.cli import app
from llm_cli_sandbox.config import Endpoint, default_config

runner = CliRunner()


def test_snapshot_shape_for_default_config():
    snap = status_mod.snapshot(default_config())
    for key in ("config", "docker", "compose", "image", "endpoint", "gateway", "ready", "missing"):
        assert key in snap
    assert isinstance(snap["ready"], bool)
    assert isinstance(snap["missing"], list)
    assert snap["endpoint"]["needs_gateway"] is True


def test_snapshot_anthropic_endpoint_has_no_gateway():
    cfg = default_config()
    cfg.endpoints["a"] = Endpoint(name="a", type="anthropic", url="https://proxy.internal")
    cfg.default_endpoint = "a"
    snap = status_mod.snapshot(cfg)
    assert snap["gateway"]["needed"] is False
    # gateway should never be the missing item for an anthropic endpoint
    assert "gateway" not in snap["missing"]


def test_status_json_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CLI_SANDBOX_HOME", str(tmp_path))
    result = runner.invoke(app, ["status", "--json"])
    data = json.loads(result.stdout)
    assert "ready" in data and "missing" in data
    # exit code mirrors readiness
    assert result.exit_code == (0 if data["ready"] else 1)
