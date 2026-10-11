#!/usr/bin/env bash
# =============================================================================
# start_qwen_all.sh — start vLLM serving Qwen2.5-VL-7B-Instruct-GPTQ-Int4
# (port 8000) on every node, in parallel, via nohup.
#
# Preflight checks per node: vLLM present, CUDA wheel vs. driver, port 8000 free,
# enough free VRAM. Never starts on an occupied port. Idempotent.
#
# Usage:  ./start_qwen_all.sh [--skip-preflight]
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"
# shellcheck source=../lib/lib_serve.sh
source "$HERE/../lib/lib_serve.sh"

SKIP_PREFLIGHT=0
[[ "${1:-}" == "--skip-preflight" ]] && SKIP_PREFLIGHT=1

# -----------------------------------------------------------------------------
# Preflight: vLLM version, torch build, and driver compatibility.
# IMPORTANT: vllm==0.29.0 pins torch==2.13.0, which only ships as cu130 wheels.
# Those need a CUDA-13 driver (>= 580). On a 12.4 driver the matching stack is
# vllm==0.8.5.post1 / torch==2.6.0+cu124 (see ../journal notes).
# -----------------------------------------------------------------------------
verify_vllm_stack() {
  log "Checking vLLM stack on each node"
  printf '%-10s %-12s %-18s %-10s %s\n' NODE VLLM TORCH TORCH_CUDA DRIVER
  printf '%-10s %-12s %-18s %-10s %s\n' ---- ---- ----- ---------- ------

  local n py out vllm torch tcuda drv dmaj rc=0
  py='import importlib.metadata as m, torch
try:
    v = m.version("vllm")
except Exception:
    v = "none"
print(v, torch.__version__, torch.version.cuda or "cpu")'

  for n in "${NODES[@]}"; do
    if ! node_up "$n"; then
      printf '%-10s %s\n' "$n" "UNREACHABLE"
      err "$n: not reachable over SSH"; rc=1; continue
    fi
    if ! ssh_out "$n" "test -x '$VLLM_ENV/bin/python'"; then
      printf '%-10s %s\n' "$n" "NO VENV ($VLLM_ENV)"
      err "$n: $VLLM_ENV/bin/python not found"; rc=1; continue
    fi
    out="$(ssh_out "$n" "'$VLLM_ENV/bin/python' -c '$py'")"
    read -r vllm torch tcuda <<<"${out:-none - -}"
    drv="$(ssh_out "$n" "nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1")"
    printf '%-10s %-12s %-18s %-10s %s\n' "$n" "$vllm" "$torch" "$tcuda" "${drv:-unknown}"

    if [[ "$vllm" == "none" ]]; then
      err "$n: vLLM not installed in $VLLM_ENV"; rc=1
    elif [[ "$tcuda" == 13* ]]; then
      dmaj="${drv%%.*}"
      if [[ "$dmaj" =~ ^[0-9]+$ ]] && (( dmaj < 580 )); then
        err "$n: torch built for CUDA $tcuda needs driver >=580, node has $drv"
        err "$n: use vllm==0.8.5.post1 / torch==2.6.0+cu124 on this driver"
        rc=1
      fi
    fi
  done
  echo
  return $rc
}

launch_qwen() {
  local node="$1" port="$2" minvram="$3" ready rc

  if api_ok "$node" "$port"; then ok "$node: already serving on $port — skip"; return 0; fi

  ssh_out "$node" "test -x '$VLLM_BIN'" || { err "$node: $VLLM_BIN missing (is $VLLM_ENV set up?)"; return 1; }
  ssh_out "$node" "test -f '$QWEN_MODEL_DIR/config.json'" || { err "$node: $QWEN_MODEL_DIR has no config.json"; return 1; }

  set +e; ready="$(check_launch_ready "$node" "$port" "$minvram")"; rc=$?; set -e
  if (( rc != 0 )); then err "$node: NOT starting — $ready"; return 1; fi

  log "$node: ${ready} MiB free — starting vLLM"

  local ip; ip="$(node_ip "$node")"

  # BIND ADDRESS — binds the node's LAN IP per SPEC §12.3 (never 0.0.0.0).
  # SOUVERAINETE — export VLLM_NO_USAGE_STATS=1 + ~/.config/vllm/do_not_track
  # LOGGING — uses hostname -s (short name) matching serve_log_name.
  ssh_run "$node" bash -s <<REMOTE
set -euo pipefail
mkdir -p "\$HOME/logs" "\$HOME/.config/vllm"
: > "\$HOME/.config/vllm/do_not_track"
export VLLM_NO_USAGE_STATS=1
cd "\$HOME"
nohup "$VLLM_BIN" serve "$QWEN_MODEL_DIR" \\
    --served-model-name "$QWEN_SERVED_NAME" \\
    --host "$ip" --port $port \\
    --gpu-memory-utilization $GPU_MEM_UTIL \\
    --max-model-len $QWEN_MAX_LEN \\
    --limit-mm-per-prompt '{"image": 1}' \\
    --trust-remote-code $QWEN_EXTRA_ARGS \\
    >"\$HOME/logs/qwen_\$(hostname -s).log" 2>&1 &
echo "  $node: started pid=\$!"
REMOTE
}

if (( ! SKIP_PREFLIGHT )); then
  if ! verify_vllm_stack; then
    err "Preflight failed. Fix the stack above, or re-run with --skip-preflight to force."
    exit 1
  fi
fi

if serve_launch_all "qwen" "$QWEN_PORT" "$QWEN_MIN_FREE_VRAM_MB" launch_qwen; then
  if serve_wait_all "qwen" "$QWEN_PORT"; then
    ok "All nodes serving Qwen2.5-VL on $QWEN_PORT"
  else
    err "Some nodes failed to come up (see logs)"
    (( BOOT_TIMEOUT <= 60 )) && serve_tail_logs "qwen"
    exit 1
  fi
else
  err "At least one node refused to start"
  exit 1
fi
