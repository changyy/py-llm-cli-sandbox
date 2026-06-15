import pytest

from llm_cli_sandbox.config import Config, Endpoint, default_config, load, save, validate
from llm_cli_sandbox.errors import SandboxError


def test_validate_rejects_bad_type():
    cfg = Config(default_endpoint="x", endpoints={"x": Endpoint(name="x", type="bogus")})
    with pytest.raises(SandboxError):
        validate(cfg)


def test_validate_requires_url_for_openai():
    cfg = Config(
        default_endpoint="x",
        endpoints={"x": Endpoint(name="x", type="openai-compat", url=None)},
    )
    with pytest.raises(SandboxError):
        validate(cfg)


def test_validate_rejects_unknown_default():
    cfg = default_config()
    cfg.default_endpoint = "does-not-exist"
    with pytest.raises(SandboxError):
        validate(cfg)


def test_load_rejects_malformed_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("this is = = not valid toml [[[")
    with pytest.raises(SandboxError):
        load(p)


def test_load_rejects_invalid_endpoint(tmp_path):
    p = tmp_path / "config.toml"
    cfg = default_config()
    cfg.endpoints["bad"] = Endpoint(name="bad", type="openai-compat", url=None)
    save(cfg, p)
    # save wrote no url for 'bad'; load must reject it
    with pytest.raises(SandboxError):
        load(p)
