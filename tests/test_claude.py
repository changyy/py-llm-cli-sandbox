import pytest

from llm_cli_sandbox import claude as claude_mod
from llm_cli_sandbox.config import default_config
from llm_cli_sandbox.sysinfo import PlatformInfo


def _info(launch: str) -> PlatformInfo:
    return PlatformInfo(
        os="linux" if launch == "exec" else "windows",
        arch="x86_64",
        is_apple_silicon=False,
        claude_launch=launch,
        container_runtime="docker",
        runtime_flavor="docker-engine",
    )


def test_build_host_env_uses_auth_token_not_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-be-removed")
    cfg = default_config()
    env = claude_mod.build_host_env(cfg, cfg.get_endpoint())
    assert "ANTHROPIC_API_KEY" not in env
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sandbox"
    # default endpoint needs a gateway -> host sees 127.0.0.1:<port>
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:18080"
    assert env["ANTHROPIC_MODEL"] == "gpt-oss:20b"


def test_launch_host_exec_path(monkeypatch):
    cfg = default_config()
    monkeypatch.setattr(claude_mod, "find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(claude_mod.plat, "detect", lambda: _info("exec"))
    captured = {}

    def fake_execvpe(file, argv, env):
        captured["file"], captured["argv"], captured["env"] = file, argv, env
        raise SystemExit(0)  # exec would replace the process; stop here

    monkeypatch.setattr(claude_mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit):
        claude_mod.launch_host(cfg, cfg.get_endpoint(), ["-p", "hi"])
    assert captured["file"] == "/usr/bin/claude"
    assert captured["argv"] == ["/usr/bin/claude", "-p", "hi"]
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == "sandbox"


def test_launch_host_subprocess_path(monkeypatch):
    cfg = default_config()
    monkeypatch.setattr(claude_mod, "find_claude", lambda: "claude.exe")
    monkeypatch.setattr(claude_mod.plat, "detect", lambda: _info("subprocess"))
    captured = {}

    class Result:
        returncode = 0

    def fake_run(argv, env=None):
        captured["argv"], captured["env"] = argv, env
        return Result()

    monkeypatch.setattr(claude_mod.subprocess, "run", fake_run)
    rc = claude_mod.launch_host(cfg, cfg.get_endpoint(), ["doctor"])
    assert rc == 0
    assert captured["argv"] == ["claude.exe", "doctor"]


def test_launch_host_missing_claude(monkeypatch):
    cfg = default_config()
    monkeypatch.setattr(claude_mod, "find_claude", lambda: None)
    with pytest.raises(FileNotFoundError):
        claude_mod.launch_host(cfg, cfg.get_endpoint(), [])
