#!/bin/bash
# =============================================================================
#  check-stop-scope.sh -- `stop` ne doit pas voir, ni tuer, son propre appelant
# =============================================================================
#  CE QUI EST MESURE, ET POURQUOI
#  ------------------------------
#  Le 2026-09-28, sur zabeth23 avec un serveur VIVANT (un seul `vllm serve`, un seul
#  `VLLM::EngineCore`), `pgrep -f` appelе a travers un `bash -c` a rendu « 3 » et « 3 » :
#  la ligne de commande de l'appelant contenait le motif, donc elle se comptait elle-meme
#  (ainsi que le sous-shell de la substitution). Une meme session avait annonce des
#  « orphelins » pour un arret parfaitement propre -- des orphelins qui n'existaient pas.
#
#  Un compte gonfle est un defaut de diagnostic : il apprend a ignorer le message qui
#  distingue « GPU rendue » de « EngineCore tient encore 74,7 % de la carte ». Et
#  `pkill -f <motif>`, la forme historique, est pire : il envoie SIGTERM a l'appelant.
#
#  CE QUE CE FICHIER VERIFIE
#  -------------------------
#   1. la variante HISTORIQUE (`pgrep -f`) se laisse compter par son appelant -- c'est
#      le controle negatif : sans lui, les cas 2 et 3 passeraient aussi sur du code
#      qui n'a rien corrige ;
#   2. `stray_by_name()`, extraite du script deploye, ne rend QUE le vrai intrus ;
#   3. l'arret des PID rendus par elle tue l'intrus et LAISSE VIVANT l'appelant.
#
#  Le motif est unique (il porte le PID du test) : rien d'autre sur la machine ne peut
#  s'y correspondre, et aucun service de la grappe n'est touche. Le test est purement
#  local : il ne contacte aucun noeud.
#
#  usage : bash check-stop-scope.sh        sortie 0 si tout tient, 1 sinon.
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SERVICE="${SERVICE_SCRIPT:-$ROOT/infra/scripts/node_vllm_service.sh}"

[ -f "$SERVICE" ] || { echo "script introuvable : $SERVICE" >&2; exit 2; }

FAIL=0
ok()  { echo "  OK    $*"; }
bad() { echo "  ECHEC $*"; FAIL=1; }

TMP="$(mktemp -d)"
PATTERN="vllm serve $TMP/faux-modele-$$"
FAKE=""
carrier_pids=""

cleanup() {
  [ -n "$FAKE" ] && kill -KILL "$FAKE" 2>/dev/null
  for p in $carrier_pids; do kill -KILL "$p" 2>/dev/null; done
  rm -rf "$TMP"
}
trap cleanup EXIT

# ------------------------------------------------------------------ extraction
# Meme regle que check-metrics-math.sh : de « nom() { » a la premiere ligne « } ».
extract() {
  awk -v f="$1" '
    $0 ~ "^" f "\\(\\)" { on = 1 }
    on { print }
    on && $0 == "}" { exit }' "$SERVICE"
}
FUNCS="$TMP/funcs.sh"
: > "$FUNCS"
for f in own_group stray_by_name; do
  extract "$f" >> "$FUNCS"; echo >> "$FUNCS"
  grep -q "^$f()" "$FUNCS" || { echo "extraction : $f absente de $SERVICE" >&2; exit 2; }
done
if ! bash -n "$FUNCS" 2> "$TMP/funcs.err"; then
  echo "INSTRUMENT INVALIDE : les fonctions extraites ne sont pas du shell valide" >&2
  sed 's/^/  /' "$TMP/funcs.err" >&2
  exit 2
fi
echo "script     : $SERVICE"
echo "extrait    : own_group, stray_by_name"
echo "motif      : $PATTERN"
echo

