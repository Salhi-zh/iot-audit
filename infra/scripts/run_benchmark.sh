#!/usr/bin/env bash
# =============================================================================
# run_benchmark.sh — drive benchmark_distributed.py against all 3 nodes.
#
#   ./run_benchmark.sh --model qwen|llama --images DIR --output FILE.json
#
# Verifies all three servers answer /v1/models before starting, runs the client
# where it can actually reach the nodes, saves the result, and prints a summary.
# If a server dies mid-run the failure is detected and reported afterwards.
#
# The client runs on a node by default (BENCH_MODE=remote) because the nodes are
# on a private LAN; set BENCH_MODE=local only if this host can reach them.
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"

MODEL=""; IMAGES=""; OUTPUT=""; URLS_OVERRIDE=""; MODE="$BENCH_MODE"

usage() { sed -n '2,13p' "$0"; exit "${1:-0}"; }

while (( $# )); do
  case "$1" in
    --model)  MODEL="${2:?}"; shift ;;
    --images) IMAGES="${2:?}"; shift ;;
    --output) OUTPUT="${2:?}"; shift ;;
    --urls)   URLS_OVERRIDE="${2:?}"; shift ;;
    --mode)   MODE="${2:?}"; shift ;;
    -h|--help) usage 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

[[ "$MODEL" =~ ^(qwen|llama)$ ]] || { err "--model must be 'qwen' or 'llama'"; usage 1; }
[[ -n "$IMAGES" ]] || { err "--images is required"; usage 1; }
[[ -n "$OUTPUT" ]] || { err "--output is required"; usage 1; }
[[ -d "$IMAGES" ]] || die "images directory not found: $IMAGES"
[[ "$MODE" =~ ^(remote|local)$ ]] || die "--mode must be 'remote' or 'local'"

case "$MODEL" in
  qwen)  PORT="$QWEN_PORT"  LABEL="Qwen2.5-VL-7B (vLLM)" ;;
  llama) PORT="$LLAMA_PORT" LABEL="Llama-3.2-11B-Vision (llama.cpp)" ;;
esac

# --- build endpoint list -----------------------------------------------------
build_urls() {
  if [[ -n "$URLS_OVERRIDE" ]]; then printf '%s' "$URLS_OVERRIDE"; return; fi
  local sep="${BENCH_URLS_SEP:-,}" n host out=""
  for n in "${NODES[@]}"; do
    if [[ "$MODE" == "remote" ]]; then host="$(node_ip "$n")"; else host="$n"; fi
    out+="${out:+$sep}http://${host}:${PORT}/v1"
  done
  printf '%s' "$out"
}
URLS="$(build_urls)"

# --- pre-flight --------------------------------------------------------------
log "Benchmark: $LABEL  (port $PORT, mode $MODE)"
log "Endpoints: $URLS"

DOWN=0
for n in "${NODES[@]}"; do
  if api_ok "$n" "$PORT"; then ok "preflight $n: $LABEL responding"; else err "preflight $n: NOT responding on $PORT"; DOWN=1; fi
done
(( DOWN == 0 )) || die "not all servers are up — start them first (start_${MODEL}_all.sh)"

# --- run ---------------------------------------------------------------------
if [[ "$MODE" == "local" ]]; then
  PY="${BENCH_PYTHON_LOCAL:-python3}"
  # BENCH_SCRIPT defaults to $NODE_HOME/benchmark_distributed.py -- a NODE-side path,
  # because BENCH_MODE=remote is the documented default. Running the client on this
  # orchestrator therefore needs BENCH_SCRIPT overridden; without this check the branch
  # died on `require_script` naming a path that exists on no orchestrator, which read
  # as "the benchmark client is missing" instead of "you are in local mode".
  [[ -f "$BENCH_SCRIPT" ]] || die "BENCH_MODE=local needs a LOCAL client: set BENCH_SCRIPT=<path> (it is a NODE-side path by default: $BENCH_SCRIPT)"
  require_script "$BENCH_SCRIPT"
  log "Running client locally: $PY $BENCH_SCRIPT"
  "$PY" "$BENCH_SCRIPT" "$BENCH_URLS_FLAG" "$URLS" --images "$IMAGES" --output "$OUTPUT"
else
  NODE="$BENCH_HOME_NODE"
  node_up "$NODE" || die "benchmark host $NODE unreachable"
  ssh_out "$NODE" "test -f '$BENCH_SCRIPT'" || die "$BENCH_SCRIPT not found on $NODE"

  RIMG="$BENCH_REMOTE_DIR/images"
  ROUT="$BENCH_REMOTE_DIR/result.json"
  log "Staging images on $NODE:$RIMG"
  ssh_out "$NODE" "mkdir -p '$BENCH_REMOTE_DIR'"
  rsync -a --info=progress2 -e "ssh $( _ssh_opts )" "$IMAGES/" "$NODE:$RIMG/"

  log "Running client on $NODE"
  # NOTE: --images/--output flag names below are the assumed CLI of
  # benchmark_distributed.py. Confirm with --help and adjust if different.
  ssh_run "$NODE" bash -s <<REMOTE
set -euo pipefail
"$BENCH_PYTHON" "$BENCH_SCRIPT" $BENCH_URLS_FLAG "$URLS" --images "$RIMG" --output "$ROUT"
REMOTE

  log "Fetching result -> $OUTPUT"
  rsync -a -e "ssh $( _ssh_opts )" "$NODE:$ROUT" "$OUTPUT"
fi

[[ -f "$OUTPUT" ]] || die "benchmark produced no output at $OUTPUT"
ok "Result saved: $OUTPUT"

# --- post-flight: identify servers that died ---------------------------------
echo
log "Post-flight health check"
DEAD=""
for n in "${NODES[@]}"; do
  if api_ok "$n" "$PORT"; then ok "$n still up"; else err "$n went DOWN during the run"; DEAD+="$n "; fi
done
[[ -z "$DEAD" ]] || warn "partial result: ${DEAD}stopped responding — rerun the affected node"

# --- summary -----------------------------------------------------------------
echo
log "Result summary"
python3 - "$OUTPUT" <<'PY' 2>/dev/null || echo "(no python3 available — inspect $OUTPUT manually)"
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print("could not parse JSON:", e); sys.exit(0)
if isinstance(d, dict):
    print("keys:", ", ".join(map(str, d.keys())))
    for k in ("model","mean_latency","avg_latency","mean_latency_s","median_latency",
              "p95_latency","success_rate","json_success_rate","json_valid_rate",
              "throughput","throughput_img_s","num_images","total_images","errors"):
        if k in d:
            print(f"  {k}: {d[k]}")
elif isinstance(d, list):
    print(f"records: {len(d)}")
    if d and isinstance(d[0], dict):
        print("fields:", ", ".join(map(str, d[0].keys())))
PY
echo
ok "Done: $OUTPUT"
