# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions use the scheme
`1.YYYYmmdd.1HHMMSS` (UTC build timestamp).

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

[1.20260616.1000745]: https://github.com/changyy/py-llm-cli-sandbox/releases/tag/1.20260616.1000745
