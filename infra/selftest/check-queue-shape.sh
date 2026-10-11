#!/bin/bash
# =============================================================================
#  check-queue-shape.sh -- la FORME de la file, pas seulement sa moyenne
# =============================================================================
#  POURQUOI (mesure du 2026-09-28)
#  -------------------------------
#  `MODE=sweep` publiait la file d'attente comme un seul nombre : `file moy=`. Or, a 96 et
#  128 req/noeud, des requetes ATTENDENT (jusqu'a 26 en attente, cache KV plein a 100 %)
#  alors que la moyenne reste a 0.0002 puis 0.0017 s. Une moyenne par requete dilue un pic
#  court : elle repond « combien de temps perdu en moyenne », jamais « quelqu'un
#  a-t-il attendu ». Le cas `un-seul-attendant` ci-dessous rend cela chiffre -- 999
#  requetes sans attente et UNE a 0,29 s donnent une moyenne de 0,00029 s, soit exactement
#  ce qu'une file vide afficherait, alors que 290 ms ont bel et bien ete perdues.
#
#  CE QUE LE CORRECTIF AJOUTE (v6), ET CE QUE CE FICHIER VERIFIE
#  ------------------------------------------------------------
#   * `total` = SUM, la somme EXACTE des attentes. Toute attente etant >= 0, aucune requete
#     ne peut depasser le total : c'est une borne superieure RIGOUREUSE du maximum, et elle
#     ne suppose rien sur la forme de la distribution. C'est ce qui rend visible le cas a
#     un seul attendant, que les buckets ne peuvent PAS resoudre (ils commencent a 0,3 s).
#   * `max` = l'intervalle de bucket qui contient le maximum.
#   * `>0.3s` = la part des requetes ayant franchi la plus petite borne finie publiee.
#
#  La verite est calculee en Python a partir des valeurs, jamais re-derivee du meme chemin
#  que les fonctions testees. Les valeurs sont converties en compteurs CUMULATIFS absolus,
#  puis differentiees par l'instrument : c'est ce chemin-la qui est mesure.
#
#  usage : bash check-queue-shape.sh        sortie 0 si tout tient, 1 sinon.
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BENCH="${BENCH_SCRIPT:-$ROOT/infra/scripts/node_gpu_bench.sh}"

[ -f "$BENCH" ] || { echo "instrument introuvable : $BENCH" >&2; exit 2; }

FAIL=0
ok()  { echo "  OK    $*"; }
bad() { echo "  ECHEC $*"; FAIL=1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------------------------------ extraction
# Meme regle que check-metrics-math.sh : de « nom() { » a la premiere ligne « } ».
extract() {
  awk -v f="$1" '
    $0 ~ "^" f "\\(\\)" { on = 1 }
    on { print }
    on && $0 == "}" { exit }' "$BENCH"
}
FUNCS="$TMP/funcs.sh"
: > "$FUNCS"
for f in metrics_delta metrics_sum metrics_maxbracket metrics_over metrics_mean; do
  extract "$f" >> "$FUNCS"; echo >> "$FUNCS"
  grep -q "^$f()" "$FUNCS" || { echo "extraction : $f absente de $BENCH" >&2; exit 2; }
done
if ! bash -n "$FUNCS" 2> "$TMP/funcs.err"; then
  echo "INSTRUMENT INVALIDE : les fonctions extraites ne sont pas du shell valide" >&2
  sed 's/^/  /' "$TMP/funcs.err" >&2
  exit 2
fi
echo "instrument : $BENCH"
echo "extrait    : 5 fonctions ($(wc -l < "$FUNCS") lignes)"
echo

# ------------------------------------------------------------------ cas
python3 - "$TMP" <<'PY'
import os, random, sys

OUT = sys.argv[1]
METRIC = "request_queue_time_seconds"
# Bornes REELLES de cette metrique, relevees sur /metrics le 2026-09-28 : la plus petite
# est 0,3 s -- c'est elle qui fixe ce que des buckets peuvent voir, et donc la borne
# au-dessus de laquelle on compte.
LABELS = ["0.3", "0.5", "0.8", "1.0", "1.5", "2.0", "2.5", "5.0", "10.0", "15.0",
          "20.0", "30.0", "40.0", "50.0", "60.0", "120.0", "240.0", "480.0", "960.0",
          "1920.0", "7680.0"]
EDGE = 0.3


def counters(base, win):
    """Compteurs CUMULATIFS absolus : `base` requetes deja passees, plus la fenetre."""
    vals = list(base) + list(win)
    return {
        "buckets": {b: sum(1 for x in vals if x <= float(b)) for b in LABELS},
        "inf": len(vals), "count": len(vals), "sum": sum(vals),
    }


def render(st):
    out = ['vllm:%s_bucket{engine="0",le="%s",model_name="m"} %s'
           % (METRIC, b, float(st["buckets"][b])) for b in LABELS]
    out.append('vllm:%s_bucket{engine="0",le="+Inf",model_name="m"} %s' % (METRIC, float(st["inf"])))
    out.append('vllm:%s_sum{engine="0",model_name="m"} %s' % (METRIC, st["sum"]))
    out.append('vllm:%s_count{engine="0",model_name="m"} %s' % (METRIC, float(st["count"])))
    return "\n".join(out) + "\n"


def expected(win):
    """Verite : somme, encadrement du max, et compte au-dessus du seuil."""
    n = len(win)
    s = sum(win)
    mx = max(win) if win else 0.0
    # Plus petite borne dont le cumul atteint n : elle porte le maximum.
    lo, hi = 0.0, None
    for b in sorted(LABELS, key=float):
        if sum(1 for x in win if x <= float(b)) >= n:
            hi = float(b); break
        lo = float(b)
    if hi is None:
        bracket = ">%.3f" % lo
    else:
        bracket = "(%.3f;%.3f]" % (lo, hi)
    over = sum(1 for x in win if x > EDGE)
    return {"n": n, "sum": s, "max": mx, "bracket": bracket,
            "over": over, "pct": (100.0 * over / n) if n else 0.0}


CASES = []


def emit(name, desc, base, win):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "before"), "w").write(render(counters([], base)))
    open(os.path.join(d, "after"), "w").write(render(counters(base, win)))
    e = expected(win)
    e["desc"] = desc
    CASES.append((name, e))


