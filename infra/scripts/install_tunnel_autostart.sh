#!/usr/bin/env bash
# =============================================================================
# install_tunnel_autostart.sh — installe / retire l'autostart du tunnel vLLM.
#
# Rend infra/systemd/iot-audit-tunnel.service actif pour VOTRE utilisateur, dans
# ~/.config/systemd/user/. Aucun droit root n'est demande et aucun fichier hors
# de ce repertoire n'est touche.
#
# POURQUOI UNE UNITE UTILISATEUR ET PAS UN SERVICE SYSTEME
#   Le tunnel est un transfert SSH fait avec les cles de l'utilisateur. Un
#   service systeme tournerait sous un autre compte, sans ces cles, et devrait
#   donc dupliquer une identite pour refaire ce que l'utilisateur fait deja.
#
# CE QUE L'INSTALLATION FAIT, DANS L'ORDRE
#   1. instancie le gabarit : @TUNNEL_VLLM@ recoit le chemin ABSOLU du script
#      tel qu'il a ete trouve a l'execution. L'unite du depot ne peut pas
#      contenir ce chemin sans supposer que le depot est a $HOME/iot-audit —
#      voir l'en-tete du .service. C'est le seul endroit qui connait a la fois
#      le depot et la machine ;
#   2. `systemd-analyze verify` sur l'unite instanciee : systemd signale
#      « Command ... is not executable » pour un chemin faux, et un chemin faux
#      est exactement le defaut que le gabarit existe pour eviter ;
#   3. ecrit l'unite dans $XDG_CONFIG_HOME/systemd/user/ (defaut ~/.config) ;
#   4. `systemctl --user daemon-reload` (sinon systemd ignore le fichier neuf) ;
#   5. `enable --now` : demarrage immediat ET redemarrage a chaque session ;
#   6. verifie que le tunnel REPOND (HTTP), pas seulement que le processus vit ;
#   7. signale `loginctl enable-linger` si le « linger » est desactive — sans
#      lui, systemd arrete l'unite des que votre derniere session se ferme, ce
#      qui est precisement le cas ou l'on veut le tunnel debout (nuit, CI).
#
# Usage:
#   infra/scripts/install_tunnel_autostart.sh [install|uninstall|status]
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../config/cluster.env
source "$HERE/../config/cluster.env"
# shellcheck source=../lib/lib_cluster.sh
source "$HERE/../lib/lib_cluster.sh"

UNIT="iot-audit-tunnel.service"
UNIT_SRC="$HERE/../systemd/$UNIT"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_DST="$UNIT_DIR/$UNIT"
TUNNEL_VLLM="$HERE/tunnel_vllm.sh"
PLACEHOLDER="@TUNNEL_VLLM@"
# Global, et non `local` : le piège EXIT s'exécute après la sortie de la
# fonction, quand les variables locales n'existent plus. Un `trap` qui cite une
# locale non liée fait échouer le script sous `set -u` — mesuré : le ménage
# transformait une installation réussie en code de retour 1.
STAGE=""
trap 'rm -rf "$STAGE"' EXIT

ACTION="${1:-install}"

usage() { sed -n '2,32p' "$0"; }

# --- prerequis ---------------------------------------------------------------
# Les trois echecs rencontres en pratique, chacun avec son message plutot qu'une
# erreur de shell obscure.
require_systemd() {
  command -v systemctl >/dev/null 2>&1 \
    || die "systemctl est absent : cette machine n'a pas systemd, l'autostart n'est pas installable ici."
  [[ -f "$UNIT_SRC" ]] \
    || die "unite introuvable : $UNIT_SRC (le depot est-il complet ?)"
  # `systemctl --user` a besoin du bus de session. Sans session ouverte (ssh
  # sans linger, cron, conteneur), il echoue en « Failed to connect to bus ».
  systemctl --user show-environment >/dev/null 2>&1 \
    || die "pas de bus 'systemd --user' joignable : ouvrez une session utilisateur (ou activez le linger) et relancez."
}