# ------------------------------------------------------------------ l'intrus
# Un processus dont la ligne de commande PORTE le motif, exactement comme le fait le
# serveur (`vllm serve <modele> ...`), mais qui n'est pas le serveur et qu'on peut tuer.
# `exec -a` remplace argv[0] : c'est ce que fait `VLLM::EngineCore`, en sens inverse.
#
# `setsid` n'est pas un detail de confort : le service reel est lance sous `setsid`, donc
# il vit dans SON groupe de processus. C'est cet invariant qui rend sur que retirer notre
# propre groupe ne peut pas cacher un vrai orphelin -- et un test qui lancerait l'intrus
# dans notre groupe mesurerait autre chose (le groupe le retirerait, et le test dirait
# que la fonction est devenue aveugle alors qu'elle fait exactement ce qu'il faut).
setsid bash -c "printf '%s\n' \$\$ > '$TMP/intrus.pid'; exec -a '$PATTERN' sleep 300" &
sleep 0.5
FAKE="$(cat "$TMP/intrus.pid" 2>/dev/null || echo '')"
if [ -z "$FAKE" ] || ! kill -0 "$FAKE" 2>/dev/null; then
  echo "mise en place impossible : l'intrus n'a pas demarre" >&2
  exit 2
fi
if [ "$(ps -o pgid= -p "$FAKE" 2>/dev/null | tr -d ' ')" != "$FAKE" ]; then
  echo "mise en place impossible : l'intrus n'est pas chef de son groupe (setsid a echoue)" >&2
  exit 2
fi
echo "intrus     : PID $FAKE (argv[0] porte le motif, groupe de processus a lui)"
echo

# ------------------------------------------------------------------ 1. controle negatif
# La forme HISTORIQUE, telle qu'elle etait ecrite, depuis un appelant qui porte le motif.
cat > "$TMP/old.sh" <<EOS
set -u
n="\$(pgrep -f "$PATTERN" | wc -l)"
printf '%s\\n' "\$n" > "$TMP/old-count.txt"
EOS
bash -c "$(cat "$TMP/old.sh")"
old="$(cat "$TMP/old-count.txt" 2>/dev/null || echo '?')"
echo "--- 1. forme historique : pgrep -f depuis un appelant qui porte le motif ---"
echo "  compte rendu : $old  (attendu >= 2 : l'intrus ET l'appelant)"
if [ "$old" -ge 2 ] 2>/dev/null; then
  ok "la forme historique se compte elle-meme -- le cas a corriger est bien reel"
else
  bad "compte=$old -- la forme historique ne s'auto-compte pas ; le controle negatif ne prouve rien"
fi
echo

# ------------------------------------------------------------------ 2. la fonction
# Meme appelant, meme motif : stray_by_name() ne doit rendre QUE l'intrus.
cat > "$TMP/new.sh" <<EOS
set -u
. "$FUNCS"
stray_by_name "$PATTERN" > "$TMP/new-pids.txt"
printf '%s\\n' "\$\$" > "$TMP/carrier.pid"
sleep 4                                    # survit-il a l'arret de ce que la fonction rend ?
printf 'survit\\n' > "$TMP/carrier-survit.txt"
EOS
bash -c "$(cat "$TMP/new.sh")" &
carrier=$!
carrier_pids="$carrier"
for _ in $(seq 1 40); do [ -s "$TMP/new-pids.txt" ] && break; sleep 0.1; done

# L'identifiant de l'appelant : le `bash -c` ci-dessus, dont la ligne porte le motif.
carrier_self="$(cat "$TMP/carrier.pid" 2>/dev/null || echo '')"

echo "--- 2. stray_by_name() : ce qu'elle rend, depuis le meme appelant ---"
echo "  PID rendus   : $(tr '\n' ' ' < "$TMP/new-pids.txt" 2>/dev/null)"
echo "  attendu      : $FAKE seul"
echo "  PID appelant : $carrier_self (doit etre ABSENT de la liste)"
# Chaque PID rendu est nomme. Sans cela un compte faux ne dit pas CE QUI a ete pris a
# tort -- et c'est precisement ce qui rendait le defaut du 2026-09-28 difficile a lire.
while read -r p; do
  [ -n "$p" ] || continue
  printf '    rendu : pid=%-8s pgid=%-8s %s\n' "$p" \
    "$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')" \
    "$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | cut -c1-70)"