# --- 1. le cas qui a motive le correctif -------------------------------------
# 999 requetes sans attente, UNE a 0,29 s. La moyenne vaut 0,00029 s : exactement ce
# qu'une file vide afficherait. Les buckets ne peuvent pas la voir non plus (le premier
# vaut 0,3 s, et 0,29 <= 0,3). Seul le TOTAL la montre.
emit("un-seul-attendant",
     "999 sans attente + une a 0,29 s : la moyenne ment, le total non",
     [], [0.0] * 999 + [0.29])

# --- 2. file franchement visible ---------------------------------------------
# 26 requetes au-dela de 0,3 s : les trois nombres doivent le dire.
emit("vingt-six-attendants",
     "26 requetes entre 0,3 et 0,5 s : max, total et part doivent tous le voir",
     [0.0] * 742, [0.41] * 26)

# --- 3. file vide -------------------------------------------------------------
emit("file-vide", "toutes les requetes sans attente : les trois nombres a zero",
     [0.0] * 500, [0.0] * 500)

# --- 4. queue longue ----------------------------------------------------------
emit("une-attente-longue", "une seule requete a 2,0 s : encadrement (1.5;2.0]",
     [0.0] * 300, [0.0] * 299 + [2.0])

# --- 5. valeur PILE sur une borne --------------------------------------------
# `metrics_over` compte STRICTEMENT au-dessus : une requete a exactement 0,3 s n'est pas
# comptee, ce qui doit correspondre au bucket `le="0.3"` qui l'inclut.
emit("pile-sur-la-borne", "valeurs exactement egales aux bornes : le compte doit suivre le bucket",
     [], [0.0] * 10 + [0.3] * 5 + [0.5] * 3 + [0.8] * 2)

# --- 6. passe non vide --------------------------------------------------------
# Un instantane AVANT non nul : la fonction travaille sur le delta, pas sur l'absolu.
emit("passe-non-vide", "passe deja comptabilisee : le delta doit l'annuler",
     [0.0] * 400 + [1.2] * 7, [0.0] * 120 + [0.6] * 9)

# --- 7..206. aleatoire, graine fixe ------------------------------------------
rnd = random.Random(20260928)


def draw():
    n = rnd.choice([1, 2, 5, 40, 300, 900, 2000])
    kind = rnd.randrange(6)
    if kind == 0:
        return [0.0] * n
    if kind == 1:
        return [0.0] * (n - 1) + [rnd.uniform(0.0, 0.3)]
    if kind == 2:
        return [0.0] * (n - 1) + [rnd.choice([0.4, 1.1, 3.0, 7.0, 200.0])]
    if kind == 3:
        return [rnd.uniform(0.0, 0.3) for _ in range(n)]
    if kind == 4:
        return [rnd.choice([0.0, 0.3, 0.5, 0.8, 1.0, 2.6, 12.0]) for _ in range(n)]
    return [rnd.uniform(0.0, 30.0) for _ in range(n)]


