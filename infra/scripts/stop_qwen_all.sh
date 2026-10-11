#!/usr/bin/env bash
# =============================================================================
# stop_qwen_all.sh — stop vLLM on every node, verify port 8000 is free.
# Idempotent: nodes already stopped are reported as such.
#
# Usage:  ./stop_qwen_all.sh
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"
# shellcheck source=../lib/lib_serve.sh
source "$HERE/../lib/lib_serve.sh"

if serve_stop_all "qwen" "$QWEN_PORT" 'vllm serve'; then
  ok "vLLM stopped on all reachable nodes"
else
  err "Some nodes could not be confirmed stopped"
  exit 1
fi
