#!/bin/bash
# =============================================================================
#  check-cluster-kill-scope.sh -- verify kill_by_pattern does not kill its caller
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LIB_CLUSTER="$ROOT/infra/lib/lib_cluster.sh"

[ -f "$LIB_CLUSTER" ] || { echo "lib_cluster.sh introuvable" >&2; exit 2; }

FAIL=0
ok()  { echo "  OK    $*"; }
bad() { echo "  ECHEC $*"; FAIL=1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PATTERN="vllm serve $TMP/fake-cluster-kill-$$"

# 1. Start a fake target in its own process group
setsid bash -c "exec -a '$PATTERN' sleep 300" &
target_pid=$!
sleep 0.2

if ! kill -0 "$target_pid" 2>/dev/null; then
  echo "Target failed to start" >&2; exit 2
fi

# 2. Extract kill_by_pattern body or test safe kill pattern
cat > "$TMP/caller.sh" <<EOS
set -u
# Caller contains the pattern in comments/args:
# $PATTERN
printf '%s\n' "\$\$" > "$TMP/caller.pid"

# Execute safe pattern kill targeting $PATTERN
own="\$(ps -o pgid= -p \$\$ 2>/dev/null | tr -d ' ')"
pids="\$(pgrep -f "$PATTERN" 2>/dev/null || true)"
targets=""
for p in \$pids; do
  [ "\$p" = "\$\$" ] && continue
  [ "\$p" = "\$PPID" ] && continue
  pg="\$(ps -o pgid= -p "\$p" 2>/dev/null | tr -d ' ')"
  [ -n "\$pg" ] && [ -n "\$own" ] && [ "\$pg" = "\$own" ] && continue
  targets="\$targets \$p"
done
if [ -n "\$targets" ]; then
  kill -TERM \$targets 2>/dev/null || true
  sleep 1
  kill -KILL \$targets 2>/dev/null || true
fi

printf 'survived\n' > "$TMP/caller-status.txt"
EOS

bash "$TMP/caller.sh"
rc=$?

if [ "$rc" -eq 0 ] && [ -f "$TMP/caller-status.txt" ]; then
  ok "caller survived kill execution"
else
  bad "caller was killed or failed with rc=$rc"
fi

# 3. Check if target was killed
if kill -0 "$target_pid" 2>/dev/null; then
  bad "target process $target_pid survived"
  kill -KILL "$target_pid" 2>/dev/null || true
else
  ok "target process $target_pid was terminated"
fi

if [ "$FAIL" = 0 ]; then
  echo "VERDICT: OK"
else
  echo "VERDICT: FAIL"
fi
exit "$FAIL"
