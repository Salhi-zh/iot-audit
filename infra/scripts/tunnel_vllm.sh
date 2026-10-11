#!/usr/bin/env bash
# =============================================================================
# tunnel_vllm.sh — local SSH tunnel to a zabeth node's vLLM service.
#
# WHY THIS EXISTS (2026-10-06). Every "live" benchmark in this repo used to tell
# the reader to type the tunnel by hand:
#
#     ssh -fN -L 18000:172.26.145.71:8000 zabeth21
#
# That line was copied into four docstrings (live_vlm_orchestrator,
# live_cross_node, live_specificity_protocol, live_specificity_smoke) with
# options that had already diverged, and NOTHING relaunched it when it died.
# It dies often: the portier gateway drops the forwarding connection several
# times an hour (measured over the 2026-10-05/06 sessions). The failure is
# silent and it is misread — a benchmark that cannot reach the model looks
# exactly like a benchmark that ran and produced nothing, and the day this
# script was written the tunnel had in fact been dead for hours behind a stray
# hand-started loop nobody owned.
#
# WHAT IT DOES
#   start    self-healing tunnel in the background (a relaunch loop, not a
#            single `ssh -fN` that dies once and stays dead)
#   stop     stops the loop AND any orphan forwarder on the same local port
#   status   says whether the tunnel really ANSWERS — an HTTP request, not just
#            a listening socket (a half-open tunnel keeps the listener)
#   restart  stop, then start
#
# MEASURED BEHAVIOURS THAT SHAPED IT
#   * A local listener proves nothing. When the remote end goes away the local
#     socket can survive; a new `ssh -L` then fails with `bind: Address already
#     in use` / ExitOnForwardFailure and the tunnel never comes back. `start`
#     therefore clears forwarders that hold the port without answering.
#   * `pkill -f "L 18000"` kills the shell that runs it, because the pattern is
#     on its own command line. The pattern is built bracketed (see
#     `bracketed_port`) so the caller never matches itself — same defect class
#     as check-stop-scope.sh (2026-09-28) and check-cluster-kill-scope.sh.
#     Verified by selftest/check-tunnel-scope.sh.
#
# Usage:
#   infra/scripts/tunnel_vllm.sh [status|start|stop|restart]
#                               [--node zabeth21] [--port 18000] [--foreground]
#
# Defaults come from infra/config/cluster.env: the first node of NODES, its
# matching entry in NODE_IPS, and QWEN_PORT as the remote port. 18000 is the
# historical local port baked into every benchmark's --endpoint default, so it
# is kept as the default here rather than invented afresh.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"

ACTION="status"
NODE="${TUNNEL_NODE:-${NODES[0]}}"
PORT="${TUNNEL_PORT:-18000}"
FOREGROUND=0

usage() { sed -n '2,45p' "$0"; }

while (( $# )); do
  case "$1" in
    status|start|stop|restart) ACTION="$1" ;;
    --node)       NODE="${2:?--node needs a value}"; shift ;;
    --port)       PORT="${2:?--port needs a value}"; shift ;;
    --foreground) FOREGROUND=1 ;;
    -h|--help)    usage; exit 0 ;;
    *) die "unknown argument: $1  (see --help)" ;;
  esac
  shift
done

REMOTE_IP="$(node_ip "$NODE")"
REMOTE_PORT="${QWEN_PORT:-8000}"
ENDPOINT="http://127.0.0.1:$PORT/v1/models"

RUNDIR="${XDG_RUNTIME_DIR:-/tmp}/iot-audit-tunnel"
PIDFILE="$RUNDIR/$PORT.pid"
LOGFILE="$RUNDIR/$PORT.log"

# --- the two properties the selftest pins ------------------------------------
#
# bracketed_port: turn 18000 into 1800[0]. As a regex that still matches the
# real forwarder's argv ("-L 18000:...") but NOT the text of the pattern
# itself, so a caller whose own command line carries the pattern cannot select
# itself. This is the whole reason the script is safe to run from a wrapper.
bracketed_port() {
  local p="${1:?bracketed_port needs a port}"
  printf '%s[%s]' "${p%?}" "${p: -1}"
}

# port_pattern: the argv fragment every forwarder for this port carries.
port_pattern() {
  printf '%s' "-L $(bracketed_port "$1"):"
}

