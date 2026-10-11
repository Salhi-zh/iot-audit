#!/usr/bin/env bash
# =============================================================================
# bootstrap_ssh.sh — install an SSH key so every other script can run without a
# password prompt (they all use BatchMode=yes, i.e. no interactive fallback).
#
#   ./bootstrap_ssh.sh                      # dry-run: prints exactly what it does
#   ./bootstrap_ssh.sh --yes                # install the key: host -> gateway -> nodes
#   ./bootstrap_ssh.sh --yes --node-to-node # ...and make the NODES trust each other
#
# The password is read from $ZABETH_SSH_PASS, or from ~/.zabeth_pass (chmod 600).
# It is NEVER written to disk by this script and must never be committed.
#
#   1. generate ~/.ssh/id_zabeth if missing
#   2. copy it to the portier gateway          (password once)
#   3. copy it to each node via ProxyJump      (password once per node)
#   4. --node-to-node: enrol each node with its peers (private key + client config)
#   5. verify passwordless login on all three, and (with 4) between all six pairs
#
# Step 4 is what makes `sync_models.sh` move artifacts node->node over the LAN
# instead of relaying them through this host. It is OFF by default because it puts
# the same private key on four machines — read the note at step 4 first.
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"

CONFIRM=0
NODE2NODE=0
while (( $# )); do
  case "$1" in
    --yes)          CONFIRM=1 ;;
    --node-to-node) NODE2NODE=1 ;;
    -h|--help)      sed -n '3,21p' "$0"; exit 0 ;;
    *)              die "unknown argument: $1" ;;
  esac
  shift
done

GW="${GATEWAY_USER}@${GATEWAY_HOST}"
JUMP="${GATEWAY_USER}@${GATEWAY_HOST}:${GATEWAY_PORT}"

log "SSH key : $SSH_KEY"
log "Gateway : $GW (port $GATEWAY_PORT)"
log "Nodes   : ${NODES[*]}"

# The password is only needed to AUTHENTICATE. A dry run must not need it: this
# script used to `die` on a missing password *before* printing the plan, so the
# documented "just prints what it would do" invocation failed outright whenever
# no secret was exported (verified 2026-09-17: exit 1, no plan printed).
PASS="${ZABETH_SSH_PASS:-}"
if [[ -z "$PASS" && -f "$HOME/.zabeth_pass" ]]; then
  PASS="$(cat "$HOME/.zabeth_pass")"
fi

if (( ! CONFIRM )); then
  echo
  warn "DRY RUN. Planned actions:"
  echo "  1) ssh-keygen -t ed25519 -N '' -f $SSH_KEY   (only if missing)"
  echo "  2) ssh-copy-id $SSH_KEY.pub -> $GW"
  for ip in "${NODE_IPS[@]}"; do
    echo "  3) ssh-copy-id $SSH_KEY.pub -> ${NODE_USER}@${ip}  (ProxyJump $JUMP)"
  done
  if (( NODE2NODE )); then
    echo "  4) --node-to-node: copy the PRIVATE key to each node ($SSH_KEY) and install"
    echo "     a client config there covering ${NODES[*]}"
    echo "     AND ${NODE_IPS[*]}"
    echo "     (sync_models.sh addresses peers by LAN IP, so the IP forms are required)"
  fi
  echo
  if [[ -n "$PASS" ]]; then
    echo "  password : supplied (will authenticate once --yes is given)"
  else
    echo "  password : MISSING -- export ZABETH_SSH_PASS or write ~/.zabeth_pass (chmod 600) before --yes"
  fi
  echo
  echo "Re-run with --yes to perform these steps."
  exit 0
fi

[[ -n "$PASS" ]] || die "no password: set ZABETH_SSH_PASS or create ~/.zabeth_pass (chmod 600)"
for c in ssh-keygen ssh-copy-id setsid; do
  command -v "$c" >/dev/null || die "$c not found"
done

# ---------------------------------------------------------------------------
# Two-hop authentication. This script used `sshpass -e ssh-copy-id … -o
# ProxyJump=…`, which CANNOT work here: sshpass answers the first prompt it sees
# (the gateway's) and the second ssh — the one that actually reaches the node —
# never receives the secret. Measured 2026-09-17 from the workstation against the
# live cluster:
#   sshpass -e ssh -o ProxyJump=… msalhi@172.26.145.72 hostname   -> rc=5, no output
#   (identical with -o PreferredAuthentications=password -o PubkeyAuthentication=no)
#   ssh with SSH_ASKPASS_REQUIRE=force + ProxyJump                -> rc=0 on all three
# This is the same mechanism `~/zabeth22-vllm-repair/remote.sh` already uses. It
# also drops the sshpass dependency and keeps the secret out of argv entirely:
# it lives in the environment of a 0700 helper process, never on a command line.
# ---------------------------------------------------------------------------
ASK_DIR="$(mktemp -d)"
printf '%s\n%s\n' '#!/bin/sh' 'printf "%s\n" "$ZABETH_PW"' >"$ASK_DIR/ask.sh"
chmod 700 "$ASK_DIR/ask.sh"
trap 'rm -rf "$ASK_DIR"' EXIT
export ZABETH_PW="$PASS" SSH_ASKPASS="$ASK_DIR/ask.sh" SSH_ASKPASS_REQUIRE=force
copy_key() { setsid -w ssh-copy-id -o StrictHostKeyChecking=accept-new "$@"; }