for i in range(200):
    win = draw()
    base = draw() if i % 3 == 0 else []
    emit("alea-%03d" % i, "aleatoire (graine 20260928)", base, win)

with open(os.path.join(OUT, "cases.tsv"), "w") as fh:
    for name, e in CASES:
        fh.write("\t".join([name, str(e["n"]), "%.6f" % e["sum"], e["bracket"],
                            str(e["over"]), "%.6f" % e["max"], "%.6f" % e["pct"],
                            e["desc"]]) + "\n")
print("cas generes : %d" % len(CASES))
PY
gen_rc=$?
[ "$gen_rc" = 0 ] || { echo "GENERATION EN ECHEC (rc=$gen_rc)" >&2; exit 1; }
echo "cas        : $(grep -c . "$TMP/cases.tsv")"
echo

# ------------------------------------------------------------------ execution
# Le lanceur vit dans un FICHIER : les programmes awk contiennent guillemets simples et
# `$`, et les re-echapper dans une commande ferait courir un code different de l'instrument.
cat > "$TMP/run-one.sh" <<'EOS'
set -u
. "$FUNCS"
d="$1"
printf 'SUM\t%s\n' "$(metrics_sum "$d/before" "$d/after" request_queue_time_seconds)"
printf 'MAXB\t%s\n' "$(metrics_maxbracket "$d/before" "$d/after" request_queue_time_seconds)"
printf 'OVER\t%s\n' "$(metrics_over "$d/before" "$d/after" request_queue_time_seconds 0.3 | awk '/^OVER /{print $2}')"
printf 'PCT\t%s\n' "$(metrics_over "$d/before" "$d/after" request_queue_time_seconds 0.3 | awk '/^PCT /{print $2}')"
printf 'MEAN\t%s\n' "$(metrics_mean "$d/before" "$d/after" request_queue_time_seconds)"
EOS

: > "$TMP/actual.tsv"
while IFS=$'\t' read -r name n sum bracket over max pct desc; do
  out="$(FUNCS="$FUNCS" bash "$TMP/run-one.sh" "$TMP/$name")"
  a_sum="$(printf '%s\n' "$out" | awk -F'\t' '/^SUM\t/{print $2}')"
  a_maxb="$(printf '%s\n' "$out" | awk -F'\t' '/^MAXB\t/{print $2}')"
  a_over="$(printf '%s\n' "$out" | awk -F'\t' '/^OVER\t/{print $2}')"
  a_mean="$(printf '%s\n' "$out" | awk -F'\t' '/^MEAN\t/{print $2}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$name" "$n" "$sum" "$bracket" "$over" "$max" "$a_sum" "$a_maxb" >> "$TMP/actual.tsv"
  # Les nombres restent disponibles pour les controles cibles ci-dessous.
  printf '%s\t%s\t%s\t%s\n' "$name" "$a_over" "$a_mean" "$pct" >> "$TMP/aux.tsv"
done < "$TMP/cases.tsv"

# ------------------------------------------------------------------ comparaison
n_ok=0; n_cmp=0
while IFS=$'\t' read -r name exp_n exp_sum exp_bracket exp_over exp_max a_sum a_maxb; do
  # 1. la somme EXACTE
  n_cmp=$((n_cmp + 1))
  if awk -v a="$a_sum" -v e="$exp_sum" 'BEGIN{d=a-e; if(d<0)d=-d; exit !(d<1e-6)}'; then
    n_ok=$((n_ok + 1))
  else
    bad "$name : somme $a_sum, attendu $exp_sum"
  fi
  # 2. l'encadrement CONTIENT le maximum, et il est serre
  n_cmp=$((n_cmp + 1))
  if [ "$a_maxb" = "$exp_bracket" ]; then
    n_ok=$((n_ok + 1))
  else
    bad "$name : encadrement du max '$a_maxb', attendu '$exp_bracket' (max reel $exp_max)"
  fi
  # 3. l'INEGALITE qui fait tout l'interet du total : max <= somme
  n_cmp=$((n_cmp + 1))
  if awk -v s="$a_sum" -v m="$exp_max" 'BEGIN{exit !(m <= s + 1e-6)}'; then
    n_ok=$((n_ok + 1))
  else
    bad "$name : max $exp_max > total $a_sum -- la borne superieure est fausse"
  fi
done < "$TMP/actual.tsv"

