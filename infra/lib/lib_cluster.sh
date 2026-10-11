# shellcheck shell=bash
# =============================================================================
# lib_cluster.sh — shared helpers. Source this AFTER cluster.env.
#   source "$HERE/cluster.env"
#   source "$HERE/lib_cluster.sh"
# =============================================================================

# --- output ------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RED=$'\e[31m'; C_GRN=$'\e[32m'; C_YEL=$'\e[33m'; C_BLU=$'\e[36m'; C_DIM=$'\e[2m'; C_RST=$'\e[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_BLU=''; C_DIM=''; C_RST=''
fi
log()  { printf '%s\n' "${C_BLU}==>${C_RST} $*"; }
ok()   { printf '%s\n' "${C_GRN} OK ${C_RST} $*"; }
warn() { printf '%s\n' "${C_YEL}WARN${C_RST} $*" >&2; }
err()  { printf '%s\n' "${C_RED}FAIL${C_RST} $*" >&2; }
die()  { err "$*"; exit 1; }

# --- ssh wrappers ------------------------------------------------------------
# Non-interactive, never hangs waiting for a password (BatchMode=yes).
_ssh_opts() {
  # shellcheck disable=SC2086
  printf '%s' "$SSH_OPTS_COMMON"
  if [[ "${ZABETH_SSH_MUX:-0}" == "1" ]]; then
    local d="${XDG_RUNTIME_DIR:-/tmp}/zabeth-ssh"
    mkdir -p "$d" 2>/dev/null || true
    printf ' -o ControlMaster=auto -o ControlPath=%s/%%C -o ControlPersist=120' "$d"
  fi
}

ssh_run() {  # ssh_run <node> <cmd...>   stdout/stderr passed through; exit code kept
  local node="$1"; shift
  # shellcheck disable=SC2046,SC2086
  ssh -o BatchMode=yes $(_ssh_opts) "$node" "$@"
}

ssh_out() {  # like ssh_run but swallows stderr — for probing remote state
  local node="$1"; shift
  # shellcheck disable=SC2046,SC2086
  ssh -o BatchMode=yes $(_ssh_opts) "$node" "$@" 2>/dev/null
}

node_up() { ssh_out "$1" true; }   # 0 = reachable over SSH

# --- remote state probes -----------------------------------------------------
port_in_use() {  # <node> <port> -> 0 = in use, 1 = free, 2 = node unreachable
  local node="$1" port="$2" out
  node_up "$node" || return 2
  out=$(ssh_out "$node" "ss -ltnH 'sport = :$port' 2>/dev/null | awk 'NR==1{print \$4}'")
  [[ -n "$out" ]]
}

port_pid() {  # <node> <port> -> prints PID(s) listening, may be empty
  local node="$1" port="$2"
  ssh_out "$node" "ss -ltnpH 'sport = :$port' 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u"
}

gpu_free_mb() { ssh_out "$1" "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -n1"; }

disk_free_gb() {  # free GB on the filesystem holding \$HOME
  ssh_out "$1" "df -BG --output=avail \$HOME 2>/dev/null | tail -n1 | tr -dc '0-9'"
}

# --- artifact identity -------------------------------------------------------
# Hugging Face keeps what it downloaded NEXT TO the model, in
# `<model>/.cache/huggingface/download/`: a `.lock` plus a `.metadata` holding the
# commit hash, the etag and the download timestamp as a float. That float's
# TEXTUAL LENGTH varies (16 vs 17 characters), so two nodes holding byte-identical
# weights still differ by ±1 byte in RAW tree size. Measured 2026-09-17:
#   6 944 521 923 B on zabeth23   vs   6 944 521 924 B on zabeth21/zabeth22
# — every difference inside a handful of `.metadata` files, while both safetensors
# hashed identically (`25aab8ca…`, `d380b110…`) on all three nodes.
# Comparing raw totals made sync_models.sh STRUCTURALLY unable to report the Qwen
# artifact as complete: it re-copied 6.9 GB on every run and exited 1 under
# --dry-run, on a cluster whose weights are byte-identical. These helpers now
# measure the PAYLOAD — the bookkeeping is regenerated on demand and is not model
# content. With it excluded all three nodes agree exactly (6 944 517 710 B, 16
# files). Override with SYNC_EXCLUDE (empty disables the exclusion).
SYNC_EXCLUDE="${SYNC_EXCLUDE:-.cache}"

