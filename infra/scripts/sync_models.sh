#!/usr/bin/env bash
# =============================================================================
# sync_models.sh — replicate the three artifacts across the zabeth cluster.
#
#   Qwen2.5-VL-7B-Instruct-GPTQ-Int4    zabeth23 -> zabeth21, zabeth22
#   llama-3.2-vision-gguf/             zabeth22 -> zabeth21, zabeth23
#   llama.cpp/build/bin/ (llama-server) zabeth22 -> zabeth21, zabeth23
#
# Idempotent: a destination whose byte size AND file count already match the
# source is skipped. Transfers go node->node directly when the two nodes can
# reach each other over SSH; otherwise they are streamed through this
# orchestrator (no local disk usage).
#
# Usage:  ./sync_models.sh [--force] [--dry-run] [--artifact qwen|llama|llama-bin]
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"

FORCE=0
DRY=0
ONLY=""

while (( $# )); do
  case "$1" in
    --force)    FORCE=1 ;;
    --dry-run)  DRY=1 ;;
    --artifact) ONLY="${2:?missing value}"; shift ;;
    -h|--help)  sed -n '2,13p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

# Rows: "label|source node|source path|dest path"
ARTIFACTS=(
  "qwen|$QWEN_SOURCE_NODE|$QWEN_MODEL_DIR|$QWEN_MODEL_DIR"
  "llama|$LLAMA_SOURCE_NODE|$LLAMA_DIR|$LLAMA_DIR"
  "llama-bin|$LLAMA_SOURCE_NODE|$LLAMA_BIN_DIR|$LLAMA_BIN_DIR"
)

# --- one transfer ------------------------------------------------------------
# Direct rsync runs ON the source node (rsync needs one endpoint to be local),
# pushing to the destination's LAN IP. Falls back to a streaming tar relay.
sync_dir() {  # <src_node> <src_path> <dst_node> <dst_path> -> 0 on success
  local src="$1" spath="$2" dst="$3" dpath="$4" ip
  ip="$(node_ip "$dst")"

  if ! ssh_out "$dst" "mkdir -p '$dpath'"; then
    err "  cannot create $dpath on $dst"; return 1
  fi

  local rsync_opts="-a --info=progress2 --partial"
  (( DRY )) && rsync_opts="$rsync_opts --dry-run"

  # Path 1 — direct node -> node (fast: stays on the LAN).
  if ssh_out "$src" "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 '$NODE_USER@$ip' true"; then
    log "  $src -> $dst : direct rsync (LAN)"
    # shellcheck disable=SC2029
    if ssh_run "$src" "rsync $rsync_opts -e 'ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new' '$spath/' '$NODE_USER@$ip:$dpath/'"; then
      return 0
    else
      return 1
    fi
  fi

  # Path 2 — relay through this orchestrator, streaming tar (no local disk use).
  warn "  $src cannot reach $dst directly — relaying through this host"
  if (( DRY )); then log "  (dry-run) tar stream $src:$spath -> $dst:$dpath"; return 0; fi
  if ssh_run "$src" "tar -C '$spath' -cf - ." | ssh_run "$dst" "tar -C '$dpath' -xf -"; then
    return 0
  else
    return 1
  fi
}

# --- verification ------------------------------------------------------------
verify_dir() {  # <src_node> <src_path> <dst_node> <dst_path> -> "OK <bytes> <files>" | "MISMATCH ..."
  local src="$1" spath="$2" dst="$3" dpath="$4" sb sf db df
  sb="$(path_size_bytes "$src" "$spath" || true)"; sf="$(count_files "$src" "$spath" || true)"
  db="$(path_size_bytes "$dst" "$dpath" || true)"; df="$(count_files "$dst" "$dpath" || true)"
  if [[ -n "$db" && -n "$sb" && "$sb" == "$db" && "$sf" == "$df" ]]; then
    printf 'OK %s %s' "$sb" "$sf"
  else
    printf 'MISMATCH src=%s/%s dst=%s/%s' "$sb" "$sf" "$db" "$df"
  fi
}

