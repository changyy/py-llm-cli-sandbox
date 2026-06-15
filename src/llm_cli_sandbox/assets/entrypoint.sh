#!/usr/bin/env bash
set -e

# Claude Code talks to the gateway (or an Anthropic-native endpoint) directly,
# so no in-container port forwarding is needed here — the network path is set
# up by docker-compose (extra_hosts + the litellm service).

if [ -t 0 ] && [ "$#" -eq 1 ] && [ "$1" = "/bin/bash" ]; then
  echo "[sandbox] interactive shell at /workspace (user: $(whoami))."
  echo "[sandbox] 'claude' is preinstalled and pointed at the configured endpoint; type 'exit' to leave."
fi

exec "$@"
