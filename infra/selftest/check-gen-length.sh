#!/bin/bash
# =============================================================================
#  check-gen-length.sh -- les deux fonctions de la LONGUEUR GENEREE (v9)
# =============================================================================
#  POURQUOI
#  --------
#  La v9 publie, par palier, la longueur REELLEMENT generee et sa repartition. Deux
#  fonctions y servent, et elles sont extraites du banc -- jamais recopiees -- pour
#  que le controle porte sur le code deploye :
#     bracket_bound()   -- lire une borne dans un intervalle "(a;b]" / "[a;b]" / ">a"
#     metrics_counter() -- delta d'un COMPTEUR a etiquettes, avec filtre optionnel
#
#  Les cas sont choisis pour couvrir ce qui a DEJA fait echouer ce projet :
#     * un nom de metrique qui est un PREFIXE d'un autre (`..._total` / `..._total_extra`) ;
#     * un instantane AVANT VIDE (l'idiome `FNR == NR` le lisait comme la reference) ;
#     * une borne inconnue ou un intervalle illisible, qui doivent rendre NA et non 0 ;
#     * le filtre de ligne, qui doit compter une seule raison de fin.
#
#  usage : bash selftest/check-gen-length.sh
# =============================================================================
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BENCH="$HERE/../scripts/node_gpu_bench.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  OK    %s\n' "$1"; }
ko()   { fail=$((fail+1)); printf '  ECHEC %s\n' "$1"; }
same() { if [ "$2" = "$3" ]; then ok "$1 ($3)"; else ko "$1 : attendu '$3', obtenu '$2'"; fi; }

[ -f "$BENCH" ] || { echo "banc introuvable : $BENCH" >&2; exit 2; }

# --- extraction : du "nom()" jusqu'a la premiere ligne qui est exactement "}" --------
extract() {
  awk -v f="$1" '
    index($0, f "()") == 1 { on = 1 }
    on { print }
    on && $0 == "}" { exit }' "$BENCH"
}

bracket_bound="$(extract bracket_bound)"
metrics_counter="$(extract metrics_counter)"
if [ -z "$metrics_counter" ] || [ -z "$bracket_bound" ]; then
  echo "extraction impossible (bracket_bound ou metrics_counter). Le banc a-t-il ete renomme ?" >&2
  exit 2
fi

# Les deux extraits sont evalues dans un sous-shell a nous : ils ne doivent rien
# attendre du reste du banc (ni URLS, ni fichier d'instantane).
eval "$bracket_bound"
eval "$metrics_counter"
bash -n <(cat <<<"$bracket_bound") 2>/dev/null && ok "bracket_bound est du shell valide"
bash -n <(cat <<<"$metrics_counter") 2>/dev/null && ok "metrics_counter est du shell valide"

echo
echo "--- bracket_bound : lire une borne sans inventer ---"
same "intervalle ferme, borne basse"  "$(bracket_bound '(1.000;2.500]' lo)" '1.000'
same "intervalle ferme, borne haute"  "$(bracket_bound '(1.000;2.500]' hi)" '2.500'
same "intervalle carre"               "$(bracket_bound '[0.080;0.100]' lo)" '0.080'
same "intervalle carre, hi"           "$(bracket_bound '[0.080;0.100]' hi)" '0.100'
same "ouvert vers le haut, lo"        "$(bracket_bound '>0.300' lo)"       '0.300'
same "ouvert vers le haut, hi"        "$(bracket_bound '>0.300' hi)"       '0.300'
same "NA rend NA"                     "$(bracket_bound 'NA' lo)"           'NA'
same "chaine vide rend NA"            "$(bracket_bound '' lo)"             'NA'
same "illisible rend NA (pas 0)"      "$(bracket_bound '(abc;def]' lo)"    'NA'
same "asymetrique : hi absent -> lo"  "$(bracket_bound '[3.000]' hi)"       '3.000'

echo
echo "--- metrics_counter : delta d'un compteur, filtre, et pieges de nom ---"
cat > "$TMP/before" <<'EOF'
vllm:generation_tokens_total{engine="0",model_name="m"} 1000
vllm:generation_tokens_total{engine="1",model_name="m"} 500
vllm:request_success_total{finished_reason="stop",engine="0"} 70
vllm:request_success_total{finished_reason="length",engine="0"} 30
# un nom dont le notre est le PREFIXE : ne doit JAMAIS etre compte
vllm:generation_tokens_total_extra{engine="0"} 999999
EOF
cat > "$TMP/after" <<'EOF'
vllm:generation_tokens_total{engine="0",model_name="m"} 1750
vllm:generation_tokens_total{engine="1",model_name="m"} 750
vllm:request_success_total{finished_reason="stop",engine="0"} 74
vllm:request_success_total{finished_reason="length",engine="0"} 66
vllm:generation_tokens_total_extra{engine="0"} 999999
EOF

same "somme des series (2 moteurs)"      "$(metrics_counter "$TMP/before" "$TMP/after" generation_tokens_total)" '1000'
same "filtre d'une seule raison"         "$(metrics_counter "$TMP/before" "$TMP/after" request_success_total 'finished_reason="length"')" '36'
same "sans filtre : somme des raisons"   "$(metrics_counter "$TMP/before" "$TMP/after" request_success_total)" '40'
same "prefixe commun NON compte"         "$(metrics_counter "$TMP/before" "$TMP/after" generation_tokens_total_extra)" '0'
same "metrique absente -> 0"             "$(metrics_counter "$TMP/before" "$TMP/after" totalement_absente)" '0'

: > "$TMP/empty"
same "AVANT vide : delta = apres"        "$(metrics_counter "$TMP/empty" "$TMP/after" request_success_total 'finished_reason="length"')" '66'
same "APRES vide : delta negatif (le signal)" "$(metrics_counter "$TMP/before" "$TMP/empty" request_success_total)" '-100'

echo
if [ "$fail" -eq 0 ]; then
  echo "VERDICT : OK -- $pass cas. La longueur publiee est lue, filtree, et non inventee."
else
  echo "VERDICT : $fail ECHEC(S) sur $((pass+fail)) cas."
  exit 1
fi