path_size_bytes() {  # <node> <path> -> payload bytes (dir or file), empty if absent
  ssh_out "$1" "if [ -d '$2' ]; then du -sb --exclude='$SYNC_EXCLUDE' '$2' | cut -f1; elif [ -f '$2' ]; then stat -c %s '$2'; fi"
}

path_exists() { ssh_out "$1" "test -e '$2' && echo yes"; }

count_files() {  # <node> <path> -> payload file count (SYNC_EXCLUDE pruned)
  ssh_out "$1" "find '$2' -name '$SYNC_EXCLUDE' -prune -o -type f -print 2>/dev/null | wc -l"
}

# --- provenance --------------------------------------------------------------
# `node_write_provenance.sh` writes two artefacts in ~/vllm-env: ENV_STATUS.md
# (human, §8.3) and provenance.json (machine-readable) — the second is what
# `iot_audit/pipeline/provenance.build_provenance` assembles at sealing time.
# The list of nodes that answered is a run's `nodes_used`; a node that answers
# with nothing must be visible as such rather than silently absent from it.
node_provenance_json() {  # <node> -> the node's provenance.json, verbatim on stdout
  local node="$1" out
  if ! out=$(ssh_out "$node" "cat \$HOME/vllm-env/provenance.json"); then
    err "$node : provenance.json illisible — lancer infra/scripts/node_write_provenance.sh sur ce noeud"
    return 1
  fi
  if [[ -z "$out" ]]; then
    err "$node : provenance.json vide (fichier present mais sans contenu)"
    return 1
  fi
  printf '%s\n' "$out"
}

# --- readiness ---------------------------------------------------------------
check_launch_ready() {  # <node> <port> <min_free_vram_mb>
  # Echoes the free VRAM (MiB) and returns 0 when the node is ready to serve.
  # Otherwise echoes a human reason and returns 1.
  local node="$1" port="$2" minvram="${3:-0}" st free
  if ! node_up "$node"; then echo "unreachable over SSH"; return 1; fi
  port_in_use "$node" "$port"; st=$?
  if (( st == 0 )); then echo "port $port already in use (pid $(port_pid "$node" "$port" | paste -sd, -))"; return 1; fi
  if (( st == 2 )); then echo "cannot query port $port"; return 1; fi
  free=$(gpu_free_mb "$node")
  if [[ -z "$free" ]]; then echo "nvidia-smi unavailable"; return 1; fi
  if (( free < minvram )); then echo "only ${free} MiB VRAM free (< ${minvram} required)"; return 1; fi
  echo "$free"
}

# The listening address is a property of how the server was started, and this
# repo has two launchers that disagree about it:
#   * start_qwen_all.sh / start_llama_all.sh  -> --host 0.0.0.0   (reachable at
#     loopback *and* the LAN address)
#   * node_vllm_service.sh (the one actually deployed) -> --host <node LAN IP>
#     (reachable ONLY at the LAN address)
# A loopback-only probe therefore reports a perfectly healthy cluster as down.
# Verified 2026-09-17 against the three live nodes: the service bound to
# 172.26.145.{71,72,73}:8000 answered (exit 0) while
# `http://127.0.0.1:8000/v1/models` gave curl exit 7 on all three.
# Probe the LAN address first, then loopback, so every bind style is covered.
api_probe_hosts() {  # <node> -> candidate addresses, most specific first
  local node="$1" ip
  ip="$(node_ip "$node")"
  if [[ -n "$ip" && "$ip" != "$node" ]]; then
    printf '%s\n%s\n' "$ip" 127.0.0.1
  else
    printf '%s\n' 127.0.0.1
  fi
}