# 4. le compte au-dessus du seuil, exact pour un seuil qui EST une borne
while IFS=$'\t' read -r name exp_n exp_sum exp_bracket exp_over exp_max a_sum a_maxb; do
  a_over="$(awk -F'\t' -v n="$name" '$1==n{print $2}' "$TMP/aux.tsv")"
  n_cmp=$((n_cmp + 1))
  if [ "$a_over" = "$exp_over" ]; then
    n_ok=$((n_ok + 1))
  else
    bad "$name : au-dessus de 0,3 s = $a_over, attendu $exp_over"
  fi
done < "$TMP/actual.tsv"

echo "comparaisons : $n_ok / $n_cmp"
echo

# ------------------------------------------------------------------ le cas temoin
echo "--- le cas qui a motive le correctif : un-seul-attendant ---"
mean="$(awk -F'\t' '$1=="un-seul-attendant"{print $3}' "$TMP/aux.tsv")"
total="$(awk -F'\t' '$1=="un-seul-attendant"{print $7}' "$TMP/actual.tsv")"
bracket="$(awk -F'\t' '$1=="un-seul-attendant"{print $8}' "$TMP/actual.tsv")"
echo "  moyenne publiee par la version d'avant (v5) : ${mean}s"
echo "  total ajoute par v6                        : ${total}s"
echo "  encadrement du max ajoute par v6           : ${bracket}"
if awk -v m="$mean" 'BEGIN{exit !(m < 0.001)}'; then
  ok "la moyenne seule (${mean}s) est indistinguable d'une file VIDE"
else
  bad "la moyenne vaut ${mean}s : le cas temoin ne montre plus ce qu'il doit montrer"
fi
if awk -v t="$total" 'BEGIN{exit !(t > 0.25)}'; then
  ok "le total (${total}s) montre qu'une requete a bien attendu ~0,29 s"
else
  bad "le total vaut ${total}s : il ne revele pas l'attente isolee"
fi
# Le bucket ne peut PAS resoudre ce cas : le max est sous la plus petite borne (0,3 s).
if [ "$bracket" = "(0.000;0.300]" ]; then
  ok "l'encadrement (0.000;0.300] dit que la resolution s'arrete a 0,3 s -- d'ou le total"
else
  bad "encadrement inattendu : $bracket"
fi
echo

# ------------------------------------------------------------------ controle negatif
# `metrics_over` ne compte que STRICTEMENT au-dessus. Une distribution entierement a
# 0,3 s -- la borne elle-meme -- ne doit donc compter AUCUNE requete, sinon le nombre
# publie contredirait le bucket `le="0.3"` qui, lui, les inclut toutes.
echo "--- controle negatif : tout pile sur la borne ---"
cat > "$TMP/at-edge" <<'EOS'
all at the edge
EOS
mkdir -p "$TMP/edge"
python3 - "$TMP/edge" <<'PY'
import sys
d = sys.argv[1]
L = ["0.3", "0.5", "1.0"]
vals = [0.3] * 50
def ren(vals):
    o = ['vllm:request_queue_time_seconds_bucket{le="%s"} %d' % (b, sum(1 for x in vals if x <= float(b))) for b in L]
    o.append('vllm:request_queue_time_seconds_bucket{le="+Inf"} %d' % len(vals))
    o.append("vllm:request_queue_time_seconds_sum %s" % sum(vals))
    o.append("vllm:request_queue_time_seconds_count %d" % len(vals))
    return "\n".join(o) + "\n"
open(d + "/before", "w").write("")
open(d + "/after", "w").write(ren(vals))
PY
edge_over="$(FUNCS="$FUNCS" bash "$TMP/run-one.sh" "$TMP/edge" | awk -F'\t' '/^OVER\t/{print $2}')"
edge_sum="$(FUNCS="$FUNCS" bash "$TMP/run-one.sh" "$TMP/edge" | awk -F'\t' '/^SUM\t/{print $2}')"
echo "  50 requetes a exactement 0,3 s -> au-dessus de 0,3 s : $edge_over (attendu 0), total $edge_sum (attendu 15.000000)"
[ "$edge_over" = "0" ] && ok "le seuil est STRICT : une valeur egale a la borne n'est pas comptee" \
                       || bad "compte=$edge_over -- attendu 0 : le seuil serait inclusif"
awk -v s="$edge_sum" 'BEGIN{exit !(s > 14.99 && s < 15.01)}' \
  && ok "le total est exact meme sans bucket au-dessus (0,3 x 50 = 15)" \
  || bad "total=$edge_sum -- attendu 15"
echo

if [ "$FAIL" = 0 ]; then
  echo "VERDICT : OK -- $n_cmp comparaisons, la forme de la file est mesuree et bornee."
else
  echo "VERDICT : ECHEC"
fi
exit "$FAIL"
