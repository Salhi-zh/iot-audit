#!/bin/bash
# =============================================================================
#  node_boot_drop_privilege.sh -- demarrer le service vLLM au BOOT sans annuaire
# =============================================================================
#  POURQUOI CE FICHIER EXISTE (2026-09-29)
#  ---------------------------------------
#  Le compte du service est `msalhi` (uid 10131). Mesure : il n'est PAS local.
#      grep -c '^msalhi:' /etc/passwd   ->  0     (les trois noeuds)
#      nsswitch                          ->  passwd: files ldap
#  Il vient de l'annuaire du campus. Or la ligne de boot existante est un
#  `@reboot` dans le crontab DE L'UTILISATEUR : pour charger ce crontab, cron
#  doit resoudre le compte, et tout ce qui enumere les groupes traverse
#  nslcd -> LDAP. Quand l'annuaire est injoignable et le cache froid, le service
#  ne peut plus demarrer.
#
#  CE QUE CE SCRIPT FAIT
#  ---------------------
#  Il installe une tache de boot SYSTEME (proprietaire root) qui ne resout AUCUN
#  nom : `setpriv` recoit des identifiants NUMERIQUES (uid, gid et liste de
#  groupes explicite), puis lance le meme `vllm-autostart.sh --run`. Cron n'a donc
#  plus qu'a resoudre `root`, qui est dans /etc/passwd. Mesure sur zabeth22 :
#
#      setpriv --reuid=10131 --regid=2104 --groups=2104,2106 \
#        sh -c 'grep -E "^(Uid|Gid|Groups)" /proc/self/status'
#      Uid: 10131   Gid: 2104   Groups: 2104 2106     <- identique a `id`, zero NSS
#
#  CE QU'IL NE FAIT PAS -- C'EST LE POINT IMPORTANT
#  ------------------------------------------------
#  Il ne touche a AUCUN fichier d'identite : ni /etc/passwd, ni /etc/group, ni
#  /etc/shadow, ni /etc/pam.d, ni /etc/nsswitch.conf, ni le binding LDAP de
#  nslcd. C'est delibere. Avec `passwd: files ldap` et `group: files ldap`, une
#  entree locale pour `msalhi` -- et surtout pour ses groupes `se4is` (2104,
#  ~50 membres) ou `se5is` (2106) -- MASQUERAIT l'annuaire sur ce noeud : un
#  membre ajoute cote annuaire perdrait son acces, et les controles d'acces
#  bases sur le groupe changeraient pour tout le monde. Le remede serait pire
#  que le mal. Aucun compte d'aucun utilisateur ne peut donc changer de
#  comportement a cause de ce script.
#
#  IDEMPOTENT ET ADDITIF
#  ---------------------
#  La ligne `@reboot` de l'utilisateur est LAISSEE en place. `vllm-autostart.sh`
#  sort 0 sans rien faire si le service tourne deja ("service deja en cours"), et
#  `vllm-service.sh` refuse un port occupe : les deux taches ne peuvent pas
#  demarrer deux serveurs. Si ce fichier etait malforme, cron l'ignorerait et
#  l'ancienne ligne continuerait de fonctionner -- c'est le filet.
#
#  RETOUR ARRIERE
#  --------------
#      sudo bash node_boot_drop_privilege.sh remove
#  Une commande, un fichier.
#
#  usage (SUR UN NOEUD) :
#      sudo bash node_boot_drop_privilege.sh install|remove|status|verify
# =============================================================================
set -uo pipefail

# Identite du service. Numerique par construction : c'est tout l'objet du fichier.
SVC_UID="${SVC_UID:-10131}"        # msalhi
SVC_GID="${SVC_GID:-2104}"         # se4is
SVC_GROUPS="${SVC_GROUPS:-2104,2106}"   # se4is,se5is -- exactement ce que rend `id`
SVC_HOME="${SVC_HOME:-/home/msalhi}"
SVC_NAME="${SVC_NAME:-msalhi}"

CRONFILE="${CRONFILE:-/etc/cron.d/iot-audit-vllm-autostart}"
SETPRIV="${SETPRIV:-/usr/bin/setpriv}"
AUTOSTART="${AUTOSTART:-$SVC_HOME/vllm-autostart.sh}"
BOOTLOG="${BOOTLOG:-$SVC_HOME/logs/vllm-autostart.log}"

die() { printf '%s\n' "$*" >&2; exit 1; }

require_root() {
  [ "$(id -u)" -eq 0 ] || die "a lancer en root (sudo)"
}

# La commande EXACTE que cron executera. Une seule source de verite : install,
# status et verify la lisent tous les trois ici, donc ce qui est verifie est
# litteralement ce qui est installe.
#
# `cd $SVC_HOME &&` n'est pas cosmetique -- MESURE 2026-09-29, zabeth22 : cron
# lance une tache avec le cwd du compte proprietaire (/root ici), et `setpriv`
# change uid/gid mais PAS le cwd. Le service demarrait donc avec cwd=/root, et
# l'EngineCore de vLLM (multiprocessing spawn) mourait sur
# `os.chdir('/root')` -> PermissionError. On fixe le cwd ici ET dans le script
# lui-meme (defense en profondeur).
boot_command() {
  printf 'cd %s && %s --reuid=%s --regid=%s --groups=%s -- env HOME=%s /bin/bash %s --run >>%s 2>&1' \
    "$SVC_HOME" "$SETPRIV" "$SVC_UID" "$SVC_GID" "$SVC_GROUPS" "$SVC_HOME" "$AUTOSTART" "$BOOTLOG"
}

