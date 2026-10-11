#!/bin/bash
# =============================================================================
#  vllm-autostart.sh -- redemarrer le service vLLM apres un BOOT de la machine
# =============================================================================
#  Pourquoi ce fichier existe : les trois noeuds sont relances par la VM hote, et
#  rien ne relance vLLM. Le 2026-09-16 les serveurs tournaient (uptime 3j18h), mais
#  /tmp avait ete vide et une grappe redemarree sans vLLM ne sert plus qu'une page
#  d'erreur -- sans qu'aucune trace ne dise pourquoi. Ce n'est pas un detail
#  d'exploitation : une grappe eteinte et une grappe saturee se ressemblent depuis un
#  client, et un banc lance dessus mesure zero.
#
#  Devuan 6 n'a pas de systemd (voir infra/README.md) : le service est un nohup + PID
#  file, et le seul mecanisme de demarrage disponible est le cron de l'utilisateur
#  (`@reboot`). sudo demande un mot de passe sur les trois noeuds, donc les emplacements
#  racine (/etc/init.d, /etc/cron.d) sont hors de portee -- et c'est aussi pourquoi
#  ce script est PER-NOEUD et vit dans $HOME, comme les autres outils per-noeud.
#
#  usage (SUR UN NOEUD) :
#      bash vllm-autostart.sh --install      # installe la ligne cron (idempotent)
#      bash vllm-autostart.sh --uninstall    # retire la ligne cron (idempotent)
#      bash vllm-autostart.sh --disable      # garde l'installation mais NE DEMARRE PLUS
#      bash vllm-autostart.sh --enable       # annule --disable
#      bash vllm-autostart.sh --status       # ce qui est installe, et la derniere tentative
#      bash vllm-autostart.sh --run [--dry-run]   # l'action du boot (defaut)
#
#  --disable vs --uninstall : --disable ecrit un marqueur ($HOME/.no-vllm-autostart)
#  que --run lit en PREMIER. La ligne cron reste en place et l'intention reste
#  visible dans --status ; --uninstall, lui, retire la ligne et laisse le noeud
#  sans demarrage automatique du tout. Les deux existent parce qu'ils repondent a
#  deux besoins differents : « pas maintenant » et « plus jamais ».
#
#  PRINCIPE : ce script ne lance JAMAIS vLLM lui-meme. Il attend que la machine soit
#  prete, puis delegue a vllm-service.sh, qui porte deja les preflights (compilateur
#  hote, ninja), le refus de port occupe, et l'attente de /v1/models. Reimplementer le
#  lancement ici aurait cree une DEUXIEME definition du service -- celle qui deriverait
#  en silence, evidemment.
#
#  CE QU'IL FAUT SAVOIR AVANT DE L'INSTALLER
#  -----------------------------------------
#  * au boot, cron appelle ce script tres tot : le pilote nvidia peut ne pas etre
#    charge, et l'interface reseau peut ne pas avoir d'adresse. Les deux sont attendus
#    ici, avec un delai maximal et une ligne de journal par tentative.
#  * si le service tourne DEJA, il ne le touche pas et sort 0 : relancer un banc ou
#    un harnais a la main reste donc possible, et un boot n'ecrase jamais un service
#    en cours.
#  * `--uninstall` rend le cron EXACTEMENT comme avant (sauvegarde datee a cote).
# =============================================================================
set -uo pipefail

# cron ne donne pas l'environnement d'un shell de connexion. HOME est donc fixe ici
# (tout le reste en derive), et PATH est COMPLETE, jamais remplace : sous Devuan, cron
# donne deja /usr/bin:/bin, ou vivent `nvidia-smi`, `ip` et `ss` ; les repertoires
# d'administration sont ajoutes parce qu'ils peuvent manquer sur une autre
# distribution. Ecraser PATH a la place (ce que faisait la premiere version) rendait
# le script intestable -- un binaire place devant dans PATH pour verifier un chemin
# d'echec etait ignore -- et pouvait perdre un chemin que l'appelant avait raison de
# fournir. vllm-service.sh verifie de son cote, dans un shell NU, que le correctif de
# compilateur est actif : ce complete de PATH ne masque pas ce controle.
export HOME="${HOME:-$(getent passwd "$(id -un)" | cut -d: -f6)}"
export PATH="${PATH:-/usr/bin:/bin}:/usr/sbin:/sbin:/usr/local/sbin:/usr/local/bin"

SELF="$HOME/vllm-autostart.sh"
if [ -z "${VLLM_SERVICE:-}" ]; then
  for s in "$HOME/vllm-service.sh" "$HOME/node_vllm_service.sh" "$(dirname "$0")/node_vllm_service.sh"; do
    [ -f "$s" ] && { VLLM_SERVICE="$s"; break; }
  done