# Instantie le gabarit dans un fichier temporaire et le VERIFIE avant de
# l'installer. Deux gardes, deux defauts distincts :
#   * le gabarit doit contenir le marqueur (sinon le depot a change de forme) ;
#   * l'unite obtenue doit passer `systemd-analyze verify` (chemin inexistant,
#     directive mal ecrite). Installer une unite cassee puis decouvrir l'erreur
#     au reboot, c'est le probleme que ce script existe pour resoudre.
#
# Le fichier a verifier doit porter le NOM de l'unite : mesure du 2026-10-06,
# `systemd-analyze verify /tmp/tmp.XyZ` echoue en « Failed to prepare filename
# ...: Invalid argument » et `$?` vaut 0 — une verification qui ne verifie rien
# et ne le dit pas. On instancie donc dans un repertoire temporaire, sous le nom
# exact de l'unite.
render_unit() {  # -> ecrit le fichier instancie sur stdout
  grep -q "$PLACEHOLDER" "$UNIT_SRC" \
    || die "$UNIT_SRC ne contient pas $PLACEHOLDER : le gabarit a change, le script doit suivre."
  sed "s|$PLACEHOLDER|$TUNNEL_VLLM|g" "$UNIT_SRC"
}

verify_unit() {  # $1 = fichier instancie
  command -v systemd-analyze >/dev/null 2>&1 || return 0
  local report
  if ! report="$(systemd-analyze verify "$1" 2>&1)"; then
    printf '%s\n' "$report" >&2
    die "l'unite instanciee ne passe pas 'systemd-analyze verify' (voir ci-dessus)."
  fi
  [[ -x "$TUNNEL_VLLM" ]] \
    || die "$TUNNEL_VLLM n'est pas executable : l'unite demarrerait puis echouerait en boucle."
}

ping_tunnel() {
  # systemd dit si le PROCESSUS tourne ; ceci dit si le tunnel REPOND.
  # Un tunnel a demi ouvert garde un listener : la difference est mesuree
  # (voir l'en-tete de infra/scripts/tunnel_vllm.sh).
  printf '\n'
  log "verification reelle du tunnel (requete HTTP, pas un simple listener) :"
  "$HERE/tunnel_vllm.sh" status || warn "le tunnel ne repond pas encore — voir les journaux ci-dessus"
}

linger_state() {  # -> "yes" | "no" | "unknown"
  command -v loginctl >/dev/null 2>&1 || { printf 'unknown'; return 0; }
  local out
  out="$(loginctl show-user "$USER" -p Linger 2>/dev/null || true)"
  case "$out" in
    *Linger=yes) printf 'yes' ;;
    *Linger=no)  printf 'no'  ;;
    *)           printf 'unknown' ;;
  esac
}

# --- actions -----------------------------------------------------------------
do_install() {
  require_systemd
  mkdir -p "$UNIT_DIR"
  local rendered
  STAGE="$(mktemp -d)"
  rendered="$STAGE/$UNIT"
  render_unit > "$rendered"
  verify_unit "$rendered"
  install -m 0644 "$rendered" "$UNIT_DST"
  ok "unite installée : $UNIT_DST"
  printf '      ExecStart : %s start --foreground\n' "$TUNNEL_VLLM"

  systemctl --user daemon-reload
  systemctl --user enable --now "$UNIT"

  log "etat de l'unite :"
  systemctl --user status "$UNIT" --no-pager || true

  case "$(linger_state)" in
    no|unknown)
      warn "linger desactive : l'unite sera arretee a la fermeture de votre derniere session."
      printf '      pour la garder debout sans session ouverte :\n'
      printf '        loginctl enable-linger %s\n' "$USER"
      ;;
    yes)
      ok "linger actif : l'unite survit a la fermeture de votre session"
      ;;
  esac

  ping_tunnel
}

do_uninstall() {
  require_systemd
  # `disable --now` d'abord : retirer le fichier d'une unite active laisserait
  # un ssh forwarder orphelin, exactement l'etat dont ce depot a deja souffert.
  systemctl --user disable --now "$UNIT" 2>/dev/null || true
  rm -f "$UNIT_DST"
  systemctl --user daemon-reload
  ok "unite retiree : $UNIT_DST"
  log "l'autostart est desactive ; le tunnel lui-meme est arrete."
  printf "      pour l'arreter a la main une derniere fois : %s stop\n" "$HERE/tunnel_vllm.sh"
}

do_status() {
  require_systemd
  log "etat de l'unite :"
  systemctl --user status "$UNIT" --no-pager || true
  log "fichier installe : $UNIT_DST"
  if [[ -f "$UNIT_DST" ]]; then
    ok "present"
  else
    warn "absent — l'autostart n'est pas installe"
  fi
  ping_tunnel
}

case "$ACTION" in
  install)   do_install ;;
  uninstall) do_uninstall ;;
  status)    do_status ;;
  -h|--help) usage; exit 0 ;;
  *)         die "argument inconnu : $ACTION  (voir --help)" ;;
esac
