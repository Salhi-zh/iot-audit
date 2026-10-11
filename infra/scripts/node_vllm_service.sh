#!/bin/bash
# =============================================================================
#  vllm-service.sh -- start / stop / status / health for the vLLM VLM service
# =============================================================================
#  Devuan 6 has no systemd, so this is nohup + a PID file, per infra/README.md
#  ("servers are launched with nohup and stopped by PID/port, never systemctl").
#
#  Defaults mirror iot-audit/infra/config/cluster.env. Override by exporting, or
#  by placing a file at ~/.iot-audit-infra.env (gitignored per the project).
#
#  usage:  bash vllm-service.sh start|stop|restart|status|health|logs|wait
#
#  DESIGN NOTES
#  ------------
#  * Binds the LAN address (SPEC §12.3), never 0.0.0.0, never a routable port.
#  * Refuses to start if the nvcc host-compiler fix is not effective IN A BARE
#    SHELL. flashinfer JIT-fails at the first token otherwise, and the server
#    would look healthy first -- so this is a preflight, not a warning.
#  * Refuses to start on an occupied port, or with less free VRAM than
#    QWEN_MIN_FREE_VRAM_MB. Never kills an existing server.
#  * Idempotent: `start` on a running service reports and exits 0.
# =============================================================================
set -uo pipefail

# NOTE (added 2026-09-14 by the executing agent, SPEC §19 P6)
# PER-NODE tool, unlike every other script in infra/scripts/. Run it ON a node:
#     ssh <node> bash node_vllm_service.sh start|stop|status|health|restart|logs
# It is the single-node supervisor (nohup + PID file, Devuan has no systemd).
# THREE deliberate differences from start_qwen_all.sh:
#   * binds the LAN address (§12.3), never 0.0.0.0
#   * preflights the two host-environment traps that kill flashinfer at the first
#     JIT op (host gcc > 13; `ninja` reachable only through $VENV/bin)
#   * `stop` reports success only when the GPU is RELEASED, and reaps an
#     EngineCore child orphaned by a kill -9 (it rewrites its argv, so
#     `pgrep -f "vllm serve"` cannot see it; it holds 74.7% of the card)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 2026-09-17: this block used to sit ABOVE the shebang, which put `#!/bin/bash`
# on line 7 — inert, so a direct `./golden-check.sh` fell back to /bin/sh — and
# shifted the `--help` range off the header it was written for. It is now the
# first block of the body, so line 1 is the shebang again and the header keeps
# its original numbering. Text unchanged; only its position moved.

# ---- configuration (mirrors cluster.env) ----------------------------------
[[ -r "$HOME/.iot-audit-infra.env" ]] && . "$HOME/.iot-audit-infra.env"

VENV="${VLLM_ENV:-$HOME/vllm-env}"
MODELS_DIR="${MODELS_DIR:-$HOME/models}"
MODEL_DIR="${QWEN_MODEL_DIR:-$MODELS_DIR/Qwen2.5-VL-7B-Instruct-GPTQ-Int4}"
SERVED_NAME="${QWEN_SERVED_NAME:-qwen2.5-vl-7b}"
PORT="${QWEN_PORT:-8000}"
GPU_UTIL="${GPU_MEM_UTIL:-0.90}"
MAX_LEN="${QWEN_MAX_LEN:-8192}"
MIN_FREE_VRAM="${QWEN_MIN_FREE_VRAM_MB:-7500}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-300}"
BOOT_INTERVAL="${BOOT_INTERVAL:-5}"
EXTRA_ARGS="${QWEN_EXTRA_ARGS:-}"

# Image de test -- meme resolution que les deux autres outils per-noeud. Les trois
# sont deployes SEPAREMENT dans $HOME (aucun n'a de checkout du depot), donc la
# liste est repetee : les garder en phase. 2026-09-28 : les octets sont versionnes
# (infra/assets/test-images/, sha256 ca07ce15...) et l'image est resolue au lieu
# d'etre devinee -- le seul chemin connu etait /tmp, qui se vide au redemarrage.
# `health` dit alors « requete image : ignoree » sur un noeud sain apres un reboot.
if [ -z "${TEST_IMAGE:-}" ]; then
  for TEST_IMAGE in \
      "$(dirname "$0")/../assets/test-images/device_clean.jpg" \
      "$HOME/infra/assets/test-images/device_clean.jpg" \
      "$HOME/vlm-test-images/device_clean.jpg" \
      /tmp/vlm-test-images/device_clean.jpg; do
    [ -f "$TEST_IMAGE" ] && break
  done