fi
SERVICE="${VLLM_SERVICE:-$HOME/vllm-service.sh}"
LOG="${AUTOSTART_LOG:-$HOME/logs/vllm-autostart.log}"
TAG="iot-audit:vllm-autostart"

GPU_WAIT_S="${GPU_WAIT_S:-300}"     # attente du pilote nvidia apres boot
NET_WAIT_S="${NET_WAIT_S:-120}"     # attente d'une adresse IPv4 globale
MAX_TRIES="${MAX_TRIES:-3}"         # tentatives de demarrage du service
RETRY_S="${RETRY_S:-30}"            # delai entre ces tentatives
STEP_S="${STEP_S:-5}"               # pas des attentes

MARKER="$HOME/.no-vllm-autostart"   # present = --run ne demarre rien (voir --disable)
DRY_RUN=0
ACTION="run"

log() {  # horodate, dans le fichier -- jamais sur stdout (cron redirige deja dedans)
  mkdir -p "$(dirname "$LOG")"
  printf '%s  %s\n' "$(date -Is)" "$*" >> "$LOG"
}

# --- LE REPERTOIRE DE TRAVAIL EST FIXE ICI, PAS HERITE DE L'APPELANT -------
# MESURE 2026-09-29, zabeth22, redemarrage reel : vLLM forke son EngineCore via
# `multiprocessing` (methode spawn). L'enfant reapplique le cwd du parent :
#
#     File ".../multiprocessing/spawn.py", line 235, in prepare
#       os.chdir(data['dir'])
#     PermissionError: [Errno 13] Permission denied: '/root'
#
# cron lance une tache avec le cwd du COMPTE PROPRIETAIRE de la tache :
# /home/msalhi pour la ligne @reboot de l'utilisateur, mais **/root** pour la
# tache systeme /etc/cron.d/iot-audit-vllm-autostart. Or `setpriv` change
# uid/gid et **pas le cwd** : l'instance systeme demarrait donc le service avec
# cwd=/root, et l'EngineCore mourait aussitot. Sur zabeth21 l'instance perdante
# etait celle-la, d'ou un service apparemment sain ; sur zabeth22 elle avait le
# verrou, donc AUCUN service. On ne depend plus du cwd de l'appelant.
cd "$HOME" || { log "ECHEC : $HOME inaccessible -- rien n'a ete lance"; exit 2; }

# ---------------------------------------------------------------- attentes
wait_gpu() {   # la carte doit repondre AVANT que vllm-service.sh ne prenne le GPU
  local waited=0
  while (( waited < GPU_WAIT_S )); do
    if nvidia-smi -L >/dev/null 2>&1; then
      log "GPU pret apres ~${waited}s ($(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1))"
      return 0
    fi
    sleep "$STEP_S"; waited=$((waited + STEP_S))
  done
  log "ECHEC : pas de GPU apres ${GPU_WAIT_S}s -- vllm-service.sh n'a pas ete appele"
  return 1
}

wait_net() {   # le service se lie a l'adresse LAN : sans adresse, la liaison echoue
  local waited=0
  while (( waited < NET_WAIT_S )); do
    if ip -4 -o addr show scope global 2>/dev/null | grep -q 'inet '; then
      log "adresse IPv4 globale presente apres ~${waited}s"
      return 0
    fi
    sleep "$STEP_S"; waited=$((waited + STEP_S))
  done
  log "ECHEC : aucune adresse IPv4 globale apres ${NET_WAIT_S}s"
  return 1
}

service_running() {   # meme definition que vllm-service.sh : PID vivant, ou port ecoute
  # Les memes variables que vllm-service.sh (LOG_DIR, QWEN_PORT) : si quelqu'un
  # deplacait le repertoire des journaux, le PID file suivrait le service -- et une
  # verification de presence qui regarde ailleurs conclurait « rien ne tourne » puis
  # lancerait un SECOND serveur sur la meme carte.
  local pidfile="${LOG_DIR:-$HOME/logs}/qwen_$(hostname -s).pid" p port
  port="${QWEN_PORT:-8000}"
  if [ -f "$pidfile" ]; then
    p="$(cat "$pidfile" 2>/dev/null)"
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null && return 0
  fi
  ss -ltn 2>/dev/null | grep -q ":${port} " && return 0
  return 1
}

