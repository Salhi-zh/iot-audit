#!/usr/bin/env bash
# =============================================================================
# stop_llama_all.sh — stop llama-server on every node, verify port 8001 is free.
# Idempotent: nodes already stopped are reported as such.
#
# Usage:  ./stop_llama_all.sh
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"
# shellcheck source=../lib/lib_serve.sh
source "$HERE/../lib/lib_serve.sh"

if serve_stop_all "llama" "$LLAMA_PORT" 'llama-server'; then
  ok "Llama servers stopped on all reachable nodes"
else
  err "Some nodes could not be confirmed stopped"
  exit 1
fi
