#!/bin/bash
# =============================================================================
#  check-bench-variants.sh -- les trois boutons de la v8, et leurs fonctions
# =============================================================================
#  POURQUOI (mesure du 2026-09-28)
#  -------------------------------
#  La v8 ajoute au banc trois choses qui decident toutes du REGIME mesure :
#    * MAXTOK_SET   -- plusieurs paliers de longueur de reponse (donc g varie) ;
#    * VARY_ROTATE  -- le jeu de prefixes en circulation cesse de valoir la concurrence ;
#    * kv_peak_report / metrics_cache_rate -- le pic de cache KV et les taux de cache
#      deviennent des nombres publies.
#  Chacune peut se tromper EN SILENCE : un corps de plus ou de moins ne se voit pas, un
#  jeu de prefixes mal compte non plus, et un pic calcule sur la mauvaise fenetre donne un
#  nombre plausible. Ce fichier fixe les proprietes qui doivent tenir :
#
#    1. le DEFAUT ne bouge pas : sans bouton, un seul corps, celui de cluster.env ;
#    2. le PRODUIT est exact : images x paliers, et NVARIANTS reste le nombre d'IMAGES ;
#    3. une valeur absurde est REFUSEE bruyamment, jamais avalee ;
#    4. la geometrie de rotation melange les paliers (chaque travailleur concurrent un
#       palier different) -- c'est elle qui rend la mesure lisible ;
#    5. un pic hors fenetre n'est PAS rapporte, et une fenetre vide donne NA, pas 0 ;
#    6. un cache qui n'a rien fait donne NA, pas 0 %.
#
#  Comme le reste du harnais, les fonctions sont EXTRAITES de node_gpu_bench.sh, jamais
#  recopiees : un test qui teste sa propre copie ne prouve rien sur l'instrument.
#  L'extracteur utilise `index()` et non une regex : dans un programme awk entre
#  guillemets simples, un antislash ecrit par erreur rend le motif muet, et la fonction
#  est alors declaree absente alors qu'elle est la (vecu en ecrivant ce fichier).
#
#  usage : bash check-bench-variants.sh      (sortie 0 si tout tient, 1 sinon)
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BENCH="${BENCH_SCRIPT:-$ROOT/infra/scripts/node_gpu_bench.sh}"
[ -f "$BENCH" ] || { echo "instrument introuvable : $BENCH" >&2; exit 2; }