fi
IMAGE="$TEST_IMAGE"

# Charge utile de mesure -- meme resolution que node_gpu_bench.sh, et MEME squelette JSON
# (226 octets, identiques dans les deux fichiers ; infra/selftest/check-payload-consistency.sh
# echoue s'ils divergent). Un `health` qui ne poste pas la meme requete que le banc ne
# valide pas ce que le banc mesure -- et c'etait exactement le cas : ce script portait sa
# propre copie du JSON, que rien ne comparait a l'autre.
# cluster.env n'est PAS source en entier ici : il definit NODE_HOME, VLLM_ENV,
# BENCH_SCRIPT, ... alors que ce script a ses propres defauts. Les trois valeurs sont
# extraites dans un SOUS-SHELL, comme le banc le fait pour ses endpoints -- rien ne fuit.
CLUSTER_ENV="${CLUSTER_ENV:-}"
if [ -z "$CLUSTER_ENV" ]; then
  for c in "$(dirname "$0")/../config/cluster.env" "$HOME/infra/config/cluster.env"; do
    [ -f "$c" ] && { CLUSTER_ENV="$c"; break; }
  done
fi
PROMPT="${VLM_PROMPT:-Identify the device: brand, model, category.}"
MAXTOK="${VLM_MAX_TOKENS:-96}"
TEMPER="${VLM_TEMPERATURE:-0}"
PAYLOAD_SOURCE="repli 2026-09-15"
payload_from_config() {  # $1 = cluster.env ; stdout = 3 lignes : prompt, max_tokens, temperature
  ( set -u
    . "$1" >/dev/null 2>&1 || exit 1
    printf '%s\n%s\n%s\n' "${VLM_PROMPT:-}" "${VLM_MAX_TOKENS:-96}" "${VLM_TEMPERATURE:-0}" )
}
if [ -n "$CLUSTER_ENV" ]; then
  if _pl="$(payload_from_config "$CLUSTER_ENV")" && [ -n "$(printf '%s' "$_pl" | sed -n 1p)" ]; then
    PROMPT="$(printf '%s\n' "$_pl" | sed -n 1p)"
    MAXTOK="$(printf '%s\n' "$_pl" | sed -n 2p)"
    TEMPER="$(printf '%s\n' "$_pl" | sed -n 3p)"
    PAYLOAD_SOURCE="config $CLUSTER_ENV"
  else
    printf 'AVERTISSEMENT : %s trouve mais sans VLM_PROMPT -- repli sur la charge du 2026-09-15\n' "$CLUSTER_ENV" >&2
  fi
fi
# Voir cluster.env : le prompt est interpole dans du JSON, on refuse plutot que de poster
# un corps auquel le serveur repondrait 400 sur CHAQUE requete.
if printf '%s' "$PROMPT" | grep -q -e '[\\"]' -e '[[:cntrl:]]'; then
  printf 'VLM_PROMPT invalide : ni guillemet double, ni antislash, ni caractere de controle\n' >&2
  printf '  (il est interpole dans le corps JSON)\n' >&2
  exit 2
fi

# La revision epinglee vit dans cluster.env, qui n'est PAS source en entier ici (voir
# la note ci-dessus sur payload_from_config) : elle s'extrait de la MEME facon, dans un
# SOUS-SHELL. Si cluster.env est introuvable ou ne la porte pas, la variable reste celle
# de l'environnement -- donc vide, ce que le preflight traite comme « non epinglee ».
revision_from_config() {  # $1 = cluster.env ; stdout = QWEN_MODEL_REVISION (vide si absente)
  ( set -u
    . "$1" >/dev/null 2>&1 || exit 1
    printf '%s\n' "${QWEN_MODEL_REVISION:-}" )
}
REVISION_PIN="${QWEN_MODEL_REVISION:-}"
if [ -n "$CLUSTER_ENV" ]; then
  if _rv="$(revision_from_config "$CLUSTER_ENV")" && [ -n "$_rv" ]; then
    REVISION_PIN="$_rv"
  fi