# --- cluster-wide probe ------------------------------------------------------
probe_cluster() {
  log "Probing current state of the cluster"
  printf '%-10s %-10s %-9s %-13s %s\n' ARTIFACT NODE PRESENT SIZE FILES
  printf '%-10s %-10s %-9s %-13s %s\n' -------- ---- ------- ---- -----
  local row label src spath dpath node present size files
  for row in "${ARTIFACTS[@]}"; do
    IFS='|' read -r label src spath dpath <<<"$row"
    [[ -n "$ONLY" && "$label" != "$ONLY" ]] && continue
    for node in "${NODES[@]}"; do
      present="no"; size="-"; files="-"
      if [[ "$(path_exists "$node" "$spath")" == "yes" ]]; then
        present="yes"
        size="$(path_size_bytes "$node" "$spath" || true)"
        files="$(count_files "$node" "$spath" || true)"
      fi
      printf '%-10s %-10s %-9s %-13s %s\n' "$label" "$node" "$present" "$size" "$files"
    done
  done
  echo
}

# --- main --------------------------------------------------------------------
probe_cluster

SUMMARY=()
FAILED=0
SYNCED=0
SKIPPED=0
row=""; label=""; src=""; spath=""; dpath=""

for row in "${ARTIFACTS[@]}"; do
  IFS='|' read -r label src spath dpath <<<"$row"
  [[ -n "$ONLY" && "$label" != "$ONLY" ]] && continue

  if [[ "$(path_exists "$src" "$spath")" != "yes" ]]; then
    err "$label: source $src:$spath does not exist — cannot sync"
    SUMMARY+=("$label|$src|SOURCE MISSING||")
    FAILED=1
    continue
  fi

  log "$label  (source $src, $(path_size_bytes "$src" "$spath" || echo '?') bytes)"

  for dst in "${NODES[@]}"; do
    [[ "$dst" == "$src" ]] && continue

    if ! node_up "$dst"; then
      err "  $dst unreachable — skipped"; FAILED=1
      SUMMARY+=("$label|$dst|UNREACHABLE||"); continue
    fi

    # Skip when already identical (unless --force).
    if (( ! FORCE )); then
      v="$(verify_dir "$src" "$spath" "$dst" "$dpath")"
      if [[ "$v" == OK* ]]; then
        read -r _ b f <<<"$v"
        ok "  $dst already complete ($b bytes, $f files) — skip"
        SUMMARY+=("$label|$dst|SKIP (identical)|$b|$f")
        SKIPPED=$((SKIPPED + 1)); continue
      fi
    fi

    # Disk space guard.
    freeg="$(disk_free_gb "$dst" || true)"
    if [[ -n "$freeg" ]] && (( freeg < MIN_FREE_DISK_GB )); then
      err "  $dst only ${freeg}GB free (< ${MIN_FREE_DISK_GB}GB) — skipped"; FAILED=1
      SUMMARY+=("$label|$dst|NO DISK (${freeg}GB)||"); continue
    fi

    log "  syncing -> $dst"
    if sync_dir "$src" "$spath" "$dst" "$dpath"; then
      v="$(verify_dir "$src" "$spath" "$dst" "$dpath")"
      if [[ "$v" == OK* ]]; then
        read -r _ b f <<<"$v"
        ok "  $dst verified ($b bytes, $f files)"
        SUMMARY+=("$label|$dst|OK|$b|$f"); SYNCED=$((SYNCED + 1))
      else
        err "  $dst integrity check failed: $v"; FAILED=1
        SUMMARY+=("$label|$dst|INTEGRITY ERROR|$v|")
      fi
    else
      err "  $dst transfer failed"; FAILED=1
      SUMMARY+=("$label|$dst|TRANSFER FAILED||")
    fi
  done
done

# --- llama-server must be executable on every node ---------------------------
if [[ -z "$ONLY" || "$ONLY" == "llama-bin" ]]; then
  for node in "${NODES[@]}"; do
    if node_up "$node"; then
      if ssh_out "$node" "test -x '$LLAMA_SERVER_BIN'"; then
        ok "llama-server executable present on $node"
      else
        warn "llama-server NOT executable on $node ($LLAMA_SERVER_BIN)"
      fi
    fi
  done
fi

# --- summary -----------------------------------------------------------------
echo
echo "=========================== SYNC SUMMARY ==========================="
printf '%-10s %-10s %-18s %-13s %s\n' MODEL NODE STATUS BYTES FILES
printf '%-10s %-10s %-18s %-13s %s\n' ----- ---- ------ ----- -----
for r in "${SUMMARY[@]}"; do
  IFS='|' read -r l n s b f <<<"$r"
  printf '%-10s %-10s %-18s %-13s %s\n' "$l" "$n" "$s" "${b:--}" "${f:--}"
done
echo "===================================================================="
echo "synced=$SYNCED  skipped=$SKIPPED  failed=$FAILED"

(( FAILED == 0 )) || exit 1