FAIL=0
ok()  { echo "  OK    $*"; }
bad() { echo "  ECHEC $*"; FAIL=1; }
eq()  { if [ "$2" = "$3" ]; then ok "$1 ($2)"; else bad "$1 : $2, attendu $3"; fi; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------------------------------ extraction
extract() {
  awk -v f="$1" '
    index($0, f "()") == 1 { on = 1 }
    on { print }
    on && $0 == "}" { exit }' "$BENCH"
}
FUNCS="$TMP/funcs.sh"
: > "$FUNCS"
for f in build_body_for build_body build_bodies body_index kv_peak_report \
         metrics_counter_delta metrics_cache_rate; do
  extract "$f" >> "$FUNCS"; echo >> "$FUNCS"
  grep -q "^$f()" "$FUNCS" || { echo "extraction : $f absente de $BENCH" >&2; exit 2; }
done
if ! bash -n "$FUNCS" 2> "$TMP/funcs.err"; then
  echo "INSTRUMENT INVALIDE : les fonctions extraites ne sont pas du shell valide" >&2
  sed 's/^/  /' "$TMP/funcs.err" >&2
  exit 2
fi
echo "instrument : $BENCH"
echo "extrait    : 7 fonctions ($(wc -l < "$FUNCS") lignes)"
echo

# ------------------------------------------------------------------ jeu d'essai
ASSETS="$TMP/images"; mkdir -p "$ASSETS/prefix-variants"
printf 'x' > "$ASSETS/device_clean.jpg"
# Trois variantes DISTINCTES (a, b, c) et non trois copies du meme octet : sans cela on ne
# pourrait pas verifier QUELLE variante entre dans un jeu limite, et une troncature qui
# prendrait la mauvaise image passerait inapercue.
printf 'a' > "$ASSETS/prefix-variants/v01.jpg"
printf 'b' > "$ASSETS/prefix-variants/v02.jpg"
printf 'c' > "$ASSETS/prefix-variants/v03.jpg"
ONEV="$TMP/one-variant"; mkdir -p "$ONEV"
printf 'y' > "$ONEV/v01.jpg"

# Construit les corps et resume ce qui a ete construit. Tourne en sous-shell pour que
# BODIES / NBODIES / NVARIANTS d'un cas ne contaminent pas le suivant.
probe() {
  . "$FUNCS"
  build_bodies >/dev/null 2>"$TMP/err"
  rc=$?
  if [ "$rc" = 0 ]; then
    if [ "${#BODIES[@]}" -gt 0 ]; then
      mt="$(printf '%s\n' "${BODIES[@]}" | grep -o '"max_tokens":[0-9]*' \
            | sed 's/.*://' | sort -n | uniq -c | awk '{printf "%sx%s ", $1, $2}')"
    else mt=""; fi
    # Une empreinte COURTE par corps, dans l'ordre de construction : c'est ce qui permet de
    # verifier qu'un jeu limite est bien un SOUS-ENSEMBLE du jeu complet, et du bon cote.
    local hs="" b
    for b in "${BODIES[@]}"; do hs="$hs $(printf '%s' "$b" | sha256sum | cut -c1-6)"; done
    printf 'rc=0 NBODIES=%s NVARIANTS=%s maxtok=[%s] hashes=[%s]\n' \
           "$NBODIES" "$NVARIANTS" "${mt% }" "${hs# }"
  else
    printf 'rc=%s err=%s\n' "$rc" "$(head -1 "$TMP/err")"
  fi
}
run() {  # $1 = IMG, $2 = VARY_PREFIX, $3 = VARIANT_DIR, $4 = MAXTOK_SET, $5 = VARIANT_COUNT
  ( export IMG="$1" VARY_PREFIX="$2" VARIANT_DIR="$3" MAXTOK_SET="$4" \
           VARIANT_COUNT="${5:-0}" MAXTOK=96 SERVED=m TEMPER=0 PROMPT=p
    probe )
}

echo "--- 1. le DEFAUT ne bouge pas (aucun bouton) ---"
r="$(run "$ASSETS/device_clean.jpg" 0 "" "")"
echo "  $r"
case "$r" in
  "rc=0 NBODIES=1 NVARIANTS=0 maxtok=[1x96]"*) ok "un seul corps, max_tokens=96 (celui de cluster.env)" ;;
  *) bad "le defaut a change : $r" ;;
esac

echo
echo "--- 2. MAXTOK_SET : un palier par travailleur ---"
r="$(run "$ASSETS/device_clean.jpg" 0 "" "32 96")"
echo "  $r"
case "$r" in
  "rc=0 NBODIES=2 NVARIANTS=0 maxtok=[1x32 1x96]"*) ok "2 corps, un par palier, NVARIANTS inchange" ;;
  *) bad "produit image x paliers incorrect : $r" ;;
esac

echo
echo "--- 3. VARY_PREFIX seul (3 variantes) ---"
r="$(run "$ASSETS/device_clean.jpg" 1 "$ASSETS/prefix-variants" "")"
echo "  $r"
case "$r" in
  "rc=0 NBODIES=3 NVARIANTS=3 maxtok=[3x96]"*) ok "3 corps = 3 images, toutes au palier par defaut" ;;
  *) bad "VARY_PREFIX seul incorrect : $r" ;;
esac
# Le jeu complet, garde pour verifier que le jeu LIMITE en est bien un sous-ensemble.
FULL="$r"

