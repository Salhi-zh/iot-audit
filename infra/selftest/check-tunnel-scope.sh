#!/bin/bash
# =============================================================================
#  check-tunnel-scope.sh -- the tunnel's stop path must not kill its caller
# =============================================================================
# WHY. `tunnel_vllm.sh stop` has to find and signal the SSH forwarder for its
# port. The naive way -- `pkill -f "L 18000"` -- kills the shell that runs it,
# because the pattern is on that shell's OWN command line. This was not
# hypothetical: the first version of the script excluded only $$ and $PPID, and
# THIS CHECK caught it selecting the caller's GRANDPARENT (an agent/CI wrapper
# whose command line mentioned the tunnel). The real thing happened twice during
# the writing session -- a cleanup `pkill` took down the pipeline it was part of.
#
# The fix is an ANCESTRY exclusion: nothing can be its own ancestor, so the
# caller and everything above it are unreachable. The bracket in the pattern
# (`bracketed_port`) is defence in depth for a caller that carries the pattern
# text verbatim, and it is NOT sufficient on its own -- the negative control
# below shows the naive form selecting the caller's parent.
#
# Offline and deterministic: no node, no ssh, no network. Nothing here touches
# port 18000 or the live tunnel -- every check uses 18999, which no forwarder
# uses. The "forwarder" is a copy of `sleep` named `ssh`, so /proc/<pid>/comm is
# genuinely "ssh" without needing a real connection.
#
#   bash selftest/check-tunnel-scope.sh
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SCRIPT="$ROOT/infra/scripts/tunnel_vllm.sh"

FAIL=0
ok()  { echo "  OK    $*"; }
bad() { echo "  ECHEC $*"; FAIL=1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

[ -f "$SCRIPT" ] || { echo "tunnel_vllm.sh introuvable : $SCRIPT" >&2; exit 2; }

# --- extraction, never a copy ------------------------------------------------
# A test that exercises its own copy of a function proves nothing about the
# script. The functions are pulled out of the real file, by name.
extract_fn() {
  awk -v fn="$1" '$0 ~ "^" fn "\\(\\)" {d=1} d {print} d && /^}/ {exit}' "$SCRIPT"
}

FNS="bracketed_port port_pattern ancestor_pids _is_protected _pat_pids forwarder_pids holder_pids"
for fn in $FNS; do
  body="$(extract_fn "$fn")"
  if [ -z "$body" ]; then
    bad "extraction de $fn vide (la fonction a-t-elle ete renommee ?)"
    continue
  fi
  if bash -n <(printf '%s\n' "$body"); then
    ok "$fn extraite et shell valide"
  else
    bad "$fn extraite n'est pas du shell valide"
  fi
done

# shellcheck disable=SC2086
eval "$(for fn in $FNS; do extract_fn "$fn"; done)"

# --- 1. the pattern's shape --------------------------------------------------
if [ "$(bracketed_port 18000)" = "1800[0]" ]; then
  ok "bracketed_port 18000 -> 1800[0]"
else
  bad "bracketed_port 18000 -> '$(bracketed_port 18000)' (attendu 1800[0])"
fi

if [ "$(bracketed_port 7)" = "[7]" ]; then
  ok "bracketed_port gere un port a un chiffre"
else
  bad "bracketed_port 7 -> '$(bracketed_port 7)' (attendu [7])"
fi

PAT="$(port_pattern 18000)"
if [ "$PAT" = "-L 1800[0]:" ]; then
  ok "port_pattern 18000 -> '-L 1800[0]:'"
else
  bad "port_pattern 18000 -> '$PAT'"
fi

if printf '%s' "-L 1800[0]:" | grep -Eq -- "$PAT"; then
  bad "le motif se selectionne lui-meme : un appelant qui le porte serait vu"
else
  ok "le motif ne correspond pas a sa propre ecriture"
fi
if printf '%s' "-L 18000:172.26.145.71:8000" | grep -Eq -- "$PAT"; then
  ok "le motif correspond a un vrai redirecteur"
else
  bad "le motif ne correspond pas a un vrai redirecteur : stop ne trouverait rien"
fi

# --- 2. ancestry: nothing above us may ever be signalled ---------------------
STRAYPORT=18999

{ for fn in $FNS; do extract_fn "$fn"; done; } > "$TMP/fns.sh"

# A real forwarder: a copy of `sleep` NAMED ssh, so /proc/<pid>/comm == "ssh".
mkdir -p "$TMP/bin"
cp "$(command -v sleep)" "$TMP/bin/ssh"
setsid bash -c "exec -a 'ssh -N -o BatchMode=yes -L $STRAYPORT:172.26.145.71:8000 zabeth21' '$TMP/bin/ssh' 300" &
forwarder_pid=$!
sleep 0.3
if kill -0 "$forwarder_pid" 2>/dev/null && [ "$(cat "/proc/$forwarder_pid/comm")" = "ssh" ]; then
  ok "redirecteur factice en place (pid $forwarder_pid, comm=ssh)"
else
  echo "le redirecteur de test n'a pas demarre" >&2; exit 2
fi

# One record per line, `TAG pid`. The first version printed space-separated
# lists on a single line and the parser kept only the first pid of each list --
# so the negative control was reading a truncated NAIVE and reported a defect
# that did not exist. A format that cannot be mis-split is part of the test.
cat > "$TMP/driver.sh" <<'DRIVER'
set -uo pipefail
PORT="$DRIVER_PORT"
. "$DRIVER_FNS"
printf 'SELF %s\n' "$$"
printf 'PARENT %s\n' "$PPID"
pgrep -f -- "$(port_pattern "$PORT")" 2>/dev/null | sed 's/^/NAIVE /'
forwarder_pids | sed 's/^/FWD /'
holder_pids | sed 's/^/HOLD /'
DRIVER

# The driver is launched from a wrapper whose OWN command line carries the
# plain pattern -- the shape that made the first version dangerous. The wrapper
# is the driver's parent, so it must survive.
wrapper="DRIVER_PORT=$STRAYPORT DRIVER_FNS='$TMP/fns.sh' bash '$TMP/driver.sh' ; : '-L $STRAYPORT:172.26.145.71:8000'"
result="$(setsid bash -c "$wrapper" 2>/dev/null)"

field() {  # every pid tagged $1, space-joined, no trailing separator
  awk -v t="$1" '$1 == t {printf "%s%s", (n++ ? " " : ""), $2}' <<<"$result"
}
SELF="$(field SELF)"; PARENT="$(field PARENT)"
NAIVE="$(field NAIVE)"; FWD="$(field FWD)"; HOLD="$(field HOLD)"
evidence="SELF='${SELF:-}' PARENT='${PARENT:-}' NAIVE='${NAIVE:-}' FWD='${FWD:-}' HOLD='${HOLD:-}'"

seen() {  # seen <space-joined-pids> <pid>
  case " ${1:-} " in *" $2 "*) return 0 ;; esac
  return 1
}

