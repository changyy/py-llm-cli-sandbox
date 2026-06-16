# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions use the scheme
`1.YYYYmmdd.1HHMMSS` (UTC build timestamp).

## [1.20260616.1190020] - 2026-06-16

### Fixed

- Switching the model/endpoint (e.g. `models use`) then launching left the
  already-running litellm gateway serving the *old* model — it loads its config
  only at startup, and `up -d` does not recreate a container when only the
  mounted config file's contents changed. `up`, `shell`, and `run` now detect a
  changed gateway config (tracked via an "applied" marker recording what the
  running container loaded) and `--force-recreate` the gateway so it reloads.
  The marker also recovers a gateway started before this tracking existed.
- `models use` now reloads a running gateway in place once the model is
  available, so a switch takes effect immediately instead of sitting stale until
  the next launch; `ping` reports a stale running gateway as "run `lcs up` to
  reload it" rather than surfacing the raw litellm 400.

### Added

- `models catalog` now flags tool-calling support per model and leads with
  tool-capable ones (`gpt-oss`, `llama3.1`, `qwen3`, `mistral-nemo`, …), since
  that is what Claude Code requires; coding-only models without tool calls
  (`qwen2.5-coder`) are marked as such. Use `lcs ping` to confirm a setup.
- Hardware-aware model selection: `models catalog` shows each model's disk and
  rough RAM needs alongside the host's detected RAM/free disk (flagging models
  that exceed available RAM), `models list` annotates tool-calling support for
  known models, and `models use` warns when a host-local model likely needs more
  RAM than the machine has (the cause of slow cold loads) or can't do tool calls.
  RAM/disk detection is stdlib-only and cross-platform.
- `ping` command: a functional round-trip that confirms the backend actually
  generates, not just that the port is open. Sends a tiny prompt directly to the
  model (`direct`) and, for gateway endpoints, through the litellm gateway over
  the Anthropic Messages API (`gateway`) — the exact path Claude Code uses —
  reporting each reply with timing. `--json` exits non-zero when the path Claude
  would use fails. For Ollama the `direct` line splits Ollama's `load_duration`
  (model load) from generation and marks `[cold]`/`[loaded]`, so a slow first
  call reads as a cold start rather than a slow backend, with a hint to keep the
  model warm when load dominates. A `tools` check sends a request that should
  trigger a tool call and verifies the reply is a structured `tool_use` block —
  the capability Claude Code depends on. Models that answer in plain text (e.g.
  `qwen2.5-coder`) pass `direct`/`gateway` but fail here, so `ping` reports
  `NOT OK` with a hint to switch to a tool-calling model (`--no-tools` skips it).
- Model preflight: `models use <name>` now verifies the model is installed on
  the endpoint and offers to pull it if not (`--pull` / `--yes` to skip the
  prompt; best-effort — silently skips when the endpoint is unreachable).
  `shell`, `run`, and `up` run the same check and stop early with an actionable
  hint, so a missing model no longer surfaces as a cryptic gateway error
  mid-session.
- `update` command: checks PyPI (GitHub releases as fallback) for a newer
  release and prints the upgrade command for the detected install method
  (pip / pipx / editable checkout). Conservative — it never modifies the
  environment. `doctor` gained a matching version check that WARNs when a newer
  release exists and stays silent when offline. Both use stdlib `urllib` only.
- `update --from <source>`: install from a local source checkout, a wheel/sdist
  file, or a git URL instead of PyPI. Validates a local source belongs to this
  package and shows current → target before installing; confirms first unless
  `--yes`. Install method is install-aware: `pipx install --force` when the tool
  is pipx-managed (since `pipx upgrade` can't take an arbitrary source),
  otherwise pip into the running interpreter.
- `quickstart` command: prints copy-pasteable examples for the common flows.
- `models catalog`: a curated shortlist of common (coding-focused) models,
  marking the ones already installed on the endpoint.
- `models use <name>`: set the model an ollama-type endpoint should use, without
  re-running `endpoints add`.
- `llm-cli` console-script alias (alongside `llm-cli-sandbox` and `lcs`).

## [1.20260616.1000745] - 2026-06-16

Initial release.

### Added

- **Docker-isolated launcher** for Claude Code (and other LLM CLIs): the agent
  runs as a non-root user in a sandbox container with only the chosen workspace
  mounted.
- **Switchable LLM backend** via named endpoint profiles. A litellm gateway is
  inserted only when the endpoint needs Anthropic translation
  (`ollama`, `openai-compat`); `anthropic`-native endpoints are used directly.
- **Commands**:
  - `init` — write config and extract Docker assets to `~/.llm-cli-sandbox/`.
  - `doctor` — environment checks with fix hints; `--json` for automation.
  - `up` / `down` / `status` — gateway lifecycle and a readiness probe;
    `status --json` exits non-zero when a launch prerequisite is missing.
  - `endpoints` — `list` / `add` / `use` / `rm`.
  - `shell` — interactive sandbox shell.
  - `run` — launch Claude Code on the host or `--in-container`.
  - `models` — `list` / `pull` / `rm` for ollama-type endpoints.
  - `version` / `--version`.
- **Dynamic generation** of `docker-compose.yml` and the litellm config from the
  selected endpoint, with `host.docker.internal:host-gateway` injected for
  identical local-endpoint reachability on Linux and Docker Desktop.
- **Cross-platform support** (macOS, Linux, Windows) with platform-aware launch
  (exec vs subprocess) and runtime detection (docker / podman; Docker Desktop /
  OrbStack).
- **Configuration** at `~/.llm-cli-sandbox/config.toml`, relocatable via the
  `LLM_CLI_SANDBOX_HOME` environment variable, with load-time validation.
- Version single-sourced in code and read dynamically by the build.
- GitHub Actions: CI (ruff + pytest on Python 3.11/3.12/3.13) and PyPI publish
  on release via trusted publishing.

[1.20260616.1190020]: https://github.com/changyy/py-llm-cli-sandbox/releases/tag/1.20260616.1190020
[1.20260616.1000745]: https://github.com/changyy/py-llm-cli-sandbox/releases/tag/1.20260616.1000745
