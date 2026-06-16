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

> Status: **alpha** — initial release. Environment checks, gateway lifecycle,
> endpoint management, and launching Claude Code on the host or inside the
> sandbox are in place. Cross-platform validation (Linux/Windows) and hardened
> distribution are still ahead — see the Roadmap.

## Install (development)

```bash
git clone git@github.com:changyy/py-llm-cli-sandbox.git
cd py-llm-cli-sandbox
pip install -e .
```

Requires Python 3.11+.

## Usage

```bash
llm-cli-sandbox version          # short aliases: `lcs` and `llm-cli`
llm-cli-sandbox quickstart       # copy-pasteable examples for the common flows
llm-cli-sandbox platform         # detected OS/arch/runtime
llm-cli-sandbox doctor           # check docker, endpoint reachability, auth, ...
llm-cli-sandbox update           # is a newer release on PyPI? print how to upgrade
llm-cli-sandbox update --from /tmp/checkout   # install from a local path / wheel / git URL

llm-cli-sandbox init             # write config + extract Docker assets to ~/.llm-cli-sandbox/
llm-cli-sandbox up               # generate compose + start the litellm gateway (if needed)
llm-cli-sandbox status           # running services + endpoint reachability
llm-cli-sandbox ping             # functional round-trip: does the model actually reply?
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
llm-cli-sandbox models catalog                     # recommended models + tool-calling, RAM & disk needs
llm-cli-sandbox models list                        # what's installed (flags tool-calling support)
llm-cli-sandbox models pull qwen2.5-coder:7b
llm-cli-sandbox models use  qwen2.5-coder:7b       # set + verify it's installed (offers to pull)
llm-cli-sandbox models use  qwen2.5-coder:7b --pull  # set and pull in one step
```

`use` checks the model is actually on the endpoint and offers to pull it if
not; `shell` / `run` / `up` do the same preflight and stop early with a clear
hint rather than letting a missing model surface as a gateway error mid-session.

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

Where `doctor`/`status` check that things are reachable, `ping` checks they
actually *work*: it sends a tiny prompt straight to the model (`direct`) and,
for gateway endpoints, through the litellm gateway over the Anthropic Messages
API (`gateway`) — the exact path Claude Code uses — and prints each reply with
timing. `--json` exits non-zero if the path Claude would use fails, so you can
confirm a backend end-to-end without launching an interactive session:

```
endpoint : local-ollama [ollama] http://localhost:11434
model    : gpt-oss:20b
direct   : OK (load 0.12s + gen 0.05s) [loaded] "pong"
gateway  : OK (0.23s) "pong"
tools    : OK (0.30s) tool_use returned
READY
```

For an Ollama endpoint, the `direct` line splits out Ollama's own
`load_duration` (model load) from generation and marks whether the model was
`[cold]` or already `[loaded]`, so a slow first call is attributed correctly —
a cold start, not a slow backend — with a hint to keep the model warm
(`OLLAMA_KEEP_ALIVE`) when load dominates.

The `tools` check is the one that decides whether Claude Code is actually
usable: it sends a request that should trigger a tool call and verifies the
reply is a structured `tool_use` block. Many capable chat models (e.g.
`qwen2.5-coder`) answer in plain text instead — they pass `direct`/`gateway`
but Claude Code, which is entirely tool-driven, can't drive them. A failure
here makes `ping` report `NOT OK` with a hint to switch to a tool-calling model
(`--no-tools` skips the check for plain-chat use).

`up` generates `~/.llm-cli-sandbox/docker-compose.yml` and `litellm.config.yaml`
from the selected endpoint — emitting a litellm gateway service only when the
endpoint needs Anthropic translation, and injecting
`extra_hosts: host.docker.internal:host-gateway` so a host-local endpoint is
reachable identically on Linux and Docker Desktop.

## Configuration

`~/.llm-cli-sandbox/config.toml` (created by `init`; defaults used until then):

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