# ancestor_pids: our own pid, then every ancestor up to init. A signal sent to
# any of these takes down the shell that invoked us — and that shell is not
# hypothetical: a wrapper (CI job, agent, `bash -c '... ssh -N -L 18000:...'`)
# carries the forwarding text on its OWN command line, so a pattern search finds
# it. MEASURED 2026-10-06: the first version of this script excluded only $$ and
# $PPID, and the selftest caught it selecting the caller's grandparent. The
# ancestor chain is the precise exclusion — nothing can be its own ancestor.
ancestor_pids() {
  local p="$$" n=0
  while [ -n "$p" ] && [ "$p" != "0" ] && [ "$p" != "1" ] && (( n++ < 64 )); do
    printf '%s\n' "$p"
    p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
  done
}

_is_protected() {  # 0 when <pid> is us or one of our ancestors
  local pid="$1" a
  for a in $(ancestor_pids); do
    [ "$pid" = "$a" ] && return 0
  done
  return 1
}

# _pat_pids: every process whose command line carries the forwarding spec and
# that we are ALLOWED to signal.
_pat_pids() {
  local pat pid
  pat="$(port_pattern "$PORT")"
  for pid in $(pgrep -f -- "$pat" 2>/dev/null || true); do
    _is_protected "$pid" && continue
    printf '%s\n' "$pid"
  done
}

# forwarder_pids: carriers that really are ssh forwarders. This is the precise
# set — match on the executable, not merely on the text, so a wrapper shell that
# happens to mention the tunnel is not a candidate.
forwarder_pids() {
  local pid
  for pid in $(_pat_pids); do
    [ "$(cat "/proc/$pid/comm" 2>/dev/null)" = "ssh" ] && printf '%s\n' "$pid"
  done
}

# holder_pids: every carrier. Used ONLY when the port is still held after the
# forwarders are gone, which is the signature of a foreign relaunch loop that
# would otherwise respawn the tunnel we just stopped. Still never our ancestry.
holder_pids() { _pat_pids; }

# Backwards-compatible name used by the selftest and by earlier callers.
stray_pids() { holder_pids; }

# --- helpers -----------------------------------------------------------------

# Real end-to-end probe. `-f` makes curl exit non-zero on any HTTP error, so a
# listener whose remote end is gone (connection closes with no response) fails
# here instead of looking healthy.
probe() {
  curl -sf -m 5 "$ENDPOINT" 2>/dev/null
}

tunnel_up() { probe >/dev/null 2>&1; }

model_id() {  # from a /v1/models body, the MODEL id only
  # Not `sed 's/.*"id":"..."'`: `.*` is greedy, so it lands on the LAST "id"
  # in the document and reports a permission token (`modelperm-…`) instead of
  # the model name. Measured 2026-10-06 — the wrong value looked plausible.
  grep -o '"id":"[^"]*"' | head -n1 | cut -d'"' -f4
}

ssh_forward_opts() {
  # One definition, so no caller can drift from another. ServerAlive* let the
  # loop notice a dead gateway in ~20 s instead of hanging until the OS
  # TCP timeout; ExitOnForwardFailure makes the failure loud and immediate.
  printf '%s' "-o ServerAliveInterval=10 -o ServerAliveCountMax=2 -o ExitOnForwardFailure=yes -o ConnectTimeout=8 -o BatchMode=yes"
}

listener_present() {
  ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .
}

# --- actions -----------------------------------------------------------------

do_status() {
  printf 'node        : %s (%s)\n' "$NODE" "$REMOTE_IP"
  printf 'forwarding  : 127.0.0.1:%s -> %s:%s\n' "$PORT" "$REMOTE_IP" "$REMOTE_PORT"
  printf 'endpoint    : %s\n' "$ENDPOINT"
  printf 'listener    : %s\n' "$(listener_present && echo present || echo absent)"
  local body
  if body="$(probe)"; then
    ok "service reachable - model '$(printf '%s' "$body" | model_id)'"
    return 0
  fi
  err "no HTTP answer on $ENDPOINT"
  if listener_present; then
    warn "a listener holds :$PORT but does not answer - half-open tunnel; run 'start' to clear and rebind"
  fi
  return 1
}

