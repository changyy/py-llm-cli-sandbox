import socket

import pytest

from llm_cli_sandbox import docker_ctl
from llm_cli_sandbox.errors import SandboxError


class FakeProc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _capturing_run(captured, returncode=0):
    def run(cmd, *a, **k):
        captured["cmd"] = cmd
        return FakeProc(returncode)
    return run


@pytest.fixture
def docker_present(monkeypatch):
    monkeypatch.setattr(docker_ctl.shutil, "which", lambda _: "/usr/bin/docker")


def test_require_docker_raises_when_missing(monkeypatch):
    monkeypatch.setattr(docker_ctl.shutil, "which", lambda _: None)
    assert docker_ctl.docker_available() is False
    with pytest.raises(SandboxError):
        docker_ctl.require_docker()


def test_compose_command_shape(monkeypatch, docker_present):
    captured = {}
    monkeypatch.setattr(docker_ctl.subprocess, "run", _capturing_run(captured))
    docker_ctl.ps()
    cmd = captured["cmd"]
    assert cmd[:5] == ["docker", "compose", "-p", "llm-cli-sandbox", "-f"]
    assert cmd[-1] == "ps"


def test_up_gateway_command(monkeypatch, docker_present):
    captured = {}
    monkeypatch.setattr(docker_ctl.subprocess, "run", _capturing_run(captured))
    docker_ctl.up_gateway()
    assert captured["cmd"][-4:] == ["up", "-d", "--wait", "litellm"]


def test_build_raises_on_failure(monkeypatch, docker_present):
    monkeypatch.setattr(docker_ctl.subprocess, "run", lambda cmd, *a, **k: FakeProc(1))
    with pytest.raises(SandboxError):
        docker_ctl.build("sandbox")


def test_build_ok(monkeypatch, docker_present):
    monkeypatch.setattr(docker_ctl.subprocess, "run", lambda cmd, *a, **k: FakeProc(0))
    assert docker_ctl.build("sandbox") is None


def test_run_sandbox_prepends_service_and_cmd(monkeypatch, docker_present):
    captured = {}
    monkeypatch.setattr(docker_ctl.subprocess, "run", _capturing_run(captured))
    docker_ctl.run_sandbox(service_cmd=["claude", "-p", "hi"])
    cmd = captured["cmd"]
    assert "run" in cmd and "--rm" in cmd
    assert cmd[-4:] == ["sandbox", "claude", "-p", "hi"]


def test_image_exists_false_when_docker_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(docker_ctl.subprocess, "run", boom)
    assert docker_ctl.image_exists() is False


def test_container_running_parses_output(monkeypatch):
    monkeypatch.setattr(docker_ctl.subprocess, "run", lambda *a, **k: FakeProc(0, "abc123\n"))
    assert docker_ctl.container_running("x") is True
    monkeypatch.setattr(docker_ctl.subprocess, "run", lambda *a, **k: FakeProc(0, ""))
    assert docker_ctl.container_running("x") is False


def test_port_in_use_with_open_socket():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    port = s.getsockname()[1]
    try:
        assert docker_ctl.port_in_use(port) is True
    finally:
        s.close()


def test_ensure_gateway_port_free_raises_for_stranger(monkeypatch):
    monkeypatch.setattr(docker_ctl, "port_in_use", lambda *a, **k: True)
    monkeypatch.setattr(docker_ctl, "container_running", lambda *a, **k: False)
    with pytest.raises(SandboxError):
        docker_ctl.ensure_gateway_port_free(18080)


def test_ensure_gateway_port_free_ok_when_our_gateway(monkeypatch):
    monkeypatch.setattr(docker_ctl, "port_in_use", lambda *a, **k: True)
    monkeypatch.setattr(docker_ctl, "container_running", lambda *a, **k: True)
    docker_ctl.ensure_gateway_port_free(18080)  # must not raise
