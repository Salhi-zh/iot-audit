#!/bin/bash
# =============================================================================
#  node_nvidia_persistence.sh -- aligner la PERSISTANCE GPU sur les trois noeuds
# =============================================================================
#  ETAT MESURE (2026-09-29)
#  ------------------------
#      zabeth21 : persistence=Enabled   nvpd present   /etc/init.d/nvidia-persistenced present
#      zabeth22 : persistence=Disabled  nvpd ABSENT    init script ABSENT
#      zabeth23 : persistence=Disabled  nvpd present   init script ABSENT
#
#  Le paquet est le MEME partout (nvidia-persistenced 615.71.09-2, depot
#  developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64). C'est donc
#  une divergence d'INSTALLATION, pas de version : le script init que le paquet
#  livre n'est present que sur zabeth21. Les octets sont vendores dans le depot
#  (infra/assets/nvidia-persistenced.init.d, sha256 f8f4f988...) et non retapes.
#
#  CE QUE FAIT CE SCRIPT
#  ---------------------
#  1. cree le compte systeme `nvpd` s'il manque (zabeth22), sans collision d'id ;
#  2. installe le script init du paquet s'il manque ;
#  3. l'active (update-rc.d) et le demarre ;
#  4. pose `nvidia-smi -pm 1` (ceinture et bretelles : le demon le refait au boot).
#
#  CE QU'IL NE TOUCHE PAS : aucun fichier d'identite d'utilisateur, aucun fichier
#  PAM/nsswitch, aucun compte existant. `nvpd` est un NOUVEAU compte systeme a
#  nologin ; il n'existe dans l'annuaire pour personne et ne peut masquer rien.
#
#  RETOUR ARRIERE
#      sudo bash node_nvidia_persistence.sh remove
#  (le compte nvpd est laisse en place : le retirer n'apporte rien et un uid
#   systeme recycle est plus risque qu'un compte nologin inutilise.)
#
#  usage (SUR UN NOEUD) : sudo bash node_nvidia_persistence.sh install|remove|status
# =============================================================================
set -uo pipefail

INITS="${INITS:-/etc/init.d/nvidia-persistenced}"
if [ -z "${SRC:-}" ]; then
  for s in "/tmp/nvidia-persistenced.init.d" \
           "$(dirname "$0")/../assets/nvidia-persistenced.init.d" \
           "$HOME/infra/assets/nvidia-persistenced.init.d"; do
    [ -f "$s" ] && { SRC="$s"; break; }
  done
fi
SRC="${SRC:-/tmp/nvidia-persistenced.init.d}"     # copie vendoree, deployee a cote
NVPD_BIN="${NVPD_BIN:-/usr/bin/nvidia-persistenced}"
UPDATE_RC_D="${UPDATE_RC_D:-/usr/sbin/update-rc.d}"
EXPECT_SHA="${EXPECT_SHA:-f8f4f9888779afc5a6af77b117a5c774234cc12cc15ab025ed2c30e560e60200}"

die() { printf '%s\n' "$*" >&2; exit 1; }
require_root() { [ "$(id -u)" -eq 0 ] || die "a lancer en root (sudo)"; }

# Sous Devuan il n'y a pas de systemd : on ne cherche PAS d'unite systemd, on
# regarde le processus. `pgrep -x nvidia-persistenced` echoue a tort (le nom est
# tronque a 15 caracteres dans /proc/comm) -- piege deja rencontre : on lit la
# ligne de commande complete.
running() { ps -eo args | grep -q '[n]vidia-persistenced'; }
persistence() { nvidia-smi --query-gpu=persistence_mode --format=csv,noheader 2>/dev/null | head -1; }

cmd_install() {
  require_root
  [ -x "$NVPD_BIN" ] || die "introuvable : $NVPD_BIN"
  [ -f "$SRC" ]      || die "introuvable : $SRC (deployer la copie vendoree)"

  # 1. compte systeme
  if getent passwd nvpd >/dev/null 2>&1; then
    printf 'compte nvpd : deja present (%s)\n' "$(getent passwd nvpd | cut -d: -f3-4)"
  else
    groupadd -r nvpd 2>/dev/null || true
    useradd -r -M -g nvpd -d /var/run/nvpd -s /usr/sbin/nologin \
            -c 'NVIDIA Persistence Daemon' nvpd \
      || die "echec de creation du compte nvpd"
    printf 'compte nvpd : cree (%s)\n' "$(getent passwd nvpd | cut -d: -f3-4)"
  fi

  # 2. script init (octets verifies avant installation : on installe ce qu'on a
  #    verifie, pas ce qu'on espere)
  local sha; sha="$(sha256sum "$SRC" | awk '{print $1}')"
  if [ "$sha" != "$EXPECT_SHA" ]; then
    die "sha256 inattendu pour $SRC : $sha (attendu $EXPECT_SHA)"
  fi
  install -m 755 -o root -g root "$SRC" "$INITS"
  printf 'script init : installe (%s)\n' "$INITS"

  # 3. activation + demarrage
  if [ -x "$UPDATE_RC_D" ]; then
    "$UPDATE_RC_D" nvidia-persistenced defaults >/dev/null 2>&1 || true
    printf 'liens rc   : %s\n' "$(ls /etc/rc2.d/*persistenced 2>/dev/null | tr '\n' ' ')"
  fi
  if running; then printf 'demon      : deja en cours\n'; else "$INITS" start >/dev/null 2>&1 || true; fi
  sleep 2

  # 4. persistance
  nvidia-smi -pm 1 >/dev/null 2>&1 || true

  printf 'demon      : %s\n' "$(running && echo 'en cours' || echo 'ABSENT')"
  printf 'persistance: %s\n' "$(persistence)"
}

cmd_remove() {
  require_root
  [ -x "$INITS" ] && "$INITS" stop >/dev/null 2>&1 || true
  if [ -x "$UPDATE_RC_D" ]; then "$UPDATE_RC_D" -f nvidia-persistenced remove >/dev/null 2>&1 || true; fi
  rm -f "$INITS"
  printf 'script init retire, demon arrete. Compte nvpd laisse en place (nologin).\n'
  printf 'persistance: %s (peut rester Enabled jusqu au prochain rechargement du pilote)\n' "$(persistence)"
}

cmd_status() {
  printf '==== persistance GPU -- %s ====\n' "$(hostname -s)"
  printf 'paquet     : %s\n' "$(dpkg -l nvidia-persistenced 2>/dev/null | awk '/^ii/{print $2, $3}')"
  printf 'compte nvpd: %s\n' "$(getent passwd nvpd | cut -d: -f1,3,4 || echo ABSENT)"
  printf 'script init: %s\n' "$([ -x "$INITS" ] && echo "$INITS" || echo ABSENT)"
  printf 'liens rc   : %s\n' "$(ls /etc/rc2.d/*persistenced 2>/dev/null | tr '\n' ' ' || echo '(aucun)')"
  printf 'demon      : %s\n' "$(running && echo 'en cours' || echo 'ABSENT')"
  printf 'persistance: %s\n' "$(persistence)"
  printf 'fichier du paquet manquant ? dpkg -V :\n'
  dpkg -V nvidia-persistenced 2>/dev/null | sed 's/^/  /' || true
}

case "${1:-status}" in
  install) cmd_install ;;
  remove)  cmd_remove ;;
  status)  cmd_status ;;
  *) die "usage: $0 install|remove|status" ;;
esac
