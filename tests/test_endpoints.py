from llm_cli_sandbox import compose
from llm_cli_sandbox.config import Endpoint, default_config, load, save


def test_endpoint_add_remove_use_roundtrip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = default_config()
    cfg.endpoints["lan"] = Endpoint(
        name="lan", type="openai-compat", url="http://10.0.0.5:8000/v1", model="qwen"
    )
    cfg.default_endpoint = "lan"
    save(cfg, p)

    reloaded = load(p)
    assert set(reloaded.endpoints) == {"local-ollama", "lan"}
    assert reloaded.default_endpoint == "lan"

    del reloaded.endpoints["lan"]
    reloaded.default_endpoint = "local-ollama"
    save(reloaded, p)
    assert "lan" not in load(p).endpoints


def test_host_vs_container_base_url_for_gateway():
    cfg = default_config()
    ep = cfg.get_endpoint()
    # gateway: host sees 127.0.0.1:<port>, container sees the service name
    assert compose.claude_base_url(cfg, ep, from_container=False) == "http://127.0.0.1:18080"
    assert compose.claude_base_url(cfg, ep, from_container=True) == "http://litellm:4000"


def test_anthropic_endpoint_direct_both_sides():
    cfg = default_config()
    cfg.endpoints["a"] = Endpoint(name="a", type="anthropic", url="https://proxy.internal")
    cfg.default_endpoint = "a"
    ep = cfg.get_endpoint()
    for fc in (True, False):
        assert compose.claude_base_url(cfg, ep, from_container=fc) == "https://proxy.internal"