wait_api() {  # <node> <port> [timeout_s] -> 0 once /v1/models answers on the node itself
  local node="$1" port="$2" timeout="${3:-$BOOT_TIMEOUT}" waited=0
  while (( waited < timeout )); do
    if api_ok "$node" "$port"; then return 0; fi
    sleep "$BOOT_INTERVAL"; waited=$((waited + BOOT_INTERVAL))
  done
  return 1
}

api_ok() {  # <node> <port> -> 0 when /v1/models answers on any address it can bind
  local node="$1" port="$2" h
  while IFS= read -r h; do
    if ssh_out "$node" "curl -sf -m 3 http://$h:$port/v1/models >/dev/null"; then
      return 0
    fi
  done < <(api_probe_hosts "$node")
  return 1
}

# --- process control ---------------------------------------------------------
kill_port() {  # <node> <port> -> TERM the listener, escalate to KILL, verify freed
  local node="$1" port="$2" pid
  pid=$(port_pid "$node" "$port")
  if [[ -z "$pid" ]]; then
    if (( $(port_in_use "$node" "$port"; echo $?) == 0 )); then
      warn "$node: port $port busy but no PID visible (need root?) — trying pkill"
    fi
    return 1
  fi
  # Replace newlines with spaces in case port_pid returned multiple PIDs
  local pids; pids="$(echo "$pid" | tr '\n' ' ')"
  ssh_out "$node" "kill -TERM $pids"
  local i
  for i in $(seq 1 15); do
    if ! port_in_use "$node" "$port"; then return 0; fi
    sleep 1
  done
  ssh_out "$node" "kill -KILL $pids"
  sleep 2
  ! port_in_use "$node" "$port"
}

kill_by_pattern() {  # <node> <pattern>  last-resort cleanup when no PID is visible
  local node="$1" pat="$2"
  # Target only strays outside our own process group to avoid killing the caller's ssh session
  ssh_out "$node" "bash -c '
    own=\$(ps -o pgid= -p \$\$ 2>/dev/null | tr -d \" \")
    pids=\$(pgrep -f \"$pat\" 2>/dev/null || true)
    targets=\"\"
    for p in \$pids; do
      [ \"\$p\" = \"\$\$\" ] && continue
      [ \"\$p\" = \"\$PPID\" ] && continue
      pg=\$(ps -o pgid= -p \"\$p\" 2>/dev/null | tr -d \" \")
      [ -n \"\$pg\" ] && [ -n \"\$own\" ] && [ \"\$pg\" = \"\$own\" ] && continue
      targets=\"\$targets \$p\"
    done
    if [ -n \"\$targets\" ]; then
      kill -TERM \$targets 2>/dev/null || true
      sleep 3
      kill -KILL \$targets 2>/dev/null || true
    fi
  '"
}

# --- misc --------------------------------------------------------------------
node_ip() {  # <node-alias> -> LAN IP (from NODE_IPS, matched by position)
  local want="$1" i ip
  for i in "${!NODES[@]}"; do
    if [[ "${NODES[$i]}" == "$want" ]]; then
      # 2026-09-28 : `${NODE_IPS[$i]:-}` -- a MISSING index (NODE_IPS SHORTER than
      # NODES, i.e. a partial topology edit) used to abort the CALLER with
      # "unbound variable" under `set -u`, which every consumer (`set -euo
      # pipefail`) sets. Verified: `set -u; NODES=(a b c); NODE_IPS=(1 2)` exits
      # 127 on the third index. The documented contract is to fall back to the
      # alias; an empty entry must do the same, not kill cluster_status.sh.
      ip="${NODE_IPS[$i]:-}"
      [[ -n "$ip" ]] || break
      printf '%s' "$ip"; return 0
    fi
  done
  printf '%s' "$want"   # fall back to the alias
}

require_script() { [[ -x "$1" ]] || die "not found or not executable: $1"; }