echo
echo "--- 4. les deux ensemble : images x paliers ---"
r="$(run "$ASSETS/device_clean.jpg" 1 "$ASSETS/prefix-variants" "16 48")"
echo "  $r"
case "$r" in
  "rc=0 NBODIES=6 NVARIANTS=3 maxtok=[3x16 3x48]"*)
    ok "3 images x 2 paliers = 6 corps, et NVARIANTS reste le nombre d'IMAGES (3)" ;;
  *) bad "produit incorrect, ou NVARIANTS confondu avec NBODIES : $r" ;;
esac

echo
echo "--- 5. VARIANT_COUNT : la TAILLE DU JEU DE PREFIXES, a concurrence fixe ---"
r="$(run "$ASSETS/device_clean.jpg" 1 "$ASSETS/prefix-variants" "" 2)"
echo "  $r"
case "$r" in
  "rc=0 NBODIES=2 NVARIANTS=2 maxtok=[2x96]"*) ok "jeu limite a 2 : 2 corps, 2 images" ;;
  *) bad "VARIANT_COUNT=2 incorrect : $r" ;;
esac
# Le point qui compte : le jeu limite doit etre un SOUS-ENSEMBLE du jeu complet, dans le
# MEME ordre. Sans cela, deux points de la courbe de retention seraient mesures sur des
# images differentes et la comparaison n'aurait pas de sens.
h_full="$(printf '%s' "$FULL" | sed 's/.*hashes=\[//; s/\].*//')"
h_two="$(printf '%s' "$r" | sed 's/.*hashes=\[//; s/\].*//')"
h_expect="$(printf '%s' "$h_full" | cut -d' ' -f1-2)"
if [ -n "$h_two" ] && [ "$h_two" = "$h_expect" ]; then
  ok "jeu a 2 = les 2 PREMIERES variantes du jeu complet (meme ordre, memes octets)"
else
  bad "jeu limite != prefixe du jeu complet : [$h_two] contre [$h_expect]"
fi

r="$(run "$ASSETS/device_clean.jpg" 1 "$ASSETS/prefix-variants" "" 1)"
echo "  $r"
case "$r" in
  "rc=0 NBODIES=1 NVARIANTS=1 maxtok=[1x96]"*)
    ok "VARIANT_COUNT=1 est LEGAL : un seul prefixe en rotation = le regime a prefixe partage" ;;
  *) bad "VARIANT_COUNT=1 refuse alors qu'il est un point de controle legitime : $r" ;;
esac

echo
echo "--- 6. VARIANT_COUNT hors bornes : refus bruyant, jamais une troncature muette ---"
for bad_n in 99 -1 abc; do
  r="$(run "$ASSETS/device_clean.jpg" 1 "$ASSETS/prefix-variants" "" "$bad_n")"
  case "$r" in
    rc=0*) bad "VARIANT_COUNT='$bad_n' ACCEPTE : $r" ;;
    *JEU_DE_PREFIXES_IMPOSSIBLE*|*VARIANT_COUNT_INVALIDE*)
      ok "VARIANT_COUNT='$bad_n' refuse : $(echo "$r" | sed 's/.*err=//')" ;;
    *) bad "VARIANT_COUNT='$bad_n' refuse mais sans message clair : $r" ;;
  esac
done

echo
echo "--- 7. les valeurs absurdes sont REFUSEES, pas avalees ---"
for bad_set in "abc" "0" "16 x" "-8"; do
  r="$(run "$ASSETS/device_clean.jpg" 0 "" "$bad_set")"
  case "$r" in
    rc=0*) bad "MAXTOK_SET='$bad_set' accepte : $r" ;;
    *PALIERS_MAXTOK_INVALIDES*) ok "MAXTOK_SET='$bad_set' refuse : $(echo "$r" | sed 's/.*err=//')" ;;
    *) bad "MAXTOK_SET='$bad_set' refuse mais sans message clair : $r" ;;
  esac
done

echo
echo "--- 8. les cas impossibles crient ---"
r="$(run "$ASSETS/device_clean.jpg" 1 "$ONEV" "")"
case "$r" in
  *PREFIXE_VARIE_IMPOSSIBLE*) ok "une seule variante : $r" ;;
  *) bad "PREFIXE_VARIE avec 1 variante non signale : $r" ;;