fi

HOST_SHORT="$(hostname -s)"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
LOG="$LOG_DIR/qwen_${HOST_SHORT}.log"
PIDFILE="$LOG_DIR/qwen_${HOST_SHORT}.pid"

VLLM_BIN="$VENV/bin/vllm"
PY="$VENV/bin/python"

err()  { printf '%s\n' "$*" >&2; }
info() { printf '%s\n' "$*"; }

# LAN address for this node, from cluster.env's NODE_IPS or auto-detected.
lan_ip() {
  local want="${NODE_IPS:-}" ip
  want="${want//[()]/}"; want="${want// /}"
  for ip in ${want//,/ }; do
    [[ "$ip" == 172.26.145.* ]] && ip -o addr show 2>/dev/null | grep -q " $ip/" && { echo "$ip"; return 0; }
  done
  ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 \
    | grep -E '^172\.26\.' | head -1
}

port_busy() { ss -ltn 2>/dev/null | grep -q ":$PORT "; }

pid_alive() {
  [[ -f "$PIDFILE" ]] || return 1
  local p; p="$(cat "$PIDFILE" 2>/dev/null)"
  [[ -n "$p" ]] && kill -0 "$p" 2>/dev/null
}

# Revision du modele PRESENTE SUR LE DISQUE. C'est la MEME mesure que le bloc « 2 bis »
# de node_write_provenance.sh, et elle doit le rester : c'est cette valeur qui part dans
# provenance.json, donc dans le rapport scelle, et une epingle qui compare autre chose
# que ce que le rapport publie ne garantit rien. Methode : 1re ligne de chaque
# *.metadata sous $MODEL/.cache/huggingface/download, espaces retires LIGNE PAR LIGNE
# (un `tr -d '[:space:]'` sur tout le fichier colle les N valeurs en une seule ligne de
# 40*N caracteres -- defaut vu et corrige le 2026-10-06 cote provenance), une seule
# valeur distincte, au format d'un sha de commit. stdout = la revision, vide si la
# reponse est absente ou ambigue.
model_disk_revision() {  # $1 = dossier modele
  local mdl="$1" tmp uniq n
  local revdir="$mdl/.cache/huggingface/download"
  [ -d "$revdir" ] || return 1
  tmp="$(mktemp "${TMPDIR:-/tmp}/rev-XXXXXX")" || return 1
  while IFS= read -r md; do
    printf '%s\n' "$(head -n1 "$md" | tr -d '[:space:]')" >>"$tmp"
  done < <(find "$revdir" -maxdepth 1 -name '*.metadata' 2>/dev/null | LC_ALL=C sort)
  uniq="$(LC_ALL=C sort -u "$tmp" | sed '/^$/d')"
  n="$(printf '%s\n' "$uniq" | sed '/^$/d' | wc -l)"
  rm -f "$tmp"
  if [ "$n" -eq 1 ] && [[ "$uniq" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' "$uniq"
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
cmd_start() {
  mkdir -p "$LOG_DIR"
  info "==== demarrage du service vLLM -- $HOST_SHORT -- $(date -Is) ===="

  if pid_alive; then
    info "  deja en cours (PID $(cat "$PIDFILE")) -- rien a faire"
    return 0
  fi
  if port_busy; then
    err "  ECHEC : le port $PORT est deja occupe par autre chose."
    err "  Ce script n'arrete jamais un serveur qu'il n'a pas lance. Verifier :"
    err "    ss -ltnp | grep :$PORT"
    return 3
  fi

  [[ -x "$VLLM_BIN" ]] || { err "  ECHEC : $VLLM_BIN introuvable"; return 2; }
  [[ -d "$MODEL_DIR" ]] || { err "  ECHEC : modele introuvable : $MODEL_DIR"; return 2; }

  # --- PREFLIGHT: the venv must be self-sufficient WITHOUT a shell ---------
  # Two 2026-09-14 defects share this shape: the engine starts, reports healthy,
  # then dies at the first flashinfer JIT build. Both are fixed in the venv's
  # sitecustomize.py, so they must hold for a bare interpreter started here.
  #   (1) host compiler -> NVCC_PREPEND_FLAGS must carry -ccbin
  #   (2) ninja is $VENV/bin/ninja -- PATH must reach it
  local probe
  probe="$(env -u NVCC_PREPEND_FLAGS -u CUDAHOSTCXX -u PATH "$PY" - <<'PYPROBE' 2>/dev/null
import os, shutil
print("CCBIN=" + (os.environ.get("NVCC_PREPEND_FLAGS") or ""))
print("NINJA=" + (shutil.which("ninja") or ""))
PYPROBE
)"
  local cf nj
  cf="$(printf '%s\n' "$probe" | sed -n 's/^CCBIN=//p')"
  nj="$(printf '%s\n' "$probe" | sed -n 's/^NINJA=//p')"
  if [[ "$cf" != *ccbin* ]]; then
    err "  ECHEC PREFLIGHT : le correctif nvcc n'est pas actif sans shell."
    err "    attendu : NVCC_PREPEND_FLAGS contient 'ccbin'"
    err "    obtenu  : '${cf:-<vide>}'"
    err "  Correctif : bash $HOME/iot-audit-work/solidify-01-venv-environment.sh"
    err "  Sans lui, flashinfer ne peut pas compiler son op de sampling et le"
    err "  moteur meurt a la premiere generation, apres un demarrage 'reussi'."
    return 4
  fi
  info "  preflight nvcc : OK ($cf)"
  if [[ -z "$nj" ]]; then
    err "  ECHEC PREFLIGHT : 'ninja' introuvable sans activation du venv."
    err "    flashinfer JIT appelle ninja, fourni uniquement par $VENV/bin/ninja."
    err "    Sans lui : FileNotFoundError: 'ninja' -> Engine core initialization failed."
    err "  Correctif : bash $HOME/iot-audit-work/solidify-01-venv-environment.sh"
    return 4
  fi
  info "  preflight ninja : OK ($nj)"

  # --- PREFLIGHT: la revision du modele est EPINGLEE, pas supposee ----------
  # Pourquoi une egalite verifiee et non `vllm serve --revision <sha>` : voir la mesure
  # citee dans cluster.env -- sur un CHEMIN LOCAL, `revision=` est ignore en silence, un
  # sha volontairement faux charge sans erreur. Le passer ferait donc publier une
  # epingle que rien n'applique ; comparer la revision lue sur le disque, elle, refuse
  # de demarrer quand le modele n'est pas celui qu'on croit avoir servi.
  local disk_rev=""
  disk_rev="$(model_disk_revision "$MODEL_DIR" 2>/dev/null || true)"
  if [ -z "$REVISION_PIN" ]; then
    info "  preflight revision : NON EPINGLEE (disque : ${disk_rev:-illisible})"
    info "    QWEN_MODEL_REVISION est vide dans cluster.env : ce serveur peut tourner,"
    info "    mais tout run qu'il produit sera refuse au scellement (provenance"
    info "    incomplete). Pour epingler :"
    info "      QWEN_MODEL_REVISION=\"${disk_rev:-<revision lue sur le disque>}\" dans infra/config/cluster.env"
  elif [ -z "$disk_rev" ]; then
    err "  ECHEC PREFLIGHT : la revision du modele n'a pas pu etre LUE sur le disque."
    err "    epinglee (cluster.env) : $REVISION_PIN"
    err "    cherche : $MODEL_DIR/.cache/huggingface/download/*.metadata"
    err "    (absent, illisible, ou plusieurs hash de commit differents)"
    err "  Sans cette lecture, impossible de dire si le modele servi est celui qui est"
    err "  epingle -- et un run le dirait quand meme. Restaurer le cache HF du modele,"
    err "  ou relire la revision publiee : ssh <noeud> cat ~/vllm-env/provenance.json"
    return 6
  elif [ "$disk_rev" = "$REVISION_PIN" ]; then
    info "  preflight revision : OK ($disk_rev)"
  else
    err "  ECHEC PREFLIGHT : le modele sur le disque n'est PAS la revision epinglee."
    err "    epinglee (cluster.env) : $REVISION_PIN"
    err "    sur le disque         : $disk_rev"
    err "  Un run produit ici porterait une provenance fausse. Correctif, au choix :"
    err "    - epingler la revision mesuree :"
    err "        QWEN_MODEL_REVISION=\"$disk_rev\" dans infra/config/cluster.env"
    err "    - restaurer le modele epingle : $MODEL_DIR"
    return 6
  fi

  local free
  free="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)"
  if [[ -n "$free" ]] && (( free < MIN_FREE_VRAM )); then
    err "  ECHEC : VRAM libre ${free} MiB < seuil ${MIN_FREE_VRAM} MiB (cluster.env)"
    # Name the holder. After a crash the usual culprit is an orphaned
    # `VLLM::EngineCore` child surviving a kill -9 of the API server; see the
    # long note above orphan_group(). Naming it turns a vague refusal into a
    # one-command fix.
    local holder
    holder="$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null)"
    if [[ -n "$holder" ]]; then
      err "    Processus detenant la GPU :"
      printf '%s\n' "$holder" | sed 's/^/      /' >&2
      err "    Si ce sont des orphelins (PPID=1), les liberer : $0 stop"
    fi
    return 3
  fi
  info "  preflight VRAM : ${free:-?} MiB libres"

  local ip; ip="$(lan_ip)"
  [[ -n "$ip" ]] || { err "  ECHEC : aucune adresse LAN 172.26.x trouvee"; return 2; }
  info "  bind : ${ip}:${PORT}  (SPEC §12.3 : jamais 0.0.0.0)"

  # sitecustomize.py carries the real fix (compiler + PATH), so the server works
  # from a bare environment. PATH is also set explicitly here: a service should
  # not depend on a magic hint from the interpreter, and it costs nothing.
  export PATH="$VENV/bin:$PATH"
  # SOUVERAINETE : rien de ce que le service declenche ne doit sortir. vLLM poste
  # par defaut un « usage heartbeat » a https://stats.vllm.ai au demarrage du
  # moteur, sous l'UID DU SERVICE -- donc invisible a toute mesure qui ne regarde
  # que l'adresse. Mesure du 2026-09-29 (instrument egress-attrib-uid.sh, fenetre
  # « demarrage ») : uid 10131 -> 2606:4700:3032::6815:58f5 port 443, et les trois
  # noeuds resolvent stats.vllm.ai vers EXACTEMENT cette adresse. Aucun invariant
  # G1-G10 ne demande ce heartbeat, et il fait dependre le demarrage du service
  # d'un tiers. Le mecanisme d'extinction est celui que documente le paquet
  # lui-meme (vllm/usage/usage_lib.py : is_usage_stats_enabled) :
  # VLLM_NO_USAGE_STATS=1. Et le meme opt-out sous forme de FICHIER, parce qu'une
  # variable exportee ne suit pas l'utilisateur hors de ce script : elle ne couvre
  # pas un `vllm` lance a la main par le compte du service. `do_not_track` si.
  export VLLM_NO_USAGE_STATS=1
  mkdir -p "$HOME/.config/vllm" && : > "$HOME/.config/vllm/do_not_track"
  : > "$LOG"
  info "  lancement (log -> $LOG)"
  local args=(serve "$MODEL_DIR"
    --served-model-name "$SERVED_NAME"
    --host "$ip" --port "$PORT"
    --gpu-memory-utilization "$GPU_UTIL"
    --max-model-len "$MAX_LEN"
    --limit-mm-per-prompt '{"image": 1}')
  # shellcheck disable=SC2206
  [[ -n "$EXTRA_ARGS" ]] && args+=($EXTRA_ARGS)

  nohup setsid "$VLLM_BIN" "${args[@]}" >>"$LOG" 2>&1 </dev/null &
  local pid=$!
  echo "$pid" > "$PIDFILE"
  info "  PID $pid"

  local waited=0
  while (( waited < BOOT_TIMEOUT )); do
    if curl -sf "http://${ip}:${PORT}/v1/models" >/dev/null 2>&1; then
      info "  PRET en ~${waited}s -- http://${ip}:${PORT}/v1/models"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      err "  ECHEC : le processus est mort pendant le demarrage."
      err "  25 dernieres lignes de $LOG :"
      tail -25 "$LOG" 2>/dev/null | sed 's/^/    /' >&2
      rm -f "$PIDFILE"
      return 5
    fi
    sleep "$BOOT_INTERVAL"; waited=$((waited + BOOT_INTERVAL))
  done
  err "  ECHEC : /v1/models toujours muet apres ${BOOT_TIMEOUT}s (PID $pid encore vivant, log conserve)"
  return 5
}

# ---------------------------------------------------------------------------
#  cmd_wait -- bloquer jusqu'a ce que le service reponde, SANS le lancer
#
#  `wait` etait annonce dans l'usage depuis l'origine et absent de la table de
#  dispatch : `vllm-service.sh wait` tombait donc dans `*` et sortait en 64 (usage)
#  -- une action documentee qui n'existe pas. Or elle a un usage reel, different de
#  `start` : attendre un serveur qu'on n'a PAS lance (relance par le cron de boot, ou
#  par quelqu'un d'autre), et savoir en un coup d'oeil s'il finit par repondre.
#  C'est aussi la sonde que le superviseur de boot pourrait utiliser apres coup.
# ---------------------------------------------------------------------------
cmd_wait() {
  local ip; ip="$(lan_ip)"
  info "==== attente de /v1/models -- $HOST_SHORT (jusqu'a ${BOOT_TIMEOUT}s) ===="
  local waited=0
  while (( waited < BOOT_TIMEOUT )); do
    if curl -sf "http://${ip:-127.0.0.1}:$PORT/v1/models" >/dev/null 2>&1; then
      info "  PRET en ~${waited}s -- http://${ip:-127.0.0.1}:$PORT/v1/models"
      return 0
    fi
    sleep "$BOOT_INTERVAL"; waited=$((waited + BOOT_INTERVAL))
  done
  err "  ECHEC : /v1/models muet apres ${BOOT_TIMEOUT}s"
  return 5
}

# ---------------------------------------------------------------------------
#  orphan_group <pgid>  -- every live PID whose process group is <pgid>
#
#  WHY THIS EXISTS (measured on zabeth22, 2026-09-14, by fault injection)
#  -----------------------------------------------------------------------
#  vLLM's V1 engine forks an `EngineCore` child. That child REWRITES ITS OWN
#  ARGV: `ps` shows it as `VLLM::EngineCore`, not as `python ... vllm serve`.
#
#  So a `kill -9` on the API server leaves:
#      PID   PPID  PGID   ARGS
#      5633  1     5452   python -c from multiprocessing.resource_tracker import main
#      5634  1     5452   VLLM::EngineCore        <- holds 8916 MiB of VRAM
#  reparented to init, invisible to `pgrep -f "vllm serve <model>"`, and still
#  in the process group `setsid` created. The GPU is unusable until someone
#  kills it by hand, and `stop` used to DELETE the pidfile first -- destroying
#  the only handle on the group.
#
#  The process group is the reliable handle: it outlives its leader.
# ---------------------------------------------------------------------------
orphan_group() {
  ps -eo pid=,pgid= 2>/dev/null | awk -v g="$1" '$2 == g {print $1}'
}

# ---------------------------------------------------------------------------
#  own_group / stray_by_name -- qui a le droit d'etre tue par `stop`
#
#  MESURE 2026-09-28, zabeth23, serveur VIVANT : `pgrep -f <motif>` compte aussi la
#  LIGNE DE COMMANDE DE L'APPELANT des que celle-ci porte le motif. Un serveur
#  unique et un EngineCore unique se lisaient « 3 » et « 3 » a travers un `bash -c`
#  (l'enveloppe ssh, plus le sous-shell de la substitution). C'est cette
#  auto-correspondance qui a fait annoncer des « orphelins » pour un arret propre.
#
#  Un compte gonfle est un defaut de diagnostic. `pkill -f` sur le meme motif est
#  pire que cela : il envoie SIGTERM a l'appelant -- donc `stop` pouvait tuer la
#  session qui l'avait lance, et, avec un motif court comme le nom du modele,
#  n'importe quel outil de surveillance qui le mentionne sur sa ligne de commande.
#
#  D'ou cette fonction : elle rend des PID, retire la chaine d'appel et notre propre
#  groupe de processus, et `stop` arrete ensuite PAR PID. Retirer notre groupe ne peut
#  pas cacher un vrai orphelin : le service est lance sous `setsid`, donc son groupe
#  est le sien et ne peut pas etre le notre.
# ---------------------------------------------------------------------------
own_group() {   # pgid de ce script (vide si `ps` ne repond pas)
  ps -o pgid= -p $$ 2>/dev/null | tr -d ' '
}

stray_by_name() {   # $1 = motif -> un PID par ligne ; appelant et soi-meme exclus
  local pat="$1" pids p own pg
  own="$(own_group)"
  pids="$(pgrep -f "$pat" 2>/dev/null || true)"
  for p in $pids; do
    [ "$p" = "$$" ] && continue
    [ "$p" = "$PPID" ] && continue
    # Un processus que `ps` ne sait plus lire est DEJA MORT : rien a arreter. C'est le
    # cas des sous-shells transitoires de la substitution de commande ci-dessus, qui
    # portent notre propre ligne de commande le temps d'un souffle et disparaissent
    # avant qu'on les regarde (mesure : un PID rendu deja absent de /proc). Les garder
    # mettrait dans la liste des PID deja recycles par le noyau, donc tuables a tort.
    pg="$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')"
    [ -n "$pg" ] || continue
    [ -n "$own" ] && [ "$pg" = "$own" ] && continue
    printf '%s\n' "$p"
  done
}

cmd_stop() {
  info "==== arret du service vLLM -- $HOST_SHORT -- $(date -Is) ===="
  local oldpid="" stopped=0
  [[ -f "$PIDFILE" ]] && oldpid="$(cat "$PIDFILE" 2>/dev/null)"

  if pid_alive; then
    # setsid gave the service its OWN process group, whose id is the recorded
    # PID. Signalling the GROUP reaches the API server and its EngineCore child
    # together -- which is what we want, and what -$p already did.
    info "  SIGTERM vers le groupe -$oldpid"
    kill -TERM "-$oldpid" 2>/dev/null || kill -TERM "$oldpid" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$oldpid" 2>/dev/null || break; sleep 1; done
    if kill -0 "$oldpid" 2>/dev/null; then
      info "  toujours vivant apres 30s -> SIGKILL du groupe"
      kill -KILL "-$oldpid" 2>/dev/null || kill -KILL "$oldpid" 2>/dev/null
      sleep 3
    fi
    stopped=1
  elif [[ -n "$oldpid" ]]; then
    # Leader already gone but the pidfile survives: an orphaned EngineCore child
    # may still hold the GPU. Signal the group before giving up the handle.
    info "  PID $oldpid mort -- verification du groupe et des orphelins"
    kill -TERM "-$oldpid" 2>/dev/null
    sleep 2
  else
    info "  pas de PID dans $PIDFILE"
  fi

  # --- sweep 1 : the precise handle, the recorded process group ------------
  if [[ -n "$oldpid" ]]; then
    local grp
    grp="$(orphan_group "$oldpid")"
    if [[ -n "$grp" ]]; then
      info "  orphelins du groupe $oldpid : $(printf '%s' "$grp" | tr '\n' ' ')"
      # shellcheck disable=SC2086
      kill -TERM $grp 2>/dev/null
      sleep 4
      grp="$(orphan_group "$oldpid")"
      if [[ -n "$grp" ]]; then
        info "  resistants -> SIGKILL : $(printf '%s' "$grp" | tr '\n' ' ')"
        # shellcheck disable=SC2086
        kill -KILL $grp 2>/dev/null
        sleep 2
      fi
      stopped=1
    fi
  fi

  # --- sweep 2 : name patterns, for the case where the pidfile is already gone
  # Two patterns are required: the API server carries the model path, the
  # EngineCore child does not (it renames its argv). The list comes from
  # stray_by_name(), which removes our caller and our own process group before
  # anything is signalled -- see its header for the measurement that required it.
  local pat found=0 strays
  for pat in "vllm serve $MODEL_DIR" "VLLM::EngineCore"; do
    strays="$(stray_by_name "$pat" | tr '\n' ' ')"
    if [[ -n "$strays" ]]; then
      info "  orphelins correspondant a [$pat] -> arret : $strays"
      # shellcheck disable=SC2086
      kill -TERM $strays 2>/dev/null
      found=1
    fi
  done
  [[ "$found" -eq 1 ]] && { sleep 4; stopped=1; }

  rm -f "$PIDFILE"

  # --- acceptance: a manager that reports "stopped" while the GPU is still held
  # is lying. The real criterion is the RELEASE OF THE DEVICE, not the port.
  local used wa
  for wa in 1 2 3 4 5 6; do
    used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)"
    [[ -z "$used" ]] && break
    (( used < 512 )) && break
    sleep 2
  done

  if port_busy; then
    err "  ECHEC : le port $PORT repond encore. Processus :"
    ss -ltnp 2>/dev/null | grep ":$PORT " | sed 's/^/    /' >&2
    return 1
  fi

  if [[ -n "$used" ]] && (( used >= 512 )); then
    err "  ECHEC : le port $PORT est libre mais la GPU est TOUJOURS OCCUPEE"
    err "    VRAM utilisee : ${used} MiB -- le serveur a bien disparu, pas son"
    err "    enfant EngineCore. Processus detenant la GPU :"
    nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv,noheader \
      2>/dev/null | sed 's/^/      /' >&2
    return 1
  fi

  info "  port $PORT libere ; VRAM ${used:-?} MiB -- GPU rendue"
  return 0
}

cmd_status() {
  local ip; ip="$(lan_ip)"
  info "==== statut vLLM -- $HOST_SHORT -- $(date -Is) ===="
  info "  modele      : $MODEL_DIR"
  info "  nom servi   : $SERVED_NAME    port : $PORT    host : ${ip:-<inconnu>}"
  info "  profil      : gpu_util=$GPU_UTIL max_len=$MAX_LEN"
  if pid_alive; then info "  processus   : PID $(cat "$PIDFILE") (vivant)"; else info "  processus   : aucun"; fi
  if port_busy; then info "  port $PORT  : ECOUTE"; else info "  port $PORT  : libre"; fi
  if curl -sf "http://${ip:-127.0.0.1}:$PORT/v1/models" >/dev/null 2>&1; then
    info "  /v1/models  : repond"
    curl -s "http://${ip:-127.0.0.1}:$PORT/v1/models" | head -c 220 | sed 's/^/    /'; info ""
  else
    info "  /v1/models  : MUET"
  fi
  info "  GPU         : $(nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null)"
  info "  log         : $LOG ($(wc -l <"$LOG" 2>/dev/null || echo 0) lignes)"
  return 0
}

cmd_health() {
  local ip; ip="$(lan_ip)"
  info "==== health -- $HOST_SHORT ===="
  local rc=0
  curl -sf "http://${ip:-127.0.0.1}:$PORT/v1/models" >/dev/null \
    && info "  /v1/models : OK" || { err "  /v1/models : ECHEC"; rc=1; }
  local img="$IMAGE"
  if [[ -f "$img" ]]; then
    local b64; b64="$(base64 -w0 "$img")"
    local body
    # Meme squelette que node_gpu_bench.sh::build_body -- le modifier PAR PAIRE.
    body="$(printf '{"model":"%s","temperature":%s,"max_tokens":%s,"messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,%s"}},{"type":"text","text":"%s"}]}]}' \
      "$SERVED_NAME" "$TEMPER" "$MAXTOK" "$b64" "$PROMPT")"
    info "  charge      : temperature=$TEMPER max_tokens=$MAXTOK   [source: $PAYLOAD_SOURCE]"
    local out
    out="$(curl -s "http://${ip:-127.0.0.1}:$PORT/v1/chat/completions" -H 'Content-Type: application/json' -d "$body")"
    if printf '%s' "$out" | grep -q '"content"'; then
      info "  requete image : OK"
      printf '%s' "$out" | sed -n 's/.*"content"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/    \1/p' | head -3 | cut -c1-150
    else
      err "  requete image : ECHEC"; err "    $(printf '%s' "$out" | head -c 300)"; rc=1
    fi
  else
    info "  requete image : ignoree ($img absent)"
  fi
  return "$rc"
}

case "${1:-status}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; sleep 3; cmd_start ;;
  status)  cmd_status ;;
  health)  cmd_health ;;
  logs)    tail -n "${2:-60}" "$LOG" ;;
  wait)    cmd_wait ;;
  *) err "usage: $0 start|stop|restart|status|health|logs|wait [n]"; exit 64 ;;
esac
