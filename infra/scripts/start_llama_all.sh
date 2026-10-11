#!/usr/bin/env bash
# =============================================================================
# start_llama_all.sh — start llama-server (Llama-3.2-11B-Vision, port 8001)
# on every node, in parallel, via nohup. Never starts on an occupied port or a
# node without enough free VRAM. Idempotent: a node already serving is skipped.
#
# Usage:  ./start_llama_all.sh
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"
# shellcheck source=../lib/lib_serve.sh
source "$HERE/../lib/lib_serve.sh"

launch_llama() {
  local node="$1" port="$2" minvram="$3" ready rc gguf mmproj webui

  # Already serving? (idempotent)
  if api_ok "$node" "$port"; then ok "$node: already serving on $port — skip"; return 0; fi

  # ARTIFACT checks first — they name the real cause. This order is deliberate:
  # it used to probe launch readiness first, so a cluster with no llama.cpp at all
  # reported "NOT starting — only 2983 MiB VRAM free (< 8000 required)", which
  # sends you to look at the GPU when the actual problem is that the binary does
  # not exist. Verified 2026-09-17: that is exactly what all three live nodes
  # printed, while the real cause is the absent llama.cpp/GGUF tree (see
  # ../config/cluster.env and ../README.md §AMENDMENT 2026-09-17).
  ssh_out "$node" "test -x '$LLAMA_SERVER_BIN'" || { err "$node: $LLAMA_SERVER_BIN missing or not executable"; return 1; }

  gguf="$(ssh_out "$node" "ls -1 '$LLAMA_DIR'/$LLAMA_GGUF_GLOB 2>/dev/null | head -n1")"
  mmproj="$(ssh_out "$node" "ls -1 '$LLAMA_DIR'/$LLAMA_MMPROJ_GLOB 2>/dev/null | head -n1")"
  [[ -n "$gguf"   ]] || { err "$node: no GGUF matching '$LLAMA_GGUF_GLOB' in $LLAMA_DIR";   return 1; }
  [[ -n "$mmproj" ]] || { err "$node: no mmproj matching '$LLAMA_MMPROJ_GLOB' in $LLAMA_DIR"; return 1; }

  set +e; ready="$(check_launch_ready "$node" "$port" "$minvram")"; rc=$?; set -e
  if (( rc != 0 )); then err "$node: NOT starting — $ready"; return 1; fi

  # --no-webui only exists on newer builds; add it when supported.
  webui=""
  if ssh_out "$node" "'$LLAMA_SERVER_BIN' --help 2>&1 | grep -q -- '--no-webui'"; then webui="--no-webui"; fi

  log "$node: ${ready} MiB free — $(basename "$gguf") + $(basename "$mmproj")"

  local ip; ip="$(node_ip "$node")"

  # BIND ADDRESS — binds the node's LAN IP per SPEC §12.3 (never 0.0.0.0).
  # LOGGING — uses hostname -s (short name) matching serve_log_name.
  ssh_run "$node" bash -s <<REMOTE
set -euo pipefail
mkdir -p "\$HOME/logs"
cd "\$HOME"
nohup "$LLAMA_SERVER_BIN" \\
    -m "$gguf" \\
    --mmproj "$mmproj" \\
    --host "$ip" --port $port \\
    -ngl $LLAMA_NGL -c $LLAMA_CTX \\
    $webui $LLAMA_EXTRA_ARGS \\
    >"\$HOME/logs/llama_\$(hostname -s).log" 2>&1 &
echo "  $node: started pid=\$!"
REMOTE
}

if serve_launch_all "llama" "$LLAMA_PORT" "$LLAMA_MIN_FREE_VRAM_MB" launch_llama; then
  if serve_wait_all "llama" "$LLAMA_PORT"; then
    ok "All nodes serving Llama-3.2-11B-Vision on $LLAMA_PORT"
  else
    err "Some nodes failed to come up (see logs)"
    (( BOOT_TIMEOUT <= 60 )) && serve_tail_logs "llama"
    exit 1
  fi
else
  err "At least one node refused to start"
  exit 1
fi