esac
r="$(run "$ASSETS/absente.jpg" 0 "" "")"
case "$r" in
  *IMAGE_ABSENTE*) ok "image absente signalee : $r" ;;
  *) bad "image absente non signalee : $r" ;;
esac
r="$(run "$ASSETS/device_clean.jpg" 1 "$TMP/pas-de-dossier" "")"
case "$r" in
  *PREFIXE_VARIE_IMPOSSIBLE*) ok "repertoire de variantes absent signale" ;;
  *) bad "repertoire absent non signale : $r" ;;
esac

echo
echo "--- 9. geometrie de rotation (body_index) ---"
#  La sortie de la section passe par un FICHIER et non par un tuyau, et son code de retour
#  est verifie. Avec `( ... ) | sed`, une section qui s'arrete en route (variable non liee
#  sous `set -u`, par exemple) ne publie que le message d'erreur : ni OK ni ECHEC, donc
#  FAIL reste a 0 et le script annonce « VERDICT : OK » sur des controles qui n'ont PAS eu
#  lieu. C'est la faute que ce fichier corrige ailleurs -- un controle qui passe en
#  n'ayant rien fait -- et elle s'etait produite ici meme, en ajoutant le pas v13.
#  NOTE (v13, apres coup) : la part calculee ci-dessous a d'abord ete presentee comme
#  « la prediction a tester ». Elle ne l'est pas -- le quinzieme lot l'a montree comme
#  CORRELEE a la distance de reutilisation, pas comme sa cause : un regime a partage NUL
#  et petit jeu touche 95,8 %, un regime a partage NUL et jeu de 32 touche 0 %. Ce que
#  cette section verifie reste vrai et necessaire -- au pas = concurrence, AUCUN partage
#  n'est possible a aucun instant -- mais c'est une propriete de la GEOMETRIE du banc, pas
#  une prediction du taux de touche. Le commentaire de la section dit encore le contraire.
( . "$FUNCS"
  # Le defaut du banc est le pas 1 : les cas a,b,c testent le chemin par defaut.
  VARY_STRIDE=1
  # a. chaque travailleur fait le tour complet de ses corps
  miss=0
  for bw in 0 1 2 3; do
    seen=""
    for i in $(seq 0 11); do body_index "$bw" "$i" 4; seen="$seen $BIDX"; done
    for want in 0 1 2 3; do
      case " $seen " in *" $want "*) ;; *) miss=$((miss + 1));; esac
    done
  done
  [ "$miss" = 0 ] && echo "OK    tout travailleur parcourt les 4 corps en 12 requetes" \
                  || echo "ECHEC une rotation ne couvre pas tous les corps ($miss manquant(s))"
  # b. a l'instant 0, 12 travailleurs sur 4 corps => 3 de chaque (melange EQUILIBRE)
  counts=""
  for bw in $(seq 0 11); do body_index "$bw" 0 4; counts="$counts $BIDX"; done
  echo "      indices a la 1re requete :$counts"
  bal=1
  for v in 0 1 2 3; do
    n=$(printf '%s\n' $counts | grep -c "^$v$")
    [ "$n" = 3 ] || bal=0
  done
  [ "$bal" = 1 ] && echo "OK    12 travailleurs / 4 corps = 3 par corps (pas de desequilibre)" \
                 || echo "ECHEC le melange n'est pas equilibre"
  # c. sans rotation (2e argument toujours 0), on retrouve l'ancienne formule wi % N
  same=1
  for bw in $(seq 0 15); do body_index "$bw" 0 4; [ "$BIDX" = "$((bw % 4))" ] || same=0; done
  [ "$same" = 1 ] && echo "OK    hors rotation, body_index redonne exactement wi % NBODIES" \
                  || echo "ECHEC hors rotation, body_index differe de wi % NBODIES"

  # d. LE PAS (v13) : qui peut partager un corps avec qui, EN MEME TEMPS ?
  #    La question que l'experience pose est celle-ci : au tour i+1, un travailleur
  #    redemande-t-il un corps qu'un AUTRE travailleur du meme serveur tient encore ?
  #    Si la reutilisation exige un porteur vivant (l'hypothese du voisinage), c'est la part
  #    des requetes qui PEUT toucher.
  #    ATTENTION (quinzieme lot) : cette part N'EST PAS le taux de touche et ne le predit
  #    pas -- elle lui est correlee dans ce montage. Le regime a partage nul et petit jeu
  #    touche 95,8 % ; a partage nul et jeu de 32, 0 %. Ce qui est affirme et verifie ici
  #    se limite a la geometrie : pas = concurrence => zero partage possible. Le pas change
  #    cette part, et c'est tout l'objet du bouton.
  predict() {  # $1 = pas, $2 = travailleurs par serveur, $3 = taille du jeu
    local S="$1" W="$2" V="$3" bw i j nxt hld share=0 tot=0
    for bw in $(seq 0 $((W - 1))); do
      for i in $(seq 0 15); do
        VARY_STRIDE=$S; body_index "$bw" $((i + 1)) "$V"; nxt=$BIDX
        tot=$((tot + 1))
        for j in $(seq 0 $((W - 1))); do
          [ "$j" = "$bw" ] && continue
          VARY_STRIDE=$S; body_index "$j" "$i" "$V"; hld=$BIDX
          [ "$hld" = "$nxt" ] && { share=$((share + 1)); break; }
        done
      done
    done
    printf '%s %s' "$share" "$tot"
  }
  echo "      part des requetes pouvant toucher (4 travailleurs, jeu 32) :"
  for S in 1 2 3 4; do
    read -r sh tot <<< "$(predict "$S" 4 32)"
    printf '        pas %s -> %s/%s = %s %%\n' "$S" "$sh" "$tot" \
            "$(awk -v a="$sh" -v b="$tot" 'BEGIN{printf "%.1f", 100*a/b}')"
  done
  read -r sh1 t1 <<< "$(predict 1 4 32)"
  read -r sh4 t4 <<< "$(predict 4 4 32)"
  [ "$sh1" -gt 0 ] && echo "OK    pas 1 : le voisinage existe ($sh1/$t1 requetes reprennent un corps tenu par un voisin)" \
                    || echo "ECHEC pas 1 : aucune reprise de voisin, l'experience ne testerait rien"
  # Le point de l'experience : un pas egal a la concurrence par noeud doit rendre le
  # partage IMPOSSIBLE. Si ce n'etait pas vrai, le run mesure ne serait pas un test.
  [ "$sh4" = 0 ] && echo "OK    pas 4 = concurrence : AUCUN partage possible a aucun instant (test valide)" \
                 || echo "ECHEC pas 4 : $sh4 partage(s) subsistent, le run ne testerait pas ce qu'il annonce"
) > "$TMP/sec9" 2>&1
rc9=$?
sed 's/^/  /' "$TMP/sec9"
[ "$rc9" = 0 ] || bad "la section 9 s'est arretee avant la fin (rc=$rc9) : des controles annonces n'ont pas eu lieu"

