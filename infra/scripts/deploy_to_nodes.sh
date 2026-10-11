#!/usr/bin/env bash
# =============================================================================
# deploy_to_nodes.sh — copy repo files to the nodes, safely.
#
# WHY THIS EXISTS (2026-09-28, ninth pass — learned the expensive way)
# -------------------------------------------------------------------
# Deploying by hand cost us the v4 bytes of `gpu-bench-node.sh`. Two deploy runs
# the same hour used the same backup stamp (`T1747`), so the second one's
# `cp -p` wrote over the backup that held v4. It was never preserved in the repo
# and a size-and-hash sweep of the nodes found nothing: b9952681... (20 738 B) is
# gone, and the rule "superseded instrument bytes are preserved" is broken for it.
# Prose alone had already failed once before (see `_backup_naming_incident` in
# evidence/2026-09-28/instrument-v4-and-config/instrument-repin-v4.json).
#
# So the rules are mechanical here instead:
#
#   1. STAGE EVERYWHERE, VERIFY EVERYWHERE, THEN SWAP.  Nothing is replaced
#      until every node has an identical staged copy. A half-done deploy is the
#      state you least want and have least means to reason about.
#   2. A BACKUP NAME IS NEVER REUSED.  The stamp has second resolution, and if a
#      name is somehow taken the next free suffix is used — an existing backup is
#      compared by content and left alone. Overwriting is impossible by design.
#   3. THE BYTES ARE VERIFIED BEFORE THE SWAP AND AFTER IT.  A `cp` that quietly
#      wrote an empty file (the `ssh -n` trap: `-n` redirects stdin from
#      /dev/null, so `ssh -n host "cat > f" < f` writes 0 bytes) hashes to
#      e3b0c442... and is refused here.
#   4. `--preserve DIR` copies the bytes being replaced into DIR before the swap,
#      named by their own hash — so the pass's evidence folder gets them without
#      anyone having to remember.
#
# usage:
#   ./deploy_to_nodes.sh [--dry-run] [--preserve DIR] [--stamp TS] \
#       <repo_path>:<node_relative_dest> [...]
#
#   ./deploy_to_nodes.sh infra/scripts/node_gpu_bench.sh:gpu-bench-node.sh
#   ./deploy_to_nodes.sh --preserve /tmp/superseded \
#       infra/scripts/node_vllm_service.sh:vllm-service.sh \
#       infra/config/cluster.env:infra/config/cluster.env
#
# The destination is relative to the node user's $HOME. Node list comes from
# cluster.env (NODES); SSH from lib_cluster.sh, so this follows whatever the
# cluster scripts follow.
#
# NOTE (host quirk, costs an hour if forgotten): `ssh` reads `~/.ssh/config` —
# where the identity file and the ProxyJump to the bastion live — from the
# account's passwd home, NOT from an exported $HOME. If HOME is overridden (a
# sandbox), run this with `HOME=/home/<account> ./deploy_to_nodes.sh ...` or every
# ssh here fails with "Permission denied" and reads like a broken key.
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"

DRY=0
PRESERVE=""
STAMP="$(date +%Y%m%dT%H%M%S)"
MAPPINGS=()

while (( $# )); do
  case "$1" in
    --dry-run)  DRY=1 ;;
    --preserve) PRESERVE="${2:?--preserve needs a directory}"; shift ;;
    --stamp)    STAMP="${2:?--stamp needs a value}"; shift ;;
    -h|--help)  sed -n '2,42p' "$0"; exit 0 ;;
    -*)         die "unknown argument: $1" ;;
    *)          MAPPINGS+=("$1") ;;
  esac
  shift
done

