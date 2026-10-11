#!/bin/bash
# =============================================================================
#  check-no-vllm-telemetry.sh -- le service ne doit pas appeler la maison
# =============================================================================
#  CE QUI A ETE MESURE, ET COMMENT
#  -------------------------------
#  Le 2026-09-29, l'instrument `evidence/2026-09-28/risk-probes/tiered-and-retention/
#  egress-attrib-uid.sh` a enregistre, pour chaque paquet HORS-CAMPUS, le triplet
#  (adresse . port . uid de l'emetteur). Fenetre « demarrage », sur zabeth22, avec un
#  redemarrage REEL du service :
#
#      tcp6  -- 2606:4700:3032::6815:58f5 . 443 . 10131
#
#  uid 10131 est le compte du service ; les trois noeuds resolvent `stats.vllm.ai`
#  vers EXACTEMENT cette adresse. Le paquet vient donc de vLLM lui-meme, qui poste
#  par defaut un « usage heartbeat » au demarrage du moteur :
#
#      vllm/envs.py       : VLLM_USAGE_STATS_SERVER = "https://stats.vllm.ai"
#      vllm/usage/usage_lib.py:268 : client.post(_USAGE_STATS_SERVER, json=data)
#
#  POURQUOI CE FICHIER EXISTE. Deux conclusions publiees avant cette mesure sont
#  tombees avec elle :
#    * « l'inference n'emet rien hors-LAN » etait VRAI -- mais mesure sur un service
#      deja chaud, donc dans une fenetre ou le chemin de demarrage ne s'execute pas ;
#    * « aucun uid du service n'emet » etait plus large que ce qui avait ete mesure.
#  Une propriete qu'aucun controle ne regarde derive en silence : c'est exactement
#  l'argument du capteur de co-locataire de node_golden_check.sh. Ce selftest rend
#  la propriete re-verifiable et, surtout, il ECHOUE si l'opt-out disparait.
#
#  CE QU'IL VERIFIE (local, ne contacte aucun noeud)
#  ------------------------------------------------
#   1. le script de service porte l'opt-out par variable (`VLLM_NO_USAGE_STATS=1`) ;
#   2. il le porte AUSSI par fichier (`$HOME/.config/vllm/do_not_track`), pour couvrir
#      un `vllm` lance a la main par le compte du service ;
#   3. ces deux lignes sont DANS le chemin de lancement -- entre l'export du PATH et
#      la ligne `nohup setsid` qui demarre le moteur -- et non dans une branche morte ;
#   4. CONTROLE NEGATIF : sur une copie du script privee de l'opt-out, la meme analyse
#      doit ECHOUER. Sans ce controle, un test qui ne sait pas echouer ne prouve rien.
#
#  usage : bash check-no-vllm-telemetry.sh        sortie 0 si tout tient, 1 sinon.
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SERVICE="${SERVICE_SCRIPT:-$ROOT/infra/scripts/node_vllm_service.sh}"
LAUNCHER="${LAUNCHER_SCRIPT:-$ROOT/infra/scripts/start_qwen_all.sh}"

[ -f "$SERVICE" ] || { echo "script introuvable : $SERVICE" >&2; exit 2; }
[ -f "$LAUNCHER" ] || { echo "launcher introuvable : $LAUNCHER" >&2; exit 2; }

FAIL=0
ok()  { echo "  OK    $*"; }
bad() { echo "  ECHEC $*"; FAIL=1; }

# Analyse une copie du script : rend 0 si l'opt-out est present ET dans le chemin de
# lancement. Utilisee deux fois (le fichier reel, puis une copie mutilee).
analyse() {
  local f="$1" lvar lfile lpath llaunch
  lvar="$(grep -n 'VLLM_NO_USAGE_STATS=1' "$f" | head -1 | cut -d: -f1)"
  lfile="$(grep -n 'do_not_track' "$f" | head -1 | cut -d: -f1)"
  lpath="$(grep -n 'export PATH=' "$f" | head -1 | cut -d: -f1)"
  llaunch="$(grep -n 'nohup setsid' "$f" | head -1 | cut -d: -f1)"
  [ -n "$lvar" ] && [ -n "$lfile" ] && [ -n "$lpath" ] && [ -n "$llaunch" ] || return 1
  # les deux opt-out doivent etre apres l'export du PATH et avant le demarrage
  [ "$lvar" -gt "$lpath" ] && [ "$lvar" -lt "$llaunch" ] || return 1
  [ "$lfile" -gt "$lpath" ] && [ "$lfile" -lt "$llaunch" ] || return 1
  return 0
}

analyse_launcher() {
  local f="$1" lvar lfile llaunch
  lvar="$(grep -n 'VLLM_NO_USAGE_STATS=1' "$f" | head -1 | cut -d: -f1)"
  lfile="$(grep -n 'do_not_track' "$f" | head -1 | cut -d: -f1)"
  llaunch="$(grep -n 'nohup "\$VLLM_BIN"' "$f" | head -1 | cut -d: -f1)"
  [ -n "$lvar" ] && [ -n "$lfile" ] && [ -n "$llaunch" ] || return 1
  [ "$lvar" -lt "$llaunch" ] && [ "$lfile" -lt "$llaunch" ] || return 1
  return 0
}

echo "--------------------------------------------------------------------------"
echo " selftest : pas de telemetrie vLLM (stats.vllm.ai) depuis le service"
echo " script   : $SERVICE"
echo " launcher : $LAUNCHER"
echo "--------------------------------------------------------------------------"

if analyse "$SERVICE"; then
  ok "opt-out present dans service, dans le chemin de lancement (variable + fichier)"
else
  bad "opt-out absent ou hors du chemin de lancement dans service"
fi

if analyse_launcher "$LAUNCHER"; then
  ok "opt-out present dans launcher cluster (variable + fichier avant vllm serve)"
else
  bad "opt-out absent ou hors du chemin de lancement dans launcher cluster"
fi

# Controle negatif : un script sans l'opt-out DOIT echouer.
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
sed -e '/VLLM_NO_USAGE_STATS=1/d' -e '/do_not_track/d' "$SERVICE" > "$TMP"
if analyse "$TMP"; then
  bad "controle negatif : un script sans opt-out passe -- le test ne sait pas echouer"
else
  ok "controle negatif : sans opt-out, l'analyse echoue (le test sait echouer)"
fi

# Le fichier est-il bien celui que vLLM lit ? VLLM_CONFIG_ROOT = $HOME/.config/vllm
if grep -q 'HOME/.config/vllm' "$SERVICE"; then
  ok "le fichier est ecrit sous \$HOME/.config/vllm (VLLM_CONFIG_ROOT mesure)"
else
  bad "chemin du fichier do_not_track inattendu"
fi

echo "--------------------------------------------------------------------------"
[ "$FAIL" -eq 0 ] && echo "  tenu." || echo "  NON TENU."
echo "--------------------------------------------------------------------------"
exit "$FAIL"
