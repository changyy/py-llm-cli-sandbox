# llm-cli-sandbox

[![CI](https://github.com/changyy/py-llm-cli-sandbox/actions/workflows/ci.yml/badge.svg)](https://github.com/changyy/py-llm-cli-sandbox/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/llm-cli-sandbox.svg)](https://pypi.org/project/llm-cli-sandbox/)
[![PyPI Downloads](https://static.pepy.tech/badge/llm-cli-sandbox)](https://pepy.tech/projects/llm-cli-sandbox)
[![Python](https://img.shields.io/pypi/pyversions/llm-cli-sandbox.svg)](https://pypi.org/project/llm-cli-sandbox/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Run **Claude Code** (and other LLM CLIs) inside a **Docker sandbox**, pointed at a
**switchable LLM endpoint** — a local Ollama, a model server on your LAN, or any
remote OpenAI- / Anthropic-compatible API.

Two pillars:

1. **Isolation** — Claude Code is an agent that runs commands and edits files.
   Running it in a container is a safety boundary: only the chosen workspace is
   mounted, and the agent runs as a non-root user.
2. **Pluggable LLM backend** — the endpoint is just a named profile. Because
   Claude Code speaks the Anthropic Messages API, the tool decides per endpoint
   whether a translation gateway (litellm) is needed:

   | Endpoint type | Speaks Anthropic? | Gateway (litellm)? |
   | ------------- | ----------------- | ------------------ |
   | `ollama` (local or remote) | no | yes |
   | `openai-compat` | no | yes |
   | `anthropic` | yes | no (point Claude Code straight at it) |

> Status: **alpha (M2)**. Feature parity with the original shell workflow, plus
> multi-endpoint switching: environment checks, gateway lifecycle, endpoint
> management, and launching Claude Code on the host or inside the sandbox.
> Cross-platform validation (Linux/Windows) is M3.

## Install (development)

```bash
git clone git@github.com:changyy/py-llm-cli-sandbox.git
cd py-llm-cli-sandbox
pip install -e .
```

Requires Python 3.11+.

## Usage (today, M2)

```bash
llm-cli-sandbox version          # or: lcs version
llm-cli-sandbox platform         # detected OS/arch/runtime
llm-cli-sandbox doctor           # check docker, endpoint reachability, auth, ...

llm-cli-sandbox init             # write config + extract Docker assets to ~/.llm-cli-sandbox/
llm-cli-sandbox up               # generate compose + start the litellm gateway (if needed)
llm-cli-sandbox status           # running services + endpoint reachability
llm-cli-sandbox down             # stop the gateway, remove containers/network

# manage LLM endpoints (the "switch API location" part)
llm-cli-sandbox endpoints list
llm-cli-sandbox endpoints add lan --type openai-compat --url http://10.0.0.5:8000/v1 -m qwen --use
llm-cli-sandbox endpoints add proxy --type anthropic --url https://proxy.internal   # no gateway
llm-cli-sandbox endpoints use local-ollama

# launch Claude Code (pass its args after `--`)
llm-cli-sandbox run -- -p "hello"                 # on the host, via the gateway
llm-cli-sandbox run --in-container -- -p "hello"   # inside the sandbox (non-root)
llm-cli-sandbox shell -w ~/Project/my-app          # interactive sandbox shell

# manage models on an ollama-type endpoint
llm-cli-sandbox models list
llm-cli-sandbox models pull qwen2.5-coder:7b
```

Machine-readable output for scripting/CI:

```bash
llm-cli-sandbox platform --json
llm-cli-sandbox doctor --json     # exits non-zero if any check fails
llm-cli-sandbox status --json     # readiness probe; exits non-zero if not ready
```

`status` reports whether everything needed to launch against the selected
endpoint is in place (config, docker, image, endpoint reachability, gateway)
and lists what is `missing`:

```json
{ "ready": false, "missing": ["gateway"], "endpoint": { "reachable": true }, ... }
```

State location defaults to `~/.llm-cli-sandbox/` and can be relocated (handy
for tests or parallel setups):

```bash
LLM_CLI_SANDBOX_HOME=/tmp/lab llm-cli-sandbox init
```

`doctor` turns every environment trap into a check with a concrete fix hint:
Docker availability, `host.docker.internal` resolution per platform, endpoint
reachability (local or remote), gateway port conflicts, and Claude Code auth
sanity.

`up` generates `~/.llm-cli-sandbox/docker-compose.yml` and `litellm.config.yaml`
from the selected endpoint — emitting a litellm gateway service only when the
endpoint needs Anthropic translation, and injecting
`extra_hosts: host.docker.internal:host-gateway` so a host-local endpoint is
reachable identically on Linux and Docker Desktop.

## Configuration

`~/.llm-cli-sandbox/config.toml` (created by `init` in M1; defaults used until then):

```toml
[general]
default_endpoint = "local-ollama"

[endpoints.local-ollama]
type  = "ollama"
host  = "host"          # "host" -> host.docker.internal from the container
port  = 11434
model = "gpt-oss:20b"

[endpoints.lan-server]
type  = "openai-compat"
url   = "http://10.0.0.5:8000/v1"
model = "qwen2.5-coder:32b"

[endpoints.anthropic-proxy]
type  = "anthropic"     # already Anthropic-native -> no gateway
url   = "https://proxy.internal"

[gateway.litellm]
port  = 18080
image = "ghcr.io/berriai/litellm:main-stable"

[sandbox]
user         = "lab"    # non-root user inside the container
restrict_net = false    # v2: allowlist egress to endpoint + git only
```

## Roadmap

- **M0 — skeleton + doctor** (done): `version`, `platform`, `doctor`;
  platform-aware from day one.
- **M1 — sandbox + lifecycle** (done): `init`, non-root image, dynamic compose
  with `extra_hosts: host-gateway`, conditional gateway, `up` / `down` /
  `status`.
- **M2 — usage + endpoints** (done): `endpoints` commands, `shell`, `run` (host
  and in-container), `models` (for Ollama-type endpoints).
- **M3 — Windows/Linux validation**: host-gateway on Linux, Windows subprocess
  launch + WSL2 notes, remote-endpoint path on all three.
- **M4 — distribution**: PyPI release, pinned litellm image, optional egress
  restriction, per-platform smoke tests.

## How this differs from other sandboxes

Container isolation for Claude Code exists elsewhere. The distinguishing goal
here is the **switchable LLM backend** (local *or* remote, with automatic
gateway insertion) combined with a cross-platform, pip-installable Python CLI
and a thorough `doctor`.

## License

MIT
