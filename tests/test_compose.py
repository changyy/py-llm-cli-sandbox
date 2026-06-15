from pathlib import Path

from llm_cli_sandbox import compose
from llm_cli_sandbox.config import Config, Endpoint, default_config, load, save


def _cfg_with(ep: Endpoint) -> Config:
    cfg = default_config()
    cfg.endpoints = {ep.name: ep}
    cfg.default_endpoint = ep.name
    return cfg


def test_config_save_load_roundtrip(tmp_path):
    cfg = default_config()
    cfg.endpoints["lan"] = Endpoint(name="lan", type="openai-compat", url="http://10.0.0.5:8000/v1", model="qwen")
    p = tmp_path / "config.toml"
    save(cfg, p)
    loaded = load(p)
    assert loaded.default_endpoint == cfg.default_endpoint
    assert "lan" in loaded.endpoints
    assert loaded.endpoints["lan"].url == "http://10.0.0.5:8000/v1"
    assert loaded.endpoints["local-ollama"].type == "ollama"


def test_compose_ollama_has_gateway():
    cfg = _cfg_with(Endpoint(name="o", type="ollama", host="host", port=11434, model="gpt-oss:20b"))
    doc = compose.build_compose(cfg, cfg.get_endpoint(), Path("/tmp/ws"))
    assert "litellm" in doc["services"]
    assert "sandbox" in doc["services"]
    # sandbox in-container points at the gateway service
    env = doc["services"]["sandbox"]["environment"]
    assert env["ANTHROPIC_BASE_URL"] == "http://litellm:4000"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sandbox"
    assert "ANTHROPIC_API_KEY" not in env
    # host-gateway injected everywhere
    assert "host.docker.internal:host-gateway" in doc["services"]["sandbox"]["extra_hosts"]
    assert "host.docker.internal:host-gateway" in doc["services"]["litellm"]["extra_hosts"]


def test_compose_anthropic_has_no_gateway():
    cfg = _cfg_with(Endpoint(name="a", type="anthropic", url="https://proxy.internal"))
    doc = compose.build_compose(cfg, cfg.get_endpoint(), Path("/tmp/ws"))
    assert "litellm" not in doc["services"]
    env = doc["services"]["sandbox"]["environment"]
    assert env["ANTHROPIC_BASE_URL"] == "https://proxy.internal"


def test_litellm_config_ollama_routing():
    ep = Endpoint(name="o", type="ollama", host="host", port=11434, model="gpt-oss:20b")
    lc = compose.gen_litellm_config(ep)
    names = [m["model_name"] for m in lc["model_list"]]
    assert "gpt-oss:20b" in names and "claude-*" in names
    params = lc["model_list"][0]["litellm_params"]
    assert params["model"] == "ollama_chat/gpt-oss:20b"
    assert params["api_base"] == "http://host.docker.internal:11434"


def test_litellm_config_openai_routing():
    ep = Endpoint(name="x", type="openai-compat", url="http://10.0.0.5:8000/v1", model="qwen")
    lc = compose.gen_litellm_config(ep)
    params = lc["model_list"][0]["litellm_params"]
    assert params["model"] == "openai/qwen"
    assert params["api_base"] == "http://10.0.0.5:8000/v1"
    assert params["api_key"] == "sk-noop"
