from llm_cli_sandbox import __version__, sysinfo
from llm_cli_sandbox.config import Endpoint, default_config, load


def test_version():
    assert isinstance(__version__, str) and __version__


def test_platform_detect():
    info = sysinfo.detect()
    assert info.os in ("darwin", "linux", "windows", info.os)
    assert info.claude_launch in ("exec", "subprocess")


def test_default_config_has_local_ollama():
    cfg = default_config()
    ep = cfg.get_endpoint()
    assert ep is not None
    assert ep.type == "ollama"
    assert ep.needs_gateway is True


def test_load_missing_returns_defaults(tmp_path):
    cfg = load(tmp_path / "nope.toml")
    assert cfg.default_endpoint == "local-ollama"


def test_endpoint_base_url_host_rewrite():
    ep = Endpoint(name="x", type="ollama", host="host", port=11434)
    assert ep.base_url(from_container=False) == "http://localhost:11434"
    assert ep.base_url(from_container=True) == "http://host.docker.internal:11434"


def test_anthropic_endpoint_no_gateway():
    ep = Endpoint(name="a", type="anthropic", url="https://proxy.internal")
    assert ep.needs_gateway is False
    assert ep.base_url(from_container=False) == "https://proxy.internal"
