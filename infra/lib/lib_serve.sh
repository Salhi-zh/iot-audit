# shellcheck shell=bash
# =============================================================================
# lib_serve.sh — shared orchestration for start_*/stop_* scripts.
# Source after cluster.env + lib_cluster.sh + lib_serve.sh.
# =============================================================================

# Launch one server per node in parallel. <launcher_fn> receives (node port vram_mb).
serve_launch_all() {
  local label="$1" port="$2" minvram="$3" launcher="$4"
  log "Launching $label (port $port) on: ${NODES[*]}"
  local n p rc=0 pids=()
  for n in "${NODES[@]}"; do
    "$launcher" "$n" "$port" "$minvram" &
    pids+=("$!")
  done
  for p in "${pids[@]}"; do wait "$p" || rc=1; done
  return $rc
}

# The launcher writes $HOME/logs/${label}_$(hostname -s).log -- the node's REAL
# hostname -- while the loops below only know the SSH alias. The two coincide on this
# cluster, but nothing enforces it: README assumption 5 states it as a thing to verify,
# and the nodes still carry `~/logs/qwen_zabeth71.*` from a period when it did not hold,
# so the hint named a file that did not exist. Ask the node; fall back to the alias
# when it is unreachable, so a failed start still prints a hint rather than nothing.
serve_log_name() {   # <node> <label> -> prints the log basename
  local h; h="$(ssh_out "$1" 'hostname -s' 2>/dev/null)" || h=""
  printf '%s_%s.log' "$2" "${h:-$1}"
}

# Poll /v1/models on every node in parallel; prints a table; 0 only if all answer.
serve_wait_all() {
  local label="$1" port="$2" timeout="${3:-$BOOT_TIMEOUT}"
  log "Waiting for $label /v1/models on port $port (timeout ${timeout}s)"
  local tmp n rc=0
  tmp="$(mktemp -d)"
  for n in "${NODES[@]}"; do
    ( if wait_api "$n" "$port" "$timeout"; then echo ok >"$tmp/$n"; else echo fail >"$tmp/$n"; fi ) &
  done
  wait
  printf '%-10s %-6s %-8s %s\n' NODE PORT STATUS LOG
  printf '%-10s %-6s %-8s %s\n' ---- ---- ------ ---
  for n in "${NODES[@]}"; do
    local logn; logn="$(serve_log_name "$n" "$label")"
    if [[ "$(cat "$tmp/$n" 2>/dev/null)" == ok ]]; then
      printf '%-10s %-6s %-8s %s\n' "$n" "$port" "OK" "~/logs/$logn"
    else
      printf '%-10s %-6s %-8s %s\n' "$n" "$port" "FAILED" "~/logs/$logn"
      rc=1
    fi
  done
  rm -rf "$tmp"
  return $rc
}

# TERM the listener on each node, verify the port is released.
serve_stop_all() {
  local label="$1" port="$2" pattern="$3" n rc=0
  log "Stopping $label (port $port) on: ${NODES[*]}"
  for n in "${NODES[@]}"; do
    if ! node_up "$n"; then err "$n: unreachable — cannot confirm stop"; rc=1; continue; fi
    if ! port_in_use "$n" "$port"; then ok "$n: port $port already free"; continue; fi

    if kill_port "$n" "$port"; then
      ok "$n: port $port released"
    else
      warn "$n: no PID visible for port $port — falling back to pkill -f '$pattern'"
      kill_by_pattern "$n" "$pattern"
      sleep 1
      if port_in_use "$n" "$port"; then
        err "$n: port $port STILL in use"; rc=1
      else
        ok "$n: port $port released (pkill)"
      fi
    fi
  done
  return $rc
}

# Print the last lines of each node's log (for a failed start).
serve_tail_logs() {
  local label="$1" n
  for n in "${NODES[@]}"; do
    local logn; logn="$(serve_log_name "$n" "$label")"
    echo "--- $n: ~/logs/$logn (tail) ---"
    ssh_out "$n" "tail -n 25 \$HOME/logs/$logn 2>/dev/null" || echo "(no log)"
  done
}