# 1 — key
if [[ -f "$SSH_KEY" ]]; then
  ok "key already exists: $SSH_KEY"
else
  log "generating $SSH_KEY"
  mkdir -p "$(dirname "$SSH_KEY")"; chmod 700 "$(dirname "$SSH_KEY")"
  ssh-keygen -t ed25519 -N '' -f "$SSH_KEY" -C "iot-audit-infra"
  ok "key generated"
fi

# 2 — gateway
log "installing key on the gateway"
copy_key -i "$SSH_KEY.pub" -p "$GATEWAY_PORT" "$GW"
ok "gateway key installed"

# 3 — nodes (gateway reached by key now, node password is the only prompt)
for ip in "${NODE_IPS[@]}"; do
  log "installing key on ${NODE_USER}@${ip}"
  copy_key -i "$SSH_KEY.pub" -o "ProxyJump=${JUMP}" "${NODE_USER}@${ip}"
  ok "${ip} key installed"
done

# 4 — OPTIONAL: enrol the nodes with each other
#
# Steps 1-3 authorise the PUBLIC key on every node, which is enough for
# host -> node. It is NOT enough for node -> node: the private key only exists
# here, so `sync_models.sh`'s peer transfers have nothing to authenticate with,
# its reachability test fails, and it silently falls back to relaying through the
# orchestrator (a 6.9 GB stream over the bastion instead of a LAN copy). The
# README's "install the key on all nodes for direct LAN transfers" therefore only
# becomes true with this step.
#
# Two things are needed, and the second is easy to miss: each node must hold the
# PRIVATE key, and its client config must match the addresses that are actually
# used. sync_models.sh builds its peer command from `node_ip` and so always
# addresses `msalhi@172.26.145.NN` — never the alias — while ssh applies
# `IdentityFile` only to a Host pattern that matches. A name-only config falls
# back to the default identities and the direct path looks unreachable.
#
# COST: the same private key then exists on four machines. Anyone who can read
# `~/.ssh/id_zabeth` on any node can log into all of them. Accept that, or keep
# this step off and live with the relay.
if (( NODE2NODE )); then
  echo
  log "node-to-node: enrolling every node with its peers"
  NODE_CFG="Host ${NODES[*]} ${NODE_IPS[*]}
    User $NODE_USER
    IdentityFile ~/.ssh/id_zabeth
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    ServerAliveInterval 30
    ServerAliveCountMax 3"
  for i in "${!NODES[@]}"; do
    if [[ -n "${NODE_IPS[$i]:-}" ]]; then
      NODE_CFG+=$'\n\n'"Host ${NODES[$i]}
    HostName ${NODE_IPS[$i]}"
    fi
  done
  # 2026-09-28 : la sauvegarde etait a usage UNIQUE -- `[ ! -f ....bak-bootstrap ]`
  # la sautait des qu'elle existait, donc une 2e execution ecrasait le ~/.ssh/config
  # courant (cat > en dessous) en ne conservant que la toute premiere version. Une
  # sauvegarde horodatee a chaque passage rend l'ecrasement reversible.
  BKSTAMP="$(date -u +%Y%m%d-%H%M%S)"
  for n in "${NODES[@]}"; do
    if ! node_up "$n"; then err "$n unreachable — skipped"; continue; fi
    ssh_out "$n" "[ -f ~/.ssh/config ] && cp -p ~/.ssh/config ~/.ssh/config.bak-$BKSTAMP; true"
    ssh_run "$n" 'umask 077; cat > ~/.ssh/id_zabeth && chmod 600 ~/.ssh/id_zabeth' <"$SSH_KEY" \
      || { err "$n: could not install the private key"; continue; }
    printf '%s\n' "$NODE_CFG" | ssh_run "$n" 'umask 077; cat > ~/.ssh/config && chmod 600 ~/.ssh/config' \
      || { err "$n: could not install the client config"; continue; }
    ok "$n: private key + peer config installed"
  done
fi

# 5 — verify
echo
log "verifying passwordless login"
FAIL=0
for n in "${NODES[@]}"; do
  if ssh_out "$n" true; then ok "$n"; else err "$n: still not reachable without a password"; FAIL=1; fi
done

if (( NODE2NODE )); then
  log "verifying node-to-node reachability (each node -> the other two, by LAN IP)"
  for n in "${NODES[@]}"; do
    for ip in "${NODE_IPS[@]}"; do
      [[ "$(node_ip "$n")" == "$ip" ]] && continue
      if ssh_out "$n" "ssh -o BatchMode=yes -o ConnectTimeout=8 '$NODE_USER@$ip' true"; then
        ok "  $n -> $ip"
      else
        err "  $n -> $ip FAILED"; FAIL=1
      fi
    done
  done
fi

(( FAIL == 0 )) || die "some links failed — check ~/.ssh/config and the key permissions"
ok "bootstrap complete — all scripts will now run non-interactively"