cmd_install() {
  require_root
  [ -x "$SETPRIV" ]  || die "introuvable ou non executable : $SETPRIV"
  [ -f "$AUTOSTART" ] || die "introuvable : $AUTOSTART"
  # Le fichier est ecrit atomiquement : jamais de /etc/cron.d a moitie lu par cron.
  local tmp; tmp="$(mktemp)"
  {
    printf '# iot-audit : demarrage du service vLLM au boot, identite NUMERIQUE.\n'
    printf '# Installe par node_boot_drop_privilege.sh le %s.\n' "$(date -Is)"
    printf '# Ne resout aucun nom d annuaire : root (local) puis setpriv numerique.\n'
    printf '# Retour arriere : supprimer ce fichier (ou: node_boot_drop_privilege.sh remove).\n'
    printf 'SHELL=/bin/sh\n'
    printf 'PATH=/usr/sbin:/usr/bin:/sbin:/bin\n'
    printf '@reboot root %s\n' "$(boot_command)"
  } > "$tmp"
  install -m 644 -o root -g root "$tmp" "$CRONFILE"
  rm -f "$tmp"
  printf 'installe : %s\n' "$CRONFILE"
  printf '  @reboot root %s\n' "$(boot_command)"
}

cmd_remove() {
  require_root
  if [ -e "$CRONFILE" ]; then rm -f "$CRONFILE"; printf 'retire : %s\n' "$CRONFILE"
  else printf 'rien a retirer (%s absent)\n' "$CRONFILE"; fi
  printf '  la ligne @reboot de l utilisateur, elle, n a jamais ete touchee.\n'
}

cmd_status() {
  printf '==== drop-privilege au boot -- %s ====\n' "$(hostname -s)"
  if [ -e "$CRONFILE" ]; then
    printf 'tache systeme : PRESENTE (%s)\n' "$CRONFILE"
    sed 's/^/  /' "$CRONFILE"
    printf '  permissions  : %s (cron exige root, non modifiable par tous)\n' \
      "$(stat -c '%U:%G %a' "$CRONFILE")"
  else
    printf 'tache systeme : ABSENTE -- le boot depend encore du crontab utilisateur\n'
  fi
  # Le crontab de l'utilisateur est lu DANS LE SPOOL, pas par `crontab -l` :
  # execute en root, `crontab -l` montre le crontab de root, pas celui du service
  # -- mesure faite le 2026-09-29, ou ce detail affichait « (aucune) » alors que la
  # ligne @reboot existait. Lire le spool est aussi exact et ne resout aucun nom.
  local spool="/var/spool/cron/crontabs/$SVC_NAME"
  printf 'ligne utilisateur (filet, laissee en place) -- %s :\n' "$spool"
  grep -F 'iot-audit:vllm-autostart' "$spool" 2>/dev/null | sed 's/^/  /' || printf '  (aucune)\n'
  printf 'service tourne maintenant : '
  local pidfile="$SVC_HOME/logs/qwen_$(hostname -s).pid" p
  if [ -f "$pidfile" ] && p="$(cat "$pidfile" 2>/dev/null)" && [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
    printf 'oui (PID %s)\n' "$p"
  else printf 'non (ou PID inconnu)\n'; fi
}

# verify -- execute la commande EXACTE de cron, telle quelle. Sert de preuve que
# la descente d'identite et l'appel du script fonctionnent ; sans risque quand le
# service tourne deja, car vllm-autostart.sh sort 0 sans rien faire.
cmd_verify() {
  require_root
  printf '==== verification de la commande de boot -- %s ====\n' "$(hostname -s)"
  local before after
  before="$(wc -l < "$BOOTLOG" 2>/dev/null || echo 0)"
  printf 'execution : %s\n' "$(boot_command)"
  bash -c "$(boot_command)"; local rc=$?
  after="$(wc -l < "$BOOTLOG" 2>/dev/null || echo 0)"
  printf 'rc=%s  (lignes ajoutees au journal du boot : %s)\n' "$rc" "$(( after - before ))"
  printf 'derniere ligne du journal :\n'
  tail -n 1 "$BOOTLOG" 2>/dev/null | sed 's/^/  /'
  [ "$rc" -eq 0 ] || printf 'ATTENTION : rc non nul -- a lire avant de compter sur cette tache\n'
  return "$rc"
}

case "${1:-status}" in
  install) cmd_install ;;
  remove)  cmd_remove ;;
  status)  cmd_status ;;
  verify)  cmd_verify ;;
  *) die "usage: $0 install|remove|status|verify" ;;
esac