# ---------------------------------------------------------------- action du boot
do_run() {
  # --- UNE SEULE INSTANCE A LA FOIS (2026-09-29) ----------------------------
  # Il y a maintenant DEUX declencheurs de boot : la ligne @reboot de
  # l'utilisateur, et la tache systeme /etc/cron.d/iot-audit-vllm-autostart
  # (identite numerique, pour demarrer meme si l'annuaire est injoignable).
  # cron les lance a la MEME milliseconde -- MESURE, zabeth21, premier vrai
  # redemarrage :
  #
  #   12:25:34.688  CRON[2751]: (root) CMD (... vllm-autostart.sh --run ...)
  #   12:25:34.689  CRON[2753]: (msalhi) CMD (... vllm-autostart.sh --run ...)
  #
  # Les deux passaient le controle "service deja en cours" AVANT que l'un ait
  # demarre quoi que ce soit : les deux ont donc lance vllm (PID 3164 et 3167).
  # L'un est mort ("EngineCore initialization failed" -- la carte etait prise
  # par l'autre) et, en mourant, vllm-service.sh supprime son pidfile : celui de
  # l'instance GAGNANTE. Bilan mesure : le service repondait 200 **sans pidfile**,
  # et le journal annoncait "ECHEC : le service n'a pas demarre apres 3 essais".
  #
  # Deux declencheurs, c'est bien (redundance). Deux LANCEMENTS, non. Le verrou
  # rend la redondance sure : l'instance perdante sort 0 immediatement, sans rien
  # toucher. Le verrou est pris sur un fd du shell et relache a la sortie du
  # processus -- un kill -9 ne peut PAS le laisser en place (contrairement a un
  # verrou par repertoire, qui exigerait de gerer la peremption).
  local lockdir="${LOG_DIR:-$HOME/logs}"
  local lockfile="$lockdir/.vllm-autostart.lock"
  mkdir -p "$lockdir"
  if [ -w "$lockdir" ] && command -v flock >/dev/null 2>&1; then
    exec 9>"$lockfile"
    if ! flock -n 9; then
      log "une autre instance de l autostart tourne deja -- rien a faire (verrou $lockfile)"
      return 0
    fi
  else
    log "AVERTISSEMENT : verrou indisponible (flock absent ou $lockdir non inscriptible)"
  fi

  log "==== autostart -- $(hostname -s) -- debut ===="
  # Le marqueur est teste AVANT tout le reste : « ne demarre pas » doit etre une
  # decision, pas une consequence de l'ordre des controles. Un noeud peut avoir
  # besoin de sa carte pour autre chose, et un serveur qui apparait tout seul au
  # boot est exactement ce qu'on ne veut pas decouvrir apres coup.
  if [ -e "$MARKER" ]; then
    log "desactive par $MARKER -- aucun demarrage (retirer ce fichier, ou --enable)"
    return 0
  fi
  if [ ! -x "$SERVICE" ] && [ ! -f "$SERVICE" ]; then
    log "ECHEC : $SERVICE introuvable -- rien a appeler"
    return 2
  fi
  if service_running; then
    log "service deja en cours -- rien a faire (ce script n'arrete ni ne relance un service vivant)"
    return 0
  fi
  wait_gpu || return 3
  wait_net || return 3

  local try=1 rc
  while (( try <= MAX_TRIES )); do
    if (( DRY_RUN )); then
      log "essai $try/$MAX_TRIES : (simulation) bash $SERVICE start"
      return 0
    fi
    log "essai $try/$MAX_TRIES : bash $SERVICE start"
    # Le code de retour est capture SEPAREMENT : apres un `if ... fi` sans `else`,
    # `$?` vaut 0 par definition (POSIX), donc le journal aurait annonce « rc=0 »
    # pour chaque echec -- et un journal qui dit 0 partout est pire qu'aucun journal.
    bash "$SERVICE" start >>"$LOG" 2>&1
    rc=$?
    if [ "$rc" -eq 0 ]; then
      log "service demarre -- $(hostname -s)"
      return 0
    fi
    log "essai $try/$MAX_TRIES en echec (rc=$rc)"
    try=$((try + 1))
    (( try <= MAX_TRIES )) && sleep "$RETRY_S"
  done
  log "ECHEC : le service n'a pas demarre apres $MAX_TRIES essais -- voir $HOME/logs/qwen_$(hostname -s).log"
  return 4
}

# ---------------------------------------------------------------- cron
cron_line() {  # la ligne EXACTE que --install ecrit (et que --status doit montrer)
  printf '@reboot /bin/bash %s --run >>%s 2>&1  # %s\n' "$SELF" "$LOG" "$TAG"
}

crontab_read() { crontab -l 2>/dev/null || true; }

