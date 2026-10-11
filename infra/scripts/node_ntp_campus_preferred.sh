#!/bin/bash
# =============================================================================
#  node_ntp_campus_preferred.sh -- preferer le serveur de temps du campus
# =============================================================================
#  ETAT MESURE (2026-09-29)
#  ------------------------
#  Le service de temps est ntpsec, lance avec `-c /etc/ntpsec/ntp.conf`. Le
#  fichier qui nomme le campus, /etc/ntp.conf (`server ntp.plil.info`), n'est PAS
#  lu par ntpsec : les trois noeuds interrogeaient donc les quatre
#  `pool N.debian.pool.ntp.org` -- c'etait le dernier appelant hors campus.
#
#  Le serveur du campus est `ntp.plil.info` -> 172.26.191.100 (resolution
#  verifiee sur les trois) et il NE REPOND PAS (sonde NTP mode 3, timeout).
#
#  CE QUE FAIT CE SCRIPT
#  ---------------------
#  Il ajoute le serveur du campus en tete de /etc/ntpsec/ntp.conf, marque
#  `prefer`, et GARDE le pool public : quand le campus repond, c'est lui qui fait
#  foi ; en attendant, l'horloge reste servie. Aucun test ne peut fermer ce point
#  tant que le serveur du campus est muet -- mais la configuration cesse d'etre
#  aveugle a sa source legitime.
#
#  L'adresse est ecrite en IP : `ntp.plil.info` demanderait une resolution DNS au
#  demarrage du demon. Meme logique que /etc/hosts pour l'annuaire ailleurs.
#
#  CE QU'IL NE TOUCHE PAS : aucun fichier d'identite, aucun PAM/nsswitch.
#
#  RETOUR ARRIERE
#      sudo bash node_ntp_campus_preferred.sh remove
#
#  usage (SUR UN NOEUD) : sudo bash node_ntp_campus_preferred.sh install|remove|status
# =============================================================================
set -uo pipefail

CONF="${CONF:-/etc/ntpsec/ntp.conf}"
INIT="${INIT:-/etc/init.d/ntpsec}"
CAMPUS_IP="${CAMPUS_IP:-172.26.191.100}"
CAMPUS_NAME="${CAMPUS_NAME:-ntp.plil.info}"
STAMP="iot-audit-20260929"
BAK="${CONF}.${STAMP}"

# Les deux lignes qui identifient notre ajout (pour install idempotent / remove).
MARK_BEGIN="# --- iot-audit : serveur de temps du campus (ajoute 2026-09-29) ---"
MARK_END="# --- fin iot-audit ---"

die() { printf '%s\n' "$*" >&2; exit 1; }
require_root() { [ "$(id -u)" -eq 0 ] || die "a lancer en root (sudo)"; }

cmd_install() {
  require_root
  [ -f "$CONF" ] || die "introuvable : $CONF"
  if grep -qF "$MARK_BEGIN" "$CONF"; then
    printf 'deja en place (marqueur present dans %s)\n' "$CONF"
  else
    [ -f "$BAK" ] || cp -a "$CONF" "$BAK"
    printf 'sauvegarde : %s\n' "$BAK"
    # Insertion AVANT le premier `pool ` : le campus est propose en premier, le
    # pool reste present et utilisable. Ecriture dans un fichier temporaire puis
    # remplacement -- jamais de configuration a moitie ecrite.
    local tmp; tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    awk -v b="$MARK_BEGIN" -v e="$MARK_END" -v ip="$CAMPUS_IP" -v nm="$CAMPUS_NAME" '
      !done && /^[[:space:]]*pool[[:space:]]/ {
        print b
        printf "server %s iburst prefer   # %s (campus)\n", ip, nm
        print e
        done = 1
      }
      { print }
      END { if (!done) { print b; printf "server %s iburst prefer   # %s (campus)\n", ip, nm; print e } }
    ' "$CONF" > "$tmp"
    cat "$tmp" > "$CONF"      # conserver inode/permissions du fichier d'origine
    rm -f "$tmp"
    printf 'ajoute : server %s iburst prefer  (%s)\n' "$CAMPUS_IP" "$CAMPUS_NAME"
  fi
  [ -x "$INIT" ] && "$INIT" restart >/dev/null 2>&1 || true
  sleep 2
  printf 'demon ntpsec : %s\n' "$(ps -eo args | grep -q '[n]tpd' && echo 'en cours' || echo ABSENT)"
}

cmd_remove() {
  require_root
  if [ -f "$BAK" ]; then
    cat "$BAK" > "$CONF"; printf 'restaure depuis %s\n' "$BAK"
  else
    printf 'aucune sauvegarde %s -- rien fait\n' "$BAK"; return 1
  fi
  [ -x "$INIT" ] && "$INIT" restart >/dev/null 2>&1 || true
  printf 'demon ntpsec : %s\n' "$(ps -eo args | grep -q '[n]tpd' && echo 'en cours' || echo ABSENT)"
}

cmd_status() {
  printf '==== temps (NTP) -- %s ====\n' "$(hostname -s)"
  printf 'demon      : %s\n' "$(ps -eo args | grep -q '[n]tpd' && echo 'en cours' || echo ABSENT)"
  printf 'config     : %s\n' "$CONF"
  grep -nE '^[[:space:]]*(server|pool)' "$CONF" | sed 's/^/  /'
  printf 'marqueur campus : %s\n' "$(grep -qF "$MARK_BEGIN" "$CONF" && echo present || echo absent)"
  printf 'sauvegarde : %s\n' "$([ -f "$BAK" ] && echo "$BAK" || echo '(aucune)')"
  printf 'pairs (ntpq -pn) :\n'
  ntpq -pn 2>/dev/null | sed 's/^/  /' || printf '  (ntpq indisponible)\n'
}

case "${1:-status}" in
  install) cmd_install ;;
  remove)  cmd_remove ;;
  status)  cmd_status ;;
  *) die "usage: $0 install|remove|status" ;;
esac