if [ -z "${SELF:-}" ]; then
  bad "le pilote n'a pas rendu son verdict ($evidence ; brut : $result)"
else
  ok "pilote lance (pid $SELF), lance par un wrapper dont l'argv porte le motif"
fi

if seen "$FWD" "$forwarder_pid"; then
  ok "forwarder_pids SELECTIONNE le vrai redirecteur"
else
  bad "forwarder_pids ne voit pas le redirecteur ($evidence, attendu $forwarder_pid)"
fi

if seen "$HOLD" "$forwarder_pid"; then
  ok "holder_pids selectionne aussi le redirecteur"
else
  bad "holder_pids ne voit pas le redirecteur ($evidence)"
fi

if seen "$HOLD" "${SELF:-x}"; then
  bad "holder_pids selectionne le PILOTE -> stop se tuerait ($evidence)"
else
  ok "holder_pids NE selectionne PAS le pilote"
fi

if seen "$HOLD" "${PARENT:-x}"; then
  bad "holder_pids selectionne l'ANCETRE (wrapper) -> stop tuerait l'appelant ($evidence)"
else
  ok "holder_pids NE selectionne PAS l'ancetre, meme quand son argv porte le motif"
fi

if seen "$FWD" "${PARENT:-x}"; then
  bad "forwarder_pids selectionne l'ancetre ($evidence)"
else
  ok "forwarder_pids NE selectionne PAS l'ancetre"
fi

# NEGATIVE CONTROL. Without it, everything above would pass just as well on a
# function that returned nothing at all. The naive search MUST see the ancestor:
# that is the defect the ancestry exclusion exists to prevent.
if seen "$NAIVE" "${PARENT:-x}"; then
  ok "controle negatif : pgrep -f nu SELECTIONNE l'ancetre (l'exclusion est bien portante)"
else
  bad "controle negatif muet : la forme nue ne voit pas l'ancetre ($evidence)"
fi

kill -TERM "$forwarder_pid" 2>/dev/null || true

# --- 3. end to end: stop run from a caller carrying the pattern --------------
# 18009 has no forwarder, so `stop` finds nothing and must still exit cleanly.
out="$(bash -c "printf 'caller -L 1809[9]:\n' >/dev/null; '$SCRIPT' stop --port 18009; echo SURVIVED" 2>&1 || true)"
if grep -q 'SURVIVED' <<<"$out"; then
  ok "l'appelant survit a 'stop' quand sa ligne de commande porte le motif"
else
  bad "l'appelant n'a pas survecu a 'stop' ; sortie : $(tr '\n' '|' <<<"$out")"
fi

echo
if (( FAIL )); then
  echo "VERDICT : ECHEC"
  exit 1
fi
echo "VERDICT : OK"