do_stop() {
  local pids
  # 1. the loop this script started, by PID file. `kill -TERM -PID` targets the
  #    GROUP (the loop plus the ssh child it is blocked on); killing only the
  #    loop would leave the current ssh forwarder alive until it was noticed.
  if [ -f "$PIDFILE" ]; then
    local lp
    lp="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$lp" ]; then
      kill -TERM "-$lp" 2>/dev/null || kill -TERM "$lp" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
  fi
  # 2. real ssh forwarders for this port (precise: executable, not text).
  pids="$(forwarder_pids | tr '\n' ' ')"
  if [ -n "${pids// /}" ]; then
    # shellcheck disable=SC2086
    kill -TERM $pids 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -KILL $pids 2>/dev/null || true
  fi
  sleep 1
  # 3. If the port is STILL held, a foreign relaunch loop owns it — a hand-made
  #    `while true; do ssh -N -L ...; done` respawns what we just killed. Killing
  #    it is the point of `stop`, so it is done, but it is announced: this is the
  #    one step that signals a process which is not an ssh forwarder.
  if listener_present; then
    local holders
    holders="$(holder_pids | tr '\n' ' ')"
    if [ -n "${holders// /}" ]; then
      warn "port :$PORT still held - killing the relaunch loop holding it: $holders"
      # shellcheck disable=SC2086
      kill -TERM $holders 2>/dev/null || true
      sleep 1
      # shellcheck disable=SC2086
      kill -KILL $holders 2>/dev/null || true
      sleep 1
    fi
  fi
  if listener_present; then
    warn "port :$PORT is still held after stop (not ours?)"
    return 1
  fi
  ok "tunnel stopped (port :$PORT free)"
}

do_start() {
  if tunnel_up; then
    ok "tunnel already answering on 127.0.0.1:$PORT"
    return 0
  fi
  mkdir -p "$RUNDIR"
  # A listener that does not answer cannot be rebound (ExitOnForwardFailure),
  # so clear it first. Measured on 2026-10-06: this is the difference between
  # `start` recovering a dropped gateway and `start` failing instantly.
  # A stale holder may be a relaunch loop, not an ssh, so every carrier is used
  # here — still never our own ancestry.
  local stale
  stale="$(holder_pids | tr '\n' ' ')"
  if [ -n "${stale// /}" ]; then
    warn "clearing process(es) holding :$PORT without answering: $stale"
    # shellcheck disable=SC2086
    kill -TERM $stale 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -KILL $stale 2>/dev/null || true
  fi

  local sshs loop
  sshs="$(ssh_forward_opts)"
  if (( FOREGROUND )); then
    log "foreground tunnel: 127.0.0.1:$PORT -> $REMOTE_IP:$REMOTE_PORT ($NODE)"
    # shellcheck disable=SC2086
    exec ssh -N $sshs -L "$PORT:$REMOTE_IP:$REMOTE_PORT" "$NODE"
  fi

  # The relaunch text is built with printf rather than embedded quoting so the
  # `$$` below is expanded by the CHILD (it must record its own pid, which is
  # also the session leader thanks to setsid, so the group can be signalled).
  printf -v loop '%s\n' \
    "echo \$\$ > '$PIDFILE'" \
    "while true; do" \
    "  ssh -N $sshs -L '$PORT:$REMOTE_IP:$REMOTE_PORT' '$NODE'" \
    "  echo \"[tunnel] \$(date -Is) connexion perdue - relance dans 3 s\"" \
    "  sleep 3" \
    "done"
  : >"$LOGFILE"
  setsid bash -c "$loop" >>"$LOGFILE" 2>&1 &

  local waited=0
  while (( waited < 20 )); do
    if tunnel_up; then
      ok "tunnel up: 127.0.0.1:$PORT -> $REMOTE_IP:$REMOTE_PORT ($NODE), pid $(cat "$PIDFILE" 2>/dev/null)"
      printf 'log         : %s\n' "$LOGFILE"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  err "tunnel did not answer within 20 s"
  [ -s "$LOGFILE" ] && { printf 'last log lines:\n'; tail -n5 "$LOGFILE"; }
  return 1
}

case "$ACTION" in
  status)  do_status ;;
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; do_start ;;
esac