echo
echo "--- 10. kv_peak_report : fenetre, pic, endpoint ---"
KV="$TMP/kv.tsv"
: > "$KV"
for i in $(seq 0 9); do
  kv=0.10; [ "$i" = 5 ] && kv=0.90
  printf '1000.%03d\thttp://a:8000\t%s\t4\t0\n' "$i" "$kv" >> "$KV"
  kvw=0.11; [ "$i" = 3 ] && kvw=0.95
  printf '1000.%03d\thttp://b:8000\t%s\t7\t5\n' "$i" "$kvw" >> "$KV"
  printf '1000.%03d\thttp://c:8000\t0.20\t6\t0\n' "$i" >> "$KV"
done
rep="$( (. "$FUNCS"; kv_peak_report "$KV" 1000.000 1010.000) )"
echo "  fenetre complete  : $rep"
case "$rep" in
  "0.950000 http://b:8000 7 5 30 "*) ok "pic 0.95 attribue a ep2, en cours max 7, en attente max 5, 30 lectures" ;;
  *) bad "rapport inattendu : $rep" ;;
esac
rep="$( (. "$FUNCS"; kv_peak_report "$KV" 1000.000 1000.002) )"
echo "  fenetre etroite   : $rep"
# La fenetre [1000.000;1000.002] ne garde que les instants 0, 1 et 2, soit 3 lectures par
# endpoint = 9. Le pic tombe alors sur ep3 (0.20) et NON sur ep2 (0.95 plus tard) ; les
# maxima d'`en cours` (7) et d'`en attente` (5) viennent d'ep2, qui est dans la fenetre.
case "$rep" in
  "0.200000 http://c:8000 7 5 9 "*) ok "hors du pic : le maximum suit la FENETRE (0.20), pas le fichier" ;;
  *) bad "la fenetre n'est pas respectee : $rep" ;;
