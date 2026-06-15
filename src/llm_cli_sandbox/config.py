"""Configuration model and loading.

Config lives at ``~/.llm-cli-sandbox/config.toml``. An endpoint is a named LLM
backend profile; the tool switches Claude Code between them and decides per
endpoint whether a translation gateway (litellm) is needed.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from llm_cli_sandbox import paths
from llm_cli_sandbox.errors import SandboxError

__all__ = [
    "Endpoint",
    "GatewayConfig",
    "SandboxConfig",
    "Config",
    "default_config",
    "load",
    "save",
    "validate",
    "VALID_ENDPOINT_TYPES",
]

# Endpoint types and which speak the Anthropic Messages API natively. The rest
# need litellm in front to translate.
VALID_ENDPOINT_TYPES = ("ollama", "openai-compat", "anthropic")
_GATEWAY_TYPES = {"ollama", "openai-compat"}


@dataclass
class Endpoint:
    name: str
    type: str  # "ollama" | "openai-compat" | "anthropic"
    # For type=ollama: host ("host" -> host.docker.internal, or an explicit host) + port.
    host: str = "host"
    port: int = 11434
    # For type=openai-compat / anthropic: the full base URL.
    url: str | None = None
    model: str | None = None

    @property
    def needs_gateway(self) -> bool:
        return self.type in _GATEWAY_TYPES

    def base_url(self, *, from_container: bool) -> str:
        """Resolve the endpoint's base URL.

        ``from_container`` rewrites a host-local Ollama to host.docker.internal.
        """
        if self.url:
            return self.url
        if self.type == "ollama":
            host = self.host
            if host == "host":
                host = "host.docker.internal" if from_container else "localhost"
            return f"http://{host}:{self.port}"
        raise ValueError(f"endpoint {self.name!r} of type {self.type!r} has no url")


@dataclass
class GatewayConfig:
    port: int = 18080
    image: str = "ghcr.io/berriai/litellm:main-stable"


@dataclass
class SandboxConfig:
    user: str = "lab"  # non-root user inside the container
    restrict_net: bool = False  # v2: allowlist egress to endpoint + git only


@dataclass
class Config:
    default_endpoint: str = "local-ollama"
    endpoints: dict[str, Endpoint] = field(default_factory=dict)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)

    def get_endpoint(self, name: str | None = None) -> Endpoint | None:
        return self.endpoints.get(name or self.default_endpoint)


def default_config() -> Config:
    """Sensible defaults: a single local-Ollama endpoint."""
    return Config(
        default_endpoint="local-ollama",
        endpoints={
            "local-ollama": Endpoint(
                name="local-ollama",
                type="ollama",
                host="host",
                port=11434,
                model="gpt-oss:20b",
            )
        },
    )


def save(cfg: Config, path: Path | None = None) -> Path:
    """Write config as TOML. Targeted serializer for our known structure."""
    path = path or paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["[general]", f'default_endpoint = "{cfg.default_endpoint}"', ""]
    for name, ep in cfg.endpoints.items():
        lines.append(f"[endpoints.{name}]")
        lines.append(f'type = "{ep.type}"')
        if ep.url:
            lines.append(f'url = "{ep.url}"')
        else:
            lines.append(f'host = "{ep.host}"')
            lines.append(f"port = {ep.port}")
        if ep.model:
            lines.append(f'model = "{ep.model}"')
        lines.append("")
    lines += ["[gateway.litellm]", f"port = {cfg.gateway.port}", f'image = "{cfg.gateway.image}"', ""]
    lines += [
        "[sandbox]",
        f'user = "{cfg.sandbox.user}"',
        f"restrict_net = {str(cfg.sandbox.restrict_net).lower()}",
        "",
    ]
    path.write_text("\n".join(lines))
    return path


def validate(cfg: Config) -> None:
    """Fail fast with a clear message on a malformed config."""
    for name, ep in cfg.endpoints.items():
        if ep.type not in VALID_ENDPOINT_TYPES:
            raise SandboxError(
                f"endpoint {name!r} has invalid type {ep.type!r}",
                hint=f"valid types: {', '.join(VALID_ENDPOINT_TYPES)}",
            )
        if ep.type in ("openai-compat", "anthropic") and not ep.url:
            raise SandboxError(
                f"endpoint {name!r} of type {ep.type!r} is missing 'url'",
                hint="add a url, e.g. url = \"http://host:port/v1\"",
            )
    if cfg.endpoints and cfg.default_endpoint not in cfg.endpoints:
        raise SandboxError(
            f"default_endpoint {cfg.default_endpoint!r} is not a defined endpoint",
            hint=f"defined: {', '.join(cfg.endpoints) or '(none)'}",
        )


def load(path: Path | None = None) -> Config:
    """Load config from disk, or return defaults if it does not exist yet."""
    path = path or paths.config_path()
    if not path.exists():
        return default_config()
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise SandboxError(f"could not parse {path}: {exc}") from exc

    cfg = default_config()
    general = raw.get("general", {})
    cfg.default_endpoint = general.get("default_endpoint", cfg.default_endpoint)

    endpoints_raw = raw.get("endpoints", {})
    if endpoints_raw:
        cfg.endpoints = {}
        for name, e in endpoints_raw.items():
            cfg.endpoints[name] = Endpoint(
                name=name,
                type=e.get("type", "ollama"),
                host=e.get("host", "host"),
                port=int(e.get("port", 11434)),
                url=e.get("url"),
                model=e.get("model"),
            )

    gw = raw.get("gateway", {}).get("litellm", {})
    cfg.gateway = GatewayConfig(
        port=int(gw.get("port", 18080)),
        image=gw.get("image", GatewayConfig.image),
    )

    sb = raw.get("sandbox", {})
    cfg.sandbox = SandboxConfig(
        user=sb.get("user", "lab"),
        restrict_net=bool(sb.get("restrict_net", False)),
    )
    validate(cfg)
    return cfg