(( ${#MAPPINGS[@]} )) || die "nothing to deploy — pass <repo_path>:<node_dest>"
(( ${#NODES[@]} ))    || die "NODES is empty in cluster.env"
[ -n "$STAMP" ] || die "empty stamp"

sha() { sha256sum "$1" | cut -d' ' -f1; }

# --- local preflight: refuse to ship something that cannot even be parsed ----
declare -a SRC DEST
for m in "${MAPPINGS[@]}"; do
  src="${m%%:*}"; dst="${m#*:}"
  [[ "$m" == *:* ]] || die "mapping needs a colon: $m"
  [[ -f "$src" ]]   || die "not a file: $src"
  [[ -s "$src" ]]   || die "refusing to deploy an EMPTY file: $src"
  case "$src" in
    *.sh) bash -n "$src" || die "bash -n failed: $src" ;;
  esac
  SRC+=("$src"); DEST+=("$dst")
done
echo "stamp ${STAMP} — ${#SRC[@]} file(s) × ${#NODES[@]} node(s)"

# --- phase 1: stage on every node, verify every staged copy ------------------
STAGED=()
for n in "${NODES[@]}"; do
  node_up "$n" || die "node unreachable: $n"
  for i in "${!SRC[@]}"; do
    src="${SRC[$i]}"; dst="${DEST[$i]}"
    want="$(sha "$src")"
    if (( DRY )); then
      printf '  would stage %-9s %-28s %s\n' "$n" "$dst" "${want:0:16}"
      continue
    fi
    # stdin from the file: NEVER `ssh -n` here, that would write an empty file.
    ssh_run "$n" "mkdir -p \"\$(dirname \"\$HOME/$dst\")\" && cat > \"\$HOME/$dst.new-$STAMP\"" < "$src"
    got="$(ssh_out "$n" "sha256sum \"\$HOME/$dst.new-$STAMP\" | cut -d' ' -f1" || true)"
    got="${got%% *}"
    [ "$got" = "$want" ] || die "staged bytes differ on $n for $dst (repo ${want:0:16}, node ${got:0:16})"
    STAGED+=("$n:$dst")
    printf '  staged %-9s %-28s %s\n' "$n" "$dst" "${want:0:16}"
  done
done
if (( DRY )); then
  echo "dry-run: nothing staged, nothing swapped"
  exit 0
fi

# --- phase 2: preserve, back up, swap ---------------------------------------
# backup_name <node> <dst> — the first FREE name, or "" when the file is absent.
# An existing backup is never written to: same content -> reused as is, different
# content -> next suffix. This is the rule that v4's loss bought.
backup_name() {
  local n="$1" dst="$2" cand cur i
  ssh_out "$n" "test -e \"\$HOME/$dst\" && echo yes" | grep -q yes || { printf ''; return; }
  for i in "" -2 -3 -4 -5 -6 -7 -8 -9; do
    cand="$dst.bak-$STAMP$i"
    if ! ssh_out "$n" "test -e \"\$HOME/$cand\" && echo yes" | grep -q yes; then
      printf '%s' "$cand"; return
    fi
    cur="$(ssh_out "$n" "sha256sum \"\$HOME/$cand\" | cut -d' ' -f1" || true)"
    if [ "$cur" = "$(ssh_out "$n" "sha256sum \"\$HOME/$dst\" | cut -d' ' -f1" || true)" ]; then
      printf '%s' "$cand"; return    # identical content: reuse, do not duplicate
    fi
  done
  die "no free backup name for $dst on $n ($STAMP)"
}

first=1
for i in "${!SRC[@]}"; do
  src="${SRC[$i]}"; dst="${DEST[$i]}"
  want="$(sha "$src")"
  for n in "${NODES[@]}"; do
    old="$(ssh_out "$n" "test -e \"\$HOME/$dst\" && sha256sum \"\$HOME/$dst\" | cut -d' ' -f1" || true)"
    if [ -n "$old" ] && [ -n "$PRESERVE" ] && (( first )); then
      mkdir -p "$PRESERVE"
      out="$PRESERVE/$(basename "$dst").${old:0:8}"
      if [ ! -f "$out" ]; then
        ssh_out "$n" "cat \"\$HOME/$dst\"" > "$out"
        echo "  preserved ${out} (from $n, ${old:0:16})"
      fi
    fi
    b="$(backup_name "$n" "$dst")"
    perm="$(stat -c '%a' "$src" 2>/dev/null || echo 755)"
    ssh_run "$n" "set -e
      [ -n '$b' ] && cp -p \"\$HOME/$dst\" \"\$HOME/$b\"
      mv \"\$HOME/$dst.new-$STAMP\" \"\$HOME/$dst\"
      chmod $perm \"\$HOME/$dst\"" >/dev/null
    now="$(ssh_out "$n" "sha256sum \"\$HOME/$dst\" | cut -d' ' -f1" || true)"
    now="${now%% *}"
    [ "$now" = "$want" ] || die "post-swap hash differs on $n for $dst (${now:0:16})"
    printf '  swapped %-9s %-28s %s   backup: %s\n' "$n" "$dst" "${now:0:16}" "${b:-aucune}"
  done
  first=0
done

# --- phase 3: nothing left staged -------------------------------------------
left="$(ssh_out "${NODES[0]}" "ls \"\$HOME\"/*.new-$STAMP 2>/dev/null | wc -l" || echo '?')"
echo "deployed ${#SRC[@]} file(s) to ${#NODES[@]} node(s); staged leftovers on ${NODES[0]}: ${left}"