esac
rep="$( (. "$FUNCS"; kv_peak_report "$KV" 9000 9001) )"
echo "  fenetre vide      : $rep"
case "$rep" in
  "NA NA 0 0 0 0") ok "aucun echantillon : NA, jamais un 0 qui se lirait comme un pic nul" ;;
  *) bad "fenetre vide mal rapportee : $rep" ;;
esac

echo
echo "--- 11. compteurs de cache ---"
B="$TMP/before"; A="$TMP/after"
printf 'vllm:prefix_cache_hits_total{e="0"} 1000\nvllm:prefix_cache_queries_total{e="0"} 2000\nvllm:mm_cache_hits_total{e="0"} 0\nvllm:mm_cache_queries_total{e="0"} 0\n' > "$B"
printf 'vllm:prefix_cache_hits_total{e="0"} 1964\nvllm:prefix_cache_queries_total{e="0"} 2000\nvllm:mm_cache_hits_total{e="0"} 50\nvllm:mm_cache_queries_total{e="0"} 50\n' > "$A"
d="$( (. "$FUNCS"; metrics_counter_delta "$B" "$A" prefix_cache_hits_total) )"
eq "delta du compteur" "$d" "964"
r="$( (. "$FUNCS"; metrics_cache_rate "$B" "$A" prefix_cache) )"
# Aucune requete de PREFIXE dans la fenetre (queries 2000 -> 2000) : le taux est NA, et il
# doit l'etre -- 0 % signifierait « le cache a rate toutes ses requetes », ce qui est faux.
eq "taux de cache de prefixe" "$r" "964 0 NA"
# Un compteur QUI NE BOUGE PAS donne NA, pas 0 % : un cache qui n'a rien fait n'est pas un
# cache qui rate tout -- confondre les deux ferait publier « 0 % de reutilisation » la ou
# aucune requete n'est passee.
B2="$TMP/b2"; A2="$TMP/a2"
printf 'vllm:mm_cache_hits_total{e="0"} 7\nvllm:mm_cache_queries_total{e="0"} 7\n' > "$B2"
printf 'vllm:mm_cache_hits_total{e="0"} 107\nvllm:mm_cache_queries_total{e="0"} 107\n' > "$A2"
r="$( (. "$FUNCS"; metrics_cache_rate "$B2" "$A2" mm_cache) )"
eq "taux multimodal" "$r" "100 100 100.00"
r="$( (. "$FUNCS"; metrics_cache_rate "$B2" "$B2" mm_cache) )"
eq "meme instantane des deux cotes" "$r" "0 0 NA"

echo
if [ "$FAIL" = 0 ]; then
  echo "VERDICT : OK -- les cinq boutons (v8 + v12 + v13) font ce qu'ils annoncent, et le defaut ne bouge pas."
else
  echo "VERDICT : ECHEC"
fi
exit "$FAIL"