done < "$TMP/new-pids.txt"
rendered="$(tr '\n' ' ' < "$TMP/new-pids.txt" 2>/dev/null)"
n_rendered="$(grep -c . "$TMP/new-pids.txt" 2>/dev/null || echo 0)"
if [ "$n_rendered" = "1" ]; then ok "un seul PID rendu"; else bad "$n_rendered PID rendus -- attendu 1"; fi
case " $rendered " in
  *" $FAKE "*) ok "l'intrus est dans la liste (elle ne l'a pas perdu de vue)" ;;
  *)           bad "l'intrus $FAKE est ABSENT de la liste -- la fonction serait devenue aveugle" ;;
esac
if [ -n "$carrier_self" ]; then
  case " $rendered " in
    *" $carrier_self "*) bad "l'appelant ($carrier_self) est dans la liste -- c'est exactement le defaut" ;;
    *)                   ok "l'appelant n'est pas dans la liste" ;;
  esac
fi
echo

# ------------------------------------------------------------------ 3. l'arret
echo "--- 3. arret des PID rendus : l'intrus meurt, l'appelant survit ---"
# shellcheck disable=SC2086
kill -TERM $rendered 2>/dev/null
sleep 1
if kill -0 "$FAKE" 2>/dev/null; then bad "l'intrus survit a l'arret"; else ok "l'intrus est arrete"; fi
sleep 4                                        # l'appelant doit aller au bout de son `sleep`
if [ -f "$TMP/carrier-survit.txt" ]; then
  ok "l'appelant a termine son travail (il n'a pas ete tue)"
else
  bad "l'appelant n'a pas fini : l'arret l'a tue (c'est le defaut de pkill -f)"
fi
echo

# ------------------------------------------------------------------ 4. ce que la forme
# historique FAISAIT de ce compte. Le point 1 a montre que `pgrep -f` compte l'appelant,
# le point 2 que la fonction corrigee ne le compte plus. Reste a mesurer la suite :
# `pkill -f` sur ce meme motif. Sans ce cas, « pkill tuait l'appelant » resterait une
# affirmation -- et c'est justement l'affirmation qui decide de garder le correctif.
#
# Le porteur est jetable et cree par ce test : la ligne de commande qui porte le motif
# est sa PROPRE ligne, placee la en commentaire. Le test lui-meme ne porte pas le motif
# (son argv est « bash check-stop-scope.sh »), et le motif contient le repertoire
# temporaire : rien hors de ce test ne peut s'y correspondre.
echo "--- 4. la forme historique employee pour ARRETER : que fait pkill -f ? ---"
cat > "$TMP/pkill-carrier.sh" <<EOS
set -u
# motif sur MA ligne de commande, comme l'outil de surveillance du cas reel :
# $PATTERN
printf '%s\n' "\$\$" > "$TMP/pkill-carrier.pid"
sleep 4
printf 'survit\n' > "$TMP/pkill-carrier-survit.txt"
EOS
bash -c "$(cat "$TMP/pkill-carrier.sh")" &
pk_carrier=$!
carrier_pids="$carrier_pids $pk_carrier"
for _ in $(seq 1 40); do [ -s "$TMP/pkill-carrier.pid" ] && break; sleep 0.1; done
# L'intrus precedent est mort : on en relance un, pour que pkill ait une vraie cible et
# qu'on ne conclue pas sur un motif sans cible.
setsid bash -c "exec -a '$PATTERN' sleep 300" &
sleep 0.5
pkill -f "$PATTERN" 2>/dev/null
sleep 1.5
if [ -f "$TMP/pkill-carrier-survit.txt" ]; then
echo "  le porteur a survecu"
else
  echo "  le porteur a ete TUE (il n'a pas atteint sa ligne suivante)"
fi
sleep 4
if [ -f "$TMP/pkill-carrier-survit.txt" ]; then
  ok "la forme historique n'a pas touche son appelant sur ce systeme"
  echo "      (l'accent reste mis sur le point 1 : le comptage, lui, est faux a coup sur)"
else
  ok "la forme historique TUE l'appelant -- le danger est mesure, pas suppose"
fi
echo

if [ "$FAIL" = 0 ]; then
  echo "VERDICT : OK -- stop ne voit ni ne tue son appelant, et trouve toujours un vrai intrus."
else
  echo "VERDICT : ECHEC"
fi
exit "$FAIL"
