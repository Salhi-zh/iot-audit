#!/usr/bin/env bash
# =============================================================================
# cluster_status.sh — live snapshot of the whole cluster.
#
# For every node: SSH reachability, hostname/uptime, GPU load + free VRAM,
# state of the CONFIGURED ports (QWEN_PORT/LLAMA_PORT, 8000/8001 by default) with
# PID, running vLLM / llama-server processes, model presence, free disk space,
# and the BOOT SUPERVISOR state (2026-09-28: whether vllm-autostart.sh is
# installed, disabled by its marker, or missing).
#
# The autostart line is checked here because its failure mode is SILENT: the
# crontab entry is a single line in one user's crontab, so anything that rewrites
# that crontab removes the boot start and nothing says so until a node comes back
# up empty. Combined with the port state below, this is also where a FAILED boot
# shows up: "port free + autostart installed" is the signature of a boot that
# tried and did not make it, while "port free + no autostart" is a node that will
# stay down after any reboot.
#
# SSH reachability is the real connectivity test here: the nodes sit on a
# private LAN and are not directly pingable from a workstation behind the
# gateway. ICMP is attempted only when the host is directly routable.
#
# Usage:  ./cluster_status.sh [--watch] [--interval 5]
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"

WATCH=0; INTERVAL=5
while (( $# )); do
  case "$1" in
    --watch)    WATCH=1 ;;
    --interval) INTERVAL="${2:?}"; shift ;;
    -h|--help)  sed -n '2,14p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

port_state() {  # <node> <port> -> PID(s) listening, or "-"
  # 2026-09-28 : renvoyait "PORT:PID" alors que l'etiquette l'imprimait deja en
  # dur, ce qui donnait "8000[8000:21573]" en direct et un port FAUX des que
  # QWEN_PORT etait surcharge. Le port vit maintenant UNE seule fois, dans
  # l'etiquette, et vient de la config.
  local node="$1" port="$2" pid
  if port_in_use "$node" "$port"; then
    pid="$(port_pid "$node" "$port" | tr '\n' ',' | sed 's/,$//')"
    printf '%s' "${pid:-?}"
  else
    printf '%s' '-'
  fi
}

status_one() {  # <node>  -> prints an aligned block
  local n="$1" ip; ip="$(node_ip "$n")"

  if ! node_up "$n"; then
    printf '%s\n' "${C_RED}● $n  ($ip) UNREACHABLE${C_RST}"
    return
  fi

  local host up gpu dq dl procs disk model_q model_l pinged auto
  host="$(ssh_out "$n" 'hostname -s' || true)"
  # Un seul aller-retour : la ligne cron marquee est-elle la ? le marqueur --disable ?
  # le script ? (`crontab -l`echoue quand l'utilisateur n'a aucun crontab : d'ou
  # le `2>/dev/null` et le `|| true`, sinon set -e ferait tomber le rapport.)
  auto="$(ssh_out "$n" 'printf "cron=%s script=%s marker=%s" \
      "$(crontab -l 2>/dev/null | grep -cF iot-audit:vllm-autostart || true)" \
      "$([ -f "$HOME/vllm-autostart.sh" ] && echo yes || echo no)" \
      "$([ -e "$HOME/.no-vllm-autostart" ] && echo yes || echo no)"' || true)"
  up="$(ssh_out "$n" "uptime -p 2>/dev/null || uptime" || true)"
  gpu="$(ssh_out "$n" "nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader 2>/dev/null | head -n1" || true)"
  dq="$(port_state "$n" "$QWEN_PORT" || true)"
  dl="$(port_state "$n" "$LLAMA_PORT" || true)"
  # `grep -v pgrep` : la commande est envoyee via `bash -c`, dont la ligne de
  # commande CONTIENT le motif -- sans ce filtre, pgrep se liste lui-meme et
  # chaque noeud affichait un faux processus (2026-09-28).
  procs="$(ssh_out "$n" "pgrep -af 'vllm serve|llama-server' 2>/dev/null | grep -v 'pgrep -af' | sed 's/^/      /'" || true)"
  disk="$(disk_free_gb "$n" || true)"
  model_q="$(path_exists "$n" "$QWEN_MODEL_DIR" || true)"
  model_l="$(path_exists "$n" "$LLAMA_DIR" || true)"

  # ICMP only useful if the host is directly routable (LAN); never fatal.
  if ping -c1 -W1 "$ip" >/dev/null 2>&1; then pinged="ping ok"; else pinged="ping n/a"; fi

  printf '%s\n' "${C_GRN}● $n${C_RST}  ($ip, $pinged)"
  printf '    host     : %s   up: %s\n' "${host:-?}" "${up:-?}"
  printf '    gpu      : %s\n' "${gpu:-nvidia-smi unavailable}"
  printf '    ports    : %s[%s]  %s[%s]\n' "$QWEN_PORT" "$dq" "$LLAMA_PORT" "$dl"
  printf '    models   : qwen=%s  llama-gguf=%s\n' "${model_q:-no}" "${model_l:-no}"
  printf '    disk free: %s GB\n' "${disk:-?}"
  # --- etat du demarrage automatique, et ce qu'il implique --------------
  local acron ascript amarker
  acron="$(printf '%s' "$auto" | sed -n 's/.*cron=\([0-9]*\).*/\1/p')"
  ascript="$(printf '%s' "$auto" | sed -n 's/.*script=\([a-z]*\).*/\1/p')"
  amarker="$(printf '%s' "$auto" | sed -n 's/.*marker=\([a-z]*\).*/\1/p')"
  if [[ "${acron:-0}" -gt 0 ]]; then
    if [[ "$amarker" == yes ]]; then
      printf '    autostart: %s (desactive par marqueur : un reboot ne demarrerait rien)\n' "$C_YEL installed, disabled$C_RST"
    else
      printf '    autostart: %s (%s ligne(s) cron, script present)\n' "${C_GRN}installed${C_RST}" "$acron"
    fi
  else
    printf '    autostart: %s\n' "${C_YEL}ABSENT${C_RST} (aucune ligne cron : un reboot laisserait ce noeud sans service)"
  fi
  # Le port Qwen est libre : c'est soit un arret volontaire, soit un boot qui a echoue.
  # La difference, c'est justement la ligne ci-dessus -- on la nomme plutot que de la
  # laisser deviner.
  if [[ "$dq" == '-' ]]; then
    if [[ "${acron:-0}" -gt 0 && "$amarker" != yes ]]; then
      printf '    %s\n' "${C_RED}!! $QWEN_PORT libre alors que le demarrage automatique est installe -- boot en echec, ou arret volontaire${C_RST}"
    else
      printf '    %s\n' "${C_YEL}!! $QWEN_PORT libre et aucun demarrage automatique -- ce noeud ne reviendra pas seul${C_RST}"
    fi
  fi
  if [[ -n "$procs" ]]; then printf '    procs    :\n%s\n' "$procs"; else printf '    procs    : none\n'; fi
}

render() {
  echo "================ zabeth cluster status — $(date '+%Y-%m-%d %H:%M:%S') ================"
  local tmp n
  tmp="$(mktemp -d)"
  for n in "${NODES[@]}"; do ( status_one "$n" >"$tmp/$n" ) & done
  wait
  for n in "${NODES[@]}"; do cat "$tmp/$n"; echo; done
  rm -rf "$tmp"
}

if (( WATCH )); then
  while :; do clear; render; sleep "$INTERVAL"; done
else
  render
fi