backup_crontab() {
  local cur; cur="$(crontab_read)"
  if [ -n "$cur" ]; then
    local b="$HOME/crontab.bak-$(date +%Y%m%dT%H%M%S)"
    printf '%s\n' "$cur" > "$b"
    chmod 600 "$b"
    log "cron sauvegarde avant modification : $b"
  fi
}

do_install() {
  command -v crontab >/dev/null 2>&1 || { echo "crontab introuvable : rien ne peut etre installe" >&2; return 2; }
  # self-install : la copie du depot n'est pas sur le noeud, et la ligne cron doit
  # pointer sur un chemin qui existe AU MOMENT DU BOOT.
  if [ "$(readlink -f "$0")" != "$(readlink -f "$SELF")" ]; then
    install -m 755 "$0" "$SELF"
    log "script installe : $SELF"
  fi
  mkdir -p "$(dirname "$LOG")"
  local cur; cur="$(crontab_read)"
  if printf '%s\n' "$cur" | grep -qF "$TAG"; then
    echo "deja installe (ligne marquee $TAG presente)"
    return 0
  fi
  backup_crontab
  { printf '%s\n' "$cur" | grep -v '^[[:space:]]*$'; cron_line; } | crontab -
  log "ligne cron installee"
  echo "installe :"
  cron_line | sed 's/^/  /'
  echo "  (pour garder l'installation sans demarrer au boot : --disable)"
}

do_uninstall() {
  local cur; cur="$(crontab_read)"
  if ! printf '%s\n' "$cur" | grep -qF "$TAG"; then
    echo "rien a retirer (aucune ligne marquee $TAG)"
    return 0
  fi
  backup_crontab
  printf '%s\n' "$cur" | grep -vF "$TAG" | sed '/^[[:space:]]*$/d' | crontab -
  log "ligne cron retiree"
  echo "retire. Le script et le journal restent en place :"
  echo "  $SELF"
  echo "  $LOG"
}

do_status() {
  echo "==== autostart -- $(hostname -s) ===="
  echo "script    : $([ -f "$SELF" ] && echo "$SELF" || echo "ABSENT ($SELF)")"
  echo "service   : $SERVICE$([ -f "$SERVICE" ] && echo "" || echo "  (ABSENT)")"
  echo "journal   : $LOG"
  if [ -e "$MARKER" ]; then
    echo "etat      : DESACTIVE (marqueur $MARKER present) -- un boot ne demarrerait rien"
  else
    echo "etat      : actif"
  fi
  echo "cron      :"
  if crontab_read | grep -qF "$TAG"; then
    crontab_read | grep -F "$TAG" | sed 's/^/  /'
  else
    echo "  aucune ligne marquee $TAG -- pas de demarrage automatique"
  fi
  # Le demon s'appelle `cron` sous Devuan (et `crond` ailleurs) : chercher seulement
  # `crond` concluait « non detecte » sur une machine ou il tourne, ce qui ferait
  # douter d'un @reboot qui, lui, fonctionne.
  if pgrep -x cron >/dev/null 2>&1 || pgrep -x crond >/dev/null 2>&1; then
    echo "demon cron: actif ($(pgrep -x cron || pgrep -x crond | head -1))"
  else
    echo "demon cron: NON DETECTE -- une ligne @reboot ne serait jamais declenchee"
  fi
  echo "service tourne maintenant : $(service_running && echo oui || echo non)"
  if [ -s "$LOG" ]; then
    echo "dernieres lignes du journal :"
    tail -n 8 "$LOG" | sed 's/^/  /'
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --install)   ACTION="install" ;;
    --uninstall) ACTION="uninstall" ;;
    --disable)   ACTION="disable" ;;
    --enable)    ACTION="enable" ;;
    --status)    ACTION="status" ;;
    --run)       ACTION="run" ;;
    --dry-run)   DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "argument inconnu : $1 (voir --help)" >&2; exit 64 ;;
  esac
  shift
done

do_disable() {
  : > "$MARKER"
  log "desactivation : $MARKER cree"
  echo "desactive : $MARKER"
  echo "  la ligne cron reste en place ; --run ne demarrera plus rien jusqu'a --enable"
}

do_enable() {
  if [ -e "$MARKER" ]; then rm -f "$MARKER"; log "reactivation : $MARKER retire"; fi
  echo "actif : $MARKER absent ($(crontab_read | grep -cF "$TAG") ligne cron marquee)"
}

case "$ACTION" in
  run)       do_run ;;
  install)   do_install ;;
  uninstall) do_uninstall ;;
  disable)   do_disable ;;
  enable)    do_enable ;;
  status)    do_status ;;
esac
